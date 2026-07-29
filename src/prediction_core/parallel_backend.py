"""Shared high-performance prediction backend for GUI/backend parity.

This module extracts the optimized execution strategy used by the web predictor
into a reusable, Redis-free backend that can be consumed by the desktop GUI
without coupling the GUI runtime to Flask or Redis infrastructure.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from astropy import units as u
from astropy.coordinates import EarthLocation

from src.prediction_core.predict_utils import (
    compute_overpass_for_single_day,
    compute_precise_for_single_position,
    get_day_night_intervals,
    get_obs_range,
)
from src.prediction_core.precise_materialization import (
    COLUMN_ORDER_PRECISE,
    vectorized_finalize_precise_results as vectorized_finalize_results_new,
)
from src.utils.time_utils import calculate_timezone_offset

try:
    MAX_WORKERS = int(os.getenv("PREDICT_MAX_WORKERS", "0"))
    if MAX_WORKERS <= 0:
        MAX_WORKERS = max(1, multiprocessing.cpu_count() - 1)
except Exception:
    MAX_WORKERS = 1

MAX_TIMES_PER_TASK = int(os.getenv("MAX_TIMES_PER_TASK", "5000"))
TARGET_SAMPLES_PER_JOB = int(os.getenv("TARGET_SAMPLES_PER_JOB", "5000"))

COLUMN_ORDER_OVERPASS = [
    "Sat_ID", "rise_time_loc", "max_time_loc", "set_time_loc", "rise_time_utc", "max_time_utc",
    "set_time_utc", "rise_azimuth", "max_elevation", "set_azimuth",
    "SatAzRise", "SatElevRise", "SatAltRise", "SatDistRise", "SatLonRise", "SatLatRise",
    "SatAz", "SatElev", "SatAlt", "SatDist", "SatLon", "SatLat",
    "SatAzSet", "SatElevSet", "SatAltSet", "SatDistSet", "SatLonSet", "SatLatSet",
    "SunRA", "SunDEC",
]


@dataclass(slots=True)
class BackendRunResult:
    """Raw backend result payload returned before GUI-side post-processing."""

    rows: list[list]
    columns: list[str]


def process_overpass_chunk(sat: dict, time_range: tuple[datetime, datetime], location: dict) -> list[list]:
    """Compute overpass rows for one satellite and one daylight/night interval."""
    return compute_overpass_for_single_day(
        start_time=time_range[0],
        end_time=time_range[1],
        lat=location["lat"],
        lon=location["lon"],
        alt=location["alt"],
        tle1=sat["tle1"],
        tle2=sat["tle2"],
        sat_name=sat["name"],
    )


def process_precise_point(args: tuple[datetime, dict, dict]) -> list | None:
    """Compute one precise prediction sample using the legacy point helper."""
    time_val, sat, loc_dict = args
    loc = EarthLocation(
        lat=loc_dict["lat"] * u.deg,
        lon=loc_dict["lon"] * u.deg,
        height=loc_dict["alt"] * u.m,
    )
    return compute_precise_for_single_position(
        time_val=time_val,
        obs_lon=loc_dict["lon"],
        obs_lat=loc_dict["lat"],
        obs_alt=loc_dict["alt"] / 1000.0,
        loc=loc,
        tle1=sat["tle1"],
        tle2=sat["tle2"],
        sat_name=sat["name"],
    )


def _run_job_worker_light(args: tuple[list[tuple[dict, list[datetime]]], dict, int, int]) -> list[tuple]:
    """Lightweight precise worker using pyorbital only.

    Returns tuples with geometry information that will be finalized in the
    parent process using vectorized Astropy transforms.
    """
    job_list, loc_dict, _margin_minutes, _timezone_offset = args
    out = []
    try:
        from pyorbital.orbital import Orbital
    except Exception:
        return out

    for sat, times in job_list:
        tle1 = sat.get("tle1")
        tle2 = sat.get("tle2")
        sat_name = sat.get("name")
        try:
            orbital = Orbital(satellite=sat_name, line1=tle1, line2=tle2)
        except Exception:
            continue

        for t in times:
            try:
                sat_az, sat_elev = orbital.get_observer_look(
                    utc_time=t,
                    lon=loc_dict["lon"],
                    lat=loc_dict["lat"],
                    alt=loc_dict["alt"] / 1000.0,
                )
                sat_lon, sat_lat, sat_alt = orbital.get_lonlatalt(t)
                dist = get_obs_range(sat_elev, sat_alt, loc_dict["alt"] / 1000.0, loc_dict["lat"])
                out.append((
                    sat_name,
                    t,
                    float(sat_az),
                    float(sat_elev),
                    float(sat_lon),
                    float(sat_lat),
                    float(sat_alt),
                    float(dist),
                ))
            except Exception:
                continue
    return out


def build_worker_batches(
    chunks: list[tuple[dict, list[datetime]]],
    location: dict,
    margin_minutes: int,
    timezone_offset: int,
    max_times_per_subtask: int = MAX_TIMES_PER_TASK,
    target_samples_per_job: int = TARGET_SAMPLES_PER_JOB,
) -> list[tuple[list[tuple[dict, list[datetime]]], dict, int, int]]:
    """Pack precise-prediction work into balanced worker jobs."""
    subtasks: list[tuple[dict, list[datetime]]] = []
    for sat, times in chunks:
        if not times:
            continue
        if len(times) <= max_times_per_subtask:
            subtasks.append((sat, times))
            continue
        for i in range(0, len(times), max_times_per_subtask):
            subtasks.append((sat, times[i:i + max_times_per_subtask]))

    if not subtasks:
        return []

    subtasks.sort(key=lambda item: len(item[1]), reverse=True)
    jobs: list[list[tuple[dict, list[datetime]]]] = []
    jobs_size: list[int] = []

    for sat, times in subtasks:
        size = len(times)
        for job_index, current_size in enumerate(jobs_size):
            if current_size + size <= target_samples_per_job:
                jobs[job_index].append((sat, times))
                jobs_size[job_index] += size
                break
        else:
            jobs.append([(sat, times)])
            jobs_size.append(size)

    return [(job, location, margin_minutes, timezone_offset) for job in jobs]


class SharedPredictionBackend:
    """Redis-free reusable backend aligned with the web prediction execution path."""

    def __init__(
        self,
        *,
        mode: str,
        satellites: list[dict],
        location: dict,
        start_datetime: datetime,
        end_datetime: datetime | None,
        days: int,
        interval: int,
        margin: int,
        constraints: dict | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.mode = mode
        self.satellites = satellites
        self.location = location
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime
        self.days = days
        self.interval = interval
        self.margin = margin
        self.constraints = constraints or {}
        self._is_cancelled = is_cancelled or (lambda: False)
        self.logger = logger or logging.getLogger(__name__)

    @property
    def column_order(self) -> list[str]:
        return COLUMN_ORDER_OVERPASS if self.mode == "overpass" else COLUMN_ORDER_PRECISE

    def is_cancelled(self) -> bool:
        return bool(self._is_cancelled())

    def run(self) -> BackendRunResult:
        if self.mode == "overpass":
            rows = self._run_parallel_overpass()
            return BackendRunResult(rows=rows, columns=COLUMN_ORDER_OVERPASS)
        if self.mode == "precise":
            rows = self._run_parallel_precise()
            return BackendRunResult(rows=rows, columns=COLUMN_ORDER_PRECISE)
        raise ValueError(f"Unsupported prediction mode: {self.mode}")

    def _run_parallel_overpass(self) -> list[list]:
        chunks = self._distribute_overpass_threaded()
        self.logger.info("Distributed %d chunk(s) for GUI overpass prediction.", len(chunks))
        if not chunks or self.is_cancelled():
            return []

        all_results: list[list] = []
        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(process_overpass_chunk, sat, time_range, self.location) for sat, time_range in chunks]
            for future in as_completed(futures):
                if self.is_cancelled():
                    executor.shutdown(wait=False)
                    return []
                result = future.result()
                all_results.extend(result if isinstance(result, list) else [result])
        return all_results

    def _run_parallel_precise(self) -> list[list]:
        import time as _time

        t_distribute = _time.perf_counter()
        chunks = self._distribute_precise_threaded()
        distribute_elapsed = _time.perf_counter() - t_distribute
        self.logger.info(
            "Distributed %d precise chunk(s) for GUI prediction in %.3fs.",
            len(chunks),
            distribute_elapsed,
        )
        if not chunks or self.is_cancelled():
            return []

        unique_satellites = len({sat.get("name") for sat, _times in chunks})
        self.logger.info(
            "Precise execution plan: unique_satellites=%d filtered_pass_chunks=%d interval_seconds=%d single_satellite_case=%s",
            unique_satellites,
            len(chunks),
            self.interval,
            unique_satellites == 1,
        )
        return self._run_multi_satellite_precise(chunks)

    def _run_multi_satellite_precise(self, chunks: list[tuple[dict, list[datetime]]]) -> list[list]:
        timezone_offset = calculate_timezone_offset()
        worker_jobs = build_worker_batches(
            chunks=chunks,
            location=self.location,
            margin_minutes=self.margin,
            timezone_offset=timezone_offset,
            max_times_per_subtask=MAX_TIMES_PER_TASK,
            target_samples_per_job=TARGET_SAMPLES_PER_JOB,
        )
        if not worker_jobs:
            return []

        total_samples = sum(len(times) for _sat, times in chunks)
        n_workers = min(MAX_WORKERS, max(1, multiprocessing.cpu_count()), max(1, len(worker_jobs)))
        self.logger.info(
            "Running precise prediction: multi-satellite, per-satellite chunking (process pool)"
        )
        self.logger.info(
            "Submitting %d worker jobs (n_workers=%d) total_samples=%d target_job_samples=%d",
            len(worker_jobs),
            n_workers,
            total_samples,
            TARGET_SAMPLES_PER_JOB,
        )

        import time as _time
        t_submit = _time.perf_counter()
        all_geom_rows: list[tuple] = []
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            future_meta = {}
            for job_arg in worker_jobs:
                future = executor.submit(_run_job_worker_light, job_arg)
                samples = sum(len(times) for _sat, times in job_arg[0])
                future_meta[future] = {"samples": samples, "t0": _time.perf_counter()}

            for future in as_completed(future_meta):
                if self.is_cancelled():
                    executor.shutdown(wait=False)
                    return []
                meta = future_meta[future]
                result = future.result()
                elapsed = _time.perf_counter() - meta["t0"]
                returned = len(result) if result else 0
                self.logger.info(
                    "Job finished: samples=%d elapsed=%.3fs returned=%d rows",
                    meta["samples"],
                    elapsed,
                    returned,
                )
                if result:
                    all_geom_rows.extend(result)

        t_total = _time.perf_counter() - t_submit
        self.logger.info(
            "All jobs complete: total_results=%d elapsed=%.3fs",
            len(all_geom_rows),
            t_total,
        )

        if self.is_cancelled():
            return []
        final_rows = vectorized_finalize_results_new(
            all_geom_rows,
            self.location,
            timezone_offset,
            constraints=self.constraints,
            prefilter_before_ra_dec=True,
        )
        self.logger.info(
            "Finalization complete: final_results=%d",
            len(final_rows),
        )
        return final_rows

    def _distribute_overpass_threaded(self) -> list[tuple[dict, tuple[datetime, datetime]]]:
        start_datetime = self.start_datetime
        if isinstance(start_datetime, str):
            start_datetime = datetime.fromisoformat(start_datetime)

        intervals = get_day_night_intervals(
            self.location["lat"],
            self.location["lon"],
            start_datetime,
            self.days,
            mode=self.constraints.get("prediction_range_overpass", "night"),
        )

        result_chunks: list[tuple[dict, tuple[datetime, datetime]]] = []

        def process_satellite_cancelable(sat: dict) -> list[tuple[dict, tuple[datetime, datetime]]]:
            if self.is_cancelled():
                return []
            return [(sat, (start, end)) for start, end in intervals if not self.is_cancelled()]

        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(self.satellites) or 1)) as executor:
            futures = [executor.submit(process_satellite_cancelable, sat) for sat in self.satellites]
            for future in as_completed(futures):
                if self.is_cancelled():
                    executor.shutdown(wait=False)
                    return []
                result_chunks.extend(future.result())
        return result_chunks

    def _distribute_precise_threaded(self):
        import numpy as np
        import pandas as pd
        from astropy.coordinates import AltAz, get_sun
        from astropy.time import Time

        lowest_elev = float(self.constraints.get("lowest_altitude_satellite", 30))
        sun_zenith_lowest = float(self.constraints.get("sun_zenith_lowest", 0))
        sun_zenith_highest = float(self.constraints.get("sun_zenith_highest", 180))

        earth_location = EarthLocation(
            lat=self.location["lat"] * u.deg,
            lon=self.location["lon"] * u.deg,
            height=self.location["alt"] * u.m,
        )

        start_dt = self.start_datetime if not isinstance(self.start_datetime, str) else datetime.fromisoformat(self.start_datetime)
        end_dt = self.end_datetime if self.end_datetime is not None else start_dt + timedelta(days=self.days)
        if isinstance(end_dt, str):
            end_dt = datetime.fromisoformat(end_dt)

        def collect_pass_metadata_for_sat(sat: dict):
            if self.is_cancelled():
                return []
            try:
                overpasses = compute_overpass_for_single_day(
                    start_time=start_dt,
                    end_time=end_dt,
                    lat=self.location["lat"],
                    lon=self.location["lon"],
                    alt=self.location["alt"],
                    tle1=sat["tle1"],
                    tle2=sat["tle2"],
                    sat_name=sat["name"],
                )
            except Exception as exc:
                self.logger.warning("[%s] Overpass error while collecting precise-pass metadata: %s", sat.get("name"), exc)
                return []

            out = []
            for row in overpasses:
                try:
                    rise = datetime.strptime(row[4], "%Y-%m-%d %H:%M:%S")
                    max_time = datetime.strptime(row[5], "%Y-%m-%d %H:%M:%S")
                    set_ = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S")
                    max_elev = float(row[17])
                    out.append((sat, {"rise": rise, "max": max_time, "set": set_, "max_elev": max_elev, "raw_row": row}))
                except Exception as exc:
                    self.logger.warning("[%s] Malformed overpass row during precise-pass metadata collection: %s", sat.get("name"), exc)
            return out

        candidate_passes = []
        with ThreadPoolExecutor(max_workers=min(len(self.satellites) or 1, MAX_WORKERS)) as executor:
            futures = [executor.submit(collect_pass_metadata_for_sat, sat) for sat in self.satellites]
            for future in as_completed(futures):
                if self.is_cancelled():
                    executor.shutdown(wait=False)
                    return []
                result = future.result()
                if result:
                    candidate_passes.extend(result)

        if not candidate_passes or self.is_cancelled():
            return []

        max_times = []
        max_meta_refs = []
        for sat, meta in candidate_passes:
            if meta["max_elev"] < lowest_elev:
                continue
            max_times.append(meta["max"])
            max_meta_refs.append((sat, meta))

        if not max_times:
            return []

        times_pd = pd.to_datetime(max_times, utc=True, errors="coerce")
        notna_mask = ~pd.isna(times_pd)
        if not notna_mask.any():
            return []

        times_valid = times_pd[notna_mask]
        import time as _time
        t0 = _time.perf_counter()
        uniques, inverse = np.unique(times_valid.values, return_inverse=True)
        t1 = _time.perf_counter()
        self.logger.info(
            "Unique mapping for solar step: %d uniques (np.unique took %.3fs)",
            len(uniques),
            t1 - t0,
        )
        py_uniques = [pd.Timestamp(val).to_pydatetime() for val in uniques]
        obs_times = Time(py_uniques, scale="utc")
        altaz_frame = AltAz(obstime=obs_times, location=earth_location)
        sun_altaz = get_sun(obs_times).transform_to(altaz_frame)
        solar_zenith_uniques = 90.0 - np.array(sun_altaz.alt.deg)

        solar_zenith_flat_valid = solar_zenith_uniques[inverse]
        solar_zenith_flat = np.full(len(max_times), np.nan, dtype=float)
        solar_zenith_flat[np.where(notna_mask)[0]] = solar_zenith_flat_valid

        filtered_passes = []
        idx = 0
        for sat, meta in max_meta_refs:
            zenith = solar_zenith_flat[idx]
            idx += 1
            if np.isnan(zenith):
                continue
            if sun_zenith_lowest <= zenith <= sun_zenith_highest:
                filtered_passes.append((sat, meta))

        self.logger.info(
            "After solar coarse filter: %d passes remain (from %d)",
            len(filtered_passes),
            len(max_times),
        )

        if not filtered_passes or self.is_cancelled():
            return []

        margin_td = timedelta(minutes=self.margin)
        final_chunks = []
        for sat, meta in filtered_passes:
            if self.is_cancelled():
                return []
            start = max(start_dt, meta["rise"] - margin_td)
            end = min(end_dt, meta["set"] + margin_td)
            if start >= end:
                continue
            seconds = (end - start).total_seconds()
            steps = max(0, int(seconds // self.interval))
            time_values = [start + timedelta(seconds=i * self.interval) for i in range(steps + 1)]
            if time_values:
                final_chunks.append((sat, time_values))

        self.logger.info(
            "Final precise chunks after staged filtering: %d satellites/passes",
            len(final_chunks),
        )

        # Always return canonical (satellite, [times]) chunks so the GUI uses the
        # same effective chunked/vectorized precise backend workflow even for the
        # single-satellite case.
        return final_chunks
