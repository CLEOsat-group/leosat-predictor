"""Slew/path diagnostics for generated observation plans.

This module estimates telescope transition overheads between adjacent selected
observation-plan rows.  The calculations are diagnostic only: they must never
select, remove, reorder, or otherwise modify observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .schema import resolve_column

DEFAULT_TRANSITION_SAMPLE_LIMIT = 5000
MIN_SLEW_RATE_DEG_PER_SEC = 0.01
MAX_SLEW_RATE_DEG_PER_SEC = 20.0
MAX_SLEW_OVERHEAD_SEC = 3600.0
MIN_TRANSITION_SAMPLE_LIMIT = 0
MAX_TRANSITION_SAMPLE_LIMIT = 100000


def validate_transition_sample_limit(value: object) -> int:
    """Return a bounded per-transition diagnostics sample limit.

    Parameters
    ----------
    value : object
        Candidate value to validate.

    Returns
    -------
    int
        Integer sample limit in the accepted range.
    """
    try:
        limit = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_TRANSITION_SAMPLE_LIMIT
    if limit < MIN_TRANSITION_SAMPLE_LIMIT:
        return MIN_TRANSITION_SAMPLE_LIMIT
    if limit > MAX_TRANSITION_SAMPLE_LIMIT:
        return MAX_TRANSITION_SAMPLE_LIMIT
    return limit


@dataclass(frozen=True)
class SlewModel:
    """Diagnostic telescope motion model.

    Parameters
    ----------
    az_rate_deg_per_sec : float
        Assumed azimuth slew rate in degrees per second.
    alt_rate_deg_per_sec : float
        Assumed altitude/elevation slew rate in degrees per second.
    settle_time_sec : float
        Assumed settling overhead after a slew.
    acquisition_time_sec : float
        Assumed acquisition/pointing overhead after a slew.
    exposure_time_sec : float
        Assumed exposure/readout overhead for one observation.

    Notes
    -----
    These values are conservative planning diagnostics only.  They are not
    hardware-authoritative telescope limits.
    """

    az_rate_deg_per_sec: float = 2.0
    alt_rate_deg_per_sec: float = 1.0
    settle_time_sec: float = 5.0
    acquisition_time_sec: float = 10.0
    exposure_time_sec: float = 0.0

    def validated(self) -> "SlewModel":
        """Return a bounded model with physically usable axis rates."""
        az_rate = _finite_bounded(
            self.az_rate_deg_per_sec,
            default=DEFAULT_SLEW_MODEL.az_rate_deg_per_sec if "DEFAULT_SLEW_MODEL" in globals() else 2.0,
            minimum=MIN_SLEW_RATE_DEG_PER_SEC,
            maximum=MAX_SLEW_RATE_DEG_PER_SEC,
        )
        alt_rate = _finite_bounded(
            self.alt_rate_deg_per_sec,
            default=DEFAULT_SLEW_MODEL.alt_rate_deg_per_sec if "DEFAULT_SLEW_MODEL" in globals() else 1.0,
            minimum=MIN_SLEW_RATE_DEG_PER_SEC,
            maximum=MAX_SLEW_RATE_DEG_PER_SEC,
        )
        return SlewModel(
            az_rate_deg_per_sec=az_rate,
            alt_rate_deg_per_sec=alt_rate,
            settle_time_sec=_finite_bounded(
                self.settle_time_sec,
                default=0.0,
                minimum=0.0,
                maximum=MAX_SLEW_OVERHEAD_SEC,
            ),
            acquisition_time_sec=_finite_bounded(
                self.acquisition_time_sec,
                default=0.0,
                minimum=0.0,
                maximum=MAX_SLEW_OVERHEAD_SEC,
            ),
            exposure_time_sec=_finite_bounded(
                self.exposure_time_sec,
                default=0.0,
                minimum=0.0,
                maximum=MAX_SLEW_OVERHEAD_SEC,
            ),
        )


DEFAULT_SLEW_MODEL = SlewModel()


def _finite_bounded(value: object, *, default: float, minimum: float, maximum: float) -> float:
    """Return ``value`` as a finite float bounded to an inclusive interval."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not np.isfinite(number):
        return float(default)
    if number < minimum:
        return float(default)
    if number > maximum:
        return float(maximum)
    return float(number)


def azimuth_delta_deg(from_az: object, to_az: object) -> float:
    """Return shortest wrapped azimuth distance in degrees.

    Parameters
    ----------
    from_az, to_az : object
        Azimuth values in degrees.

    Returns
    -------
    float
        Absolute wrapped angular distance in the interval [0, 180].
    """
    start = float(from_az)
    stop = float(to_az)
    return float(abs(((stop - start + 180.0) % 360.0) - 180.0))


def _resolve_optional(df: pd.DataFrame, logical: str) -> str | None:
    """Resolve an optional logical observation-planner column."""
    if df is None or df.empty:
        return None
    try:
        return resolve_column(df, logical, required=False)
    except Exception:
        return None


def _empty_summary(*, reason_unavailable: str | None, model: SlewModel, sample_limit: int = DEFAULT_TRANSITION_SAMPLE_LIMIT) -> dict[str, Any]:
    """Return a complete empty slew/path summary dictionary."""
    available = reason_unavailable is None
    return {
        "available": available,
        "reason_unavailable": reason_unavailable,
        "coordinate_model": "alt_az",
        "transition_count": 0,
        "total_az_delta_deg": 0.0 if available else None,
        "total_alt_delta_deg": 0.0 if available else None,
        "total_axis_path_deg": 0.0 if available else None,
        "max_single_axis_delta_deg": None,
        "median_single_axis_delta_deg": None,
        "total_estimated_slew_sec": 0.0 if available else None,
        "median_estimated_slew_sec": None,
        "max_estimated_slew_sec": None,
        "total_estimated_transition_sec": 0.0 if available else None,
        "median_slack_sec": None,
        "min_slack_sec": None,
        "transition_violation_count": 0,
        "transition_violation_fraction": 0.0 if available else None,
        "model_az_rate_deg_per_sec": float(model.az_rate_deg_per_sec),
        "model_alt_rate_deg_per_sec": float(model.alt_rate_deg_per_sec),
        "model_settle_time_sec": float(model.settle_time_sec),
        "model_acquisition_time_sec": float(model.acquisition_time_sec),
        "model_exposure_time_sec": float(model.exposure_time_sec),
        "transition_sample_limit": int(validate_transition_sample_limit(sample_limit)),
    }


def _sample_records(records: list[dict[str, Any]], limit: int) -> tuple[dict[str, Any], ...]:
    """Return a deterministic bounded tuple of transition records."""
    if limit <= 0:
        return tuple()
    if len(records) <= limit:
        return tuple(records)
    indices = np.linspace(0, len(records) - 1, int(limit), dtype=int)
    return tuple(records[int(index)] for index in indices)


def _plot_values(records: list[dict[str, Any]], key: str, limit: int) -> list[Any]:
    """Return bounded values from transition records for plot diagnostics."""
    sampled = _sample_records(records, limit)
    return [record.get(key) for record in sampled]


def unavailable_slew_path_diagnostics(
    *,
    model: SlewModel | None = None,
    sample_limit: int = DEFAULT_TRANSITION_SAMPLE_LIMIT,
    reason: str = "Slew/path diagnostics disabled by user preference.",
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], dict[str, Any]]:
    """Return stable unavailable diagnostics with the active model values.

    Parameters
    ----------
    model : SlewModel, optional
        Diagnostic motion model whose validated values should be reported.
    sample_limit : int, optional
        Configured transition sample limit to report.
    reason : str, optional
        User-facing reason for unavailable diagnostics.

    Returns
    -------
    summary, transitions, plot_series : tuple
        Stable disabled diagnostics structures.
    """
    active_model = (model or DEFAULT_SLEW_MODEL).validated()
    return _empty_summary(
        reason_unavailable=reason,
        model=active_model,
        sample_limit=validate_transition_sample_limit(sample_limit),
    ), tuple(), {
        "transition_available_time_sec": [],
        "transition_slew_sec": [],
        "transition_slack_sec": [],
        "transition_az_delta_deg": [],
        "transition_alt_delta_deg": [],
        "transition_violation_flags": [],
    }


def compute_slew_path_diagnostics(
    plan_df: pd.DataFrame,
    *,
    model: SlewModel | None = None,
    sample_limit: int = DEFAULT_TRANSITION_SAMPLE_LIMIT,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], dict[str, Any]]:
    """Compute diagnostic slew/path metrics for a selected plan.

    Parameters
    ----------
    plan_df : pandas.DataFrame
        Selected observation plan.  It is copied defensively and never mutated.
    model : SlewModel, optional
        Diagnostic motion model.  Defaults to :data:`DEFAULT_SLEW_MODEL`.
    sample_limit : int, optional
        Maximum number of per-transition records and plot points to retain.

    Returns
    -------
    summary, transitions, plot_series : tuple
        JSON-serializable aggregate summary, bounded transition records, and
        plot-ready series.  Empty/unavailable diagnostics are explicit.
    """
    active_model = (model or DEFAULT_SLEW_MODEL).validated()
    active_sample_limit = validate_transition_sample_limit(sample_limit)
    if plan_df is None or plan_df.empty:
        return _empty_summary(
            reason_unavailable="No selected observation plan rows.",
            model=active_model,
            sample_limit=active_sample_limit,
        ), tuple(), {}

    plan = plan_df.copy().reset_index(drop=False).rename(columns={"index": "_original_row"})
    if len(plan) < 2:
        return _empty_summary(reason_unavailable=None, model=active_model, sample_limit=active_sample_limit), tuple(), {
            "transition_available_time_sec": [],
            "transition_slew_sec": [],
            "transition_slack_sec": [],
            "transition_az_delta_deg": [],
            "transition_alt_delta_deg": [],
            "transition_violation_flags": [],
        }

    date_col = "datetime" if "datetime" in plan.columns else _resolve_optional(plan, "date_ut")
    az_col = _resolve_optional(plan, "az")
    alt_col = _resolve_optional(plan, "elev")
    sat_col = _resolve_optional(plan, "satellite")

    missing = [name for name, column in (("time", date_col), ("az", az_col), ("elev", alt_col)) if column is None]
    if missing:
        reason = f"Missing required slew/path diagnostic column(s): {', '.join(missing)}."
        return _empty_summary(reason_unavailable=reason, model=active_model, sample_limit=active_sample_limit), tuple(), {}

    plan["_diag_time"] = pd.to_datetime(plan[date_col], errors="coerce", utc=True)
    plan["_diag_az"] = pd.to_numeric(plan[az_col], errors="coerce")
    plan["_diag_alt"] = pd.to_numeric(plan[alt_col], errors="coerce")
    valid_mask = plan["_diag_time"].notna() & np.isfinite(plan["_diag_az"]) & np.isfinite(plan["_diag_alt"])
    if not bool(valid_mask.all()):
        invalid_count = int((~valid_mask).sum())
        reason = f"Invalid slew/path diagnostic time, azimuth, or elevation value(s): {invalid_count} row(s)."
        return _empty_summary(reason_unavailable=reason, model=active_model, sample_limit=active_sample_limit), tuple(), {}

    plan = plan.sort_values("_diag_time", kind="mergesort").reset_index(drop=True)
    records: list[dict[str, Any]] = []
    for position in range(len(plan) - 1):
        first = plan.iloc[position]
        second = plan.iloc[position + 1]
        available_time_sec = float((second["_diag_time"] - first["_diag_time"]).total_seconds())
        az_delta = azimuth_delta_deg(first["_diag_az"], second["_diag_az"])
        alt_delta = float(abs(float(second["_diag_alt"]) - float(first["_diag_alt"])))
        axis_limited_slew_sec = max(
            az_delta / active_model.az_rate_deg_per_sec,
            alt_delta / active_model.alt_rate_deg_per_sec,
        )
        estimated_transition_sec = (
            axis_limited_slew_sec
            + active_model.settle_time_sec
            + active_model.acquisition_time_sec
            + active_model.exposure_time_sec
        )
        slack_sec = available_time_sec - estimated_transition_sec
        from_satellite = str(first[sat_col]) if sat_col else None
        to_satellite = str(second[sat_col]) if sat_col else None
        records.append(
            {
                "from_row": int(first["_original_row"]),
                "to_row": int(second["_original_row"]),
                "from_time_utc": first["_diag_time"].isoformat(),
                "to_time_utc": second["_diag_time"].isoformat(),
                "from_satellite": from_satellite,
                "to_satellite": to_satellite,
                "available_time_sec": available_time_sec,
                "az_delta_deg": float(az_delta),
                "alt_delta_deg": float(alt_delta),
                "axis_limited_slew_sec": float(axis_limited_slew_sec),
                "estimated_transition_sec": float(estimated_transition_sec),
                "slack_sec": float(slack_sec),
                "violates_model": bool(slack_sec < 0.0),
            }
        )

    az_values = pd.Series([record["az_delta_deg"] for record in records], dtype="float64")
    alt_values = pd.Series([record["alt_delta_deg"] for record in records], dtype="float64")
    single_axis_values = pd.Series(
        [max(record["az_delta_deg"], record["alt_delta_deg"]) for record in records],
        dtype="float64",
    )
    slew_values = pd.Series([record["axis_limited_slew_sec"] for record in records], dtype="float64")
    transition_values = pd.Series([record["estimated_transition_sec"] for record in records], dtype="float64")
    slack_values = pd.Series([record["slack_sec"] for record in records], dtype="float64")
    violation_count = int(sum(bool(record["violates_model"]) for record in records))

    summary = {
        "available": True,
        "reason_unavailable": None,
        "coordinate_model": "alt_az",
        "transition_count": int(len(records)),
        "total_az_delta_deg": float(az_values.sum()),
        "total_alt_delta_deg": float(alt_values.sum()),
        "total_axis_path_deg": float(single_axis_values.sum()),
        "max_single_axis_delta_deg": float(single_axis_values.max()),
        "median_single_axis_delta_deg": float(single_axis_values.median()),
        "total_estimated_slew_sec": float(slew_values.sum()),
        "median_estimated_slew_sec": float(slew_values.median()),
        "max_estimated_slew_sec": float(slew_values.max()),
        "total_estimated_transition_sec": float(transition_values.sum()),
        "median_slack_sec": float(slack_values.median()),
        "min_slack_sec": float(slack_values.min()),
        "transition_violation_count": violation_count,
        "transition_violation_fraction": float(violation_count / len(records)) if records else 0.0,
        "model_az_rate_deg_per_sec": float(active_model.az_rate_deg_per_sec),
        "model_alt_rate_deg_per_sec": float(active_model.alt_rate_deg_per_sec),
        "model_settle_time_sec": float(active_model.settle_time_sec),
        "model_acquisition_time_sec": float(active_model.acquisition_time_sec),
        "model_exposure_time_sec": float(active_model.exposure_time_sec),
        "transition_sample_limit": int(active_sample_limit),
    }
    bounded_records = _sample_records(records, active_sample_limit)
    plot_series = {
        "transition_available_time_sec": _plot_values(records, "available_time_sec", active_sample_limit),
        "transition_slew_sec": _plot_values(records, "axis_limited_slew_sec", active_sample_limit),
        "transition_slack_sec": _plot_values(records, "slack_sec", active_sample_limit),
        "transition_az_delta_deg": _plot_values(records, "az_delta_deg", active_sample_limit),
        "transition_alt_delta_deg": _plot_values(records, "alt_delta_deg", active_sample_limit),
        "transition_violation_flags": _plot_values(records, "violates_model", active_sample_limit),
    }
    return summary, bounded_records, plot_series
