"""GUI prediction worker thread support."""

from multiprocessing import Event
import json
import logging
import os
from time import perf_counter

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal
from astropy import units as u
from astropy.coordinates import EarthLocation

from src.prediction_core.parallel_backend import SharedPredictionBackend
from src.utils.results_processor import apply_constraints, process_results

# Global cancellation event shared across GUI prediction workers.
global_cancel_event = Event()
global_cancel_event.clear()

logger = logging.getLogger(__name__)

PRECISE_INLINE_MAX_ROWS = int(os.getenv("SAVE_TO_FILE_MIN_ROWS", "10000"))
PRECISE_INLINE_MAX_BYTES = int(os.getenv("SAVE_TO_FILE_MIN_BYTES", str(1_000_000)))


def _select_precise_result_contract(raw_rows: list[list], unique_satellites: int | None = None) -> tuple[str, int]:
    """Select the GUI precise result materialization contract.

    The web predictor is the behavioral reference, but this GUI-only path
    preserves the observed web behavior for the verified single-satellite case
    by forcing inline/processed materialization there.

    Parameters
    ----------
    raw_rows : list[list]
        Raw finalized precise rows returned by the shared backend.
    unique_satellites : int | None, optional
        Number of unique satellites represented in ``raw_rows`` when already
        known cheaply by the caller.

    Returns
    -------
    tuple[str, int]
        Chosen contract name and the serialized size in bytes of the 10-row
        sample.
    """
    row_count = len(raw_rows)
    sample = raw_rows[:10]
    try:
        sample_bytes = len(json.dumps(sample, default=str))
    except Exception:
        sample_bytes = 0

    if unique_satellites == 1:
        return "inline_processed", sample_bytes

    should_use_raw_large_contract = (
        row_count >= PRECISE_INLINE_MAX_ROWS
        or sample_bytes >= PRECISE_INLINE_MAX_BYTES
    )
    contract = "raw_large" if should_use_raw_large_contract else "inline_processed"
    return contract, sample_bytes


class PredictionThread(QThread):
    """Execute GUI predictions in a worker thread."""

    finished = pyqtSignal(pd.DataFrame)
    error = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        lat,
        lon,
        alt,
        start_datetime,
        end_datetime=None,
        days=1,
        interval=1,
        satellites_list=None,
        mode="overpass",
        constraints=None,
        margin=5,
    ):
        super().__init__()
        self.lat = lat
        self.lon = lon
        self.alt = alt
        self.days = days
        self.interval = interval
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime
        self.satellites_list = satellites_list
        self.mode = mode
        self.constraints = constraints or {}
        self.margin_minutes = int(margin)
        self.results = pd.DataFrame()

    def run(self):
        """Run the GUI prediction workflow using the shared optimized backend."""
        global global_cancel_event
        global_cancel_event.clear()
        self.results = pd.DataFrame()

        try:
            if not self.satellites_list:
                raise ValueError("No satellites provided for prediction.")

            location = {"lat": self.lat, "lon": self.lon, "alt": self.alt}
            backend = SharedPredictionBackend(
                mode=self.mode,
                satellites=self.satellites_list,
                location=location,
                start_datetime=self.start_datetime,
                end_datetime=self.end_datetime,
                days=self.days,
                interval=self.interval,
                margin=self.margin_minutes,
                constraints=self.constraints,
                is_cancelled=lambda: global_cancel_event.is_set(),
                logger=logger,
            )

            backend_start = perf_counter()
            raw_result = backend.run()
            backend_elapsed = perf_counter() - backend_start

            if global_cancel_event.is_set():
                logger.info("PredictionThread: emitting cancelled state.")
                self.results = pd.DataFrame()
                self.cancelled.emit()
                return

            if not raw_result.rows:
                self.results = pd.DataFrame()
                self.error.emit("No prediction results found.")
                logger.error("No prediction results found.")
                return

            combined_results = pd.DataFrame(raw_result.rows, columns=raw_result.columns)
            logger.info(
                "PredictionThread: backend returned %d raw %s row(s) in %.3fs.",
                len(combined_results),
                self.mode,
                backend_elapsed,
            )
            if self.mode == "precise":
                logger.info(
                    "PredictionThread: precise backend stage complete; remaining time is materialization/filtering plus GUI handoff."
                )

            observer_location = EarthLocation(
                lat=self.lat * u.deg,
                lon=self.lon * u.deg,
                height=self.alt * u.m,
            )

            processing_start = perf_counter()
            if self.mode == "precise":
                unique_satellites = int(combined_results["Sat_ID"].nunique(dropna=True)) if "Sat_ID" in combined_results.columns else None
                precise_contract, sample_bytes = _select_precise_result_contract(
                    raw_result.rows,
                    unique_satellites=unique_satellites,
                )
                logger.info(
                    "PredictionThread: precise result contract=%s rows=%d unique_satellites=%s sample_bytes=%d thresholds(rows=%d, bytes=%d).",
                    precise_contract,
                    len(combined_results),
                    unique_satellites,
                    sample_bytes,
                    PRECISE_INLINE_MAX_ROWS,
                    PRECISE_INLINE_MAX_BYTES,
                )
                if precise_contract == "inline_processed":
                    final_results = process_results(
                        combined_results,
                        mode=self.mode,
                        constraints=self.constraints,
                        location=observer_location,
                    )
                    logger.info(
                        "PredictionThread: applied inline precise processing/filtering, rows %d -> %d (effective GUI/web parity path).",
                        len(combined_results),
                        len(final_results),
                    )
                else:
                    pre_filter_rows = len(combined_results)
                    final_results = combined_results
                    if self.constraints:
                        final_results = apply_constraints(final_results, self.constraints)
                    final_results = final_results.sort_values(by=["Sat_ID", "Obs_Time"]).reset_index(drop=True)
                    logger.info(
                        "PredictionThread: applied GUI-only multi-satellite precise displayed-result filtering, rows %d -> %d.",
                        pre_filter_rows,
                        len(final_results),
                    )
            else:
                final_results = process_results(
                    combined_results,
                    mode=self.mode,
                    constraints=self.constraints,
                    location=observer_location,
                )

            processing_elapsed = perf_counter() - processing_start
            logger.info(
                "PredictionThread: final %s materialization/filtering completed in %.3fs.",
                self.mode,
                processing_elapsed,
            )
            logger.info(
                "PredictionThread: emitting %d final %s row(s) to the GUI.",
                len(final_results),
                self.mode,
            )
            self.results = final_results
            self.finished.emit(final_results)

        except Exception as exc:  # pragma: no cover - defensive GUI worker guard
            self.results = pd.DataFrame()
            logger.error("PredictionThread: Error occurred - %s", exc)
            self.error.emit(str(exc))

    @staticmethod
    def stop():
        """Signal the thread to stop gracefully."""
        global global_cancel_event
        global_cancel_event.set()
        logger.info("PredictionThread: cancellation event set.")

