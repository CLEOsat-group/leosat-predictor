"""Qt-free filename helpers for Observation Planner exports.

The helpers in this module build only the initial filename suggested by the
GUI save dialog.  They do not own directories, file-dialog interaction, or the
final user-selected export path.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from string import Formatter

from src.observation_planner.sampling import (
    PLAN_METHOD_MAX_ELEVATION,
    PLAN_METHOD_STRATIFIED_ELEVATION,
    PLAN_METHOD_STRATIFIED_SOLAR_PHASE,
)

DEFAULT_PLANNER_EXPORT_PATTERN = "leosat_obs_plan_{date}.csv"
UNKNOWN_PLAN_METHOD_TOKEN = "unknown-method"
MANUAL_PLAN_METHOD_TOKEN = "manual"

_PLAN_METHOD_TOKENS = {
    PLAN_METHOD_MAX_ELEVATION: "max-elevation",
    PLAN_METHOD_STRATIFIED_ELEVATION: "stratified-elevation",
    PLAN_METHOD_STRATIFIED_SOLAR_PHASE: "stratified-solar-phase",
    "max-elevation": "max-elevation",
    "stratified-elevation": "stratified-elevation",
    "stratified-solar-phase": "stratified-solar-phase",
    MANUAL_PLAN_METHOD_TOKEN: MANUAL_PLAN_METHOD_TOKEN,
}
_PLAN_METHOD_ALIASES = {
    canonical.replace("-", "_"): token
    for canonical, token in _PLAN_METHOD_TOKENS.items()
}
_ALLOWED_PATTERN_FIELDS = frozenset({"date", "datetime", "method"})
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_REPEATED_UNDERSCORES = re.compile(r"_{2,}")


def normalize_planner_export_method(value: object) -> str:
    """Return a safe filename token for a planner method identifier.

    Parameters
    ----------
    value : object
        Planner method identifier or an already normalized filename token.

    Returns
    -------
    str
        Canonical method token suitable for use in a filename. Unknown values
        return ``"unknown-method"`` rather than exposing arbitrary input.
    """
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    return _PLAN_METHOD_ALIASES.get(key, UNKNOWN_PLAN_METHOD_TOKEN)


def build_planner_export_filename(
    pattern: str,
    *,
    plan_method: str,
    timestamp: datetime,
) -> str:
    """Build a safe method-aware planner export filename suggestion.

    Parameters
    ----------
    pattern : str
        User-configured filename pattern. Supported placeholders are
        ``{date}``, ``{datetime}``, and ``{method}``.
    plan_method : str
        Planner method identifier or canonical filename token.
    timestamp : datetime
        Timestamp used to expand date placeholders.

    Returns
    -------
    str
        A filename only, never a directory path. If ``{method}`` is absent,
        the canonical method token is inserted before the final extension.

    Notes
    -----
    Unsupported placeholders or malformed format expressions fall back to the
    default planner filename pattern. The helper affects only the save-dialog
    suggestion; a path selected by the user remains authoritative.
    """
    method_token = normalize_planner_export_method(plan_method)
    selected_pattern = str(pattern or "").strip() or DEFAULT_PLANNER_EXPORT_PATTERN

    try:
        field_names = _validate_pattern(selected_pattern)
        formatted = selected_pattern.format(
            date=timestamp.strftime("%Y-%m-%d"),
            datetime=timestamp.strftime("%Y-%m-%d_%H-%M-%S"),
            method=method_token,
        )
    except (KeyError, IndexError, ValueError):
        selected_pattern = DEFAULT_PLANNER_EXPORT_PATTERN
        field_names = _validate_pattern(selected_pattern)
        formatted = selected_pattern.format(
            date=timestamp.strftime("%Y-%m-%d"),
            datetime=timestamp.strftime("%Y-%m-%d_%H-%M-%S"),
            method=method_token,
        )

    filename = _sanitize_filename(formatted)
    if not filename:
        filename = DEFAULT_PLANNER_EXPORT_PATTERN.format(
            date=timestamp.strftime("%Y-%m-%d"),
        )
        field_names = {"date"}

    if "method" not in field_names:
        filename = _append_method_suffix(filename, method_token)

    return filename


def _validate_pattern(pattern: str) -> set[str]:
    """Validate supported fields and return the fields used by ``pattern``."""
    fields: set[str] = set()
    for _, field_name, format_spec, conversion in Formatter().parse(pattern):
        if field_name is None:
            continue
        if field_name not in _ALLOWED_PATTERN_FIELDS:
            raise KeyError(field_name)
        if format_spec or conversion:
            raise ValueError("Planner export filename fields do not support format specifications or conversions.")
        fields.add(field_name)
    return fields


def _sanitize_filename(value: object) -> str:
    """Return a cross-platform-safe basename while preserving its extension."""
    normalized_path = str(value or "").replace("\\", "/")
    basename = Path(normalized_path).name.strip()
    basename = _UNSAFE_FILENAME_CHARS.sub("_", basename)
    basename = _REPEATED_UNDERSCORES.sub("_", basename)
    basename = basename.rstrip(" .")
    if not basename:
        return ""

    path = Path(basename)
    if path.stem.upper() in _WINDOWS_RESERVED_NAMES:
        basename = f"_{basename}"
    return basename


def _append_method_suffix(filename: str, method_token: str) -> str:
    """Insert ``method_token`` before the final extension without duplication."""
    path = Path(filename)
    suffix = path.suffix
    stem = filename[: -len(suffix)] if suffix else filename
    marker = f"_{method_token}"
    if not stem.lower().endswith(marker.lower()):
        stem = f"{stem}{marker}"
    return f"{stem}{suffix}"


__all__ = [
    "DEFAULT_PLANNER_EXPORT_PATTERN",
    "MANUAL_PLAN_METHOD_TOKEN",
    "UNKNOWN_PLAN_METHOD_TOKEN",
    "build_planner_export_filename",
    "normalize_planner_export_method",
]
