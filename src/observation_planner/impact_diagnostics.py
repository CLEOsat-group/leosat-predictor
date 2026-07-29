"""Optimization-impact diagnostics for observation planner runs.

This module compares the active generated observation plan against a
controlled baseline plan.  The comparison is diagnostic-only: it must never
select, remove, reorder, or otherwise modify observation-plan rows.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd


_BASELINE_OPTIMIZATION_OBJECTIVE = "quality"
_BASELINE_TRANSITION_CONSTRAINT_MODE = "time_spacing"


def unavailable_optimization_impact_summary(reason: str | None = None) -> dict[str, Any]:
    """Return a stable unavailable optimization-impact payload.

    Parameters
    ----------
    reason : str or None, optional
        Human-readable reason why the comparison was not computed.

    Returns
    -------
    dict
        JSON-serializable diagnostics payload with all expected high-level
        fields present.
    """
    message = str(reason or "Optimization impact comparison unavailable.")
    return {
        "impact_analysis_available": False,
        "reason_unavailable": message,
        "interpretation": message,
        "active_plan_method": None,
        "active_metric": None,
        "active_optimization_objective": None,
        "active_transition_constraint_mode": None,
        "baseline_optimization_objective": _BASELINE_OPTIMIZATION_OBJECTIVE,
        "baseline_transition_constraint_mode": _BASELINE_TRANSITION_CONSTRAINT_MODE,
        "rows_changed_count": None,
        "rows_changed_fraction": None,
        "common_rows_count": None,
        "active_only_rows_count": None,
        "baseline_only_rows_count": None,
        "active_total_axis_path_deg": None,
        "baseline_total_axis_path_deg": None,
        "axis_path_delta_deg": None,
        "axis_path_delta_percent": None,
        "active_total_estimated_slew_sec": None,
        "baseline_total_estimated_slew_sec": None,
        "slew_time_delta_sec": None,
        "slew_time_delta_percent": None,
        "slew_time_reduction_sec": None,
        "slew_time_reduction_percent": None,
        "active_physical_transition_violations": None,
        "baseline_physical_transition_violations": None,
        "physical_transition_violations_delta": None,
        "active_min_transition_slack_sec": None,
        "baseline_min_transition_slack_sec": None,
        "min_transition_slack_delta_sec": None,
        "active_achieved_bins": None,
        "baseline_achieved_bins": None,
        "achieved_bins_delta": None,
        "active_metric_range_coverage": None,
        "baseline_metric_range_coverage": None,
        "metric_range_coverage_delta": None,
    }


def build_optimization_impact_summary(
    *,
    active_plan: pd.DataFrame | None,
    baseline_plan: pd.DataFrame | None,
    active_diagnostics: Any,
    baseline_diagnostics: Any,
) -> dict[str, Any]:
    """Compare active planner output against a controlled baseline.

    Parameters
    ----------
    active_plan : pandas.DataFrame or None
        Plan selected with the user's active planner settings.
    baseline_plan : pandas.DataFrame or None
        Plan selected with the controlled baseline settings.
    active_diagnostics : object
        Diagnostics object for the active plan.  It is accessed by public
        attributes to avoid a circular dependency on ``diagnostics.py``.
    baseline_diagnostics : object
        Diagnostics object for the baseline plan.

    Returns
    -------
    dict
        JSON-serializable optimization-impact summary.
    """
    if active_plan is None or baseline_plan is None:
        return unavailable_optimization_impact_summary("Active or baseline plan is missing.")
    if active_diagnostics is None or baseline_diagnostics is None:
        return unavailable_optimization_impact_summary("Active or baseline diagnostics are missing.")

    active_rows = int(len(active_plan))
    baseline_rows = int(len(baseline_plan))
    if active_rows == 0 and baseline_rows == 0:
        return unavailable_optimization_impact_summary("Active and baseline plans are both empty.")

    active_keys = _plan_identity_keys(active_plan)
    baseline_keys = _plan_identity_keys(baseline_plan)
    common_keys = active_keys.intersection(baseline_keys)
    active_only = active_keys.difference(baseline_keys)
    baseline_only = baseline_keys.difference(active_keys)
    changed_count = int(len(active_only) + len(baseline_only))
    denominator = max(1, int(len(active_keys.union(baseline_keys))))

    active_slew = dict(getattr(active_diagnostics, "slew_path_summary", {}) or {})
    baseline_slew = dict(getattr(baseline_diagnostics, "slew_path_summary", {}) or {})
    active_run = dict(getattr(active_diagnostics, "run_summary", {}) or {})
    baseline_run = dict(getattr(baseline_diagnostics, "run_summary", {}) or {})
    active_quality = dict(getattr(active_diagnostics, "quality_metrics", {}) or {})
    baseline_quality = dict(getattr(baseline_diagnostics, "quality_metrics", {}) or {})
    active_transition = dict(active_run.get("transition_constraint_summary", {}) or {})
    baseline_transition = dict(baseline_run.get("transition_constraint_summary", {}) or {})
    active_bins = dict(getattr(active_diagnostics, "bin_summary", {}) or {})
    baseline_bins = dict(getattr(baseline_diagnostics, "bin_summary", {}) or {})

    active_axis_path = _optional_float(active_slew.get("total_axis_path_deg"))
    baseline_axis_path = _optional_float(baseline_slew.get("total_axis_path_deg"))
    axis_delta = _delta(active_axis_path, baseline_axis_path)

    active_slew_sec = _optional_float(active_slew.get("total_estimated_slew_sec"))
    baseline_slew_sec = _optional_float(baseline_slew.get("total_estimated_slew_sec"))
    slew_delta = _delta(active_slew_sec, baseline_slew_sec)

    active_violations = _safe_int(
        active_transition.get("physical_transition_violations"),
        default=_safe_int(active_slew.get("transition_violation_count"), default=0),
    )
    baseline_violations = _safe_int(
        baseline_transition.get("physical_transition_violations"),
        default=_safe_int(baseline_slew.get("transition_violation_count"), default=0),
    )

    active_slack = _optional_float(
        active_transition.get("min_transition_slack_sec", active_slew.get("min_slack_sec"))
    )
    baseline_slack = _optional_float(
        baseline_transition.get("min_transition_slack_sec", baseline_slew.get("min_slack_sec"))
    )

    active_achieved_bins = _safe_int(active_bins.get("achieved_bins"), default=0)
    baseline_achieved_bins = _safe_int(baseline_bins.get("achieved_bins"), default=0)
    active_metric_coverage = _optional_float(active_quality.get("metric_range_coverage"))
    baseline_metric_coverage = _optional_float(baseline_quality.get("metric_range_coverage"))

    summary = {
        "impact_analysis_available": True,
        "reason_unavailable": None,
        "interpretation": "",
        "active_plan_method": active_run.get("plan_method") or getattr(active_diagnostics, "method", None),
        "active_metric": active_run.get("metric"),
        "active_optimization_objective": active_run.get("optimization_objective"),
        "active_transition_constraint_mode": active_run.get("transition_constraint_mode") or active_run.get("transition_constraint"),
        "baseline_optimization_objective": baseline_run.get("optimization_objective") or _BASELINE_OPTIMIZATION_OBJECTIVE,
        "baseline_transition_constraint_mode": baseline_run.get("transition_constraint_mode") or _BASELINE_TRANSITION_CONSTRAINT_MODE,
        "active_selected_rows": active_rows,
        "baseline_selected_rows": baseline_rows,
        "selected_rows_delta": int(active_rows - baseline_rows),
        "rows_changed_count": changed_count,
        "rows_changed_fraction": float(changed_count / denominator),
        "common_rows_count": int(len(common_keys)),
        "active_only_rows_count": int(len(active_only)),
        "baseline_only_rows_count": int(len(baseline_only)),
        "active_total_axis_path_deg": active_axis_path,
        "baseline_total_axis_path_deg": baseline_axis_path,
        "axis_path_delta_deg": axis_delta,
        "axis_path_delta_percent": _percent_delta(active_axis_path, baseline_axis_path),
        "axis_path_reduction_deg": _delta(baseline_axis_path, active_axis_path),
        "axis_path_reduction_percent": _percent_reduction(active_axis_path, baseline_axis_path),
        "active_total_estimated_slew_sec": active_slew_sec,
        "baseline_total_estimated_slew_sec": baseline_slew_sec,
        "slew_time_delta_sec": slew_delta,
        "slew_time_delta_percent": _percent_delta(active_slew_sec, baseline_slew_sec),
        "slew_time_reduction_sec": _delta(baseline_slew_sec, active_slew_sec),
        "slew_time_reduction_percent": _percent_reduction(active_slew_sec, baseline_slew_sec),
        "active_physical_transition_violations": active_violations,
        "baseline_physical_transition_violations": baseline_violations,
        "physical_transition_violations_delta": int(active_violations - baseline_violations),
        "physical_transition_violations_reduction": int(baseline_violations - active_violations),
        "active_min_transition_slack_sec": active_slack,
        "baseline_min_transition_slack_sec": baseline_slack,
        "min_transition_slack_delta_sec": _delta(active_slack, baseline_slack),
        "active_achieved_bins": active_achieved_bins,
        "baseline_achieved_bins": baseline_achieved_bins,
        "achieved_bins_delta": int(active_achieved_bins - baseline_achieved_bins),
        "active_metric_range_coverage": active_metric_coverage,
        "baseline_metric_range_coverage": baseline_metric_coverage,
        "metric_range_coverage_delta": _delta(active_metric_coverage, baseline_metric_coverage),
        "baseline_controlled_same_method": bool(
            (active_run.get("plan_method") or getattr(active_diagnostics, "method", None))
            == (baseline_run.get("plan_method") or getattr(baseline_diagnostics, "method", None))
        ),
        "baseline_controlled_same_metric": bool(active_run.get("metric") == baseline_run.get("metric")),
        "baseline_forced_quality_objective": bool(
            (baseline_run.get("optimization_objective") or _BASELINE_OPTIMIZATION_OBJECTIVE)
            == _BASELINE_OPTIMIZATION_OBJECTIVE
        ),
        "baseline_forced_time_spacing": bool(
            (baseline_run.get("transition_constraint_mode") or _BASELINE_TRANSITION_CONSTRAINT_MODE)
            == _BASELINE_TRANSITION_CONSTRAINT_MODE
        ),
    }
    summary["interpretation"] = _interpret(summary)
    return summary


def _plan_identity_keys(plan_df: pd.DataFrame) -> set[str]:
    """Return stable row identity keys for a generated plan."""
    if plan_df is None or plan_df.empty:
        return set()
    keys: set[str] = set()
    for row_number, (_, row) in enumerate(plan_df.iterrows()):
        key = _row_identity_key(row, row_number=row_number)
        if key:
            keys.add(key)
    return keys


def _row_identity_key(row: pd.Series, *, row_number: int) -> str:
    """Return a stable key for one plan row."""
    for column in ("global_index", "base_index", "local_index"):
        if column in row.index:
            value = _safe_identity_value(row.get(column))
            if value is not None:
                return f"{column}:{value}"
    satellite = _safe_identity_value(row.get("satellite") if "satellite" in row.index else row.get("Satellite"))
    time_value = None
    for column in ("datetime", "date_ut", "Date [UT]"):
        if column in row.index:
            timestamp = pd.to_datetime(row.get(column), errors="coerce", utc=True)
            if pd.notna(timestamp):
                time_value = timestamp.isoformat()
                break
    if satellite is not None and time_value is not None:
        return f"sat_time:{satellite}|{time_value}"
    return f"row:{row_number}"


def _safe_identity_value(value: Any) -> str | None:
    """Return a normalized row-identity scalar string."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def _safe_int(value: Any, *, default: int = 0) -> int:
    """Return ``value`` as an integer, or ``default`` when invalid."""
    try:
        if value is None or pd.isna(value):
            return int(default)
    except Exception:
        pass
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _optional_float(value: Any) -> float | None:
    """Return ``value`` as a finite float or ``None``."""
    try:
        number = float(value)
    except Exception:
        return None
    if not np.isfinite(number):
        return None
    return float(number)


def _delta(active: float | None, baseline: float | None) -> float | None:
    """Return active minus baseline when both values are available."""
    if active is None or baseline is None:
        return None
    return float(active - baseline)


def _percent_delta(active: float | None, baseline: float | None) -> float | None:
    """Return percent change from baseline to active."""
    if active is None or baseline is None or abs(float(baseline)) < 1.0e-12:
        return None
    return float((active - baseline) / abs(baseline) * 100.0)


def _percent_reduction(active: float | None, baseline: float | None) -> float | None:
    """Return positive percentage when active is smaller than baseline."""
    if active is None or baseline is None or abs(float(baseline)) < 1.0e-12:
        return None
    return float((baseline - active) / abs(baseline) * 100.0)


def _interpret(summary: Mapping[str, Any]) -> str:
    """Return a concise human-readable optimization-impact interpretation."""
    parts: list[str] = []
    rows_changed = _safe_int(summary.get("rows_changed_count"), default=0)
    active_rows = _safe_int(summary.get("active_selected_rows"), default=0)
    baseline_rows = _safe_int(summary.get("baseline_selected_rows"), default=0)
    if rows_changed == 0 and active_rows == baseline_rows:
        parts.append("Active settings selected the same rows as the controlled baseline.")
    else:
        parts.append(
            f"Active settings changed {rows_changed} row identity assignment(s) "
            f"relative to the controlled baseline ({baseline_rows} baseline row(s), {active_rows} active row(s))."
        )

    slew_reduction_percent = _optional_float(summary.get("slew_time_reduction_percent"))
    if slew_reduction_percent is not None:
        if slew_reduction_percent > 1.0:
            parts.append(f"Estimated slew time decreased by {slew_reduction_percent:.1f}%.")
        elif slew_reduction_percent < -1.0:
            parts.append(f"Estimated slew time increased by {abs(slew_reduction_percent):.1f}%.")
        else:
            parts.append("Estimated slew time is essentially unchanged.")

    violation_reduction = _safe_int(summary.get("physical_transition_violations_reduction"), default=0)
    if violation_reduction > 0:
        parts.append(f"Physical-transition violations decreased by {violation_reduction}.")
    elif _safe_int(summary.get("physical_transition_violations_delta"), default=0) > 0:
        parts.append("Physical-transition violations increased relative to the baseline.")

    bins_delta = _safe_int(summary.get("achieved_bins_delta"), default=0)
    if bins_delta < 0:
        parts.append(f"Metric bin coverage decreased by {abs(bins_delta)} bin(s).")
    elif bins_delta > 0:
        parts.append(f"Metric bin coverage increased by {bins_delta} bin(s).")
    else:
        parts.append("Metric bin coverage is unchanged.")

    return " ".join(parts)
