"""Operator-facing trust summary for observation-plan optimization.

This module distills the detailed planner diagnostics into a compact summary
that answers the practical operator questions: what ran, whether optimization
was active, whether the plan changed, whether slew/feasibility improved, and
whether science sampling was preserved.  It is diagnostic-only and must never
feed back into planner selection.
"""

from __future__ import annotations

from typing import Any, Mapping

import math


_TRUE_VALUES = {"true", "1", "yes", "y", "on"}
_QUALITY_OBJECTIVE = "quality"
_SLEW_AWARE_OBJECTIVE = "slew_aware"
_TIME_SPACING_MODE = "time_spacing"
_PHYSICAL_TRANSITION_MODE = "physical_transition"
_SCIENCE_ROW_DELTA_MIN = -1
_SCIENCE_METRIC_COVERAGE_DELTA_MIN = -0.05


def unavailable_optimization_trust_summary(reason: str | None = None) -> dict[str, Any]:
    """Return a stable unavailable trust-summary payload.

    Parameters
    ----------
    reason : str or None, optional
        Human-readable explanation for the unavailable summary.

    Returns
    -------
    dict
        JSON-safe operator-facing summary with stable keys.
    """
    message = str(reason or "Optimization trust summary unavailable.")
    return {
        "trust_summary_available": False,
        "plan_method": "unknown",
        "sampling_metric_label": "unknown",
        "optimization_objective": "unknown",
        "transition_constraint_mode": "unknown",
        "optimization_active": "unknown",
        "physical_constraint_active": "unknown",
        "baseline_comparison_available": "no",
        "plan_changed_vs_baseline": "unknown",
        "trust_assessment": "not_available",
        "recommended_user_interpretation": message,
        "active_mode_summary": "Unavailable",
        "rows_changed_summary": "Unavailable",
        "slew_time_summary": "Unavailable",
        "axis_path_summary": "Unavailable",
        "transition_feasibility_summary": "Unavailable",
        "science_sampling_summary": "Unavailable",
        "operator_next_check": "Review raw diagnostics sections below.",
    }


def build_optimization_trust_summary(diagnostics: Any) -> dict[str, Any]:
    """Build a compact operator-facing trust summary.

    Parameters
    ----------
    diagnostics : object
        Diagnostics object exposing the public Task 35 diagnostics mappings.

    Returns
    -------
    dict
        JSON-safe summary suitable for table display and diagnostics sidecar
        export.  The summary is derived from diagnostics only and does not
        alter planner output.
    """
    if diagnostics is None:
        return unavailable_optimization_trust_summary("Diagnostics object is missing.")

    run = _as_mapping(getattr(diagnostics, "run_summary", None))
    multi_start = _as_mapping(getattr(diagnostics, "multi_start_summary", None))
    impact = _as_mapping(getattr(diagnostics, "optimization_impact_summary", None))
    quality = _as_mapping(getattr(diagnostics, "quality_metrics", None))
    slew_path = _as_mapping(getattr(diagnostics, "slew_path_summary", None))
    transition = _as_mapping(run.get("transition_constraint_summary"))

    plan_method = str(run.get("plan_method") or run.get("method") or getattr(diagnostics, "method", "unknown"))
    metric_label = str(run.get("metric_label") or run.get("metric") or getattr(diagnostics, "metric", "metric"))
    objective = str(run.get("optimization_objective") or _QUALITY_OBJECTIVE)
    transition_mode = str(run.get("transition_constraint_mode") or run.get("transition_constraint") or _TIME_SPACING_MODE)
    optimization_enabled = _as_bool(multi_start.get("optimization_enabled"))
    slew_aware_active = _as_bool(multi_start.get("slew_aware_selection_active")) or objective == _SLEW_AWARE_OBJECTIVE
    physical_active = _as_bool(
        transition.get("physical_transition_mode_active", run.get("physical_transition_mode_active"))
    )
    physical_requested = _as_bool(
        transition.get("physical_transition_mode_requested", run.get("physical_transition_mode_requested"))
    ) or transition_mode == _PHYSICAL_TRANSITION_MODE

    impact_available = _as_bool(impact.get("impact_analysis_available"))
    if not impact_available:
        return unavailable_optimization_trust_summary(
            "Baseline comparison is unavailable; optimization trust summary unavailable."
        )

    rows_changed = _safe_int(impact.get("rows_changed_count"))
    rows_fraction = _safe_float(impact.get("rows_changed_fraction"))
    active_rows = _safe_int(impact.get("active_selected_rows"), default=_safe_int(getattr(diagnostics, "selected_rows", None), default=0))
    baseline_rows = _safe_int(impact.get("baseline_selected_rows"))
    selected_rows_delta = _safe_int(impact.get("selected_rows_delta"))
    plan_changed = bool(impact_available and (rows_changed > 0 or selected_rows_delta != 0))

    slew_reduction_percent = _safe_float(impact.get("slew_time_reduction_percent"))
    slew_reduction_sec = _safe_float(impact.get("slew_time_reduction_sec"))
    axis_reduction_percent = _safe_float(impact.get("axis_path_reduction_percent"))
    axis_reduction_deg = _safe_float(impact.get("axis_path_reduction_deg"))
    violation_reduction = _safe_int(impact.get("physical_transition_violations_reduction"))
    active_violations = _safe_int(
        impact.get("active_physical_transition_violations"),
        default=_safe_int(transition.get("physical_transition_violations"), default=_safe_int(slew_path.get("transition_violation_count"))),
    )
    baseline_violations = _safe_int(impact.get("baseline_physical_transition_violations"))
    slack_delta = _safe_float(impact.get("min_transition_slack_delta_sec"))
    bins_delta = _safe_int(impact.get("achieved_bins_delta"))
    metric_coverage_delta = _safe_float(impact.get("metric_range_coverage_delta"))
    active_bins = _safe_int(impact.get("active_achieved_bins"), default=_safe_int(quality.get("achieved_bin_count")))
    baseline_bins = _safe_int(impact.get("baseline_achieved_bins"))

    optimization_active_text = _yes_no(optimization_enabled or slew_aware_active)
    physical_active_text = _yes_no(physical_active)
    plan_changed_text = _yes_no(plan_changed)

    rows_changed_summary = _rows_changed_summary(
        impact_available=impact_available,
        rows_changed=rows_changed,
        rows_fraction=rows_fraction,
        active_rows=active_rows,
        baseline_rows=baseline_rows,
        selected_rows_delta=selected_rows_delta,
    )
    slew_time_summary = _improvement_summary(
        label="Estimated slew time",
        reduction_value=slew_reduction_sec,
        reduction_percent=slew_reduction_percent,
        unit="s",
        impact_available=impact_available,
    )
    axis_path_summary = _improvement_summary(
        label="Axis path",
        reduction_value=axis_reduction_deg,
        reduction_percent=axis_reduction_percent,
        unit="deg",
        impact_available=impact_available,
    )
    transition_feasibility_summary = _transition_summary(
        impact_available=impact_available,
        physical_requested=physical_requested,
        physical_active=physical_active,
        active_violations=active_violations,
        baseline_violations=baseline_violations,
        violation_reduction=violation_reduction,
        slack_delta=slack_delta,
    )
    science_sampling_summary = _science_summary(
        impact_available=impact_available,
        bins_delta=bins_delta,
        active_bins=active_bins,
        baseline_bins=baseline_bins,
        metric_coverage_delta=metric_coverage_delta,
    )

    trust_assessment = _trust_assessment(
        optimization_active=optimization_enabled or slew_aware_active,
        physical_requested=physical_requested,
        physical_active=physical_active,
        plan_changed=plan_changed,
        slew_reduction_percent=slew_reduction_percent,
        slew_reduction_sec=slew_reduction_sec,
        axis_reduction_percent=axis_reduction_percent,
        axis_reduction_deg=axis_reduction_deg,
        violation_reduction=violation_reduction,
        active_violations=active_violations,
        selected_rows_delta=selected_rows_delta,
        bins_delta=bins_delta,
        metric_coverage_delta=metric_coverage_delta,
    )
    interpretation = _recommended_interpretation(
        trust_assessment=trust_assessment,
        optimization_active=optimization_enabled or slew_aware_active,
        physical_requested=physical_requested,
        physical_active=physical_active,
        plan_changed=plan_changed,
        slew_reduction_percent=slew_reduction_percent,
        slew_reduction_sec=slew_reduction_sec,
        selected_rows_delta=selected_rows_delta,
        violation_reduction=violation_reduction,
        bins_delta=bins_delta,
        metric_coverage_delta=metric_coverage_delta,
    )

    return {
        "trust_summary_available": True,
        "plan_method": plan_method,
        "sampling_metric_label": metric_label,
        "optimization_objective": objective,
        "transition_constraint_mode": transition_mode,
        "optimization_active": optimization_active_text,
        "physical_constraint_active": physical_active_text,
        "baseline_comparison_available": "yes",
        "plan_changed_vs_baseline": plan_changed_text,
        "trust_assessment": trust_assessment,
        "recommended_user_interpretation": interpretation,
        "active_mode_summary": _active_mode_summary(plan_method, metric_label, objective, transition_mode),
        "rows_changed_summary": rows_changed_summary,
        "slew_time_summary": slew_time_summary,
        "axis_path_summary": axis_path_summary,
        "transition_feasibility_summary": transition_feasibility_summary,
        "science_sampling_summary": science_sampling_summary,
        "operator_next_check": _operator_next_check(trust_assessment),
    }


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Return ``value`` when mapping-like, otherwise an empty mapping."""
    return value if isinstance(value, Mapping) else {}


def _as_bool(value: Any) -> bool:
    """Return a practical bool for diagnostics values."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_VALUES
    try:
        return bool(value)
    except Exception:
        return False


def _safe_float(value: Any, *, default: float | None = None) -> float | None:
    """Return a finite float or ``default``."""
    try:
        number = float(value)
    except Exception:
        return default
    return float(number) if math.isfinite(number) else default


def _safe_int(value: Any, *, default: int = 0) -> int:
    """Return an integer or ``default``."""
    number = _safe_float(value)
    if number is None:
        return int(default)
    return int(round(number))


def _yes_no(value: bool) -> str:
    """Return stable yes/no text for operator display."""
    return "yes" if bool(value) else "no"


def _active_mode_summary(plan_method: str, metric_label: str, objective: str, transition_mode: str) -> str:
    """Return one compact mode/objective/constraint summary."""
    return (
        f"Method={plan_method}; metric={metric_label}; "
        f"objective={objective}; transition constraint={transition_mode}"
    )


def _rows_changed_summary(
    *,
    impact_available: bool,
    rows_changed: int,
    rows_fraction: float | None,
    active_rows: int,
    baseline_rows: int,
    selected_rows_delta: int,
) -> str:
    """Return a concise baseline row-change statement."""
    if not impact_available:
        return "Baseline comparison unavailable."
    percent = f" ({rows_fraction * 100.0:.1f}% of row identities)" if rows_fraction is not None else ""
    delta = f"; selected rows delta={selected_rows_delta:+d}" if selected_rows_delta else ""
    if rows_changed == 0 and active_rows == baseline_rows:
        return f"No row changes versus baseline ({active_rows} selected rows)."
    return f"Changed {rows_changed} row identity assignment(s){percent}; baseline={baseline_rows}, active={active_rows}{delta}."


def _improvement_summary(
    *,
    label: str,
    reduction_value: float | None,
    reduction_percent: float | None,
    unit: str,
    impact_available: bool,
) -> str:
    """Return improvement/worsening summary for a numeric reduction metric."""
    if not impact_available or reduction_value is None:
        return f"{label} comparison unavailable."
    percent = f" ({reduction_percent:.1f}%)" if reduction_percent is not None else ""
    if reduction_value > 1.0e-9:
        return f"{label} reduced by {reduction_value:.3g} {unit}{percent}."
    if reduction_value < -1.0e-9:
        return f"{label} increased by {abs(reduction_value):.3g} {unit}{percent}."
    return f"{label} unchanged."


def _transition_summary(
    *,
    impact_available: bool,
    physical_requested: bool,
    physical_active: bool,
    active_violations: int,
    baseline_violations: int,
    violation_reduction: int,
    slack_delta: float | None,
) -> str:
    """Return transition-feasibility trust summary."""
    if not physical_requested:
        return "Physical-transition constraint not requested; time spacing only."
    if not physical_active:
        return "Physical-transition constraint requested but not active; check mount-coordinate availability."
    if not impact_available:
        return f"Physical-transition mode active; active violations={active_violations}."
    slack = f"; minimum slack delta={slack_delta:.3g} s" if slack_delta is not None else ""
    if violation_reduction > 0:
        return f"Physical-transition violations reduced from {baseline_violations} to {active_violations}{slack}."
    if violation_reduction < 0:
        return f"Physical-transition violations increased from {baseline_violations} to {active_violations}{slack}."
    return f"Physical-transition violations unchanged at {active_violations}{slack}."


def _science_summary(
    *,
    impact_available: bool,
    bins_delta: int,
    active_bins: int,
    baseline_bins: int,
    metric_coverage_delta: float | None,
) -> str:
    """Return science-sampling preservation summary."""
    if not impact_available:
        return "Science-sampling baseline comparison unavailable."
    coverage = ""
    if metric_coverage_delta is not None:
        coverage = f"; metric-range coverage delta={metric_coverage_delta:+.3g}"
    if bins_delta == 0:
        return f"Metric bin coverage preserved ({active_bins} bin(s)){coverage}."
    if bins_delta > 0:
        return f"Metric bin coverage increased by {bins_delta} bin(s) ({baseline_bins} -> {active_bins}){coverage}."
    return f"Metric bin coverage decreased by {abs(bins_delta)} bin(s) ({baseline_bins} -> {active_bins}){coverage}."


def _trust_assessment(
    *,
    optimization_active: bool,
    physical_requested: bool,
    physical_active: bool,
    plan_changed: bool,
    slew_reduction_percent: float | None,
    slew_reduction_sec: float | None,
    axis_reduction_percent: float | None,
    axis_reduction_deg: float | None,
    violation_reduction: int,
    active_violations: int,
    selected_rows_delta: int,
    bins_delta: int,
    metric_coverage_delta: float | None,
) -> str:
    """Classify the operator-facing trust posture."""
    advanced_configuration_active = optimization_active or (physical_requested and physical_active)
    if not advanced_configuration_active:
        return "configuration_inactive"

    science_preserved = _science_quality_preserved(
        selected_rows_delta=selected_rows_delta,
        bins_delta=bins_delta,
        metric_coverage_delta=metric_coverage_delta,
    )
    motion_improved = _motion_improved(
        slew_reduction_percent=slew_reduction_percent,
        slew_reduction_sec=slew_reduction_sec,
        axis_reduction_percent=axis_reduction_percent,
        axis_reduction_deg=axis_reduction_deg,
    )

    if physical_requested and physical_active and selected_rows_delta < 0 and violation_reduction > 0:
        return "physical_constraint_reduced_rows"
    if violation_reduction > 0:
        return "physical_feasibility_improved"
    if motion_improved and science_preserved:
        return "optimized_motion_improved_quality_preserved"
    if motion_improved and not science_preserved:
        return "optimized_motion_improved_quality_degraded"
    if not science_preserved:
        return "science_quality_degraded"
    if not plan_changed and active_violations == 0:
        return "baseline_same"
    return "no_measurable_optimization_effect"


def _recommended_interpretation(
    *,
    trust_assessment: str,
    optimization_active: bool,
    physical_requested: bool,
    physical_active: bool,
    plan_changed: bool,
    slew_reduction_percent: float | None,
    slew_reduction_sec: float | None,
    selected_rows_delta: int,
    violation_reduction: int,
    bins_delta: int,
    metric_coverage_delta: float | None,
) -> str:
    """Return a concise human-readable operator recommendation."""
    if trust_assessment == "configuration_inactive":
        return "The planner ran without an active advanced optimization or physical-transition constraint; no optimization impact is expected."
    if trust_assessment == "baseline_same":
        return "Active settings produced the same selected rows as the baseline; current constraints may not be binding."
    if trust_assessment == "optimized_motion_improved_quality_preserved":
        percent = f" by {slew_reduction_percent:.1f}%" if slew_reduction_percent is not None else ""
        value = f" by {slew_reduction_sec:.3g} s" if slew_reduction_percent is None and slew_reduction_sec is not None else ""
        return f"The active settings reduced estimated telescope motion{percent}{value} while preserving science-sampling checks."
    if trust_assessment == "optimized_motion_improved_quality_degraded":
        return "The active settings reduced estimated telescope motion but degraded science-sampling coverage. Review before accepting."
    if trust_assessment == "physical_feasibility_improved":
        return "Physical-transition mode reduced infeasible transitions relative to the baseline. Verify row count and science coverage before observing."
    if trust_assessment == "physical_constraint_reduced_rows":
        return "Physical-transition mode improved feasibility but reduced selected rows. Consider relaxing spacing or increasing candidate depth to recover rows."
    if trust_assessment == "science_quality_degraded":
        return "The active settings degraded science-sampling coverage. Review whether the operational tradeoff is acceptable."
    if trust_assessment == "no_measurable_optimization_effect":
        return "The active settings changed the plan, but current diagnostics do not show a clear motion, feasibility, or science-sampling benefit."
    if plan_changed:
        return "The active plan differs from the baseline. Review row changes, slew, feasibility, and science sampling below."
    return "The active plan matches the baseline. No optimization-driven change is visible for this run."


def _science_quality_preserved(
    *,
    selected_rows_delta: int,
    bins_delta: int,
    metric_coverage_delta: float | None,
) -> bool:
    """Return whether science-sampling quality is preserved for summary text."""
    coverage_ok = metric_coverage_delta is None or metric_coverage_delta >= _SCIENCE_METRIC_COVERAGE_DELTA_MIN
    return selected_rows_delta >= _SCIENCE_ROW_DELTA_MIN and bins_delta >= 0 and coverage_ok


def _motion_improved(
    *,
    slew_reduction_percent: float | None,
    slew_reduction_sec: float | None,
    axis_reduction_percent: float | None,
    axis_reduction_deg: float | None,
) -> bool:
    """Return whether motion/path diagnostics show an improvement."""
    return any(
        value is not None and value > 1.0e-9
        for value in (
            slew_reduction_sec,
            axis_reduction_deg,
        )
    ) or any(
        value is not None and value > 1.0
        for value in (
            slew_reduction_percent,
            axis_reduction_percent,
        )
    )


def _operator_next_check(trust_assessment: str) -> str:
    """Return the most useful next diagnostics section to inspect."""
    if trust_assessment in {"physical_feasibility_improved", "physical_constraint_reduced_rows"}:
        return "Check Physical Transition Constraint and Slew / Path Summary."
    if trust_assessment in {"optimized_motion_improved_quality_degraded", "science_quality_degraded"}:
        return "Check Plan Quality, Bin Summary, and Optimization Impact Summary."
    if trust_assessment in {"optimized_motion_improved_quality_preserved", "no_measurable_optimization_effect"}:
        return "Check Optimization Impact Summary and Slew / Path Summary."
    return "Raw diagnostics are available below for audit and reproducibility."
