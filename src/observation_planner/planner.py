"""Observation-plan generation logic shared by application front ends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace as dataclass_replace

import pandas as pd

from .diagnostics import PlanGenerationDiagnostics, build_plan_generation_diagnostics
from .impact_diagnostics import build_optimization_impact_summary, unavailable_optimization_impact_summary
from .exceptions import ObservationPlanGenerationCancelled
from .normalize import clean_satellite_name
from .schema import mapping_from_table, resolve_column
from .slew_diagnostics import DEFAULT_TRANSITION_SAMPLE_LIMIT, SlewModel
from .transition_constraints import (
    DEFAULT_TRANSITION_CONSTRAINT_MODE,
    DEFAULT_TRANSITION_SAFETY_MARGIN_SEC,
    TRANSITION_CONSTRAINT_PHYSICAL,
    apply_physical_transition_filter,
    apply_time_spacing_filter,
    normalize_transition_constraint_mode,
    validate_transition_safety_margin_sec,
)
from .sampling import (
    BINNING_EQUAL_WIDTH,
    DEFAULT_BIN_WIDTH_DEG,
    DEFAULT_RANDOM_SEED,
    DEFAULT_OPTIMIZATION_TRIALS,
    DEFAULT_SAMPLE_BINS,
    DEFAULT_CANDIDATE_DEPTH,
    OPTIMIZATION_OBJECTIVE_QUALITY,
    DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT,
    DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT,
    DEFAULT_LOCAL_REPAIR_ENABLED,
    DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS,
    PLAN_METHOD_MAX_ELEVATION,
    PLAN_METHOD_STRATIFIED_SOLAR_PHASE,
    SamplingPlannerRequest,
    generate_multistart_stratified_sample_plan,
    normalize_plan_method,
)


JSON_TIMES_MODE = "json_times"
AUTO_SEQUENCE_MODE = "auto_sequence"


def _emit_progress(progress_callback: Callable[[str], None] | None, message: str) -> None:
    """Emit a planner progress message when a callback is available."""
    if progress_callback is None:
        return
    try:
        progress_callback(message)
    except Exception:
        # Progress reporting must never affect deterministic planning results.
        return


def _check_cancel(cancel_callback: Callable[[], bool] | None) -> None:
    """Raise when cooperative cancellation has been requested."""
    if cancel_callback is not None and cancel_callback():
        raise ObservationPlanGenerationCancelled("Observation plan generation canceled; previous plan kept.")


def build_auto_targets_from_visibility(visibility_df: pd.DataFrame, column_mapping=None) -> pd.DataFrame:
    """Build automatic-mode target rows from visibility data.

    Parameters
    ----------
    visibility_df : pandas.DataFrame
        Visibility table using supported satellite-column aliases.

    Returns
    -------
    pandas.DataFrame
        Target table with one row per cleaned satellite name and null
        ``datetime`` values.
    """
    effective_mapping = mapping_from_table(visibility_df, column_mapping)
    satellite_col = resolve_column(visibility_df, "satellite", column_mapping=effective_mapping)
    satellites = (
        visibility_df[satellite_col]
        .astype(str)
        .map(clean_satellite_name)
        .dropna()
        .unique()
    )
    return pd.DataFrame({"satellite": satellites, "datetime": [None] * len(satellites)})


def should_use_loaded_targets_for_auto_mode(targets_df: pd.DataFrame | None) -> bool:
    """Return whether loaded targets should constrain automatic planning.

    Parameters
    ----------
    targets_df : pandas.DataFrame or None
        Loaded target table.

    Returns
    -------
    bool
        `True` when targets exist and contain no usable date/time values,
        matching the selector's automatic-mode fallback behavior.
    """
    if targets_df is None or targets_df.empty:
        return False

    for column in targets_df.columns:
        column_lower = str(column).lower()
        if "date" in column_lower or "time" in column_lower or column_lower == "datetime":
            if targets_df[column].notnull().any():
                return False
    return True


def _apply_spacing_filter(plan_df: pd.DataFrame, spacing_min: int | float) -> pd.DataFrame:
    """Apply the donor-compatible chronological minimum-spacing filter."""
    return apply_time_spacing_filter(plan_df, spacing_min=float(spacing_min))


def _apply_transition_constraint_filter(
    plan_df: pd.DataFrame,
    *,
    spacing_min: int | float,
    transition_constraint_mode: str,
    slew_model: SlewModel | None,
    transition_safety_margin_sec: int | float,
    column_mapping=None,
) -> pd.DataFrame:
    """Apply the configured final spacing/transition feasibility filter."""
    mode = normalize_transition_constraint_mode(transition_constraint_mode)
    if mode != TRANSITION_CONSTRAINT_PHYSICAL:
        result = _apply_spacing_filter(plan_df, spacing_min)
        return result
    result, _summary, _records = apply_physical_transition_filter(
        plan_df,
        model=slew_model,
        user_spacing_min=float(spacing_min),
        safety_margin_sec=validate_transition_safety_margin_sec(transition_safety_margin_sec),
        transition_constraint_mode=mode,
        column_mapping=column_mapping,
    )
    return result

def _build_json_time_candidates(
    df_vis: pd.DataFrame,
    df_targets: pd.DataFrame,
    *,
    tolerance_sec: int | float,
    time_range_sec: int | float,
    cancel_callback: Callable[[], bool] | None = None,
) -> pd.DataFrame:
    """Return all visibility rows matching JSON target-time windows."""
    exact = pd.merge(df_targets, df_vis, on=["satellite", "datetime"], how="inner")
    effective_tolerance_sec = max(float(tolerance_sec), float(time_range_sec) / 2.0)
    if effective_tolerance_sec <= 0:
        return exact.copy()

    tolerance = pd.Timedelta(seconds=effective_tolerance_sec)
    matched_rows = []
    for index, (_, target_row) in enumerate(df_targets.dropna(subset=["datetime"]).iterrows()):
        if index % 128 == 0:
            _check_cancel(cancel_callback)
        satellite = target_row["satellite"]
        timestamp = target_row["datetime"]
        visibility_matches = df_vis[
            (df_vis["satellite"] == satellite)
            & (df_vis["datetime"].between(timestamp - tolerance, timestamp + tolerance))
        ]
        if not visibility_matches.empty:
            matched_rows.append(visibility_matches.copy())
    if not matched_rows:
        return exact.copy()
    candidates = pd.concat(matched_rows, ignore_index=True)
    # Avoid duplicate candidates when target windows overlap or when exact rows
    # are also covered by the tolerance/range window.  Use stable key columns to
    # avoid object-column hashing issues in arbitrary donor CSVs.
    if "global_index" in candidates.columns:
        return candidates.drop_duplicates(subset=["global_index"]).reset_index(drop=True)
    return candidates.drop_duplicates(subset=["satellite", "datetime"]).reset_index(drop=True)


def _build_json_time_best_matches(
    df_vis: pd.DataFrame,
    df_targets: pd.DataFrame,
    *,
    tolerance_sec: int | float,
    time_range_sec: int | float,
    cancel_callback: Callable[[], bool] | None = None,
) -> pd.DataFrame:
    """Return one best visibility row per JSON target time.

    Exact timestamp matches are preferred target-by-target. Near matching is
    used only for targets that do not have an exact row, so one exact target
    cannot suppress tolerance/range matching for later targets.
    """
    effective_tolerance_sec = max(float(tolerance_sec), float(time_range_sec) / 2.0)
    tolerance = pd.Timedelta(seconds=effective_tolerance_sec)
    matched_rows = []

    for index, (_, target_row) in enumerate(df_targets.dropna(subset=["datetime"]).iterrows()):
        if index % 128 == 0:
            _check_cancel(cancel_callback)
        satellite = target_row["satellite"]
        timestamp = target_row["datetime"]

        exact_matches = df_vis[(df_vis["satellite"] == satellite) & (df_vis["datetime"] == timestamp)]
        if not exact_matches.empty:
            matched_rows.append(exact_matches.copy())
            continue

        if effective_tolerance_sec <= 0:
            continue

        visibility_matches = df_vis[
            (df_vis["satellite"] == satellite)
            & (df_vis["datetime"].between(timestamp - tolerance, timestamp + tolerance))
        ]
        if visibility_matches.empty:
            continue
        visibility_matches = visibility_matches.assign(
            dt_diff=(visibility_matches["datetime"] - timestamp).abs()
        )
        best = visibility_matches.loc[visibility_matches["dt_diff"].idxmin()]
        matched_rows.append(best.to_frame().T)

    return pd.concat(matched_rows, ignore_index=True) if matched_rows else pd.DataFrame()


def _build_auto_candidate_pool(df_vis: pd.DataFrame, df_targets: pd.DataFrame) -> pd.DataFrame:
    """Return visibility rows for the automatic target satellite set."""
    satellites = set(df_targets["satellite"].dropna().astype(str))
    if not satellites:
        return df_vis.iloc[0:0].copy()
    return df_vis[df_vis["satellite"].isin(satellites)].copy().reset_index(drop=True)


def generate_observation_plan(
    visibility_df: pd.DataFrame,
    targets_df: pd.DataFrame | None = None,
    *,
    mode: str = JSON_TIMES_MODE,
    tolerance_sec: int | float = 1,
    spacing_min: int | float = 3,
    min_elevation: int | float | None = None,
    time_range_sec: int | float = 0,
    column_mapping=None,
    plan_method: str = PLAN_METHOD_MAX_ELEVATION,
    binning_mode: str = BINNING_EQUAL_WIDTH,
    sample_bins: int = DEFAULT_SAMPLE_BINS,
    bin_width_deg: float = DEFAULT_BIN_WIDTH_DEG,
    custom_elevation_bin_edges=(),
    custom_solar_phase_bin_edges=(),
    random_seed: int = DEFAULT_RANDOM_SEED,
    optimization_enabled: bool = True,
    optimization_trials: int = DEFAULT_OPTIMIZATION_TRIALS,
    candidate_depth: int = DEFAULT_CANDIDATE_DEPTH,
    optimization_objective: str = OPTIMIZATION_OBJECTIVE_QUALITY,
    local_repair_enabled: bool = DEFAULT_LOCAL_REPAIR_ENABLED,
    local_repair_max_additions: int = DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS,
    local_repair_candidate_limit: int = DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT,
    local_repair_attempt_limit: int = DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT,
    slew_diagnostics_enabled: bool = True,
    slew_model: SlewModel | None = None,
    slew_transition_sample_limit: int = DEFAULT_TRANSITION_SAMPLE_LIMIT,
    transition_constraint_mode: str = DEFAULT_TRANSITION_CONSTRAINT_MODE,
    transition_safety_margin_sec: float = DEFAULT_TRANSITION_SAFETY_MARGIN_SEC,
    impact_comparison_enabled: bool = True,
    return_diagnostics: bool = False,
    progress_callback: Callable[[str], None] | None = None,
    cancel_callback: Callable[[], bool] | None = None,
) -> pd.DataFrame | tuple[pd.DataFrame, PlanGenerationDiagnostics | None]:
    """Generate an observation plan from visibility data.

    Parameters
    ----------
    visibility_df : pandas.DataFrame
        Visibility prediction table using supported selector-style or
        predictor-style column aliases.
    targets_df : pandas.DataFrame or None, optional
        Target table with ``satellite`` and ``datetime`` columns. If omitted in
        automatic mode, one target is generated for each visible satellite.
    mode : {"json_times", "auto_sequence"}, optional
        Planning mode. ``"json_times"`` matches target timestamps to visibility
        timestamps. ``"auto_sequence"`` selects the maximum-elevation row per
        target satellite for the legacy donor-compatible method.
    tolerance_sec : int or float, optional
        Time tolerance in seconds used for per-target JSON-time matching. For
        sampling it defines the JSON target candidate window together with
        ``time_range_sec``.
    spacing_min : int or float, optional
        Minimum spacing in minutes between retained plan rows. This remains a
        hard constraint for all methods.
    min_elevation : int, float, or None, optional
        Minimum satellite elevation. If provided, the visibility table is
        filtered before planning.
    time_range_sec : int or float, optional
        Donor time-range control in seconds. For JSON-time mode this expands
        the target-time matching window symmetrically. ``0`` preserves the
        selector/default no-expansion behavior.
    column_mapping : mapping, optional
        Donor-compatible column mapping to use for visibility resolution.
    plan_method : str, optional
        ``max_elevation`` preserves the existing donor behavior. Stratified
        sampling methods add distribution-aware plan generation beside the
        donor method.
    binning_mode : str, optional
        Stratified binning mode. ``fixed_width`` uses physical degree-grid bins.
    sample_bins : int, optional
        Requested bin count for count-based stratified modes.
    bin_width_deg : float, optional
        Fixed physical bin width in degrees, used only by ``fixed_width``.
    optimization_enabled : bool, optional
        Enable deterministic multi-start optimization for stratified methods.
        Ignored for the legacy Max Elevation method.
    optimization_trials : int, optional
        Bounded number of deterministic trial seeds for stratified methods.
    candidate_depth : int, optional
        Bounded number of representatives retained per satellite/pass/bin group
        before global spacing selection for stratified methods.
    local_repair_enabled : bool, optional
        Enable optional 31D-B compatible additive local repair for stratified
        methods.  Disabled by default to preserve established output.
    local_repair_max_additions : int, optional
        Bounded maximum number of repair rows that may be added when repair is
        explicitly enabled.
    local_repair_candidate_limit : int, optional
        Maximum reduced-pool candidates scanned by local repair.
    local_repair_attempt_limit : int, optional
        Maximum ranked repair insertion attempts.
    slew_diagnostics_enabled : bool, optional
        Diagnostics-only switch for Task 35A/35B slew/path reporting.  This
        must not affect candidate selection or spacing behavior.
    slew_model : SlewModel or None, optional
        Diagnostics-only telescope motion model used after selection completes.
    slew_transition_sample_limit : int, optional
        Maximum number of per-transition slew diagnostics retained.
    transition_constraint_mode : str, optional
        Final spacing/transition feasibility mode. ``"time_spacing"`` preserves
        established behavior; ``"physical_transition"`` explicitly enables the
        Task 35E model-aware feasibility filter.
    transition_safety_margin_sec : float, optional
        Additional conservative margin added to physical transition requirements
        when physical-transition mode is active.
    return_diagnostics : bool, optional
        If `True`, return ``(plan_df, diagnostics)``. Diagnostics are non-None
        only for stratified sampling methods.
    progress_callback : callable, optional
        Optional UI-neutral callback receiving coarse progress messages. The
        callback is advisory only and must not influence planning results.
    cancel_callback : callable, optional
        Optional UI-neutral callback polled at safe checkpoints.  When it
        returns `True`, generation raises ``ObservationPlanGenerationCancelled``
        before publishing partial results.

    Returns
    -------
    pandas.DataFrame or tuple
        Planned observation rows, optionally with sampling diagnostics.
    """
    diagnostics: PlanGenerationDiagnostics | None = None
    _check_cancel(cancel_callback)
    _emit_progress(progress_callback, "Planner core: validating visibility input.")
    if visibility_df is None or visibility_df.empty:
        empty = pd.DataFrame(columns=[])
        return (empty, diagnostics) if return_diagnostics else empty

    effective_mapping = mapping_from_table(visibility_df, column_mapping)
    df_input = visibility_df.copy()
    df_input.attrs.update(getattr(visibility_df, "attrs", {}))
    if min_elevation is not None:
        elev_col = resolve_column(df_input, "elev", column_mapping=effective_mapping)
        before_filter_rows = len(df_input)
        df_input = df_input[df_input[elev_col] >= min_elevation].copy()
        _emit_progress(
            progress_callback,
            f"Planner core: minimum-elevation filter kept {len(df_input)}/{before_filter_rows} row(s).",
        )
        if df_input.empty:
            empty = pd.DataFrame(columns=visibility_df.columns)
            return (empty, diagnostics) if return_diagnostics else empty

    _check_cancel(cancel_callback)
    df_vis = df_input.copy()
    date_col = resolve_column(df_vis, "date_ut", column_mapping=effective_mapping)
    satellite_col = resolve_column(df_vis, "satellite", column_mapping=effective_mapping)

    df_vis["datetime"] = pd.to_datetime(df_vis[date_col], errors="coerce").dt.floor("s")
    df_vis["satellite"] = df_vis[satellite_col].astype(str).map(clean_satellite_name)
    df_vis = df_vis.dropna(subset=["datetime", "satellite"]).copy()
    _emit_progress(progress_callback, f"Planner core: normalized {len(df_vis)} visibility row(s).")

    if targets_df is None:
        if mode == JSON_TIMES_MODE:
            empty = pd.DataFrame(columns=visibility_df.columns)
            return (empty, diagnostics) if return_diagnostics else empty
        df_targets = pd.DataFrame(
            {
                "satellite": df_vis["satellite"].unique(),
                "datetime": [None] * df_vis["satellite"].nunique(),
            }
        )
    else:
        df_targets = targets_df.copy()
        target_satellite_col = resolve_column(df_targets, "satellite", column_mapping=effective_mapping)
        if "datetime" not in df_targets.columns:
            df_targets["datetime"] = None
        df_targets["datetime"] = pd.to_datetime(df_targets["datetime"], errors="coerce").dt.floor("s")
        df_targets["satellite"] = df_targets[target_satellite_col].astype(str).map(clean_satellite_name)

    _emit_progress(progress_callback, f"Planner core: prepared {len(df_targets)} target row(s).")
    _check_cancel(cancel_callback)

    normalized_plan_method = normalize_plan_method(plan_method)
    if normalized_plan_method != PLAN_METHOD_MAX_ELEVATION:
        if mode == JSON_TIMES_MODE:
            candidate_pool = _build_json_time_candidates(
                df_vis,
                df_targets,
                tolerance_sec=tolerance_sec,
                time_range_sec=time_range_sec,
                cancel_callback=cancel_callback,
            )
        elif mode == AUTO_SEQUENCE_MODE:
            candidate_pool = _build_auto_candidate_pool(df_vis, df_targets)
        else:
            candidate_pool = pd.DataFrame(columns=visibility_df.columns)

        _emit_progress(
            progress_callback,
            f"Planner core: stratified candidate pool contains {len(candidate_pool)} row(s).",
        )
        request = SamplingPlannerRequest(
            plan_method=normalized_plan_method,
            binning_mode=binning_mode,
            sample_bins=sample_bins,
            bin_width_deg=bin_width_deg,
            random_seed=random_seed,
            spacing_min=float(spacing_min),
            optimization_enabled=bool(optimization_enabled),
            optimization_trials=int(optimization_trials),
            candidate_depth=int(candidate_depth),
            optimization_objective=optimization_objective,
            slew_model=slew_model,
            transition_constraint_mode=transition_constraint_mode,
            transition_safety_margin_sec=transition_safety_margin_sec,
            local_repair_enabled=bool(local_repair_enabled),
            local_repair_max_additions=int(local_repair_max_additions),
            local_repair_candidate_limit=int(local_repair_candidate_limit),
            local_repair_attempt_limit=int(local_repair_attempt_limit),
            custom_elevation_bin_edges=tuple(custom_elevation_bin_edges or ()),
            custom_solar_phase_bin_edges=tuple(custom_solar_phase_bin_edges or ()),
        )
        _check_cancel(cancel_callback)
        plan_df, sampling_diagnostics = generate_multistart_stratified_sample_plan(
            candidate_pool,
            request=request,
            column_mapping=effective_mapping,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )
        _check_cancel(cancel_callback)
        _emit_progress(progress_callback, f"Planner core: selected {len(plan_df)} stratified row(s).")
        diagnostics = build_plan_generation_diagnostics(
            method=normalized_plan_method,
            mode=mode,
            input_df=visibility_df,
            filtered_df=df_vis,
            candidate_df=candidate_pool,
            plan_before_spacing=plan_df,
            selected_plan=plan_df,
            spacing_min=float(spacing_min),
            metric_logical=(
                "solar_phase_angle"
                if normalized_plan_method == PLAN_METHOD_STRATIFIED_SOLAR_PHASE
                else "elev"
            ),
            sampling_diagnostics=sampling_diagnostics,
            slew_model=slew_model,
            slew_diagnostics_enabled=slew_diagnostics_enabled,
            slew_transition_sample_limit=slew_transition_sample_limit,
            transition_constraint_mode=transition_constraint_mode,
            transition_safety_margin_sec=transition_safety_margin_sec,
        )
        if return_diagnostics and impact_comparison_enabled:
            diagnostics = _attach_optimization_impact_summary(
                diagnostics,
                active_plan=plan_df,
                visibility_df=visibility_df,
                targets_df=targets_df,
                mode=mode,
                tolerance_sec=tolerance_sec,
                spacing_min=spacing_min,
                min_elevation=min_elevation,
                time_range_sec=time_range_sec,
                column_mapping=column_mapping,
                plan_method=normalized_plan_method,
                binning_mode=binning_mode,
                sample_bins=sample_bins,
                bin_width_deg=bin_width_deg,
                custom_elevation_bin_edges=custom_elevation_bin_edges,
                custom_solar_phase_bin_edges=custom_solar_phase_bin_edges,
                random_seed=random_seed,
                optimization_enabled=optimization_enabled,
                optimization_trials=optimization_trials,
                candidate_depth=candidate_depth,
                local_repair_enabled=local_repair_enabled,
                local_repair_max_additions=local_repair_max_additions,
                local_repair_candidate_limit=local_repair_candidate_limit,
                local_repair_attempt_limit=local_repair_attempt_limit,
                slew_diagnostics_enabled=slew_diagnostics_enabled,
                slew_model=slew_model,
                slew_transition_sample_limit=slew_transition_sample_limit,
                transition_safety_margin_sec=transition_safety_margin_sec,
                cancel_callback=cancel_callback,
            )
        _check_cancel(cancel_callback)
        return (plan_df, diagnostics) if return_diagnostics else plan_df

    # Legacy donor-compatible max-elevation path. Keep this behavior unchanged.
    _emit_progress(progress_callback, "Planner core: running legacy max-elevation selection.")
    if mode == JSON_TIMES_MODE:
        plan_df = _build_json_time_best_matches(
            df_vis,
            df_targets,
            tolerance_sec=tolerance_sec,
            time_range_sec=time_range_sec,
            cancel_callback=cancel_callback,
        )
    elif mode == AUTO_SEQUENCE_MODE:
        elev_col = resolve_column(df_vis, "elev", column_mapping=effective_mapping)
        plan_rows = []
        for index, satellite in enumerate(df_targets["satellite"].unique()):
            if index % 128 == 0:
                _check_cancel(cancel_callback)
            satellite_df = df_vis[df_vis["satellite"] == satellite]
            if satellite_df.empty:
                continue
            best = satellite_df.loc[satellite_df[elev_col].idxmax()]
            plan_rows.append(best.to_frame().T)
        plan_df = pd.concat(plan_rows, ignore_index=True) if plan_rows else pd.DataFrame()
    else:
        plan_df = pd.DataFrame(columns=visibility_df.columns)

    _check_cancel(cancel_callback)
    plan_before_spacing = plan_df.copy() if plan_df is not None else pd.DataFrame()
    plan_df = (
        _apply_transition_constraint_filter(
            plan_df,
            spacing_min=spacing_min,
            transition_constraint_mode=transition_constraint_mode,
            slew_model=slew_model,
            transition_safety_margin_sec=transition_safety_margin_sec,
            column_mapping=effective_mapping,
        )
        if not plan_df.empty
        else plan_df
    )
    _emit_progress(progress_callback, f"Planner core: selected {len(plan_df)} max-elevation row(s).")
    if return_diagnostics:
        diagnostics = build_plan_generation_diagnostics(
            method=PLAN_METHOD_MAX_ELEVATION,
            mode=mode,
            input_df=visibility_df,
            filtered_df=df_vis,
            candidate_df=df_vis,
            plan_before_spacing=plan_before_spacing,
            selected_plan=plan_df,
            spacing_min=float(spacing_min),
            metric_logical="elev",
            sampling_diagnostics=None,
            slew_model=slew_model,
            slew_diagnostics_enabled=slew_diagnostics_enabled,
            slew_transition_sample_limit=slew_transition_sample_limit,
            transition_constraint_mode=transition_constraint_mode,
            transition_safety_margin_sec=transition_safety_margin_sec,
        )
        if impact_comparison_enabled:
            diagnostics = _attach_optimization_impact_summary(
                diagnostics,
                active_plan=plan_df,
                visibility_df=visibility_df,
                targets_df=targets_df,
                mode=mode,
                tolerance_sec=tolerance_sec,
                spacing_min=spacing_min,
                min_elevation=min_elevation,
                time_range_sec=time_range_sec,
                column_mapping=column_mapping,
                plan_method=PLAN_METHOD_MAX_ELEVATION,
                binning_mode=binning_mode,
                sample_bins=sample_bins,
                bin_width_deg=bin_width_deg,
                custom_elevation_bin_edges=custom_elevation_bin_edges,
                custom_solar_phase_bin_edges=custom_solar_phase_bin_edges,
                random_seed=random_seed,
                optimization_enabled=optimization_enabled,
                optimization_trials=optimization_trials,
                candidate_depth=candidate_depth,
                local_repair_enabled=local_repair_enabled,
                local_repair_max_additions=local_repair_max_additions,
                local_repair_candidate_limit=local_repair_candidate_limit,
                local_repair_attempt_limit=local_repair_attempt_limit,
                slew_diagnostics_enabled=slew_diagnostics_enabled,
                slew_model=slew_model,
                slew_transition_sample_limit=slew_transition_sample_limit,
                transition_safety_margin_sec=transition_safety_margin_sec,
                cancel_callback=cancel_callback,
            )
    _check_cancel(cancel_callback)
    return (plan_df, diagnostics) if return_diagnostics else plan_df


def _attach_optimization_impact_summary(
    diagnostics: PlanGenerationDiagnostics,
    *,
    active_plan: pd.DataFrame,
    visibility_df: pd.DataFrame,
    targets_df: pd.DataFrame | None,
    mode: str,
    tolerance_sec: int | float,
    spacing_min: int | float,
    min_elevation: int | float | None,
    time_range_sec: int | float,
    column_mapping,
    plan_method: str,
    binning_mode: str,
    sample_bins: int,
    bin_width_deg: float,
    custom_elevation_bin_edges,
    custom_solar_phase_bin_edges,
    random_seed: int,
    optimization_enabled: bool,
    optimization_trials: int,
    candidate_depth: int,
    local_repair_enabled: bool,
    local_repair_max_additions: int,
    local_repair_candidate_limit: int,
    local_repair_attempt_limit: int,
    slew_diagnostics_enabled: bool,
    slew_model: SlewModel | None,
    slew_transition_sample_limit: int,
    transition_safety_margin_sec: float,
    cancel_callback: Callable[[], bool] | None,
) -> PlanGenerationDiagnostics:
    """Return diagnostics with an active-vs-baseline impact summary attached.

    The baseline run is deliberately generated with recursion disabled.  It
    uses the same science sampling setup but forces the current default quality
    objective and time-spacing transition behavior.  This helper must never
    alter the active plan returned to the caller.
    """
    try:
        _check_cancel(cancel_callback)
        baseline_plan, baseline_diagnostics = generate_observation_plan(
            visibility_df,
            targets_df,
            mode=mode,
            tolerance_sec=tolerance_sec,
            spacing_min=spacing_min,
            min_elevation=min_elevation,
            time_range_sec=time_range_sec,
            column_mapping=column_mapping,
            plan_method=plan_method,
            binning_mode=binning_mode,
            sample_bins=sample_bins,
            bin_width_deg=bin_width_deg,
            custom_elevation_bin_edges=custom_elevation_bin_edges,
            custom_solar_phase_bin_edges=custom_solar_phase_bin_edges,
            random_seed=random_seed,
            optimization_enabled=optimization_enabled,
            optimization_trials=optimization_trials,
            candidate_depth=candidate_depth,
            optimization_objective=OPTIMIZATION_OBJECTIVE_QUALITY,
            local_repair_enabled=local_repair_enabled,
            local_repair_max_additions=local_repair_max_additions,
            local_repair_candidate_limit=local_repair_candidate_limit,
            local_repair_attempt_limit=local_repair_attempt_limit,
            slew_diagnostics_enabled=slew_diagnostics_enabled,
            slew_model=slew_model,
            slew_transition_sample_limit=slew_transition_sample_limit,
            transition_constraint_mode=DEFAULT_TRANSITION_CONSTRAINT_MODE,
            transition_safety_margin_sec=transition_safety_margin_sec,
            impact_comparison_enabled=False,
            return_diagnostics=True,
            progress_callback=None,
            cancel_callback=cancel_callback,
        )
        impact_summary = build_optimization_impact_summary(
            active_plan=active_plan,
            baseline_plan=baseline_plan,
            active_diagnostics=diagnostics,
            baseline_diagnostics=baseline_diagnostics,
        )
    except ObservationPlanGenerationCancelled:
        raise
    except Exception as exc:
        impact_summary = unavailable_optimization_impact_summary(
            f"Controlled baseline comparison failed: {exc}"
        )
    return dataclass_replace(diagnostics, optimization_impact_summary=impact_summary)
