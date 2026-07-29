import logging
import math
from datetime import datetime, timedelta, timezone

import ephem
from astropy import units as u
from astropy.coordinates import SkyCoord, Angle, AltAz, get_body

from pyorbital.astronomy import (sun_ra_dec, sun_zenith_angle)
from pyorbital.orbital import Orbital
from suntime import Sun
from src.utils.time_utils import calculate_timezone_offset

REARTH_EQU = 6378.137  # Radius at sea level at the equator in km
REARTH_POL = 6356.752  # Radius at poles in km

# Date format
frmt = "%Y-%m-%dT%H:%M:%S.%f"
logger = logging.getLogger(__name__)


def compute_precise_for_single_position(time_val, obs_lon, obs_lat, obs_alt, loc, tle1, tle2, sat_name):
    # Reinitialize the satellite object within the worker process
    satellite = Orbital('SAT', line1=tle1, line2=tle2)

    sat_az, sat_elev = satellite.get_observer_look(utc_time=time_val,
                                                   lon=obs_lon, lat=obs_lat, alt=obs_alt)

    radec = SkyCoord(alt=sat_elev * u.deg, az=sat_az * u.deg,
                     obstime=time_val, frame='altaz', location=loc)

    # Sun calculations
    sun_coordinates = sun_ra_dec(time_val)
    sun_zenith = sun_zenith_angle(time_val, obs_lon, obs_lat)
    sun_ra_hms = Angle(sun_coordinates[0], u.rad).hour
    sun_dec_dms = Angle(sun_coordinates[1], u.rad).degree

    # Satellite calculations
    sat_lon, sat_lat, sat_alt = satellite.get_lonlatalt(time_val)
    sat_ra = Angle(radec.icrs.ra.value, u.degree).to_string(unit=u.hour, sep=':', precision=2)
    sat_dec = Angle(radec.icrs.dec.value, u.degree).to_string(unit=u.degree, sep=':', precision=2)

    # Range, distance observer satellite
    dist_obs_sat = get_obs_range(sat_elev, sat_alt, obs_alt, obs_lat)

    timezone_offset = calculate_timezone_offset()
    local_time = time_val + timedelta(hours=timezone_offset)

    return [sat_name,
            time_val.strftime(frmt)[:-3],
            local_time.strftime("%Y-%m-%d %H:%M:%S"),
            time_val.strftime("%Y-%m-%d"),
            time_val.strftime('%H:%M:%S.%f')[:-3],
            sat_ra, sat_dec,
            sat_az, sat_elev, sat_alt,
            dist_obs_sat, sun_ra_hms, sun_dec_dms,
            sun_zenith,
            radec.icrs.ra.value, radec.icrs.dec.value, sat_lon, sat_lat]


# def compute_overpass_for_single_day(start_time, lat, lon, alt, tle1, tle2, sat_name, end_time=None):
#     """Compute overpass for single day."""
#
#     results = []
#
#     # Initialize observer
#     observer = ephem.Observer()
#     observer.lat, observer.lon, observer.elevation = str(lat), str(lon), alt
#     observer.date = ephem.Date(start_time)
#
#     end_time = ephem.Date(start_time + timedelta(days=1)) if not end_time else ephem.Date(end_time)
#
#     try:
#         satellite = ephem.readtle(sat_name, str(tle1), str(tle2))
#     except Exception as e:
#         logger.warning(f"ephem.readtle failed for {sat_name}: {e}; skipping.")
#         return results
#
#     try:
#         orbital = Orbital(satellite=sat_name, line1=tle1, line2=tle2)
#     except Exception as e:
#         logger.warning(f"pyorbital.Orbital failed for {sat_name}: {e}; skipping.")
#         return results
#
#     while observer.date < end_time:
#         try:
#             # Fetch next pass details
#             rise_time, azr, max_time, altt, set_time, azs = observer.next_pass(satellite, singlepass=True)
#
#             # Ensure None values are handled properly
#             if any(val is None for val in [rise_time, max_time, set_time]):
#                 logger.info(f"Skipping pass due to missing values: {rise_time}, {max_time}, {set_time}")
#                 break
#
#             # time.sleep(0.5)  # Sleep for testing purposes
#             # Skip if the pass is outside our time window
#             if ephem.Date(rise_time) > end_time:
#                 break
#
#             # # Convert max_time to UTC datetime
#             # utc_max_time = ephem.localtime(max_time).astimezone(timezone.utc)
#             #
#             # # Convert max_time to naive datetime (remove timezone info)
#             # naive_max_time = utc_max_time.replace(tzinfo=None)
#             #
#             # # Get satellite position
#             # sat_az, sat_elev = orbital.get_observer_look(
#             #     utc_time=naive_max_time,
#             #     lon=lon,
#             #     lat=lat,
#             #     alt=alt / 1000.0  # Convert to km
#             # )
#             #
#             # # Calculate sublon, sublat and altitude of satellite.
#             # sat_lon, sat_lat, sat_alt = orbital.get_lonlatalt(naive_max_time)
#             # # Range, distance observer satellite
#             # dist_obs_sat = get_obs_range(sat_elev, sat_alt, alt / 1000.0, lat)
#
#             # Convert times to UTC datetime
#             utc_rise_time = ephem.localtime(rise_time).astimezone(timezone.utc).replace(tzinfo=None)
#             utc_max_time = ephem.localtime(max_time).astimezone(timezone.utc).replace(tzinfo=None)
#             utc_set_time = ephem.localtime(set_time).astimezone(timezone.utc).replace(tzinfo=None)
#
#             # Get satellite parameters for rise time
#             sat_az_rise, sat_elev_rise = orbital.get_observer_look(utc_rise_time, lon, lat, alt / 1000.0)
#             sat_lon_rise, sat_lat_rise, sat_alt_rise = orbital.get_lonlatalt(utc_rise_time)
#             dist_obs_sat_rise = get_obs_range(sat_elev_rise, sat_alt_rise, alt / 1000.0, lat)
#
#             # Get satellite parameters for max time
#             sat_az_max, sat_elev_max = orbital.get_observer_look(utc_max_time, lon, lat, alt / 1000.0)
#             sat_lon_max, sat_lat_max, sat_alt_max = orbital.get_lonlatalt(utc_max_time)
#             dist_obs_sat_max = get_obs_range(sat_elev_max, sat_alt_max, alt / 1000.0, lat)
#
#             # Get satellite parameters for set time
#             sat_az_set, sat_elev_set = orbital.get_observer_look(utc_set_time, lon, lat, alt / 1000.0)
#             sat_lon_set, sat_lat_set, sat_alt_set = orbital.get_lonlatalt(utc_set_time)
#             dist_obs_sat_set = get_obs_range(sat_elev_set, sat_alt_set, alt / 1000.0, lat)
#
#             # Sun calculations
#             sun_coordinates = sun_ra_dec(utc_max_time)
#             sun_ra_hms = Angle(sun_coordinates[0], u.rad).hour
#             sun_dec_dms = Angle(sun_coordinates[1], u.rad).degree
#
#             result = [sat_name,
#                       ephem.localtime(rise_time).strftime("%Y-%m-%d %H:%M:%S"),
#                       ephem.localtime(max_time).strftime("%Y-%m-%d %H:%M:%S"),
#                       ephem.localtime(set_time).strftime("%Y-%m-%d %H:%M:%S"),
#                       utc_rise_time.strftime("%Y-%m-%d %H:%M:%S"),
#                       utc_max_time.strftime("%Y-%m-%d %H:%M:%S"),
#                       utc_set_time.strftime("%Y-%m-%d %H:%M:%S"),
#                       azr * 180. / math.pi, altt * 180. / math.pi, azs * 180. / math.pi,
#                       # Rise time parameters
#                       sat_az_rise, sat_elev_rise, sat_alt_rise, dist_obs_sat_rise, sat_lon_rise, sat_lat_rise,
#                       # Max time parameters
#                       sat_az_max, sat_elev_max, sat_alt_max, dist_obs_sat_max, sat_lon_max, sat_lat_max,
#                       # Set time parameters
#                       sat_az_set, sat_elev_set, sat_alt_set, dist_obs_sat_set, sat_lon_set, sat_lat_set,
#                       sun_ra_hms, sun_dec_dms
#                       ]
#
#             results.append(result)
#
#             # Update observer date to the set time to fetch the next pass
#             observer.date = set_time
#         except (ValueError, ephem.CircumpolarError, NotImplementedError) as e:
#             logger.error(f"Error during pass calculation: {e}")
#             break
#     # print(f"Results: {results}")
#     return results

def compute_overpass_for_single_day(start_time, lat, lon, alt, tle1, tle2, sat_name, end_time=None):
    """Compute overpass for single day with robust skipping on invalid data."""
    results = []

    # Initialize observer
    observer = ephem.Observer()
    observer.lat, observer.lon, observer.elevation = str(lat), str(lon), alt
    observer.date = ephem.Date(start_time)

    end_time = ephem.Date(start_time + timedelta(days=1)) if not end_time else ephem.Date(end_time)

    try:
        satellite = ephem.readtle(sat_name, str(tle1), str(tle2))
    except Exception as e:
        logger.warning(f"ephem.readtle failed for {sat_name}: {e}; skipping.")
        return results

    try:
        orbital = Orbital(satellite=sat_name, line1=tle1, line2=tle2)
    except Exception as e:
        logger.warning(f"pyorbital.Orbital failed for {sat_name}: {e}; skipping.")
        return results

    # Safety to avoid infinite loops if next_pass keeps failing
    max_iters = 1000
    iters = 0

    def _advance(hours: float = 1.0):
        observer.date = ephem.Date(observer.date + hours * ephem.hour)

    while observer.date < end_time and iters < max_iters:
        iters += 1
        try:
            # next_pass sometimes raises TypeError when it builds a tuple with None inside
            p = observer.next_pass(satellite, singlepass=True)
        except (TypeError, ValueError, ephem.CircumpolarError, NotImplementedError) as e:
            logger.info(f"Skipping pass due to ephem.next_pass error: {e}")
            _advance(1.0)
            continue
        except Exception as e:
            logger.error(f"Unexpected error in next_pass: {e}")
            _advance(1.0)
            continue

        if not p or len(p) != 6:
            logger.info("Skipping pass due to malformed next_pass result.")
            _advance(1.0)
            continue

        rise_time, azr, max_time, altt, set_time, azs = p

        # Guard against None values from next_pass
        if any(val is None for val in (rise_time, max_time, set_time, azr, altt, azs)):
            logger.info(f"Skipping pass due to None values: {p}")
            _advance(1.0)
            continue

        # Skip if the pass is outside our time window
        if ephem.Date(rise_time) > end_time:
            break

        # Convert times to UTC naive datetimes
        try:
            utc_rise_time = ephem.localtime(rise_time).astimezone(timezone.utc).replace(tzinfo=None)
            utc_max_time = ephem.localtime(max_time).astimezone(timezone.utc).replace(tzinfo=None)
            utc_set_time = ephem.localtime(set_time).astimezone(timezone.utc).replace(tzinfo=None)
        except Exception as e:
            logger.info(f"Skipping pass due to time conversion error: {e}")
            _advance(1.0)
            continue

        # Satellite parameters at rise/max/set; skip gracefully on any error
        try:
            # Rise
            sat_az_rise, sat_elev_rise = orbital.get_observer_look(utc_rise_time, lon, lat, alt / 1000.0)
            sat_lon_rise, sat_lat_rise, sat_alt_rise = orbital.get_lonlatalt(utc_rise_time)
            dist_obs_sat_rise = get_obs_range(sat_elev_rise, sat_alt_rise, alt / 1000.0, lat)

            # Max
            sat_az_max, sat_elev_max = orbital.get_observer_look(utc_max_time, lon, lat, alt / 1000.0)
            sat_lon_max, sat_lat_max, sat_alt_max = orbital.get_lonlatalt(utc_max_time)
            dist_obs_sat_max = get_obs_range(sat_elev_max, sat_alt_max, alt / 1000.0, lat)

            # Set
            sat_az_set, sat_elev_set = orbital.get_observer_look(utc_set_time, lon, lat, alt / 1000.0)
            sat_lon_set, sat_lat_set, sat_alt_set = orbital.get_lonlatalt(utc_set_time)
            dist_obs_sat_set = get_obs_range(sat_elev_set, sat_alt_set, alt / 1000.0, lat)
        except Exception as e:
            logger.info(f"Skipping pass due to pyorbital error: {e}")
            _advance(1.0)
            continue

        # Sun at max time
        try:
            sun_coordinates = sun_ra_dec(utc_max_time)
            sun_ra_hms = Angle(sun_coordinates[0], u.rad).hour
            sun_dec_dms = Angle(sun_coordinates[1], u.rad).degree
        except Exception as e:
            logger.info(f"Skipping pass due to sun calculation error: {e}")
            _advance(1.0)
            continue

        result = [
            sat_name,
            ephem.localtime(rise_time).strftime("%Y-%m-%d %H:%M:%S"),
            ephem.localtime(max_time).strftime("%Y-%m-%d %H:%M:%S"),
            ephem.localtime(set_time).strftime("%Y-%m-%d %H:%M:%S"),
            utc_rise_time.strftime("%Y-%m-%d %H:%M:%S"),
            utc_max_time.strftime("%Y-%m-%d %H:%M:%S"),
            utc_set_time.strftime("%Y-%m-%d %H:%M:%S"),
            azr * 180.0 / math.pi, altt * 180.0 / math.pi, azs * 180.0 / math.pi,
            # Rise
            sat_az_rise, sat_elev_rise, sat_alt_rise, dist_obs_sat_rise, sat_lon_rise, sat_lat_rise,
            # Max
            sat_az_max, sat_elev_max, sat_alt_max, dist_obs_sat_max, sat_lon_max, sat_lat_max,
            # Set
            sat_az_set, sat_elev_set, sat_alt_set, dist_obs_sat_set, sat_lon_set, sat_lat_set,
            sun_ra_hms, sun_dec_dms
        ]
        results.append(result)

        # Move to the end of this pass to find the next one
        observer.date = set_time

    if iters >= max_iters:
        logger.warning(f"Aborted overpass loop due to iteration cap for {sat_name} on {start_time}.")

    return results

def compute_overpass_details(time, lat, lon, alt, orbital):
    """"""
    # Convert max_time to UTC datetime
    utc_time = ephem.localtime(time).astimezone(timezone.utc)

    # Convert max_time to naive datetime (remove timezone info)
    naive_time = utc_time.replace(tzinfo=None)

    # Get satellite position
    sat_az, sat_elev = orbital.get_observer_look(
        utc_time=naive_time,
        lon=lon,
        lat=lat,
        alt=alt / 1000.0  # Convert to km
    )

    sat_lon, sat_lat, sat_alt = orbital.get_lonlatalt(naive_time)

    # Range, distance observer satellite
    dist_obs_sat = get_obs_range(sat_elev, sat_alt, alt / 1000.0, lat)

    return naive_time, sat_az, sat_elev, sat_alt, dist_obs_sat, sat_lon, sat_lat


def calculate_pos_times(start_time, exptime, dt):
    num_intervals = int(exptime / dt) if dt else 1
    pos_times = [start_time - timedelta(seconds=dt)]
    pos_times += [start_time + timedelta(seconds=i * dt) for i in range(num_intervals + 1)]
    return pos_times


def compute_solar_zenith(time_grid, location):
    """
    Compute the solar zenith angle for a given time grid and location.

    Parameters:
    - time_grid (Time): Array of times for which to compute solar zenith angle.
    - location (EarthLocation): Observer's location.

    Returns:
    - np.array: Solar zenith angles in degrees.
    """
    observer_frame = AltAz(obstime=time_grid, location=location)
    solar_zenith = get_body('sun', time_grid).transform_to(observer_frame).zen.degree
    return solar_zenith


def get_day_night_intervals(latitude, longitude, start_date, num_days, mode="both"):
    """
    Returns a list of (start_time, end_time) tuples for daytime and nighttime periods over multiple days.
    All times are computed in UTC. Local time conversion is for display purposes only.

    Parameters:
        latitude (float): Observer's latitude.
        longitude (float): Observer's longitude.
        start_date (datetime): Start date (UTC).
        num_days (int): Number of days to compute intervals for.
        mode (str): "both" for all intervals, "night" for only nighttime, "day" for only daytime.

    Returns:
        List[Tuple[datetime, datetime]]: List of (start_time, end_time) tuples in UTC.
    """
    sun = Sun(latitude, longitude)
    time_chunks = []

    # Get the current UTC time
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    # print("Current UTC time:", now_utc.date())
    # print("Start date:", start_date)
    is_today = start_date.date() == now_utc.date()
    # print("Is today:", is_today)

    for i in range(num_days):
        # midnight = datetime.combine(start_date.date(), datetime.min.time())
        current_day = start_date + timedelta(days=i)
        next_day = current_day + timedelta(days=1)
        # print(f"Current day: {current_day}, Next day: {next_day}, Now: {now_utc}")

        sunrise = sun.get_sunrise_time(at_date=current_day).replace(tzinfo=None)  # UTC
        sunset = sun.get_sunset_time(at_date=current_day).replace(tzinfo=None)  # UTC
        next_sunrise = sun.get_sunrise_time(at_date=next_day).replace(tzinfo=None)  # UTC
        next_sunset = sun.get_sunset_time(at_date=next_day).replace(tzinfo=None)  # UTC
        # print(f"Mode: {mode}, Sunrise: {sunrise}, Sunset: {sunset}, Next sunrise: {next_sunrise}, Next sunset: {next_sunset}")

        if i == 0 and is_today:
            if mode in ("both", "night"):
                if now_utc < sunrise:
                    time_chunks.append((now_utc, sunrise))
            if mode in ("both", "day"):
                if sunrise < now_utc < next_sunset:
                    time_chunks.append((now_utc, next_sunset))

        if mode in ("both", "night"):
            time_chunks.append((next_sunset, next_sunrise))
        if mode in ("both", "day"):
            time_chunks.append((sunrise, next_sunset))
    # print(f"Time chunks: {time_chunks}")
    return time_chunks


def export_to_csv(df, filename="satellite_passes.csv"):
    df.to_csv(filename, index=False)


def convert_utc_to_local(obs_time):
    if isinstance(obs_time, str):
        obs_time = datetime.strptime(obs_time, '%Y-%m-%dT%H:%M:%S.%f')

    obs_time_utc = obs_time.replace(tzinfo=timezone.utc)
    local_time = obs_time_utc.astimezone()  # Convert to local time (system timezone)
    tz_difference = (local_time.utcoffset().total_seconds()) / 3600  # Offset in hours

    return local_time.strftime('%Y-%m-%d %H:%M:%S'), tz_difference


def get_obs_range(sat_elev, h_orb, h_obs_km, lat):
    """Get satellite-observer range.

    Adopted from get_sat_observer_range.m by Angel Otarola, aotarola@tmt.org

    """

    # Get the radius of Earth for a given observation site latitude
    Rearth_obs = get_radius_earth(lat)
    Rearth = Rearth_obs + h_obs_km

    # derived quantities
    # S = satellite position along its orbit
    # O = observer position on the surface
    # C = Geo-center

    gamma = 90. + sat_elev  # degrees, Angle with the center in the observer - <SOC>

    # Length of the CO side = Rearth
    # Length of the CS side = Rearth + Horb

    CO = Rearth  # km
    CS = Rearth + h_orb  # km

    # use the law of sin for derivation of the beta angle <CSO>
    beta = math.asin(CO / CS * math.sin(gamma * math.pi / 180.)) * 180. / math.pi  # degrees

    # derivation of the alpha angle, <OCS>
    alpha = 180. - gamma - beta  # degrees,

    # Use of the cos law for derivation of the distance from Observer to
    # Satellite (OS), accounting for its elevation (or zenith) angle
    OS = math.sqrt(CO ** 2 + CS ** 2 - 2. * CO * CS * math.cos(alpha * math.pi / 180.))

    return OS


def get_radius_earth(B):
    """Get the radius of Earth for a given observation site latitude"""
    B = math.radians(B)  # converting into radians

    a = REARTH_EQU  # Radius at sea level at the equator
    b = REARTH_POL  # Radius at poles

    c = (a ** 2 * math.cos(B)) ** 2
    d = (b ** 2 * math.sin(B)) ** 2
    e = (a * math.cos(B)) ** 2
    f = (b * math.sin(B)) ** 2

    R = math.sqrt((c + d) / (e + f))
    return R
