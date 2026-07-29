"""Shared observation-planner core package."""

from .export import (
    CSV_EXPORT_COLUMNS,
    TXT_EXPORT_HEADER,
    format_plan_for_csv,
    format_plan_for_txt,
    write_plan_csv,
    write_plan_txt,
)
from .io import detect_visibility_file_type, load_targets_json, load_visibility_file
from .normalize import (
    ALL_SATELLITES_LABEL,
    clean_satellite_name,
    filter_by_satellite,
    filter_by_targets,
    make_base_and_view,
    prepare_visibility_dataframe,
)
from .planner import (
    AUTO_SEQUENCE_MODE,
    JSON_TIMES_MODE,
    build_auto_targets_from_visibility,
    generate_observation_plan,
    should_use_loaded_targets_for_auto_mode,
)
from .schema import (
    COLUMN_SPECS,
    ColumnSpec,
    get_default_width,
    get_display_name,
    resolve_column,
    resolve_columns,
)

__all__ = [
    "ALL_SATELLITES_LABEL",
    "AUTO_SEQUENCE_MODE",
    "COLUMN_SPECS",
    "CSV_EXPORT_COLUMNS",
    "JSON_TIMES_MODE",
    "TXT_EXPORT_HEADER",
    "ColumnSpec",
    "build_auto_targets_from_visibility",
    "clean_satellite_name",
    "detect_visibility_file_type",
    "filter_by_satellite",
    "filter_by_targets",
    "format_plan_for_csv",
    "format_plan_for_txt",
    "generate_observation_plan",
    "get_default_width",
    "get_display_name",
    "load_targets_json",
    "load_visibility_file",
    "make_base_and_view",
    "prepare_visibility_dataframe",
    "resolve_column",
    "resolve_columns",
    "should_use_loaded_targets_for_auto_mode",
    "write_plan_csv",
    "write_plan_txt",
]
