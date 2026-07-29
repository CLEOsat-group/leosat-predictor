"""Shared precise prediction materialization utilities.

This module owns the canonical precise-prediction row contracts and the
vectorized Astropy materialization step used by both the desktop GUI shared
backend and the web backend.  It deliberately has no Flask, Redis, GUI, or
route dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import logging
from typing import Any


_LOGGER = logging.getLogger(__name__)


GEOMETRY_COLUMNS: list[str] = [
    "SatName",
    "ObsTime",
    "SatAz",
    "SatElev",
    "SatLon",
    "SatLat",
    "SatAlt",
    "DistKm",
]

COLUMN_ORDER_PRECISE_BASE: list[str] = [
    "Sat_ID",
    "Obs_Time",
    "Local_Time",
    "UT_Date",
    "UT_time",
    "SatRA",
    "SatDEC",
    "SatAz",
    "SatElev",
    "SatAlt",
    "SatDist",
    "SunRA",
    "SunDEC",
    "SunZenithAngle",
    "RA",
    "DEC",
    "SatLon",
    "SatLat",
]

COLUMN_ORDER_PRECISE_WITH_PHASE: list[str] = [
    *COLUMN_ORDER_PRECISE_BASE,
    "time_of_day",
    "light_phase",
]

_SAT_ELEV_INDEX = COLUMN_ORDER_PRECISE_BASE.index("SatElev") + 1

COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE: list[str] = [
    *COLUMN_ORDER_PRECISE_BASE[:_SAT_ELEV_INDEX],
    "SolarPhaseAngle",
    *COLUMN_ORDER_PRECISE_BASE[_SAT_ELEV_INDEX:],
]

COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE_AND_LABELS: list[str] = [
    *COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE,
    "time_of_day",
    "light_phase",
]

# Canonical current internal precise result contract.  The base 18-column
# contract and the Task-25 20-column label contract are still accepted by
# readers via ``infer_precise_column_order``.
COLUMN_ORDER_PRECISE: list[str] = COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE_AND_LABELS

# Public/default precise CSV export contract.  The backend keeps derived
# twilight labels internally for performance, but the official scientific
# precise export adds only ``SolarPhaseAngle`` to the legacy web-facing schema.
COLUMN_ORDER_PRECISE_EXPORT: list[str] = COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE


def infer_precise_column_order(record: Sequence[Any] | None) -> list[str] | None:
    """Infer the precise result column order from a raw row length.

    Parameters
    ----------
    record : Sequence[Any] | None
        Raw precise row.  The function only inspects ``len(record)`` and does
        not mutate or interpret the values.

    Returns
    -------
    list[str] | None
        ``COLUMN_ORDER_PRECISE_BASE`` for the legacy 18-column contract,
        ``COLUMN_ORDER_PRECISE_WITH_PHASE`` for the Task-25 20-column label
        contract, ``COLUMN_ORDER_PRECISE`` for the current 21-column internal
        contract, or ``None`` when the row length is not a recognized precise
        materialization contract. The 19-column public export contract is a
        projection target, not a raw materialization input contract.
    """
    if record is None:
        return None

    try:
        record_length = len(record)
    except TypeError:
        return None

    if record_length == len(COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE_AND_LABELS):
        return COLUMN_ORDER_PRECISE_WITH_SOLAR_PHASE_AND_LABELS
    if record_length == len(COLUMN_ORDER_PRECISE_WITH_PHASE):
        return COLUMN_ORDER_PRECISE_WITH_PHASE
    if record_length == len(COLUMN_ORDER_PRECISE_BASE):
        return COLUMN_ORDER_PRECISE_BASE
    return None


def classify_solar_phase_from_altaz(
    solar_elevation_degrees: Iterable[float],
    solar_azimuth_degrees: Iterable[float],
) -> tuple[object, object]:
    """Classify solar phase labels from already-computed solar AltAz values.

    This helper intentionally performs only NumPy classification. It does not
    construct Astropy ``Time`` objects and does not execute additional solar
    coordinate transforms. Precise finalization can therefore reuse the
    ``sun_altaz`` values already needed for ``SunZenithAngle``.

    Parameters
    ----------
    solar_elevation_degrees : Iterable[float]
        Solar altitude/elevation angles in degrees.
    solar_azimuth_degrees : Iterable[float]
        Solar azimuth angles in degrees. Values below 180 degrees are labeled
        as morning twilight and values of 180 degrees or above as evening
        twilight when the Sun is below the horizon but above -18 degrees.

    Returns
    -------
    tuple[numpy.ndarray, numpy.ndarray]
        ``time_of_day`` and ``light_phase`` object arrays using the existing
        GUI labels: ``Day``, ``Morning``, ``Evening``, ``Night`` and
        ``Daytime``, ``Civil Twilight``, ``Nautical Twilight``,
        ``Astronomical Twilight``, ``Night``, ``Unknown``.
    """
    import numpy as np

    solar_elevations = np.asarray(solar_elevation_degrees, dtype=np.float64)
    solar_azimuths = np.asarray(solar_azimuth_degrees, dtype=np.float64)

    if solar_elevations.shape != solar_azimuths.shape:
        raise ValueError(
            "solar_elevation_degrees and solar_azimuth_degrees must have matching shapes."
        )

    n_rows = solar_elevations.size
    time_of_day = np.full(n_rows, "Night", dtype=object)
    light_phase = np.full(n_rows, "Unknown", dtype=object)

    finite = np.isfinite(solar_elevations) & np.isfinite(solar_azimuths)
    m_day = finite & (solar_elevations >= 0.0)
    m_civil = finite & (solar_elevations < 0.0) & (solar_elevations >= -6.0)
    m_nautical = finite & (solar_elevations < -6.0) & (solar_elevations >= -12.0)
    m_astro = finite & (solar_elevations < -12.0) & (solar_elevations >= -18.0)
    m_night = finite & (solar_elevations < -18.0)

    light_phase[m_day] = "Daytime"
    light_phase[m_civil] = "Civil Twilight"
    light_phase[m_nautical] = "Nautical Twilight"
    light_phase[m_astro] = "Astronomical Twilight"
    light_phase[m_night] = "Night"

    time_of_day[m_day] = "Day"
    m_twilight = finite & (solar_elevations < 0.0) & (solar_elevations >= -18.0)
    time_of_day[m_twilight & (solar_azimuths < 180.0)] = "Morning"
    time_of_day[m_twilight & (solar_azimuths >= 180.0)] = "Evening"

    return time_of_day, light_phase



def compute_solar_phase_angle_from_altaz(
    satellite_elevation_degrees: Iterable[float],
    satellite_azimuth_degrees: Iterable[float],
    solar_elevation_degrees: Iterable[float],
    solar_azimuth_degrees: Iterable[float],
    observer_satellite_range_km: Iterable[float],
    observer_sun_distance_km: Iterable[float],
) -> object:
    """Compute the Sun-satellite-observer phase angle vectorized.

    The returned angle is the angle at the satellite between the Sun and the
    observer. The calculation uses the observed Sun/satellite AltAz angular
    separation and the observer-Sun / observer-satellite side lengths. It is
    the vectorized equivalent of the scalar law-of-cosines phase-angle
    calculation used in the legacy analysis code, without per-row ``ephem`` or
    second solar-position calls.

    Parameters
    ----------
    satellite_elevation_degrees : Iterable[float]
        Apparent satellite elevation angles in degrees.
    satellite_azimuth_degrees : Iterable[float]
        Apparent satellite azimuth angles in degrees.
    solar_elevation_degrees : Iterable[float]
        Apparent solar elevation angles in degrees.
    solar_azimuth_degrees : Iterable[float]
        Apparent solar azimuth angles in degrees.
    observer_satellite_range_km : Iterable[float]
        Observer-to-satellite range in kilometers.
    observer_sun_distance_km : Iterable[float]
        Observer/Earth-to-Sun distance in kilometers.

    Returns
    -------
    numpy.ndarray
        Solar phase angle in degrees, with invalid rows set to ``nan``.
    """
    import numpy as np

    sat_el = np.asarray(satellite_elevation_degrees, dtype=np.float64)
    sat_az = np.asarray(satellite_azimuth_degrees, dtype=np.float64)
    sun_el = np.asarray(solar_elevation_degrees, dtype=np.float64)
    sun_az = np.asarray(solar_azimuth_degrees, dtype=np.float64)
    sat_range = np.asarray(observer_satellite_range_km, dtype=np.float64)
    sun_distance = np.asarray(observer_sun_distance_km, dtype=np.float64)

    try:
        sat_el, sat_az, sun_el, sun_az, sat_range, sun_distance = np.broadcast_arrays(
            sat_el, sat_az, sun_el, sun_az, sat_range, sun_distance
        )
    except ValueError as exc:
        raise ValueError(
            "solar phase angle inputs must be broadcast-compatible."
        ) from exc

    result = np.full(sat_el.shape, np.nan, dtype=np.float64)
    valid = (
        np.isfinite(sat_el)
        & np.isfinite(sat_az)
        & np.isfinite(sun_el)
        & np.isfinite(sun_az)
        & np.isfinite(sat_range)
        & np.isfinite(sun_distance)
        & (sat_range > 0.0)
        & (sun_distance > 0.0)
    )
    if not np.any(valid):
        return result

    sat_el_rad = np.deg2rad(sat_el[valid])
    sat_az_rad = np.deg2rad(sat_az[valid])
    sun_el_rad = np.deg2rad(sun_el[valid])
    sun_az_rad = np.deg2rad(sun_az[valid])
    sat_range_valid = sat_range[valid]
    sun_distance_valid = sun_distance[valid]

    cos_elongation = (
        np.sin(sun_el_rad) * np.sin(sat_el_rad)
        + np.cos(sun_el_rad)
        * np.cos(sat_el_rad)
        * np.cos(sun_az_rad - sat_az_rad)
    )
    elongation_rad = np.arccos(np.clip(cos_elongation, -1.0, 1.0))

    sun_sat_distance = np.sqrt(
        np.maximum(
            sun_distance_valid**2
            + sat_range_valid**2
            - 2.0 * sun_distance_valid * sat_range_valid * np.cos(elongation_rad),
            0.0,
        )
    )

    denominator = 2.0 * sat_range_valid * sun_sat_distance
    valid_denominator = denominator > 0.0
    phase_valid = np.full(sat_range_valid.shape, np.nan, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        cos_phase = (
            sat_range_valid[valid_denominator] ** 2
            + sun_sat_distance[valid_denominator] ** 2
            - sun_distance_valid[valid_denominator] ** 2
        ) / denominator[valid_denominator]
        phase_valid[valid_denominator] = np.rad2deg(
            np.arccos(np.clip(cos_phase, -1.0, 1.0))
        )

    result[valid] = phase_valid
    return result


def _get_prefilter_thresholds(constraints: dict | None) -> tuple[float, float, float] | None:
    """Return validated prefilter thresholds or ``None`` when unavailable.

    The final post-materialization ``apply_constraints(...)`` call remains the
    authoritative safety filter.  This helper only enables the earlier
    optimization when all required keys are present and numerically valid,
    avoiding accidental use of a different default policy from the existing
    post-filter path.
    """
    if not constraints:
        return None

    required_keys = (
        "lowest_altitude_satellite",
        "sun_zenith_lowest",
        "sun_zenith_highest",
    )
    if any(key not in constraints for key in required_keys):
        return None

    try:
        lowest_altitude = float(constraints["lowest_altitude_satellite"])
        sun_zenith_lowest = float(constraints["sun_zenith_lowest"])
        sun_zenith_highest = float(constraints["sun_zenith_highest"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Precise materialization prefilter constraints must be numeric."
        ) from exc

    if sun_zenith_lowest > sun_zenith_highest:
        raise ValueError(
            "sun_zenith_lowest must be less than or equal to sun_zenith_highest."
        )

    return lowest_altitude, sun_zenith_lowest, sun_zenith_highest


def vectorized_finalize_precise_results(
    geom_rows: list[tuple],
    location: dict,
    timezone_offset: int,
    constraints: dict | None = None,
    prefilter_before_ra_dec: bool = False,
) -> list[list]:
    """Finalize precise geometry rows into the canonical precise result schema.

    Parameters
    ----------
    geom_rows : list[tuple]
        Worker geometry tuples in ``GEOMETRY_COLUMNS`` order:
        ``(sat_name, obs_time_utc, sat_az, sat_elev, sat_lon, sat_lat,
        sat_alt_km, distance_km)``.
    location : dict
        Observer location with ``lat`` and ``lon`` in degrees and ``alt`` in
        meters.
    timezone_offset : int
        Local time offset in hours used for the display-only ``Local_Time``
        column.
    constraints : dict | None, optional
        Visibility constraints using the same keys as
        ``src.utils.results_processor.apply_constraints``.  They are used only
        when ``prefilter_before_ra_dec`` is true and all required keys are
        present.
    prefilter_before_ra_dec : bool, optional
        If true, apply a conservative SatElev/SunZenith prefilter before the
        expensive satellite RA/DEC ICRS transform and RA/DEC string formatting.
        The final post-materialization constraint filter must remain in place
        as the authoritative safety net.

    Returns
    -------
    list[list]
        Rows matching ``COLUMN_ORDER_PRECISE``.
    """
    import numpy as np
    import pandas as pd
    from astropy import units as u
    from astropy.coordinates import AltAz, EarthLocation, ICRS, SkyCoord, get_sun
    from astropy.coordinates.erfa_astrom import ErfaAstromInterpolator, erfa_astrom
    from astropy.time import Time

    if not geom_rows:
        return []

    df = pd.DataFrame(geom_rows, columns=GEOMETRY_COLUMNS)
    input_count = len(df)

    prefilter_thresholds = None
    if prefilter_before_ra_dec:
        prefilter_thresholds = _get_prefilter_thresholds(constraints)

    if prefilter_thresholds is not None:
        lowest_altitude, sun_zenith_lowest, sun_zenith_highest = prefilter_thresholds
        sat_elevations = df["SatElev"].to_numpy(dtype=np.float64)
        sat_mask = np.isfinite(sat_elevations) & (sat_elevations >= lowest_altitude)
        df = df.loc[sat_mask].reset_index(drop=True)
        after_sat_elevation_count = len(df)

        if df.empty:
            _LOGGER.info(
                "Precise prefilter before RA/DEC: input=%d after_sat_elev=0 after_sun_zenith=0",
                input_count,
            )
            return []
    else:
        lowest_altitude = sun_zenith_lowest = sun_zenith_highest = None
        after_sat_elevation_count = len(df)

    obs_loc = EarthLocation(
        lat=location["lat"] * u.deg,
        lon=location["lon"] * u.deg,
        height=location["alt"] * u.m,
    )

    times = df["ObsTime"].tolist()
    astropy_times = Time(times, scale="utc")
    altaz = AltAz(obstime=astropy_times, location=obs_loc)

    sun_coords = get_sun(astropy_times)
    with erfa_astrom.set(ErfaAstromInterpolator(300 * u.s)):
        sun_altaz = sun_coords.transform_to(altaz)

    solar_elevations = sun_altaz.alt.degree
    solar_azimuths = sun_altaz.az.degree
    solar_zenith = 90.0 - solar_elevations

    if prefilter_thresholds is not None:
        sun_mask = (
            np.isfinite(solar_zenith)
            & (solar_zenith >= sun_zenith_lowest)
            & (solar_zenith <= sun_zenith_highest)
        )
        df = df.loc[sun_mask].reset_index(drop=True)
        solar_elevations = solar_elevations[sun_mask]
        solar_azimuths = solar_azimuths[sun_mask]
        solar_zenith = solar_zenith[sun_mask]
        sun_coords = sun_coords[sun_mask]
        astropy_times = astropy_times[sun_mask]

        after_sun_zenith_count = len(df)
        _LOGGER.info(
            "Precise prefilter before RA/DEC: input=%d after_sat_elev=%d after_sun_zenith=%d",
            input_count,
            after_sat_elevation_count,
            after_sun_zenith_count,
        )

        if df.empty:
            return []

        altaz = AltAz(obstime=astropy_times, location=obs_loc)

    alt = df["SatElev"].to_numpy(dtype=np.float64) * u.deg
    az = df["SatAz"].to_numpy(dtype=np.float64) * u.deg
    sky = SkyCoord(alt=alt, az=az, frame=altaz)

    with erfa_astrom.set(ErfaAstromInterpolator(300 * u.s)):
        sky_icrs = sky.transform_to(ICRS())

    ra_deg = sky_icrs.ra.value
    dec_deg = sky_icrs.dec.value
    tmp = ICRS(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
    ra_hms = tmp.ra.to_string(unit=u.hour, sep=":", precision=2)
    dec_dms = tmp.dec.to_string(unit=u.degree, sep=":", precision=2)

    with erfa_astrom.set(ErfaAstromInterpolator(300 * u.s)):
        sun_icrs = sun_coords.transform_to(ICRS())

    time_of_day, light_phase = classify_solar_phase_from_altaz(
        solar_elevations,
        solar_azimuths,
    )
    sun_ra_h = sun_icrs.ra.hour
    sun_dec_d = sun_icrs.dec.degree

    sat_names = df["SatName"].to_numpy()
    obs_times = df["ObsTime"].to_numpy()
    sat_az = df["SatAz"].to_numpy(dtype=np.float64)
    sat_elev = df["SatElev"].to_numpy(dtype=np.float64)
    sat_alt = df["SatAlt"].to_numpy(dtype=np.float64)
    dist_km = df["DistKm"].to_numpy(dtype=np.float64)
    sat_lon = df["SatLon"].to_numpy(dtype=np.float64)
    sat_lat = df["SatLat"].to_numpy(dtype=np.float64)

    sun_distance_km = sun_coords.distance.to_value(u.km)
    solar_phase_angle = compute_solar_phase_angle_from_altaz(
        satellite_elevation_degrees=sat_elev,
        satellite_azimuth_degrees=sat_az,
        solar_elevation_degrees=solar_elevations,
        solar_azimuth_degrees=solar_azimuths,
        observer_satellite_range_km=dist_km,
        observer_sun_distance_km=sun_distance_km,
    )

    obs_series = pd.to_datetime(obs_times)
    iso_strs = obs_series.strftime("%Y-%m-%dT%H:%M:%S.%f").str[:-3].to_numpy()
    date_strs = obs_series.strftime("%Y-%m-%d").to_numpy()
    time_strs = obs_series.strftime("%H:%M:%S.%f").str[:-3].to_numpy()
    local_times = (obs_series + pd.Timedelta(hours=timezone_offset)).strftime(
        "%Y-%m-%d %H:%M:%S"
    ).to_numpy()

    final_rows = np.column_stack([
        sat_names,
        iso_strs,
        local_times,
        date_strs,
        time_strs,
        ra_hms,
        dec_dms,
        sat_az,
        sat_elev,
        solar_phase_angle,
        sat_alt,
        dist_km,
        sun_ra_h,
        sun_dec_d,
        solar_zenith,
        ra_deg,
        dec_deg,
        sat_lon,
        sat_lat,
        time_of_day,
        light_phase,
    ])
    return final_rows.tolist()
