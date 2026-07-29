"""Normalization and filtering utilities for observation-planner tables."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .schema import attach_column_mapping, mapping_from_table, resolve_column


ALL_SATELLITES_LABEL = "All Satellites"


def _resolve_authoritative_time_column(df: pd.DataFrame, column_mapping=None) -> str:
    """Return the selector-authoritative UTC observation-time column.

    The standalone selector derives ``date_ts`` from the visible UTC
    observation time.  For predictor CSVs this is ``Obs_Time``; for selector
    files this is ``Date [UT]``/``date[UT]``.  Generic helpers such as
    ``timestamp`` are fallback only and must never override ``Obs_Time``.
    """
    preferred_aliases = (
        "Obs_Time",
        "obs_time",
        "Date [UT]",
        "date[UT]",
        "timestamp",
    )
    columns = list(df.columns)
    for alias in preferred_aliases:
        if alias in columns:
            return alias
    return resolve_column(df, "date_ut", column_mapping=column_mapping)


def _numeric_epoch_seconds(values: pd.Series) -> pd.Series:
    """Convert numeric epoch values with unit detection to seconds.

    Values with ambiguous small magnitudes are rejected instead of being plotted
    near 1970.  A correct modern epoch second timestamp is expected to be of
    order 1e9; millisecond/microsecond/nanosecond values are scaled down.
    """
    numeric = pd.to_numeric(values, errors="coerce")
    result = pd.Series(np.nan, index=values.index, dtype="float64")
    finite = numeric.notna() & np.isfinite(numeric)
    if not finite.any():
        return result

    abs_values = numeric.abs()
    seconds = finite & (abs_values >= 1.0e9) & (abs_values < 1.0e11)
    milliseconds = finite & (abs_values >= 1.0e11) & (abs_values < 1.0e14)
    microseconds = finite & (abs_values >= 1.0e14) & (abs_values < 1.0e17)
    nanoseconds = finite & (abs_values >= 1.0e17)

    result.loc[seconds] = numeric.loc[seconds]
    result.loc[milliseconds] = numeric.loc[milliseconds] / 1.0e3
    result.loc[microseconds] = numeric.loc[microseconds] / 1.0e6
    result.loc[nanoseconds] = numeric.loc[nanoseconds] / 1.0e9
    return result


def _datetime_series_to_epoch_seconds(timestamps_utc: pd.Series) -> pd.Series:
    """Convert parsed UTC datetimes to epoch seconds with fixed ns precision.

    The standalone selector used ``astype("int64") // 10**9`` on pandas
    datetime values.  That works when pandas stores datetimes as nanoseconds,
    but newer pandas versions may preserve millisecond resolution for strings
    such as ``2026-05-22T23:18:57.000``.  In that case ``astype("int64")``
    returns milliseconds and an unconditional division by ``1e9`` produces
    values near ``1.779e6``, which plotting time axes display as 1970.

    Force the parsed UTC values to ``datetime64[ns]`` before integer conversion
    so the GUI planner has the same epoch-second contract independently of the
    pandas datetime storage resolution.
    """
    result = pd.Series(np.nan, index=timestamps_utc.index, dtype="float64")
    valid = timestamps_utc.notna()
    if not valid.any():
        return result

    valid_timestamps = timestamps_utc.loc[valid]
    try:
        # Convert timezone-aware UTC timestamps to naive UTC first, then force
        # nanosecond precision.  ``to_numpy(dtype="datetime64[ns]")`` is the
        # important selector-parity guard against pandas millisecond dtypes.
        naive_utc = valid_timestamps.dt.tz_convert("UTC").dt.tz_localize(None)
    except (AttributeError, TypeError):
        naive_utc = valid_timestamps

    epoch_ns = naive_utc.to_numpy(dtype="datetime64[ns]").astype("int64")
    result.loc[valid_timestamps.index] = epoch_ns.astype("float64") / 1.0e9
    return result


def _parse_observation_time_to_epoch_seconds(values: pd.Series) -> pd.Series:
    """Parse observation times into canonical UTC epoch seconds.

    Numeric timestamp inputs are interpreted with explicit unit detection.
    String datetime inputs are parsed as UTC, using pandas' mixed-format parser
    when available so predictor ISO strings and selector-style strings are both
    accepted.  Parsed datetimes are normalized to nanosecond precision before
    integer conversion to avoid pandas-version-dependent millisecond scaling.
    """
    if pd.api.types.is_numeric_dtype(values):
        return _numeric_epoch_seconds(values)

    stripped = values.astype(str).str.strip()
    numeric_candidate = pd.to_numeric(stripped, errors="coerce")
    numeric_mask = numeric_candidate.notna()
    result = pd.Series(np.nan, index=values.index, dtype="float64")
    if numeric_mask.any():
        result.loc[numeric_mask] = _numeric_epoch_seconds(stripped.loc[numeric_mask])

    text_mask = ~numeric_mask & stripped.notna() & (stripped != "") & (stripped.str.lower() != "nan")
    if text_mask.any():
        try:
            timestamps_utc = pd.to_datetime(
                stripped.loc[text_mask],
                errors="coerce",
                utc=True,
                format="mixed",
            )
        except TypeError:
            timestamps_utc = pd.to_datetime(stripped.loc[text_mask], errors="coerce", utc=True)

        epoch_seconds = _datetime_series_to_epoch_seconds(timestamps_utc)
        result.loc[epoch_seconds.index] = epoch_seconds
    return result


def clean_satellite_name(value: object) -> str:
    """Return a selector-compatible cleaned satellite name.

    Parameters
    ----------
    value : object
        Satellite identifier or display name.

    Returns
    -------
    str
        String value stripped of surrounding whitespace and a trailing
        ``-ID-<digits>`` suffix when present.
    """
    return re.sub(r"-ID-\d+$", "", str(value)).strip()


def prepare_visibility_dataframe(df: pd.DataFrame, column_mapping=None) -> pd.DataFrame:
    """Prepare visibility data with selector-compatible helper columns.

    Parameters
    ----------
    df : pandas.DataFrame
        Raw visibility table using either selector-style or predictor-style
        column names.

    Returns
    -------
    pandas.DataFrame
        Prepared copy with ``_checked``, ``date_ts``, and ``global_index``
        present.

    Raises
    ------
    KeyError
        If the observation time column cannot be resolved.
    """
    prepared = df.copy()
    effective_mapping = mapping_from_table(df, column_mapping)
    attach_column_mapping(prepared, effective_mapping)

    if "_checked" not in prepared.columns:
        prepared.insert(0, "_checked", False)

    # Always rebuild the helper timestamp from the authoritative observation
    # time column.  CSV files exported by earlier planner/predictor versions may
    # contain a stale ``date_ts`` helper with the wrong unit scale.  Reusing such
    # a column makes the plot time axis display dates around 1970 even though the
    # visible ``Date [UT]``/``Obs_Time`` column is correct.
    date_col = _resolve_authoritative_time_column(prepared, effective_mapping)

    # Drop existing helper columns before assignment.  This protects the plot
    # from duplicate ``date_ts`` labels and from stale helper values exported by
    # earlier development builds.
    if "date_ts" in prepared.columns:
        prepared = prepared.drop(columns=["date_ts"])

    prepared["date_ts"] = _parse_observation_time_to_epoch_seconds(prepared[date_col])

    valid_timestamps = pd.to_numeric(prepared["date_ts"], errors="coerce")
    if valid_timestamps.notna().sum() == 0:
        raise ValueError(
            "No valid UTC observation timestamps found for Observation Planner plot. "
            f"Tried column '{date_col}'."
        )

    finite_timestamps = valid_timestamps[np.isfinite(valid_timestamps)]
    if not finite_timestamps.empty and float(finite_timestamps.median()) < 1.0e9:
        raise ValueError(
            "Observation timestamps are not valid epoch seconds for plotting. "
            f"Median date_ts={float(finite_timestamps.median()):.3f}; source column='{date_col}'."
        )

    prepared["global_index"] = range(len(prepared))
    attach_column_mapping(prepared, effective_mapping)
    return prepared


def make_base_and_view(data_master: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Create selector-compatible base and view tables from master data.

    Parameters
    ----------
    data_master : pandas.DataFrame
        Prepared master visibility table.

    Returns
    -------
    tuple of pandas.DataFrame
        ``(data_base, data_view)`` where ``base_index`` and ``local_index`` are
        reset as in the selector workflow.
    """
    effective_mapping = mapping_from_table(data_master)
    data_base = data_master.copy().reset_index(drop=True)
    attach_column_mapping(data_base, effective_mapping)
    data_base["base_index"] = range(len(data_base))

    data_view = data_base.copy().reset_index(drop=True)
    attach_column_mapping(data_view, effective_mapping)
    data_view["local_index"] = range(len(data_view))
    return data_base, data_view


def filter_by_targets(
    data_master: pd.DataFrame,
    targets_df: pd.DataFrame | None,
    *,
    apply_targets: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filter master visibility rows by loaded target names.

    Parameters
    ----------
    data_master : pandas.DataFrame
        Prepared master visibility table.
    targets_df : pandas.DataFrame or None
        Target table with a satellite-name column.
    apply_targets : bool
        If `True`, apply the target filter. If `False`, restore the full master
        table.

    Returns
    -------
    tuple of pandas.DataFrame
        ``(data_base, data_view)`` after target filtering and index reset.

    Notes
    -----
    Phase 1 intentionally preserves the selector's case-insensitive substring
    matching behavior. This is isolated here so stricter matching can be
    reviewed separately later.
    """
    effective_mapping = mapping_from_table(data_master)
    if apply_targets and targets_df is not None:
        target_col = resolve_column(targets_df, "satellite", column_mapping=effective_mapping)
        satellite_col = resolve_column(data_master, "satellite", column_mapping=effective_mapping)
        target_names = targets_df[target_col].astype(str).str.strip().str.upper().unique()

        if len(target_names) == 0:
            data_base = data_master.iloc[0:0].copy().reset_index(drop=True)
            attach_column_mapping(data_base, effective_mapping)
        else:
            pattern = "|".join(map(re.escape, target_names))
            mask = data_master[satellite_col].astype(str).str.upper().str.contains(pattern, na=False)
            data_base = data_master[mask].copy().reset_index(drop=True)
            attach_column_mapping(data_base, effective_mapping)
    else:
        data_base = data_master.copy().reset_index(drop=True)
        attach_column_mapping(data_base, effective_mapping)

    data_base["base_index"] = range(len(data_base))
    data_view = data_base.copy().reset_index(drop=True)
    attach_column_mapping(data_view, effective_mapping)
    data_view["local_index"] = range(len(data_view))
    return data_base, data_view


def filter_by_satellite(data_base: pd.DataFrame, satellite_filter: str) -> pd.DataFrame:
    """Filter a base visibility table by one satellite name.

    Parameters
    ----------
    data_base : pandas.DataFrame
        Base visibility table.
    satellite_filter : str
        Satellite name to select, or ``"All Satellites"`` for no filtering.

    Returns
    -------
    pandas.DataFrame
        View table with ``local_index`` reset.
    """
    effective_mapping = mapping_from_table(data_base)
    if satellite_filter == ALL_SATELLITES_LABEL:
        data_view = data_base.copy().reset_index(drop=True)
    else:
        satellite_col = resolve_column(data_base, "satellite", column_mapping=effective_mapping)
        data_view = data_base[data_base[satellite_col] == satellite_filter].copy().reset_index(drop=True)

    attach_column_mapping(data_view, effective_mapping)
    data_view["local_index"] = range(len(data_view))
    return data_view
