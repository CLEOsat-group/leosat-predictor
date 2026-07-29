"""Shared Observation Planner preference contract.

This module is deliberately GUI- and web-neutral.  It adapts donor-style
``leosat-obs-selector.py`` settings and the integrated predictor preference tree
into one validated object that can be used by the GUI now and by the future web
Observation Planner later.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, replace
from typing import Any

from .column_mapping import default_donor_column_mapping, normalize_column_mapping
from .coordinate_format import COORD_FORMAT_COLON, normalize_coordinate_format
from .slew_diagnostics import (
    DEFAULT_SLEW_MODEL,
    DEFAULT_TRANSITION_SAMPLE_LIMIT,
    MAX_SLEW_OVERHEAD_SEC,
    MAX_SLEW_RATE_DEG_PER_SEC,
    MAX_TRANSITION_SAMPLE_LIMIT,
    MIN_SLEW_RATE_DEG_PER_SEC,
    MIN_TRANSITION_SAMPLE_LIMIT,
    SlewModel,
    validate_transition_sample_limit,
)
from .transition_constraints import (
    DEFAULT_TRANSITION_CONSTRAINT_MODE,
    DEFAULT_TRANSITION_SAFETY_MARGIN_SEC,
    TRANSITION_CONSTRAINT_TIME_SPACING,
    normalize_transition_constraint_mode,
    validate_transition_safety_margin_sec,
)
from .sampling import (
    BINNING_EQUAL_WIDTH,
    DEFAULT_BIN_WIDTH_DEG,
    MIN_BIN_WIDTH_DEG,
    MAX_BIN_WIDTH_DEG,
    DEFAULT_RANDOM_SEED,
    DEFAULT_OPTIMIZATION_TRIALS,
    DEFAULT_SAMPLE_BINS,
    DEFAULT_CANDIDATE_DEPTH,
    DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT,
    DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT,
    DEFAULT_LOCAL_REPAIR_ENABLED,
    DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS,
    PLAN_METHOD_MAX_ELEVATION,
    SAMPLING_METRIC_ELEVATION,
    metric_for_plan_method,
    normalize_binning_mode,
    normalize_plan_method,
    parse_custom_bin_edges,
    validate_optimization_trials,
    validate_candidate_depth,
    validate_bin_width_deg,
    validate_local_repair_attempt_limit,
    validate_local_repair_candidate_limit,
    validate_local_repair_max_additions,
    OPTIMIZATION_OBJECTIVE_SLEW_AWARE,
    normalize_optimization_objective,
)


OBSERVATION_PLANNER_SECTION = "observation_planner"

PREFERENCE_KEYS = (
    "exposure_time_sec",
    "time_range_sec",
    "min_elevation_deg",
    "tolerance_sec",
    "spacing_min",
    "default_mode",
    "filename_pattern",
    "default_plan_pattern",  # retained compatibility alias
    "legend_page_size",
    "column_mapping",
    "default_plan_method",
    "default_sampling_metric",
    "default_binning_mode",
    "default_sample_bins",
    "default_bin_width_deg",
    "custom_elevation_bin_edges",
    "custom_solar_phase_bin_edges",
    "random_seed",
    "optimization_enabled",
    "optimization_trials",
    "candidate_depth",
    "optimization_objective",
    "local_repair_enabled",
    "local_repair_max_additions",
    "local_repair_candidate_limit",
    "local_repair_attempt_limit",
    "transition_constraint_mode",
    "transition_safety_margin_sec",
    "default_coordinate_format",
    "slew_diagnostics_enabled",
    "slew_az_rate_deg_per_sec",
    "slew_alt_rate_deg_per_sec",
    "slew_settle_time_sec",
    "slew_acquisition_time_sec",
    "slew_exposure_time_sec",
    "slew_transition_sample_limit",
)

DEFAULT_EXPOSURE_TIME_SEC = 5.0
DEFAULT_TIME_RANGE_SEC = 0.0
DEFAULT_MIN_ELEVATION_DEG = 0.0
DEFAULT_TOLERANCE_SEC = 1.0
DEFAULT_SPACING_MIN = 3.0
DEFAULT_MODE = "automatic"
DEFAULT_FILENAME_PATTERN = "leosat_obs_plan_{date}.csv"
DEFAULT_LEGEND_PAGE_SIZE = 5
DEFAULT_PLAN_METHOD = PLAN_METHOD_MAX_ELEVATION
DEFAULT_SAMPLING_METRIC = SAMPLING_METRIC_ELEVATION
DEFAULT_BINNING_MODE = BINNING_EQUAL_WIDTH
DEFAULT_OPTIMIZATION_ENABLED = True
DEFAULT_OPTIMIZATION_OBJECTIVE = OPTIMIZATION_OBJECTIVE_SLEW_AWARE
DEFAULT_TRANSITION_CONSTRAINT_MODE = TRANSITION_CONSTRAINT_TIME_SPACING
DEFAULT_COORDINATE_FORMAT = COORD_FORMAT_COLON
DEFAULT_SLEW_DIAGNOSTICS_ENABLED = True
DEFAULT_SLEW_AZ_RATE_DEG_PER_SEC = DEFAULT_SLEW_MODEL.az_rate_deg_per_sec
DEFAULT_SLEW_ALT_RATE_DEG_PER_SEC = DEFAULT_SLEW_MODEL.alt_rate_deg_per_sec
DEFAULT_SLEW_SETTLE_TIME_SEC = DEFAULT_SLEW_MODEL.settle_time_sec
DEFAULT_SLEW_ACQUISITION_TIME_SEC = DEFAULT_SLEW_MODEL.acquisition_time_sec
DEFAULT_SLEW_EXPOSURE_TIME_SEC = DEFAULT_SLEW_MODEL.exposure_time_sec
DEFAULT_SLEW_TRANSITION_SAMPLE_LIMIT = DEFAULT_TRANSITION_SAMPLE_LIMIT

_MODE_ALIASES = {
    "automatic": "automatic",
    "auto": "automatic",
    "auto_sequence": "automatic",
    "auto sequence": "automatic",
    "json_times": "json_times",
    "json times": "json_times",
    "use json times": "json_times",
}


@dataclass(frozen=True)
class ObservationPlannerPreferences:
    """Validated Observation Planner preference values.

    Parameters
    ----------
    exposure_time_sec : float
        Exposure time used for start-observation display calculations.
    time_range_sec : float
        Donor time-range control in seconds.  The shared planner consumes this
        as a symmetric target-time matching window when JSON-time planning is
        used; ``0`` preserves donor/default no-expansion behavior.
    min_elevation_deg : float
        Minimum satellite elevation for planning.
    tolerance_sec : float
        Exact/near-target matching tolerance in seconds.
    spacing_min : float
        Minimum spacing between generated observations in minutes.
    default_mode : str
        ``"automatic"`` or ``"json_times"``.
    filename_pattern : str
        Observation-plan export filename pattern.
    legend_page_size : int
        Donor-equivalent satellite legend page size.
    column_mapping : dict
        Donor-compatible logical-to-physical visibility column mapping.
    """

    exposure_time_sec: float = DEFAULT_EXPOSURE_TIME_SEC
    time_range_sec: float = DEFAULT_TIME_RANGE_SEC
    min_elevation_deg: float = DEFAULT_MIN_ELEVATION_DEG
    tolerance_sec: float = DEFAULT_TOLERANCE_SEC
    spacing_min: float = DEFAULT_SPACING_MIN
    default_mode: str = DEFAULT_MODE
    filename_pattern: str = DEFAULT_FILENAME_PATTERN
    legend_page_size: int = DEFAULT_LEGEND_PAGE_SIZE
    column_mapping: Mapping[str, Any] | None = None
    default_plan_method: str = DEFAULT_PLAN_METHOD
    default_sampling_metric: str = DEFAULT_SAMPLING_METRIC
    default_binning_mode: str = DEFAULT_BINNING_MODE
    default_sample_bins: int = DEFAULT_SAMPLE_BINS
    default_bin_width_deg: float = DEFAULT_BIN_WIDTH_DEG
    custom_elevation_bin_edges: tuple[float, ...] = ()
    custom_solar_phase_bin_edges: tuple[float, ...] = ()
    random_seed: int = DEFAULT_RANDOM_SEED
    optimization_enabled: bool = DEFAULT_OPTIMIZATION_ENABLED
    optimization_trials: int = DEFAULT_OPTIMIZATION_TRIALS
    candidate_depth: int = DEFAULT_CANDIDATE_DEPTH
    optimization_objective: str = DEFAULT_OPTIMIZATION_OBJECTIVE
    local_repair_enabled: bool = DEFAULT_LOCAL_REPAIR_ENABLED
    local_repair_max_additions: int = DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS
    local_repair_candidate_limit: int = DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT
    local_repair_attempt_limit: int = DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT
    transition_constraint_mode: str = DEFAULT_TRANSITION_CONSTRAINT_MODE
    transition_safety_margin_sec: float = DEFAULT_TRANSITION_SAFETY_MARGIN_SEC
    default_coordinate_format: str = DEFAULT_COORDINATE_FORMAT
    slew_diagnostics_enabled: bool = DEFAULT_SLEW_DIAGNOSTICS_ENABLED
    slew_az_rate_deg_per_sec: float = DEFAULT_SLEW_AZ_RATE_DEG_PER_SEC
    slew_alt_rate_deg_per_sec: float = DEFAULT_SLEW_ALT_RATE_DEG_PER_SEC
    slew_settle_time_sec: float = DEFAULT_SLEW_SETTLE_TIME_SEC
    slew_acquisition_time_sec: float = DEFAULT_SLEW_ACQUISITION_TIME_SEC
    slew_exposure_time_sec: float = DEFAULT_SLEW_EXPOSURE_TIME_SEC
    slew_transition_sample_limit: int = DEFAULT_SLEW_TRANSITION_SAMPLE_LIMIT

    @property
    def default_plan_pattern(self) -> str:
        """Backward-compatible alias used by older GUI code."""
        return self.filename_pattern

    def normalized(self) -> "ObservationPlannerPreferences":
        """Return a validated/normalized copy of this preference object."""
        return _validate_preferences(self)

    def slew_model(self) -> SlewModel:
        """Return the validated diagnostics-only telescope motion model."""
        return SlewModel(
            az_rate_deg_per_sec=self.slew_az_rate_deg_per_sec,
            alt_rate_deg_per_sec=self.slew_alt_rate_deg_per_sec,
            settle_time_sec=self.slew_settle_time_sec,
            acquisition_time_sec=self.slew_acquisition_time_sec,
            exposure_time_sec=self.slew_exposure_time_sec,
        ).validated()


def _as_section(raw: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Return the nested observation-planner preference section when present."""
    if not isinstance(raw, Mapping):
        return {}
    section = raw.get(OBSERVATION_PLANNER_SECTION)
    if isinstance(section, Mapping):
        return section
    return raw


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _to_bool(value: Any, default: bool) -> bool:
    """Return a permissive boolean value from persisted preferences."""
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    return bool(default)


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    """Return a finite float preference constrained to a safe range."""
    try:
        number = float(value)
    except Exception:
        return float(default)
    if number != number or number in {float("inf"), float("-inf")}:
        return float(default)
    if number < minimum:
        return float(default)
    if number > maximum:
        return float(maximum)
    return float(number)


def normalize_mode(value: Any) -> str:
    """Normalize donor/integrated mode labels to stored identifiers."""
    key = str(value or DEFAULT_MODE).strip().lower().replace("-", "_")
    return _MODE_ALIASES.get(key, DEFAULT_MODE)


def planner_mode_from_default_mode(value: Any) -> str:
    """Return the shared planner mode constant for a preference mode value."""
    mode = normalize_mode(value)
    return "json_times" if mode == "json_times" else "auto_sequence"


def default_observation_planner_preferences() -> ObservationPlannerPreferences:
    """Return validated donor-compatible default preferences."""
    return ObservationPlannerPreferences(
        column_mapping=default_donor_column_mapping(),
    ).normalized()


def _validate_preferences(preferences: ObservationPlannerPreferences) -> ObservationPlannerPreferences:
    """Validate and normalize an Observation Planner preference object."""
    exposure = float(preferences.exposure_time_sec)
    time_range = float(preferences.time_range_sec)
    min_elev = float(preferences.min_elevation_deg)
    tolerance = float(preferences.tolerance_sec)
    spacing = float(preferences.spacing_min)
    legend_page_size = int(preferences.legend_page_size)
    mode = normalize_mode(preferences.default_mode)
    filename_pattern = str(preferences.filename_pattern or DEFAULT_FILENAME_PATTERN).strip() or DEFAULT_FILENAME_PATTERN
    column_mapping = normalize_column_mapping(preferences.column_mapping)
    plan_method = normalize_plan_method(preferences.default_plan_method)
    sampling_metric = metric_for_plan_method(plan_method)
    binning_mode = normalize_binning_mode(preferences.default_binning_mode)
    sample_bins = int(preferences.default_sample_bins)
    bin_width_deg = validate_bin_width_deg(preferences.default_bin_width_deg)
    elevation_edges = parse_custom_bin_edges(preferences.custom_elevation_bin_edges)
    solar_phase_edges = parse_custom_bin_edges(preferences.custom_solar_phase_bin_edges)
    random_seed = int(preferences.random_seed)
    optimization_enabled = bool(preferences.optimization_enabled)
    optimization_trials = validate_optimization_trials(preferences.optimization_trials)
    candidate_depth = validate_candidate_depth(preferences.candidate_depth)
    optimization_objective = normalize_optimization_objective(preferences.optimization_objective)
    local_repair_enabled = bool(preferences.local_repair_enabled)
    local_repair_max_additions = validate_local_repair_max_additions(
        preferences.local_repair_max_additions,
        sample_bins=sample_bins,
    )
    local_repair_candidate_limit = validate_local_repair_candidate_limit(preferences.local_repair_candidate_limit)
    local_repair_attempt_limit = validate_local_repair_attempt_limit(preferences.local_repair_attempt_limit)
    transition_constraint_mode = normalize_transition_constraint_mode(preferences.transition_constraint_mode)
    transition_safety_margin_sec = validate_transition_safety_margin_sec(preferences.transition_safety_margin_sec)
    coordinate_format = normalize_coordinate_format(preferences.default_coordinate_format)
    slew_diagnostics_enabled = bool(preferences.slew_diagnostics_enabled)
    slew_az_rate = _bounded_float(
        preferences.slew_az_rate_deg_per_sec,
        default=DEFAULT_SLEW_AZ_RATE_DEG_PER_SEC,
        minimum=MIN_SLEW_RATE_DEG_PER_SEC,
        maximum=MAX_SLEW_RATE_DEG_PER_SEC,
    )
    slew_alt_rate = _bounded_float(
        preferences.slew_alt_rate_deg_per_sec,
        default=DEFAULT_SLEW_ALT_RATE_DEG_PER_SEC,
        minimum=MIN_SLEW_RATE_DEG_PER_SEC,
        maximum=MAX_SLEW_RATE_DEG_PER_SEC,
    )
    slew_settle = _bounded_float(
        preferences.slew_settle_time_sec,
        default=DEFAULT_SLEW_SETTLE_TIME_SEC,
        minimum=0.0,
        maximum=MAX_SLEW_OVERHEAD_SEC,
    )
    slew_acquisition = _bounded_float(
        preferences.slew_acquisition_time_sec,
        default=DEFAULT_SLEW_ACQUISITION_TIME_SEC,
        minimum=0.0,
        maximum=MAX_SLEW_OVERHEAD_SEC,
    )
    slew_exposure = _bounded_float(
        preferences.slew_exposure_time_sec,
        default=DEFAULT_SLEW_EXPOSURE_TIME_SEC,
        minimum=0.0,
        maximum=MAX_SLEW_OVERHEAD_SEC,
    )
    slew_transition_sample_limit = validate_transition_sample_limit(preferences.slew_transition_sample_limit)

    if exposure <= 0:
        raise ValueError("Observation Planner exposure_time_sec must be > 0.")
    if time_range < 0:
        raise ValueError("Observation Planner time_range_sec must be >= 0.")
    if not -90.0 <= min_elev <= 90.0:
        raise ValueError("Observation Planner min_elevation_deg must be between -90 and 90.")
    if tolerance < 0:
        raise ValueError("Observation Planner tolerance_sec must be >= 0.")
    if spacing <= 0:
        raise ValueError("Observation Planner spacing_min must be > 0.")
    if legend_page_size < 1:
        raise ValueError("Observation Planner legend_page_size must be >= 1.")
    if sample_bins < 1:
        raise ValueError("Observation Planner default_sample_bins must be >= 1.")
    if random_seed < 0:
        raise ValueError("Observation Planner random_seed must be >= 0.")

    return replace(
        preferences,
        exposure_time_sec=exposure,
        time_range_sec=time_range,
        min_elevation_deg=min_elev,
        tolerance_sec=tolerance,
        spacing_min=spacing,
        default_mode=mode,
        filename_pattern=filename_pattern,
        legend_page_size=legend_page_size,
        column_mapping=column_mapping,
        default_plan_method=plan_method,
        default_sampling_metric=sampling_metric,
        default_binning_mode=binning_mode,
        default_sample_bins=sample_bins,
        default_bin_width_deg=bin_width_deg,
        custom_elevation_bin_edges=elevation_edges,
        custom_solar_phase_bin_edges=solar_phase_edges,
        random_seed=random_seed,
        optimization_enabled=optimization_enabled,
        optimization_trials=optimization_trials,
        candidate_depth=candidate_depth,
        optimization_objective=optimization_objective,
        local_repair_enabled=local_repair_enabled,
        local_repair_max_additions=local_repair_max_additions,
        local_repair_candidate_limit=local_repair_candidate_limit,
        local_repair_attempt_limit=local_repair_attempt_limit,
        transition_constraint_mode=transition_constraint_mode,
        transition_safety_margin_sec=transition_safety_margin_sec,
        default_coordinate_format=coordinate_format,
        slew_diagnostics_enabled=slew_diagnostics_enabled,
        slew_az_rate_deg_per_sec=slew_az_rate,
        slew_alt_rate_deg_per_sec=slew_alt_rate,
        slew_settle_time_sec=slew_settle,
        slew_acquisition_time_sec=slew_acquisition,
        slew_exposure_time_sec=slew_exposure,
        slew_transition_sample_limit=slew_transition_sample_limit,
    )


def migrate_legacy_observation_planner_preferences(raw: MutableMapping[str, Any] | Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a preference dictionary with legacy keys preserved and expanded.

    Parameters
    ----------
    raw : mapping or None
        Either a full integrated preferences tree containing an
        ``observation_planner`` section, or the section itself.  Donor-style
        settings with ``visibility.columns`` are also accepted.

    Returns
    -------
    dict
        Full preference-tree-like dictionary containing a complete
        ``observation_planner`` section.  Existing explicit user values are not
        overwritten.
    """
    full: dict[str, Any] = dict(raw or {}) if isinstance(raw, Mapping) else {}
    section = dict(_as_section(full))

    # Donor settings store the column contract under visibility.columns.
    donor_column_source: Mapping[str, Any] | None = None
    if isinstance(full.get("visibility"), Mapping):
        donor_column_source = full
    if isinstance(section.get("visibility"), Mapping):
        donor_column_source = section

    if "filename_pattern" not in section and "default_plan_pattern" in section:
        section["filename_pattern"] = section["default_plan_pattern"]
    if "default_plan_pattern" not in section and "filename_pattern" in section:
        section["default_plan_pattern"] = section["filename_pattern"]

    defaults = default_observation_planner_preferences()
    section.setdefault("exposure_time_sec", defaults.exposure_time_sec)
    section.setdefault("time_range_sec", defaults.time_range_sec)
    section.setdefault("min_elevation_deg", defaults.min_elevation_deg)
    section.setdefault("tolerance_sec", defaults.tolerance_sec)
    section.setdefault("spacing_min", defaults.spacing_min)
    section.setdefault("default_mode", defaults.default_mode)
    section.setdefault("filename_pattern", defaults.filename_pattern)
    section.setdefault("default_plan_pattern", section.get("filename_pattern", defaults.filename_pattern))
    section.setdefault("legend_page_size", defaults.legend_page_size)
    section.setdefault("default_plan_method", defaults.default_plan_method)
    section.setdefault("default_sampling_metric", defaults.default_sampling_metric)
    section.setdefault("default_binning_mode", defaults.default_binning_mode)
    section.setdefault("default_sample_bins", defaults.default_sample_bins)
    section.setdefault("default_bin_width_deg", defaults.default_bin_width_deg)
    section.setdefault("custom_elevation_bin_edges", list(defaults.custom_elevation_bin_edges))
    section.setdefault("custom_solar_phase_bin_edges", list(defaults.custom_solar_phase_bin_edges))
    section.setdefault("random_seed", defaults.random_seed)
    section.setdefault("optimization_enabled", defaults.optimization_enabled)
    section.setdefault("optimization_trials", defaults.optimization_trials)
    section.setdefault("candidate_depth", defaults.candidate_depth)
    section.setdefault("optimization_objective", defaults.optimization_objective)
    section.setdefault("local_repair_enabled", defaults.local_repair_enabled)
    section.setdefault("local_repair_max_additions", defaults.local_repair_max_additions)
    section.setdefault("local_repair_candidate_limit", defaults.local_repair_candidate_limit)
    section.setdefault("local_repair_attempt_limit", defaults.local_repair_attempt_limit)
    section.setdefault("transition_constraint_mode", defaults.transition_constraint_mode)
    section.setdefault("transition_safety_margin_sec", defaults.transition_safety_margin_sec)
    section.setdefault("default_coordinate_format", defaults.default_coordinate_format)
    section.setdefault("slew_diagnostics_enabled", defaults.slew_diagnostics_enabled)
    section.setdefault("slew_az_rate_deg_per_sec", defaults.slew_az_rate_deg_per_sec)
    section.setdefault("slew_alt_rate_deg_per_sec", defaults.slew_alt_rate_deg_per_sec)
    section.setdefault("slew_settle_time_sec", defaults.slew_settle_time_sec)
    section.setdefault("slew_acquisition_time_sec", defaults.slew_acquisition_time_sec)
    section.setdefault("slew_exposure_time_sec", defaults.slew_exposure_time_sec)
    section.setdefault("slew_transition_sample_limit", defaults.slew_transition_sample_limit)

    if "column_mapping" not in section:
        section["column_mapping"] = normalize_column_mapping(donor_column_source)
    else:
        section["column_mapping"] = normalize_column_mapping(section.get("column_mapping"))

    full[OBSERVATION_PLANNER_SECTION] = section
    return full


def from_preferences_dict(raw: Mapping[str, Any] | None) -> ObservationPlannerPreferences:
    """Materialize shared Observation Planner preferences from a dictionary."""
    migrated = migrate_legacy_observation_planner_preferences(raw)
    section = migrated[OBSERVATION_PLANNER_SECTION]
    prefs = ObservationPlannerPreferences(
        exposure_time_sec=_to_float(section.get("exposure_time_sec"), DEFAULT_EXPOSURE_TIME_SEC),
        time_range_sec=_to_float(section.get("time_range_sec"), DEFAULT_TIME_RANGE_SEC),
        min_elevation_deg=_to_float(section.get("min_elevation_deg"), DEFAULT_MIN_ELEVATION_DEG),
        tolerance_sec=_to_float(section.get("tolerance_sec"), DEFAULT_TOLERANCE_SEC),
        spacing_min=_to_float(section.get("spacing_min"), DEFAULT_SPACING_MIN),
        default_mode=normalize_mode(section.get("default_mode", DEFAULT_MODE)),
        filename_pattern=str(
            section.get("filename_pattern", section.get("default_plan_pattern", DEFAULT_FILENAME_PATTERN))
        ),
        legend_page_size=_to_int(section.get("legend_page_size"), DEFAULT_LEGEND_PAGE_SIZE),
        column_mapping=section.get("column_mapping"),
        default_plan_method=section.get("default_plan_method", DEFAULT_PLAN_METHOD),
        default_sampling_metric=section.get("default_sampling_metric", DEFAULT_SAMPLING_METRIC),
        default_binning_mode=section.get("default_binning_mode", DEFAULT_BINNING_MODE),
        default_sample_bins=_to_int(section.get("default_sample_bins"), DEFAULT_SAMPLE_BINS),
        default_bin_width_deg=_to_float(section.get("default_bin_width_deg"), DEFAULT_BIN_WIDTH_DEG),
        custom_elevation_bin_edges=parse_custom_bin_edges(section.get("custom_elevation_bin_edges", ())),
        custom_solar_phase_bin_edges=parse_custom_bin_edges(section.get("custom_solar_phase_bin_edges", ())),
        random_seed=_to_int(section.get("random_seed"), DEFAULT_RANDOM_SEED),
        optimization_enabled=_to_bool(section.get("optimization_enabled"), DEFAULT_OPTIMIZATION_ENABLED),
        optimization_trials=_to_int(section.get("optimization_trials"), DEFAULT_OPTIMIZATION_TRIALS),
        candidate_depth=_to_int(section.get("candidate_depth"), DEFAULT_CANDIDATE_DEPTH),
        optimization_objective=normalize_optimization_objective(section.get("optimization_objective", DEFAULT_OPTIMIZATION_OBJECTIVE)),
        local_repair_enabled=_to_bool(section.get("local_repair_enabled"), DEFAULT_LOCAL_REPAIR_ENABLED),
        local_repair_max_additions=_to_int(section.get("local_repair_max_additions"), DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS),
        local_repair_candidate_limit=_to_int(section.get("local_repair_candidate_limit"), DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT),
        local_repair_attempt_limit=_to_int(section.get("local_repair_attempt_limit"), DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT),
        transition_constraint_mode=normalize_transition_constraint_mode(
            section.get("transition_constraint_mode", DEFAULT_TRANSITION_CONSTRAINT_MODE)
        ),
        transition_safety_margin_sec=_to_float(
            section.get("transition_safety_margin_sec"),
            DEFAULT_TRANSITION_SAFETY_MARGIN_SEC,
        ),
        default_coordinate_format=normalize_coordinate_format(
            section.get("default_coordinate_format", DEFAULT_COORDINATE_FORMAT)
        ),
        slew_diagnostics_enabled=_to_bool(
            section.get("slew_diagnostics_enabled"),
            DEFAULT_SLEW_DIAGNOSTICS_ENABLED,
        ),
        slew_az_rate_deg_per_sec=_to_float(
            section.get("slew_az_rate_deg_per_sec"),
            DEFAULT_SLEW_AZ_RATE_DEG_PER_SEC,
        ),
        slew_alt_rate_deg_per_sec=_to_float(
            section.get("slew_alt_rate_deg_per_sec"),
            DEFAULT_SLEW_ALT_RATE_DEG_PER_SEC,
        ),
        slew_settle_time_sec=_to_float(
            section.get("slew_settle_time_sec"),
            DEFAULT_SLEW_SETTLE_TIME_SEC,
        ),
        slew_acquisition_time_sec=_to_float(
            section.get("slew_acquisition_time_sec"),
            DEFAULT_SLEW_ACQUISITION_TIME_SEC,
        ),
        slew_exposure_time_sec=_to_float(
            section.get("slew_exposure_time_sec"),
            DEFAULT_SLEW_EXPOSURE_TIME_SEC,
        ),
        slew_transition_sample_limit=_to_int(
            section.get("slew_transition_sample_limit"),
            DEFAULT_SLEW_TRANSITION_SAMPLE_LIMIT,
        ),
    )
    return prefs.normalized()


def to_preferences_dict(preferences: ObservationPlannerPreferences) -> dict[str, Any]:
    """Serialize preferences to the integrated nested preference section."""
    prefs = preferences.normalized()
    column_mapping = normalize_column_mapping(prefs.column_mapping)
    return {
        OBSERVATION_PLANNER_SECTION: {
            "exposure_time_sec": prefs.exposure_time_sec,
            "time_range_sec": prefs.time_range_sec,
            "min_elevation_deg": prefs.min_elevation_deg,
            "tolerance_sec": prefs.tolerance_sec,
            "spacing_min": prefs.spacing_min,
            "default_mode": prefs.default_mode,
            "filename_pattern": prefs.filename_pattern,
            "default_plan_pattern": prefs.filename_pattern,
            "legend_page_size": prefs.legend_page_size,
            # Donor-compatible storage shape.  The legacy flat
            # ``column_mapping`` key is retained as a compatibility alias for
            # existing integrated code, but user-facing editing is the donor
            # table, not a raw JSON field.
            "visibility": {"columns": column_mapping},
            "column_mapping": column_mapping,
            "default_plan_method": prefs.default_plan_method,
            "default_sampling_metric": prefs.default_sampling_metric,
            "default_binning_mode": prefs.default_binning_mode,
            "default_sample_bins": prefs.default_sample_bins,
            "default_bin_width_deg": prefs.default_bin_width_deg,
            "custom_elevation_bin_edges": list(prefs.custom_elevation_bin_edges),
            "custom_solar_phase_bin_edges": list(prefs.custom_solar_phase_bin_edges),
            "random_seed": prefs.random_seed,
            "optimization_enabled": prefs.optimization_enabled,
            "optimization_trials": prefs.optimization_trials,
            "candidate_depth": prefs.candidate_depth,
            "optimization_objective": prefs.optimization_objective,
            "local_repair_enabled": prefs.local_repair_enabled,
            "local_repair_max_additions": prefs.local_repair_max_additions,
            "local_repair_candidate_limit": prefs.local_repair_candidate_limit,
            "local_repair_attempt_limit": prefs.local_repair_attempt_limit,
            "transition_constraint_mode": prefs.transition_constraint_mode,
            "transition_safety_margin_sec": prefs.transition_safety_margin_sec,
            "default_coordinate_format": prefs.default_coordinate_format,
            "slew_diagnostics_enabled": prefs.slew_diagnostics_enabled,
            "slew_az_rate_deg_per_sec": prefs.slew_az_rate_deg_per_sec,
            "slew_alt_rate_deg_per_sec": prefs.slew_alt_rate_deg_per_sec,
            "slew_settle_time_sec": prefs.slew_settle_time_sec,
            "slew_acquisition_time_sec": prefs.slew_acquisition_time_sec,
            "slew_exposure_time_sec": prefs.slew_exposure_time_sec,
            "slew_transition_sample_limit": prefs.slew_transition_sample_limit,
        }
    }


def legend_page_slice(satellites: list[str] | tuple[str, ...], page: int, page_size: int) -> tuple[list[str], int, int]:
    """Return donor-equivalent satellite legend page contents.

    Parameters
    ----------
    satellites : sequence of str
        Satellite names in plot/color order.
    page : int
        Zero-based requested page index.  Values wrap by total page count.
    page_size : int
        Maximum number of satellites per legend page.

    Returns
    -------
    tuple
        ``(page_satellites, normalized_page_index, total_pages)``.
    """
    size = max(1, int(page_size))
    names = [str(item) for item in satellites]
    total_pages = max(1, (len(names) + size - 1) // size)
    page_index = int(page) % total_pages
    start = page_index * size
    return names[start : start + size], page_index, total_pages
