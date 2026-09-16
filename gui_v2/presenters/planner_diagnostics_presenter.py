"""Presentation helpers for GUI-v2 planner diagnostics.

This module converts backend-provided planner diagnostics into concise,
operator-facing GUI text.  It does not compute planner metrics, mutate
planner results, or alter planner selection behavior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DiagnosticsCardPresentation:
    """Human-readable presentation for one diagnostics overview card.

    Parameters
    ----------
    title : str
        Card title shown in the overview.
    status : str
        Short status phrase, for example ``"Good"`` or ``"Check"``.
    summary : str
        One concise operator-facing sentence.
    details : tuple[str, ...]
        Optional supporting detail sentences.
    severity : str
        Semantic severity token: ``ready``, ``info``, ``success``,
        ``warning``, or ``error``.
    """

    title: str
    status: str
    summary: str
    details: tuple[str, ...] = ()
    severity: str = "info"

    def body_text(self) -> str:
        """Return compact multiline text for QLabel display."""
        parts = [f"{self.status}: {self.summary}" if self.status else self.summary]
        parts.extend(detail for detail in self.details if detail)
        return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class DiagnosticsOverviewPresentation:
    """Complete overview-card presentation for planner diagnostics."""

    cards: tuple[DiagnosticsCardPresentation, ...]


def present_planner_diagnostics_overview(diagnostics: object | None) -> DiagnosticsOverviewPresentation:
    """Return human-readable overview cards for planner diagnostics.

    The function is intentionally defensive: all values are read from backend
    diagnostics fields if present, but missing or malformed values simply lead
    to unavailable-state text.  No planner metrics are recomputed here.
    """

    if diagnostics is None:
        return DiagnosticsOverviewPresentation(
            cards=(
                DiagnosticsCardPresentation(
                    "Plan Status",
                    "Pending",
                    "Generate or refresh planner diagnostics to inspect the current plan.",
                    severity="warning",
                ),
                DiagnosticsCardPresentation(
                    "Plan Quality",
                    "Pending",
                    "Plan quality metrics are not available yet.",
                    severity="warning",
                ),
                DiagnosticsCardPresentation(
                    "Spacing",
                    "Pending",
                    "Spacing diagnostics are not available yet.",
                    severity="warning",
                ),
                DiagnosticsCardPresentation(
                    "Optimization Impact",
                    "Pending",
                    "Optimization impact diagnostics are not available yet.",
                    severity="warning",
                ),
                DiagnosticsCardPresentation(
                    "Slew / Path",
                    "Pending",
                    "Slew and path diagnostics are not available yet.",
                    severity="warning",
                ),
                DiagnosticsCardPresentation(
                    "Repair / Multi-start",
                    "Pending",
                    "Multi-start and repair diagnostics are not available yet.",
                    severity="warning",
                ),
            )
        )

    return DiagnosticsOverviewPresentation(
        cards=(
            _present_plan_status(diagnostics),
            _present_plan_quality(diagnostics),
            _present_spacing(diagnostics),
            _present_optimization_impact(diagnostics),
            _present_slew_path(diagnostics),
            _present_repair_multistart(diagnostics),
        )
    )


def _present_plan_status(diagnostics: object) -> DiagnosticsCardPresentation:
    output = _mapping(getattr(diagnostics, "output_summary", {}))
    selected = _int(output.get("selected_rows", getattr(diagnostics, "selected_rows", None)))
    unique = _int(output.get("unique_satellites"))
    if unique is None:
        quality = _mapping(getattr(diagnostics, "quality_metrics", {}))
        unique = _int(quality.get("unique_satellite_count") or quality.get("unique_satellites"))

    if selected is not None and selected > 0:
        summary = f"Valid plan with {selected} selected observation{'s' if selected != 1 else ''}."
        details = (f"{unique} unique satellite{'s' if unique != 1 else ''} represented." if unique else "",)
        return DiagnosticsCardPresentation("Plan Status", "Ready", summary, _clean(details), "success")
    return DiagnosticsCardPresentation(
        "Plan Status",
        "Check",
        "No selected observations are reported for the current diagnostics.",
        severity="warning",
    )


def _present_plan_quality(diagnostics: object) -> DiagnosticsCardPresentation:
    metrics = _mapping(getattr(diagnostics, "quality_metrics", {}))
    selected = _int(metrics.get("selected_count") or metrics.get("selected_rows"))
    unique = _int(metrics.get("unique_satellite_count") or metrics.get("unique_satellites"))
    coverage = _float(metrics.get("metric_range_coverage") or metrics.get("bin_coverage_ratio"))
    dominance = _float(metrics.get("satellite_dominance_ratio") or metrics.get("satellite_dominance"))

    details: list[str] = []
    if selected is not None and unique is not None:
        details.append(f"{unique} unique satellites in {selected} selected observations.")
    if coverage is not None:
        details.append(f"Metric coverage is {_percent(coverage)}.")
    if dominance is not None:
        details.append(f"Largest-satellite share is {_percent(dominance)}.")

    if coverage is not None and coverage >= 0.8:
        return DiagnosticsCardPresentation(
            "Plan Quality",
            "Good",
            "The selected plan covers a broad range of the optimization metric.",
            tuple(details),
            "success",
        )
    if details:
        return DiagnosticsCardPresentation(
            "Plan Quality",
            "Review",
            "Quality diagnostics are available for the selected plan.",
            tuple(details),
            "info",
        )
    return DiagnosticsCardPresentation(
        "Plan Quality",
        "Unavailable",
        "Quality metrics are not available for this diagnostics run.",
        severity="warning",
    )


def _present_spacing(diagnostics: object) -> DiagnosticsCardPresentation:
    spacing = _mapping(getattr(diagnostics, "spacing_summary", {}))
    violations = _int(spacing.get("spacing_violations"))
    requested = _float(spacing.get("requested_spacing_min"))
    min_actual = _float(spacing.get("min_actual_spacing_min"))
    median_actual = _float(spacing.get("median_actual_spacing_min"))

    details = []
    if requested is not None:
        details.append(f"Requested minimum spacing: {_minutes(requested)}.")
    if min_actual is not None:
        details.append(f"Actual minimum spacing: {_minutes(min_actual)}.")
    if median_actual is not None:
        details.append(f"Median spacing: {_minutes(median_actual)}.")

    if violations == 0:
        return DiagnosticsCardPresentation(
            "Spacing",
            "Good",
            "No spacing violations were reported.",
            tuple(details),
            "success",
        )
    if violations is not None:
        return DiagnosticsCardPresentation(
            "Spacing",
            "Check",
            f"{violations} spacing violation{'s' if violations != 1 else ''} reported.",
            tuple(details),
            "warning",
        )
    return DiagnosticsCardPresentation(
        "Spacing",
        "Unavailable",
        "Spacing diagnostics are not available for this plan.",
        tuple(details),
        "warning",
    )


def _present_optimization_impact(diagnostics: object) -> DiagnosticsCardPresentation:
    impact = _mapping(getattr(diagnostics, "optimization_impact_summary", {}))
    available = _bool(impact.get("impact_analysis_available"))
    same = _bool(impact.get("controlled_same_method") or impact.get("baseline_same") or impact.get("active_matches_baseline"))
    selected_delta = _int(impact.get("selected_rows_delta") or impact.get("active_selected_rows_delta"))
    interpretation = _text(impact.get("interpretation"))

    details = []
    if selected_delta is not None:
        details.append(f"Selected-row difference relative to baseline: {selected_delta:+d}.")
    if interpretation:
        details.append(_ensure_sentence(interpretation))

    if available is False:
        return DiagnosticsCardPresentation(
            "Optimization Impact",
            "Unavailable",
            "The active diagnostics run did not include an impact comparison.",
            tuple(details),
            "warning",
        )
    if same is True:
        return DiagnosticsCardPresentation(
            "Optimization Impact",
            "Baseline match",
            "The active method selected the same rows as the baseline under the current constraints.",
            tuple(details),
            "info",
        )
    if selected_delta is not None and selected_delta > 0:
        return DiagnosticsCardPresentation(
            "Optimization Impact",
            "Improved count",
            "The active method selected more observations than the baseline comparison.",
            tuple(details),
            "success",
        )
    return DiagnosticsCardPresentation(
        "Optimization Impact",
        "Available",
        "Optimization impact diagnostics are available for review.",
        tuple(details),
        "info",
    )


def _present_slew_path(diagnostics: object) -> DiagnosticsCardPresentation:
    summary = _mapping(getattr(diagnostics, "slew_path_summary", {}))
    available = _bool(summary.get("summary_available") or summary.get("available"))
    transitions = _int(summary.get("transition_count"))
    violations = _int(summary.get("transition_violation_count") or summary.get("physical_transition_violations"))
    min_slack = _float(summary.get("min_slack_sec") or summary.get("min_transition_slack_sec"))
    total_slew = _float(summary.get("total_estimated_slew_sec") or summary.get("total_estimated_transition_sec"))

    details = []
    if transitions is not None:
        details.append(f"{transitions} transition{'s' if transitions != 1 else ''} evaluated.")
    if total_slew is not None:
        details.append(f"Estimated cumulative slew time: {_seconds(total_slew)}.")
    if min_slack is not None:
        details.append(f"Minimum transition slack: {_seconds(min_slack)}.")

    if violations == 0:
        return DiagnosticsCardPresentation(
            "Slew / Path",
            "Good",
            "No transition violations were reported in the diagnostic estimate.",
            tuple(details),
            "success",
        )
    if violations is not None and violations > 0:
        return DiagnosticsCardPresentation(
            "Slew / Path",
            "Check",
            f"{violations} transition violation{'s' if violations != 1 else ''} reported.",
            tuple(details),
            "warning",
        )
    if available:
        return DiagnosticsCardPresentation(
            "Slew / Path",
            "Available",
            "Slew/path diagnostics are available for this plan.",
            tuple(details),
            "info",
        )
    return DiagnosticsCardPresentation(
        "Slew / Path",
        "Diagnostic only",
        "Slew/path estimates are not available or were not requested for this run.",
        tuple(details),
        "info",
    )


def _present_repair_multistart(diagnostics: object) -> DiagnosticsCardPresentation:
    multi = _mapping(getattr(diagnostics, "multi_start_summary", {}))
    repair = _mapping(getattr(diagnostics, "local_repair_summary", {}))
    trials = _int(multi.get("trial_count") or multi.get("trials") or multi.get("executed_trials"))
    added = _int(repair.get("repair_added_rows") or repair.get("added_rows") or repair.get("local_repair_added_rows"))
    enabled = _bool(repair.get("enabled") or repair.get("local_repair_enabled"))

    details = []
    if trials is not None:
        details.append(f"Multi-start trials evaluated: {trials}.")
    if added is not None:
        details.append(f"Repair-added observations: {added}.")

    if trials is not None or enabled is not None or added is not None:
        if added and added > 0:
            return DiagnosticsCardPresentation(
                "Repair / Multi-start",
                "Repair used",
                "Local repair added observations after the initial selection.",
                tuple(details),
                "success",
            )
        return DiagnosticsCardPresentation(
            "Repair / Multi-start",
            "Available",
            "Multi-start and repair diagnostics are available for this plan.",
            tuple(details),
            "info",
        )
    return DiagnosticsCardPresentation(
        "Repair / Multi-start",
        "Unavailable",
        "Multi-start and repair diagnostics are not available for this run.",
        tuple(details),
        "warning",
    )


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "active", "available"}:
            return True
        if lowered in {"false", "no", "0", "inactive", "unavailable"}:
            return False
    return bool(value)


def _percent(value: float) -> str:
    return f"{100.0 * value:.0f}%"


def _minutes(value: float) -> str:
    return f"{value:.2f} min"


def _seconds(value: float) -> str:
    return f"{value:.1f} s"


def _ensure_sentence(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    return stripped if stripped[-1] in ".!?" else stripped + "."


def _clean(items: Sequence[str]) -> tuple[str, ...]:
    return tuple(item for item in items if item)


__all__ = (
    "DiagnosticsCardPresentation",
    "DiagnosticsOverviewPresentation",
    "present_planner_diagnostics_overview",
)
