"""Plan-quality metrics for Observation Planner generated schedules.

This module is intentionally GUI- and web-neutral.  It computes deterministic,
JSON-serializable quality metrics for already-generated observation plans.  It
must not generate, optimize, or alter plan rows; Task 31A only scores the plan
that the existing planner produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .schema import resolve_column


@dataclass(frozen=True)
class PlanQualityMetrics:
    """Auditable scalar metrics for one observation plan.

    Parameters
    ----------
    selected_count : int
        Number of selected observations in the final plan.
    unique_satellite_count : int
        Number of unique satellites represented in the plan.
    unique_pass_count : int
        Number of unique passes represented when pass identifiers are known.
    achieved_bin_count : int
        Number of metric bins represented by selected observations.
    actual_bin_count : int
        Number of bins available/considered by the planner.
    bin_coverage_ratio : float or None
        ``achieved_bin_count / actual_bin_count`` when bins are applicable.
    bin_balance_entropy : float or None
        Normalized entropy of selected bin counts.  ``1`` means balanced counts
        across represented bins; ``0`` means collapsed to one bin.
    bin_balance_score : float or None
        ``1 - coefficient_of_variation`` of selected bin counts, clipped to
        ``[0, 1]``.  Useful as a simple imbalance score.
    metric_range_coverage : float or None
        Ratio between selected metric range and available candidate metric
        range.
    satellite_dominance_ratio : float or None
        Maximum selected count for one satellite divided by total selections.
    pass_dominance_ratio : float or None
        Maximum selected count for one pass divided by total selections.
    min_spacing_min, median_spacing_min, max_spacing_min : float or None
        Chronological spacing statistics in minutes.
    spacing_margin_min : float or None
        ``min_spacing_min - requested_spacing_min``.
    spacing_violation_count : int
        Number of adjacent selected observations closer than required spacing.
    selected_global_indices, selected_base_indices, selected_local_indices : tuple[int, ...]
        Source-row identity metadata, when available.
    """

    selected_count: int
    unique_satellite_count: int
    unique_pass_count: int
    achieved_bin_count: int
    actual_bin_count: int
    bin_coverage_ratio: float | None
    bin_balance_entropy: float | None
    bin_balance_score: float | None
    metric_range_coverage: float | None
    satellite_dominance_ratio: float | None
    pass_dominance_ratio: float | None
    min_spacing_min: float | None
    median_spacing_min: float | None
    max_spacing_min: float | None
    spacing_margin_min: float | None
    spacing_violation_count: int
    selected_global_indices: tuple[int, ...]
    selected_base_indices: tuple[int, ...]
    selected_local_indices: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable quality metrics."""
        return {
            "selected_count": self.selected_count,
            "unique_satellite_count": self.unique_satellite_count,
            "unique_pass_count": self.unique_pass_count,
            "achieved_bin_count": self.achieved_bin_count,
            "actual_bin_count": self.actual_bin_count,
            "bin_coverage_ratio": self.bin_coverage_ratio,
            "bin_balance_entropy": self.bin_balance_entropy,
            "bin_balance_score": self.bin_balance_score,
            "metric_range_coverage": self.metric_range_coverage,
            "satellite_dominance_ratio": self.satellite_dominance_ratio,
            "pass_dominance_ratio": self.pass_dominance_ratio,
            "min_spacing_min": self.min_spacing_min,
            "median_spacing_min": self.median_spacing_min,
            "max_spacing_min": self.max_spacing_min,
            "spacing_margin_min": self.spacing_margin_min,
            "spacing_violation_count": self.spacing_violation_count,
            "selected_global_indices": list(self.selected_global_indices),
            "selected_base_indices": list(self.selected_base_indices),
            "selected_local_indices": list(self.selected_local_indices),
        }


@dataclass(frozen=True)
class PlanQualityScore:
    """Lexicographic quality score for future plan comparison.

    Task 31A records this score for diagnostics only.  It must not be used to
    choose a different plan until a later multi-start optimization slice.
    """

    metrics: PlanQualityMetrics
    lexicographic_score: tuple[Any, ...]
    compact_summary: str

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-serializable score data."""
        return {
            "metrics": self.metrics.to_dict(),
            "lexicographic_score": list(self.lexicographic_score),
            "compact_summary": self.compact_summary,
        }


def _resolve_optional(df: pd.DataFrame | None, logical: str) -> str | None:
    """Resolve a logical observation-planner column when present."""
    if df is None or df.empty:
        return None
    if logical in df.columns:
        return logical
    try:
        return resolve_column(df, logical, required=False)
    except Exception:
        return None


def _metric_logical_name(metric_name: object) -> str:
    """Return the canonical logical metric column name."""
    name = str(metric_name or "elev").strip().lower()
    if name in {"solar_phase", "solar_phase_angle", "phase", "phase_angle"}:
        return "solar_phase_angle"
    if name in {"elevation", "sat_elev", "satellite_elevation"}:
        return "elev"
    return name


def _finite_numeric(series: pd.Series | None) -> pd.Series:
    """Return finite numeric values from a pandas Series."""
    if series is None:
        return pd.Series(dtype="float64")
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric[np.isfinite(numeric)].astype(float)


def _safe_int_tuple(values: Sequence[Any]) -> tuple[int, ...]:
    """Return stable integer tuple from row-identity values."""
    result: list[int] = []
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        try:
            result.append(int(float(value)))
        except Exception:
            continue
    return tuple(result)


def _indices_from_records(records: Sequence[Mapping[str, Any]], key: str) -> tuple[int, ...]:
    """Return index tuple from selected-row diagnostic records."""
    return _safe_int_tuple([record.get(key) for record in records])


def _spacing_minutes(plan_df: pd.DataFrame | None, date_col: str | None) -> list[float]:
    """Return sorted adjacent spacing deltas in minutes."""
    if plan_df is None or plan_df.empty or not date_col or date_col not in plan_df.columns:
        return []
    timestamps = pd.to_datetime(plan_df[date_col], errors="coerce", utc=True).dropna().sort_values()
    if len(timestamps) < 2:
        return []
    deltas = timestamps.diff().dropna().dt.total_seconds() / 60.0
    return [float(value) for value in deltas if np.isfinite(value)]


def _normalized_entropy(counts: Sequence[int]) -> float | None:
    """Return normalized Shannon entropy for positive counts."""
    positive = np.asarray([count for count in counts if count > 0], dtype="float64")
    if positive.size < 2:
        return None
    probabilities = positive / positive.sum()
    entropy = -float(np.sum(probabilities * np.log(probabilities)))
    denominator = float(np.log(positive.size))
    if denominator <= 0.0:
        return None
    return float(entropy / denominator)


def _balance_score(counts: Sequence[int]) -> float | None:
    """Return a simple clipped balance score from selected bin counts."""
    positive = np.asarray([count for count in counts if count > 0], dtype="float64")
    if positive.size < 2:
        return None
    mean = float(positive.mean())
    if mean <= 0.0:
        return None
    coefficient_of_variation = float(positive.std(ddof=0) / mean)
    return float(max(0.0, min(1.0, 1.0 - coefficient_of_variation)))


def _counts_from_sampling_diagnostics(sampling_diagnostics: Any | None) -> list[int]:
    """Return selected bin counts from sampling diagnostics, when available."""
    if sampling_diagnostics is None:
        return []
    counts: list[int] = []
    for item in tuple(getattr(sampling_diagnostics, "bin_diagnostics", ()) or ()):  # dataclass or mapping
        if isinstance(item, Mapping):
            value = item.get("selected_count")
        else:
            value = getattr(item, "selected_count", None)
        try:
            counts.append(int(value))
        except Exception:
            counts.append(0)
    return counts


def _metric_range_coverage(
    selected_plan: pd.DataFrame | None,
    candidate_df: pd.DataFrame | None,
    metric_logical: str,
) -> float | None:
    """Return selected/candidate metric range coverage."""
    candidate_col = _resolve_optional(candidate_df, metric_logical)
    selected_col = _resolve_optional(selected_plan, metric_logical)
    if candidate_col is None or selected_col is None:
        return None
    candidate_values = _finite_numeric(candidate_df[candidate_col])
    selected_values = _finite_numeric(selected_plan[selected_col])
    if candidate_values.empty or selected_values.empty:
        return None
    candidate_range = float(candidate_values.max() - candidate_values.min())
    if candidate_range <= 0.0:
        return None
    selected_range = float(selected_values.max() - selected_values.min())
    return float(max(0.0, min(1.0, selected_range / candidate_range)))


def compute_plan_quality(
    *,
    selected_plan: pd.DataFrame,
    candidate_df: pd.DataFrame | None,
    spacing_min: float,
    metric_logical: str = "elev",
    sampling_diagnostics: Any | None = None,
    selected_row_records: Sequence[Mapping[str, Any]] = (),
    trial_index: int = 0,
) -> PlanQualityScore:
    """Compute backend plan-quality metrics without altering plan rows.

    Parameters
    ----------
    selected_plan : pandas.DataFrame
        Final observation plan produced by the planner.
    candidate_df : pandas.DataFrame or None
        Candidate population used by the planner, when available.
    spacing_min : float
        Required minimum spacing in minutes.
    metric_logical : str, optional
        Logical metric used for distribution/range diagnostics.
    sampling_diagnostics : object, optional
        Stratified sampling diagnostics.  Used only for bin/pass metadata.
    selected_row_records : sequence of mappings, optional
        Existing selected-row reproducibility records.
    trial_index : int, optional
        Deterministic tiebreaker placeholder for future multi-start scoring.

    Returns
    -------
    PlanQualityScore
        Quality metrics, lexicographic score, and compact summary.
    """
    # Task 31G: avoid copying constellation-scale candidate tables during each
    # multi-start trial.  This function is read-only with respect to both
    # inputs, so references are sufficient and substantially cheaper.
    plan = selected_plan if selected_plan is not None else pd.DataFrame()
    candidates = candidate_df if candidate_df is not None else pd.DataFrame()
    metric_logical = _metric_logical_name(metric_logical)

    selected_count = int(len(plan))
    satellite_col = _resolve_optional(plan, "satellite")
    unique_satellite_count = int(plan[satellite_col].astype(str).nunique()) if satellite_col else 0

    pass_ids: list[Any] = []
    if "pass_id" in plan.columns:
        pass_ids = plan["pass_id"].dropna().tolist()
    elif selected_row_records:
        pass_ids = [record.get("pass_id") for record in selected_row_records if record.get("pass_id") is not None]
    unique_pass_count = int(pd.Series(pass_ids).nunique()) if pass_ids else 0

    bin_counts = _counts_from_sampling_diagnostics(sampling_diagnostics)
    actual_bin_count = int(getattr(sampling_diagnostics, "actual_bins", 0) or len(bin_counts) or 0)
    achieved_bin_count = int(getattr(sampling_diagnostics, "achieved_bins", 0) or sum(1 for count in bin_counts if count > 0))
    bin_coverage_ratio = (float(achieved_bin_count) / float(actual_bin_count)) if actual_bin_count > 0 else None
    bin_balance_entropy = _normalized_entropy(bin_counts)
    bin_balance_score = _balance_score(bin_counts)

    metric_range_coverage = _metric_range_coverage(plan, candidates, metric_logical)

    if selected_count > 0 and satellite_col:
        satellite_counts = plan[satellite_col].astype(str).value_counts()
        satellite_dominance_ratio = float(satellite_counts.max() / selected_count)
    else:
        satellite_dominance_ratio = None

    if selected_count > 0 and pass_ids:
        pass_counts = pd.Series(pass_ids).value_counts()
        pass_dominance_ratio = float(pass_counts.max() / selected_count)
    else:
        pass_dominance_ratio = None

    date_col = "datetime" if "datetime" in plan.columns else _resolve_optional(plan, "date_ut")
    deltas = _spacing_minutes(plan, date_col)
    if deltas:
        min_spacing = float(min(deltas))
        median_spacing = float(pd.Series(deltas).median())
        max_spacing = float(max(deltas))
        spacing_violation_count = int(sum(delta < float(spacing_min) for delta in deltas))
        spacing_margin = float(min_spacing - float(spacing_min))
    else:
        min_spacing = median_spacing = max_spacing = spacing_margin = None
        spacing_violation_count = 0

    selected_global_indices = _safe_int_tuple(plan["global_index"].tolist()) if "global_index" in plan.columns else _indices_from_records(selected_row_records, "global_index")
    selected_base_indices = _safe_int_tuple(plan["base_index"].tolist()) if "base_index" in plan.columns else _indices_from_records(selected_row_records, "base_index")
    selected_local_indices = _safe_int_tuple(plan["local_index"].tolist()) if "local_index" in plan.columns else _indices_from_records(selected_row_records, "local_index")

    metrics = PlanQualityMetrics(
        selected_count=selected_count,
        unique_satellite_count=unique_satellite_count,
        unique_pass_count=unique_pass_count,
        achieved_bin_count=achieved_bin_count,
        actual_bin_count=actual_bin_count,
        bin_coverage_ratio=bin_coverage_ratio,
        bin_balance_entropy=bin_balance_entropy,
        bin_balance_score=bin_balance_score,
        metric_range_coverage=metric_range_coverage,
        satellite_dominance_ratio=satellite_dominance_ratio,
        pass_dominance_ratio=pass_dominance_ratio,
        min_spacing_min=min_spacing,
        median_spacing_min=median_spacing,
        max_spacing_min=max_spacing,
        spacing_margin_min=spacing_margin,
        spacing_violation_count=spacing_violation_count,
        selected_global_indices=selected_global_indices,
        selected_base_indices=selected_base_indices,
        selected_local_indices=selected_local_indices,
    )

    lexicographic_score = (
        1 if spacing_violation_count == 0 else 0,
        selected_count,
        unique_satellite_count,
        achieved_bin_count,
        _score_value(bin_balance_entropy),
        _score_value(metric_range_coverage),
        -_score_value(satellite_dominance_ratio),
        -_score_value(pass_dominance_ratio),
        _score_value(spacing_margin),
        -int(trial_index),
    )
    compact = (
        "Quality: "
        f"selected={selected_count}, unique_sats={unique_satellite_count}, "
        f"bins={achieved_bin_count}/{actual_bin_count}, "
        f"bin_entropy={_format_optional(bin_balance_entropy)}, "
        f"metric_range={_format_optional(metric_range_coverage)}, "
        f"sat_dominance={_format_optional(satellite_dominance_ratio)}, "
        f"spacing_margin={_format_optional(spacing_margin)} min, "
        f"spacing_violations={spacing_violation_count}."
    )
    return PlanQualityScore(metrics=metrics, lexicographic_score=lexicographic_score, compact_summary=compact)


def _score_value(value: float | None) -> float:
    """Return finite value for lexicographic-score construction."""
    if value is None or not np.isfinite(value):
        return float("-inf")
    return float(value)


def _format_optional(value: float | None) -> str:
    """Return compact text for an optional numeric quality metric."""
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"{value:.3g}"
