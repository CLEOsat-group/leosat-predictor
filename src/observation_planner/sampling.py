"""Stratified observation-plan sampling algorithms.

This module is GUI- and web-neutral.  It extends the donor-compatible
Observation Planner with seeded, reproducible stratified sampling methods while
preserving the existing max-elevation planner path in ``planner.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import time
from collections.abc import Callable
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from .exceptions import ObservationPlanGenerationCancelled
from .normalize import clean_satellite_name
from .quality import compute_plan_quality
from .schema import resolve_column
from .slew_diagnostics import DEFAULT_SLEW_MODEL, SlewModel, compute_slew_path_diagnostics
from .slew_quality import compute_slew_aware_selection_score
from .transition_constraints import (
    DEFAULT_TRANSITION_CONSTRAINT_MODE,
    DEFAULT_TRANSITION_SAFETY_MARGIN_SEC,
    TRANSITION_CONSTRAINT_PHYSICAL,
    apply_physical_transition_filter,
    normalize_transition_constraint_mode,
    validate_transition_safety_margin_sec,
)

PLAN_METHOD_MAX_ELEVATION = "max_elevation"
PLAN_METHOD_STRATIFIED_ELEVATION = "stratified_elevation_sample"
PLAN_METHOD_STRATIFIED_SOLAR_PHASE = "stratified_solar_phase_sample"

PLAN_METHOD_ALIASES = {
    PLAN_METHOD_MAX_ELEVATION: PLAN_METHOD_MAX_ELEVATION,
    "automatic": PLAN_METHOD_MAX_ELEVATION,
    "auto": PLAN_METHOD_MAX_ELEVATION,
    "auto_sequence": PLAN_METHOD_MAX_ELEVATION,
    "max elevation": PLAN_METHOD_MAX_ELEVATION,
    "stratified elevation": PLAN_METHOD_STRATIFIED_ELEVATION,
    "stratified elevation sample": PLAN_METHOD_STRATIFIED_ELEVATION,
    PLAN_METHOD_STRATIFIED_ELEVATION: PLAN_METHOD_STRATIFIED_ELEVATION,
    "stratified solar phase": PLAN_METHOD_STRATIFIED_SOLAR_PHASE,
    "stratified solar phase sample": PLAN_METHOD_STRATIFIED_SOLAR_PHASE,
    "stratified phase": PLAN_METHOD_STRATIFIED_SOLAR_PHASE,
    PLAN_METHOD_STRATIFIED_SOLAR_PHASE: PLAN_METHOD_STRATIFIED_SOLAR_PHASE,
}

SAMPLING_METRIC_ELEVATION = "elevation"
SAMPLING_METRIC_SOLAR_PHASE = "solar_phase"

BINNING_EQUAL_WIDTH = "equal_width"
BINNING_QUANTILE = "quantile"
BINNING_CUSTOM_EDGES = "custom_edges"
BINNING_FIXED_WIDTH = "fixed_width"

BINNING_ALIASES = {
    BINNING_EQUAL_WIDTH: BINNING_EQUAL_WIDTH,
    "equal width": BINNING_EQUAL_WIDTH,
    "equal-width": BINNING_EQUAL_WIDTH,
    "linear": BINNING_EQUAL_WIDTH,
    BINNING_QUANTILE: BINNING_QUANTILE,
    "empirical quantile": BINNING_QUANTILE,
    "quantiles": BINNING_QUANTILE,
    BINNING_CUSTOM_EDGES: BINNING_CUSTOM_EDGES,
    "custom edges": BINNING_CUSTOM_EDGES,
    "custom": BINNING_CUSTOM_EDGES,
    BINNING_FIXED_WIDTH: BINNING_FIXED_WIDTH,
    "fixed width": BINNING_FIXED_WIDTH,
    "fixed-width": BINNING_FIXED_WIDTH,
    "width": BINNING_FIXED_WIDTH,
    "bin width": BINNING_FIXED_WIDTH,
    "bin_width": BINNING_FIXED_WIDTH,
    "physical width": BINNING_FIXED_WIDTH,
    "physical_width": BINNING_FIXED_WIDTH,
}

DEFAULT_SAMPLE_BINS = 6
DEFAULT_BIN_WIDTH_DEG = 5.0
MIN_BIN_WIDTH_DEG = 0.5
MAX_BIN_WIDTH_DEG = 180.0
DEFAULT_RANDOM_SEED = 12345
DEFAULT_OPTIMIZATION_TRIALS = 32
MAX_OPTIMIZATION_TRIALS = 256
DEFAULT_CANDIDATE_DEPTH = 3
MAX_CANDIDATE_DEPTH = 16
DEFAULT_LOCAL_REPAIR_ENABLED = False
DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS = 10
DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT = 5000
DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT = 20000

OPTIMIZATION_OBJECTIVE_QUALITY = "quality"
OPTIMIZATION_OBJECTIVE_SLEW_AWARE = "slew_aware"

OPTIMIZATION_OBJECTIVE_ALIASES = {
    OPTIMIZATION_OBJECTIVE_QUALITY: OPTIMIZATION_OBJECTIVE_QUALITY,
    "science": OPTIMIZATION_OBJECTIVE_QUALITY,
    "default": OPTIMIZATION_OBJECTIVE_QUALITY,
    "plan_quality": OPTIMIZATION_OBJECTIVE_QUALITY,
    "quality_first": OPTIMIZATION_OBJECTIVE_QUALITY,
    OPTIMIZATION_OBJECTIVE_SLEW_AWARE: OPTIMIZATION_OBJECTIVE_SLEW_AWARE,
    "slew aware": OPTIMIZATION_OBJECTIVE_SLEW_AWARE,
    "slew-aware": OPTIMIZATION_OBJECTIVE_SLEW_AWARE,
    "path": OPTIMIZATION_OBJECTIVE_SLEW_AWARE,
    "path_aware": OPTIMIZATION_OBJECTIVE_SLEW_AWARE,
}


def normalize_optimization_objective(value: object) -> str:
    """Return a supported multi-start optimization objective identifier.

    Parameters
    ----------
    value : object
        Persisted or user-provided objective value.

    Returns
    -------
    str
        ``"quality"`` for current science-quality behavior or
        ``"slew_aware"`` for the optional Task 35D path-aware objective.
    """
    key = str(value or OPTIMIZATION_OBJECTIVE_QUALITY).strip().lower().replace("-", "_")
    return OPTIMIZATION_OBJECTIVE_ALIASES.get(key, OPTIMIZATION_OBJECTIVE_QUALITY)


CANDIDATE_REDUCTION_MODE_RANDOM = "random"
CANDIDATE_REDUCTION_MODE_METRIC_INFORMED = "metric_informed"

CANDIDATE_REDUCTION_MODE_ALIASES = {
    CANDIDATE_REDUCTION_MODE_RANDOM: CANDIDATE_REDUCTION_MODE_RANDOM,
    "default": CANDIDATE_REDUCTION_MODE_RANDOM,
    CANDIDATE_REDUCTION_MODE_METRIC_INFORMED: CANDIDATE_REDUCTION_MODE_METRIC_INFORMED,
    "metric-informed": CANDIDATE_REDUCTION_MODE_METRIC_INFORMED,
    "metric_aware": CANDIDATE_REDUCTION_MODE_METRIC_INFORMED,
}


def normalize_candidate_reduction_mode(value: object) -> str:
    """Return a supported candidate-depth reduction mode identifier.

    Parameters
    ----------
    value : object
        Persisted or caller-provided reduction-mode value.

    Returns
    -------
    str
        ``"random"`` for the current production default (uniform seeded
        selection) or ``"metric_informed"`` for the investigation-only
        bin-representative alternative. ``metric_informed`` is not exposed in
        the GUI and is not a production default -- see
        ``tools/dev/compare_candidate_reduction_strategies.py`` for the
        empirical comparison that gates whether it should ever become one.
    """
    key = str(value or CANDIDATE_REDUCTION_MODE_RANDOM).strip().lower().replace("-", "_")
    return CANDIDATE_REDUCTION_MODE_ALIASES.get(key, CANDIDATE_REDUCTION_MODE_RANDOM)


def _emit_progress(progress_callback: Callable[[str], None] | None, message: str) -> None:
    """Emit an optional progress message without affecting sampling results."""
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception:
        return


def _check_cancel(cancel_callback: Callable[[], bool] | None) -> None:
    """Raise when cooperative cancellation has been requested."""
    if cancel_callback is not None and cancel_callback():
        raise ObservationPlanGenerationCancelled("Observation plan generation canceled; previous plan kept.")


def _should_report_trial(trial_index: int, trial_count: int) -> bool:
    """Return whether a multi-start trial should emit a progress message."""
    if trial_index == 0 or trial_index == trial_count - 1:
        return True
    if trial_count <= 16:
        return True
    step = max(1, trial_count // 10)
    return (trial_index + 1) % step == 0


@dataclass(frozen=True)
class SamplingPlannerRequest:
    """Validated request for stratified observation-plan sampling.

    Parameters
    ----------
    plan_method : str
        Sampling plan method.  Supported non-legacy values are
        ``stratified_elevation_sample`` and ``stratified_solar_phase_sample``.
    binning_mode : str
        Binning strategy: ``equal_width``, ``quantile``, ``custom_edges``,
        or ``fixed_width``.
    sample_bins : int
        Requested number of bins for equal-width or quantile modes.
    bin_width_deg : float
        Fixed physical bin width in degrees, used only when
        ``binning_mode`` is ``fixed_width``.
    random_seed : int
        Seed used for reproducible candidate reduction and tie-breaking.
    spacing_min : float
        Minimum observation spacing in minutes.  This is always a hard
        constraint; repair never decreases it.
    custom_elevation_bin_edges : sequence of float, optional
        Explicit elevation bin edges for custom-edge elevation sampling.
    custom_solar_phase_bin_edges : sequence of float, optional
        Explicit solar-phase bin edges for custom-edge solar-phase sampling.
    """

    plan_method: str
    binning_mode: str = BINNING_EQUAL_WIDTH
    sample_bins: int = DEFAULT_SAMPLE_BINS
    bin_width_deg: float = DEFAULT_BIN_WIDTH_DEG
    random_seed: int = DEFAULT_RANDOM_SEED
    spacing_min: float = 3.0
    custom_elevation_bin_edges: tuple[float, ...] = field(default_factory=tuple)
    custom_solar_phase_bin_edges: tuple[float, ...] = field(default_factory=tuple)
    optimization_enabled: bool = True
    optimization_trials: int = DEFAULT_OPTIMIZATION_TRIALS
    candidate_depth: int = DEFAULT_CANDIDATE_DEPTH
    local_repair_enabled: bool = DEFAULT_LOCAL_REPAIR_ENABLED
    local_repair_max_additions: int = DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS
    local_repair_candidate_limit: int = DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT
    local_repair_attempt_limit: int = DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT
    optimization_objective: str = OPTIMIZATION_OBJECTIVE_QUALITY
    slew_model: SlewModel | None = None
    transition_constraint_mode: str = DEFAULT_TRANSITION_CONSTRAINT_MODE
    transition_safety_margin_sec: float = DEFAULT_TRANSITION_SAFETY_MARGIN_SEC
    candidate_reduction_mode: str = CANDIDATE_REDUCTION_MODE_RANDOM

    @property
    def active_optimization_objective(self) -> str:
        """Return the normalized multi-start optimization objective."""
        return normalize_optimization_objective(self.optimization_objective)

    @property
    def active_candidate_reduction_mode(self) -> str:
        """Return the normalized candidate-depth reduction mode (investigation-only)."""
        return normalize_candidate_reduction_mode(self.candidate_reduction_mode)

    @property
    def active_slew_model(self) -> SlewModel:
        """Return the validated telescope motion model for slew-aware scoring."""
        return (self.slew_model or DEFAULT_SLEW_MODEL).validated()

    @property
    def active_transition_constraint_mode(self) -> str:
        """Return the normalized transition-constraint mode."""
        return normalize_transition_constraint_mode(self.transition_constraint_mode)

    @property
    def active_transition_safety_margin_sec(self) -> float:
        """Return the bounded physical-transition safety margin."""
        return validate_transition_safety_margin_sec(self.transition_safety_margin_sec)

    def metric(self) -> str:
        """Return the metric implied by ``plan_method``."""
        return metric_for_plan_method(self.plan_method)


@dataclass(frozen=True)
class BinDiagnostics:
    """Diagnostic information for one sampling bin."""

    bin_id: int
    candidate_count: int
    reduced_candidate_count: int
    selected_count: int
    lower_edge: float | None = None
    upper_edge: float | None = None


@dataclass(frozen=True)
class SamplingPlannerDiagnostics:
    """Auditable diagnostics returned by the sampling planner."""

    method: str
    metric: str
    binning_mode: str
    requested_bins: int
    actual_bins: int
    input_rows: int
    filtered_rows: int
    invalid_metric_rows: int
    candidate_rows: int
    reduced_candidate_rows: int
    selected_rows: int
    achieved_bins: int
    missing_bins: tuple[int, ...]
    spacing_min: float
    random_seed: int
    pass_groups: int
    bin_diagnostics: tuple[BinDiagnostics, ...] = field(default_factory=tuple)
    selected_row_ids: tuple[dict[str, object], ...] = field(default_factory=tuple)
    plot_series: dict[str, object] = field(default_factory=dict)
    candidate_depth: int = DEFAULT_CANDIDATE_DEPTH
    multi_start_summary: dict[str, object] = field(default_factory=dict)
    local_repair_summary: dict[str, object] = field(default_factory=dict)
    bin_width_deg: float | None = None
    bin_anchor_policy: str = "observed_range"
    bin_domain_min_deg: float | None = None
    bin_domain_max_deg: float | None = None

    def to_log_message(self) -> str:
        """Return a compact user-facing diagnostics string."""
        missing = ",".join(str(item) for item in self.missing_bins) if self.missing_bins else "none"
        width_fragment = ""
        if self.binning_mode == BINNING_FIXED_WIDTH:
            width_fragment = f"bin_width_deg={self.bin_width_deg}, "
        return (
            "Sampling diagnostics: "
            f"method={self.method}, metric={self.metric}, bins={self.achieved_bins}/{self.actual_bins} "
            f"(requested={self.requested_bins}, missing={missing}), "
            f"input={self.input_rows}, filtered={self.filtered_rows}, "
            f"invalid_metric={self.invalid_metric_rows}, candidates={self.candidate_rows}, "
            f"reduced={self.reduced_candidate_rows}, selected={self.selected_rows}, "
            f"candidate_depth={self.candidate_depth}, "
            f"{width_fragment}"
            f"spacing={self.spacing_min} min, seed={self.random_seed}."
        )


@dataclass(frozen=True)
class PreparedStratifiedSamplingProblem:
    """Invariant candidate-preparation state for stratified sampling.

    Parameters
    ----------
    method : str
        Normalized stratified planner method.
    metric : str
        Sampling metric implied by the method.
    binning_mode : str
        Normalized binning mode.
    requested_bins : int
        Requested number of sampling bins.
    actual_bins : int
        Actual number of bins represented by the prepared problem.
    input_rows : int
        Rows received by the stratified sampler before metric filtering.
    filtered_rows : int
        Rows retained after metric/bin/date filtering.
    invalid_metric_rows : int
        Rows rejected because the requested metric was invalid.
    candidate_rows : int
        Prepared candidate rows available to seed-dependent trials.
    pass_groups : int
        Number of detected satellite/pass groups.
    edge_pairs : tuple
        Bin edge diagnostics.
    candidates : pandas.DataFrame
        Prepared candidate table with sampling columns.
    """

    method: str
    metric: str
    binning_mode: str
    bin_width_deg: float | None
    bin_anchor_policy: str
    bin_domain_min_deg: float | None
    bin_domain_max_deg: float | None
    requested_bins: int
    actual_bins: int
    input_rows: int
    filtered_rows: int
    invalid_metric_rows: int
    candidate_rows: int
    pass_groups: int
    edge_pairs: tuple[tuple[float | None, float | None], ...]
    candidates: pd.DataFrame
    group_indices: tuple[np.ndarray, ...] = field(default_factory=tuple)
    group_count: int = 0
    available_bin_ids: tuple[int, ...] = field(default_factory=tuple)
    candidate_bin_counts: Mapping[int, int] = field(default_factory=dict)



def normalize_plan_method(value: object) -> str:
    """Normalize plan-method labels to backend constants."""
    key = str(value or PLAN_METHOD_MAX_ELEVATION).strip().lower().replace("-", "_")
    key = key.replace(" ", "_")
    return PLAN_METHOD_ALIASES.get(key, PLAN_METHOD_MAX_ELEVATION)


def metric_for_plan_method(plan_method: object) -> str:
    """Return the sampling metric implied by a planner method.

    Parameters
    ----------
    plan_method : object
        Planner method identifier or user-facing alias.

    Returns
    -------
    str
        ``"solar_phase"`` only for the stratified solar-phase method;
        otherwise ``"elevation"``.  This helper is the single source of truth
        for legacy ``default_sampling_metric`` synchronization.
    """
    method = normalize_plan_method(plan_method)
    if method == PLAN_METHOD_STRATIFIED_SOLAR_PHASE:
        return SAMPLING_METRIC_SOLAR_PHASE
    return SAMPLING_METRIC_ELEVATION


def normalize_binning_mode(value: object) -> str:
    """Normalize binning-mode labels to backend constants."""
    key = str(value or BINNING_EQUAL_WIDTH).strip().lower().replace("-", "_")
    key = key.replace(" ", "_")
    return BINNING_ALIASES.get(key, BINNING_EQUAL_WIDTH)


def parse_custom_bin_edges(value: object) -> tuple[float, ...]:
    """Parse comma/semicolon/whitespace separated custom bin edges."""
    if value is None:
        return ()
    if isinstance(value, str):
        cleaned = value.replace(";", ",").replace("\n", ",")
        parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    elif isinstance(value, Iterable):
        parts = list(value)
    else:
        parts = [value]
    edges: list[float] = []
    for part in parts:
        try:
            edges.append(float(part))
        except Exception as exc:
            raise ValueError(f"Invalid custom bin edge: {part!r}") from exc
    return tuple(edges)


def _validate_custom_edges(edges: Sequence[float], *, metric: str) -> tuple[float, ...]:
    """Validate custom edges for a sampling metric."""
    edge_values = tuple(float(edge) for edge in edges)
    if len(edge_values) < 2:
        raise ValueError("Custom binning requires at least two bin edges.")
    if any(not np.isfinite(edge) for edge in edge_values):
        raise ValueError("Custom bin edges must be finite numbers.")
    if any(right <= left for left, right in zip(edge_values[:-1], edge_values[1:])):
        raise ValueError("Custom bin edges must be strictly increasing.")
    if metric == SAMPLING_METRIC_SOLAR_PHASE and (edge_values[0] < 0.0 or edge_values[-1] > 180.0):
        raise ValueError("SolarPhaseAngle custom bin edges must be within 0–180 degrees.")
    if metric == SAMPLING_METRIC_ELEVATION and (edge_values[0] < -90.0 or edge_values[-1] > 90.0):
        raise ValueError("Elevation custom bin edges must be within -90–90 degrees.")
    return edge_values


def _metric_column(df: pd.DataFrame, metric: str, column_mapping=None) -> str:
    """Resolve the DataFrame column for a sampling metric."""
    if metric == SAMPLING_METRIC_SOLAR_PHASE:
        return resolve_column(df, "solar_phase_angle", column_mapping=column_mapping)
    return resolve_column(df, "elev", column_mapping=column_mapping)


def _validated_metric_values(df: pd.DataFrame, metric_col: str, metric: str) -> pd.Series:
    """Return numeric metric values with invalid entries represented as NaN."""
    values = pd.to_numeric(df[metric_col], errors="coerce")
    values = values.where(np.isfinite(values), np.nan)
    if metric == SAMPLING_METRIC_SOLAR_PHASE:
        values = values.where((values >= 0.0) & (values <= 180.0), np.nan)
    elif metric == SAMPLING_METRIC_ELEVATION:
        values = values.where((values >= -90.0) & (values <= 90.0), np.nan)
    return values



def validate_bin_width_deg(value: object) -> float:
    """Return a validated fixed physical bin width in degrees.

    Parameters
    ----------
    value : object
        Requested fixed-width bin size in degrees.

    Returns
    -------
    float
        Width in degrees.

    Raises
    ------
    ValueError
        If the requested width is not finite or is outside the Task 31H
        guardrail range.
    """
    try:
        width = float(value)
    except Exception as exc:
        raise ValueError("Fixed-width bin size must be a finite number of degrees.") from exc
    if not np.isfinite(width):
        raise ValueError("Fixed-width bin size must be finite.")
    if width < MIN_BIN_WIDTH_DEG or width > MAX_BIN_WIDTH_DEG:
        raise ValueError(
            f"Fixed-width bin size must be between {MIN_BIN_WIDTH_DEG:g} and {MAX_BIN_WIDTH_DEG:g} degrees."
        )
    return width


def _metric_domain(metric: str) -> tuple[float | None, float | None]:
    """Return the physical degree domain for a sampling metric."""
    if metric == SAMPLING_METRIC_SOLAR_PHASE:
        return 0.0, 180.0
    if metric == SAMPLING_METRIC_ELEVATION:
        return -90.0, 90.0
    return None, None


def _fixed_width_edges(
    finite_values: pd.Series,
    *,
    metric: str,
    width_deg: float,
) -> tuple[np.ndarray, float | None, float | None]:
    """Return zero-grid anchored fixed-width bin edges for finite values.

    The grid is anchored to physical zero, not to the observed data minimum.
    Edges are clamped to the physical metric domain when a domain is known.
    """
    width = validate_bin_width_deg(width_deg)
    observed_min = float(finite_values.min())
    observed_max = float(finite_values.max())
    domain_min, domain_max = _metric_domain(metric)

    start = np.floor(observed_min / width) * width
    end = np.ceil(observed_max / width) * width
    if np.isclose(start, end):
        end = start + width

    if domain_min is not None:
        start = max(float(domain_min), float(start))
    if domain_max is not None:
        end = min(float(domain_max), float(end))
    if not end > start:
        # This can only occur for a value lying exactly on a clamped domain edge.
        if domain_max is not None and np.isclose(start, domain_max):
            start = max(float(domain_min) if domain_min is not None else start - width, start - width)
        else:
            end = start + width
            if domain_max is not None:
                end = min(float(domain_max), end)

    count = max(1, int(np.ceil((end - start) / width)))
    edges = start + np.arange(count + 1, dtype="float64") * width
    edges[-1] = end
    # Remove any tiny floating point overshoot and ensure strict monotonicity.
    edges = np.round(edges, decimals=10)
    edges = edges[np.concatenate(([True], np.diff(edges) > 1.0e-10))]
    if len(edges) < 2:
        edges = np.array([start, start + width], dtype="float64")
    return edges.astype("float64"), domain_min, domain_max

def _assign_bins(
    values: pd.Series,
    *,
    request: SamplingPlannerRequest,
    metric: str,
) -> tuple[pd.Series, list[tuple[float | None, float | None]]]:
    """Assign metric values to bins and return bin edge diagnostics."""
    mode = normalize_binning_mode(request.binning_mode)
    bins = max(1, int(request.sample_bins))
    finite_values = values.dropna().astype(float)
    if finite_values.empty:
        return pd.Series(np.nan, index=values.index, dtype="float64"), []

    if mode == BINNING_FIXED_WIDTH:
        width = validate_bin_width_deg(request.bin_width_deg)
        edges, _, _ = _fixed_width_edges(finite_values, metric=metric, width_deg=width)
        labels = list(range(len(edges) - 1))
        assigned = pd.cut(values, bins=edges, labels=labels, include_lowest=True, right=False)
        # Include values that lie exactly on the final edge in the final bin.
        if len(labels) > 0:
            assigned = assigned.astype("float64")
            assigned.loc[values == edges[-1]] = labels[-1]
        edge_pairs = [(float(edges[index]), float(edges[index + 1])) for index in labels]
        return pd.to_numeric(assigned, errors="coerce"), edge_pairs

    if mode == BINNING_CUSTOM_EDGES:
        edges = request.custom_solar_phase_bin_edges if metric == SAMPLING_METRIC_SOLAR_PHASE else request.custom_elevation_bin_edges
        edge_values = _validate_custom_edges(edges, metric=metric)
        labels = list(range(len(edge_values) - 1))
        assigned = pd.cut(values, bins=edge_values, labels=labels, include_lowest=True)
        edge_pairs = [(edge_values[index], edge_values[index + 1]) for index in labels]
        return pd.to_numeric(assigned, errors="coerce"), edge_pairs

    if mode == BINNING_QUANTILE:
        if finite_values.nunique() <= 1:
            assigned = pd.Series(0, index=values.index, dtype="float64").where(values.notna(), np.nan)
            return assigned, [(float(finite_values.iloc[0]), float(finite_values.iloc[0]))]
        try:
            assigned, edges = pd.qcut(
                finite_values,
                q=min(bins, len(finite_values)),
                labels=False,
                retbins=True,
                duplicates="drop",
            )
        except ValueError:
            assigned = pd.Series(0, index=finite_values.index, dtype="float64")
            edges = np.array([finite_values.min(), finite_values.max()], dtype="float64")
        result = pd.Series(np.nan, index=values.index, dtype="float64")
        result.loc[assigned.index] = pd.to_numeric(assigned, errors="coerce")
        edge_pairs = [(float(edges[index]), float(edges[index + 1])) for index in range(max(0, len(edges) - 1))]
        return result, edge_pairs

    observed_min = float(finite_values.min())
    observed_max = float(finite_values.max())
    if np.isclose(observed_min, observed_max):
        assigned = pd.Series(0, index=values.index, dtype="float64").where(values.notna(), np.nan)
        return assigned, [(observed_min, observed_max)]
    edges = np.linspace(observed_min, observed_max, bins + 1)
    labels = list(range(len(edges) - 1))
    assigned = pd.cut(values, bins=edges, labels=labels, include_lowest=True)
    edge_pairs = [(float(edges[index]), float(edges[index + 1])) for index in labels]
    return pd.to_numeric(assigned, errors="coerce"), edge_pairs


def _assign_pass_ids(df: pd.DataFrame, spacing_min: float) -> pd.Series:
    """Assign pass identifiers using vectorized satellite-wise gap detection.

    The pass-break semantics match the Task 31F contract: within each
    satellite, rows are ordered by time, the positive cadence median defines
    the nominal cadence, and a new pass begins when a gap exceeds
    ``max(2 * median_cadence, 2 * spacing_min)``.  Invalid datetimes keep the
    default ``-1`` pass id and are normally removed before this function is
    called by the planner.
    """
    spacing_sec = max(0.0, float(spacing_min) * 60.0)
    pass_ids = pd.Series(-1, index=df.index, dtype="int64")
    if df.empty:
        return pass_ids

    work = pd.DataFrame(
        {
            "__satellite": df["satellite"].astype(str),
            "__datetime": pd.to_datetime(df["datetime"], errors="coerce"),
        },
        index=df.index,
    ).dropna(subset=["__datetime"])
    if work.empty:
        return pass_ids

    work = work.sort_values(["__satellite", "__datetime"], kind="mergesort").copy()
    deltas = work.groupby("__satellite", sort=False)["__datetime"].diff().dt.total_seconds()
    positive_deltas = deltas.where((deltas > 0.0) & np.isfinite(deltas))
    median_positive_delta = positive_deltas.groupby(work["__satellite"], sort=False).median()

    thresholds = work["__satellite"].map(median_positive_delta).astype("float64")
    thresholds = thresholds.to_numpy(dtype="float64") * 2.0
    thresholds = np.maximum(thresholds, 2.0 * spacing_sec)
    thresholds = np.where(np.isfinite(thresholds), thresholds, max(1.0, 2.0 * spacing_sec))

    delta_values = deltas.to_numpy(dtype="float64")
    satellite_breaks = work["__satellite"].ne(work["__satellite"].shift()).to_numpy(dtype=bool)
    gap_breaks = np.isfinite(delta_values) & (delta_values > thresholds)
    break_markers = satellite_breaks | gap_breaks

    local_pass = (
        pd.Series(break_markers, index=work.index, dtype=bool)
        .groupby(work["__satellite"], sort=False)
        .cumsum()
        .astype("int64")
        - 1
    )
    pass_keys = pd.MultiIndex.from_arrays([work["__satellite"].to_numpy(), local_pass.to_numpy()])
    pass_codes = pd.factorize(pass_keys, sort=False)[0].astype("int64")
    pass_ids.loc[work.index] = pass_codes
    return pass_ids


def _reduce_candidates_by_pass_bin(
    candidates: pd.DataFrame,
    *,
    rng: np.random.Generator,
    candidate_depth: int = DEFAULT_CANDIDATE_DEPTH,
) -> pd.DataFrame:
    """Keep a bounded seeded candidate pool per satellite/pass/bin group.

    The original stratified sampler retained exactly one representative from
    each satellite/pass/bin group.  Task 31C generalizes that reduction by
    retaining up to ``candidate_depth`` representatives.  Task 31F keeps this
    legacy ``rng.choice`` reduction path for now because it preserves the
    established deterministic optimization semantics; the dominant Starlink
    scaling win is achieved by preparing invariant candidate state once and by
    vectorizing pass-id assignment.
    """
    if candidates.empty:
        return candidates.copy()
    depth = validate_candidate_depth(candidate_depth)
    rows = []
    group_cols = ["satellite", "pass_id", "sampling_bin"]
    for _, group in candidates.groupby(group_cols, sort=False, dropna=True):
        if group.empty:
            continue
        if depth <= 1:
            position = int(rng.integers(0, len(group)))
            rows.append(group.iloc[[position]])
            continue
        take_count = min(depth, len(group))
        if take_count >= len(group):
            rows.append(group)
            continue
        positions = np.sort(rng.choice(len(group), size=take_count, replace=False))
        rows.append(group.iloc[positions])
    return pd.concat(rows, ignore_index=True) if rows else candidates.iloc[0:0].copy()



def _prepared_group_indices(candidates: pd.DataFrame) -> tuple[np.ndarray, ...]:
    """Return candidate row-position arrays for satellite/pass/bin groups.

    The group order intentionally mirrors ``DataFrame.groupby(...,
    sort=False, dropna=True)`` so that the fast Task 31G reducer consumes random
    numbers in the same order as the legacy reducer.
    """
    required = {"satellite", "pass_id", "sampling_bin"}
    if candidates is None or candidates.empty or not required.issubset(candidates.columns):
        return ()
    grouped = candidates.groupby(["satellite", "pass_id", "sampling_bin"], sort=False, dropna=True)
    return tuple(np.asarray(indices, dtype=np.int64) for indices in grouped.indices.values())


def _prepared_bin_counts(candidates: pd.DataFrame) -> tuple[tuple[int, int], ...]:
    """Return sorted ``(bin_id, count)`` pairs for prepared candidates."""
    if candidates is None or candidates.empty or "sampling_bin" not in candidates.columns:
        return ()
    counts = candidates["sampling_bin"].dropna().astype(int).value_counts(sort=False).to_dict()
    return tuple((int(bin_id), int(counts[bin_id])) for bin_id in sorted(counts))


def _reduce_prepared_candidates_by_pass_bin(
    problem: PreparedStratifiedSamplingProblem,
    *,
    rng: np.random.Generator,
    candidate_depth: int = DEFAULT_CANDIDATE_DEPTH,
    cancel_callback: Callable[[], bool] | None = None,
) -> pd.DataFrame:
    """Fast exact-compatible candidate-depth reduction for prepared groups.

    This keeps the established Task 31C random-selection semantics by making the
    same per-group ``rng.integers`` / ``rng.choice`` calls as the legacy pandas
    group loop, but avoids rebuilding groups and concatenating thousands of
    small DataFrames on every multi-start trial.
    """
    candidates = problem.candidates
    if candidates is None or candidates.empty:
        return pd.DataFrame() if candidates is None else candidates.copy()
    groups = problem.group_indices or _prepared_group_indices(candidates)
    if not groups:
        return _reduce_candidates_by_pass_bin(candidates, rng=rng, candidate_depth=candidate_depth)

    depth = validate_candidate_depth(candidate_depth)
    selected_positions: list[np.ndarray] = []
    for group_index, group_positions in enumerate(groups):
        if group_index % 512 == 0:
            _check_cancel(cancel_callback)
        group_positions = np.asarray(group_positions, dtype=np.int64)
        group_size = int(group_positions.size)
        if group_size <= 0:
            continue
        if depth <= 1:
            position = int(rng.integers(0, group_size))
            selected_positions.append(group_positions[[position]])
            continue
        take_count = min(depth, group_size)
        if take_count >= group_size:
            selected_positions.append(group_positions)
            continue
        positions = np.sort(rng.choice(group_size, size=take_count, replace=False))
        selected_positions.append(group_positions[positions])

    if not selected_positions:
        return candidates.iloc[0:0].copy()
    positions = np.concatenate(selected_positions).astype(np.int64, copy=False)
    return candidates.iloc[positions].reset_index(drop=True)


def _reduce_candidates_by_pass_bin_metric_informed(
    candidates: pd.DataFrame,
    *,
    rng: np.random.Generator,
    candidate_depth: int = DEFAULT_CANDIDATE_DEPTH,
) -> pd.DataFrame:
    """Investigation-only candidate-depth reduction: keep bin-representative rows.

    Unlike the production ``_reduce_candidates_by_pass_bin``/
    ``_reduce_prepared_candidates_by_pass_bin`` (uniform seeded random
    selection), this keeps, per ``(satellite, pass_id, sampling_bin)`` group,
    the ``candidate_depth`` rows whose ``sampling_metric`` value is closest to
    that group's own metric mean -- i.e. the most representative/typical rows
    for the group, rather than the highest or lowest metric value.

    This deliberately does not assume a universal "higher/lower is better"
    direction for ``sampling_metric``: that holds for elevation (higher is
    better) but not for solar-phase-angle, which has no such direction in this
    codebase. Bin-centrality is direction-agnostic and applies to both.

    This is a strictly opt-in, investigation-only alternative gated behind
    ``SamplingPlannerRequest.candidate_reduction_mode`` -- see
    ``tools/dev/compare_candidate_reduction_strategies.py`` for the empirical
    comparison against the production random-selection default, and the
    acceptance criteria that decide whether this should ever be promoted to a
    real opt-in preference. It intentionally does NOT share the RNG-call-order
    compatibility contract that the two functions above document and must
    preserve for deterministic multi-start optimization.
    """
    if candidates.empty:
        return candidates.copy()
    depth = validate_candidate_depth(candidate_depth)
    rows = []
    group_cols = ["satellite", "pass_id", "sampling_bin"]
    for _, group in candidates.groupby(group_cols, sort=False, dropna=True):
        if group.empty:
            continue
        take_count = min(depth, len(group))
        if take_count >= len(group):
            rows.append(group)
            continue
        metric_values = pd.to_numeric(group.get("sampling_metric"), errors="coerce")
        group_mean = metric_values.mean()
        if pd.isna(group_mean):
            # No usable metric signal in this group -- fall back to random
            # selection rather than an arbitrary/undefined ordering.
            positions = np.sort(rng.choice(len(group), size=take_count, replace=False))
            rows.append(group.iloc[positions])
            continue
        distance = (metric_values - group_mean).abs().to_numpy()
        # Deterministic tie-break among equal-distance rows via the seeded rng,
        # so ties do not silently depend on incoming row order.
        tie_break = rng.random(len(group))
        order = np.lexsort((tie_break, distance))
        rows.append(group.iloc[order[:take_count]])
    return pd.concat(rows, ignore_index=True) if rows else candidates.iloc[0:0].copy()


def _weighted_interval_select(
    candidates: pd.DataFrame,
    *,
    spacing_min: float,
    rng: np.random.Generator,
    cancel_callback: Callable[[], bool] | None = None,
) -> pd.DataFrame:
    """Select a maximum-cardinality spacing-valid subset with weighted repair.

    The primary score term dominates all secondary terms, so the dynamic program
    first maximizes the number of selected observations.  Secondary terms prefer
    scarce bins and seeded jitter only among maximum-cardinality solutions.
    """
    if candidates.empty:
        return candidates.copy()

    ordered = candidates.sort_values("datetime").reset_index(drop=True).copy()
    # Force nanosecond precision before converting to integer epoch values.
    # Pandas can preserve lower-resolution datetime dtypes such as
    # ``datetime64[ms]`` on some platforms/environments.  Calling
    # ``astype("int64")`` directly on such data would produce milliseconds,
    # while ``spacing_ns`` is expressed in nanoseconds.  That silently makes
    # every row look mutually conflicting and collapses the sampled plan to a
    # single row.
    times_ns = (
        pd.to_datetime(ordered["datetime"], errors="coerce")
        .to_numpy(dtype="datetime64[ns]")
        .astype("int64")
    )
    spacing_ns = int(float(spacing_min) * 60.0 * 1_000_000_000)
    bin_counts = ordered["sampling_bin"].value_counts().to_dict()
    max_secondary = 1000.0
    count_weight = (len(ordered) + 1) * (max_secondary + 2.0)
    bin_scarcity = ordered["sampling_bin"].map(lambda value: max_secondary / max(1, int(bin_counts.get(value, 1)))).to_numpy(dtype="float64")
    jitter = rng.random(len(ordered))
    weights = count_weight + bin_scarcity + jitter

    predecessors = np.full(len(ordered), -1, dtype="int64")
    for index, start_ns in enumerate(times_ns):
        if index % 4096 == 0:
            _check_cancel(cancel_callback)
        compatible_time = start_ns - spacing_ns
        predecessors[index] = int(np.searchsorted(times_ns, compatible_time, side="right") - 1)

    opt = np.zeros(len(ordered) + 1, dtype="float64")
    take = np.zeros(len(ordered), dtype=bool)
    for index in range(1, len(ordered) + 1):
        if index % 4096 == 0:
            _check_cancel(cancel_callback)
        row_index = index - 1
        include_score = weights[row_index] + opt[predecessors[row_index] + 1]
        exclude_score = opt[index - 1]
        if include_score > exclude_score:
            opt[index] = include_score
            take[row_index] = True
        else:
            opt[index] = exclude_score

    selected_indices: list[int] = []
    index = len(ordered) - 1
    while index >= 0:
        if index % 4096 == 0:
            _check_cancel(cancel_callback)
        include_score = weights[index] + opt[predecessors[index] + 1]
        exclude_score = opt[index]
        if include_score > exclude_score or np.isclose(include_score, exclude_score):
            selected_indices.append(index)
            index = int(predecessors[index])
        else:
            index -= 1
    selected_indices.reverse()
    return ordered.iloc[selected_indices].sort_values("datetime").reset_index(drop=True)




_MISSING_FIELD = object()

_IDENTITY_INDEX_COLUMNS = ("global_index", "base_index", "local_index")


def _identity_key_from_primitives(
    index_items: Sequence[tuple[str, object]],
    *,
    satellite: object = _MISSING_FIELD,
    datetime_value: object = _MISSING_FIELD,
    prefloored_isoformat: object = _MISSING_FIELD,
) -> tuple[str, object] | None:
    """Return the identity key from already-extracted primitive row values.

    Single source of truth for the identity-key coercion ladder.  Both the
    per-row Series wrapper and the column-extraction hot path delegate here so
    the two can never drift.  Per-row pandas Series construction dominated
    multi-start runtime, so the hot path passes plain NumPy scalars instead.

    ``prefloored_isoformat`` is the batch fast path: callers that already
    floored and formatted the row timestamp vectorized (``dt.floor("s")`` +
    ``isoformat()``) pass the resulting string (or ``None`` for invalid
    times) so the fallback branch avoids a per-row ``pd.to_datetime`` +
    ``Timestamp.floor`` pair, which dominated the scan cost.
    """
    for column, value in index_items:
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return column, str(value)

    if prefloored_isoformat is not _MISSING_FIELD:
        if prefloored_isoformat is not None and satellite is not _MISSING_FIELD:
            return "satellite_datetime", (str(satellite), prefloored_isoformat)
        return None

    if satellite is not _MISSING_FIELD and datetime_value is not _MISSING_FIELD:
        timestamp = pd.to_datetime(datetime_value, errors="coerce")
        if pd.notna(timestamp):
            return "satellite_datetime", (str(satellite), timestamp.floor("s").isoformat())
    return None


def _identity_key_from_row(row: pd.Series) -> tuple[str, object] | None:
    """Return the most stable available identity key for a candidate row.

    Parameters
    ----------
    row : pandas.Series
        Candidate or selected-plan row.

    Returns
    -------
    tuple or None
        ``(identity_name, value)`` when a stable identifier is available.
    """
    index_items = [(column, row[column]) for column in _IDENTITY_INDEX_COLUMNS if column in row.index]
    return _identity_key_from_primitives(
        index_items,
        satellite=row["satellite"] if "satellite" in row.index else _MISSING_FIELD,
        datetime_value=row["datetime"] if "datetime" in row.index else _MISSING_FIELD,
    )


def _identity_key_set(rows: pd.DataFrame) -> set[tuple[str, object]]:
    """Return stable row-identity keys for a dataframe."""
    keys: set[tuple[str, object]] = set()
    if rows is None or rows.empty:
        return keys
    index_arrays = [(column, rows[column].to_numpy()) for column in _IDENTITY_INDEX_COLUMNS if column in rows.columns]
    satellites = rows["satellite"].to_numpy() if "satellite" in rows.columns else None
    datetimes = rows["datetime"].to_numpy() if "datetime" in rows.columns else None
    for position in range(len(rows)):
        key = _identity_key_from_primitives(
            [(column, values[position]) for column, values in index_arrays],
            satellite=satellites[position] if satellites is not None else _MISSING_FIELD,
            datetime_value=datetimes[position] if datetimes is not None else _MISSING_FIELD,
        )
        if key is not None:
            keys.add(key)
    return keys


def _datetime_ns_array(values: pd.Series) -> np.ndarray:
    """Return sorted finite nanosecond timestamps for spacing checks."""
    if values is None:
        return np.array([], dtype="int64")
    timestamps = pd.to_datetime(values, errors="coerce").dropna()
    if timestamps.empty:
        return np.array([], dtype="int64")
    return np.sort(timestamps.to_numpy(dtype="datetime64[ns]").astype("int64"))


def _candidate_compatible_with_selected(
    candidate_time_ns: int,
    selected_times_ns: np.ndarray,
    *,
    spacing_ns: int,
) -> tuple[bool, bool]:
    """Return spacing compatibility and whether the candidate lies in a large gap.

    Parameters
    ----------
    candidate_time_ns : int
        Candidate timestamp as nanoseconds since epoch.
    selected_times_ns : numpy.ndarray
        Sorted selected-plan timestamps as nanoseconds since epoch.
    spacing_ns : int
        Required spacing in nanoseconds.

    Returns
    -------
    tuple
        ``(is_compatible, is_large_gap_candidate)``.
    """
    if selected_times_ns.size == 0:
        return True, False

    position = int(np.searchsorted(selected_times_ns, candidate_time_ns, side="left"))
    left_delta = None
    right_delta = None
    if position > 0:
        left_delta = int(candidate_time_ns - selected_times_ns[position - 1])
        if left_delta < spacing_ns:
            return False, False
    if position < selected_times_ns.size:
        right_delta = int(selected_times_ns[position] - candidate_time_ns)
        if right_delta < spacing_ns:
            return False, False

    is_large_gap = False
    if left_delta is not None and right_delta is not None:
        is_large_gap = bool(left_delta + right_delta >= 2 * spacing_ns)
    return True, is_large_gap


def _vectorized_spacing_compatibility(
    times_ns: np.ndarray,
    selected_times_ns: np.ndarray,
    *,
    spacing_ns: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized equivalent of ``_candidate_compatible_with_selected``.

    Returns ``(compatible, is_large_gap)`` boolean arrays computed for every
    candidate time at once via one ``searchsorted`` pass.  Large-gap flags are
    meaningful only where ``compatible`` is also true, matching the scalar
    function's early-return behavior.
    """
    count = int(times_ns.size)
    if selected_times_ns.size == 0:
        return np.ones(count, dtype=bool), np.zeros(count, dtype=bool)

    positions = np.searchsorted(selected_times_ns, times_ns, side="left")
    has_left = positions > 0
    has_right = positions < selected_times_ns.size

    left_delta = np.zeros(count, dtype="int64")
    right_delta = np.zeros(count, dtype="int64")
    left_delta[has_left] = times_ns[has_left] - selected_times_ns[positions[has_left] - 1]
    right_delta[has_right] = selected_times_ns[positions[has_right]] - times_ns[has_right]

    compatible = np.ones(count, dtype=bool)
    compatible &= ~(has_left & (left_delta < spacing_ns))
    compatible &= ~(has_right & (right_delta < spacing_ns))

    both_sides = has_left & has_right
    is_large_gap = both_sides & ((left_delta + right_delta) >= 2 * spacing_ns)
    return compatible, is_large_gap


def _quality_score_tuple_for_repair(
    *,
    selected: pd.DataFrame,
    reduced: pd.DataFrame,
    spacing_min: float,
    metric: str,
    diagnostics_proxy: object | None,
) -> list[object]:
    """Return a JSON-friendly quality score tuple for repair diagnostics."""
    metric_logical = "solar_phase_angle" if metric == SAMPLING_METRIC_SOLAR_PHASE else "elev"
    score = compute_plan_quality(
        selected_plan=selected if selected is not None else pd.DataFrame(),
        candidate_df=reduced if reduced is not None else pd.DataFrame(),
        spacing_min=float(spacing_min),
        metric_logical=metric_logical,
        sampling_diagnostics=diagnostics_proxy,
        selected_row_records=_selected_row_id_records(selected),
    )
    return list(_plain_quality_value(score.lexicographic_score))


def _row_identity_payload(row: pd.Series) -> str:
    """Return a stable text payload for deterministic repair tie-breaking.

    Parameters
    ----------
    row : pandas.Series
        Candidate row from the reduced backend candidate pool.

    Returns
    -------
    str
        Stable identity payload built from the most specific available row
        identity and deterministic fallback fields.
    """
    key = _identity_key_from_row(row)
    if key is not None:
        return f"{key[0]}={key[1]!r}"
    parts: list[str] = []
    for column in ("satellite", "datetime", "sampling_bin", "sampling_metric", "pass_id"):
        if column not in row.index:
            continue
        value = row[column]
        if isinstance(value, pd.Timestamp):
            value = value.isoformat()
        elif isinstance(value, np.generic):
            value = value.item()
        parts.append(f"{column}={value!r}")
    return "|".join(parts)


def _stable_repair_tie_breaker(row: pd.Series, *, seed: int) -> int:
    """Return a deterministic seed-aware tie-breaker for a repair candidate.

    Python's built-in ``hash`` is intentionally salted per process.  A short
    SHA-256 digest gives stable ordering across operating systems, Python
    versions, and GUI sessions while still allowing the random seed to affect
    tie-breaking deterministically.
    """
    return _stable_repair_tie_breaker_from_payload(_row_identity_payload(row), seed=seed)


def _stable_repair_tie_breaker_from_payload(payload: str, *, seed: int) -> int:
    """Return the deterministic tie-breaker for an already-built identity payload."""
    digest_input = f"{int(seed)}|{payload}".encode("utf-8", errors="replace")
    return int.from_bytes(hashlib.sha256(digest_input).digest()[:8], byteorder="big", signed=False)


def _candidate_time_ns(row: pd.Series) -> int | None:
    """Return a candidate timestamp in nanoseconds, or ``None`` when invalid."""
    candidate_time = pd.to_datetime(row.get("datetime"), errors="coerce")
    if pd.isna(candidate_time):
        return None
    return int(candidate_time.to_datetime64().astype("datetime64[ns]").astype("int64"))


def _insert_sorted_ns(values: np.ndarray, value: int) -> np.ndarray:
    """Return a sorted timestamp array with one timestamp inserted."""
    if values.size == 0:
        return np.array([int(value)], dtype="int64")
    position = int(np.searchsorted(values, int(value), side="left"))
    return np.insert(values, position, int(value)).astype("int64", copy=False)


def _candidate_id_record_from_row(row: pd.Series, *, output_row: int | None = None) -> dict[str, object]:
    """Return a JSON-friendly identity record for an inserted repair row."""
    record: dict[str, object] = {}
    if output_row is not None:
        record["output_row"] = int(output_row)
    for column in ("global_index", "base_index", "local_index", "satellite", "datetime", "sampling_metric", "sampling_bin", "pass_id"):
        if column not in row.index:
            continue
        value = row[column]
        if isinstance(value, pd.Timestamp):
            record[column] = value.isoformat()
        elif isinstance(value, np.generic):
            record[column] = value.item()
        else:
            try:
                record[column] = None if pd.isna(value) else value
            except Exception:
                record[column] = value
    return record


def _safe_int(value: object, default: int) -> int:
    """Return ``value`` as ``int`` or a fallback default."""
    try:
        return int(float(value))
    except Exception:
        return int(default)


def validate_local_repair_candidate_limit(value: object, *, maximum: int = DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT) -> int:
    """Return a bounded candidate-scan limit for local repair."""
    limit = _safe_int(value, DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT)
    return max(0, min(int(maximum), limit))


def validate_local_repair_attempt_limit(value: object, *, maximum: int = DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT) -> int:
    """Return a bounded active-repair attempt limit."""
    limit = _safe_int(value, DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT)
    return max(0, min(int(maximum), limit))


def validate_local_repair_max_additions(
    value: object,
    *,
    sample_bins: int | None = None,
    maximum: int = DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS,
) -> int:
    """Return the bounded maximum number of local-repair additions.

    The first active repair slice intentionally keeps the bound small.  By
    default, the effective limit is no larger than the number of sampling bins
    and no larger than ``DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS``.
    """
    requested = _safe_int(value, DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS)
    bin_bound = int(sample_bins) if sample_bins is not None else int(maximum)
    bin_bound = max(0, bin_bound)
    return max(0, min(int(maximum), bin_bound, requested))


def _build_local_repair_summary(
    *,
    reduced: pd.DataFrame,
    selected: pd.DataFrame,
    spacing_min: float,
    metric: str,
    missing_bins: Sequence[int],
    actual_bins: int,
    bin_diagnostics: Sequence[BinDiagnostics],
    repair_enabled: bool,
    repair_max_additions: int,
    repair_candidate_limit: int,
    repair_attempt_limit: int,
    random_seed: int,
    cancel_callback: Callable[[], bool] | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Analyze or apply deterministic compatible additive local repair.

    Parameters
    ----------
    reduced : pandas.DataFrame
        Reduced backend candidate pool created by stratified sampling.
    selected : pandas.DataFrame
        Primary spacing-valid plan produced by weighted interval selection.
    spacing_min : float
        Hard minimum spacing in minutes.  Active repair never relaxes it.
    metric : str
        Sampling metric identifier.
    missing_bins : sequence of int
        Bins not represented in the primary selected plan.
    actual_bins : int
        Number of available bins for diagnostics scoring.
    bin_diagnostics : sequence of BinDiagnostics
        Per-bin diagnostics before local repair.
    repair_enabled : bool
        When `True`, apply bounded compatible additive insertions.  When
        `False`, perform the 31D-A dry-run analysis only.
    repair_max_additions : int
        Maximum accepted insertions in active mode.
    repair_candidate_limit : int
        Maximum reduced-pool candidates scanned for repair.
    repair_attempt_limit : int
        Maximum active insertion attempts after deterministic ranking.
    random_seed : int
        Seed used only for stable tie-breaking among candidates with identical
        repair priority.

    Returns
    -------
    tuple
        ``(possibly_repaired_selected_df, local_repair_summary)``.
    """
    reduced_rows = 0 if reduced is None else int(len(reduced))
    selected_original = selected.copy().reset_index(drop=True) if selected is not None else pd.DataFrame()
    selected_work = selected_original.copy()
    selected_rows = int(len(selected_work))
    spacing_ns = int(float(spacing_min) * 60.0 * 1_000_000_000)
    selected_times_ns = _datetime_ns_array(selected_work.get("datetime", pd.Series(dtype=object)))
    selected_keys = _identity_key_set(selected_work)
    missing_bin_set = {int(value) for value in missing_bins or ()}
    score_proxy = SimpleSamplingDiagnosticsProxy(actual_bins=actual_bins, bin_diagnostics=bin_diagnostics)
    score_before = _quality_score_tuple_for_repair(
        selected=selected_work,
        reduced=reduced if reduced is not None else pd.DataFrame(),
        spacing_min=float(spacing_min),
        metric=metric,
        diagnostics_proxy=score_proxy,
    )

    candidate_limit = validate_local_repair_candidate_limit(repair_candidate_limit)
    attempt_limit = validate_local_repair_attempt_limit(repair_attempt_limit)
    max_additions = validate_local_repair_max_additions(repair_max_additions)
    if not repair_enabled:
        max_additions = 0

    if reduced is None or reduced.empty or candidate_limit <= 0:
        summary = {
            "repair_enabled": bool(repair_enabled),
            "repair_dry_run": not bool(repair_enabled),
            "repair_mode": "compatible_additive_insertion" if repair_enabled else "compatible_additive_insertion_dry_run",
            "candidate_pool_rows": reduced_rows,
            "already_selected_rows": selected_rows,
            "eligible_candidate_rows": 0,
            "compatible_insert_count": 0,
            "missing_bin_opportunity_count": 0,
            "large_gap_opportunity_count": 0,
            "underrepresented_satellite_compatible_count": 0,
            "metric_range_opportunity_count": 0,
            "attempted_insertions": 0,
            "accepted_insertions": 0,
            "rejected_spacing_count": 0,
            "final_selected_rows": selected_rows,
            "spacing_preserved": True,
            "score_before": score_before,
            "score_after": score_before,
            "selected_row_ids_added": [],
            "candidate_limit": int(candidate_limit),
            "attempt_limit": int(attempt_limit),
            "max_additions": int(max_additions),
        }
        return selected_work, summary

    selected_satellite_counts = (
        selected_work.get("satellite", pd.Series(dtype=object)).astype(str).value_counts().to_dict()
        if not selected_work.empty and "satellite" in selected_work.columns
        else {}
    )
    max_satellite_count = max(selected_satellite_counts.values()) if selected_satellite_counts else 0
    selected_metric_values = pd.to_numeric(
        selected_work.get("sampling_metric", pd.Series(dtype="float64")),
        errors="coerce",
    )
    selected_metric_values = selected_metric_values[np.isfinite(selected_metric_values)]
    selected_metric_min = float(selected_metric_values.min()) if not selected_metric_values.empty else None
    selected_metric_max = float(selected_metric_values.max()) if not selected_metric_values.empty else None

    eligible_candidate_rows = 0
    compatible_insert_count = 0
    missing_bin_opportunity_count = 0
    large_gap_opportunity_count = 0
    underrepresented_satellite_compatible_count = 0
    metric_range_opportunity_count = 0
    rejected_spacing_count = 0
    repair_candidates: list[dict[str, object]] = []

    # Column primitives are extracted once for the whole scan.  Per-row pandas
    # Series construction (iterrows) previously dominated multi-start runtime;
    # every mask below replicates the original per-row control flow exactly
    # via the shared scalar helpers (_identity_key_from_primitives,
    # _vectorized_spacing_compatibility, _stable_repair_tie_breaker_from_payload).
    work = reduced.head(candidate_limit)
    row_count = int(len(work))
    if row_count:
        _check_cancel(cancel_callback)
        datetime_present = "datetime" in work.columns
        if datetime_present:
            timestamps = pd.to_datetime(work["datetime"], errors="coerce")
        else:
            timestamps = pd.Series([pd.NaT] * row_count)
        valid_time = timestamps.notna().to_numpy()
        time_ns_values = timestamps.to_numpy(dtype="datetime64[ns]").view("int64")

        index_arrays = [(column, work[column].to_numpy()) for column in _IDENTITY_INDEX_COLUMNS if column in work.columns]
        satellite_present = "satellite" in work.columns
        satellite_values = work["satellite"].to_numpy() if satellite_present else None
        floored_timestamps = timestamps.dt.floor("s").tolist()
        iso_values: list[str | None] = [
            floored_timestamps[position].isoformat() if valid_time[position] else None
            for position in range(row_count)
        ]
        keys: list[tuple[str, object] | None] = [
            _identity_key_from_primitives(
                [(column, values[position]) for column, values in index_arrays],
                satellite=satellite_values[position] if satellite_present else _MISSING_FIELD,
                prefloored_isoformat=iso_values[position],
            )
            for position in range(row_count)
        ]

        key_duplicate = np.fromiter(
            (key is not None and key in selected_keys for key in keys),
            dtype=bool,
            count=row_count,
        )
        eligible_mask = ~key_duplicate & valid_time
        compatible_arr, large_gap_arr = _vectorized_spacing_compatibility(
            time_ns_values,
            selected_times_ns,
            spacing_ns=spacing_ns,
        )
        compatible_mask = eligible_mask & compatible_arr

        eligible_candidate_rows = int(eligible_mask.sum())
        rejected_spacing_count = int((eligible_mask & ~compatible_arr).sum())
        compatible_insert_count = int(compatible_mask.sum())

        if "sampling_bin" in work.columns:
            bin_values = pd.to_numeric(work["sampling_bin"], errors="coerce").fillna(-1).astype("int64").to_numpy()
        else:
            bin_values = np.full(row_count, -1, dtype="int64")
        if missing_bin_set:
            missing_bin_flags = np.isin(bin_values, np.fromiter(missing_bin_set, dtype="int64"))
        else:
            missing_bin_flags = np.zeros(row_count, dtype=bool)
        missing_bin_opportunity_count = int((compatible_mask & missing_bin_flags).sum())
        large_gap_opportunity_count = int((compatible_mask & large_gap_arr).sum())

        satellite_strings = [str(value) for value in satellite_values] if satellite_present else [""] * row_count
        if max_satellite_count == 0:
            underrepresented_flags = np.ones(row_count, dtype=bool)
        else:
            satellite_counts = np.fromiter(
                (int(selected_satellite_counts.get(name, 0)) for name in satellite_strings),
                dtype="int64",
                count=row_count,
            )
            underrepresented_flags = satellite_counts < max_satellite_count
        underrepresented_satellite_compatible_count = int((compatible_mask & underrepresented_flags).sum())

        if "sampling_metric" in work.columns:
            metric_values = pd.to_numeric(work["sampling_metric"], errors="coerce").to_numpy(dtype="float64")
        else:
            metric_values = np.full(row_count, np.nan)
        finite_metric = np.isfinite(metric_values)
        if selected_metric_min is not None and selected_metric_max is not None:
            metric_extension_flags = finite_metric & (
                (metric_values < selected_metric_min) | (metric_values > selected_metric_max)
            )
        elif selected_metric_min is None:
            metric_extension_flags = finite_metric.copy()
        else:
            metric_extension_flags = np.zeros(row_count, dtype=bool)
        metric_range_opportunity_count = int((compatible_mask & metric_extension_flags).sum())

        for position in np.flatnonzero(compatible_mask):
            position = int(position)
            key = keys[position]
            if key is not None:
                tie_value = _stable_repair_tie_breaker_from_payload(
                    f"{key[0]}={key[1]!r}",
                    seed=int(random_seed),
                )
            else:
                tie_value = _stable_repair_tie_breaker(work.iloc[position], seed=int(random_seed))
            repair_candidates.append(
                {
                    "position": position,
                    "time_ns": int(time_ns_values[position]),
                    "identity_key": key,
                    "missing_bin": bool(missing_bin_flags[position]),
                    "large_gap": bool(large_gap_arr[position]),
                    "underrepresented": bool(underrepresented_flags[position]),
                    "metric_extension": bool(metric_extension_flags[position]),
                    "tie": tie_value,
                    "reduced_position": position,
                }
            )

    attempted_insertions = 0
    accepted_insertions = 0
    selected_row_ids_added: list[dict[str, object]] = []

    if repair_enabled and max_additions > 0 and attempt_limit > 0 and repair_candidates:
        # Lower sort values are attempted first.  The tuple order implements the
        # approved 31D-B priority ladder and then uses a seed-aware stable tie.
        ranked = sorted(
            repair_candidates,
            key=lambda item: (
                not bool(item["missing_bin"]),
                not bool(item["large_gap"]),
                not bool(item["underrepresented"]),
                not bool(item["metric_extension"]),
                int(item["tie"]),
                int(item["reduced_position"]),
            ),
        )
        accepted_positions: list[int] = []
        for item in ranked[:attempt_limit]:
            if accepted_insertions >= max_additions:
                break
            attempted_insertions += 1
            key = item.get("identity_key")
            if key is not None and key in selected_keys:
                continue
            candidate_time_ns = int(item["time_ns"])
            compatible, _ = _candidate_compatible_with_selected(
                candidate_time_ns,
                selected_times_ns,
                spacing_ns=spacing_ns,
            )
            if not compatible:
                rejected_spacing_count += 1
                continue

            selected_times_ns = _insert_sorted_ns(selected_times_ns, candidate_time_ns)
            if key is not None:
                selected_keys.add(key)
            accepted_insertions += 1
            accepted_positions.append(int(item["position"]))
            selected_row_ids_added.append(_candidate_id_record_from_row(work.iloc[int(item["position"])]))

        # The acceptance loop only consults selected_times_ns/selected_keys
        # between acceptances, and spacing-compatible plans cannot contain
        # duplicate datetimes, so one batched concat+sort reproduces the
        # per-acceptance concat+sort result exactly.
        if accepted_positions:
            added_frames = [pd.DataFrame([work.iloc[position]]) for position in accepted_positions]
            selected_work = pd.concat([selected_work, *added_frames], ignore_index=True)
            selected_work = selected_work.sort_values("datetime").reset_index(drop=True)

    if accepted_insertions == 0:
        # No rows changed, so the deterministic score is unchanged; skip the
        # redundant recompute (always the case in dry-run mode).
        score_after = list(score_before)
    else:
        score_after = _quality_score_tuple_for_repair(
            selected=selected_work,
            reduced=reduced if reduced is not None else pd.DataFrame(),
            spacing_min=float(spacing_min),
            metric=metric,
            diagnostics_proxy=score_proxy,
        )
    final_selected_rows = int(len(selected_work))
    spacing_preserved = True
    if final_selected_rows > 1:
        deltas = np.diff(_datetime_ns_array(selected_work.get("datetime", pd.Series(dtype=object))))
        spacing_preserved = bool(np.all(deltas >= spacing_ns)) if deltas.size else True

    for output_row, record in enumerate(selected_row_ids_added):
        record.setdefault("output_row", int(output_row))

    summary = {
        "repair_enabled": bool(repair_enabled),
        "repair_dry_run": not bool(repair_enabled),
        "repair_mode": "compatible_additive_insertion" if repair_enabled else "compatible_additive_insertion_dry_run",
        "candidate_pool_rows": reduced_rows,
        "already_selected_rows": selected_rows,
        "eligible_candidate_rows": int(eligible_candidate_rows),
        "compatible_insert_count": int(compatible_insert_count),
        "missing_bin_opportunity_count": int(missing_bin_opportunity_count),
        "large_gap_opportunity_count": int(large_gap_opportunity_count),
        "underrepresented_satellite_compatible_count": int(underrepresented_satellite_compatible_count),
        "metric_range_opportunity_count": int(metric_range_opportunity_count),
        "attempted_insertions": int(attempted_insertions),
        "accepted_insertions": int(accepted_insertions),
        "rejected_spacing_count": int(rejected_spacing_count),
        "final_selected_rows": final_selected_rows,
        "spacing_preserved": bool(spacing_preserved),
        "score_before": score_before,
        "score_after": score_after,
        "selected_row_ids_added": selected_row_ids_added,
        "candidate_limit": int(candidate_limit),
        "attempt_limit": int(attempt_limit),
        "max_additions": int(max_additions),
    }
    return selected_work, summary


# Backward-compatible alias used by the 31D-A verifier and by downstream
# review scripts that explicitly refer to the dry-run implementation name.
def _build_local_repair_dry_run_summary(
    *,
    reduced: pd.DataFrame,
    selected: pd.DataFrame,
    spacing_min: float,
    metric: str,
    missing_bins: Sequence[int],
    actual_bins: int,
    bin_diagnostics: Sequence[BinDiagnostics],
) -> dict[str, object]:
    """Analyze compatible repair opportunities without modifying rows."""
    _, summary = _build_local_repair_summary(
        reduced=reduced,
        selected=selected,
        spacing_min=spacing_min,
        metric=metric,
        missing_bins=missing_bins,
        actual_bins=actual_bins,
        bin_diagnostics=bin_diagnostics,
        repair_enabled=False,
        repair_max_additions=0,
        repair_candidate_limit=DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT,
        repair_attempt_limit=DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT,
        random_seed=DEFAULT_RANDOM_SEED,
    )
    return summary


@dataclass(frozen=True)
class SimpleSamplingDiagnosticsProxy:
    """Minimal quality-metric adapter for local-repair dry-run scoring."""

    actual_bins: int
    bin_diagnostics: Sequence[BinDiagnostics]

def _sample_values(values: pd.Series, limit: int = 5000) -> list[float]:
    """Return a deterministic bounded list of finite numeric values."""
    numeric = pd.to_numeric(values, errors="coerce")
    numeric = numeric[np.isfinite(numeric)].reset_index(drop=True)
    if len(numeric) > limit:
        indices = np.linspace(0, len(numeric) - 1, limit, dtype=int)
        numeric = numeric.iloc[indices]
    return [float(value) for value in numeric.tolist()]


def _sample_epoch_seconds(values: pd.Series, limit: int = 5000) -> list[float]:
    """Return a bounded list of UTC epoch-second timestamps."""
    timestamps = pd.to_datetime(values, errors="coerce", utc=True).dropna().reset_index(drop=True)
    if len(timestamps) > limit:
        indices = np.linspace(0, len(timestamps) - 1, limit, dtype=int)
        timestamps = timestamps.iloc[indices]
    if len(timestamps) == 0:
        return []
    epoch_ns = timestamps.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]").astype("int64")
    return [float(value) / 1.0e9 for value in epoch_ns]


def _selected_row_id_records(selected: pd.DataFrame) -> tuple[dict[str, object], ...]:
    """Return selected row identity records for reproducibility."""
    if selected is None or selected.empty:
        return ()
    # Columns are extracted once; the per-value coercion below matches the
    # historical per-row (iterrows) implementation exactly while avoiding its
    # per-row Series construction cost in the multi-start hot path.
    column_arrays = [
        (column, selected[column].to_numpy())
        for column in ("global_index", "base_index", "local_index", "satellite", "datetime", "sampling_metric", "sampling_bin", "pass_id")
        if column in selected.columns
    ]
    records: list[dict[str, object]] = []
    for output_row in range(len(selected)):
        record: dict[str, object] = {"output_row": int(output_row)}
        for column, values in column_arrays:
            value = values[output_row]
            if isinstance(value, np.datetime64):
                value = pd.Timestamp(value) if not np.isnat(value) else pd.NaT
            if isinstance(value, pd.Timestamp):
                record[column] = value.isoformat()
            elif isinstance(value, np.generic):
                record[column] = value.item()
            elif pd.isna(value):
                record[column] = None
            else:
                record[column] = value
        records.append(record)
    return tuple(records)


def _local_repair_plot_series(local_repair_summary: Mapping[str, object] | None) -> dict[str, object]:
    """Return plot-series points for repair-added observations.

    Parameters
    ----------
    local_repair_summary : mapping or None
        Local-repair diagnostics summary containing ``selected_row_ids_added``.

    Returns
    -------
    dict
        JSON-serializable repair-added time/metric arrays.
    """
    records = []
    if local_repair_summary:
        raw_records = local_repair_summary.get("selected_row_ids_added")
        if isinstance(raw_records, Sequence) and not isinstance(raw_records, (str, bytes)):
            records = [record for record in raw_records if isinstance(record, Mapping)]
    return {
        "repair_added_times": _sample_epoch_seconds(pd.Series([record.get("datetime") for record in records])),
        "repair_added_metric_values": _sample_values(pd.Series([record.get("sampling_metric") for record in records])),
        "repair_added_count": int(len(records)),
    }


def _sampling_plot_series(
    candidates: pd.DataFrame,
    reduced: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    metric: str,
    edge_pairs: Sequence[tuple[float | None, float | None]],
    local_repair_summary: Mapping[str, object] | None = None,
    binning_mode: str | None = None,
    bin_width_deg: float | None = None,
    bin_anchor_policy: str | None = None,
) -> dict[str, object]:
    """Build GUI/web-ready numeric diagnostics series for sampling."""
    available_bins = sorted(int(value) for value in candidates.get("sampling_bin", pd.Series(dtype=int)).dropna().unique())
    bin_edges: list[float] = []
    if edge_pairs:
        bin_edges = [float(edge_pairs[0][0])] if edge_pairs[0][0] is not None else []
        for _, right in edge_pairs:
            if right is not None:
                bin_edges.append(float(right))
    series = {
        "metric_name": metric,
        "metric_input_values": _sample_values(candidates.get("sampling_metric", pd.Series(dtype=float))),
        "metric_reduced_values": _sample_values(reduced.get("sampling_metric", pd.Series(dtype=float))),
        "metric_selected_values": _sample_values(selected.get("sampling_metric", pd.Series(dtype=float))),
        "candidate_times": _sample_epoch_seconds(candidates.get("datetime", pd.Series(dtype=object))),
        "candidate_metric_values": _sample_values(candidates.get("sampling_metric", pd.Series(dtype=float))),
        "reduced_times": _sample_epoch_seconds(reduced.get("datetime", pd.Series(dtype=object))),
        "reduced_metric_values": _sample_values(reduced.get("sampling_metric", pd.Series(dtype=float))),
        "selected_times": _sample_epoch_seconds(selected.get("datetime", pd.Series(dtype=object))),
        "selected_metric_values": _sample_values(selected.get("sampling_metric", pd.Series(dtype=float))),
        "spacing_deltas_minutes": [float(value) for value in pd.to_datetime(selected.get("datetime", pd.Series(dtype=object)), errors="coerce", utc=True).dropna().sort_values().diff().dropna().dt.total_seconds().div(60.0).tolist()],
        "bin_ids": available_bins,
        "bin_edges": bin_edges,
        "binning_mode": binning_mode,
        "bin_width_deg": bin_width_deg,
        "bin_anchor_policy": bin_anchor_policy,
        "bin_counts_input": [int((candidates["sampling_bin"] == bin_id).sum()) for bin_id in available_bins],
        "bin_counts_reduced": [int((reduced["sampling_bin"] == bin_id).sum()) if not reduced.empty else 0 for bin_id in available_bins],
        "bin_counts_selected": [int((selected["sampling_bin"] == bin_id).sum()) if not selected.empty else 0 for bin_id in available_bins],
    }
    series.update(_local_repair_plot_series(local_repair_summary))
    return series


def _prepare_stratified_sampling_problem(
    visibility_df: pd.DataFrame,
    *,
    request: SamplingPlannerRequest,
    column_mapping=None,
    progress_callback: Callable[[str], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
) -> PreparedStratifiedSamplingProblem:
    """Prepare invariant stratified candidate state once per plan generation.

    This function contains the seed-independent work that must not be repeated
    for every multi-start trial on constellation-scale inputs.
    """
    _check_cancel(cancel_callback)
    method = normalize_plan_method(request.plan_method)
    if method == PLAN_METHOD_MAX_ELEVATION:
        raise ValueError("Stratified sampling preparation requires a stratified sampling method.")

    t_prepare = time.perf_counter()
    metric = request.metric()
    binning_mode = normalize_binning_mode(request.binning_mode)
    requested_bins = max(1, int(request.sample_bins))
    input_rows = 0 if visibility_df is None else len(visibility_df)

    def _problem(
        candidates: pd.DataFrame,
        *,
        filtered_rows: int,
        invalid_metric_rows: int,
        actual_bins: int,
        edge_pairs: Sequence[tuple[float | None, float | None]] = (),
        pass_groups: int = 0,
    ) -> PreparedStratifiedSamplingProblem:
        group_indices = _prepared_group_indices(candidates)
        bin_count_pairs = _prepared_bin_counts(candidates)
        candidate_bin_counts = {int(bin_id): int(count) for bin_id, count in bin_count_pairs}
        available_bin_ids = tuple(int(bin_id) for bin_id, _ in bin_count_pairs)
        return PreparedStratifiedSamplingProblem(
            method=method,
            metric=metric,
            binning_mode=binning_mode,
            bin_width_deg=validate_bin_width_deg(request.bin_width_deg) if binning_mode == BINNING_FIXED_WIDTH else None,
            bin_anchor_policy="zero_grid_physical_width" if binning_mode == BINNING_FIXED_WIDTH else "observed_range",
            bin_domain_min_deg=_metric_domain(metric)[0] if binning_mode == BINNING_FIXED_WIDTH else None,
            bin_domain_max_deg=_metric_domain(metric)[1] if binning_mode == BINNING_FIXED_WIDTH else None,
            requested_bins=requested_bins,
            actual_bins=int(actual_bins),
            input_rows=int(input_rows),
            filtered_rows=int(filtered_rows),
            invalid_metric_rows=int(invalid_metric_rows),
            candidate_rows=int(len(candidates)),
            pass_groups=int(pass_groups),
            edge_pairs=tuple(edge_pairs),
            candidates=candidates,
            group_indices=group_indices,
            group_count=int(len(group_indices)),
            available_bin_ids=available_bin_ids,
            candidate_bin_counts=candidate_bin_counts,
        )

    if visibility_df is None or visibility_df.empty:
        _emit_progress(progress_callback, "Stratified sampler: prepared empty candidate problem in 0.000 s.")
        return _problem(pd.DataFrame(columns=[]), filtered_rows=0, invalid_metric_rows=0, actual_bins=0)

    _check_cancel(cancel_callback)
    candidates = visibility_df.copy().reset_index(drop=True)
    t_metric = time.perf_counter()
    metric_col = _metric_column(candidates, metric, column_mapping=column_mapping)
    values = _validated_metric_values(candidates, metric_col, metric)
    invalid_metric_rows = int(values.isna().sum())
    candidates = candidates.loc[values.notna()].copy()
    candidates["sampling_metric"] = values.loc[candidates.index].astype(float)
    candidates["satellite"] = candidates["satellite"].astype(str).map(clean_satellite_name)
    candidates["datetime"] = pd.to_datetime(candidates["datetime"], errors="coerce").dt.floor("s")
    candidates = candidates.dropna(subset=["datetime", "satellite", "sampling_metric"]).copy()
    metric_elapsed = time.perf_counter() - t_metric

    _check_cancel(cancel_callback)
    if candidates.empty:
        _emit_progress(
            progress_callback,
            (
                f"Stratified sampler: metric/date preparation retained 0/{input_rows} row(s) "
                f"in {metric_elapsed:.3f} s."
            ),
        )
        return _problem(candidates, filtered_rows=0, invalid_metric_rows=invalid_metric_rows, actual_bins=0)

    _check_cancel(cancel_callback)
    t_bins = time.perf_counter()
    bin_ids, edge_pairs = _assign_bins(candidates["sampling_metric"], request=request, metric=metric)
    candidates["sampling_bin"] = bin_ids
    candidates = candidates.dropna(subset=["sampling_bin"]).copy()
    # Binning metadata intentionally lives on PreparedStratifiedSamplingProblem
    # fields, not DataFrame.attrs: pandas deep-copies non-empty attrs into
    # every derived row/slice via __finalize__, a hidden per-operation tax in
    # the multi-start hot path.
    if not candidates.empty:
        candidates["sampling_bin"] = candidates["sampling_bin"].astype(int)
    actual_bins = len(edge_pairs) if edge_pairs else int(candidates["sampling_bin"].nunique()) if not candidates.empty else 0
    bins_elapsed = time.perf_counter() - t_bins

    if candidates.empty:
        _emit_progress(
            progress_callback,
            (
                f"Stratified sampler: assigned {actual_bins} bin(s) but retained 0 candidate row(s) "
                f"in {bins_elapsed:.3f} s."
            ),
        )
        return _problem(candidates, filtered_rows=0, invalid_metric_rows=invalid_metric_rows, actual_bins=actual_bins, edge_pairs=edge_pairs)

    _check_cancel(cancel_callback)
    t_pass = time.perf_counter()
    candidates["pass_id"] = _assign_pass_ids(candidates, request.spacing_min)
    pass_groups = int(candidates["pass_id"].nunique())
    pass_elapsed = time.perf_counter() - t_pass
    total_elapsed = time.perf_counter() - t_prepare

    _emit_progress(
        progress_callback,
        (
            f"Stratified sampler: prepared {len(candidates)} candidate row(s), "
            f"{pass_groups} pass group(s), {actual_bins} bin(s) in {total_elapsed:.3f} s "
            f"(metric={metric_elapsed:.3f} s, bins={bins_elapsed:.3f} s, pass_ids={pass_elapsed:.3f} s)."
        ),
    )
    return _problem(
        candidates,
        filtered_rows=len(candidates),
        invalid_metric_rows=invalid_metric_rows,
        actual_bins=actual_bins,
        edge_pairs=edge_pairs,
        pass_groups=pass_groups,
    )


def _build_stratified_trial_diagnostics(
    *,
    problem: PreparedStratifiedSamplingProblem,
    request: SamplingPlannerRequest,
    reduced: pd.DataFrame,
    selected: pd.DataFrame,
    local_repair_summary: Mapping[str, object],
    build_plot_series: bool = True,
) -> SamplingPlannerDiagnostics:
    """Build diagnostics for one stratified trial from prepared candidates."""
    candidates = problem.candidates
    available_bins = set(int(value) for value in (problem.available_bin_ids or ()))
    if not available_bins and candidates is not None and not candidates.empty:
        available_bins = set(int(value) for value in candidates.get("sampling_bin", pd.Series(dtype=int)).dropna().unique())
    selected_bins = set(int(value) for value in selected.get("sampling_bin", pd.Series(dtype=int)).dropna().unique())
    missing_bins = tuple(sorted(available_bins - selected_bins))
    reduced_counts = (
        reduced["sampling_bin"].dropna().astype(int).value_counts(sort=False).to_dict()
        if reduced is not None and not reduced.empty and "sampling_bin" in reduced.columns
        else {}
    )
    selected_counts = (
        selected["sampling_bin"].dropna().astype(int).value_counts(sort=False).to_dict()
        if selected is not None and not selected.empty and "sampling_bin" in selected.columns
        else {}
    )

    bin_diag: list[BinDiagnostics] = []
    for bin_id in sorted(available_bins):
        lower = upper = None
        if 0 <= bin_id < len(problem.edge_pairs):
            lower, upper = problem.edge_pairs[bin_id]
        bin_diag.append(
            BinDiagnostics(
                bin_id=bin_id,
                candidate_count=int(problem.candidate_bin_counts.get(bin_id, 0)),
                reduced_candidate_count=int(reduced_counts.get(bin_id, 0)),
                selected_count=int(selected_counts.get(bin_id, 0)),
                lower_edge=lower,
                upper_edge=upper,
            )
        )

    plot_series = {}
    if build_plot_series:
        plot_series = _sampling_plot_series(
            candidates,
            reduced,
            selected,
            metric=problem.metric,
            edge_pairs=problem.edge_pairs,
            local_repair_summary=local_repair_summary,
            binning_mode=problem.binning_mode,
            bin_width_deg=problem.bin_width_deg,
            bin_anchor_policy=problem.bin_anchor_policy,
        )

    return SamplingPlannerDiagnostics(
        method=problem.method,
        metric=problem.metric,
        binning_mode=problem.binning_mode,
        requested_bins=problem.requested_bins,
        actual_bins=problem.actual_bins,
        input_rows=problem.input_rows,
        filtered_rows=problem.filtered_rows,
        invalid_metric_rows=problem.invalid_metric_rows,
        candidate_rows=problem.candidate_rows,
        reduced_candidate_rows=len(reduced),
        selected_rows=len(selected),
        achieved_bins=len(selected_bins),
        missing_bins=missing_bins,
        spacing_min=float(request.spacing_min),
        random_seed=int(request.random_seed),
        pass_groups=problem.pass_groups,
        candidate_depth=validate_candidate_depth(request.candidate_depth),
        bin_diagnostics=tuple(bin_diag),
        selected_row_ids=_selected_row_id_records(selected),
        plot_series=plot_series,
        local_repair_summary=dict(local_repair_summary or {}),
        bin_width_deg=problem.bin_width_deg,
        bin_anchor_policy=problem.bin_anchor_policy,
        bin_domain_min_deg=problem.bin_domain_min_deg,
        bin_domain_max_deg=problem.bin_domain_max_deg,
    )


def _local_repair_deferred_summary(
    *,
    reduced: pd.DataFrame,
    selected: pd.DataFrame,
    spacing_min: float,
    metric: str,
    bin_diagnostics: Sequence[BinDiagnostics],
    candidate_limit: int,
    attempt_limit: int,
    max_additions: int,
) -> dict[str, object]:
    """Return a fast placeholder when dry-run repair is deferred to final diagnostics."""
    selected_rows = 0 if selected is None else int(len(selected))
    score_proxy = SimpleSamplingDiagnosticsProxy(actual_bins=len(bin_diagnostics), bin_diagnostics=bin_diagnostics)
    score = _quality_score_tuple_for_repair(
        selected=selected if selected is not None else pd.DataFrame(),
        reduced=reduced if reduced is not None else pd.DataFrame(),
        spacing_min=float(spacing_min),
        metric=metric,
        diagnostics_proxy=score_proxy,
    )
    return {
        "repair_enabled": False,
        "repair_dry_run": True,
        "repair_deferred": True,
        "repair_mode": "compatible_additive_insertion_dry_run_deferred",
        "candidate_pool_rows": 0 if reduced is None else int(len(reduced)),
        "already_selected_rows": selected_rows,
        "eligible_candidate_rows": 0,
        "compatible_insert_count": 0,
        "missing_bin_opportunity_count": 0,
        "large_gap_opportunity_count": 0,
        "underrepresented_satellite_compatible_count": 0,
        "metric_range_opportunity_count": 0,
        "attempted_insertions": 0,
        "accepted_insertions": 0,
        "rejected_spacing_count": 0,
        "final_selected_rows": selected_rows,
        "spacing_preserved": True,
        "score_before": score,
        "score_after": score,
        "selected_row_ids_added": [],
        "candidate_limit": int(candidate_limit),
        "attempt_limit": int(attempt_limit),
        "max_additions": int(max_additions),
    }


def _run_stratified_sampling_trial(
    problem: PreparedStratifiedSamplingProblem,
    *,
    request: SamplingPlannerRequest,
    build_full_diagnostics: bool = True,
    run_repair_diagnostics: bool = True,
    cancel_callback: Callable[[], bool] | None = None,
) -> tuple[pd.DataFrame, SamplingPlannerDiagnostics, dict[str, float]]:
    """Run one seed-dependent stratified sampling trial."""
    rng = np.random.default_rng(int(request.random_seed))
    timings: dict[str, float] = {}

    t_reduce = time.perf_counter()
    _check_cancel(cancel_callback)
    if request.active_candidate_reduction_mode == CANDIDATE_REDUCTION_MODE_METRIC_INFORMED:
        # Investigation-only path -- see tools/dev/compare_candidate_reduction_strategies.py.
        reduced = _reduce_candidates_by_pass_bin_metric_informed(
            problem.candidates,
            rng=rng,
            candidate_depth=validate_candidate_depth(request.candidate_depth),
        )
    else:
        reduced = _reduce_prepared_candidates_by_pass_bin(
            problem,
            rng=rng,
            candidate_depth=validate_candidate_depth(request.candidate_depth),
            cancel_callback=cancel_callback,
        )
    timings["reduction_s"] = time.perf_counter() - t_reduce

    t_select = time.perf_counter()
    _check_cancel(cancel_callback)
    selected = _weighted_interval_select(reduced, spacing_min=request.spacing_min, rng=rng, cancel_callback=cancel_callback)
    timings["selection_s"] = time.perf_counter() - t_select

    available_bins = set(int(value) for value in (problem.available_bin_ids or ()))
    if not available_bins:
        available_bins = set(int(value) for value in problem.candidates.get("sampling_bin", pd.Series(dtype=int)).dropna().unique())
    selected_bins = set(int(value) for value in selected.get("sampling_bin", pd.Series(dtype=int)).dropna().unique())
    missing_bins = tuple(sorted(available_bins - selected_bins))
    pre_repair_bin_diag: list[BinDiagnostics] = []
    for bin_id in sorted(available_bins):
        lower = upper = None
        if 0 <= bin_id < len(problem.edge_pairs):
            lower, upper = problem.edge_pairs[bin_id]
        pre_repair_bin_diag.append(
            BinDiagnostics(
                bin_id=bin_id,
                candidate_count=int(problem.candidate_bin_counts.get(bin_id, 0)),
                reduced_candidate_count=int(reduced["sampling_bin"].eq(bin_id).sum()) if not reduced.empty else 0,
                selected_count=int(selected["sampling_bin"].eq(bin_id).sum()) if not selected.empty else 0,
                lower_edge=lower,
                upper_edge=upper,
            )
        )

    t_repair = time.perf_counter()
    repair_candidate_limit = validate_local_repair_candidate_limit(request.local_repair_candidate_limit)
    repair_attempt_limit = validate_local_repair_attempt_limit(request.local_repair_attempt_limit)
    repair_max_additions = validate_local_repair_max_additions(
        request.local_repair_max_additions,
        sample_bins=max(1, int(request.sample_bins)),
    )
    if bool(request.local_repair_enabled) or bool(run_repair_diagnostics):
        selected, local_repair_summary = _build_local_repair_summary(
            reduced=reduced,
            selected=selected,
            spacing_min=float(request.spacing_min),
            metric=problem.metric,
            missing_bins=missing_bins,
            actual_bins=problem.actual_bins,
            bin_diagnostics=tuple(pre_repair_bin_diag),
            repair_enabled=bool(request.local_repair_enabled),
            repair_max_additions=repair_max_additions,
            repair_candidate_limit=repair_candidate_limit,
            repair_attempt_limit=repair_attempt_limit,
            random_seed=int(request.random_seed),
            cancel_callback=cancel_callback,
        )
    else:
        local_repair_summary = _local_repair_deferred_summary(
            reduced=reduced,
            selected=selected,
            spacing_min=float(request.spacing_min),
            metric=problem.metric,
            bin_diagnostics=tuple(pre_repair_bin_diag),
            candidate_limit=repair_candidate_limit,
            attempt_limit=repair_attempt_limit,
            max_additions=0,
        )
    timings["repair_s"] = time.perf_counter() - t_repair

    t_transition = time.perf_counter()
    if request.active_transition_constraint_mode == TRANSITION_CONSTRAINT_PHYSICAL:
        pre_transition_selected_rows = int(len(selected))
        selected, _transition_summary, _transition_records = apply_physical_transition_filter(
            selected,
            model=request.active_slew_model,
            user_spacing_min=float(request.spacing_min),
            safety_margin_sec=request.active_transition_safety_margin_sec,
            transition_constraint_mode=request.active_transition_constraint_mode,
        )
        local_repair_summary = dict(local_repair_summary or {})
        local_repair_summary["transition_constraint_applied_after_repair"] = True
        local_repair_summary["pre_transition_selected_rows"] = pre_transition_selected_rows
        local_repair_summary["post_transition_selected_rows"] = int(len(selected))
    timings["transition_s"] = time.perf_counter() - t_transition

    t_diag = time.perf_counter()
    _check_cancel(cancel_callback)
    diagnostics = _build_stratified_trial_diagnostics(
        problem=problem,
        request=request,
        reduced=reduced,
        selected=selected,
        local_repair_summary=local_repair_summary,
        build_plot_series=bool(build_full_diagnostics),
    )
    timings["diagnostics_s"] = time.perf_counter() - t_diag
    timings["total_s"] = sum(timings.values())

    plan = selected.drop(columns=["sampling_metric", "sampling_bin", "pass_id"], errors="ignore").reset_index(drop=True)
    plan.attrs.update(getattr(selected, "attrs", {}))
    return plan, diagnostics, timings


def generate_stratified_sample_plan(
    visibility_df: pd.DataFrame,
    *,
    request: SamplingPlannerRequest,
    column_mapping=None,
    progress_callback: Callable[[str], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
) -> tuple[pd.DataFrame, SamplingPlannerDiagnostics]:
    """Generate a stratified spacing-safe observation plan."""
    problem = _prepare_stratified_sampling_problem(
        visibility_df,
        request=request,
        column_mapping=column_mapping,
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
    )
    plan, diagnostics, timings = _run_stratified_sampling_trial(problem, request=request, cancel_callback=cancel_callback)
    _emit_progress(
        progress_callback,
        (
            f"Stratified sampler: one-shot trial reduced {problem.candidate_rows} -> "
            f"{diagnostics.reduced_candidate_rows} row(s), selected {len(plan)} row(s) "
            f"in {timings.get('total_s', 0.0):.3f} s."
        ),
    )
    return plan, diagnostics


def validate_candidate_depth(value: object, *, maximum: int = MAX_CANDIDATE_DEPTH) -> int:
    """Return a bounded positive candidate-pool depth.

    Parameters
    ----------
    value : object
        Requested number of representatives retained per satellite/pass/bin
        group before global spacing selection.
    maximum : int, optional
        Upper safety bound.  The Task 31C guardrail is 16 candidates.

    Returns
    -------
    int
        Candidate depth clamped to ``[1, maximum]``.
    """
    try:
        depth = int(float(value))
    except Exception:
        depth = DEFAULT_CANDIDATE_DEPTH
    return max(1, min(int(maximum), depth))


def validate_optimization_trials(value: object, *, maximum: int = MAX_OPTIMIZATION_TRIALS) -> int:
    """Return a bounded positive multi-start trial count.

    Parameters
    ----------
    value : object
        Requested trial count.
    maximum : int, optional
        Upper safety bound.  The Task 31B guardrail is 256 trials.

    Returns
    -------
    int
        Trial count clamped to ``[1, maximum]``.
    """
    try:
        count = int(float(value))
    except Exception:
        count = DEFAULT_OPTIMIZATION_TRIALS
    return max(1, min(int(maximum), count))


def _plain_quality_value(value: Any) -> Any:
    """Return a JSON-friendly value for trial quality diagnostics."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_plain_quality_value(item) for item in value]
    if isinstance(value, list):
        return [_plain_quality_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain_quality_value(item) for key, item in value.items()}
    if isinstance(value, float) and not np.isfinite(value):
        if np.isposinf(value):
            return "Infinity"
        if np.isneginf(value):
            return "-Infinity"
        return None
    return value


def _trial_signature(plan_df: pd.DataFrame, selected_row_ids: Sequence[Mapping[str, object]]) -> tuple[object, ...]:
    """Return a stable signature for one sampled trial."""
    if plan_df is not None and "global_index" in plan_df.columns:
        values = []
        for value in plan_df["global_index"].tolist():
            try:
                if pd.isna(value):
                    continue
            except Exception:
                pass
            try:
                values.append(int(float(value)))
            except Exception:
                values.append(str(value))
        if values:
            return tuple(values)

    signature: list[tuple[object, ...]] = []
    for record in selected_row_ids or ():
        signature.append(
            (
                record.get("global_index"),
                record.get("base_index"),
                record.get("local_index"),
                record.get("satellite"),
                record.get("datetime"),
            )
        )
    return tuple(signature)


def _trial_summary(
    *,
    trial_index: int,
    trial_seed: int,
    plan_df: pd.DataFrame,
    diagnostics: SamplingPlannerDiagnostics,
    quality_score,
    signature: tuple[object, ...],
    optimization_objective: str = OPTIMIZATION_OBJECTIVE_QUALITY,
    active_score: tuple[object, ...] | None = None,
    slew_selection_payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return one auditable multi-start trial summary."""
    metrics = quality_score.metrics
    objective = normalize_optimization_objective(optimization_objective)
    summary = {
        "trial_index": int(trial_index),
        "trial_seed": int(trial_seed),
        "selected_count": int(metrics.selected_count),
        "unique_satellites": int(metrics.unique_satellite_count),
        "achieved_bins": int(metrics.achieved_bin_count),
        "actual_bins": int(metrics.actual_bin_count),
        "bin_balance_entropy": metrics.bin_balance_entropy,
        "satellite_dominance_ratio": metrics.satellite_dominance_ratio,
        "min_spacing_min": metrics.min_spacing_min,
        "spacing_violations": int(metrics.spacing_violation_count),
        "score_tuple": list(_plain_quality_value(quality_score.lexicographic_score)),
        "selection_score_tuple": list(_plain_quality_value(active_score or quality_score.lexicographic_score)),
        "selection_score_kind": "slew_aware" if objective == OPTIMIZATION_OBJECTIVE_SLEW_AWARE else "quality",
        "selected_global_indices": list(metrics.selected_global_indices),
        "signature": list(_plain_quality_value(signature)),
        "quality_summary": quality_score.compact_summary,
        "reduced_candidate_rows": int(diagnostics.reduced_candidate_rows),
        "candidate_rows": int(diagnostics.candidate_rows),
        "candidate_depth": int(diagnostics.candidate_depth),
    }
    if slew_selection_payload:
        summary["slew_aware_selection_score"] = _plain_quality_value(dict(slew_selection_payload))
    return summary


def _active_trial_selection_score(
    *,
    trial_plan: pd.DataFrame,
    quality_score,
    request: SamplingPlannerRequest,
    trial_index: int,
) -> tuple[tuple[object, ...], dict[str, object] | None]:
    """Return the active multi-start score for the requested objective.

    The default ``quality`` objective preserves the pre-Task-35D score exactly.
    The optional ``slew_aware`` objective evaluates a summary-only slew/path
    diagnostic for the trial and uses it as secondary path-aware score terms.
    """
    objective = request.active_optimization_objective
    if objective != OPTIMIZATION_OBJECTIVE_SLEW_AWARE:
        return quality_score.lexicographic_score, None

    summary, _records, _plot = compute_slew_path_diagnostics(
        trial_plan,
        model=request.active_slew_model,
        sample_limit=0,
    )
    payload = compute_slew_aware_selection_score(
        quality_score=quality_score,
        slew_path_summary=summary,
        trial_index=trial_index,
    )
    return tuple(payload.get("selection_score_tuple") or quality_score.lexicographic_score), payload


_PARETO_MISSING_VALUE = -1.0e12

_PARETO_OBJECTIVE_NAMES_QUALITY: tuple[str, ...] = (
    "neg_spacing_violation_count",
    "selected_count",
    "bin_coverage_ratio",
    "metric_range_coverage",
    "neg_satellite_dominance_ratio",
    "neg_pass_dominance_ratio",
)
_PARETO_OBJECTIVE_NAMES_SLEW_AWARE: tuple[str, ...] = _PARETO_OBJECTIVE_NAMES_QUALITY + (
    "neg_transition_violation_count",
    "neg_total_estimated_transition_sec",
    "neg_max_estimated_slew_sec",
)


def _pareto_objective_names(slew_aware_active: bool) -> tuple[str, ...]:
    """Return the objective names matching ``_pareto_objective_vector`` order."""
    return _PARETO_OBJECTIVE_NAMES_SLEW_AWARE if slew_aware_active else _PARETO_OBJECTIVE_NAMES_QUALITY


def _pareto_score_value(value: object, *, negate: bool = False) -> float:
    """Return a finite maximization-convention value or the worst-case sentinel."""
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return _PARETO_MISSING_VALUE
    if not np.isfinite(result):
        return _PARETO_MISSING_VALUE
    return -result if negate else result


def _pareto_objective_vector(
    *,
    quality_score,
    slew_selection_payload: Mapping[str, object] | None,
    slew_aware_active: bool,
) -> tuple[float, ...]:
    """Return one trial's clean objective vector for non-domination ranking.

    Every element uses the maximization convention (larger is better), with
    ``None``/non-finite metrics mapped to a worst-case sentinel.  The element
    order must stay in sync with ``_pareto_objective_names``.  Unlike the
    lexicographic selection tuple, this vector contains only the raw plan
    metrics -- no composite weights, jitter, or trial-index tie-breaks -- so
    dominance between trials reflects genuine metric trade-offs.
    """
    metrics = quality_score.metrics
    vector = [
        _pareto_score_value(metrics.spacing_violation_count, negate=True),
        _pareto_score_value(metrics.selected_count),
        _pareto_score_value(metrics.bin_coverage_ratio),
        _pareto_score_value(metrics.metric_range_coverage),
        _pareto_score_value(metrics.satellite_dominance_ratio, negate=True),
        _pareto_score_value(metrics.pass_dominance_ratio, negate=True),
    ]
    if slew_aware_active:
        payload = slew_selection_payload or {}
        vector.extend(
            (
                _pareto_score_value(payload.get("transition_violation_count"), negate=True),
                _pareto_score_value(payload.get("total_estimated_transition_sec"), negate=True),
                _pareto_score_value(payload.get("max_estimated_slew_sec"), negate=True),
            )
        )
    return tuple(vector)


def _pareto_non_dominated_mask(vectors: Sequence[tuple[float, ...]]) -> list[bool]:
    """Return which objective vectors are Pareto non-dominated.

    Vector ``j`` dominates vector ``i`` when ``j`` is at least as good on
    every objective and strictly better on at least one (maximization
    convention).  Straight O(n^2) pairwise comparison -- the multi-start trial
    pool is bounded at ``MAX_OPTIMIZATION_TRIALS`` (256), so this is
    negligible and needs no external optimization library.
    """
    array = np.asarray([tuple(vector) for vector in vectors], dtype=float)
    count = int(array.shape[0])
    mask = [True] * count
    for i in range(count):
        row = array[i]
        for j in range(count):
            if i == j:
                continue
            other = array[j]
            if bool(np.all(other >= row)) and bool(np.any(other > row)):
                mask[i] = False
                break
    return mask


def generate_multistart_stratified_sample_plan(
    visibility_df: pd.DataFrame,
    *,
    request: SamplingPlannerRequest,
    column_mapping=None,
    progress_callback: Callable[[str], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
) -> tuple[pd.DataFrame, SamplingPlannerDiagnostics]:
    """Generate a stratified plan using deterministic multi-start optimization.

    Task 31F prepares all seed-invariant candidate state once and reuses that
    prepared problem across all trial seeds.  Each trial performs only the
    seed-dependent candidate-depth reduction, weighted interval selection,
    optional repair, and scoring steps.
    """
    method = normalize_plan_method(request.plan_method)
    if method == PLAN_METHOD_MAX_ELEVATION:
        raise ValueError("Multi-start optimization is only valid for stratified sampling methods.")

    if not bool(request.optimization_enabled):
        _emit_progress(progress_callback, "Stratified sampler: optimization disabled; running one deterministic sample.")
        return generate_stratified_sample_plan(
            visibility_df,
            request=request,
            column_mapping=column_mapping,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )

    trial_count = validate_optimization_trials(request.optimization_trials)
    base_seed = int(request.random_seed)
    metric_logical = "solar_phase_angle" if method == PLAN_METHOD_STRATIFIED_SOLAR_PHASE else "elev"
    candidate_depth = validate_candidate_depth(request.candidate_depth)
    optimization_objective = request.active_optimization_objective
    slew_aware_active = optimization_objective == OPTIMIZATION_OBJECTIVE_SLEW_AWARE
    total_start = time.perf_counter()

    _emit_progress(
        progress_callback,
        (
            "Stratified sampler: running "
            f"{trial_count} optimization trial(s) from base seed {base_seed} "
            f"with candidate_depth={candidate_depth}, objective={optimization_objective}."
        ),
    )

    problem = _prepare_stratified_sampling_problem(
        visibility_df,
        request=request,
        column_mapping=column_mapping,
        progress_callback=progress_callback,
        cancel_callback=cancel_callback,
    )

    best_plan: pd.DataFrame | None = None
    best_diagnostics: SamplingPlannerDiagnostics | None = None
    best_score = None
    best_selection_score: tuple[object, ...] | None = None
    best_slew_selection_payload: dict[str, object] | None = None
    best_trial_index = 0
    best_trial_seed = base_seed
    trial_summaries: list[dict[str, object]] = []
    trial_signatures: list[tuple[object, ...]] = []
    trial_seeds: list[int] = []
    trial_quality_scores: list[object] = []
    trial_selection_scores: list[tuple[object, ...]] = []
    trial_slew_payloads: list[dict[str, object] | None] = []
    trial_objective_vectors: list[tuple[float, ...]] = []

    for trial_index in range(trial_count):
        _check_cancel(cancel_callback)
        trial_seed = base_seed + trial_index
        trial_request = replace(
            request,
            random_seed=trial_seed,
            optimization_enabled=False,
            optimization_trials=1,
            candidate_depth=candidate_depth,
        )
        trial_plan, trial_diagnostics, timings = _run_stratified_sampling_trial(
            problem,
            request=trial_request,
            build_full_diagnostics=False,
            run_repair_diagnostics=bool(trial_request.local_repair_enabled),
            cancel_callback=cancel_callback,
        )
        quality_score = compute_plan_quality(
            selected_plan=trial_plan,
            candidate_df=problem.candidates if problem.candidates is not None else pd.DataFrame(),
            spacing_min=float(request.spacing_min),
            metric_logical=metric_logical,
            sampling_diagnostics=trial_diagnostics,
            selected_row_records=trial_diagnostics.selected_row_ids,
            trial_index=trial_index,
        )
        active_score, slew_selection_payload = _active_trial_selection_score(
            trial_plan=trial_plan,
            quality_score=quality_score,
            request=request,
            trial_index=trial_index,
        )
        trial_seeds.append(trial_seed)
        trial_quality_scores.append(quality_score)
        trial_selection_scores.append(active_score)
        trial_slew_payloads.append(slew_selection_payload)
        trial_objective_vectors.append(
            _pareto_objective_vector(
                quality_score=quality_score,
                slew_selection_payload=slew_selection_payload,
                slew_aware_active=slew_aware_active,
            )
        )
        signature = _trial_signature(trial_plan, trial_diagnostics.selected_row_ids)
        trial_signatures.append(signature)
        trial_summary = _trial_summary(
            trial_index=trial_index,
            trial_seed=trial_seed,
            plan_df=trial_plan,
            diagnostics=trial_diagnostics,
            quality_score=quality_score,
            signature=signature,
            optimization_objective=optimization_objective,
            active_score=active_score,
            slew_selection_payload=slew_selection_payload,
        )
        trial_summaries.append(trial_summary)

        if best_selection_score is None or active_score > best_selection_score:
            best_plan = trial_plan
            best_diagnostics = trial_diagnostics
            best_score = quality_score
            best_selection_score = active_score
            best_slew_selection_payload = slew_selection_payload
            best_trial_index = trial_index
            best_trial_seed = trial_seed

        if _should_report_trial(trial_index, trial_count):
            _emit_progress(
                progress_callback,
                (
                    f"Stratified sampler: trial {trial_index + 1}/{trial_count} complete "
                    f"(seed={trial_seed}, reduced {problem.candidate_rows} -> "
                    f"{trial_diagnostics.reduced_candidate_rows}, selected={len(trial_plan)}, "
                    f"elapsed={timings.get('total_s', 0.0):.3f} s "
                    f"(reduce={timings.get('reduction_s', 0.0):.3f}, "
                    f"select={timings.get('selection_s', 0.0):.3f}, "
                    f"repair={timings.get('repair_s', 0.0):.3f}, "
                    f"diag={timings.get('diagnostics_s', 0.0):.3f}), "
                    f"current_best={best_trial_index + 1})."
                ),
            )

    if best_plan is None or best_diagnostics is None or best_score is None or best_selection_score is None:
        return generate_stratified_sample_plan(
            visibility_df,
            request=request,
            column_mapping=column_mapping,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )

    # Pareto non-domination winner selection.  The incremental loop tracking
    # above is the legacy lexicographic rule; its result is kept only for the
    # transparency report.  The actual winner is chosen from the Pareto front
    # of clean per-trial metric vectors: dominated trials (worse-or-equal on
    # every objective, strictly worse on at least one) can never win.  Within
    # the front, the existing selection score ranks the remaining defensible
    # trade-offs, tie-broken by lowest trial index for determinism.
    legacy_best_trial_index = int(best_trial_index)
    pareto_mask = _pareto_non_dominated_mask(trial_objective_vectors)
    pareto_front_indices = [index for index, flag in enumerate(pareto_mask) if flag]
    pareto_winner_index = max(
        pareto_front_indices,
        key=lambda index: (tuple(trial_selection_scores[index]), -index),
    )
    best_trial_index = int(pareto_winner_index)
    best_trial_seed = int(trial_seeds[pareto_winner_index])
    best_score = trial_quality_scores[pareto_winner_index]
    best_selection_score = trial_selection_scores[pareto_winner_index]
    best_slew_selection_payload = trial_slew_payloads[pareto_winner_index]
    for summary_index, summary in enumerate(trial_summaries):
        summary["pareto_non_dominated"] = bool(pareto_mask[summary_index])
        summary["pareto_objective_vector"] = list(trial_objective_vectors[summary_index])

    _check_cancel(cancel_callback)
    t_final = time.perf_counter()
    final_request = replace(
        request,
        random_seed=int(best_trial_seed),
        optimization_enabled=False,
        optimization_trials=1,
        candidate_depth=candidate_depth,
    )
    best_plan, best_diagnostics, final_timings = _run_stratified_sampling_trial(
        problem,
        request=final_request,
        build_full_diagnostics=True,
        run_repair_diagnostics=True,
        cancel_callback=cancel_callback,
    )
    final_diag_elapsed = time.perf_counter() - t_final

    total_elapsed = time.perf_counter() - total_start
    _emit_progress(
        progress_callback,
        (
            f"Stratified sampler: selected best trial {best_trial_index + 1}/{trial_count} "
            f"(seed={best_trial_seed}, rows={len(best_plan)}) in {total_elapsed:.3f} s total "
            f"including final diagnostics {final_diag_elapsed:.3f} s."
        ),
    )

    unique_signatures = {repr(signature) for signature in trial_signatures}
    multi_start_summary = {
        "optimization_enabled": True,
        "trial_count": int(trial_count),
        "base_seed": int(base_seed),
        "candidate_depth": int(candidate_depth),
        "best_trial_index": int(best_trial_index),
        "best_trial_seed": int(best_trial_seed),
        "optimization_objective": optimization_objective,
        "slew_aware_selection_active": bool(slew_aware_active),
        "selection_score_kind": "slew_aware" if slew_aware_active else "quality",
        "selection_strategy": "pareto_front",
        "pareto_objectives": list(_pareto_objective_names(slew_aware_active)),
        "pareto_front_size": int(len(pareto_front_indices)),
        "pareto_front_trial_indices": [int(index) for index in pareto_front_indices],
        "legacy_best_trial_index": int(legacy_best_trial_index),
        "pareto_changed_selection": bool(pareto_winner_index != legacy_best_trial_index),
        "best_score_tuple": list(_plain_quality_value(best_selection_score)),
        "best_quality_score_tuple": list(_plain_quality_value(best_score.lexicographic_score)),
        "best_slew_aware_selection_score": _plain_quality_value(best_slew_selection_payload or {}),
        "trial_summaries": trial_summaries,
        "all_trial_quality_summaries": trial_summaries,
        "unique_trial_signatures": int(len(unique_signatures)),
        "trial_signatures": [list(_plain_quality_value(signature)) for signature in trial_signatures],
        "requested_trials": int(request.optimization_trials),
        "max_trials": int(MAX_OPTIMIZATION_TRIALS),
        "prepared_candidate_rows": int(problem.candidate_rows),
        "prepared_pass_groups": int(problem.pass_groups),
        "prepared_sampling_groups": int(problem.group_count),
        "second_stage_optimization": "prepared_group_indices_and_deferred_final_diagnostics",
    }
    _check_cancel(cancel_callback)
    return best_plan, replace(best_diagnostics, multi_start_summary=multi_start_summary)

