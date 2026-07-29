"""File loading utilities for the shared observation-planner core."""

from __future__ import annotations

import datetime as _dt
import json
import mimetypes
from pathlib import Path

import pandas as pd


def detect_visibility_file_type(path: str | Path) -> str:
    """Detect the supported visibility-file type from a file path.

    Parameters
    ----------
    path : str or pathlib.Path
        Visibility file path.

    Returns
    -------
    str
        One of ``"csv"``, ``"txt"``, or ``"json"``. Unknown extensions fall
        back to ``"txt"`` to preserve the selector loader behavior.
    """
    file_path = Path(path)
    ext = file_path.suffix.lstrip(".").lower()

    if not ext:
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type and "json" in mime_type:
            ext = "json"

    if ext == "csv":
        return "csv"
    if ext in {"txt", "tsv"}:
        return "txt"
    if ext == "json":
        return "json"
    return "txt"


def load_visibility_file(path: str | Path) -> pd.DataFrame:
    """Load a visibility-data table from CSV, TXT, or TSV.

    Parameters
    ----------
    path : str or pathlib.Path
        Path to the visibility-data file.

    Returns
    -------
    pandas.DataFrame
        Loaded visibility table.

    Raises
    ------
    ValueError
        If the detected file type is JSON, which is reserved for target files.
    """
    file_type = detect_visibility_file_type(path)
    if file_type == "csv":
        return pd.read_csv(path)
    if file_type == "txt":
        return pd.read_csv(path, sep="\t", engine="python")
    raise ValueError("JSON files are target-selection files, not visibility tables.")


def load_targets_json(path: str | Path) -> pd.DataFrame:
    """Load a selector-style JSON target file.

    Parameters
    ----------
    path : str or pathlib.Path
        JSON file containing a dictionary whose keys are satellite names and
        whose values are lists of time strings or empty lists.

    Returns
    -------
    pandas.DataFrame
        Flattened target table with columns ``satellite`` and ``datetime``.
        Invalid time strings are represented by ``None`` to preserve selector
        parsing behavior.

    Raises
    ------
    ValueError
        If the JSON root object is not a dictionary.
    """
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    if not isinstance(raw, dict):
        raise ValueError("Target JSON must contain a dictionary of satellite names to time lists.")

    flat: list[dict[str, object]] = []
    for satellite, times in raw.items():
        sat_name = str(satellite).strip()
        if times:
            for time_text in times:
                try:
                    parsed = _dt.datetime.strptime(str(time_text), "%Y %b %d %H:%M:%S")
                except ValueError:
                    parsed = None
                flat.append({"satellite": sat_name, "datetime": parsed})
        else:
            flat.append({"satellite": sat_name, "datetime": None})

    return pd.DataFrame(flat, columns=["satellite", "datetime"])
