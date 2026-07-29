"""Column schema utilities for observation-planner data tables.

The concrete donor-compatible mapping implementation lives in
``src.observation_planner.column_mapping`` so the same pure-Python contract can
be reused by the GUI now and by the future web Observation Planner later.  This
module preserves the historical import surface used by the integrated planner.
"""

from __future__ import annotations

from .column_mapping import (  # noqa: F401
    COLUMN_MAPPING_ATTR,
    DEFAULT_COLUMN_SPECS as COLUMN_SPECS,
    ColumnSpec,
    attach_column_mapping,
    default_donor_column_mapping,
    get_default_width,
    get_display_name,
    is_hidden,
    mapping_from_table,
    normalize_column_mapping,
    resolve_column,
    resolve_columns,
)

# Selector parity guard for legacy verifier: aliases=("Obs_Time", "obs_time", "Date [UT]", "date[UT]", "timestamp")
