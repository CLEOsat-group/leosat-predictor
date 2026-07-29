"""GUI-neutral Observation Planner workflow helpers.

This module contains reusable observation-planner use-case preparation that is
shared by concrete front ends.  It must remain independent of front-end frameworks and any
GUI package so the desktop GUI and the later web planner can call the same
planner preparation path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.observation_planner.diagnostics import refresh_diagnostics_for_current_plan
from src.observation_planner.planner import (
    AUTO_SEQUENCE_MODE,
    JSON_TIMES_MODE,
    build_auto_targets_from_visibility,
    should_use_loaded_targets_for_auto_mode,
)
from src.observation_planner.preferences import ObservationPlannerPreferences
from src.observation_planner.sampling import PLAN_METHOD_MAX_ELEVATION, metric_for_plan_method, normalize_plan_method


@dataclass(frozen=True)
class ObservationPlannerRunRequest:
    """Backend request for observation-plan generation.

    Parameters
    ----------
    use_json_times : bool
        Whether selector JSON target times should be used.
    tolerance_sec : int
        Matching tolerance in seconds for JSON-time mode.
    spacing_min : float
        Minimum spacing between generated observations in minutes.
    min_elevation : float
        Minimum accepted elevation in degrees.
    time_range_sec : int or float, optional
        Additional target-time matching window in seconds.
    plan_method : str, optional
        Planner method identifier.
    binning_mode : str, optional
        Sampling binning mode override.
    sample_bins : int, optional
        Sampling bin-count override.
    bin_width_deg : float, optional
        Fixed-width bin size override in degrees.
    preferences : ObservationPlannerPreferences
        Shared planner preferences.
    """

    use_json_times: bool
    tolerance_sec: int
    spacing_min: float
    min_elevation: float
    time_range_sec: int | float = 0
    plan_method: str = PLAN_METHOD_MAX_ELEVATION
    binning_mode: str | None = None
    sample_bins: int | None = None
    bin_width_deg: float | None = None
    preferences: ObservationPlannerPreferences | None = None


@dataclass(frozen=True)
class PreparedObservationPlannerRun:
    """Prepared planner-run payload for GUI or web callers.

    Parameters
    ----------
    visibility_df : pandas.DataFrame
        Visibility table supplied to the planner core.
    targets_df : pandas.DataFrame or None
        Target table supplied to the planner core.
    planner_kwargs : dict[str, Any]
        Keyword arguments for ``generate_observation_plan``.
    mode : str
        Resolved planner mode.
    normalized_plan_method : str
        Normalized planner method identifier.
    metric : str
        Metric implied by the planner method.
    messages : tuple[str, ...]
        Human-readable setup messages suitable for logs.
    """

    visibility_df: pd.DataFrame
    targets_df: pd.DataFrame | None
    planner_kwargs: dict[str, Any]
    mode: str
    normalized_plan_method: str
    metric: str
    messages: tuple[str, ...]


def prepare_observation_planner_run(
    visibility_df: pd.DataFrame,
    targets_df: pd.DataFrame | None,
    request: ObservationPlannerRunRequest,
) -> PreparedObservationPlannerRun:
    """Prepare an observation-planner run without depending on a UI toolkit.

    Parameters
    ----------
    visibility_df : pandas.DataFrame
        Prepared visibility table.
    targets_df : pandas.DataFrame or None
        Optional loaded selector target table.
    request : ObservationPlannerRunRequest
        Front-end-neutral request values.

    Returns
    -------
    PreparedObservationPlannerRun
        Prepared targets, mode, planner kwargs, and log messages.

    Raises
    ------
    ValueError
        If required visibility data, settings, or JSON targets are missing.
    """
    if visibility_df is None or visibility_df.empty:
        raise ValueError("No visibility data loaded. Cannot generate plan.")
    if request.preferences is None:
        raise ValueError("Observation planner preferences are required.")

    settings = request.preferences
    messages: list[str] = []

    if request.use_json_times:
        if targets_df is None or targets_df.empty:
            raise ValueError("JSON times requested, but no JSON loaded. Aborting.")
        mode = JSON_TIMES_MODE
        prepared_targets = targets_df
    else:
        mode = AUTO_SEQUENCE_MODE
        if should_use_loaded_targets_for_auto_mode(targets_df):
            prepared_targets = targets_df
            messages.append("Automatic mode: using loaded JSON as satellite list.")
        else:
            prepared_targets = build_auto_targets_from_visibility(
                visibility_df,
                column_mapping=settings.column_mapping,
            )
            if targets_df is None or targets_df.empty:
                messages.append("Automatic mode: no JSON loaded — using fallback from visibility data.")
            else:
                messages.append("Automatic mode: loaded JSON contains times — using visibility data fallback.")

    normalized_plan_method = normalize_plan_method(request.plan_method)
    derived_metric = metric_for_plan_method(normalized_plan_method)

    planner_kwargs: dict[str, Any] = {
        "mode": mode,
        "tolerance_sec": request.tolerance_sec,
        "spacing_min": request.spacing_min,
        "min_elevation": request.min_elevation,
        "time_range_sec": request.time_range_sec,
        "column_mapping": settings.column_mapping,
        "plan_method": request.plan_method,
        "binning_mode": request.binning_mode or settings.default_binning_mode,
        "sample_bins": request.sample_bins or settings.default_sample_bins,
        "bin_width_deg": request.bin_width_deg if request.bin_width_deg is not None else settings.default_bin_width_deg,
        "custom_elevation_bin_edges": settings.custom_elevation_bin_edges,
        "custom_solar_phase_bin_edges": settings.custom_solar_phase_bin_edges,
        "random_seed": settings.random_seed,
        "optimization_enabled": settings.optimization_enabled,
        "optimization_trials": settings.optimization_trials,
        "candidate_depth": settings.candidate_depth,
        "optimization_objective": settings.optimization_objective,
        "local_repair_enabled": settings.local_repair_enabled,
        "local_repair_max_additions": settings.local_repair_max_additions,
        "local_repair_candidate_limit": settings.local_repair_candidate_limit,
        "local_repair_attempt_limit": settings.local_repair_attempt_limit,
        "slew_diagnostics_enabled": settings.slew_diagnostics_enabled,
        "slew_model": settings.slew_model(),
        "slew_transition_sample_limit": settings.slew_transition_sample_limit,
        "transition_constraint_mode": settings.transition_constraint_mode,
        "transition_safety_margin_sec": settings.transition_safety_margin_sec,
    }

    return PreparedObservationPlannerRun(
        visibility_df=visibility_df,
        targets_df=prepared_targets,
        planner_kwargs=planner_kwargs,
        mode=mode,
        normalized_plan_method=normalized_plan_method,
        metric=derived_metric,
        messages=tuple(messages),
    )


def refresh_observation_plan_diagnostics(
    last_diagnostics: object | None,
    plan_df: pd.DataFrame,
    *,
    spacing_min: float,
    source_visibility: pd.DataFrame | None,
    preferences: ObservationPlannerPreferences,
) -> object | None:
    """Refresh diagnostics for a manually edited or regenerated plan.

    Parameters
    ----------
    last_diagnostics : object or None
        Existing diagnostics object from the last planner run.
    plan_df : pandas.DataFrame
        Current visible observation plan.
    spacing_min : float
        Required minimum spacing in minutes.
    source_visibility : pandas.DataFrame or None
        Source visibility table used for diagnostic comparison.
    preferences : ObservationPlannerPreferences
        Shared planner preferences.

    Returns
    -------
    object or None
        Updated diagnostics object, or ``None`` if diagnostics cannot be
        refreshed.
    """
    return refresh_diagnostics_for_current_plan(
        last_diagnostics,
        plan_df,
        spacing_min=spacing_min,
        source_visibility=source_visibility,
        slew_model=preferences.slew_model(),
        slew_diagnostics_enabled=preferences.slew_diagnostics_enabled,
        slew_transition_sample_limit=preferences.slew_transition_sample_limit,
        transition_constraint_mode=preferences.transition_constraint_mode,
        transition_safety_margin_sec=preferences.transition_safety_margin_sec,
    )
