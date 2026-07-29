"""Physical transition constraints for observation-plan selection.

This module provides the Task 35E opt-in feasibility filter used by the
Observation Planner.  It is intentionally GUI-neutral and dependency-light.  The
filter is deterministic and chronological: it never reorders observations, and
it is active only when explicitly requested by planner settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .schema import resolve_column
from .slew_diagnostics import SlewModel, azimuth_delta_deg

TRANSITION_CONSTRAINT_TIME_SPACING = "time_spacing"
TRANSITION_CONSTRAINT_PHYSICAL = "physical_transition"
DEFAULT_TRANSITION_CONSTRAINT_MODE = TRANSITION_CONSTRAINT_TIME_SPACING
DEFAULT_TRANSITION_SAFETY_MARGIN_SEC = 0.0
MAX_TRANSITION_SAFETY_MARGIN_SEC = 3600.0

_TRANSITION_MODE_ALIASES = {
    TRANSITION_CONSTRAINT_TIME_SPACING: TRANSITION_CONSTRAINT_TIME_SPACING,
    "time": TRANSITION_CONSTRAINT_TIME_SPACING,
    "spacing": TRANSITION_CONSTRAINT_TIME_SPACING,
    "time spacing": TRANSITION_CONSTRAINT_TIME_SPACING,
    "time-spacing": TRANSITION_CONSTRAINT_TIME_SPACING,
    "time_spacing_only": TRANSITION_CONSTRAINT_TIME_SPACING,
    "time spacing only": TRANSITION_CONSTRAINT_TIME_SPACING,
    TRANSITION_CONSTRAINT_PHYSICAL: TRANSITION_CONSTRAINT_PHYSICAL,
    "physical": TRANSITION_CONSTRAINT_PHYSICAL,
    "physical transition": TRANSITION_CONSTRAINT_PHYSICAL,
    "physical-transition": TRANSITION_CONSTRAINT_PHYSICAL,
    "physical transition constrained": TRANSITION_CONSTRAINT_PHYSICAL,
    "physical_transition_constrained": TRANSITION_CONSTRAINT_PHYSICAL,
}


@dataclass(frozen=True)
class TransitionComputation:
    """Computed transition quantities between two adjacent observations.

    Parameters
    ----------
    available_gap_sec : float
        Chronological gap between observations.
    required_gap_sec : float
        Required gap after applying the larger of user spacing and physical
        transition time.
    physical_gap_sec : float
        Physical transition time implied by the motion model, independent of
        user spacing.
    slew_time_sec : float
        Axis-limited slew time between mount coordinates.
    transition_slack_sec : float
        ``available_gap_sec - required_gap_sec``.
    feasible : bool
        Whether the transition satisfies the required gap.
    """

    available_gap_sec: float
    required_gap_sec: float
    physical_gap_sec: float
    slew_time_sec: float
    transition_slack_sec: float
    feasible: bool
    az_delta_deg: float
    alt_delta_deg: float


def normalize_transition_constraint_mode(value: object) -> str:
    """Return a supported transition-constraint mode identifier.

    Parameters
    ----------
    value : object
        Persisted or user-supplied transition-constraint value.

    Returns
    -------
    str
        ``"time_spacing"`` or ``"physical_transition"``.
    """
    key = str(value or DEFAULT_TRANSITION_CONSTRAINT_MODE).strip().lower().replace("-", "_")
    key = key.replace(" ", "_")
    return _TRANSITION_MODE_ALIASES.get(key, DEFAULT_TRANSITION_CONSTRAINT_MODE)


def validate_transition_safety_margin_sec(value: object) -> float:
    """Return a finite non-negative transition safety margin in seconds."""
    try:
        margin = float(value)
    except Exception:
        return DEFAULT_TRANSITION_SAFETY_MARGIN_SEC
    if not np.isfinite(margin) or margin < 0.0:
        return DEFAULT_TRANSITION_SAFETY_MARGIN_SEC
    return min(float(margin), MAX_TRANSITION_SAFETY_MARGIN_SEC)


def physical_transition_requested(mode: object) -> bool:
    """Return whether the normalized mode requests physical feasibility."""
    return normalize_transition_constraint_mode(mode) == TRANSITION_CONSTRAINT_PHYSICAL


def _resolve_mount_columns(plan_df: pd.DataFrame, column_mapping=None) -> tuple[str | None, str | None, str | None]:
    """Resolve datetime, azimuth, and altitude columns for transition checks."""
    if plan_df is None or plan_df.empty:
        return None, None, None
    date_col = "datetime" if "datetime" in plan_df.columns else resolve_column(
        plan_df,
        "date_ut",
        column_mapping=column_mapping,
        required=False,
    )
    az_col = resolve_column(plan_df, "az", column_mapping=column_mapping, required=False)
    alt_col = resolve_column(plan_df, "elev", column_mapping=column_mapping, required=False)
    return date_col, az_col, alt_col


def _summary(
    *,
    mode: str,
    requested: bool,
    active: bool,
    reason_unavailable: str | None,
    safety_margin_sec: float,
    input_rows: int,
    selected_rows: int,
    dropped_rows: int = 0,
    transitions: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a JSON-friendly transition-constraint summary."""
    records = list(transitions or [])
    slacks = [float(item["transition_slack_sec"]) for item in records if item.get("transition_slack_sec") is not None]
    violations = [item for item in records if item.get("feasible") is False]
    if slacks:
        min_slack = float(np.min(slacks))
        median_slack = float(np.median(slacks))
        max_slack = float(np.max(slacks))
    else:
        min_slack = median_slack = max_slack = None
    transition_count = int(len(records))
    violation_count = int(len(violations))
    return {
        "transition_constraint_mode": mode,
        "physical_transition_mode_requested": bool(requested),
        "physical_transition_mode_active": bool(active),
        "reason_unavailable": reason_unavailable,
        "transition_safety_margin_sec": float(safety_margin_sec),
        "input_rows": int(input_rows),
        "selected_rows": int(selected_rows),
        "dropped_rows": int(dropped_rows),
        "transition_count": transition_count,
        "physical_transition_violations": violation_count,
        "physical_transition_violation_fraction": (
            float(violation_count / transition_count) if transition_count > 0 else 0.0
        ),
        "min_transition_slack_sec": min_slack,
        "median_transition_slack_sec": median_slack,
        "max_transition_slack_sec": max_slack,
    }


def unavailable_transition_constraint_summary(
    *,
    mode: object = DEFAULT_TRANSITION_CONSTRAINT_MODE,
    reason: str | None = None,
    safety_margin_sec: object = DEFAULT_TRANSITION_SAFETY_MARGIN_SEC,
    input_rows: int = 0,
    selected_rows: int = 0,
) -> dict[str, Any]:
    """Return a stable inactive transition-constraint summary."""
    normalized_mode = normalize_transition_constraint_mode(mode)
    requested = physical_transition_requested(normalized_mode)
    return _summary(
        mode=normalized_mode,
        requested=requested,
        active=False,
        reason_unavailable=reason,
        safety_margin_sec=validate_transition_safety_margin_sec(safety_margin_sec),
        input_rows=int(input_rows),
        selected_rows=int(selected_rows),
    )


def transition_required_gap_sec(
    row_a: pd.Series,
    row_b: pd.Series,
    *,
    model: SlewModel,
    user_spacing_sec: float,
    safety_margin_sec: float = 0.0,
    date_col: str = "datetime",
    az_col: str = "az",
    alt_col: str = "elev",
) -> TransitionComputation:
    """Return physical and effective required gap for adjacent observations.

    Parameters
    ----------
    row_a, row_b : pandas.Series
        Chronologically adjacent observation rows.
    model : SlewModel
        Validated telescope motion model.
    user_spacing_sec : float
        User-requested minimum spacing in seconds.
    safety_margin_sec : float, optional
        Additional conservative transition margin.
    date_col, az_col, alt_col : str, optional
        Resolved column names for time, azimuth, and altitude/elevation.

    Returns
    -------
    TransitionComputation
        Computed transition quantities.
    """
    active_model = model.validated()
    start_time = pd.to_datetime(row_a[date_col], errors="coerce")
    stop_time = pd.to_datetime(row_b[date_col], errors="coerce")
    available_gap = float((stop_time - start_time).total_seconds())
    az_delta = azimuth_delta_deg(row_a[az_col], row_b[az_col])
    alt_delta = float(abs(float(row_b[alt_col]) - float(row_a[alt_col])))
    az_slew = az_delta / active_model.az_rate_deg_per_sec
    alt_slew = alt_delta / active_model.alt_rate_deg_per_sec
    slew_time = float(max(az_slew, alt_slew))
    physical_gap = float(
        active_model.exposure_time_sec
        + slew_time
        + active_model.settle_time_sec
        + active_model.acquisition_time_sec
        + validate_transition_safety_margin_sec(safety_margin_sec)
    )
    required_gap = float(max(float(user_spacing_sec), physical_gap))
    slack = float(available_gap - required_gap)
    return TransitionComputation(
        available_gap_sec=available_gap,
        required_gap_sec=required_gap,
        physical_gap_sec=physical_gap,
        slew_time_sec=slew_time,
        transition_slack_sec=slack,
        feasible=bool(slack >= -1.0e-9),
        az_delta_deg=float(az_delta),
        alt_delta_deg=float(alt_delta),
    )


def _transition_record(
    *,
    output_row_from: int,
    output_row_to: int,
    row_a: pd.Series,
    row_b: pd.Series,
    computation: TransitionComputation,
    date_col: str,
) -> dict[str, Any]:
    """Return a JSON-friendly transition diagnostic record."""
    start_time = pd.to_datetime(row_a[date_col], errors="coerce")
    stop_time = pd.to_datetime(row_b[date_col], errors="coerce")
    return {
        "output_row_from": int(output_row_from),
        "output_row_to": int(output_row_to),
        "datetime_from": start_time.isoformat() if pd.notna(start_time) else None,
        "datetime_to": stop_time.isoformat() if pd.notna(stop_time) else None,
        "available_gap_sec": float(computation.available_gap_sec),
        "required_gap_sec": float(computation.required_gap_sec),
        "physical_gap_sec": float(computation.physical_gap_sec),
        "estimated_slew_sec": float(computation.slew_time_sec),
        "transition_slack_sec": float(computation.transition_slack_sec),
        "feasible": bool(computation.feasible),
        "az_delta_deg": float(computation.az_delta_deg),
        "alt_delta_deg": float(computation.alt_delta_deg),
    }


def apply_time_spacing_filter(plan_df: pd.DataFrame, *, spacing_min: float) -> pd.DataFrame:
    """Return a deterministic chronological time-spacing filtered plan."""
    if plan_df is None or plan_df.empty:
        return pd.DataFrame() if plan_df is None else plan_df.copy()
    date_col = "datetime" if "datetime" in plan_df.columns else resolve_column(
        plan_df,
        "date_ut",
        required=False,
    )
    if date_col is None:
        result = plan_df.copy().reset_index(drop=True)
        result.attrs.update(getattr(plan_df, "attrs", {}))
        return result
    ordered = plan_df.copy()
    ordered[date_col] = pd.to_datetime(ordered[date_col], errors="coerce")
    ordered = ordered.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
    selected_rows: list[pd.Series] = []
    last_time = None
    spacing = pd.Timedelta(minutes=float(spacing_min))
    for _, row in ordered.iterrows():
        timestamp = row[date_col]
        if last_time is None or timestamp >= last_time + spacing:
            selected_rows.append(row)
            last_time = timestamp
    result = pd.DataFrame(selected_rows).reset_index(drop=True) if selected_rows else ordered.iloc[0:0].copy()
    result.attrs.update(getattr(plan_df, "attrs", {}))
    return result


def apply_physical_transition_filter(
    plan_df: pd.DataFrame,
    *,
    model: SlewModel | None = None,
    user_spacing_min: float,
    safety_margin_sec: float = 0.0,
    transition_constraint_mode: object = TRANSITION_CONSTRAINT_PHYSICAL,
    column_mapping=None,
) -> tuple[pd.DataFrame, dict[str, Any], tuple[dict[str, Any], ...]]:
    """Return a plan filtered by time spacing or physical transition feasibility.

    The returned rows are chronologically ordered and include a diagnostic
    summary in ``DataFrame.attrs["transition_constraint_summary"]``.
    """
    normalized_mode = normalize_transition_constraint_mode(transition_constraint_mode)
    requested = physical_transition_requested(normalized_mode)
    active_model = (model or SlewModel()).validated()
    safety_margin = validate_transition_safety_margin_sec(safety_margin_sec)
    if plan_df is None or plan_df.empty:
        empty = pd.DataFrame() if plan_df is None else plan_df.copy()
        summary = _summary(
            mode=normalized_mode,
            requested=requested,
            active=False,
            reason_unavailable=None if requested else "time_spacing_only",
            safety_margin_sec=safety_margin,
            input_rows=0 if plan_df is None else len(plan_df),
            selected_rows=0,
        )
        empty.attrs["transition_constraint_summary"] = summary
        empty.attrs["transition_constraint_transitions"] = tuple()
        return empty, summary, tuple()

    if not requested:
        selected = apply_time_spacing_filter(plan_df, spacing_min=float(user_spacing_min))
        summary = _summary(
            mode=normalized_mode,
            requested=False,
            active=False,
            reason_unavailable="time_spacing_only",
            safety_margin_sec=safety_margin,
            input_rows=len(plan_df),
            selected_rows=len(selected),
            dropped_rows=max(0, len(plan_df) - len(selected)),
        )
        selected.attrs["transition_constraint_summary"] = summary
        selected.attrs["transition_constraint_transitions"] = tuple()
        return selected, summary, tuple()

    date_col, az_col, alt_col = _resolve_mount_columns(plan_df, column_mapping=column_mapping)
    if not (date_col and az_col and alt_col):
        selected = apply_time_spacing_filter(plan_df, spacing_min=float(user_spacing_min))
        summary = _summary(
            mode=normalized_mode,
            requested=True,
            active=False,
            reason_unavailable="missing_mount_coordinates",
            safety_margin_sec=safety_margin,
            input_rows=len(plan_df),
            selected_rows=len(selected),
            dropped_rows=max(0, len(plan_df) - len(selected)),
        )
        selected.attrs["transition_constraint_summary"] = summary
        selected.attrs["transition_constraint_transitions"] = tuple()
        return selected, summary, tuple()

    ordered = plan_df.copy()
    ordered[date_col] = pd.to_datetime(ordered[date_col], errors="coerce")
    ordered[az_col] = pd.to_numeric(ordered[az_col], errors="coerce")
    ordered[alt_col] = pd.to_numeric(ordered[alt_col], errors="coerce")
    ordered = ordered.dropna(subset=[date_col, az_col, alt_col]).sort_values(date_col).reset_index(drop=True)
    if len(ordered) != len(plan_df):
        selected = apply_time_spacing_filter(plan_df, spacing_min=float(user_spacing_min))
        summary = _summary(
            mode=normalized_mode,
            requested=True,
            active=False,
            reason_unavailable="invalid_mount_coordinates",
            safety_margin_sec=safety_margin,
            input_rows=len(plan_df),
            selected_rows=len(selected),
            dropped_rows=max(0, len(plan_df) - len(selected)),
        )
        selected.attrs["transition_constraint_summary"] = summary
        selected.attrs["transition_constraint_transitions"] = tuple()
        return selected, summary, tuple()

    selected_rows: list[pd.Series] = []
    selected_original_positions: list[int] = []
    rejected_count = 0
    if not ordered.empty:
        selected_rows.append(ordered.iloc[0].copy())
        selected_original_positions.append(0)

    spacing_sec = float(user_spacing_min) * 60.0
    for position in range(1, len(ordered)):
        candidate = ordered.iloc[position]
        last_selected = selected_rows[-1]
        computation = transition_required_gap_sec(
            last_selected,
            candidate,
            model=active_model,
            user_spacing_sec=spacing_sec,
            safety_margin_sec=safety_margin,
            date_col=date_col,
            az_col=az_col,
            alt_col=alt_col,
        )
        if computation.feasible:
            selected_rows.append(candidate.copy())
            selected_original_positions.append(position)
        else:
            rejected_count += 1

    selected = pd.DataFrame(selected_rows).reset_index(drop=True) if selected_rows else ordered.iloc[0:0].copy()
    selected.attrs.update(getattr(plan_df, "attrs", {}))

    transition_records: list[dict[str, Any]] = []
    for output_row in range(1, len(selected)):
        computation = transition_required_gap_sec(
            selected.iloc[output_row - 1],
            selected.iloc[output_row],
            model=active_model,
            user_spacing_sec=spacing_sec,
            safety_margin_sec=safety_margin,
            date_col=date_col,
            az_col=az_col,
            alt_col=alt_col,
        )
        transition_records.append(
            _transition_record(
                output_row_from=output_row - 1,
                output_row_to=output_row,
                row_a=selected.iloc[output_row - 1],
                row_b=selected.iloc[output_row],
                computation=computation,
                date_col=date_col,
            )
        )

    summary = _summary(
        mode=normalized_mode,
        requested=True,
        active=True,
        reason_unavailable=None,
        safety_margin_sec=safety_margin,
        input_rows=len(plan_df),
        selected_rows=len(selected),
        dropped_rows=max(0, len(plan_df) - len(selected)),
        transitions=transition_records,
    )
    summary["candidate_transition_rejection_count"] = int(rejected_count)
    selected.attrs["transition_constraint_summary"] = summary
    selected.attrs["transition_constraint_transitions"] = tuple(transition_records)
    return selected, summary, tuple(transition_records)
