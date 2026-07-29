"""Export formatting for observation-planner output tables."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .coordinate_format import COORD_FORMAT_COLON, format_coordinate_value
from .diagnostics import PlanGenerationDiagnostics, diagnostics_sidecar_path, write_diagnostics_json
from .schema import resolve_column


CSV_EXPORT_COLUMNS = ["Satellite", "Date", "Time", "RA", "DEC", "Elevation", "SolarPhaseAngle"]
TXT_EXPORT_HEADER = "# Satellite\tDate\tTime\tRA\tDEC\tElevation\tSolarPhaseAngle"


def _resolve_plan_date_column(plan_df: pd.DataFrame) -> str:
    """Resolve the best date column for export formatting."""
    if "datetime" in plan_df.columns:
        return "datetime"
    return resolve_column(plan_df, "date_ut")


def _resolve_plan_column(plan_df: pd.DataFrame, logical_name: str, *, required: bool = True) -> str | None:
    """Resolve a plan column while accepting internal plan-model names.

    The donor-compatible resolver is optimized for loaded visibility tables.
    Observation-plan rows are stored with internal logical names such as
    ``elev``.  Export must accept both shapes so the GUI table model and the
    future web backend can share the same helper.
    """
    if logical_name in plan_df.columns:
        return logical_name
    return resolve_column(plan_df, logical_name, required=required)


def _format_date_time(value: object) -> tuple[str, str]:
    """Format an observation timestamp in selector-compatible date/time fields."""
    try:
        timestamp = pd.to_datetime(value)
        date_text = timestamp.strftime("%Y %b %d")
        date_text = date_text.replace(timestamp.strftime("%b"), timestamp.strftime("%b").capitalize())
        time_text = timestamp.strftime("%H:%M:%S")
        return date_text, time_text
    except Exception:
        return str(value), ""




def _format_optional_float(value: object, precision: int = 2) -> str:
    """Format an optional numeric export value.

    Parameters
    ----------
    value : object
        Value to format.
    precision : int, optional
        Number of decimal places.

    Returns
    -------
    str
        Formatted numeric text, original text, or an empty string for nulls.
    """
    if pd.isna(value):
        return ""
    try:
        return f"{float(value):.{precision}f}"
    except Exception:
        return str(value)


def format_plan_for_csv(
    plan_df: pd.DataFrame,
    *,
    coordinate_format: str | None = COORD_FORMAT_COLON,
) -> pd.DataFrame:
    """Format a plan table for selector-compatible CSV export.

    Parameters
    ----------
    plan_df : pandas.DataFrame
        Observation plan table.
    coordinate_format : str or None, optional
        RA/DEC output-format identifier.

    Returns
    -------
    pandas.DataFrame
        Export table with columns ``Satellite, Date, Time, RA, DEC,
        Elevation, SolarPhaseAngle``.  ``SolarPhaseAngle`` is the integrated
        planner extension added after the donor export contract was ported.
    """
    satellite_col = _resolve_plan_column(plan_df, "satellite")
    date_col = _resolve_plan_date_column(plan_df)
    ra_col = _resolve_plan_column(plan_df, "ra")
    dec_col = _resolve_plan_column(plan_df, "dec")
    elev_col = _resolve_plan_column(plan_df, "elev")

    solar_phase_col = _resolve_plan_column(plan_df, "solar_phase_angle", required=False)

    rows = []
    for _, row in plan_df.iterrows():
        date_text, time_text = _format_date_time(row[date_col])
        rows.append(
            [
                row[satellite_col],
                date_text,
                time_text,
                format_coordinate_value(row[ra_col], coordinate_format),
                format_coordinate_value(row[dec_col], coordinate_format),
                row[elev_col],
                _format_optional_float(row[solar_phase_col]) if solar_phase_col is not None else "",
            ]
        )
    return pd.DataFrame(rows, columns=CSV_EXPORT_COLUMNS)


def format_plan_for_txt(
    plan_df: pd.DataFrame,
    *,
    coordinate_format: str | None = COORD_FORMAT_COLON,
) -> str:
    """Format a plan table for selector-compatible TXT export.

    Parameters
    ----------
    plan_df : pandas.DataFrame
        Observation plan table.
    coordinate_format : str or None, optional
        RA/DEC output-format identifier.

    Returns
    -------
    str
        Tab-separated text with selector-compatible header and rows.
    """
    satellite_col = _resolve_plan_column(plan_df, "satellite")
    date_col = _resolve_plan_date_column(plan_df)
    ra_col = _resolve_plan_column(plan_df, "ra")
    dec_col = _resolve_plan_column(plan_df, "dec")

    elev_col = _resolve_plan_column(plan_df, "elev")
    solar_phase_col = _resolve_plan_column(plan_df, "solar_phase_angle", required=False)

    lines = [TXT_EXPORT_HEADER]
    for _, row in plan_df.iterrows():
        date_text, time_text = _format_date_time(row[date_col])
        solar_phase = _format_optional_float(row[solar_phase_col]) if solar_phase_col is not None else ""
        lines.append(
            f"{row[satellite_col]}\t{date_text}\t{time_text}\t"
            f"{format_coordinate_value(row[ra_col], coordinate_format)}\t"
            f"{format_coordinate_value(row[dec_col], coordinate_format)}\t"
            f"{row[elev_col]}\t{solar_phase}"
        )
    return "\n".join(lines) + "\n"


def write_plan_csv(
    plan_df: pd.DataFrame,
    path: str | Path,
    *,
    coordinate_format: str | None = COORD_FORMAT_COLON,
) -> None:
    """Write a selector-compatible CSV observation plan.

    Parameters
    ----------
    plan_df : pandas.DataFrame
        Observation plan table.
    path : str or pathlib.Path
        Output CSV path.
    coordinate_format : str or None, optional
        RA/DEC output-format identifier.
    """
    format_plan_for_csv(plan_df, coordinate_format=coordinate_format).to_csv(path, index=False)


def write_plan_txt(
    plan_df: pd.DataFrame,
    path: str | Path,
    *,
    coordinate_format: str | None = COORD_FORMAT_COLON,
) -> None:
    """Write a selector-compatible TXT observation plan.

    Parameters
    ----------
    plan_df : pandas.DataFrame
        Observation plan table.
    path : str or pathlib.Path
        Output TXT path.
    coordinate_format : str or None, optional
        RA/DEC output-format identifier.
    """
    Path(path).write_text(format_plan_for_txt(plan_df, coordinate_format=coordinate_format), encoding="utf-8")


def write_plan_diagnostics_sidecar(
    diagnostics: PlanGenerationDiagnostics,
    plan_path: str | Path,
) -> Path:
    """Write the diagnostics JSON sidecar for an exported observation plan.

    Parameters
    ----------
    diagnostics : PlanGenerationDiagnostics
        Backend-generated diagnostics object.
    plan_path : str or pathlib.Path
        Main CSV/TXT plan export path.

    Returns
    -------
    pathlib.Path
        Sidecar JSON path.
    """
    sidecar = diagnostics_sidecar_path(plan_path)
    return write_diagnostics_json(diagnostics, sidecar)
