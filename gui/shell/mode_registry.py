"""Stable mode identifiers for the GUI dashboard shell.

The dashboard shell uses these internal identifiers for all mode routing.  Visible
labels may change without changing behavior, exports, or planner handoff logic.
"""

from __future__ import annotations

MODE_OVERPASS = "overpass"
MODE_PRECISE = "precise"
MODE_PLANNER = "planner"

PREDICTION_MODES = frozenset((MODE_OVERPASS, MODE_PRECISE))
ALL_MODES = (MODE_OVERPASS, MODE_PRECISE, MODE_PLANNER)


__all__ = [
    "ALL_MODES",
    "MODE_OVERPASS",
    "MODE_PLANNER",
    "MODE_PRECISE",
    "PREDICTION_MODES",
]
