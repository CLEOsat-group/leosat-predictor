"""Qt workers for the observation planner widget."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import QThread, pyqtSignal

from gui.helpers.tle_file_index import load_tle_file_index
from src.observation_planner.exceptions import ObservationPlanGenerationCancelled
from src.observation_planner.io import load_targets_json, load_visibility_file
from src.observation_planner.normalize import (
    filter_by_satellite,
    filter_by_targets,
    make_base_and_view,
    prepare_visibility_dataframe,
)
from src.observation_planner.planner import generate_observation_plan
from src.observation_planner.schema import resolve_column
from src.observation_planner.selector_plot_contract import prepare_selector_plot_payload


class ObservationPlannerWorker(QThread):
    """Base QThread with an error payload signal."""

    failed = pyqtSignal(str)

    def _emit_failure(self, exc: BaseException) -> None:
        """Emit a formatted failure message."""
        self.failed.emit(f"{exc}\n{traceback.format_exc()}")


class LoadVisibilityWorker(ObservationPlannerWorker):
    """Load and prepare a visibility-data file in a worker thread."""

    finished = pyqtSignal(object, object, object)

    def __init__(self, path: str | Path, parent=None, column_mapping=None):
        super().__init__(parent)
        self.path = Path(path)
        self.column_mapping = column_mapping

    def run(self) -> None:
        """Load the visibility file and emit master/base/view tables."""
        try:
            raw = load_visibility_file(self.path)
            data_master = prepare_visibility_dataframe(raw, column_mapping=self.column_mapping)
            data_base, data_view = make_base_and_view(data_master)
            self.finished.emit(data_master, data_base, data_view)
        except Exception as exc:
            self._emit_failure(exc)


class LoadVisibilityDataFrameWorker(ObservationPlannerWorker):
    """Prepare an in-memory visibility table in a worker thread.

    Parameters
    ----------
    dataframe : pandas.DataFrame
        Raw visibility table already held by the GUI. The worker applies the
        same normalization path used for file-backed visibility loads.
    parent : QObject, optional
        Parent Qt object.
    column_mapping : dict, optional
        Optional observation-planner column mapping.
    """

    finished = pyqtSignal(object, object, object)

    def __init__(self, dataframe: pd.DataFrame, parent=None, column_mapping=None):
        super().__init__(parent)
        self.dataframe = dataframe
        self.column_mapping = column_mapping

    def run(self) -> None:
        """Prepare the in-memory table and emit master/base/view tables."""
        try:
            data_master = prepare_visibility_dataframe(self.dataframe, column_mapping=self.column_mapping)
            data_base, data_view = make_base_and_view(data_master)
            self.finished.emit(data_master, data_base, data_view)
        except Exception as exc:
            self._emit_failure(exc)


class LoadTleFileWorker(ObservationPlannerWorker):
    """Load and index a TLE file in a worker thread.

    Parameters
    ----------
    path : str or pathlib.Path
        TLE text file path selected by the user or supplied by the precise
        prediction handoff.
    parent : QObject, optional
        Parent Qt object.
    """

    finished = pyqtSignal(object, object, str)

    def __init__(self, path: str | Path, parent=None):
        super().__init__(parent)
        self.path = Path(path)

    def run(self) -> None:
        """Parse the TLE file and emit the lookup index."""
        try:
            tle_index = load_tle_file_index(self.path)
            if len(tle_index) == 0:
                raise ValueError("No valid TLE entries found.")
            message = f"Loaded TLE file: {self.path} ({len(tle_index)} valid entries)."
            self.finished.emit(self.path, tle_index, message)
        except Exception as exc:
            self._emit_failure(exc)


class LoadTargetsWorker(ObservationPlannerWorker):
    """Load a selector-style JSON target file in a worker thread."""

    finished = pyqtSignal(object)

    def __init__(self, path: str | Path, parent=None, column_mapping=None):
        super().__init__(parent)
        self.path = Path(path)
        self.column_mapping = column_mapping

    def run(self) -> None:
        """Load target JSON and emit a flattened DataFrame."""
        try:
            self.finished.emit(load_targets_json(self.path))
        except Exception as exc:
            self._emit_failure(exc)


class ApplyTargetsWorker(ObservationPlannerWorker):
    """Apply or revert target filtering in a worker thread."""

    finished = pyqtSignal(bool, object, object)

    def __init__(self, data_master: pd.DataFrame, targets_df: pd.DataFrame | None, apply_targets: bool, parent=None):
        super().__init__(parent)
        self.data_master = data_master
        self.targets_df = targets_df
        self.apply_targets = apply_targets

    def run(self) -> None:
        """Apply/revert target filtering and emit base/view tables."""
        try:
            data_base, data_view = filter_by_targets(self.data_master, self.targets_df, apply_targets=self.apply_targets)
            self.finished.emit(self.apply_targets, data_base, data_view)
        except Exception as exc:
            self._emit_failure(exc)


class FilterSatelliteWorker(ObservationPlannerWorker):
    """Filter a base visibility table by satellite name."""

    finished = pyqtSignal(object)

    def __init__(self, data_base: pd.DataFrame, satellite_filter: str, parent=None):
        super().__init__(parent)
        self.data_base = data_base
        self.satellite_filter = satellite_filter

    def run(self) -> None:
        """Apply satellite filtering and emit the resulting view table."""
        try:
            self.finished.emit(filter_by_satellite(self.data_base, self.satellite_filter))
        except Exception as exc:
            self._emit_failure(exc)


class GeneratePlanWorker(ObservationPlannerWorker):
    """Generate an observation plan in a worker thread.

    The Observation Planner can run deterministic multi-start optimization for
    stratified sampling methods.  That work must not execute on the Qt GUI
    thread because a typical multi-start run may evaluate many complete
    candidate plans.  This worker keeps the shared planner core UI-neutral and
    returns the generated plan plus diagnostics to the controller.

    Parameters
    ----------
    visibility_df : pandas.DataFrame
        Current planner visibility table.
    targets_df : pandas.DataFrame or None
        Target table prepared by the controller.
    planner_kwargs : dict
        Keyword arguments passed directly to
        :func:`src.observation_planner.planner.generate_observation_plan`.
    parent : QObject, optional
        Parent Qt object.
    """

    finished = pyqtSignal(object, object)
    progress = pyqtSignal(str)
    canceled = pyqtSignal(str)

    def __init__(self, visibility_df: pd.DataFrame, targets_df: pd.DataFrame | None, planner_kwargs: dict, parent=None):
        super().__init__(parent)
        self.visibility_df = visibility_df
        self.targets_df = targets_df
        self.planner_kwargs = dict(planner_kwargs)
        self._cancel_requested = threading.Event()

    def request_cancel(self) -> None:
        """Request cooperative cancellation of plan generation.

        The worker does not terminate the Qt thread forcefully.  Instead, the
        shared planner core polls the callback supplied by :meth:`run` and
        raises a cancellation exception at safe checkpoints.
        """
        self._cancel_requested.set()
        self.requestInterruption()

    def _is_cancel_requested(self) -> bool:
        """Return whether cancellation was requested by the GUI thread."""
        return self._cancel_requested.is_set() or self.isInterruptionRequested()

    def run(self) -> None:
        """Generate the plan and emit ``(plan_df, diagnostics)``."""
        try:
            self.progress.emit("Plan worker: started observation-plan generation.")
            plan_df, diagnostics = generate_observation_plan(
                self.visibility_df,
                self.targets_df,
                return_diagnostics=True,
                progress_callback=self.progress.emit,
                cancel_callback=self._is_cancel_requested,
                **self.planner_kwargs,
            )
            self.progress.emit("Plan worker: generation core finished; publishing results.")
            self.finished.emit(plan_df, diagnostics)
        except ObservationPlanGenerationCancelled as exc:
            message = str(exc) or "Observation plan generation canceled."
            self.progress.emit(message)
            self.canceled.emit(message)
        except Exception as exc:
            self._emit_failure(exc)


class PrepareVisibilityPlotWorker(ObservationPlannerWorker):
    """Prepare compact visibility-plot data outside the GUI thread.

    Parameters
    ----------
    dataframe : pandas.DataFrame
        Current planner visibility view. The worker takes its deep snapshot in
        :meth:`run` so the GUI thread does not pay the copy cost.
    generation : int
        Monotonic request token used by the plot widget to reject stale results.
    parent : QObject, optional
        Parent Qt object.
    """

    prepared = pyqtSignal(int, object)
    preparationFailed = pyqtSignal(int, str)
    canceled = pyqtSignal(int)

    def __init__(self, dataframe: pd.DataFrame, generation: int, parent=None):
        super().__init__(parent)
        self.dataframe = dataframe
        self.generation = int(generation)
        self._cancel_requested = threading.Event()

    def request_cancel(self) -> None:
        """Request cooperative preparation cancellation."""

        self._cancel_requested.set()
        self.requestInterruption()

    def _is_cancel_requested(self) -> bool:
        """Return whether the GUI requested cooperative cancellation."""

        return self._cancel_requested.is_set() or self.isInterruptionRequested()

    def run(self) -> None:
        """Prepare and emit one immutable plain-data payload."""

        try:
            if self._is_cancel_requested():
                self.canceled.emit(self.generation)
                return
            snapshot = self.dataframe.copy(deep=True)
            payload = prepare_selector_plot_payload(
                snapshot,
                cancel_callback=self._is_cancel_requested,
            )
            if self._is_cancel_requested():
                self.canceled.emit(self.generation)
                return
            self.prepared.emit(self.generation, payload)
        except InterruptedError:
            self.canceled.emit(self.generation)
        except Exception as exc:
            self.preparationFailed.emit(
                self.generation,
                f"{exc}\n{traceback.format_exc()}",
            )
        finally:
            self.dataframe = pd.DataFrame()


def build_satellite_colors(dataframe: pd.DataFrame) -> dict[str, int]:
    """Build deterministic integer color indices for satellites.

    Parameters
    ----------
    dataframe : pandas.DataFrame
        Visibility table.

    Returns
    -------
    dict of str to int
        Mapping from satellite display name to color index. The plot widget
        converts these indices to pyqtgraph colors.
    """
    if dataframe is None or dataframe.empty:
        return {}
    satellite_col = resolve_column(dataframe, "satellite")
    satellites = list(dataframe[satellite_col].astype(str).unique())
    return {satellite: index for index, satellite in enumerate(satellites)}
