"""GUI-v2 Observation Planner coordinator.

Task 48D promotes the planner shell from load-only setup to a real,
controller-owned generation workflow.  The controller remains the single owner
of planner runtime state, worker lifetimes, checked-row synchronization, and
plan records while the GUI-v2 pages stay thin view adapters.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PyQt6.QtCore import QObject, pyqtSignal

from gui_v2.helpers.planner_export_naming import (
    MANUAL_PLAN_METHOD_TOKEN,
    UNKNOWN_PLAN_METHOD_TOKEN,
    normalize_planner_export_method,
)
from gui_v2.models.observation_plan_table_model import (
    GENERATED_SOURCE,
    MANUAL_SOURCE,
    ObservationPlanRecord,
    ObservationPlanTableModel,
    plan_record_key,
)
from gui_v2.workers.observation_planner_workers import (
    ApplyTargetsWorker,
    FilterSatelliteWorker,
    GeneratePlanWorker,
    LoadTargetsWorker,
    LoadTleFileWorker,
    LoadVisibilityDataFrameWorker,
    LoadVisibilityWorker,
    build_satellite_colors,
)
from src.observation_planner.normalize import ALL_SATELLITES_LABEL
from src.observation_planner.planner import JSON_TIMES_MODE
from src.observation_planner.preferences import (
    ObservationPlannerPreferences,
    default_observation_planner_preferences,
    from_preferences_dict,
)
from src.observation_planner.coordinate_format import normalize_coordinate_format
from src.observation_planner.export import (
    write_plan_csv,
    write_plan_diagnostics_sidecar,
    write_plan_txt,
)
from src.observation_planner.sampling import PLAN_METHOD_MAX_ELEVATION
from src.observation_planner.schema import resolve_column
from src.observation_planner.workflow import (
    ObservationPlannerRunRequest,
    prepare_observation_planner_run,
    refresh_observation_plan_diagnostics,
)

from gui_v2.state.planner_state import (
    PlannerDataReadiness,
    PlannerExportResult,
    PlannerGenerationStatus,
    PlannerLoadState,
    PlannerRuntimeSnapshot,
    PlannerRuntimeState,
    PlannerSelectionSnapshot,
)


_TABLE_ATTRS = {
    "data_master": "visibility_dataframe",
    "data_base": "base_dataframe",
    "data_view": "view_dataframe",
}


class PlannerController(QObject):
    """Own GUI-v2 planner runtime state, workers, and row synchronization."""

    stateChanged = pyqtSignal(object)
    logMessage = pyqtSignal(str)
    visibilityTableChanged = pyqtSignal(object)
    satellitesChanged = pyqtSignal(object)
    targetsAvailabilityChanged = pyqtSignal(bool, bool)
    loadStateChanged = pyqtSignal(str, str, str)
    failed = pyqtSignal(str, str)
    preferencesRequested = pyqtSignal()
    preferencesChanged = pyqtSignal(object)

    plotDataChanged = pyqtSignal(object, object)
    checkedRowsChanged = pyqtSignal(object)
    planRecordsChanged = pyqtSignal(object)
    diagnosticsChanged = pyqtSignal(object)
    observationInfoChanged = pyqtSignal(object, str)
    visibilitySelectionChanged = pyqtSignal(int)
    visibilityTableFocusRequested = pyqtSignal(int)
    planSelectionChanged = pyqtSignal(object)
    planGenerationStarted = pyqtSignal()
    planGenerationSucceeded = pyqtSignal(str)
    planGenerationCanceled = pyqtSignal(str)
    planGenerationFailed = pyqtSignal(str)
    planGenerationFinished = pyqtSignal()
    planGenerationProgress = pyqtSignal(str)
    exposureTimeChanged = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = PlannerRuntimeState()
        self._preferences = default_observation_planner_preferences()
        self._workers: list[object] = []
        self._generate_plan_worker: GeneratePlanWorker | None = None
        self._generation_token = 0
        self._plan_records: list[ObservationPlanRecord] = []
        self._selected_plan_record: ObservationPlanRecord | None = None
        self._last_spacing_min = float(getattr(self._preferences, "spacing_min", 3.0))
        self._exposure_time_seconds = float(getattr(self._preferences, "exposure_time_sec", 5.0))
        self._diagnostics_dirty_notice_logged = False
        self._pending_handoff_tle_source_path: Path | None = None
        self._satellite_color_indices: dict[str, int] = {}
        self._identity_positions: dict[str, dict[str, dict[object, int]]] = {
            table: {} for table in _TABLE_ATTRS
        }

    @property
    def runtime_state(self) -> PlannerRuntimeState:
        """Return the mutable runtime state holder."""
        return self._state

    @property
    def preferences(self) -> ObservationPlannerPreferences:
        """Return the current planner runtime preferences."""
        return self._preferences

    def current_snapshot(self) -> PlannerRuntimeSnapshot:
        """Return the current immutable planner snapshot."""
        return self._state.snapshot

    def plan_records(self) -> list[ObservationPlanRecord]:
        """Return a copy of the current generated/manual plan records."""
        return list(self._plan_records)

    def current_diagnostics(self) -> object | None:
        """Return the current planner diagnostics object without mutation."""
        return self._state.diagnostics

    def current_plan_export_method(self) -> str:
        """Return the filename token that truthfully describes the current plan.

        Returns
        -------
        str
            The canonical generated-plan method token while generated rows are
            present, ``"manual"`` for a manual-only plan, or
            ``"unknown-method"`` when no current plan can be classified.
        """
        has_generated_rows = any(record.source == GENERATED_SOURCE for record in self._plan_records)
        if has_generated_rows:
            return normalize_planner_export_method(self._state.snapshot.last_generated_plan_method)
        if self._plan_records:
            return MANUAL_PLAN_METHOD_TOKEN
        return UNKNOWN_PLAN_METHOD_TOKEN

    def diagnostics_available(self) -> bool:
        """Return whether diagnostics are current according to readiness state."""
        return bool(self._state.snapshot.readiness.diagnostics_available and self._state.diagnostics is not None)

    def set_preferences(self, preferences: Mapping[str, Any] | ObservationPlannerPreferences | None) -> None:
        """Set planner runtime preferences from the GUI-v2 preference tree."""
        if isinstance(preferences, ObservationPlannerPreferences):
            self._preferences = preferences
        elif isinstance(preferences, Mapping):
            self._preferences = from_preferences_dict(preferences)
        else:
            self._preferences = default_observation_planner_preferences()
        self._last_spacing_min = float(getattr(self._preferences, "spacing_min", self._last_spacing_min))
        self._exposure_time_seconds = float(getattr(self._preferences, "exposure_time_sec", self._exposure_time_seconds))
        coordinate_format = normalize_coordinate_format(
            getattr(self._preferences, "default_coordinate_format", self._state.snapshot.coordinate_format)
        )
        if coordinate_format != self._state.snapshot.coordinate_format:
            self._commit_snapshot(self._state.snapshot.with_updates(coordinate_format=coordinate_format))
        self.exposureTimeChanged.emit(self._exposure_time_seconds)
        self.preferencesChanged.emit(self._preferences)

    def request_preferences_page(self) -> None:
        """Request navigation to the editable planner preferences page."""
        self.preferencesRequested.emit()

    def set_status_message(self, message: str) -> PlannerRuntimeSnapshot:
        """Update the planner status message and notify listeners."""
        snapshot = self._state.update_snapshot(self._state.snapshot.with_status(message))
        self.stateChanged.emit(snapshot)
        return snapshot

    def append_log(self, message: str) -> PlannerRuntimeSnapshot:
        """Append a planner log message and notify listeners."""
        snapshot = self._state.update_snapshot(self._state.snapshot.with_log_line(message))
        self.logMessage.emit(message)
        self.stateChanged.emit(snapshot)
        return snapshot

    def reset(self) -> PlannerRuntimeSnapshot:
        """Reset the planner runtime to its empty setup state."""
        self.cancel_plan_generation()
        self._plan_records = []
        self._selected_plan_record = None
        self._diagnostics_dirty_notice_logged = False
        self._pending_handoff_tle_source_path = None
        self._satellite_color_indices = {}
        self._identity_positions = {table: {} for table in _TABLE_ATTRS}
        snapshot = self._state.reset()
        self.stateChanged.emit(snapshot)
        self.visibilityTableChanged.emit(pd.DataFrame())
        self.plotDataChanged.emit(pd.DataFrame(), {})
        self.satellitesChanged.emit([])
        self.targetsAvailabilityChanged.emit(False, False)
        self.planRecordsChanged.emit([])
        self.diagnosticsChanged.emit(None)
        self.observationInfoChanged.emit(None, "")
        return snapshot

    def load_visibility_file(self, path: str | Path) -> bool:
        """Load and prepare visibility data in a worker thread."""
        if self._generation_is_running():
            self.append_log("Cancel or finish plan generation before loading new visibility data.")
            return False
        file_path = Path(path)
        if not file_path.is_file():
            self._on_worker_failed(f"Visibility file does not exist: {file_path}", "visibility")
            return False
        self._pending_handoff_tle_source_path = None
        self._set_load_state("visibility", PlannerLoadState.LOADING, detail=str(file_path))
        self._commit_snapshot(
            self._state.snapshot.with_updates(
                visibility_file_path=str(file_path),
                tle_file_path=None,
                target_file_path=self._state.snapshot.target_file_path,
                generation_status=PlannerGenerationStatus.LOADING,
                status_message=f"Loading visibility data: {file_path}",
                readiness=replace(
                    self._state.snapshot.readiness,
                    visibility_loaded=False,
                    tle_loaded=False,
                    plan_available=False,
                    diagnostics_available=False,
                ),
            )
        )
        self._state.tle_index = None
        self._clear_plan_records(emit=True, clear_checks=False)
        self.append_log(f"Loading visibility data: {file_path}")
        worker = LoadVisibilityWorker(file_path, self, column_mapping=self._preferences.column_mapping)
        worker.finished.connect(lambda master, base, view, p=file_path: self._on_visibility_loaded(p, master, base, view))
        worker.failed.connect(lambda message: self._on_worker_failed(message, "visibility"))
        self._start_worker(worker)
        return True

    def load_visibility_dataframe(
        self,
        dataframe: pd.DataFrame,
        *,
        source_label: str | None = None,
        tle_source_path: str | Path | None = None,
    ) -> bool:
        """Load in-memory visibility data from precise handoff.

        This mirrors the GUI-v1 precise-to-planner handoff boundary: the
        completed precise result projection is normalized by the same planner
        worker path used for file-backed visibility data, and an associated TLE
        file is loaded afterwards only for Observation Info / Copy TLE support.
        TLE loading never gates generation readiness.
        """
        if self._generation_is_running():
            self.append_log("Cancel or finish plan generation before loading precise handoff data.")
            return False
        if dataframe is None or getattr(dataframe, "empty", True):
            self.append_log("No precise visibility data were available for planner handoff.")
            return False

        label = source_label or "Precise Prediction"
        self._pending_handoff_tle_source_path = Path(tle_source_path) if tle_source_path else None
        self._set_load_state("visibility", PlannerLoadState.LOADING, detail=label)
        self._commit_snapshot(
            self._state.snapshot.with_updates(
                visibility_file_path=label,
                tle_file_path=None,
                target_file_path=self._state.snapshot.target_file_path,
                generation_status=PlannerGenerationStatus.LOADING,
                status_message=f"Loading visibility data from {label}.",
                readiness=replace(
                    self._state.snapshot.readiness,
                    visibility_loaded=False,
                    tle_loaded=False,
                    plan_available=False,
                    diagnostics_available=False,
                ),
            )
        )
        self._state.tle_index = None
        self._clear_plan_records(emit=True, clear_checks=False)
        self.append_log(f"Loading visibility data from {label}: {len(dataframe)} rows.")
        worker = LoadVisibilityDataFrameWorker(
            dataframe,
            self,
            column_mapping=self._preferences.column_mapping,
        )
        worker.finished.connect(lambda master, base, view, p=label: self._on_visibility_loaded(p, master, base, view))
        worker.failed.connect(lambda message: self._on_worker_failed(message, "visibility"))
        self._start_worker(worker)
        return True

    def load_tle_file(self, path: str | Path) -> bool:
        """Load a TLE file for Observation Info copy support.

        TLE loading intentionally does not gate observation-plan generation.
        The loaded index is used only to populate the Copy TLE action for a
        selected observation, matching the GUI-v1 planner workflow.
        """
        if not self._state.snapshot.readiness.visibility_loaded:
            self.append_log("Load visibility data before loading a TLE file.")
            return False
        if self._generation_is_running():
            self.append_log("Cancel or finish plan generation before loading a new TLE file.")
            return False
        file_path = Path(path)
        if not file_path.is_file():
            self._on_worker_failed(f"TLE file does not exist: {file_path}", "tle")
            return False
        self._set_load_state("tle", PlannerLoadState.LOADING, detail=str(file_path))
        self.append_log(f"Loading TLE file: {file_path}")
        worker = LoadTleFileWorker(file_path, self)
        worker.finished.connect(self._on_tle_loaded)
        worker.failed.connect(lambda message: self._on_worker_failed(message, "tle"))
        self._start_worker(worker)
        return True

    def load_targets_file(self, path: str | Path) -> bool:
        """Load optional target JSON in a worker thread."""
        if self._generation_is_running():
            self.append_log("Cancel or finish plan generation before loading new targets.")
            return False
        file_path = Path(path)
        if not file_path.is_file():
            self._on_worker_failed(f"Target JSON file does not exist: {file_path}", "targets")
            return False
        self._set_load_state("targets", PlannerLoadState.LOADING, detail=str(file_path))
        self.append_log(f"Loading targets: {file_path}")
        worker = LoadTargetsWorker(file_path, self, column_mapping=self._preferences.column_mapping)
        worker.finished.connect(lambda targets, p=file_path: self._on_targets_loaded(p, targets))
        worker.failed.connect(lambda message: self._on_worker_failed(message, "targets"))
        self._start_worker(worker)
        return True

    def apply_or_revert_targets(self, checked: bool) -> bool:
        """Apply or revert loaded target filtering."""
        if self._generation_is_running():
            self.append_log("Cancel or finish plan generation before changing target filtering.")
            return False
        if self._state.visibility_dataframe is None:
            self.append_log("No visibility data loaded. Cannot apply targets.")
            return False
        if self._state.target_dataframe is None:
            self.append_log("No target JSON loaded. Cannot apply targets.")
            return False
        self.append_log("Applying JSON targets…" if checked else "Reverting target filter…")
        worker = ApplyTargetsWorker(self._state.visibility_dataframe, self._state.target_dataframe, checked, self)
        worker.finished.connect(self._on_targets_applied)
        worker.failed.connect(lambda message: self._on_worker_failed(message, "targets"))
        self._start_worker(worker)
        return True

    def filter_by_satellite(self, satellite_filter: str) -> bool:
        """Filter the current base visibility table by satellite name."""
        if self._state.base_dataframe is None:
            return False
        if self._generation_is_running():
            self.append_log("Cancel or finish plan generation before changing the satellite filter.")
            return False
        worker = FilterSatelliteWorker(self._state.base_dataframe, satellite_filter, self)
        worker.finished.connect(lambda view, label=satellite_filter: self._on_satellite_filtered(label, view))
        worker.failed.connect(lambda message: self._on_worker_failed(message, "satellite filter"))
        self._start_worker(worker)
        return True

    def generate_plan(
        self,
        *,
        use_json_times: bool,
        tolerance_sec: int,
        spacing_min: float,
        min_elevation: float,
        time_range_sec: int | float = 0,
        plan_method: str = PLAN_METHOD_MAX_ELEVATION,
        binning_mode: str | None = None,
        sample_bins: int | None = None,
        bin_width_deg: float | None = None,
    ) -> bool:
        """Start observation-plan generation on a worker thread.

        Parameters
        ----------
        use_json_times : bool
            Whether the run should use loaded JSON target times.
        tolerance_sec : int
            Matching tolerance for JSON-time mode, in seconds.
        spacing_min : float
            Minimum spacing between observations, in minutes.
        min_elevation : float
            Minimum accepted satellite elevation, in degrees.
        time_range_sec : int or float, optional
            Additional time-range window used by the backend.
        plan_method : str, optional
            Planner method identifier.
        binning_mode : str, optional
            Sampling binning mode for stratified methods.
        sample_bins : int, optional
            Per-run bin count override.
        bin_width_deg : float, optional
            Per-run fixed-width bin size override.

        Returns
        -------
        bool
            `True` when a worker was started, otherwise `False`.
        """
        if not self._state.snapshot.readiness.ready_for_generation:
            self.append_log("Load visibility data before generating an observation plan.")
            return False
        if self._state.base_dataframe is None or self._state.base_dataframe.empty:
            self.append_log("No visibility rows are available for plan generation.")
            return False
        if self._generation_is_running():
            self.append_log("Observation plan generation is already running.")
            return False

        self._last_spacing_min = float(spacing_min)
        request = ObservationPlannerRunRequest(
            use_json_times=bool(use_json_times),
            tolerance_sec=int(tolerance_sec),
            spacing_min=float(spacing_min),
            min_elevation=float(min_elevation),
            time_range_sec=time_range_sec,
            plan_method=plan_method,
            binning_mode=binning_mode,
            sample_bins=sample_bins,
            bin_width_deg=bin_width_deg,
            preferences=self._preferences,
        )
        try:
            prepared_run = prepare_observation_planner_run(
                self._state.base_dataframe,
                self._state.target_dataframe,
                request,
            )
        except ValueError as exc:
            self.append_log(str(exc))
            self._commit_snapshot(self._state.snapshot.with_status(str(exc), last_error=str(exc)))
            return False

        for setup_message in prepared_run.messages:
            self.append_log(setup_message)

        token = self._next_generation_token()
        worker = GeneratePlanWorker(prepared_run.visibility_df, prepared_run.targets_df, prepared_run.planner_kwargs, self)
        worker.progress.connect(self._on_plan_worker_progress)
        worker.finished.connect(
            lambda plan_df, diagnostics, token=token: self._on_plan_worker_finished(
                token,
                plan_df,
                diagnostics,
                mode=prepared_run.mode,
                plan_method=prepared_run.normalized_plan_method,
                spacing_min=float(spacing_min),
                min_elevation=float(min_elevation),
                time_range_sec=time_range_sec,
            )
        )
        worker.failed.connect(lambda message, token=token: self._on_plan_worker_failed(token, message))
        worker.canceled.connect(lambda message, token=token: self._on_plan_worker_canceled(token, message))
        self._generate_plan_worker = worker
        self._start_worker(worker)

        readiness = replace(self._state.snapshot.readiness, diagnostics_available=False)
        snapshot = self._state.snapshot.with_updates(
            generation_status=PlannerGenerationStatus.GENERATING,
            readiness=readiness,
            status_message="Generating observation plan…",
            last_error=None,
        )
        self._commit_snapshot(snapshot)
        self.planGenerationStarted.emit()
        self.append_log(
            (
                "Generating observation plan… "
                f"method={prepared_run.normalized_plan_method}, metric={prepared_run.metric}, "
                f"rows={len(prepared_run.visibility_df)}, spacing={spacing_min} min, "
                f"minimum_elevation={min_elevation}°, mode={prepared_run.mode}."
            )
        )
        return True

    def cancel_plan_generation(self) -> bool:
        """Request cooperative cancellation of the active plan-generation worker.

        Returns
        -------
        bool
            `True` when a running worker was asked to cancel.
        """
        worker = self._generate_plan_worker
        if worker is None:
            return False
        try:
            if not worker.isRunning():
                self._generate_plan_worker = None
                return False
            worker.request_cancel()
        except RuntimeError:
            self._generate_plan_worker = None
            return False
        snapshot = self._state.snapshot.with_updates(
            generation_status=PlannerGenerationStatus.CANCELING,
            status_message="Cancel requested; waiting for planner checkpoint…",
        )
        self._commit_snapshot(snapshot)
        self.planGenerationProgress.emit("Cancel requested; waiting for planner checkpoint…")
        self.append_log("Cancel requested; waiting for planner checkpoint…")
        return True

    def set_coordinate_format(self, coordinate_format: str | None) -> PlannerRuntimeSnapshot:
        """Store the selected RA/DEC coordinate format in planner state."""
        value = normalize_coordinate_format(coordinate_format)
        snapshot = self._state.snapshot.with_updates(coordinate_format=value)
        return self._commit_snapshot(snapshot)

    def set_exposure_time_seconds(self, seconds: int | float) -> None:
        """Store and publish the exposure-time value used by Observation Info."""
        try:
            value = max(0.0, float(seconds))
        except (TypeError, ValueError):
            value = 0.0
        self._exposure_time_seconds = value
        self.exposureTimeChanged.emit(value)

    def exposure_time_seconds(self) -> float:
        """Return the current exposure time used by Observation Info."""
        return self._exposure_time_seconds

    def add_or_remove_manual_row(self, row: int, checked: bool, *, spacing_min: float | None = None) -> bool:
        """Add or remove a manual plan row from a visibility-table checkbox.

        Parameters
        ----------
        row : int
            Current view-table row index.
        checked : bool
            Target checkbox state requested by the user.
        spacing_min : float, optional
            Current spacing control value used for diagnostics refresh.

        Returns
        -------
        bool
            `True` when the plan was changed or re-synchronized.
        """
        dataframe = self._state.view_dataframe
        if not isinstance(dataframe, pd.DataFrame) or row < 0 or row >= len(dataframe):
            return False
        try:
            record = self._record_from_dataframe_row(dataframe, int(row), source=MANUAL_SOURCE)
        except Exception as exc:
            self.append_log(f"Unable to convert selected visibility row to a plan record: {exc}")
            return False
        return self.add_or_remove_manual_record(record, checked, spacing_min=spacing_min)

    def add_or_remove_manual_record(
        self,
        record: ObservationPlanRecord,
        checked: bool,
        *,
        spacing_min: float | None = None,
    ) -> bool:
        """Add or remove a manual observation-plan record."""
        if spacing_min is not None:
            self._last_spacing_min = float(spacing_min)
        changed = False
        matching_manual = self.matching_record_index(self._plan_records, record, source=MANUAL_SOURCE)
        matching_any = self.matching_record_index(self._plan_records, record)
        if checked:
            if matching_any is None:
                self._plan_records.append(record)
                self._sort_plan_records()
                changed = True
            updates = self.set_record_checked(record, True)
            status_message = "Manual observation added."
        else:
            remove_index = matching_any
            if remove_index is not None:
                removed = self._plan_records.pop(remove_index)
                changed = True
                if self._same_record(self._selected_plan_record, removed):
                    self._selected_plan_record = None
                    self.observationInfoChanged.emit(None, "")
                    self.planSelectionChanged.emit(None)
            still_present = self.matching_record_index(self._plan_records, record) is not None
            updates = self.set_record_checked(record, still_present)
            status_message = "Observation removed from plan."

        self.checkedRowsChanged.emit(updates)
        if changed:
            self._publish_plan_records(status_message)
            self._mark_diagnostics_stale_after_plan_edit()
        return True

    def select_visibility_row(self, row: int) -> None:
        """Publish current visibility-row selection and plot highlight."""
        if row < 0:
            return
        snapshot = self._state.snapshot.with_updates(
            selected=PlannerSelectionSnapshot(visibility_identity=int(row), plan_identity=self._state.snapshot.selected.plan_identity)
        )
        self._commit_snapshot(snapshot)
        self.visibilitySelectionChanged.emit(int(row))

    def focus_visibility_row(self, row: int) -> None:
        """Select a visibility row and request table focus for external sources.

        Plot-point selection should scroll/focus the setup table like GUI-v1.
        Plain table row selection must not echo back into the same table because
        that causes unnecessary scrolling and can make large tables feel stuck.
        """
        self.select_visibility_row(row)
        self.visibilityTableFocusRequested.emit(int(row))

    def select_plan_record(self, record: ObservationPlanRecord | None) -> None:
        """Store and highlight the selected plan-table record."""
        self._selected_plan_record = record
        snapshot = self._state.snapshot.with_updates(
            selected=PlannerSelectionSnapshot(
                visibility_identity=self._state.snapshot.selected.visibility_identity,
                plan_identity=self._record_key(record) if record is not None else None,
            )
        )
        self._commit_snapshot(snapshot)
        self.planSelectionChanged.emit(record)

    def select_current_plan_observation(self) -> bool:
        """Send the selected plan row to the Observation Info workspace."""
        record = self._selected_plan_record
        if record is None:
            self.append_log("Select a generated-plan row before using Select Observation.")
            return False
        tle_text = self._tle_clipboard_text_for_satellite(record.satellite)
        self.observationInfoChanged.emit(record, tle_text)
        self.append_log(f"Selected observation: {record.satellite} at {record.date_ut}.")
        return True

    def remove_selected_plan_record(self, *, spacing_min: float | None = None) -> bool:
        """Remove the selected observation from the current plan."""
        record = self._selected_plan_record
        if record is None:
            self.append_log("Select a generated-plan row before removing an observation.")
            return False
        index = self.matching_record_index(self._plan_records, record)
        if index is None:
            self.append_log("Selected observation is no longer present in the plan.")
            self._selected_plan_record = None
            self.planSelectionChanged.emit(None)
            return False
        removed = self._plan_records.pop(index)
        still_present = self.matching_record_index(self._plan_records, removed) is not None
        updates = self.set_record_checked(removed, still_present)
        self.checkedRowsChanged.emit(updates)
        self._selected_plan_record = None
        self.observationInfoChanged.emit(None, "")
        self.planSelectionChanged.emit(None)
        self._publish_plan_records("Removed selected observation from the plan.")
        if spacing_min is not None:
            self._last_spacing_min = float(spacing_min)
        self._mark_diagnostics_stale_after_plan_edit()
        return True

    def clear_plan(self) -> bool:
        """Clear all current plan records and synchronized visibility checks."""
        if not self._plan_records:
            self.append_log("No observation plan rows to clear.")
            return False
        updates = self.clear_all_checked_records()
        self.checkedRowsChanged.emit(updates)
        self._clear_plan_records(emit=True, clear_checks=False)
        self._diagnostics_dirty_notice_logged = False
        self.append_log("Cleared observation plan.")
        return True

    def _mark_diagnostics_stale_after_plan_edit(self) -> None:
        """Mark diagnostics stale after a manual plan edit without recomputing.

        GUI-v1 deliberately avoids a full diagnostics recomputation on every
        checkbox click because large visibility tables must keep manual edits
        responsive. GUI-v2 follows the same rule: plan rows and checkboxes update
        immediately; diagnostics can be refreshed by a later diagnostics/export
        workflow.
        """
        diagnostics_available = False
        if not self._plan_records:
            self._state.diagnostics = None
            self.diagnosticsChanged.emit(None)
            self._diagnostics_dirty_notice_logged = False
        readiness = replace(self._state.snapshot.readiness, diagnostics_available=diagnostics_available)
        self._commit_snapshot(self._state.snapshot.with_updates(readiness=readiness))
        if self._plan_records and not self._diagnostics_dirty_notice_logged:
            self.append_log("Diagnostics pending; refreshed on diagnostics activation or export.")
            self._diagnostics_dirty_notice_logged = True

    def refresh_diagnostics_for_current_plan(self, *, spacing_min: float | None = None) -> object | None:
        """Refresh diagnostics for the current generated/manual plan.

        Parameters
        ----------
        spacing_min : float, optional
            Spacing value in minutes used by the diagnostics layer.

        Returns
        -------
        object or None
            Updated diagnostics object, or `None` if no plan is available.
        """
        if spacing_min is not None:
            self._last_spacing_min = float(spacing_min)
        plan_df = self._records_to_dataframe(include_metadata=True)
        if plan_df.empty:
            self._state.generated_plan = plan_df
            self._state.diagnostics = None
            readiness = replace(self._state.snapshot.readiness, plan_available=False, diagnostics_available=False)
            self._commit_snapshot(self._state.snapshot.with_updates(readiness=readiness))
            self.diagnosticsChanged.emit(None)
            return None

        source_visibility = self._first_non_empty_dataframe(
            self._state.visibility_dataframe,
            self._state.base_dataframe,
            self._state.view_dataframe,
        )
        diagnostics = refresh_observation_plan_diagnostics(
            self._state.diagnostics,
            plan_df,
            spacing_min=float(self._last_spacing_min),
            source_visibility=source_visibility,
            preferences=self._preferences,
        )
        self._state.generated_plan = plan_df
        self._state.diagnostics = diagnostics
        readiness = replace(
            self._state.snapshot.readiness,
            plan_available=True,
            diagnostics_available=diagnostics is not None,
        )
        self._commit_snapshot(self._state.snapshot.with_updates(readiness=readiness))
        self.diagnosticsChanged.emit(diagnostics)
        return diagnostics

    def export_current_plan(
        self,
        path: str | Path,
        *,
        coordinate_format: str | None = None,
        refresh_diagnostics: bool = True,
    ) -> PlannerExportResult:
        """Export the current generated/manual plan and optional diagnostics sidecar.

        Parameters
        ----------
        path : str or pathlib.Path
            Destination selected by the user. ``.txt`` writes the selector TXT
            representation; all other suffixes use CSV.
        coordinate_format : str, optional
            RA/DEC output-format identifier.  When omitted, the current GUI-v2
            planner coordinate-format snapshot is used.
        refresh_diagnostics : bool, optional
            If `True`, refresh stale diagnostics once immediately before export.

        Returns
        -------
        PlannerExportResult
            Export metadata for status display and verification.

        Raises
        ------
        ValueError
            If no current plan rows are available.
        OSError
            If the selected destination cannot be written.
        """
        file_path = Path(path)
        plan_df = self._records_to_dataframe(include_metadata=True)
        if plan_df.empty:
            message = "No observation plan to export."
            self._commit_snapshot(self._state.snapshot.with_status(message, last_error=message))
            self.append_log(message)
            raise ValueError(message)

        selected_format = coordinate_format or self._state.snapshot.coordinate_format
        diagnostics = self._state.diagnostics
        if refresh_diagnostics:
            diagnostics = self.refresh_diagnostics_for_current_plan(spacing_min=self._last_spacing_min)

        if file_path.suffix.lower() == ".txt":
            write_plan_txt(plan_df, file_path, coordinate_format=selected_format)
            export_kind = "TXT"
        else:
            if file_path.suffix == "":
                file_path = file_path.with_suffix(".csv")
            write_plan_csv(plan_df, file_path, coordinate_format=selected_format)
            export_kind = "CSV"

        sidecar_path: Path | None = None
        if diagnostics is not None:
            sidecar_path = write_plan_diagnostics_sidecar(diagnostics, file_path)

        result = PlannerExportResult(
            plan_path=file_path,
            sidecar_path=sidecar_path,
            row_count=len(plan_df),
            exported_at=datetime.now(UTC),
        )
        message = f"Exported {export_kind} observation plan to {file_path}"
        if sidecar_path is not None:
            message = f"{message} and diagnostics to {sidecar_path}"
        snapshot = self._state.snapshot.with_updates(
            status_message=message,
            last_error=None,
            last_export_path=str(file_path),
            last_export_sidecar_path=str(sidecar_path) if sidecar_path is not None else None,
            last_export_row_count=result.row_count,
            last_exported_at=result.exported_at,
        )
        self._commit_snapshot(snapshot)
        self.append_log(message)
        return result

    def set_record_checked(self, record: ObservationPlanRecord, checked: bool) -> dict[str, list[int]]:
        """Set a record's checkbox state in all loaded visibility tables."""
        return self.set_records_checked([record], checked)

    def set_records_checked(self, records: Iterable[ObservationPlanRecord], checked: bool) -> dict[str, list[int]]:
        """Set multiple records' checkbox state with identity-based lookup.

        The method prefers helper identity columns for large tables.  A
        satellite/time fallback is kept only for legacy rows without helper
        identity metadata.
        """
        records = list(records)
        updated: dict[str, list[int]] = {name: [] for name in _TABLE_ATTRS}
        if not records:
            return updated

        for table_name, attr_name in _TABLE_ATTRS.items():
            dataframe = getattr(self._state, attr_name, None)
            if dataframe is None or getattr(dataframe, "empty", True) or "_checked" not in dataframe.columns:
                continue
            positions: set[int] = set()
            fallback_records: list[ObservationPlanRecord] = []
            for record in records:
                position = self._position_for_record(table_name, record)
                if position is None:
                    fallback_records.append(record)
                else:
                    positions.add(position)

            if positions:
                check_col = dataframe.columns.get_loc("_checked")
                rows = sorted(positions)
                dataframe.iloc[rows, check_col] = bool(checked)
                updated[table_name].extend(rows)

            if fallback_records:
                updated[table_name].extend(
                    self._set_records_checked_by_satellite_time(dataframe, fallback_records, checked)
                )

        return {name: sorted(set(rows)) for name, rows in updated.items()}

    def clear_all_checked_records(self) -> dict[str, list[int]]:
        """Clear checkbox state in loaded visibility tables and report rows."""
        updated: dict[str, list[int]] = {name: [] for name in _TABLE_ATTRS}
        for table_name, attr_name in _TABLE_ATTRS.items():
            dataframe = getattr(self._state, attr_name, None)
            if dataframe is None or getattr(dataframe, "empty", True) or "_checked" not in dataframe.columns:
                continue
            try:
                checked_mask = dataframe["_checked"].astype(bool).to_numpy(copy=False)
                rows = [int(index) for index in np.flatnonzero(checked_mask)]
            except Exception:
                rows = list(range(len(dataframe)))
            if rows:
                dataframe.loc[:, "_checked"] = False
                updated[table_name] = rows
        return updated

    def mark_plan_dataframe_checked(self, plan_df: pd.DataFrame | None) -> dict[str, list[int]]:
        """Mark generated plan rows as checked in all visibility tables."""
        if plan_df is None or plan_df.empty:
            return {name: [] for name in _TABLE_ATTRS}
        sat_col = resolve_column(plan_df, "satellite")
        date_col = resolve_column(plan_df, "date_ut", required=False) or "datetime"
        records: list[ObservationPlanRecord] = []
        for _, row in plan_df.iterrows():
            records.append(
                ObservationPlanRecord(
                    satellite=row.get(sat_col),
                    date_ut=row.get(date_col),
                    ra=row.get(resolve_column(plan_df, "ra", required=False) or "ra", ""),
                    dec=row.get(resolve_column(plan_df, "dec", required=False) or "dec", ""),
                    elev=row.get(resolve_column(plan_df, "elev", required=False) or "elev", ""),
                    source=GENERATED_SOURCE,
                    global_index=row.get("global_index"),
                    base_index=row.get("base_index"),
                    local_index=row.get("local_index"),
                )
            )
        return self.set_records_checked(records, True)

    def plot_color_map(self) -> dict[str, object]:
        """Return deterministic satellite color indexes for the plot adapter."""
        return dict(self._satellite_color_indices)

    def shutdown_workers(self, *, wait_msecs: int = 500) -> bool:
        """Request worker shutdown with cooperative cancellation and bounded wait."""
        alive = []
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    if hasattr(worker, "request_cancel"):
                        worker.request_cancel()
                    else:
                        worker.requestInterruption()
                    worker.quit()
                    if not worker.wait(max(0, int(wait_msecs))):
                        alive.append(worker)
                        continue
                self._forget_worker(worker)
            except RuntimeError:
                continue
        self._workers = alive
        if self._generate_plan_worker not in alive:
            self._generate_plan_worker = None
        return not alive

    def _on_visibility_loaded(self, file_path: Path, data_master: object, data_base: object, data_view: object) -> None:
        self._state.visibility_dataframe = data_master
        self._state.base_dataframe = data_base
        self._state.view_dataframe = data_view
        self._state.tle_index = None
        self._state.generated_plan = None
        self._state.diagnostics = None
        self._plan_records = []
        self._selected_plan_record = None
        self._diagnostics_dirty_notice_logged = False
        self._rebuild_identity_positions()
        self._satellite_color_indices = build_satellite_colors(data_master)
        row_count = self._safe_len(data_master)
        visible_count = self._safe_len(data_view)
        satellites = self._satellites_from_dataframe(data_base)
        readiness = PlannerDataReadiness(
            visibility_loaded=True,
            tle_loaded=False,
            targets_loaded=self._state.target_dataframe is not None,
        )
        snapshot = self._state.snapshot.with_updates(
            readiness=readiness,
            generation_status=PlannerGenerationStatus.READY,
            visibility_file_path=str(file_path),
            tle_file_path=None,
            visibility_row_count=row_count,
            visible_row_count=visible_count,
            satellite_count=len(satellites),
            current_satellite_filter=ALL_SATELLITES_LABEL,
            visibility_load_state=PlannerLoadState.LOADED,
            tle_load_state=PlannerLoadState.IDLE,
            status_message=f"Loaded visibility data: {row_count} rows, {len(satellites)} satellites.",
            last_error=None,
        )
        self._commit_snapshot(snapshot)
        self.loadStateChanged.emit("visibility", PlannerLoadState.LOADED.value, str(file_path))
        self.loadStateChanged.emit("tle", PlannerLoadState.IDLE.value, "TLE loading is available.")
        self.visibilityTableChanged.emit(data_view)
        self.plotDataChanged.emit(data_view, self.plot_color_map())
        self.planRecordsChanged.emit([])
        self.diagnosticsChanged.emit(None)
        self.observationInfoChanged.emit(None, "")
        self.satellitesChanged.emit(satellites)
        self.append_log(f"Loaded visibility data: {file_path} ({row_count} rows, {len(satellites)} satellites).")
        self._load_pending_handoff_tle_file()

    def _load_pending_handoff_tle_file(self) -> None:
        """Load a precise-handoff TLE source after visibility data are ready."""
        tle_source_path = self._pending_handoff_tle_source_path
        self._pending_handoff_tle_source_path = None
        if tle_source_path is None:
            return
        if not tle_source_path.is_file():
            self.append_log(f"No file-backed TLE source was available for precise handoff: {tle_source_path}")
            return
        self.load_tle_file(tle_source_path)

    def _on_tle_loaded(self, file_path: Path, tle_index: object, message: str) -> None:
        self._state.tle_index = tle_index
        readiness = replace(self._state.snapshot.readiness, tle_loaded=True)
        snapshot = self._state.snapshot.with_updates(
            readiness=readiness,
            generation_status=PlannerGenerationStatus.READY,
            tle_file_path=str(file_path),
            tle_load_state=PlannerLoadState.LOADED,
            status_message=message,
            last_error=None,
        )
        self._commit_snapshot(snapshot)
        self.loadStateChanged.emit("tle", PlannerLoadState.LOADED.value, str(file_path))
        if self._selected_plan_record is not None:
            tle_text = self._tle_clipboard_text_for_satellite(self._selected_plan_record.satellite)
            self.observationInfoChanged.emit(self._selected_plan_record, tle_text)
        self.append_log(message)

    def _on_targets_loaded(self, file_path: Path, targets_df: object) -> None:
        self._state.target_dataframe = targets_df
        row_count = self._safe_len(targets_df)
        has_times = self._targets_have_times(targets_df)
        readiness = replace(self._state.snapshot.readiness, targets_loaded=row_count > 0)
        snapshot = self._state.snapshot.with_updates(
            readiness=readiness,
            target_file_path=str(file_path),
            target_row_count=row_count,
            target_has_times=has_times,
            targets_load_state=PlannerLoadState.LOADED,
            status_message=f"Loaded target JSON: {row_count} targets.",
            last_error=None,
        )
        self._commit_snapshot(snapshot)
        self.loadStateChanged.emit("targets", PlannerLoadState.LOADED.value, str(file_path))
        self.targetsAvailabilityChanged.emit(row_count > 0 and self._state.visibility_dataframe is not None, has_times)
        self.append_log(f"Loaded target JSON: {file_path} ({row_count} targets).")

    def _on_targets_applied(self, checked: bool, data_base: object, data_view: object) -> None:
        self._state.base_dataframe = data_base
        self._state.view_dataframe = data_view
        self._rebuild_identity_positions()
        satellites = self._satellites_from_dataframe(data_base)
        visible_count = self._safe_len(data_view)
        snapshot = self._state.snapshot.with_updates(
            targets_applied=bool(checked),
            current_satellite_filter=ALL_SATELLITES_LABEL,
            visible_row_count=visible_count,
            satellite_count=len(satellites),
            status_message="Applied target filter." if checked else "Reverted target filter.",
            last_error=None,
        )
        self._commit_snapshot(snapshot)
        self.visibilityTableChanged.emit(data_view)
        self.plotDataChanged.emit(data_view, self.plot_color_map())
        self.satellitesChanged.emit(satellites)
        self.checkedRowsChanged.emit(self._checked_rows_for_view())
        self.append_log("Applied target filter." if checked else "Reverted target filter.")

    def _on_satellite_filtered(self, satellite_filter: str, data_view: object) -> None:
        self._state.view_dataframe = data_view
        self._rebuild_identity_positions()
        visible_count = self._safe_len(data_view)
        snapshot = self._state.snapshot.with_updates(
            current_satellite_filter=satellite_filter,
            visible_row_count=visible_count,
            status_message=f"Displayed {visible_count} visibility rows for {satellite_filter}.",
            last_error=None,
        )
        self._commit_snapshot(snapshot)
        self.visibilityTableChanged.emit(data_view)
        self.plotDataChanged.emit(data_view, self.plot_color_map())
        self.checkedRowsChanged.emit(self._checked_rows_for_view())
        self.append_log(f"Filtered visibility rows: {satellite_filter} ({visible_count} rows).")

    def _on_plan_worker_finished(
        self,
        token: int,
        plan_df: pd.DataFrame,
        diagnostics: object,
        *,
        mode: str,
        plan_method: str,
        spacing_min: float,
        min_elevation: float,
        time_range_sec: int | float,
    ) -> None:
        """Publish plan-generation results produced by the worker thread."""
        if token != self._generation_token:
            return
        try:
            manual_records = [record for record in self._plan_records if record.source == MANUAL_SOURCE]
            generated_records = [record for record in self._plan_records if record.source == GENERATED_SOURCE]
            manual_keys = {self._record_identity_key(record) for record in manual_records}
            obsolete_generated = [record for record in generated_records if self._record_identity_key(record) not in manual_keys]
            uncheck_updates = self.set_records_checked(obsolete_generated, False)
            new_generated = ObservationPlanTableModel.from_plan_dataframe(plan_df, source=GENERATED_SOURCE)
            self._plan_records = manual_records + new_generated
            self._sort_plan_records()
            check_updates = self.mark_plan_dataframe_checked(plan_df)
            updates = self._merge_row_updates(uncheck_updates, check_updates)
            self.checkedRowsChanged.emit(updates)

            plan_available = bool(self._plan_records)
            self._state.generated_plan = self._records_to_dataframe(include_metadata=True)
            self._state.diagnostics = diagnostics
            self._diagnostics_dirty_notice_logged = False
            readiness = replace(
                self._state.snapshot.readiness,
                plan_available=plan_available,
                diagnostics_available=diagnostics is not None,
            )
            records_count = len(new_generated)
            mode_text = "JSON Times" if mode == JSON_TIMES_MODE else "Automatic"
            status = (
                f"Generated observation plan with {records_count} observations."
                if records_count
                else "Plan generation completed with no generated observations."
            )
            snapshot = self._state.snapshot.with_updates(
                readiness=readiness,
                generation_status=PlannerGenerationStatus.COMPLETE,
                status_message=status,
                last_error=None,
                last_generated_plan_method=(plan_method if records_count else None),
            )
            self._commit_snapshot(snapshot)
            self.planRecordsChanged.emit(self.plan_records())
            self.planSelectionChanged.emit(None)
            self.observationInfoChanged.emit(None, "")
            self.diagnosticsChanged.emit(diagnostics)
            if diagnostics is not None and hasattr(diagnostics, "to_log_message"):
                self.append_log(diagnostics.to_log_message())
            self.append_log(
                (
                    f"Generated observation plan with {records_count} observations "
                    f"(mode={mode_text}, method={plan_method}, Δt={spacing_min} min, "
                    f"elev ≥ {min_elevation}°, range={time_range_sec}s)."
                )
            )
            self.planGenerationSucceeded.emit(status)
        finally:
            self._generate_plan_worker = None
            self.planGenerationFinished.emit()

    def _on_plan_worker_canceled(self, token: int, message: str) -> None:
        """Handle cooperative cancellation without mutating the current plan."""
        if token != self._generation_token:
            return
        try:
            text = message or "Plan generation canceled; previous plan kept."
            snapshot = self._state.snapshot.with_updates(
                generation_status=PlannerGenerationStatus.CANCELED,
                status_message="Plan generation canceled; previous plan kept.",
            )
            self._commit_snapshot(snapshot)
            self.append_log("Plan generation canceled; previous plan kept.")
            self.planGenerationCanceled.emit(text)
        finally:
            self._generate_plan_worker = None
            self.planGenerationFinished.emit()

    def _on_plan_worker_failed(self, token: int, message: str) -> None:
        """Handle plan-generation worker failures without resetting loaded data."""
        if token != self._generation_token:
            return
        try:
            summary = message.splitlines()[0] if message else "unknown error"
            snapshot = self._state.snapshot.with_updates(
                generation_status=PlannerGenerationStatus.ERROR,
                status_message=f"Unable to generate plan: {summary}",
                last_error=message,
            )
            self._commit_snapshot(snapshot)
            self.failed.emit(message, "plan generation")
            self.append_log(f"ERROR generating plan: {summary}")
            self.planGenerationFailed.emit(message or "Observation plan generation failed.")
        finally:
            self._generate_plan_worker = None
            self.planGenerationFinished.emit()

    def _on_plan_worker_progress(self, message: str) -> None:
        """Forward worker progress to GUI-v2 logging and progress signals."""
        if not message:
            return
        self.planGenerationProgress.emit(message)
        self.append_log(message)

    def _on_worker_failed(self, message: str, context: str) -> None:
        state_key = {
            "visibility": "visibility_load_state",
            "tle": "tle_load_state",
            "targets": "targets_load_state",
        }.get(context)
        summary = message.splitlines()[0] if message else "unknown error"
        updates = {
            "generation_status": PlannerGenerationStatus.ERROR,
            "status_message": f"Unable to load {context}: {summary}",
            "last_error": message,
        }
        if context == "visibility":
            self._pending_handoff_tle_source_path = None
        if state_key is not None:
            updates[state_key] = PlannerLoadState.ERROR
        snapshot = self._state.snapshot.with_updates(**updates)
        self._commit_snapshot(snapshot)
        if state_key is not None:
            self.loadStateChanged.emit(context, PlannerLoadState.ERROR.value, summary)
        self.append_log(f"ERROR loading {context}: {summary}")
        self.failed.emit(message, context)

    def _set_load_state(self, kind: str, state: PlannerLoadState, *, detail: str | None = None) -> None:
        field = f"{kind}_load_state"
        if hasattr(self._state.snapshot, field):
            self._commit_snapshot(self._state.snapshot.with_updates(**{field: state}))
        self.loadStateChanged.emit(kind, state.value, detail or "")

    def _commit_snapshot(self, snapshot: PlannerRuntimeSnapshot) -> PlannerRuntimeSnapshot:
        committed = self._state.update_snapshot(snapshot)
        self.stateChanged.emit(committed)
        return committed

    def _start_worker(self, worker: object) -> None:
        self._workers.append(worker)
        worker.finished.connect(lambda *args, w=worker: self._forget_worker(w))
        worker.failed.connect(lambda *args, w=worker: self._forget_worker(w))
        if hasattr(worker, "canceled"):
            worker.canceled.connect(lambda *args, w=worker: self._forget_worker(w))
        worker.start()

    def _forget_worker(self, worker: object) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass
        if worker is self._generate_plan_worker:
            try:
                if not worker.isRunning():
                    self._generate_plan_worker = None
            except RuntimeError:
                self._generate_plan_worker = None
        try:
            worker.deleteLater()
        except RuntimeError:
            pass

    def _generation_is_running(self) -> bool:
        worker = self._generate_plan_worker
        if worker is None:
            return False
        try:
            return bool(worker.isRunning())
        except RuntimeError:
            self._generate_plan_worker = None
            return False

    def _next_generation_token(self) -> int:
        self._generation_token += 1
        return self._generation_token

    def _publish_plan_records(self, status_message: str | None = None) -> None:
        self._sort_plan_records()
        self._state.generated_plan = self._records_to_dataframe(include_metadata=True)
        readiness = replace(
            self._state.snapshot.readiness,
            plan_available=bool(self._plan_records),
            diagnostics_available=self._state.diagnostics is not None,
        )
        has_generated_rows = any(record.source == GENERATED_SOURCE for record in self._plan_records)
        snapshot = self._state.snapshot.with_updates(
            readiness=readiness,
            status_message=status_message or self._state.snapshot.status_message,
            last_generated_plan_method=(
                self._state.snapshot.last_generated_plan_method if has_generated_rows else None
            ),
        )
        self._commit_snapshot(snapshot)
        self.planRecordsChanged.emit(self.plan_records())

    def _clear_plan_records(self, *, emit: bool, clear_checks: bool) -> None:
        if clear_checks:
            self.checkedRowsChanged.emit(self.clear_all_checked_records())
        self._plan_records = []
        self._selected_plan_record = None
        self._state.generated_plan = pd.DataFrame()
        self._state.diagnostics = None
        readiness = replace(self._state.snapshot.readiness, plan_available=False, diagnostics_available=False)
        self._state.update_snapshot(
            self._state.snapshot.with_updates(
                readiness=readiness,
                last_generated_plan_method=None,
            )
        )
        if emit:
            self.planRecordsChanged.emit([])
            self.planSelectionChanged.emit(None)
            self.diagnosticsChanged.emit(None)
            self.observationInfoChanged.emit(None, "")

    def _records_to_dataframe(self, *, include_metadata: bool) -> pd.DataFrame:
        model = ObservationPlanTableModel()
        model.add_records(self._plan_records, sort_after=True)
        return model.to_dataframe(include_metadata=include_metadata)

    def _sort_plan_records(self) -> None:
        self._plan_records.sort(key=lambda record: pd.to_datetime(record.date_ut, errors="coerce"))

    def _record_from_dataframe_row(self, dataframe: pd.DataFrame, row: int, *, source: str) -> ObservationPlanRecord:
        mapping = self._preferences.column_mapping
        source_row = dataframe.iloc[row]
        solar_phase_col = resolve_column(dataframe, "solar_phase_angle", required=False, column_mapping=mapping)
        values: dict[str, object] = {}
        for logical in ("satellite", "date_ut", "ra", "dec", "elev"):
            column = resolve_column(dataframe, logical, column_mapping=mapping)
            values[logical] = source_row[column]
        values["solar_phase_angle"] = source_row[solar_phase_col] if solar_phase_col is not None else ""
        for identity_column in ("global_index", "base_index", "local_index"):
            values[identity_column] = source_row[identity_column] if identity_column in source_row.index else None
        return ObservationPlanRecord(source=source, **values)

    def _rebuild_identity_positions(self) -> None:
        self._identity_positions = {table: {} for table in _TABLE_ATTRS}
        for table_name, attr_name in _TABLE_ATTRS.items():
            dataframe = getattr(self._state, attr_name, None)
            if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
                continue
            for identity_column in ("global_index", "base_index", "local_index"):
                if identity_column not in dataframe.columns:
                    continue
                positions: dict[object, int] = {}
                for position, value in enumerate(dataframe[identity_column].tolist()):
                    if self._valid_identity(value) and value not in positions:
                        positions[value] = position
                self._identity_positions[table_name][identity_column] = positions

    def _position_for_record(self, table_name: str, record: ObservationPlanRecord) -> int | None:
        preferred = {
            "data_master": ("global_index", "base_index", "local_index"),
            "data_base": ("base_index", "global_index", "local_index"),
            "data_view": ("local_index", "base_index", "global_index"),
        }
        for identity_column in preferred.get(table_name, ("global_index", "base_index", "local_index")):
            value = getattr(record, identity_column, None)
            if not self._valid_identity(value):
                continue
            position = self._identity_positions.get(table_name, {}).get(identity_column, {}).get(value)
            if position is not None:
                return int(position)
        return None

    def _set_records_checked_by_satellite_time(
        self,
        dataframe: pd.DataFrame,
        records: Iterable[ObservationPlanRecord],
        checked: bool,
    ) -> list[int]:
        """Legacy fallback for rows without helper identity metadata."""
        changed: list[int] = []
        try:
            sat_col = resolve_column(dataframe, "satellite")
            date_col = resolve_column(dataframe, "date_ut")
            sat_values = dataframe[sat_col].astype(str)
            date_values = dataframe[date_col].astype(str)
        except Exception:
            return changed

        for record in records:
            try:
                mask = (sat_values == str(record.satellite)) & (date_values == str(record.date_ut))
                if mask.any():
                    rows = [int(pos) for pos in np.flatnonzero(mask.to_numpy(copy=False))]
                    dataframe.loc[mask, "_checked"] = bool(checked)
                    changed.extend(rows)
            except Exception:
                continue
        return changed

    def _checked_rows_for_view(self) -> dict[str, list[int]]:
        dataframe = self._state.view_dataframe
        if not isinstance(dataframe, pd.DataFrame) or dataframe.empty or "_checked" not in dataframe.columns:
            return {name: [] for name in _TABLE_ATTRS}
        try:
            rows = [int(index) for index in np.flatnonzero(dataframe["_checked"].astype(bool).to_numpy(copy=False))]
        except Exception:
            rows = []
        return {"data_master": [], "data_base": [], "data_view": rows}

    @staticmethod
    def _merge_row_updates(*updates: Mapping[str, Iterable[int]]) -> dict[str, list[int]]:
        merged: dict[str, set[int]] = {name: set() for name in _TABLE_ATTRS}
        for update in updates:
            for name, rows in update.items():
                if name in merged:
                    merged[name].update(int(row) for row in rows)
        return {name: sorted(rows) for name, rows in merged.items()}

    @staticmethod
    def _record_key(record: ObservationPlanRecord | None) -> tuple[object, ...] | None:
        return plan_record_key(record, include_source=True)

    @staticmethod
    def _record_identity_key(record: ObservationPlanRecord | None) -> tuple[object, ...] | None:
        return plan_record_key(record, include_source=False)

    @staticmethod
    def _same_record(a: ObservationPlanRecord | None, b: ObservationPlanRecord | None) -> bool:
        if a is None or b is None:
            return False
        return PlannerController._record_key(a) == PlannerController._record_key(b)

    @staticmethod
    def _valid_identity(value: object) -> bool:
        if value is None:
            return False
        try:
            return not bool(pd.isna(value))
        except Exception:
            return True

    @staticmethod
    def matching_record_index(
        records: Iterable[ObservationPlanRecord],
        record: ObservationPlanRecord,
        *,
        source: str | None = None,
    ) -> int | None:
        """Find the first row matching a plan-record key."""
        target_key = PlannerController._record_key(record)
        for row, existing in enumerate(records):
            if source is not None and existing.source != source:
                continue
            if PlannerController._record_key(existing) == target_key:
                return row
            if str(existing.satellite) == str(record.satellite) and str(existing.date_ut) == str(record.date_ut):
                return row
        return None

    def _tle_clipboard_text_for_satellite(self, satellite: object) -> str:
        tle_index = self._state.tle_index
        if tle_index is None:
            return ""
        for name in ("lookup", "get", "entry_for_satellite"):
            method = getattr(tle_index, name, None)
            if callable(method):
                try:
                    entry = method(str(satellite))
                except Exception:
                    continue
                text = self._tle_entry_to_text(entry)
                if text:
                    return text
        try:
            entry = tle_index[str(satellite)]
        except Exception:
            return ""
        return self._tle_entry_to_text(entry)

    @staticmethod
    def _tle_entry_to_text(entry: object) -> str:
        if entry is None:
            return ""
        clipboard_text = getattr(entry, "clipboard_text", None)
        if callable(clipboard_text):
            try:
                return str(clipboard_text())
            except Exception:
                return ""
        if isinstance(clipboard_text, str) and clipboard_text.strip():
            return clipboard_text
        if isinstance(entry, str):
            return entry
        parts = []
        for name in ("name", "line1", "line2"):
            value = getattr(entry, name, None)
            if value:
                parts.append(str(value))
        return "\n".join(parts)

    @staticmethod
    def _first_non_empty_dataframe(*dataframes: object) -> pd.DataFrame | None:
        for dataframe in dataframes:
            if isinstance(dataframe, pd.DataFrame) and not dataframe.empty:
                return dataframe
        return None

    @staticmethod
    def _safe_len(value: object) -> int:
        try:
            return int(len(value))
        except Exception:
            return 0

    @staticmethod
    def _targets_have_times(targets_df: object) -> bool:
        if not isinstance(targets_df, pd.DataFrame) or targets_df.empty or "datetime" not in targets_df.columns:
            return False
        return bool(targets_df["datetime"].notna().sum() > 0)

    @staticmethod
    def _satellites_from_dataframe(dataframe: object) -> list[str]:
        if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
            return []
        try:
            satellite_col = resolve_column(dataframe, "satellite")
        except Exception:
            return []
        return list(dataframe[satellite_col].astype(str).unique())


__all__ = ("PlannerController",)
