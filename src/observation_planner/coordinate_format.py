"""Coordinate display formatting helpers for observation-plan outputs.

The Observation Planner keeps raw plan records unchanged and applies these
helpers only at presentation/copy/export boundaries.
"""

from __future__ import annotations

import pandas as pd

COORD_FORMAT_COLON = "colon"
COORD_FORMAT_COMPACT = "compact"
_COORD_FORMATS = {COORD_FORMAT_COLON, COORD_FORMAT_COMPACT}


def normalize_coordinate_format(coordinate_format: str | None) -> str:
    """Return a supported coordinate-format identifier.

    Parameters
    ----------
    coordinate_format : str or None
        Requested coordinate-format identifier.

    Returns
    -------
    str
        ``"colon"`` for the current/default representation, or ``"compact"``
        for the separator-free representation.
    """
    normalized = str(coordinate_format or COORD_FORMAT_COLON).strip().lower()
    if normalized in _COORD_FORMATS:
        return normalized
    return COORD_FORMAT_COLON


def format_coordinate_value(value: object, coordinate_format: str | None = COORD_FORMAT_COLON) -> str:
    """Format one RA/DEC value for display, copy, or export.

    Compact formatting removes colon separators only.  It intentionally
    preserves signs, decimals, leading zeroes, and all non-colon characters so
    the helper remains a presentation transform rather than a coordinate parser.

    Parameters
    ----------
    value : object
        Raw coordinate value from an observation-plan record or DataFrame.
    coordinate_format : str or None, optional
        Coordinate-format identifier.  Unsupported values fall back to colon
        mode.

    Returns
    -------
    str
        Formatted coordinate text.
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass

    text = str(value)
    if normalize_coordinate_format(coordinate_format) == COORD_FORMAT_COMPACT:
        return text.replace(":", "")
    return text
