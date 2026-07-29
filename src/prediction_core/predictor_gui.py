import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import timedelta, datetime
from functools import partial

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.coordinates import EarthLocation

from .predict_utils import compute_overpass_for_single_day, compute_precise_for_single_position

# Column order for the final DataFrame
COLUMN_ORDER_PRECISE = ['Sat_ID', 'Obs_Time', 'Local_Time', 'UT_Date', 'UT_time', 'SatRA', 'SatDEC', 'SatAz',
                        'SatElev', 'SatAlt', 'SatDist', 'SunRA', 'SunDEC', 'SunZenithAngle', 'RA', 'DEC', 'SatLon',
                        'SatLat']

COLUMN_ORDER_OVERPASS = ['Sat_ID', 'rise_time_loc', 'max_time_loc', 'set_time_loc', 'rise_time_utc', 'max_time_utc',
                         'set_time_utc', 'rise_azimuth', 'max_elevation', 'set_azimuth', 'SatAz', 'SatElev', 'SatAlt',
                         'SatDist', 'SatLon', 'SatLat']

# Date format
frmt = "%Y-%m-%dT%H:%M:%S.%f"
logger = logging.getLogger(__name__)


class SatellitePredictor:
    def __init__(self, sat_name, tle1, tle2):
        self.sat_name = sat_name
        self.tle1 = tle1
        self.tle2 = tle2

    def run_prediction(self, mode, lat, lon, alt,
                       start_datetime, end_datetime=None, days=1, interval=1,
                       cancel_event=None, multiple_satellites=True, margin=5):
        """
        Shared internal function to call specific prediction modes.
        """
        logger.info(f"Starting {mode} prediction for {self.sat_name}")

        if cancel_event and cancel_event.is_set():
            logger.info("Prediction cancelled before starting.")
            return pd.DataFrame()

        if mode == "overpass":
            results = self.run_overpass_prediction(lat, lon, alt, days, start_datetime=start_datetime,
                                                   cancel_event=cancel_event, multiple_satellites=multiple_satellites)
        elif mode == "precise":
            results = self.run_precise_prediction(lat, lon, alt,
                                                  start_datetime=start_datetime, end_datetime=end_datetime,
                                                  interval=interval, cancel_event=cancel_event,
                                                  multiple_satellites=multiple_satellites, margin_timedelta=margin)
        else:
            logger.error(f"Invalid prediction mode: {mode}")
            return pd.DataFrame()  # Return empty DataFrame for invalid mode

        if results is None or results.empty:
            logger.warning(f"No results returned from {mode} prediction.")
            return pd.DataFrame()

        # Always return results here without modifications.
        return results

    def run_overpass_prediction(self, lat, lon, alt, days, start_datetime,
                                multiple_satellites=True, cancel_event=None):
        """Calculate satellite overpasses."""

        sat_name = self.sat_name
        tle1 = self.tle1
        tle2 = self.tle2
        # print(f"Calculating overpasses for {sat_name} for {days} days.")
        # print(f"Start time: {start_datetime}")
        # print(f"Location: {lat}, {lon}, {alt}")
        # print(f"Multiple satellites: {multiple_satellites}")
        # print(f"Cancel event: {cancel_event}")
        # print(f"Satellite: {sat_name}, TLE1: {tle1}, TLE2: {tle2}")
        # Initialize results list
        results = []

        executor_class = ProcessPoolExecutor
        if multiple_satellites:
            for day in range(days):
                if cancel_event and cancel_event.is_set():
                    logger.info("Prediction cancelled. Exiting loop.")
                    break  # Exit the loop if the prediction is canceled
                daily_start_datetime = start_datetime + timedelta(days=day)
                result = compute_overpass_for_single_day(start_time=daily_start_datetime,
                                                              lat=lat, lon=lon, alt=alt,
                                                              tle1=tle1, tle2=tle2, sat_name=sat_name)
                if result:
                    results.append(result)

        else:
            days_to_predict = [start_datetime + timedelta(days=i) for i in range(days)]
            func = partial(compute_overpass_for_single_day, lat=lat, lon=lon, alt=alt,
                           tle1=tle1, tle2=tle2, sat_name=sat_name)
            # Multiprocessing or multithreading mode
            with executor_class() as executor:
                futures = {executor.submit(func, d): d for d in days_to_predict}
                for future in as_completed(futures):
                    if cancel_event and cancel_event.is_set():
                        logger.info("Prediction cancelled during processing.")
                        break
                    try:
                        result = future.result()
                        # print(f"Result: {result}")
                        if result:
                            results.append(result)
                    except Exception as e:
                        logger.error(f"Error processing time {futures[future]}: {e}")

        results = np.concatenate(results, axis=0)

        df = pd.DataFrame(results, columns=COLUMN_ORDER_OVERPASS)
        # print(f"Overpass prediction completed. Passes calculated: {len(results)}")

        return df

    def run_precise_prediction(self, lat, lon, alt,
                               interval=1,
                               start_datetime=None, end_datetime=None,
                               sat_name=None, tle1=None, tle2=None,
                               cancel_event=None, multiple_satellites=True, margin_timedelta=5):
        """Calculate precise satellite paths for visible satellites."""
        sat_name = sat_name or self.sat_name
        tle1 = tle1 or self.tle1
        tle2 = tle2 or self.tle2
        obs_alt = alt * u.m

        # Initialize results list
        results = []

        overpasses = compute_overpass_for_single_day(
            start_time=start_datetime,
            end_time=end_datetime,  # Updated to handle full window
            lat=lat, lon=lon, alt=alt,
            tle1=tle1, tle2=tle2, sat_name=sat_name
        )

        if not overpasses or len(overpasses) == 0:
            logger.info(f"No overpasses found for satellite {sat_name}. Skipping precise prediction.")
            return pd.DataFrame()

        adjusted_windows = []
        for overpass in overpasses:
            rise_time = datetime.strptime(overpass[4], "%Y-%m-%d %H:%M:%S")
            set_time = datetime.strptime(overpass[6], "%Y-%m-%d %H:%M:%S")
            adjusted_start = max(start_datetime, rise_time - margin_timedelta)
            adjusted_end = min(end_datetime, set_time + margin_timedelta)

            # Generate position times for this pass
            observation_window_seconds = (adjusted_end - adjusted_start).total_seconds()
            num_intervals = int(observation_window_seconds / interval)
            pos_times = [adjusted_start + timedelta(seconds=i * interval) for i in range(num_intervals + 1)]
            adjusted_windows.extend(pos_times)

        logger.info(f"Total position times generated for {sat_name}: {len(adjusted_windows)}")

        # Initialize observer location
        observer_location = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=obs_alt)

        # Calculate the observation window and intervals for the prediction
        observation_window_seconds = (end_datetime - start_datetime).total_seconds()
        number_of_intervals = int(observation_window_seconds / interval)
        logger.info(f"Observation window: {observation_window_seconds}s with {number_of_intervals} intervals.")

        # Generate the list of observation times
        pos_times = [start_datetime + timedelta(seconds=i * interval) for i in range(number_of_intervals)]

        # Define the function to compute the precise position for a single time
        func = partial(compute_precise_for_single_position, obs_lon=lon, obs_lat=lat, obs_alt=alt / 1000.0,
                       loc=observer_location, tle1=tle1, tle2=tle2, sat_name=sat_name)

        # Dynamically select executor class
        executor_class = ProcessPoolExecutor

        # Process the predictions.
        # If a single satellite is provided, use a ProcessPoolExecutor to parallelize the position times.
        # If multiple satellites are provided, process the position time serial,
        # because the satellites use a ProcessPoolExecutor.
        if not multiple_satellites:
            # Multiprocessing or multithreading mode
            with executor_class() as executor:
                futures = {executor.submit(func, t): t for t in adjusted_windows}

                for future in as_completed(futures):
                    if cancel_event and cancel_event.is_set():
                        logger.info("Prediction cancelled during processing.")
                        # Shutdown the executor and break
                        executor.shutdown(wait=False)
                        for f in futures:
                            f.cancel()  # Explicitly cancel any remaining tasks
                        break
                    try:
                        result = future.result()
                        if result:
                            results.append(result)
                    except Exception as e:
                        logger.error(f"Error processing time {futures[future]}: {e}")
        else:
            for t in adjusted_windows:
                if cancel_event and cancel_event.is_set():
                    logger.info("Prediction cancelled during processing.")
                    break
                try:
                    result = func(t)
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.error(f"Error processing time {t}: {e}")

        df = pd.DataFrame(results, columns=COLUMN_ORDER_PRECISE)

        logger.info(f"Precise prediction completed. Passes calculated: {len(results)}")
        return df
