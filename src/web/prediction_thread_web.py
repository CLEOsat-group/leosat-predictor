import logging
import threading
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta

from astropy import units as u
from astropy.coordinates import EarthLocation

import os
import multiprocessing
import time as _time

# utility imported where calculate_timezone_offset is defined
from src.utils.time_utils import calculate_timezone_offset

from src.prediction_core.predict_utils import (
    compute_overpass_for_single_day,
    compute_precise_for_single_position, get_day_night_intervals, compute_solar_zenith, get_obs_range
)
from src.prediction_core.precise_materialization import vectorized_finalize_precise_results
from src.web.redis_task_store import store_task_result, update_task_status, get_task_status

# Per-worker process pool size (used by ProcessPoolExecutor)
# Defaults to environment variable set by run_server.py or fallback to cpu_count()-1
try:
    MAX_WORKERS = int(os.getenv("PREDICT_MAX_WORKERS", "0"))
    if MAX_WORKERS <= 0:
        MAX_WORKERS = max(1, multiprocessing.cpu_count() - 1)
except Exception:
    MAX_WORKERS = 1

# How many times to allow per worker task before chunking
MAX_TIMES_PER_TASK = int(os.getenv("MAX_TIMES_PER_TASK", "5000"))

# Target samples per job (can be tuned via env)
TARGET_SAMPLES_PER_JOB = int(os.getenv("TARGET_SAMPLES_PER_JOB", "5000"))

logger = logging.getLogger(__name__)

def process_overpass_chunk(sat, time_range, location):

    return compute_overpass_for_single_day(
        start_time=time_range[0],
        end_time=time_range[1],
        lat=location["lat"],
        lon=location["lon"],
        alt=location["alt"],
        tle1=sat["tle1"],
        tle2=sat["tle2"],
        sat_name=sat["name"]
    )

def process_precise_point(args):
    time_val, sat, loc_dict = args
    loc = EarthLocation(lat=loc_dict["lat"] * u.deg,
                        lon=loc_dict["lon"] * u.deg,
                        height=loc_dict["alt"])
    return compute_precise_for_single_position(
        time_val=time_val,
        obs_lon=loc_dict["lon"],
        obs_lat=loc_dict["lat"],
        obs_alt=loc_dict["alt"] / 1000.0,
        loc=loc,
        tle1=sat["tle1"],
        tle2=sat["tle2"],
        sat_name=sat["name"]
    )

# Light-weight worker: only uses pyorbital and math; no Astropy/ERFA inside workers.
def _run_job_worker_light(args):
    """
    Lightweight worker that only uses pyorbital/own math and returns geometry rows.
    args: (job_list, loc_dict, margin_minutes, timezone_offset)
    job_list: list of (sat, times_list)
    returns: list of simple tuples (sat_name, naive_datetime, sat_az, sat_elev, sat_lon, sat_lat, sat_alt, dist_km)
    """
    job_list, loc_dict, margin_minutes, timezone_offset = args
    out = []
    try:
        from pyorbital.orbital import Orbital
    except Exception:
        # If pyorbital isn't available, return empty quickly
        return out

    for sat, times in job_list:
        tle1 = sat.get("tle1")
        tle2 = sat.get("tle2")
        sat_name = sat.get("name")
        try:
            orbital = Orbital(satellite=sat_name, line1=tle1, line2=tle2)
        except Exception:
            # If pyorbital init fails, skip this satellite
            continue

        for t in times:
            try:
                # pyorbital expects naive UTC datetimes
                sat_az, sat_elev = orbital.get_observer_look(utc_time=t,
                                                             lon=loc_dict["lon"],
                                                             lat=loc_dict["lat"],
                                                             alt=loc_dict["alt"] / 1000.0)
                sat_lon, sat_lat, sat_alt = orbital.get_lonlatalt(t)
                dist = get_obs_range(sat_elev, sat_alt, loc_dict["alt"] / 1000.0, loc_dict["lat"])
                out.append((sat_name, t, float(sat_az), float(sat_elev), float(sat_lon), float(sat_lat), float(sat_alt), float(dist)))
            except Exception:
                # skip single times robustly
                continue
    return out


def build_worker_batches(chunks, location, margin_minutes, timezone_offset, max_times_per_subtask=MAX_TIMES_PER_TASK,
                         target_samples_per_job=TARGET_SAMPLES_PER_JOB, max_jobs: int | None = None):
    """
    Convert (sat, times_list) chunks into balanced worker argument batches.

    Returns list of worker_args:
      Each element is one tuple to send to a worker process:
        ( [ (sat, times_slice), (sat2, times_slice2), ... ], location, margin_minutes, timezone_offset )
    """
    # 1) split large per-sat lists into subtasks of size <= max_times_per_subtask
    subtasks = []
    for sat, times in chunks:
        if not times:
            continue
        if len(times) <= max_times_per_subtask:
            subtasks.append((sat, times))
        else:
            for i in range(0, len(times), max_times_per_subtask):
                subtasks.append((sat, times[i:i + max_times_per_subtask]))

    if not subtasks:
        return []

    # 2) Greedy pack into jobs by sample-count (largest-first to improve packing)
    subtasks.sort(key=lambda x: len(x[1]), reverse=True)
    jobs = []  # list of job lists
    jobs_size = []

    for sat, times in subtasks:
        n = len(times)
        placed = False
        for j_idx, size in enumerate(jobs_size):
            if size + n <= target_samples_per_job:
                jobs[j_idx].append((sat, times))
                jobs_size[j_idx] += n
                placed = True
                break
        if not placed:
            jobs.append([(sat, times)])
            jobs_size.append(n)

    # optional: if max_jobs set, merge jobs further
    if max_jobs and len(jobs) > max_jobs:
        while len(jobs) > max_jobs:
            a = jobs.pop()
            b = jobs.pop()
            jobs.append(b + a)
            jobs_size = [sum(len(t[1]) for t in job) for job in jobs]

    # Build worker_args list
    worker_args = []
    for job in jobs:
        worker_args.append((job, location, margin_minutes, timezone_offset))

    return worker_args


def vectorized_finalize_results(
    geom_rows,
    location,
    timezone_offset,
    constraints=None,
    prefilter_before_ra_dec=False,
):
    """Legacy compatibility wrapper for the shared precise materializer."""
    if constraints is None and not prefilter_before_ra_dec:
        return vectorized_finalize_precise_results(geom_rows, location, timezone_offset)
    return vectorized_finalize_precise_results(
        geom_rows,
        location,
        timezone_offset,
        constraints=constraints,
        prefilter_before_ra_dec=prefilter_before_ra_dec,
    )


def vectorized_finalize_results_new(
    geom_rows,
    location,
    timezone_offset,
    constraints=None,
    prefilter_before_ra_dec=False,
):
    """Compatibility wrapper for the shared precise materializer.

    Web and GUI precise prediction now use the same implementation in
    ``src.prediction_core.precise_materialization``.
    """
    if constraints is None and not prefilter_before_ra_dec:
        return vectorized_finalize_precise_results(geom_rows, location, timezone_offset)
    return vectorized_finalize_precise_results(
        geom_rows,
        location,
        timezone_offset,
        constraints=constraints,
        prefilter_before_ra_dec=prefilter_before_ra_dec,
    )


def _format_ra_vectorized(ra_deg):
    """Vectorized RA formatting (degrees to HMS)."""
    import numpy as np
    ra_hours = ra_deg / 15.0
    hours = np.floor(ra_hours).astype(int)
    minutes_frac = (ra_hours - hours) * 60
    minutes = np.floor(minutes_frac).astype(int)
    seconds = (minutes_frac - minutes) * 60
    return np.array([f"{h:02d}:{m:02d}:{s:05.2f}" for h, m, s in zip(hours, minutes, seconds)])


def _format_dec_vectorized(dec_deg):
    """Vectorized Dec formatting (degrees to DMS)."""
    import numpy as np
    sign = np.sign(dec_deg)
    abs_dec = np.abs(dec_deg)
    degrees = np.floor(abs_dec).astype(int)
    minutes_frac = (abs_dec - degrees) * 60
    minutes = np.floor(minutes_frac).astype(int)
    seconds = (minutes_frac - minutes) * 60
    sign_char = np.where(sign < 0, '-', '+')
    return np.array([f"{s}{d:02d}:{m:02d}:{sec:05.2f}" for s, d, m, sec in zip(sign_char, degrees, minutes, seconds)])


class PredictionThreadWeb:
    def __init__(self, task_id, mode, satellites, location,
                 start_datetime, end_datetime, days, interval,
                 margin, constraints):
        self.task_id = task_id
        self.mode = mode
        self.satellites = satellites
        self.location = location
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime
        self.days = days
        self.interval = interval
        self.margin = margin
        self.constraints = constraints or {}

        self.results = []
        self.error = None
        self.logger = logging.getLogger(__name__)
        self.thread = threading.Thread(target=self._run_task)

    def start(self):
        self.logger.info(f"Starting thread for task {self.task_id}")
        self.thread.start()

    def is_alive(self):
        return self.thread.is_alive()

    def is_cancelled(self):
        return get_task_status(self.task_id) == "cancelled"

    def join(self, timeout=None):
        if self.thread:
            self.thread.join(timeout)
            return not self.thread.is_alive()
        return True

    def _run_task(self):
        try:
            self.logger.info(f"Starting {self.mode} prediction task {self.task_id}")
            update_task_status(self.task_id, status="running")

            if self.mode == "overpass":
                self.results = self._run_parallel_overpass()
            elif self.mode == "precise":
                self.results = self._run_parallel_precise()
            else:
                raise ValueError(f"Unsupported mode: {self.mode}")

            if self.is_cancelled():
                self.logger.info(f"Task {self.task_id} was canceled")
                update_task_status(self.task_id, status="cancelled")
                return

            # Result handling is done by the watcher thread in PredictionManager
            # to avoid double-writes. We simply leave self.results populated.
            # safe to return now.

        except Exception as e:
            self.error = str(e)
            update_task_status(self.task_id, "error")
            self.logger.exception(f"[{self.task_id}] Prediction failed: {e}")

    def _run_parallel_overpass(self):
        chunks = self._distribute_overpass_threaded()
        self.logger.info(f"Distributed {len(chunks)} chunks for overpass prediction.")

        if not chunks:
            return []

        if self.is_cancelled():
            self.logger.info(f"[{self.task_id}] Task canceled before processing could start")
            return []

        all_results = []
        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = []
            for sat, time_range in chunks:
                # self.logger.info(get_task_status(task_id=self.task_id))
                if self.is_cancelled():
                    self.logger.info(f"[{self.task_id}] Cancellation detected from Redis")
                    executor.shutdown(wait=False)
                    return []
                futures.append(executor.submit(process_overpass_chunk, sat, time_range, self.location))

            for f in as_completed(futures):
                if self.is_cancelled():
                    executor.shutdown(wait=False)
                    return []
                result = f.result()
                all_results.extend(result if isinstance(result, list) else [result])

        if self.is_cancelled():
            self.logger.info(f"Task {self.task_id} was canceled")
            return []
        else:
            self.logger.info(f"Task {self.task_id} completed with {len(all_results)} results")
            return all_results

    def _run_parallel_precise(self):
        self.logger.info(get_task_status(task_id=self.task_id))
        chunks = self._distribute_precise_threaded()
        self.logger.info(f"Distributed {len(chunks)} precise positions for prediction")

        if not chunks:
            return []

        if self.is_cancelled():
            self.logger.info(f"[{self.task_id}] Task canceled before processing could start")
            return []

        # single-satellite / per-time chunking: keep using ThreadPoolExecutor for light per-time calls
        if isinstance(chunks[0], tuple) and isinstance(chunks[0][0], datetime):
            self.logger.info("Running precise prediction: single-satellite, per-time chunking")
            all_results = []
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = []
                for args in chunks:
                    if self.is_cancelled():
                        executor.shutdown(wait=False)
                        return []
                    futures.append(executor.submit(process_precise_point, args))

                for f in as_completed(futures):
                    if self.is_cancelled():
                        executor.shutdown(wait=False)
                        return []
                    try:
                        res = f.result()
                        if res:
                            all_results.extend(res)
                    except Exception as e:
                        self.logger.exception(f"Per-time worker failed: {e}")

            if self.is_cancelled():
                return []
            return all_results

        # multi-satellite case: use ProcessPoolExecutor with batched lightweight workers and vectorized finalizer
        self.logger.info("Running precise prediction: multi-satellite, per-satellite chunking (process pool)")

        # Build worker jobs (packing)
        timezone_offset = calculate_timezone_offset()
        final_chunks = chunks  # chunks are (sat, [times]) pairs

        total_samples = sum(len(times) for _, times in final_chunks)
        worker_jobs = build_worker_batches(
            chunks=final_chunks,
            location=self.location,
            margin_minutes=self.margin,
            timezone_offset=timezone_offset,
            max_times_per_subtask=MAX_TIMES_PER_TASK,
            target_samples_per_job=TARGET_SAMPLES_PER_JOB,
            max_jobs=None
        )

        n_cpus = multiprocessing.cpu_count()
        n_workers = min(MAX_WORKERS, max(1, n_cpus), max(1, len(worker_jobs)))

        self.logger.info(f"[{self.task_id}] Submitting {len(worker_jobs)} worker jobs (n_workers={n_workers}) total_samples={total_samples} target_job_samples={TARGET_SAMPLES_PER_JOB}")

        all_geom_rows = []
        t_submit = _time.perf_counter()

        with ProcessPoolExecutor(max_workers=n_workers) as pexec:
            future_to_meta = {}
            for jidx, job_arg in enumerate(worker_jobs):
                # job_arg is (job_list, location, margin, tz)
                try:
                    samples_in_job = sum(len(times) for sat, times in job_arg[0])
                except Exception:
                    samples_in_job = 0
                fut = pexec.submit(_run_job_worker_light, job_arg)
                future_to_meta[fut] = {"idx": jidx, "samples": samples_in_job, "t0": _time.perf_counter()}

            for fut in as_completed(future_to_meta):
                meta = future_to_meta[fut]
                elapsed = _time.perf_counter() - meta["t0"]
                jidx = meta["idx"]
                samples = meta["samples"]
                try:
                    res = fut.result()
                    returned = len(res) if res else 0
                    self.logger.info(f"[{self.task_id}] Job finished: samples={samples} elapsed={elapsed:.3f}s returned={returned} rows")
                    if res:
                        all_geom_rows.extend(res)
                except Exception as e:
                    self.logger.exception(f"[{self.task_id}] Job {jidx} failed after {elapsed:.3f}s: {e}")

        t_total = _time.perf_counter() - t_submit
        self.logger.info(f"[{self.task_id}] All jobs complete: total_results={len(all_geom_rows)} elapsed={t_total:.3f}s")

        t_submit = _time.perf_counter()

        # # Finalize with vectorized Astropy transforms in parent thread
        # final_results = vectorized_finalize_results(all_geom_rows, self.location, timezone_offset)
        #
        # t_total = _time.perf_counter() - t_submit
        # self.logger.info(f"[{self.task_id}] Finalization complete: final_results={len(final_results)} elapsed={t_total:.3f}s")
        # t_submit = _time.perf_counter()

        # Finalize with vectorized Astropy transforms in parent thread
        final_results = vectorized_finalize_results_new(
            all_geom_rows,
            self.location,
            timezone_offset,
            constraints=self.constraints,
            prefilter_before_ra_dec=True,
        )

        t_total = _time.perf_counter() - t_submit
        self.logger.info(f"[{self.task_id}] Finalization (new) complete: final_results={len(final_results)} elapsed={t_total:.3f}s")
        if self.is_cancelled():
            return []
        return final_results

    def _distribute_overpass_threaded(self):
        start_datetime = self.start_datetime
        if isinstance(start_datetime, str):
            start_datetime = datetime.fromisoformat(start_datetime)

        intervals = get_day_night_intervals(
            self.location["lat"],
            self.location["lon"],
            start_datetime,
            self.days,
            mode=self.constraints.get("prediction_range_overpass", "night")
        )

        def process_satellite_cancelable(sat):
            if self.is_cancelled():
                return []
            chunks = []
            for start, end in intervals:
                if self.is_cancelled():
                    return []
                chunks.append((sat, (start, end)))
            return chunks

        result_chunks = []
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(self.satellites) or 1)) as executor:
            futures = [executor.submit(process_satellite_cancelable, sat) for sat in self.satellites]
            for f in as_completed(futures):
                if self.is_cancelled():
                    executor.shutdown(wait=False)
                    return []
                result_chunks.extend(f.result())

        return result_chunks

    def _distribute_precise_threaded(self):
        """
        Produce (sat, [filtered_times]) chunks for precise prediction using staged filtering.
        """
        import numpy as np
        import pandas as pd
        from astropy.time import Time
        from astropy.coordinates import AltAz, get_sun
        from astropy import units as u

        lowest_elev = float(self.constraints.get("lowest_altitude_satellite", 30))
        sun_zenith_lowest = float(self.constraints.get('sun_zenith_lowest', 0))
        sun_zenith_highest = float(self.constraints.get('sun_zenith_highest', 180))

        earth_location = EarthLocation(
            lat=self.location["lat"] * u.deg,
            lon=self.location["lon"] * u.deg,
            height=self.location["alt"]
        )

        start_dt = self.start_datetime
        if isinstance(start_dt, str):
            start_dt = datetime.fromisoformat(start_dt)
        if self.end_datetime:
            end_dt = self.end_datetime if not isinstance(self.end_datetime, str) else datetime.fromisoformat(self.end_datetime)
        else:
            end_dt = start_dt + timedelta(days=self.days)

        def collect_pass_metadata_for_sat(sat):
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
                    sat_name=sat["name"]
                )
            except Exception as e:
                self.logger.warning(f"[{sat.get('name')}] Overpass error when collecting metadata: {e}")
                return []

            out = []
            for row in overpasses:
                try:
                    rise = datetime.strptime(row[4], "%Y-%m-%d %H:%M:%S")
                    max_time = datetime.strptime(row[5], "%Y-%m-%d %H:%M:%S")
                    set_ = datetime.strptime(row[6], "%Y-%m-%d %H:%M:%S")
                    max_elev = float(row[17])
                    out.append((sat, {"rise": rise, "max": max_time, "set": set_, "max_elev": max_elev, "raw_row": row}))
                except Exception as e:
                    self.logger.warning(f"[{sat.get('name')}] Malformed overpass row during metadata collection: {e}")
                    continue
            return out

        candidate_passes = []
        max_workers = min(len(self.satellites) or 1, MAX_WORKERS)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(collect_pass_metadata_for_sat, sat) for sat in self.satellites]
            for f in as_completed(futures):
                if self.is_cancelled():
                    ex.shutdown(wait=False)
                    return []
                res = f.result()
                if res:
                    candidate_passes.extend(res)

        if self.is_cancelled():
            return []

        if not candidate_passes:
            return []

        # vectorize max times
        max_times = []
        max_meta_refs = []
        for sat, meta in candidate_passes:
            if meta["max_elev"] < lowest_elev:
                continue
            max_times.append(meta["max"])
            max_meta_refs.append((sat, meta))

        if not max_times:
            return []

        times_pd = pd.to_datetime(max_times, utc=True, errors='coerce')
        notna_mask = ~pd.isna(times_pd)
        if not notna_mask.any():
            return []

        times_valid = times_pd[notna_mask]
        t0 = _time.perf_counter()
        uniques, inverse = np.unique(times_valid.values, return_inverse=True)
        t1 = _time.perf_counter()
        self.logger.info(f"Unique mapping for solar step: {len(uniques)} uniques (np.unique took {t1 - t0:.3f}s)")

        py_uniques = [pd.Timestamp(u).to_pydatetime() for u in uniques]
        obs_times = Time(py_uniques, scale='utc')
        altaz_frame = AltAz(obstime=obs_times, location=earth_location)
        sun_altaz = get_sun(obs_times).transform_to(altaz_frame)
        solar_zenith_uniques = 90.0 - np.array(sun_altaz.alt.deg)

        solar_zenith_flat_valid = solar_zenith_uniques[inverse]
        solar_zenith_flat = np.full(len(max_times), np.nan, dtype=float)
        solar_zenith_flat[np.where(notna_mask)[0]] = solar_zenith_flat_valid

        filtered_passes = []
        idx = 0
        for (sat, meta) in max_meta_refs:
            zen = solar_zenith_flat[idx]
            idx += 1
            if np.isnan(zen):
                continue
            if sun_zenith_lowest <= zen <= sun_zenith_highest:
                filtered_passes.append((sat, meta))
        self.logger.info(f"After solar coarse filter: {len(filtered_passes)} passes remain (from {len(max_times)})")

        if not filtered_passes:
            return []

        if self.is_cancelled():
            return []

        final_chunks = []
        margin_td = timedelta(minutes=self.margin)

        for sat, meta in filtered_passes:
            if self.is_cancelled():
                return []
            start = max(start_dt, meta["rise"] - margin_td)
            end = min(end_dt, meta["set"] + margin_td)
            if start >= end:
                continue
            seconds = (end - start).total_seconds()
            steps = max(0, int(seconds // self.interval))
            time_vals = [start + timedelta(seconds=i * self.interval) for i in range(steps + 1)]
            if time_vals:
                final_chunks.append((sat, time_vals))

        if self.is_cancelled():
            return []

        self.logger.info(f"Final precise chunks after staged filtering: {len(final_chunks)} satellites/passes")
        return final_chunks
