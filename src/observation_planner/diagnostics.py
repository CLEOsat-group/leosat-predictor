"""Shared observation-plan diagnostics contract.

This module is deliberately GUI- and web-neutral.  It contains only plain
Python, pandas/NumPy-compatible data preparation, and JSON serialization
helpers used by the Observation Planner GUI today and by a future web planner
backend later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from types import SimpleNamespace

import numpy as np
import pandas as pd

from .schema import resolve_column
from .quality import compute_plan_quality
from .impact_diagnostics import unavailable_optimization_impact_summary
from .trust_summary import build_optimization_trust_summary
from .sampling import OPTIMIZATION_OBJECTIVE_QUALITY, OPTIMIZATION_OBJECTIVE_SLEW_AWARE
from .slew_quality import compute_slew_aware_quality_preview
from .transition_constraints import (
    DEFAULT_TRANSITION_CONSTRAINT_MODE,
    DEFAULT_TRANSITION_SAFETY_MARGIN_SEC,
    TRANSITION_CONSTRAINT_PHYSICAL,
    unavailable_transition_constraint_summary,
    normalize_transition_constraint_mode,
    validate_transition_safety_margin_sec,
)
from .slew_diagnostics import (
    DEFAULT_TRANSITION_SAMPLE_LIMIT,
    SlewModel,
    compute_slew_path_diagnostics,
    unavailable_slew_path_diagnostics,
)

SCHEMA_VERSION = "observation_planner.diagnostics.v1"
ALGORITHM_VERSION = "task30.diagnostics.1"
DEFAULT_PLOT_SAMPLE_LIMIT = 5000


def _plain_value(value: Any) -> Any:
    """Return a JSON-serializable scalar value.

    Parameters
    ----------
    value : object
        Arbitrary scalar-like value from pandas/NumPy/Python.

    Returns
    -------
    object
        JSON-compatible scalar, list, or mapping.
    """
    if value is None:
        return None
    if isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not np.isfinite(value):
            return None
        return value
    if isinstance(value, np.generic):
        return _plain_value(value.item())
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain_value(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return str(value)


def _numeric_summary(values: pd.Series) -> dict[str, Any]:
    """Return compact numeric summary statistics for a series."""
    numeric = pd.to_numeric(values, errors="coerce")
    numeric = numeric[np.isfinite(numeric)]
    if numeric.empty:
        return {"count": 0, "min": None, "median": None, "max": None}
    return {
        "count": int(len(numeric)),
        "min": float(numeric.min()),
        "median": float(numeric.median()),
        "max": float(numeric.max()),
    }


def _time_summary(values: pd.Series) -> dict[str, Any]:
    """Return start/end summary for datetime-like values."""
    timestamps = pd.to_datetime(values, errors="coerce", utc=True).dropna()
    if timestamps.empty:
        return {"start_utc": None, "end_utc": None}
    return {
        "start_utc": timestamps.min().isoformat(),
        "end_utc": timestamps.max().isoformat(),
    }


def _sample_list(values: pd.Series, limit: int = DEFAULT_PLOT_SAMPLE_LIMIT) -> list[Any]:
    """Return a deterministic bounded list from a series for diagnostics plots."""
    if values is None:
        return []
    series = pd.Series(values).dropna().reset_index(drop=True)
    if len(series) <= limit:
        return [_plain_value(value) for value in series.tolist()]
    indices = np.linspace(0, len(series) - 1, limit, dtype=int)
    return [_plain_value(value) for value in series.iloc[indices].tolist()]


def _datetime_epoch_seconds(values: pd.Series, limit: int = DEFAULT_PLOT_SAMPLE_LIMIT) -> list[float]:
    """Return bounded UTC epoch-second values for datetime-like values."""
    timestamps = pd.to_datetime(values, errors="coerce", utc=True).dropna().reset_index(drop=True)
    if len(timestamps) == 0:
        return []
    if len(timestamps) > limit:
        indices = np.linspace(0, len(timestamps) - 1, limit, dtype=int)
        timestamps = timestamps.iloc[indices]
    epoch_ns = timestamps.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]").astype("int64")
    return [float(value) / 1.0e9 for value in epoch_ns]


def _spacing_minutes(plan_df: pd.DataFrame, date_col: str = "datetime") -> list[float]:
    """Return chronological spacing deltas in minutes."""
    if plan_df is None or plan_df.empty or date_col not in plan_df.columns:
        return []
    timestamps = pd.to_datetime(plan_df[date_col], errors="coerce", utc=True).dropna().sort_values()
    if len(timestamps) < 2:
        return []
    deltas = timestamps.diff().dropna().dt.total_seconds() / 60.0
    return [float(value) for value in deltas if np.isfinite(value)]


def _spacing_summary(plan_df: pd.DataFrame, spacing_min: float, date_col: str = "datetime") -> dict[str, Any]:
    """Return spacing diagnostics for a selected plan."""
    deltas = _spacing_minutes(plan_df, date_col=date_col)
    if not deltas:
        violations = 0
        minimum = median = maximum = None
    else:
        spacing = float(spacing_min)
        violations = int(sum(value < spacing for value in deltas))
        minimum = float(min(deltas))
        median = float(pd.Series(deltas).median())
        maximum = float(max(deltas))
    return {
        "requested_spacing_min": float(spacing_min),
        "spacing_relaxed": False,
        "distribution_relaxed": False,
        "spacing_violations": violations,
        "min_actual_spacing_min": minimum,
        "median_actual_spacing_min": median,
        "max_actual_spacing_min": maximum,
        "spacing_deltas_minutes": deltas,
    }


def _selected_row_records(
    selected_df: pd.DataFrame,
    *,
    metric_col: str | None = None,
    bin_col: str | None = None,
    pass_col: str | None = None,
) -> list[dict[str, Any]]:
    """Return reproducibility row identifiers from selected plan rows."""
    if selected_df is None or selected_df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for row_number, (_, row) in enumerate(selected_df.iterrows()):
        record: dict[str, Any] = {"output_row": row_number}
        for column in ("global_index", "base_index", "local_index", "source", "satellite", "datetime", "date_ut"):
            if column in selected_df.columns:
                record[column] = _plain_value(row[column])
        if metric_col and metric_col in selected_df.columns:
            record["metric_value"] = _plain_value(row[metric_col])
        if bin_col and bin_col in selected_df.columns:
            record["bin_id"] = _plain_value(row[bin_col])
        if pass_col and pass_col in selected_df.columns:
            record["pass_id"] = _plain_value(row[pass_col])
        rows.append(record)
    return rows


@dataclass(frozen=True)
class PlanGenerationDiagnostics:
    """Method-neutral diagnostics for one observation-plan generation run."""

    method: str
    mode: str
    compact_summary: str
    run_summary: dict[str, Any]
    input_summary: dict[str, Any]
    filtering_summary: dict[str, Any]
    candidate_reduction_summary: dict[str, Any]
    bin_summary: dict[str, Any]
    spacing_summary: dict[str, Any]
    output_summary: dict[str, Any]
    selected_row_ids: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    plot_series: dict[str, Any] = field(default_factory=dict)
    quality_metrics: dict[str, Any] = field(default_factory=dict)
    multi_start_summary: dict[str, Any] = field(default_factory=dict)
    local_repair_summary: dict[str, Any] = field(default_factory=dict)
    slew_path_summary: dict[str, Any] = field(default_factory=dict)
    slew_path_transitions: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    slew_aware_quality_preview: dict[str, Any] = field(default_factory=dict)
    optimization_impact_summary: dict[str, Any] = field(default_factory=dict)
    optimization_trust_summary: dict[str, Any] = field(default_factory=dict)
    quality_score_summary: str = ""
    quality_lexicographic_score: tuple[Any, ...] = field(default_factory=tuple)
    schema_version: str = SCHEMA_VERSION
    algorithm_version: str = ALGORITHM_VERSION

    @property
    def input_rows(self) -> int:
        """Return legacy diagnostics input count for compatibility.

        Task 29 sampling diagnostics used this field for the candidate-pool
        size after mode/target-window restriction.  The richer Task 30 input
        summary still preserves the full original visibility row count.
        """
        candidate_rows = self.candidate_reduction_summary.get("candidate_rows")
        if candidate_rows is not None:
            return int(candidate_rows)
        return int(self.input_summary.get("input_rows") or 0)

    @property
    def filtered_rows(self) -> int:
        """Return filtered row count."""
        return int(self.filtering_summary.get("rows_after_filtering") or 0)

    @property
    def selected_rows(self) -> int:
        """Return selected row count for compatibility with Task 29 diagnostics."""
        return int(self.output_summary.get("selected_rows") or 0)

    @property
    def candidate_rows(self) -> int:
        """Return candidate row count."""
        return int(self.candidate_reduction_summary.get("candidate_rows") or 0)

    @property
    def reduced_candidate_rows(self) -> int:
        """Return reduced candidate row count."""
        return int(self.candidate_reduction_summary.get("reduced_candidate_rows") or 0)

    @property
    def achieved_bins(self) -> int:
        """Return achieved bin count."""
        return int(self.bin_summary.get("achieved_bins") or 0)

    @property
    def metric(self) -> str | None:
        """Return selected sampling metric when available."""
        return self.run_summary.get("metric")

    @property
    def actual_bins(self) -> int:
        """Return available/actual bin count."""
        return int(self.bin_summary.get("actual_bins") or 0)

    @property
    def invalid_metric_rows(self) -> int:
        """Return invalid metric row count."""
        return int(self.filtering_summary.get("invalid_metric_rows") or 0)

    def resolved_optimization_trust_summary(self) -> dict[str, Any]:
        """Return the operator-facing optimization trust summary.

        The summary is intentionally derived from current diagnostics fields so
        dataclass-replaced diagnostics, such as Task 35F baseline-comparison
        results, cannot carry stale trust text.
        """
        return build_optimization_trust_summary(self)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable diagnostics."""
        return {
            "schema_version": self.schema_version,
            "algorithm_version": self.algorithm_version,
            "method": self.method,
            "mode": self.mode,
            "compact_summary": self.compact_summary,
            "run_summary": _plain_value(self.run_summary),
            "input_summary": _plain_value(self.input_summary),
            "filtering_summary": _plain_value(self.filtering_summary),
            "candidate_reduction_summary": _plain_value(self.candidate_reduction_summary),
            "bin_summary": _plain_value(self.bin_summary),
            "spacing_summary": _plain_value(self.spacing_summary),
            "output_summary": _plain_value(self.output_summary),
            "selected_rows": _plain_value(list(self.selected_row_ids)),
            "plot_series": _plain_value(self.plot_series),
            "quality_metrics": _plain_value(self.quality_metrics),
            "multi_start_summary": _plain_value(self.multi_start_summary),
            "local_repair_summary": _plain_value(self.local_repair_summary),
            "slew_path_summary": _plain_value(self.slew_path_summary),
            "slew_path_transitions": _plain_value(list(self.slew_path_transitions)),
            "slew_aware_quality_preview": _plain_value(self.slew_aware_quality_preview),
            "optimization_impact_summary": _plain_value(self.optimization_impact_summary),
            "optimization_trust_summary": _plain_value(self.resolved_optimization_trust_summary()),
            "quality_score_summary": _plain_value(self.quality_score_summary),
            "quality_lexicographic_score": _plain_value(self.quality_lexicographic_score),
        }

    def to_log_message(self) -> str:
        """Return the compact level-1 log summary."""
        return self.compact_summary

    def table_sections(self) -> list[tuple[str, dict[str, Any]]]:
        """Return ordered sections for GUI diagnostics tables."""
        sections: list[tuple[str, dict[str, Any]]] = [
            ("Optimization Trust Summary", self.resolved_optimization_trust_summary()),
            ("Optimization Impact Summary", self.optimization_impact_summary),
            ("Run Summary", self.run_summary),
        ]
        if self.multi_start_summary:
            sections.append(("Multi-Start Optimization", self.multi_start_summary))
        sections.append(("Physical Transition Constraint", self.run_summary.get("transition_constraint_summary", {})))
        sections.append(("Slew / Path Summary", self.slew_path_summary))
        sections.append(
            (
                "Plan Quality",
                {
                    "quality_score_summary": self.quality_score_summary,
                    "quality_lexicographic_score": list(self.quality_lexicographic_score),
                    **dict(self.quality_metrics or {}),
                },
            )
        )
        if self.local_repair_summary:
            repair_title = (
                "Local Repair Dry-Run"
                if self.local_repair_summary.get("repair_dry_run", True)
                else "Local Repair"
            )
            sections.append((repair_title, self.local_repair_summary))
        sections.extend(
            [
                ("Input Summary", self.input_summary),
                ("Filtering Summary", self.filtering_summary),
                ("Candidate Reduction Summary", self.candidate_reduction_summary),
                ("Bin Summary", self.bin_summary),
                ("Spacing Summary", self.spacing_summary),
                ("Slew-Aware Quality Preview", self.slew_aware_quality_preview),
                ("Output Summary", self.output_summary),
                ("Selected Row IDs / Reproducibility", {"selected_rows": list(self.selected_row_ids)}),
            ]
        )
        return sections





def _normalize_metric_logical(metric_name: object) -> str:
    """Return the canonical logical column name for a planner metric.

    Parameters
    ----------
    metric_name : object
        Metric identifier from planner diagnostics or sampling diagnostics.

    Returns
    -------
    str
        Canonical logical column name resolvable through the observation planner
        schema.
    """
    name = str(metric_name or "elev").strip().lower()
    if name in {"solar_phase", "solar_phase_angle", "phase", "phase_angle"}:
        return "solar_phase_angle"
    if name in {"elevation", "elev", "sat_elev", "satellite_elevation"}:
        return "elev"
    return name


def _metric_display_metadata(metric_name: object) -> dict[str, str]:
    """Return stable display metadata for a diagnostics metric.

    Parameters
    ----------
    metric_name : object
        Logical metric identifier from the executed planner method.

    Returns
    -------
    dict[str, str]
        JSON-safe metadata containing a display label and physical unit.
    """
    logical = _normalize_metric_logical(metric_name)
    if logical == "solar_phase_angle":
        return {"metric_label": "Solar phase angle [deg]", "metric_unit": "deg"}
    return {"metric_label": "Elevation [deg]", "metric_unit": "deg"}


def _safe_identity_key(value: Any) -> str | None:
    """Return a stable string key for row-identity comparisons.

    Parameters
    ----------
    value : object
        Row identity value from a plan row or visibility row.

    Returns
    -------
    str or None
        Normalized key, or ``None`` for missing/invalid values.
    """
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


def _match_plan_rows_to_visibility(
    current_plan: pd.DataFrame,
    source_visibility: pd.DataFrame | None,
) -> pd.DataFrame:
    """Return source visibility rows matching the current observation plan.

    The diagnostics plots must represent the same rows that are visible in the
    Observation Plan table.  The plan table stores hidden row identity fields
    where available; this helper uses those identifiers to recover the exact
    source visibility rows so diagnostic plot points cannot drift from the
    loaded visibility table.

    Parameters
    ----------
    current_plan : pandas.DataFrame
        Current observation-plan rows, including hidden metadata when available.
    source_visibility : pandas.DataFrame or None
        Prepared visibility table, preferably ``data_master``.

    Returns
    -------
    pandas.DataFrame
        Matched source rows in observation-plan order.  Falls back to
        ``current_plan`` when exact matching is not possible.
    """
    if current_plan is None or current_plan.empty:
        return pd.DataFrame()
    if source_visibility is None or source_visibility.empty:
        return current_plan.copy()

    source = source_visibility
    matched_rows: list[pd.Series] = []

    identity_columns = ("global_index", "base_index", "local_index")
    identity_maps: dict[str, dict[str, int]] = {}
    for column in identity_columns:
        if column not in source.columns or column not in current_plan.columns:
            continue
        wanted = {
            key
            for key in (_safe_identity_key(value) for value in current_plan[column].to_numpy(copy=False))
            if key is not None
        }
        if not wanted:
            continue
        mapping: dict[str, int] = {}
        for position, value in enumerate(source[column].to_numpy(copy=False)):
            key = _safe_identity_key(value)
            if key in wanted and key not in mapping:
                mapping[key] = int(position)
                if len(mapping) == len(wanted):
                    break
        identity_maps[column] = mapping

    source_sat_col = _resolve_optional(source, "satellite")
    source_date_col = _resolve_optional(source, "date_ut")
    plan_sat_col = _resolve_optional(current_plan, "satellite")
    plan_date_col = _resolve_optional(current_plan, "date_ut") or ("datetime" if "datetime" in current_plan.columns else None)
    fallback_map: dict[tuple[str, pd.Timestamp], int] | None = None

    def _fallback_match_position(plan_row: pd.Series) -> int | None:
        nonlocal fallback_map
        if not (source_sat_col and source_date_col and plan_sat_col and plan_date_col):
            return None
        try:
            plan_time = pd.to_datetime(plan_row[plan_date_col], errors="coerce", utc=True)
            if pd.isna(plan_time):
                return None
            if fallback_map is None:
                fallback_map = {}
                source_times = pd.to_datetime(source[source_date_col], errors="coerce", utc=True)
                satellites = source[source_sat_col].astype(str).to_numpy(copy=False)
                for position, (satellite, timestamp) in enumerate(zip(satellites, source_times, strict=False)):
                    if pd.isna(timestamp):
                        continue
                    key = (str(satellite), timestamp)
                    if key not in fallback_map:
                        fallback_map[key] = int(position)
            return fallback_map.get((str(plan_row[plan_sat_col]), plan_time))
        except Exception:
            return None

    for _, plan_row in current_plan.iterrows():
        matched_row: pd.Series | None = None

        for column in identity_columns:
            if column not in current_plan.columns or column not in identity_maps:
                continue
            key = _safe_identity_key(plan_row.get(column))
            position = identity_maps[column].get(key) if key is not None else None
            if position is not None:
                matched_row = source.iloc[int(position)].copy()
                break

        if matched_row is None:
            position = _fallback_match_position(plan_row)
            if position is not None:
                matched_row = source.iloc[int(position)].copy()

        if matched_row is None:
            matched_row = plan_row.copy()

        # Preserve plan-table source state for diagnostics even when values come
        # from the source visibility row.
        for column in ("source", "global_index", "base_index", "local_index"):
            if column in current_plan.columns and column not in matched_row.index:
                matched_row[column] = plan_row[column]
            elif column == "source" and column in current_plan.columns:
                matched_row[column] = plan_row[column]

        matched_rows.append(matched_row)

    if not matched_rows:
        return current_plan.copy()
    return pd.DataFrame(matched_rows).reset_index(drop=True)

def refresh_diagnostics_for_current_plan(
    diagnostics: PlanGenerationDiagnostics | None,
    current_plan: pd.DataFrame,
    *,
    spacing_min: float,
    source_visibility: pd.DataFrame | None = None,
    slew_model: SlewModel | None = None,
    slew_diagnostics_enabled: bool = True,
    slew_transition_sample_limit: int = DEFAULT_TRANSITION_SAMPLE_LIMIT,
    transition_constraint_mode: str | None = None,
    transition_safety_margin_sec: float | None = None,
) -> PlanGenerationDiagnostics | None:
    """Return diagnostics updated for the currently visible observation plan.

    Manual plan-table edits should not discard the generation diagnostics.  The
    original run/input/filtering/candidate/bin sections remain the audit trail
    for how the generated plan was created, while spacing, output, selected row
    identities, and selected plot series are refreshed from the current visible
    plan rows.

    Parameters
    ----------
    diagnostics : PlanGenerationDiagnostics or None
        Existing backend diagnostics from the last generated plan.
    current_plan : pandas.DataFrame
        Current observation-plan table, including generated and manually added
        rows.
    spacing_min : float
        Required minimum spacing in minutes.
    source_visibility : pandas.DataFrame or None, optional
        Prepared visibility table used to recover exact source rows by
        ``global_index``/``base_index``/``local_index``.  When supplied,
        current-plan diagnostic plot points are derived from the same source rows
        as the visibility table.
    slew_model : SlewModel or None, optional
        Diagnostics-only telescope motion model.  The model must not affect
        observation selection.
    slew_diagnostics_enabled : bool, optional
        If `False`, return a stable disabled slew/path diagnostics summary.
    slew_transition_sample_limit : int, optional
        Maximum number of slew transition records and plot points retained.

    Returns
    -------
    PlanGenerationDiagnostics or None
        Updated diagnostics, or ``None`` when no diagnostics/current plan exists.
    """
    if diagnostics is None:
        return None
    if current_plan is None or current_plan.empty:
        return None

    plan_df = current_plan.copy()
    source_plan_df = _match_plan_rows_to_visibility(plan_df, source_visibility)

    date_col = "datetime" if "datetime" in plan_df.columns else _resolve_optional(plan_df, "date_ut")
    source_date_col = "datetime" if "datetime" in source_plan_df.columns else _resolve_optional(source_plan_df, "date_ut")
    metric_name = _normalize_metric_logical(diagnostics.run_summary.get("metric") or "elev")
    metric_col = _resolve_optional(plan_df, metric_name) or _resolve_optional(plan_df, "elev")
    source_metric_col = _resolve_optional(source_plan_df, metric_name) or _resolve_optional(source_plan_df, "elev")

    spacing = _spacing_summary(plan_df, spacing_min, date_col=date_col or "datetime")
    selected_identity = _selected_row_records(source_plan_df, metric_col=source_metric_col)
    selected_global_indices = [
        item.get("global_index") for item in selected_identity if item.get("global_index") is not None
    ]

    output_metric_summary: dict[str, Any] = {}
    if source_metric_col and source_metric_col in source_plan_df.columns:
        output_metric_summary = _numeric_summary(source_plan_df[source_metric_col])
    elif metric_col and metric_col in plan_df.columns:
        output_metric_summary = _numeric_summary(plan_df[metric_col])

    output_summary = dict(diagnostics.output_summary)
    output_summary.update(
        {
            "selected_rows": int(len(plan_df)),
            "selected_global_indices": selected_global_indices,
            "metric_summary": output_metric_summary,
            "time_range": _time_summary(source_plan_df[source_date_col]) if source_date_col else (_time_summary(plan_df[date_col]) if date_col else {}),
            "manual_rows": int((plan_df.get("source") == "manual").sum()) if "source" in plan_df.columns else None,
            "generated_rows": int((plan_df.get("source") == "plan").sum()) if "source" in plan_df.columns else None,
            "manually_adjusted": True,
        }
    )

    plot_series = dict(diagnostics.plot_series or {})
    metric_display = _metric_display_metadata(diagnostics.run_summary.get("metric") or metric_name)
    plot_series.setdefault("metric_name", diagnostics.run_summary.get("metric") or metric_name)
    plot_series.update(metric_display)
    selected_metric = pd.Series(dtype="float64")
    if source_metric_col and source_metric_col in source_plan_df.columns:
        selected_metric = pd.to_numeric(source_plan_df[source_metric_col], errors="coerce")
    elif metric_col and metric_col in plan_df.columns:
        selected_metric = pd.to_numeric(plan_df[metric_col], errors="coerce")
    plot_series["selected_times"] = _datetime_epoch_seconds(source_plan_df[source_date_col]) if source_date_col else (_datetime_epoch_seconds(plan_df[date_col]) if date_col else [])
    plot_series["selected_metric_values"] = _sample_list(selected_metric)
    plot_series["metric_selected_values"] = _sample_list(selected_metric)
    plot_series["spacing_deltas_minutes"] = spacing["spacing_deltas_minutes"]
    plot_series["selected_source_row_count"] = int(len(source_plan_df))
    if slew_diagnostics_enabled:
        slew_path_summary, slew_path_transitions, slew_plot_series = compute_slew_path_diagnostics(
            source_plan_df,
            model=slew_model,
            sample_limit=slew_transition_sample_limit,
        )
    else:
        slew_path_summary, slew_path_transitions, slew_plot_series = unavailable_slew_path_diagnostics(
            model=slew_model,
            sample_limit=slew_transition_sample_limit,
        )
    plot_series.update(slew_plot_series)

    quality_bin_records = []
    for item in diagnostics.bin_summary.get("bin_diagnostics", []) if isinstance(diagnostics.bin_summary, dict) else []:
        if isinstance(item, Mapping):
            quality_bin_records.append({"selected_count": item.get("selected_count", 0)})
    quality_source = SimpleNamespace(
        actual_bins=diagnostics.bin_summary.get("actual_bins") if isinstance(diagnostics.bin_summary, dict) else 0,
        achieved_bins=diagnostics.bin_summary.get("achieved_bins") if isinstance(diagnostics.bin_summary, dict) else 0,
        bin_diagnostics=tuple(quality_bin_records),
    )
    quality_score = compute_plan_quality(
        selected_plan=source_plan_df,
        candidate_df=source_visibility if source_visibility is not None else source_plan_df,
        spacing_min=float(spacing_min),
        metric_logical=metric_name,
        sampling_diagnostics=quality_source,
        selected_row_records=selected_identity,
    )
    slew_aware_quality_preview = compute_slew_aware_quality_preview(
        quality_metrics=quality_score.metrics.to_dict(),
        slew_path_summary=slew_path_summary,
        active_for_selection=(
            diagnostics.run_summary.get("optimization_objective", OPTIMIZATION_OBJECTIVE_QUALITY)
            == OPTIMIZATION_OBJECTIVE_SLEW_AWARE
        ),
    )
    existing_transition_summary = dict(diagnostics.run_summary.get("transition_constraint_summary", {}) or {})
    transition_summary = dict(existing_transition_summary) if existing_transition_summary else unavailable_transition_constraint_summary(
        mode=transition_constraint_mode or diagnostics.run_summary.get("transition_constraint", DEFAULT_TRANSITION_CONSTRAINT_MODE),
        reason="manual_refresh_diagnostics_only",
        safety_margin_sec=(
            transition_safety_margin_sec
            if transition_safety_margin_sec is not None
            else diagnostics.run_summary.get("transition_safety_margin_sec", DEFAULT_TRANSITION_SAFETY_MARGIN_SEC)
        ),
        input_rows=len(plan_df),
        selected_rows=len(plan_df),
    )

    compact_summary = (
        f"Plan diagnostics: method={diagnostics.method}, mode={diagnostics.mode}, "
        f"input={diagnostics.input_summary.get('input_rows')}, selected={len(plan_df)}, "
        f"manual_rows={output_summary.get('manual_rows')}, generated_rows={output_summary.get('generated_rows')}, "
        f"spacing_violations={spacing.get('spacing_violations')}"
    )
    if diagnostics.bin_summary.get("available"):
        compact_summary += (
            f", bins={diagnostics.bin_summary.get('achieved_bins')}/"
            f"{diagnostics.bin_summary.get('actual_bins')}, "
            f"seed={diagnostics.run_summary.get('random_seed')}"
        )
    compact_summary += f". {quality_score.compact_summary}"

    return PlanGenerationDiagnostics(
        method=diagnostics.method,
        mode=diagnostics.mode,
        compact_summary=compact_summary,
        run_summary={**dict(diagnostics.run_summary), **metric_display, "transition_constraint_summary": transition_summary},
        input_summary=dict(diagnostics.input_summary),
        filtering_summary=dict(diagnostics.filtering_summary),
        candidate_reduction_summary=dict(diagnostics.candidate_reduction_summary),
        bin_summary=dict(diagnostics.bin_summary),
        spacing_summary=spacing,
        output_summary=output_summary,
        selected_row_ids=tuple(selected_identity),
        plot_series=plot_series,
        quality_metrics=quality_score.metrics.to_dict(),
        multi_start_summary=dict(diagnostics.multi_start_summary or {}),
        local_repair_summary=dict(diagnostics.local_repair_summary or {}),
        slew_path_summary=slew_path_summary,
        slew_path_transitions=tuple(slew_path_transitions),
        slew_aware_quality_preview=slew_aware_quality_preview,
        optimization_impact_summary=unavailable_optimization_impact_summary("Manual plan refresh; baseline comparison not recomputed."),
        optimization_trust_summary={},
        quality_score_summary=quality_score.compact_summary,
        quality_lexicographic_score=quality_score.lexicographic_score,
        schema_version=diagnostics.schema_version,
        algorithm_version=diagnostics.algorithm_version,
    )


def diagnostics_sidecar_path(path: str | Path) -> Path:
    """Return the diagnostics JSON sidecar path for an exported plan file."""
    file_path = Path(path)
    return file_path.with_name(f"{file_path.stem}_diagnostics.json")


def write_diagnostics_json(diagnostics: PlanGenerationDiagnostics, path: str | Path) -> Path:
    """Write diagnostics as JSON and return the output path."""
    output_path = Path(path)
    output_path.write_text(
        json.dumps(diagnostics.to_dict(), indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path


def _resolve_optional(df: pd.DataFrame, logical: str) -> str | None:
    """Resolve an optional logical column without raising."""
    if df is None or df.empty:
        return None
    try:
        return resolve_column(df, logical, required=False)
    except Exception:
        return None


def build_plan_generation_diagnostics(
    *,
    method: str,
    mode: str,
    input_df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    candidate_df: pd.DataFrame,
    plan_before_spacing: pd.DataFrame,
    selected_plan: pd.DataFrame,
    spacing_min: float,
    metric_logical: str = "elev",
    sampling_diagnostics: Any | None = None,
    slew_model: SlewModel | None = None,
    slew_diagnostics_enabled: bool = True,
    slew_transition_sample_limit: int = DEFAULT_TRANSITION_SAMPLE_LIMIT,
    transition_constraint_mode: str = DEFAULT_TRANSITION_CONSTRAINT_MODE,
    transition_safety_margin_sec: float = DEFAULT_TRANSITION_SAFETY_MARGIN_SEC,
) -> PlanGenerationDiagnostics:
    """Build method-neutral diagnostics from planner dataframes.

    Parameters
    ----------
    method : str
        Backend plan-method identifier.
    mode : str
        Planner mode identifier, e.g. ``auto_sequence`` or ``json_times``.
    input_df : pandas.DataFrame
        Input visibility rows before planner filtering.
    filtered_df : pandas.DataFrame
        Visibility rows after min-elevation/timestamp/satellite filtering.
    candidate_df : pandas.DataFrame
        Candidate rows handed to the final plan selection step.
    plan_before_spacing : pandas.DataFrame
        Rows selected by the plan method before final spacing filtering.
    selected_plan : pandas.DataFrame
        Final selected plan rows.
    spacing_min : float
        Required minimum spacing in minutes.
    metric_logical : str, optional
        Logical metric used for distribution plots.
    sampling_diagnostics : object, optional
        Task 29 sampling diagnostics, when generated by a stratified method.
    slew_model : SlewModel or None, optional
        Diagnostics-only telescope motion model.  The model must not affect
        planner selection or row ordering.
    slew_diagnostics_enabled : bool, optional
        If `False`, include a stable disabled slew/path diagnostics summary.
    slew_transition_sample_limit : int, optional
        Maximum number of slew transition records and plot points retained.

    Returns
    -------
    PlanGenerationDiagnostics
        JSON-serializable diagnostics object.
    """
    metric_logical = _normalize_metric_logical(metric_logical)

    input_rows = 0 if input_df is None else len(input_df)
    filtered_rows = 0 if filtered_df is None else len(filtered_df)
    candidate_rows = 0 if candidate_df is None else len(candidate_df)
    pre_spacing_rows = 0 if plan_before_spacing is None else len(plan_before_spacing)
    selected_rows_count = 0 if selected_plan is None else len(selected_plan)

    metric_col = _resolve_optional(candidate_df, metric_logical) or _resolve_optional(candidate_df, "elev")
    selected_metric_col = _resolve_optional(selected_plan, metric_logical) or _resolve_optional(selected_plan, "elev")
    date_col = "datetime" if selected_plan is not None and "datetime" in selected_plan.columns else _resolve_optional(selected_plan, "date_ut")
    candidate_date_col = "datetime" if candidate_df is not None and "datetime" in candidate_df.columns else _resolve_optional(candidate_df, "date_ut")

    spacing = _spacing_summary(selected_plan, spacing_min, date_col=date_col or "datetime")
    selected_identity = _selected_row_records(selected_plan, metric_col=selected_metric_col)
    sampling_identity = tuple(getattr(sampling_diagnostics, "selected_row_ids", ()) or ())
    if sampling_identity:
        selected_identity = tuple(dict(item) for item in sampling_identity)
    selected_global_indices = [item.get("global_index") for item in selected_identity if item.get("global_index") is not None]

    multi_start_summary: dict[str, Any] = dict(getattr(sampling_diagnostics, "multi_start_summary", {}) or {})
    local_repair_summary: dict[str, Any] = dict(getattr(sampling_diagnostics, "local_repair_summary", {}) or {})

    bin_summary: dict[str, Any] = {
        "available": sampling_diagnostics is not None,
        "binning_mode": getattr(sampling_diagnostics, "binning_mode", None),
        "requested_bins": getattr(sampling_diagnostics, "requested_bins", None),
        "actual_bins": getattr(sampling_diagnostics, "actual_bins", None),
        "effective_bin_count": getattr(sampling_diagnostics, "actual_bins", None),
        "bin_width_deg": getattr(sampling_diagnostics, "bin_width_deg", None),
        "bin_anchor_policy": getattr(sampling_diagnostics, "bin_anchor_policy", None),
        "bin_domain_min_deg": getattr(sampling_diagnostics, "bin_domain_min_deg", None),
        "bin_domain_max_deg": getattr(sampling_diagnostics, "bin_domain_max_deg", None),
        "achieved_bins": getattr(sampling_diagnostics, "achieved_bins", None),
        "missing_bins": list(getattr(sampling_diagnostics, "missing_bins", ()) or ()),
        "bin_diagnostics": [
            _plain_value(getattr(item, "__dict__", item))
            for item in tuple(getattr(sampling_diagnostics, "bin_diagnostics", ()) or ())
        ],
    }
    if sampling_diagnostics is not None and getattr(sampling_diagnostics, "plot_series", None):
        plot_series = dict(getattr(sampling_diagnostics, "plot_series"))
    else:
        metric_input = pd.Series(dtype="float64")
        metric_selected = pd.Series(dtype="float64")
        if metric_col and candidate_df is not None and metric_col in candidate_df.columns:
            metric_input = pd.to_numeric(candidate_df[metric_col], errors="coerce")
        if selected_metric_col and selected_plan is not None and selected_metric_col in selected_plan.columns:
            metric_selected = pd.to_numeric(selected_plan[selected_metric_col], errors="coerce")
        plot_series = {
            "metric_name": metric_logical,
            "metric_input_values": _sample_list(metric_input),
            "metric_reduced_values": _sample_list(metric_input),
            "metric_selected_values": _sample_list(metric_selected),
            "candidate_times": _datetime_epoch_seconds(candidate_df[candidate_date_col]) if candidate_date_col else [],
            "candidate_metric_values": _sample_list(metric_input),
            "selected_times": _datetime_epoch_seconds(selected_plan[date_col]) if date_col else [],
            "selected_metric_values": _sample_list(metric_selected),
            "spacing_deltas_minutes": spacing["spacing_deltas_minutes"],
            "bin_edges": [],
            "bin_counts_input": [],
            "bin_counts_reduced": [],
            "bin_counts_selected": [],
        }

    executed_metric = getattr(sampling_diagnostics, "metric", metric_logical)
    metric_display = _metric_display_metadata(executed_metric)
    plot_series.setdefault("metric_name", executed_metric)
    plot_series.update(metric_display)

    if slew_diagnostics_enabled:
        slew_path_summary, slew_path_transitions, slew_plot_series = compute_slew_path_diagnostics(
            selected_plan if selected_plan is not None else pd.DataFrame(),
            model=slew_model,
            sample_limit=slew_transition_sample_limit,
        )
    else:
        slew_path_summary, slew_path_transitions, slew_plot_series = unavailable_slew_path_diagnostics(
            model=slew_model,
            sample_limit=slew_transition_sample_limit,
        )
    plot_series.update(slew_plot_series)

    normalized_transition_mode = normalize_transition_constraint_mode(transition_constraint_mode)
    transition_safety_margin = validate_transition_safety_margin_sec(transition_safety_margin_sec)
    selected_attrs = getattr(selected_plan, "attrs", {}) if selected_plan is not None else {}
    transition_summary = dict(selected_attrs.get("transition_constraint_summary", {}) or {})
    if not transition_summary:
        transition_summary = unavailable_transition_constraint_summary(
            mode=normalized_transition_mode,
            reason="time_spacing_only" if normalized_transition_mode != TRANSITION_CONSTRAINT_PHYSICAL else "not_applied",
            safety_margin_sec=transition_safety_margin,
            input_rows=pre_spacing_rows,
            selected_rows=selected_rows_count,
        )
    else:
        transition_summary.setdefault("transition_constraint_mode", normalized_transition_mode)
        transition_summary.setdefault("transition_safety_margin_sec", transition_safety_margin)

    output_metric_summary = {}
    if selected_metric_col and selected_plan is not None and selected_metric_col in selected_plan.columns:
        output_metric_summary = _numeric_summary(selected_plan[selected_metric_col])

    run_summary = {
        "method": method,
        "plan_method": method,
        "mode": mode,
        "metric": executed_metric,
        "metric_label": metric_display["metric_label"],
        "metric_unit": metric_display["metric_unit"],
        "optimization_objective": multi_start_summary.get("optimization_objective", "quality"),
        "transition_constraint": transition_summary.get("transition_constraint_mode", normalized_transition_mode),
        "transition_constraint_mode": transition_summary.get("transition_constraint_mode", normalized_transition_mode),
        "physical_transition_mode_requested": transition_summary.get("physical_transition_mode_requested"),
        "physical_transition_mode_active": transition_summary.get("physical_transition_mode_active"),
        "transition_safety_margin_sec": transition_summary.get("transition_safety_margin_sec", transition_safety_margin),
        "transition_constraint_summary": transition_summary,
        "schema_version": SCHEMA_VERSION,
        "algorithm_version": ALGORITHM_VERSION,
        "random_seed": getattr(sampling_diagnostics, "random_seed", None),
    }
    input_summary = {
        "input_rows": input_rows,
        "input_columns": list(input_df.columns) if input_df is not None else [],
        "time_range": _time_summary(input_df[_resolve_optional(input_df, "date_ut")]) if _resolve_optional(input_df, "date_ut") else {},
    }
    filtering_summary = {
        "rows_after_filtering": filtered_rows,
        "rows_removed_by_filtering": max(0, input_rows - filtered_rows),
        "invalid_metric_rows": getattr(sampling_diagnostics, "invalid_metric_rows", None),
    }
    candidate_reduction_summary = {
        "candidate_rows": candidate_rows,
        "pre_spacing_rows": pre_spacing_rows,
        "reduced_candidate_rows": getattr(sampling_diagnostics, "reduced_candidate_rows", candidate_rows),
        "candidate_depth": getattr(sampling_diagnostics, "candidate_depth", None),
        "pass_groups": getattr(sampling_diagnostics, "pass_groups", None),
    }
    output_summary = {
        "selected_rows": selected_rows_count,
        "selected_global_indices": selected_global_indices,
        "metric_summary": output_metric_summary,
        "time_range": _time_summary(selected_plan[date_col]) if date_col else {},
    }

    quality_trial_index = int(multi_start_summary.get("best_trial_index") or 0)

    quality_score = compute_plan_quality(
        selected_plan=selected_plan if selected_plan is not None else pd.DataFrame(),
        candidate_df=candidate_df if candidate_df is not None else pd.DataFrame(),
        spacing_min=float(spacing_min),
        metric_logical=metric_logical,
        sampling_diagnostics=sampling_diagnostics,
        selected_row_records=selected_identity,
        trial_index=quality_trial_index,
    )
    slew_aware_quality_preview = compute_slew_aware_quality_preview(
        quality_metrics=quality_score.metrics.to_dict(),
        slew_path_summary=slew_path_summary,
        active_for_selection=bool(multi_start_summary.get("slew_aware_selection_active", False)),
    )

    compact_summary = (
        f"Plan diagnostics: method={method}, mode={mode}, input={input_rows}, "
        f"filtered={filtered_rows}, candidates={candidate_rows}, selected={selected_rows_count}, "
        f"spacing_violations={spacing['spacing_violations']}"
    )
    if sampling_diagnostics is not None:
        compact_summary += (
            f", bins={getattr(sampling_diagnostics, 'achieved_bins', 0)}/"
            f"{getattr(sampling_diagnostics, 'actual_bins', 0)}, "
            f"binning={getattr(sampling_diagnostics, 'binning_mode', None)}, "
            f"candidate_depth={getattr(sampling_diagnostics, 'candidate_depth', None)}, "
            f"seed={getattr(sampling_diagnostics, 'random_seed', None)}"
        )
    if multi_start_summary.get("optimization_enabled"):
        compact_summary += (
            f", multi_start_trials={multi_start_summary.get('trial_count')}, "
            f"best_trial={multi_start_summary.get('best_trial_index')}"
        )
    compact_summary += f". {quality_score.compact_summary}"

    return PlanGenerationDiagnostics(
        method=method,
        mode=mode,
        compact_summary=compact_summary,
        run_summary=run_summary,
        input_summary=input_summary,
        filtering_summary=filtering_summary,
        candidate_reduction_summary=candidate_reduction_summary,
        bin_summary=bin_summary,
        spacing_summary=spacing,
        output_summary=output_summary,
        selected_row_ids=tuple(selected_identity),
        plot_series=plot_series,
        quality_metrics=quality_score.metrics.to_dict(),
        multi_start_summary=multi_start_summary,
        local_repair_summary=local_repair_summary,
        slew_path_summary=slew_path_summary,
        slew_path_transitions=tuple(slew_path_transitions),
        slew_aware_quality_preview=slew_aware_quality_preview,
        optimization_impact_summary=unavailable_optimization_impact_summary("Baseline comparison not computed for this diagnostics object."),
        optimization_trust_summary={},
        quality_score_summary=quality_score.compact_summary,
        quality_lexicographic_score=quality_score.lexicographic_score,
    )
