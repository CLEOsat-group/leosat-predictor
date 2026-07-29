"""Diagnostic-only slew-aware quality preview for observation plans.

This module combines the existing plan-quality diagnostics with the
slew/path diagnostics from :mod:`src.observation_planner.slew_diagnostics`.
It is intentionally read-only: it must never select, remove, reorder, score
trials for selection, or otherwise modify observation-plan rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


SLEW_AWARE_QUALITY_SCORE_KIND = "diagnostic_preview"
SLEW_AWARE_SELECTION_SCORE_KIND = "slew_aware"
_MISSING_SCORE_VALUE = -1.0e12


@dataclass(frozen=True)
class SlewAwareQualityPreview:
    """Diagnostic-only preview of future slew-aware quality terms.

    Parameters
    ----------
    available : bool
        Whether the preview could be computed from both plan-quality and
        slew/path diagnostics.
    reason_unavailable : str or None
        Human-readable reason when the preview is unavailable.
    active_for_selection : bool
        Whether the plan this preview describes was actually generated with
        the ``slew_aware`` optimization objective.  This reflects the real
        per-run objective, not a fixed capability flag: the preview itself is
        always diagnostic-only and never influences selection regardless of
        this value.
    score_tuple : tuple
        Diagnostic score tuple.  It is deliberately not used by the current
        planner selection pipeline.
    score_summary : str
        Compact summary for diagnostics tables and logs.
    metrics : mapping
        Flat JSON-serializable preview metrics.
    """

    available: bool
    reason_unavailable: str | None
    active_for_selection: bool
    score_tuple: tuple[Any, ...]
    score_summary: str
    metrics: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable preview dictionary."""
        return {
            "available": bool(self.available),
            "reason_unavailable": self.reason_unavailable,
            "active_for_selection": bool(self.active_for_selection),
            "score_kind": SLEW_AWARE_QUALITY_SCORE_KIND,
            "score_tuple": list(self.score_tuple),
            "score_summary": self.score_summary,
            **dict(self.metrics),
        }


def unavailable_slew_aware_quality_preview(
    reason: str | None = None,
    *,
    active_for_selection: bool = False,
) -> dict[str, Any]:
    """Return a stable unavailable preview payload.

    Parameters
    ----------
    reason : str or None, optional
        Human-readable unavailability reason.
    active_for_selection : bool, optional
        Whether the plan this preview describes was actually generated with
        the ``slew_aware`` optimization objective.

    Returns
    -------
    dict
        JSON-serializable diagnostic preview payload.
    """
    message = str(reason or "Slew-aware quality preview unavailable.")
    return SlewAwareQualityPreview(
        available=False,
        reason_unavailable=message,
        active_for_selection=bool(active_for_selection),
        score_tuple=(),
        score_summary=message,
        metrics=_empty_preview_metrics(),
    ).to_dict()


def compute_slew_aware_quality_preview(
    *,
    quality_metrics: Mapping[str, Any] | None,
    slew_path_summary: Mapping[str, Any] | None,
    active_for_selection: bool = False,
) -> dict[str, Any]:
    """Return diagnostic-only slew-aware quality preview metrics.

    Parameters
    ----------
    quality_metrics : mapping or None
        Existing Task 31 plan-quality metrics for the already-selected plan.
    slew_path_summary : mapping or None
        Existing Task 35A/35B slew/path summary for the already-selected plan.
    active_for_selection : bool, optional
        Whether the plan this preview describes was actually generated with
        the ``slew_aware`` optimization objective.  Purely informational: the
        preview computed here is never itself used to select a plan.

    Returns
    -------
    dict
        JSON-serializable diagnostic preview.  The returned score is never used
        to select a plan in Task 35C.
    """
    active_for_selection = bool(active_for_selection)
    if not quality_metrics:
        return unavailable_slew_aware_quality_preview(
            "Plan-quality metrics are unavailable.",
            active_for_selection=active_for_selection,
        )
    if not slew_path_summary:
        return unavailable_slew_aware_quality_preview(
            "Slew/path summary is unavailable.",
            active_for_selection=active_for_selection,
        )
    if not bool(slew_path_summary.get("available")):
        reason = slew_path_summary.get("reason_unavailable") or "Slew/path diagnostics are unavailable."
        return unavailable_slew_aware_quality_preview(
            str(reason),
            active_for_selection=active_for_selection,
        )

    transition_violation_count = _safe_int(slew_path_summary.get("transition_violation_count"), default=0)
    transition_count = _safe_int(slew_path_summary.get("transition_count"), default=0)
    transition_violation_fraction = _safe_float(
        slew_path_summary.get("transition_violation_fraction"),
        default=(float(transition_violation_count) / float(transition_count) if transition_count > 0 else 0.0),
    )
    min_slack_sec = _safe_optional_float(slew_path_summary.get("min_slack_sec"))
    median_slack_sec = _safe_optional_float(slew_path_summary.get("median_slack_sec"))
    total_axis_path_deg = _safe_float(slew_path_summary.get("total_axis_path_deg"), default=0.0)
    total_estimated_slew_sec = _safe_float(slew_path_summary.get("total_estimated_slew_sec"), default=0.0)
    total_estimated_transition_sec = _safe_float(
        slew_path_summary.get("total_estimated_transition_sec"),
        default=0.0,
    )
    median_estimated_slew_sec = _safe_optional_float(slew_path_summary.get("median_estimated_slew_sec"))
    max_estimated_slew_sec = _safe_float(slew_path_summary.get("max_estimated_slew_sec"), default=0.0)

    selected_count = _safe_int(quality_metrics.get("selected_count"), default=0)
    achieved_bin_count = _safe_int(quality_metrics.get("achieved_bin_count"), default=0)
    actual_bin_count = _safe_int(quality_metrics.get("actual_bin_count"), default=0)
    bin_balance_entropy = _safe_optional_float(quality_metrics.get("bin_balance_entropy"))
    metric_range_coverage = _safe_optional_float(quality_metrics.get("metric_range_coverage"))
    satellite_dominance_ratio = _safe_optional_float(quality_metrics.get("satellite_dominance_ratio"))
    pass_dominance_ratio = _safe_optional_float(quality_metrics.get("pass_dominance_ratio"))

    transition_feasible_flag = 1 if transition_violation_count == 0 else 0
    score_tuple = (
        transition_feasible_flag,
        -transition_violation_count,
        _score_value(min_slack_sec),
        selected_count,
        achieved_bin_count,
        _score_value(bin_balance_entropy),
        _score_value(metric_range_coverage),
        -_score_value(satellite_dominance_ratio),
        -_score_value(pass_dominance_ratio),
        -total_estimated_transition_sec,
        -max_estimated_slew_sec,
        -total_axis_path_deg,
    )

    metrics = {
        "transition_violation_count": transition_violation_count,
        "transition_violation_fraction": transition_violation_fraction,
        "min_slack_sec": min_slack_sec,
        "median_slack_sec": median_slack_sec,
        "total_axis_path_deg": total_axis_path_deg,
        "total_estimated_slew_sec": total_estimated_slew_sec,
        "total_estimated_transition_sec": total_estimated_transition_sec,
        "median_estimated_slew_sec": median_estimated_slew_sec,
        "max_estimated_slew_sec": max_estimated_slew_sec,
        "selected_count": selected_count,
        "achieved_bin_count": achieved_bin_count,
        "actual_bin_count": actual_bin_count,
        "bin_balance_entropy": bin_balance_entropy,
        "metric_range_coverage": metric_range_coverage,
        "satellite_dominance_ratio": satellite_dominance_ratio,
        "pass_dominance_ratio": pass_dominance_ratio,
    }
    summary = (
        "Slew-aware quality preview: "
        f"active_for_selection={'true' if active_for_selection else 'false'}, selected={selected_count}, "
        f"bins={achieved_bin_count}/{actual_bin_count}, "
        f"slew_violations={transition_violation_count}, "
        f"min_slack={_format_optional(min_slack_sec)} s, "
        f"total_transition={total_estimated_transition_sec:.3g} s, "
        f"total_path={total_axis_path_deg:.3g} deg."
    )
    return SlewAwareQualityPreview(
        available=True,
        reason_unavailable=None,
        active_for_selection=active_for_selection,
        score_tuple=score_tuple,
        score_summary=summary,
        metrics=metrics,
    ).to_dict()


def compute_slew_aware_selection_score(
    *,
    quality_score: Any,
    slew_path_summary: Mapping[str, Any] | None,
    trial_index: int = 0,
) -> dict[str, Any]:
    """Return a selection-active score for the optional Task 35D objective.

    Parameters
    ----------
    quality_score : object
        Existing plan-quality score from :func:`compute_plan_quality`.  Its
        science-quality terms remain the primary score dimensions.
    slew_path_summary : mapping or None
        Summary-only slew/path diagnostics for the candidate trial.
    trial_index : int, optional
        Deterministic tie-breaker used only after quality and slew terms.

    Returns
    -------
    dict
        JSON-serializable score payload.  This score is used only when the
        user explicitly selects the ``slew_aware`` optimization objective.
    """
    quality_tuple = tuple(getattr(quality_score, "lexicographic_score", ()) or ())
    if not quality_tuple:
        quality_tuple = (0,)

    available = bool(slew_path_summary and slew_path_summary.get("available"))
    reason = None if available else str(
        (slew_path_summary or {}).get("reason_unavailable") or "Slew/path diagnostics unavailable for selection score."
    )
    transition_violation_count = _safe_int((slew_path_summary or {}).get("transition_violation_count"), default=0)
    min_slack_sec = _safe_optional_float((slew_path_summary or {}).get("min_slack_sec"))
    total_axis_path_deg = _safe_float((slew_path_summary or {}).get("total_axis_path_deg"), default=0.0)
    total_estimated_transition_sec = _safe_float(
        (slew_path_summary or {}).get("total_estimated_transition_sec"),
        default=0.0,
    )
    max_estimated_slew_sec = _safe_float((slew_path_summary or {}).get("max_estimated_slew_sec"), default=0.0)

    # Preserve the main science-quality dimensions from Task 31/35C before
    # applying slew/path terms.  The final two quality tiebreakers
    # (spacing margin and trial index in current code) remain after the
    # slew/path terms so the optional objective can prefer smoother paths
    # among otherwise comparable science plans.
    primary_quality = quality_tuple[:8]
    secondary_quality = quality_tuple[8:]
    slew_terms = (
        1 if available else 0,
        1 if transition_violation_count == 0 else 0,
        -int(transition_violation_count),
        _score_value(min_slack_sec),
        -float(total_estimated_transition_sec),
        -float(max_estimated_slew_sec),
        -float(total_axis_path_deg),
    )
    selection_score_tuple = tuple(primary_quality) + tuple(slew_terms) + tuple(secondary_quality) + (-int(trial_index),)
    return {
        "available": bool(available),
        "reason_unavailable": reason,
        "active_for_selection": True,
        "score_kind": SLEW_AWARE_SELECTION_SCORE_KIND,
        "selection_score_tuple": list(selection_score_tuple),
        "quality_score_tuple": list(quality_tuple),
        "transition_violation_count": int(transition_violation_count),
        "min_slack_sec": min_slack_sec,
        "total_axis_path_deg": float(total_axis_path_deg),
        "total_estimated_transition_sec": float(total_estimated_transition_sec),
        "max_estimated_slew_sec": float(max_estimated_slew_sec),
    }


def _empty_preview_metrics() -> dict[str, Any]:
    """Return stable metric keys for an unavailable preview."""
    return {
        "transition_violation_count": None,
        "transition_violation_fraction": None,
        "min_slack_sec": None,
        "median_slack_sec": None,
        "total_axis_path_deg": None,
        "total_estimated_slew_sec": None,
        "total_estimated_transition_sec": None,
        "median_estimated_slew_sec": None,
        "max_estimated_slew_sec": None,
        "selected_count": None,
        "achieved_bin_count": None,
        "actual_bin_count": None,
        "bin_balance_entropy": None,
        "metric_range_coverage": None,
        "satellite_dominance_ratio": None,
        "pass_dominance_ratio": None,
    }


def _safe_int(value: Any, *, default: int) -> int:
    """Return a finite integer or a default."""
    try:
        if value is None or not np.isfinite(float(value)):
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _safe_float(value: Any, *, default: float) -> float:
    """Return a finite float or a default."""
    try:
        result = float(value)
    except Exception:
        return float(default)
    if not np.isfinite(result):
        return float(default)
    return result


def _safe_optional_float(value: Any) -> float | None:
    """Return a finite float or ``None``."""
    try:
        result = float(value)
    except Exception:
        return None
    if not np.isfinite(result):
        return None
    return result


def _score_value(value: float | None) -> float:
    """Return a deterministic finite value for score-tuple construction."""
    if value is None:
        return _MISSING_SCORE_VALUE
    try:
        result = float(value)
    except Exception:
        return _MISSING_SCORE_VALUE
    if not np.isfinite(result):
        return _MISSING_SCORE_VALUE
    return result


def _format_optional(value: float | None) -> str:
    """Return compact text for optional numeric fields."""
    if value is None:
        return "n/a"
    try:
        result = float(value)
    except Exception:
        return "n/a"
    if not np.isfinite(result):
        return "n/a"
    return f"{result:.3g}"
