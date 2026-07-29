"""Column-mapping contract for Observation Planner visibility data.

This module is intentionally GUI- and web-neutral.  It preserves the donor
``leosat-obs-selector.py`` logical-column idea while adding predictor CSV
aliases used by the integrated application.  Table, plot, and plan-generation
code should resolve visibility columns through this module, either directly or
through ``src.observation_planner.schema``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import pandas as pd


COLUMN_MAPPING_ATTR = "observation_planner_column_mapping"


@dataclass(frozen=True)
class ColumnSpec:
    """Description of one logical observation-planner column.

    Parameters
    ----------
    logical_name : str
        Canonical planner field name.
    aliases : tuple of str
        Physical CSV/DataFrame labels accepted for this logical field.
    display_name : str
        User-facing table header label.
    default_width : int
        Default table width in pixels.
    hidden : bool, optional
        Whether the field is a helper column hidden in the visibility table.
    """

    logical_name: str
    aliases: tuple[str, ...]
    display_name: str
    default_width: int
    hidden: bool = False


DEFAULT_COLUMN_SPECS: dict[str, ColumnSpec] = {
    "satellite": ColumnSpec(
        "satellite",
        (
            "satellite",
            "Satellite",
            "SatName",
            "Sat_Name",
            "Sat_ID",
            "sat_name",
            "satellite_id",
        ),
        "Satellite",
        140,
    ),
    "date_ut": ColumnSpec(
        "date_ut",
        (
            # Predictor CSVs must win over generic timestamp-like helpers.
            "Obs_Time",
            "obs_time",
            # Donor selector aliases.
            "Date [UT]",
            "date[UT]",
            "date_ut",
            # Fallback only.
            "timestamp",
        ),
        "Date [UT]",
        160,
    ),
    "ra": ColumnSpec(
        "ra",
        ("SatRA[hr]", "RA [hr]", "SatRA", "sat_ra", "ra", "RA"),
        "RA [hr]",
        100,
    ),
    "dec": ColumnSpec(
        "dec",
        ("SatDEC[deg]", "DEC [deg]", "SatDEC", "sat_dec", "dec", "DEC"),
        "DEC [deg]",
        100,
    ),
    "elev": ColumnSpec(
        "elev",
        (
            "elev",
            "SatElevation[deg]",
            "Elevation [deg]",
            "Elev. [deg]",
            "Elevation",
            "SatElev",
            "sat_elev",
        ),
        "Elev. [deg]",
        120,
    ),
    "solar_phase_angle": ColumnSpec(
        "solar_phase_angle",
        (
            "SolarPhaseAngle",
            "solar_phase_angle",
            "Solar Phase Angle",
            "Solar Phase Angle [deg]",
            "Solar Phase [deg]",
            "solar_phase_angle_deg",
        ),
        "Solar Phase [deg]",
        135,
    ),
    "az": ColumnSpec(
        "az",
        ("SatAz", "sat_az", "Az. [deg]", "Azimuth [deg]", "Azimuth"),
        "Az. [deg]",
        120,
    ),
    "satellite_altitude_km": ColumnSpec(
        "satellite_altitude_km",
        ("SatAlt", "sat_alt", "SatAlt[km]", "Altitude [km]"),
        "Sat. Alt. [km]",
        120,
    ),
    "satellite_distance_km": ColumnSpec(
        "satellite_distance_km",
        ("SatDist", "sat_dist", "SatDistance[km]", "Distance [km]"),
        "Sat. Dist. [km]",
        120,
    ),
    "solar_zenith_angle": ColumnSpec(
        "solar_zenith_angle",
        ("SunZenithAngle", "sun_zenith_angle", "Sun Zenith Angle"),
        "Sun Zenith [deg]",
        135,
    ),
    "local_time": ColumnSpec(
        "local_time",
        ("Local_Time", "local_time", "Local Time"),
        "Local Time",
        160,
    ),
    "satellite_longitude": ColumnSpec(
        "satellite_longitude",
        ("SatLon", "sat_lon", "SatLongitude", "Longitude [deg]"),
        "Sat. Lon. [deg]",
        120,
    ),
    "satellite_latitude": ColumnSpec(
        "satellite_latitude",
        ("SatLat", "sat_lat", "SatLatitude", "Latitude [deg]"),
        "Sat. Lat. [deg]",
        120,
    ),
    "sun_ra": ColumnSpec("sun_ra", ("SunRA", "sun_ra", "Sun RA"), "Sun RA", 100),
    "sun_dec": ColumnSpec("sun_dec", ("SunDEC", "sun_dec", "Sun DEC"), "Sun DEC", 100),
    "_checked": ColumnSpec("_checked", ("_checked",), "✓", 25),
    "date_ts": ColumnSpec("date_ts", ("date_ts",), "date_ts", 100, hidden=True),
    "global_index": ColumnSpec("global_index", ("global_index",), "global_index", 100, hidden=True),
    "base_index": ColumnSpec("base_index", ("base_index",), "base_index", 100, hidden=True),
    "local_index": ColumnSpec("local_index", ("local_index",), "local_index", 100, hidden=True),
}

REQUIRED_CANONICAL_FIELDS = (
    "satellite",
    "date_ut",
    "elev",
    "ra",
    "dec",
)


def default_donor_column_mapping() -> dict[str, dict[str, Any]]:
    """Return donor-compatible default column mapping.

    Returns
    -------
    dict
        Mapping from canonical field names to serializable mapping metadata.
    """
    return {
        logical: {
            "aliases": list(spec.aliases),
            "display": spec.display_name,
            "width": spec.default_width,
            "hidden": spec.hidden,
        }
        for logical, spec in DEFAULT_COLUMN_SPECS.items()
    }


def _coerce_aliases(value: Any) -> list[str]:
    """Return a clean alias list from a donor/integrated mapping value."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _extract_column_mapping(raw_mapping: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Extract donor ``visibility.columns`` mappings when present."""
    if not isinstance(raw_mapping, Mapping):
        return {}
    if "visibility" in raw_mapping and isinstance(raw_mapping.get("visibility"), Mapping):
        visibility = raw_mapping["visibility"]
        if isinstance(visibility.get("columns"), Mapping):
            return visibility["columns"]
    if "columns" in raw_mapping and isinstance(raw_mapping.get("columns"), Mapping):
        return raw_mapping["columns"]
    return raw_mapping


def normalize_column_mapping(raw_mapping: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Return a complete validated planner column mapping.

    Parameters
    ----------
    raw_mapping : mapping, optional
        Donor-style or integrated mapping.  Supported forms include
        ``{"visibility": {"columns": ...}}``, ``{"columns": ...}``, and
        direct ``{logical: config}`` mappings.  Values may be strings, alias
        lists, or dictionaries containing ``aliases``, ``display``, ``width``,
        and ``hidden``.

    Returns
    -------
    dict
        Complete serializable mapping merged with donor-compatible defaults.
    """
    merged = default_donor_column_mapping()
    raw_columns = _extract_column_mapping(raw_mapping)

    for logical, raw_config in raw_columns.items():
        logical_name = str(logical).strip()
        if not logical_name:
            continue
        base = dict(merged.get(logical_name, {
            "aliases": [logical_name],
            "display": logical_name,
            "width": 100,
            "hidden": False,
        }))

        if isinstance(raw_config, Mapping):
            if "aliases" in raw_config:
                aliases = _coerce_aliases(raw_config.get("aliases"))
                if aliases:
                    base["aliases"] = list(dict.fromkeys([*aliases, *base.get("aliases", [])]))
            elif "alias" in raw_config:
                aliases = _coerce_aliases(raw_config.get("alias"))
                if aliases:
                    base["aliases"] = list(dict.fromkeys([*aliases, *base.get("aliases", [])]))
            elif "column" in raw_config:
                aliases = _coerce_aliases(raw_config.get("column"))
                if aliases:
                    base["aliases"] = list(dict.fromkeys([*aliases, *base.get("aliases", [])]))
            if "display" in raw_config:
                base["display"] = str(raw_config.get("display") or logical_name)
            if "display_name" in raw_config:
                base["display"] = str(raw_config.get("display_name") or logical_name)
            if "width" in raw_config:
                try:
                    base["width"] = int(raw_config.get("width"))
                except Exception:
                    pass
            if "hidden" in raw_config:
                base["hidden"] = bool(raw_config.get("hidden"))
        else:
            aliases = _coerce_aliases(raw_config)
            if aliases:
                base["aliases"] = list(dict.fromkeys([*aliases, *base.get("aliases", [])]))

        # Keep the logical name itself available as a final fallback.
        aliases = list(dict.fromkeys([*base.get("aliases", []), logical_name]))
        base["aliases"] = aliases
        base["display"] = str(base.get("display", logical_name))
        try:
            base["width"] = max(20, int(base.get("width", 100)))
        except Exception:
            base["width"] = 100
        base["hidden"] = bool(base.get("hidden", False))
        merged[logical_name] = base

    missing = [field for field in REQUIRED_CANONICAL_FIELDS if field not in merged]
    if missing:
        raise ValueError(f"Column mapping is missing required logical fields: {missing}")
    return merged


def attach_column_mapping(frame: pd.DataFrame, column_mapping: Mapping[str, Any] | None) -> pd.DataFrame:
    """Attach normalized column mapping metadata to a DataFrame.

    Parameters
    ----------
    frame : pandas.DataFrame
        DataFrame to annotate.
    column_mapping : mapping, optional
        Mapping to normalize and attach.

    Returns
    -------
    pandas.DataFrame
        The same DataFrame instance, annotated via ``attrs``.
    """
    frame.attrs[COLUMN_MAPPING_ATTR] = normalize_column_mapping(column_mapping)
    return frame


def mapping_from_table(table: Any, column_mapping: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Return the effective mapping for a table-like object."""
    if column_mapping is not None:
        return normalize_column_mapping(column_mapping)
    attrs = getattr(table, "attrs", None)
    if isinstance(attrs, Mapping) and COLUMN_MAPPING_ATTR in attrs:
        return normalize_column_mapping(attrs[COLUMN_MAPPING_ATTR])
    return normalize_column_mapping(None)


def _columns_from_table(table: pd.DataFrame | pd.Series | Iterable[str]) -> list[str]:
    """Return column labels from a supported table-like object."""
    if isinstance(table, pd.DataFrame):
        return list(table.columns)
    if isinstance(table, pd.Series):
        return list(table.index)
    return list(table)


def resolve_column(
    table: pd.DataFrame | pd.Series | Iterable[str],
    logical_name: str,
    *,
    required: bool = True,
    column_mapping: Mapping[str, Any] | None = None,
) -> str | None:
    """Resolve a physical column name for a logical planner column.

    Parameters
    ----------
    table : pandas.DataFrame, pandas.Series, or iterable of str
        Table, row, or explicit column-label collection to inspect.
    logical_name : str
        Canonical logical column name.
    required : bool, optional
        If `True`, raise an error when unresolved.
    column_mapping : mapping, optional
        Explicit mapping.  If omitted, mapping stored in ``table.attrs`` is used
        before falling back to defaults.

    Returns
    -------
    str or None
        Matching physical column name or ``None`` if optional and unresolved.
    """
    mapping = mapping_from_table(table, column_mapping)
    if logical_name not in mapping:
        if required:
            raise KeyError(f"Unknown logical column '{logical_name}'.")
        return None

    columns = _columns_from_table(table)
    aliases = mapping[logical_name].get("aliases", [])
    for alias in aliases:
        if alias in columns:
            return alias

    if required:
        raise KeyError(
            f"No column found for logical '{logical_name}'. "
            f"Available columns: {columns}. Expected one of: {list(aliases)}."
        )
    return None


def resolve_columns(
    table: pd.DataFrame | pd.Series | Iterable[str],
    logical_names: Iterable[str],
    *,
    required: bool = True,
    column_mapping: Mapping[str, Any] | None = None,
) -> dict[str, str | None]:
    """Resolve multiple logical columns."""
    return {
        logical_name: resolve_column(
            table,
            logical_name,
            required=required,
            column_mapping=column_mapping,
        )
        for logical_name in logical_names
    }


def get_display_name(logical_name: str, column_mapping: Mapping[str, Any] | None = None) -> str:
    """Return the display label for a logical planner column."""
    mapping = normalize_column_mapping(column_mapping)
    if logical_name not in mapping:
        raise KeyError(f"Unknown logical column '{logical_name}'.")
    return str(mapping[logical_name].get("display", logical_name))


def get_default_width(logical_name: str, column_mapping: Mapping[str, Any] | None = None) -> int:
    """Return the default display width for a logical planner column."""
    mapping = normalize_column_mapping(column_mapping)
    if logical_name not in mapping:
        raise KeyError(f"Unknown logical column '{logical_name}'.")
    return int(mapping[logical_name].get("width", 100))


def is_hidden(logical_name: str, column_mapping: Mapping[str, Any] | None = None) -> bool:
    """Return whether a logical column is hidden by mapping metadata."""
    mapping = normalize_column_mapping(column_mapping)
    if logical_name not in mapping:
        raise KeyError(f"Unknown logical column '{logical_name}'.")
    return bool(mapping[logical_name].get("hidden", False))
