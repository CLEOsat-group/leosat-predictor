"""Precise Prediction setup/run page for GUI."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QGridLayout, QWidget

from gui.services.location_service import LocationService
from gui.services.prediction_export_service import PredictionExportService
from gui.services.preferences_service import PreferencesService, PreferencesServiceError
from gui.presenters.precise_export_presenter import PreciseExportPresenter
from gui.shell.navigation_model import NavigationNode
from gui.state.precise_execution_state import PreciseExecutionSnapshot, PreciseExecutionState
from gui.state.precise_results_state import PLANNER_HANDOFF_DEFERRED_MESSAGE, PreciseResultsState
from gui.state.precise_validation import (
    PreciseInputSnapshot,
    PreciseValidationState,
    validate_precise_inputs,
)
from gui.widgets.location_card import LocationCard
from gui.widgets.log_console_card import LogConsoleCard
from gui.widgets.precise_settings_card import PreciseSettingsCard
from gui.widgets.run_controls_card import RunControlsCard
from gui.widgets.tle_selection_card import TleSelectionCard
from src.models.prediction_thread_gui import PredictionThread
from src.utils.time_utils import calculate_timezone_offset, get_date_time_object


class PreciseSetupServices(Protocol):
    """Structural service bundle required by ``PreciseSetupPage``."""

    @property
    def preferences_service(self) -> PreferencesService: ...

    @property
    def location_service(self) -> LocationService: ...

    @property
    def tle_service(self) -> object: ...

    @property
    def prediction_export_service(self) -> PredictionExportService: ...


class PreciseSetupPage(QWidget):
    """Production GUI page for precise setup, execution, and result actions.

    The page owns GUI precise setup cards, validates inputs, starts the
    existing shared GUI prediction worker in ``mode="precise"``, and exposes
    result-dependent CSV export. Real planner handoff remains guarded until a
    concrete GUI planner consumer exists.
    """

    executionStarted = pyqtSignal(str)
    executionSucceeded = pyqtSignal(str)
    executionCanceled = pyqtSignal(str)
    executionFailed = pyqtSignal(str)
    executionEnded = pyqtSignal()
    defaultLocationSaved = pyqtSignal(object)

    def __init__(
        self,
        *,
        page: NavigationNode,
        services: PreciseSetupServices,
        results_state: PreciseResultsState,
        result_handoff_callback: Callable[[], None] | None = None,
        planner_handoff_callback: Callable[[], bool] | None = None,
        observatory_context_callback: Callable[[Mapping[str, object]], None] | None = None,
        status_callback: Callable[[str, str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.page = page
        self._services = services
        self._results_state = results_state
        self._result_handoff_callback = result_handoff_callback
        self._planner_handoff_callback = planner_handoff_callback
        self._observatory_context_callback = observatory_context_callback
        self._status_callback = status_callback
        self.setObjectName("guiPreciseSetupPage")
        self._validation_state: PreciseValidationState | None = None
        self._last_validation_summary = ""
        self._active_prediction_thread: PredictionThread | None = None
        self._active_snapshot: PreciseExecutionSnapshot | None = None
        self._export_presenter = PreciseExportPresenter(
            results_state=self._results_state,
            parent=self,
            export_service=getattr(self._services, "prediction_export_service", None),
        )

        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setHorizontalSpacing(0)
        root.setVerticalSpacing(12)

        self.log_console_card = LogConsoleCard(self)
        preferences = self._load_preferences()
        self._preferences = preferences

        grid_host = QWidget(self)
        grid_host.setObjectName("guiWorkspaceGrid")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.location_card = LocationCard(
            location_service=self._services.location_service,
            preferences=preferences,
            preferences_service=self._services.preferences_service,
            log_callback=self._append_log,
            observatory_context_callback=self._notify_observatory_context,
            parent=grid_host,
        )
        self.precise_settings_card = PreciseSettingsCard(
            preferences=preferences,
            log_callback=self._append_log,
            parent=grid_host,
        )
        self.tle_selection_card = TleSelectionCard(
            tle_service=self._services.tle_service,
            log_callback=self._append_log,
            parent=grid_host,
        )
        self.run_controls_card = RunControlsCard(
            log_callback=self._append_log,
            parent=grid_host,
            workflow_label="precise",
            run_button_text="Run Precise",
            readiness_waiting_text="Precise setup validation is waiting for input.",
            show_export_button=True,
            show_handoff_button=True,
            handoff_button_text="Send to Planner",
        )

        grid.addWidget(self.location_card, 0, 0, 2, 2)
        grid.addWidget(self.tle_selection_card, 2, 0, 2, 2)
        grid.addWidget(self.precise_settings_card, 0, 2, 1, 2)
        grid.addWidget(self.log_console_card, 1, 2, 2, 2)
        grid.addWidget(self.run_controls_card, 3, 2, 1, 2)

        grid.setColumnMinimumWidth(0, 260)
        grid.setColumnMinimumWidth(1, 260)
        grid.setColumnMinimumWidth(2, 260)
        grid.setColumnMinimumWidth(3, 220)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)
        grid.setColumnStretch(3, 2)
        grid.setRowStretch(0, 0)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 1)
        grid.setRowStretch(3, 0)

        root.addWidget(grid_host, 0, 0)
        root.setRowStretch(0, 1)
        root.setColumnStretch(0, 1)

        self.location_card.defaultLocationSaved.connect(self.defaultLocationSaved)
        self._connect_validation_signals()
        self._connect_run_signals()
        self._refresh_validation_state(log_transition=False)
        self._refresh_deferred_action_state()
        # self._append_log("Precise setup page assembled with execution and export readiness.", "INFO")


    def apply_preferences(self, preferences: Mapping[str, object], *, tle_service: object | None = None) -> bool:
        """Apply saved preferences to eligible precise setup fields.

        The backing preference reference is updated immediately.  Visible fields
        are refreshed only when they are safe to update, so active user edits
        and running predictions are not overwritten.
        """
        self._preferences = preferences
        thread = self._active_prediction_thread
        if thread is not None and thread.isRunning():
            self._append_log(
                "Preferences saved; precise setup fields were preserved because a prediction is running.",
                "WARNING",
            )
            return False

        updated = False
        updated = self.location_card.apply_preferences(preferences, preserve_user_edits=True) or updated
        updated = self.precise_settings_card.apply_preferences(preferences, preserve_user_edits=True) or updated
        if tle_service is not None:
            updated = self.tle_selection_card.set_tle_service(tle_service, preserve_loaded_data=True) or updated
        self._refresh_validation_state(log_transition=False)
        self._append_log(
            "Saved preferences applied to eligible Precise setup fields."
            if updated
            else "Saved preferences stored for Precise; active setup fields were preserved.",
            "INFO",
        )
        return updated

    def apply_default_location(self, location: Mapping[str, object]) -> None:
        """Adopt a global default location raised from another setup page.

        The location fields are overwritten because the user explicitly set a
        new default.  Active edits are preserved only while a prediction is
        running on this page.
        """
        if isinstance(self._preferences, dict):
            self._preferences["default_location"] = dict(location)
        thread = self._active_prediction_thread
        if thread is not None and thread.isRunning():
            self._append_log(
                "New default location saved; Precise fields were preserved because a prediction is running.",
                "WARNING",
            )
            return
        self.location_card.apply_default_location(location)
        self._refresh_validation_state(log_transition=False)

    def _connect_validation_signals(self) -> None:
        """Wire card-level state changes into one central validation refresh."""
        self.location_card.stateChanged.connect(self._refresh_validation_state)
        self.precise_settings_card.stateChanged.connect(self._refresh_validation_state)
        self.tle_selection_card.stateChanged.connect(self._refresh_validation_state)

    def _connect_run_signals(self) -> None:
        """Wire run controls to precise execution and deferred-action handlers."""
        self.run_controls_card.runRequested.connect(self._handle_run_requested)
        self.run_controls_card.cancelRequested.connect(self._handle_cancel_requested)
        self.run_controls_card.exportRequested.connect(self._handle_export_requested)
        self.run_controls_card.handoffRequested.connect(self._handle_handoff_requested)

    def _current_input_snapshot(self) -> PreciseInputSnapshot:
        """Collect raw precise setup input from child cards."""
        location = self.location_card.validation_snapshot()
        settings = self.precise_settings_card.validation_snapshot()
        tle = self.tle_selection_card.validation_snapshot()
        return PreciseInputSnapshot(
            location_name=str(location.get("name", "")),
            latitude=str(location.get("latitude", "")),
            longitude=str(location.get("longitude", "")),
            altitude=str(location.get("altitude", "")),
            start_date=str(settings.get("start_date", "")),
            interval=str(settings.get("interval", "")),
            interval_unit=str(settings.get("interval_unit", "")),
            prediction_range=str(settings.get("prediction_range", "")),
            lowest_elevation=str(settings.get("lowest_elevation", "")),
            sun_zenith_highest=str(settings.get("sun_zenith_highest", "")),
            sun_zenith_lowest=str(settings.get("sun_zenith_lowest", "")),
            constellation=str(tle.get("constellation", "")),
            loaded_satellite_count=_safe_int(tle.get("loaded_satellite_count", 0)),
            selected_satellite_count=_safe_int(tle.get("selected_satellite_count", 0)),
            selection_confirmed=bool(tle.get("selection_confirmed", False)),
        )

    def _refresh_validation_state(self, *, log_transition: bool = True) -> None:
        """Recompute and render the centralized precise readiness state."""
        snapshot = self._current_input_snapshot()
        state = validate_precise_inputs(snapshot)
        self._validation_state = state
        self.run_controls_card.set_validation_state(state)
        self._apply_field_validity(state)
        if log_transition and state.summary != self._last_validation_summary:
            level = "INFO" if state.is_ready else "WARNING"
            self._append_log(f"{state.summary}", level)
        self._last_validation_summary = state.summary

    def _apply_field_validity(self, state: PreciseValidationState) -> None:
        """Apply geometry-neutral validation properties to visible controls."""
        issue_by_field = {issue.field_id: issue for issue in state.issues}
        for field_id in (
            "location.name",
            "location.latitude",
            "location.longitude",
            "location.altitude",
        ):
            issue = issue_by_field.get(field_id)
            self.location_card.set_field_validity(field_id, issue is None, "" if issue is None else issue.message)

        for field_id in (
            "settings.start_date",
            "settings.interval",
            "settings.interval_unit",
            "settings.prediction_range",
            "constraints.lowest_elevation",
            "constraints.sun_zenith_highest",
            "constraints.sun_zenith_lowest",
        ):
            issue = issue_by_field.get(field_id)
            self.precise_settings_card.set_field_validity(field_id, issue is None, "" if issue is None else issue.message)

        for field_id in ("tle.constellation", "tle.loaded", "tle.selection"):
            issue = issue_by_field.get(field_id)
            self.tle_selection_card.set_field_validity(field_id, issue is None, "" if issue is None else issue.message)

    def _handle_run_requested(self) -> None:
        """Start a precise run from the confirmed, validated setup state."""
        if self._active_prediction_thread is not None and self._active_prediction_thread.isRunning():
            self._append_log("Precise prediction is already running.", "WARNING")
            return
        state = self._validation_state or validate_precise_inputs(self._current_input_snapshot())
        if not state.is_ready:
            self._refresh_validation_state(log_transition=True)
            self._append_log(f"Run rejected: {state.summary}", "WARNING")
            return
        try:
            snapshot = self._build_execution_snapshot()
        except ValueError as exc:
            self._append_log(f"Run rejected before execution: {exc}", "ERROR")
            self.run_controls_card.set_execution_state(PreciseExecutionState.failed(str(exc)))
            return

        started_at = datetime.now().astimezone()
        self._active_snapshot = snapshot
        self._results_state.mark_started(started_at, snapshot=snapshot)
        self._refresh_deferred_action_state()
        self._set_inputs_enabled(False)
        self.run_controls_card.set_execution_state(
            PreciseExecutionState.running(
                satellite_count=snapshot.satellite_count,
                started_at=started_at,
            )
        )
        self._append_log(
            f"Starting precise prediction for {snapshot.satellite_count} satellite(s) from "
            f"{snapshot.start_datetime.isoformat()} to {snapshot.end_datetime.isoformat()}.",
            "INFO",
        )

        self.executionStarted.emit("Precise prediction is running…")

        try:
            thread = PredictionThread(
                lat=snapshot.latitude_deg,
                lon=snapshot.longitude_deg,
                alt=snapshot.altitude_m,
                start_datetime=snapshot.start_datetime,
                end_datetime=snapshot.end_datetime,
                days=1,
                interval=snapshot.interval_seconds,
                satellites_list=list(snapshot.satellites),
                mode="precise",
                constraints=dict(snapshot.constraints),
                margin=snapshot.visibility_margin_minutes,
            )
            thread.finished.connect(self._handle_prediction_finished)
            thread.error.connect(self._handle_prediction_error)
            thread.cancelled.connect(self._handle_prediction_cancelled)
            self._active_prediction_thread = thread
            self.log_console_card.enable_logging_capture()
            thread.start()
        except Exception as exc:
            message = f"Unable to start precise prediction: {exc}"
            self._results_state.set_error(message)
            self._refresh_deferred_action_state()
            self._append_log(message, "ERROR")
            self.run_controls_card.set_execution_state(PreciseExecutionState.failed(message))
            self._release_finished_thread()
            self.executionFailed.emit(message)
            self.executionEnded.emit()
            self._set_inputs_enabled(True)
            self._refresh_validation_state(log_transition=False)

    def _handle_cancel_requested(self) -> None:
        """Request cancellation of the active precise worker."""
        thread = self._active_prediction_thread
        if thread is None or not thread.isRunning():
            self._append_log("Cancel ignored because no precise prediction is running.", "WARNING")
            return
        self.run_controls_card.set_execution_state(PreciseExecutionState.cancelling())
        self._append_log("Cancelling precise prediction...", "INFO")
        PredictionThread.stop()

    def _handle_prediction_finished(self, results: object) -> None:
        """Store precise results and hand off to the results page."""
        summary = self._results_state.set_results(results, snapshot=self._active_snapshot)  # type: ignore[arg-type]
        self._refresh_deferred_action_state()
        terminal_message = f"Precise prediction completed with {summary.row_count} result row(s)."
        self._append_log(f"Precise run finished with {summary.row_count} result row(s).", "INFO")
        self.run_controls_card.set_execution_state(PreciseExecutionState.succeeded(row_count=summary.row_count))
        self._release_finished_thread()
        self._set_inputs_enabled(True)
        self._refresh_validation_state(log_transition=False)
        if self._result_handoff_callback is not None:
            self._result_handoff_callback()
        self.executionSucceeded.emit(terminal_message)
        self.executionEnded.emit()

    def _handle_prediction_error(self, message: str) -> None:
        """Render a worker error without navigating to the results page."""
        self._results_state.set_error(message)
        self._refresh_deferred_action_state()
        self._append_log(f"Precise prediction failed: {message}", "ERROR")
        self.run_controls_card.set_execution_state(PreciseExecutionState.failed(message))
        self._release_finished_thread()
        self.executionFailed.emit(message or "Precise prediction failed.")
        self.executionEnded.emit()
        self._set_inputs_enabled(True)
        self._refresh_validation_state(log_transition=False)

    def _handle_prediction_cancelled(self) -> None:
        """Render worker cancellation acknowledgement."""
        self._refresh_deferred_action_state()
        self._append_log("Precise prediction cancelled.", "WARNING")
        self.run_controls_card.set_execution_state(PreciseExecutionState.cancelled())
        self._release_finished_thread()
        self.executionCanceled.emit("Precise prediction canceled.")
        self.executionEnded.emit()
        self._set_inputs_enabled(True)
        self._refresh_validation_state(log_transition=False)

    def _handle_export_requested(self) -> None:
        """Export the latest precise results through the shared presenter path."""
        csv_path = self._export_presenter.export_csv()
        self._refresh_deferred_action_state()
        if csv_path is not None:
            self._append_log(f"Exported current precise results to: {csv_path}", "INFO")
            if self._results_state.latest_export_warning:
                self._append_log(self._results_state.latest_export_warning, "WARNING")
        elif self._results_state.latest_export_error:
            self._append_log(f"Precise CSV export failed: {self._results_state.latest_export_error}", "ERROR")

    def _handle_handoff_requested(self) -> None:
        """Send completed precise results to the GUI planner consumer."""
        if self._planner_handoff_callback is None:
            self._results_state.set_handoff_message(PLANNER_HANDOFF_DEFERRED_MESSAGE)
            self._append_log(PLANNER_HANDOFF_DEFERRED_MESSAGE, "WARNING")
            self._refresh_deferred_action_state()
            return
        started = self._planner_handoff_callback()
        self._refresh_deferred_action_state()
        if started:
            self._append_log("Precise prediction results sent to Observation Planner.", "INFO")
        elif self._results_state.latest_handoff_error:
            self._append_log(f"Planner handoff failed: {self._results_state.latest_handoff_error}", "ERROR")

    def _refresh_deferred_action_state(self) -> None:
        """Refresh result-dependent export and planner handoff availability."""
        self.run_controls_card.set_export_available(self._results_state.can_export())
        self.run_controls_card.set_handoff_available(
            self._results_state.can_handoff(consumer_available=self._planner_handoff_callback is not None)
        )

    def _build_execution_snapshot(self) -> PreciseExecutionSnapshot:
        """Build the immutable v1-compatible precise execution snapshot."""
        location = self.location_card.values()
        settings = self.precise_settings_card.execution_snapshot()
        satellites = tuple(dict(satellite) for satellite in self.tle_selection_card.selected_satellites())
        self._validate_tle_lines(satellites)

        selected_date = datetime.strptime(str(settings.get("start_date", "")).strip(), "%Y-%m-%d").date()
        prediction_range = str(settings.get("prediction_range", "")).strip().lower()
        time_params = {
            "year": selected_date.year,
            "month": selected_date.month,
            "day": selected_date.day,
            "window": prediction_range,
        }
        timezone_offset = calculate_timezone_offset()
        start_datetime, finish_datetime = get_date_time_object(time_params, timezone_offset)

        constraints = dict(self._preferences.get("visibility_constraints", {}))
        constraints["lowest_altitude_satellite"] = float(str(settings.get("lowest_elevation", "")).strip())
        constraints["sun_zenith_highest"] = float(str(settings.get("sun_zenith_highest", "")).strip())
        constraints["sun_zenith_lowest"] = float(str(settings.get("sun_zenith_lowest", "")).strip())
        constraints["prediction_range_precise"] = prediction_range

        return PreciseExecutionSnapshot(
            latitude_deg=float(str(location.get("latitude", "")).strip()),
            longitude_deg=float(str(location.get("longitude", "")).strip()),
            altitude_m=float(str(location.get("altitude", "")).strip()),
            start_datetime=start_datetime,
            end_datetime=finish_datetime,
            interval_seconds=_interval_seconds(
                str(settings.get("interval", "")).strip(),
                str(settings.get("interval_unit", "")).strip().lower(),
            ),
            constellation=self.tle_selection_card.current_constellation(),
            satellites=satellites,
            constraints=constraints,
            visibility_margin_minutes=_visibility_margin_minutes(self._preferences.get("visibility_margin", 5)),
            source_file=str(self.tle_selection_card.validation_snapshot().get("source_file", "")),
        )

    def _validate_tle_lines(self, satellites: tuple[dict[str, object], ...]) -> None:
        """Apply the legacy pre-execution TLE line sanity checks."""
        if not satellites:
            raise ValueError("No satellites selected.")
        errors: list[str] = []
        for satellite in satellites:
            name = str(satellite.get("name", "Unknown"))
            tle1 = str(satellite.get("tle1", ""))
            tle2 = str(satellite.get("tle2", ""))
            if not tle1 or len(tle1) < 69 or not tle1.startswith("1 "):
                errors.append(f"TLE Line 1 is invalid for satellite {name}")
            if not tle2 or len(tle2) < 69 or not tle2.startswith("2 "):
                errors.append(f"TLE Line 2 is invalid for satellite {name}")
        if errors:
            raise ValueError("\n".join(errors))

    def _set_inputs_enabled(self, enabled: bool) -> None:
        """Enable or disable setup input cards while preserving run controls."""
        self.location_card.setEnabled(enabled)
        self.precise_settings_card.set_inputs_enabled(enabled)
        self.tle_selection_card.setEnabled(enabled)

    def _release_finished_thread(self) -> None:
        """Release the completed worker object after signal delivery."""
        self.log_console_card.disable_logging_capture()
        thread = self._active_prediction_thread
        self._active_prediction_thread = None
        self._active_snapshot = None
        if thread is not None:
            thread.deleteLater()

    def _load_preferences(self) -> Mapping[str, object]:
        try:
            preferences = self._services.preferences_service.load()
        except PreferencesServiceError as exc:
            self._append_log(f"Unable to load preferences for setup page: {exc}", "ERROR")
            return {}
        self._append_log("Preferences loaded for Precise Setup & Run execution readiness.", "INFO")
        return preferences

    def _notify_observatory_context(self, location: Mapping[str, object]) -> None:
        """Forward loaded/saved observatory location to the dashboard header."""
        if self._observatory_context_callback is not None:
            self._observatory_context_callback(location)

    def _append_log(self, message: str, level: str = "INFO") -> None:
        self.log_console_card.append_message(message, level=level)
        if self._status_callback is not None:
            self._status_callback(message, level)

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """Request bounded worker cleanup if the page is closed during execution."""
        thread = self._active_prediction_thread
        if thread is not None and thread.isRunning():
            self._append_log("Window closing while precise prediction is active; requesting cancellation.", "WARNING")
            PredictionThread.stop()
            thread.wait(3000)
            self.log_console_card.disable_logging_capture()
        super().closeEvent(event)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _interval_seconds(interval_text: str, interval_unit: str) -> int:
    """Convert the validated precise interval to seconds using v1 semantics."""
    interval = int(interval_text)
    if interval_unit == "minutes":
        return interval * 60
    if interval_unit == "hours":
        return interval * 3600
    return interval


def _visibility_margin_minutes(value: object) -> int:
    """Return the validated visibility margin fallback used by the v1 screen."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 5
