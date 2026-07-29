from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from astropy.coordinates import EarthLocation, AltAz, get_sun
from astropy.time import Time


def process_results(results, mode, constraints=None, location=None):
    """
    Process prediction results based on the mode (overpass, precise, planner).

    Parameters:
        results (pd.DataFrame): Raw prediction results.
        mode (str): Prediction mode ('overpass', 'precise', or 'planner').
        constraints (dict): Optional constraints for filtering.
        location (EarthLocation): Observer's location for solar position calculations.

    Returns:
        pd.DataFrame: Processed results ready for display or export.
    """

    if results is None or results.empty:
        return results
    if mode == "overpass":
        return process_overpass_results(results, location)
    elif mode == "precise":
        return process_precise_results(results, constraints, location)
    elif mode == "planner":
        return process_planner_results(results, constraints)
    else:
        raise ValueError(f"Unsupported mode: {mode}")

#
# def process_overpass_results(results, location):
#     """
#     Process overpass results with optimizations for large datasets.
#     """
#     time_column = "max_time_utc"  # Always known for overpass
#     df = process_in_chunks(results, add_solar_phase_columns, time_column, location)
#
#     # Drop duplicates and sort efficiently
#     df.drop_duplicates([time_column], inplace=True)
#     df.sort_values(by=["Sat_ID", time_column], inplace=True)
#
#     return df
#     # # For small datasets, use the direct approach
#     # if len(results) < 1000:
#     #     return _process_overpass_direct(results, location)
#     #
#     # # For larger datasets, use chunked processing
#     # return _process_overpass_chunked(results, location)
#

# def process_precise_results(results, constraints, location):
#     """Filter and sort precise prediction results."""
#
#     time_column = "Obs_Time"  # Always known for precise mode
#     df = process_in_chunks(results, add_solar_phase_columns, time_column, location)
#
#     if constraints:
#         df = apply_constraints(df, constraints)
#
#     # Sort by Sat_ID and Obs_Time
#     return df.sort_values(by=["Sat_ID", time_column]).reset_index(drop=True)


def process_planner_results(results, constraints=None):
    """Filter and format data for the observation planner."""
    if constraints:
        results = apply_constraints(results, constraints)
    return results.sort_values(by=["obs_time"]).reset_index(drop=True)


# def process_in_chunks(df, processor_fn, *args):
#     """
#     Process a DataFrame in chunks using a specified processing function.
#
#     Parameters:
#         df (pd.DataFrame): The DataFrame to process.
#         processor_fn (callable): Function to process each chunk.
#         *args: Additional arguments to pass to the processor function.
#
#
#     Returns:
#         pd.DataFrame: Concatenated results from all processed chunks.
#     """
#     # Create chunks of the dataframe
#     chunk_size = min(1000, max(100, len(df) // 10))  # Adjust chunk size based on data size
#     chunks = [df.iloc[i:i + chunk_size].copy() for i in range(0, len(df), chunk_size)]
#
#     # Process chunks in parallel
#     with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as executor:
#         processed_chunks = list(executor.map(lambda x: processor_fn(x, *args), chunks))
#
#     # Combine results
#     combined_results = pd.concat(processed_chunks, ignore_index=False)
#
#     return combined_results
#
#     # processed_chunks = []
#     # for start in range(0, len(df), chunk_size):
#     #     chunk = df.iloc[start:start + chunk_size].copy()
#     #     processed_chunk = processor_fn(chunk, *args)
#     #     processed_chunks.append(processed_chunk)
#     #
#     # return pd.concat(processed_chunks, ignore_index=True)

def process_overpass_results(results, location):
    """
    Process overpass results with optimizations for large datasets.
    Note: add_solar_phase_columns is called once (serially) after chunk processing
    to avoid calling Astropy/ERFA inside worker threads.
    """
    time_column = "max_time_utc"  # Always known for overpass

    # Process chunks WITHOUT running Astropy-time / transforms per-thread.
    # Pass processor_fn=None (identity) so threads only do light work (if any).
    df = process_in_chunks(results, processor_fn=None)

    # Now call the (Astropy-using) function once in the main thread.
    # This is the critical change to avoid ERFA/Astropy segfaults in threads.
    df = add_solar_phase_columns(df, time_column, location)

    # Drop duplicates and sort efficiently
    df = df.drop_duplicates([time_column]).sort_values(by=["Sat_ID", time_column]).reset_index(drop=True)

    return df


def process_precise_results(results, constraints, location):
    """Filter and sort precise prediction results.

    Precise rows produced by the shared backend already contain
    ``time_of_day`` and ``light_phase`` labels.  In that fast path, this
    function must not call ``add_solar_phase_columns`` again because that would
    repeat the expensive Astropy solar AltAz pass.  The fallback remains for
    older precise rows that do not yet provide the labels.
    """
    time_column = "Obs_Time"  # Always known for precise mode

    # As above: avoid calling Astropy inside thread workers.
    df = process_in_chunks(results, processor_fn=None)

    has_phase_columns = {"time_of_day", "light_phase"}.issubset(df.columns)
    if not has_phase_columns:
        # Fallback for legacy precise rows without backend-derived phase labels.
        df = add_solar_phase_columns(df, time_column, location)

    if constraints:
        df = apply_constraints(df, constraints)

    # Sort by Sat_ID and Obs_Time
    return df.sort_values(by=["Sat_ID", time_column]).reset_index(drop=True)


def process_in_chunks(df, processor_fn=None, *, chunk_size=None, max_workers=8):
    """
    Process a DataFrame in chunks. Runs 'processor_fn' per-chunk if provided,
    otherwise concatenates chunks unchanged.

    Parameters
    ----------
    df : pandas.DataFrame
        The DataFrame to process.
    processor_fn : callable | None
        Function(chunk_df) -> processed_chunk_df. If None, chunk is returned unchanged.
        IMPORTANT: do NOT pass functions that call astropy.Time or other ERFA code
        when using ThreadPoolExecutor; instead keep processor_fn thread-safe.
    chunk_size : int | None
        Number of rows per chunk. If None an adaptive default is used.
    max_workers : int
        Max threads for ThreadPoolExecutor.

    Returns
    -------
    pandas.DataFrame
        Concatenated results from all processed chunks (ignore_index=True).
    """
    import math
    import pandas as pd
    from concurrent.futures import ThreadPoolExecutor

    if df is None or len(df) == 0:
        return df.copy()

    # adaptive chunk size if not provided
    if chunk_size is None:
        chunk_size = min(1000, max(100, len(df) // 10))

    # create chunk slices
    indices = list(range(0, len(df), chunk_size))
    chunks = [df.iloc[i:i + chunk_size].copy() for i in indices]

    # choose a safe per-chunk worker
    def _identity(chunk):
        return chunk

    worker_fn = processor_fn if processor_fn is not None else _identity

    # run chunk processing in threads (but worker_fn should be thread-safe)
    n_workers = min(max_workers, max(1, len(chunks)))
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        processed_chunks = list(executor.map(worker_fn, chunks))

    # Combine results into a single DataFrame (reindex to avoid duplicate indices)
    combined_results = pd.concat(processed_chunks, ignore_index=True)

    return combined_results

# def add_solar_phase_columns(df, time_column, location):
#     """Add solar phase and time of day columns to the DataFrame based on solar position.
#     Parameters:
#         df (pd.DataFrame): DataFrame containing observation times.
#         time_column (str): Column name with observation times in ISO format.
#         location (EarthLocation): Observer's location for solar position calculations.
#
#     Returns:
#         pd.DataFrame: DataFrame with added 'time_of_day' and 'light_phase' columns.
#     """
#     obs_times = pd.to_datetime(df[time_column])
#     print(f"Calculating solar positions for {len(obs_times)} observation times...")
#     print(obs_times)
#     obs_times_utc = Time(obs_times.apply(lambda x: x.isoformat()).tolist())
#     print(obs_times_utc)
#     altaz_frame = AltAz(obstime=obs_times_utc, location=location)
#     sun_altaz = get_sun(obs_times_utc).transform_to(altaz_frame)
#
#     solar_elevations = sun_altaz.alt.degree
#     solar_azimuths = sun_altaz.az.degree
#
#     # Pre-allocate result arrays
#     time_of_day = np.empty(len(df), dtype=object)
#     light_phase = np.empty(len(df), dtype=object)
#
#     # Vectorized categorization using NumPy masks
#     light_phase[(solar_elevations >= 0)] = 'Daytime'
#     light_phase[(solar_elevations < 0) & (solar_elevations >= -6)] = 'Civil Twilight'
#     light_phase[(solar_elevations < -6) & (solar_elevations >= -12)] = 'Nautical Twilight'
#     light_phase[(solar_elevations < -12) & (solar_elevations >= -18)] = 'Astronomical Twilight'
#     light_phase[(solar_elevations < -18)] = 'Night'
#
#     time_of_day[(solar_elevations < 0) & (solar_elevations >= -18) & (solar_azimuths < 180)] = 'Morning'
#     time_of_day[(solar_elevations >= 0)] = 'Day'
#     time_of_day[(solar_elevations < 0) & (solar_elevations >= -18) & (solar_azimuths >= 180)] = 'Evening'
#     time_of_day[(solar_elevations < -18) | ((solar_elevations < 0) & ~(
#             ((solar_elevations >= -18) & (solar_azimuths < 180)) |
#             ((solar_elevations >= -18) & (solar_azimuths >= 180))
#     ))] = 'Night'
#
#     # Assign the results
#     df['time_of_day'] = time_of_day
#     df['light_phase'] = light_phase
#
#     return df

def add_solar_phase_columns(df, time_column, location):
    """
    Add solar phase / time-of-day labels to a results DataFrame.

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame containing observation times.
    time_column : str
        Column name with observation times (pandas-compatible datetime values).
        Values are interpreted as UTC unless timezone-aware timestamps are provided.
    location : astropy.coordinates.EarthLocation
        Observer location used for AltAz transforms.

    Returns
    -------
    pandas.DataFrame
        The same DataFrame with two new columns:
        - 'time_of_day' : {'Morning','Day','Evening','Night'}
        - 'light_phase'  : {'Daytime','Civil Twilight','Nautical Twilight',
                           'Astronomical Twilight','Night','Unknown'}
    """
    import logging
    import datetime
    import numpy as np
    import pandas as pd
    from astropy.time import Time
    from astropy.coordinates import AltAz, get_sun

    log = logging.getLogger(__name__)

    # Convert to pandas datetime index/series (do this deterministically here,
    # not inside many threads). Ensure we have python datetimes with UTC tzinfo.
    times_pd = pd.to_datetime(df[time_column], utc=False, errors='coerce')

    # Build list of timezone-aware python datetimes in UTC
    py_datetimes = []
    for ts in times_pd:
        if pd.isna(ts):
            py_datetimes.append(None)
            continue
        # ts is a pandas.Timestamp
        py_dt = ts.to_pydatetime()
        if py_dt.tzinfo is None:
            # treat naive timestamps as UTC (explicit)
            py_dt = py_dt.replace(tzinfo=datetime.timezone.utc)
        else:
            py_dt = py_dt.astimezone(datetime.timezone.utc)
        py_datetimes.append(py_dt)

    try:
        # Construct a single Time object (vectorized) - do this in a single thread
        obs_times_utc = Time(py_datetimes, scale='utc')
        altaz_frame = AltAz(obstime=obs_times_utc, location=location)
        sun_altaz = get_sun(obs_times_utc).transform_to(altaz_frame)

        # Use .deg for the Quantity -> numpy array
        solar_elevations = np.array(sun_altaz.alt.deg)
        solar_azimuths = np.array(sun_altaz.az.deg)

    except Exception as exc:
        # If Astropy fails, avoid crashing the whole worker.
        log.exception("Failed to compute solar positions: %s", exc)
        n = len(df)
        # fallback arrays (all unknown/night)
        solar_elevations = np.full(n, -999.0, dtype=float)
        solar_azimuths = np.full(n, 0.0, dtype=float)

    n = len(df)
    # defaults
    time_of_day = np.full(n, 'Night', dtype=object)
    light_phase = np.full(n, 'Unknown', dtype=object)

    # Masks (use safe comparisons)
    m_day = solar_elevations >= 0.0
    m_civil = (solar_elevations < 0.0) & (solar_elevations >= -6.0)
    m_nautical = (solar_elevations < -6.0) & (solar_elevations >= -12.0)
    m_astro = (solar_elevations < -12.0) & (solar_elevations >= -18.0)
    m_night = solar_elevations < -18.0

    light_phase[m_day] = 'Daytime'
    light_phase[m_civil] = 'Civil Twilight'
    light_phase[m_nautical] = 'Nautical Twilight'
    light_phase[m_astro] = 'Astronomical Twilight'
    light_phase[m_night] = 'Night'

    # Time of day:
    # - Day (sun above horizon)
    # - Morning / Evening when below horizon but within -18 .. 0 and AZ < / >= 180
    # - Night otherwise (including cases where elevation is very negative)
    time_of_day[m_day] = 'Day'

    m_twilight = (solar_elevations < 0.0) & (solar_elevations >= -18.0)
    m_morning = m_twilight & (solar_azimuths < 180.0)
    m_evening = m_twilight & (solar_azimuths >= 180.0)

    time_of_day[m_morning] = 'Morning'
    time_of_day[m_evening] = 'Evening'

    # Assign to DataFrame (preserve index)
    df = df.copy()
    df['time_of_day'] = time_of_day
    df['light_phase'] = light_phase

    return df

def _process_overpass_direct(results, location):
    """Optimized direct processing for smaller datasets"""
    # Convert datetimes efficiently
    obs_times = pd.to_datetime(results["max_time_utc"])

    # Use vectorized string conversion - faster than list comprehension
    obs_times_utc = Time(obs_times.apply(lambda x: x.isoformat()).tolist())

    # Create AltAz frame and get sun positions
    altaz_frame = AltAz(obstime=obs_times_utc, location=location)
    sun_altaz = get_sun(obs_times_utc).transform_to(altaz_frame)

    # Use NumPy arrays for faster operations
    solar_elevations = sun_altaz.alt.degree
    solar_azimuths = sun_altaz.az.degree

    # Pre-allocate result arrays
    time_of_day = np.empty(len(results), dtype=object)
    light_phase = np.empty(len(results), dtype=object)

    # Vectorized categorization using NumPy masks
    # Light phase determination
    light_phase[(solar_elevations >= 0)] = 'Daytime'
    light_phase[(solar_elevations < 0) & (solar_elevations >= -6)] = 'Civil Twilight'
    light_phase[(solar_elevations < -6) & (solar_elevations >= -12)] = 'Nautical Twilight'
    light_phase[(solar_elevations < -12) & (solar_elevations >= -18)] = 'Astronomical Twilight'
    light_phase[(solar_elevations < -18)] = 'Night'

    # Time of day determination
    time_of_day[(solar_elevations < 0) & (solar_elevations >= -18) & (solar_azimuths < 180)] = 'Morning'
    time_of_day[(solar_elevations >= 0)] = 'Day'
    time_of_day[(solar_elevations < 0) & (solar_elevations >= -18) & (solar_azimuths >= 180)] = 'Evening'
    time_of_day[(solar_elevations < -18) | ((solar_elevations < 0) & ~(
            ((solar_elevations >= -18) & (solar_azimuths < 180)) |
            ((solar_elevations >= -18) & (solar_azimuths >= 180))
    ))] = 'Night'

    # Assign the results
    results['time_of_day'] = time_of_day
    results['light_phase'] = light_phase

    # Drop duplicates and sort efficiently
    results.drop_duplicates(['max_time_utc'], inplace=True)
    results.sort_values(by=["Sat_ID", "max_time_utc"], inplace=True)

    return results


def _process_chunk(chunk, location):
    """Process a chunk of data"""
    return _process_overpass_direct(chunk, location)


def _process_overpass_chunked(results, location):
    """Process large datasets in chunks with parallel execution"""
    # Create chunks of the dataframe
    chunk_size = min(1000, max(100, len(results) // 10))  # Adjust chunk size based on data size
    chunks = [results.iloc[i:i + chunk_size].copy() for i in range(0, len(results), chunk_size)]

    # Process chunks in parallel
    with ThreadPoolExecutor(max_workers=min(8, len(chunks))) as executor:
        processed_chunks = list(executor.map(lambda chunk: _process_chunk(chunk, location), chunks))

    # Combine results
    combined_results = pd.concat(processed_chunks, ignore_index=False)

    # Final deduplication and sorting
    combined_results.drop_duplicates(['max_time_utc'], inplace=True)
    combined_results.sort_values(by=["Sat_ID", "max_time_utc"], inplace=True)

    return combined_results


def apply_constraints(results, constraints):
    """Filter results based on visibility constraints."""
    lowest_altitude = constraints.get("lowest_altitude_satellite", 30)
    sun_zenith_highest = constraints.get("sun_zenith_highest", 112)
    sun_zenith_lowest = constraints.get("sun_zenith_lowest", 99)

    return results[
        (results["SatElev"] >= lowest_altitude) &
        (results["SunZenithAngle"] >= sun_zenith_lowest) &
        (results["SunZenithAngle"] <= sun_zenith_highest)
        ]

