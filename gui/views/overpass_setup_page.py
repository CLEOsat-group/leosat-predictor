"""Overpass Prediction setup/run static assembly page for GUI."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Protocol

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QFrame, QGridLayout, QScrollArea, QSizePolicy, QWidget

from gui.services.location_service import LocationService
from gui.services.preferences_service import PreferencesService, PreferencesServiceError
from gui.presenters.overpass_export_presenter import OverpassExportPresenter
from gui.shell.navigation_model import NavigationNode
from gui.state.overpass_execution_state import (
    OverpassExecutionSnapshot,
    OverpassExecutionState,
)
from gui.state.overpass_results_state import OverpassResultsState
from gui.state.overpass_validation import (
    OverpassInputSnapshot,
    OverpassValidationState,
    validate_overpass_inputs,
)
from gui.widgets.location_card import LocationCard
from gui.widgets.log_console_card import LogConsoleCard
from gui.widgets.overpass_settings_card import OverpassSettingsCard
from gui.widgets.run_controls_card import RunControlsCard
from gui.widgets.tle_selection_card import TleSelectionCard
from src.models.prediction_thread_gui import PredictionThread


class OverpassSetupServices(Protocol):
    """Structural service bundle required by ``OverpassSetupPage``."""

    @property
    def preferences_service(self) -> PreferencesService: ...

    @property
    def location_service(self) -> LocationService: ...

    @property
    def tle_service(self) -> object: ...


class OverpassSetupPage(QWidget):
    """Concrete Task 44A page for static overpass input assembly.

    The page replaces only ``predictions.overpass.setup_run``. It assembles the
    GUI-native setup cards, wires services for preferences/location/TLE
    staging, and keeps run/validation/export/execution disabled until later
    Task 44 slices.
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
        services: OverpassSetupServices,
        observatory_context_callback: Callable[[Mapping[str, object]], None] | None = None,
        status_callback: Callable[[str, str], None] | None = None,
        results_state: OverpassResultsState | None = None,
        result_handoff_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.page = page
        self._services = services
        self._observatory_context_callback = observatory_context_callback
        self._status_callback = status_callback
        self._results_state = results_state or OverpassResultsState()
        self._result_handoff_callback = result_handoff_callback
        self._active_prediction_thread: PredictionThread | None = None
        self._export_presenter = OverpassExportPresenter(results_state=self._results_state, parent=self)
        self.setObjectName("guiOverpassSetupPage")
        self._validation_state: OverpassValidationState | None = None
        self._last_validation_summary = ""

        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setHorizontalSpacing(0)
        root.setVerticalSpacing(12)

        self.log_console_card = LogConsoleCard(self)
        preferences = self._load_preferences()
        self._preferences = preferences

        scroll_area = QScrollArea(self)
        scroll_area.setObjectName("guiOverpassSetupScrollArea")
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        grid_host = QWidget(scroll_area)
        grid_host.setObjectName("guiOverpassSetupScrollContent")
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
        self.overpass_settings_card = OverpassSettingsCard(
            preferences=preferences,
            log_callback=self._append_log,
            parent=grid_host,
        )
        self.tle_selection_card = TleSelectionCard(
            tle_service=self._services.tle_service,
            log_callback=self._append_log,
            parent=grid_host,
        )
        self.run_controls_card = RunControlsCard(log_callback=self._append_log, parent=grid_host)

        # Task 44A refined 4-row workspace grid.
        #
        # Logical placement:
        # - rows 0-1, columns 0-1: location input
        # - rows 2-3, columns 0-1: TLE selection
        # - row 0, column 2: time window and constraints
        # - rows 1-2, columns 2-3: setup log console
        # - row 3, columns 2-3: run controls
        #
        # Column 3 is intentionally unused in row 0. This preserves the
        # requested asymmetric placement instead of widening the settings card.
        grid.addWidget(self.location_card, 0, 0, 2, 2)
        grid.addWidget(self.tle_selection_card, 2, 0, 2, 2)
        grid.addWidget(self.overpass_settings_card, 0, 2)
        grid.addWidget(self.log_console_card, 1, 2, 2, 2)
        grid.addWidget(self.run_controls_card, 3, 2, 1, 2)

        # The page grid uses moderate minimums and non-equal stretch so the TLE
        # side remains readable without forcing an oversized, non-resizable
        # window.  The right-side log remains useful but does not dominate the
        # page width.
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

        scroll_area.setWidget(grid_host)
        root.addWidget(scroll_area, 0, 0)
        root.setRowStretch(0, 1)
        root.setColumnStretch(0, 1)

        self.location_card.defaultLocationSaved.connect(self.defaultLocationSaved)
        self._connect_validation_signals()
        self._connect_execution_signals()
        self._refresh_validation_state(log_transition=False)
        self._refresh_setup_export_state()
        # self._append_log("Overpass setup page assembled with Task 44E setup-page export readiness.", "INFO")


    def apply_preferences(self, preferences: Mapping[str, object], *, tle_service: object | None = None) -> bool:
        """Apply saved preferences to eligible overpass setup fields.

        Active prediction input is preserved while the page's backing
        preference reference is updated for future execution snapshots.
        """
        self._preferences = preferences
        thread = self._active_prediction_thread
        if thread is not None and thread.isRunning():
            self._append_log(
                "Preferences saved; overpass setup fields were preserved because a prediction is running.",
                "WARNING",
            )
            return False

        updated = False
        updated = self.location_card.apply_preferences(preferences, preserve_user_edits=True) or updated
        updated = self.overpass_settings_card.apply_preferences(preferences, preserve_user_edits=True) or updated
        if tle_service is not None:
            updated = self.tle_selection_card.set_tle_service(tle_service, preserve_loaded_data=True) or updated
        self._refresh_validation_state(log_transition=False)
        self._append_log(
            "Saved preferences applied to Overpass setup fields."
            if updated
            else "Saved preferences stored for Overpass.",
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
                "New default location saved; Overpass fields were preserved because a prediction is running.",
                "WARNING",
            )
            return
        self.location_card.apply_default_location(location)
        self._refresh_validation_state(log_transition=False)

    def _connect_validation_signals(self) -> None:
        """Wire card-level state changes into one central validation refresh."""
        self.location_card.stateChanged.connect(self._refresh_validation_state)
        self.overpass_settings_card.stateChanged.connect(self._refresh_validation_state)
        self.tle_selection_card.stateChanged.connect(self._refresh_validation_state)

    def _connect_execution_signals(self) -> None:
        """Wire run/cancel controls to the overpass execution coordinator."""
        self.run_controls_card.runRequested.connect(self._handle_run_requested)
        self.run_controls_card.cancelRequested.connect(self._handle_cancel_requested)
        self.run_controls_card.exportRequested.connect(self._handle_export_requested)

    def _current_input_snapshot(self) -> OverpassInputSnapshot:
        """Collect raw overpass setup input from child cards."""
        location = self.location_card.validation_snapshot()
        settings = self.overpass_settings_card.validation_snapshot()
        tle = self.tle_selection_card.validation_snapshot()
        return OverpassInputSnapshot(
            location_name=str(location.get("name", "")),
            latitude=str(location.get("latitude", "")),
            longitude=str(location.get("longitude", "")),
            altitude=str(location.get("altitude", "")),
            start_date=str(settings.get("start_date", "")),
            days=str(settings.get("days", "")),
            constellation=str(tle.get("constellation", "")),
            selected_satellite_count=_safe_int(tle.get("selected_satellite_count", 0)),
            loaded_satellite_count=_safe_int(tle.get("loaded_satellite_count", 0)),
            selection_confirmed=bool(tle.get("selection_confirmed", False)),
        )

    def _refresh_validation_state(self, *, log_transition: bool = True) -> None:
        """Recompute and render the centralized overpass readiness state."""
        snapshot = self._current_input_snapshot()
        state = validate_overpass_inputs(snapshot)
        self._validation_state = state
        self.run_controls_card.set_validation_state(state)
        self._apply_field_validity(state)
        if log_transition and state.summary != self._last_validation_summary:
            level = "INFO" if state.is_ready else "WARNING"
            self._append_log(f"{state.summary}", level)
        self._last_validation_summary = state.summary

    def _apply_field_validity(self, state: OverpassValidationState) -> None:
        """Apply geometry-neutral validation properties to visible input controls."""
        issue_by_field = {issue.field_id: issue for issue in state.issues}
        for field_id in (
            "location.name",
            "location.latitude",
            "location.longitude",
            "location.altitude",
        ):
            issue = issue_by_field.get(field_id)
            self.location_card.set_field_validity(field_id, issue is None, "" if issue is None else issue.message)

        for field_id in ("settings.start_date", "settings.days"):
            issue = issue_by_field.get(field_id)
            self.overpass_settings_card.set_field_validity(field_id, issue is None, "" if issue is None else issue.message)

        for field_id in ("tle.constellation", "tle.loaded", "tle.selection"):
            issue = issue_by_field.get(field_id)
            self.tle_selection_card.set_field_validity(field_id, issue is None, "" if issue is None else issue.message)

    def _handle_run_requested(self) -> None:
        """Start an overpass run from the confirmed, validated setup state."""
        if self._active_prediction_thread is not None and self._active_prediction_thread.isRunning():
            self._append_log("Overpass prediction is already running.", "WARNING")
            return
        state = self._validation_state or validate_overpass_inputs(self._current_input_snapshot())
        if not state.is_ready:
            self._refresh_validation_state(log_transition=True)
            self._append_log(f"Run rejected: {state.summary}", "WARNING")
            return
        try:
            snapshot = self._build_execution_snapshot()
        except ValueError as exc:
            self._append_log(f"Run rejected before execution: {exc}", "ERROR")
            self.run_controls_card.set_execution_state(OverpassExecutionState.failed(str(exc)))
            return

        started_at = datetime.now().astimezone()
        self._results_state.mark_started(started_at, snapshot=snapshot)
        self._refresh_setup_export_state()
        self._set_inputs_enabled(False)
        self.run_controls_card.set_execution_state(
            OverpassExecutionState.running(
                satellite_count=snapshot.satellite_count,
                started_at=started_at,
            )
        )
        self._append_log(
            f"Starting overpass prediction for {snapshot.satellite_count} satellite(s) from "
            f"{snapshot.start_datetime_utc.isoformat()} UTC.",
            "INFO",
        )

        self.executionStarted.emit("Overpass prediction is running…")

        try:
            thread = PredictionThread(
                lat=snapshot.latitude_deg,
                lon=snapshot.longitude_deg,
                alt=snapshot.altitude_m,
                days=snapshot.days,
                interval=0,
                start_datetime=snapshot.start_datetime_utc,
                satellites_list=list(snapshot.satellites),
                mode="overpass",
                constraints=snapshot.constraints,
            )
            thread.finished.connect(self._handle_prediction_finished)
            thread.error.connect(self._handle_prediction_error)
            thread.cancelled.connect(self._handle_prediction_cancelled)
            self._active_prediction_thread = thread
            self.log_console_card.enable_logging_capture()
            thread.start()
        except Exception as exc:
            message = f"Unable to start overpass prediction: {exc}"
            self._results_state.set_error(message)
            self._refresh_setup_export_state()
            self._append_log(message, "ERROR")
            self.run_controls_card.set_execution_state(OverpassExecutionState.failed(message))
            self._release_finished_thread()
            self.executionFailed.emit(message)
            self.executionEnded.emit()
            self._set_inputs_enabled(True)
            self._refresh_validation_state(log_transition=False)

    def _handle_cancel_requested(self) -> None:
        """Request cancellation of the active overpass worker."""
        thread = self._active_prediction_thread
        if thread is None or not thread.isRunning():
            self._append_log("Cancel ignored because no overpass prediction is running.", "WARNING")
            return
        self.run_controls_card.set_execution_state(OverpassExecutionState.cancelling())
        self._append_log("Cancelling overpass prediction...", "INFO")
        PredictionThread.stop()

    def _handle_prediction_finished(self, results: object) -> None:
        """Store overpass results and hand off to the results page."""
        summary = self._results_state.set_results(results)  # type: ignore[arg-type]
        self._refresh_setup_export_state()
        terminal_message = f"Overpass prediction completed with {summary.row_count} result row(s)."
        self._append_log(f"Overpass run finished with {summary.row_count} result row(s).", "INFO")
        self.run_controls_card.set_execution_state(OverpassExecutionState.succeeded(row_count=summary.row_count))
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
        self._refresh_setup_export_state()
        self._append_log(f"Overpass prediction failed: {message}", "ERROR")
        self.run_controls_card.set_execution_state(OverpassExecutionState.failed(message))
        self._release_finished_thread()
        self.executionFailed.emit(message or "Overpass prediction failed.")
        self.executionEnded.emit()
        self._set_inputs_enabled(True)
        self._refresh_validation_state(log_transition=False)

    def _handle_prediction_cancelled(self) -> None:
        """Render worker cancellation acknowledgement."""
        self._refresh_setup_export_state()
        self._append_log("Overpass prediction cancelled.", "WARNING")
        self.run_controls_card.set_execution_state(OverpassExecutionState.cancelled())
        self._release_finished_thread()
        self.executionCanceled.emit("Overpass prediction canceled.")
        self.executionEnded.emit()
        self._set_inputs_enabled(True)
        self._refresh_validation_state(log_transition=False)

    def _handle_export_requested(self) -> None:
        """Export the latest completed overpass result from the setup page."""
        csv_path = self._export_presenter.export_csv()
        self._refresh_setup_export_state()
        if csv_path is not None:
            self._append_log(f"Exported current overpass results to: {csv_path}", "INFO")
            return
        if self._results_state.latest_export_error:
            self._append_log(f"Overpass CSV export failed: {self._results_state.latest_export_error}", "ERROR")

    def _refresh_setup_export_state(self) -> None:
        """Render setup-page export availability from shared overpass result state."""
        self.run_controls_card.set_export_available(self._results_state.can_export())

    def _build_execution_snapshot(self) -> OverpassExecutionSnapshot:
        """Build the immutable v1-compatible overpass execution snapshot."""
        location = self.location_card.values()
        settings = self.overpass_settings_card.validation_snapshot()
        satellites = tuple(dict(satellite) for satellite in self.tle_selection_card.selected_satellites())
        self._validate_tle_lines(satellites)

        selected_date = datetime.strptime(str(settings.get("start_date", "")).strip(), "%Y-%m-%d").date()
        local_now = datetime.now().astimezone()
        local_start_datetime = datetime.combine(selected_date, local_now.timetz())
        start_datetime_utc = local_start_datetime.astimezone(timezone.utc)

        preferences = self._preferences
        constraints = dict(preferences.get("visibility_constraints", {}))
        constraints.setdefault(
            "prediction_range_overpass",
            preferences.get("prediction_range_overpass", "night"),
        )

        return OverpassExecutionSnapshot(
            latitude_deg=float(str(location.get("latitude", "")).strip()),
            longitude_deg=float(str(location.get("longitude", "")).strip()),
            altitude_m=float(str(location.get("altitude", "")).strip()),
            start_datetime_utc=start_datetime_utc,
            days=int(str(settings.get("days", "")).strip()),
            constellation=self.tle_selection_card.current_constellation(),
            satellites=satellites,
            constraints=constraints,
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
        self.overpass_settings_card.setEnabled(enabled)
        self.tle_selection_card.setEnabled(enabled)

    def _release_finished_thread(self) -> None:
        """Release the completed worker object after signal delivery."""
        self.log_console_card.disable_logging_capture()
        thread = self._active_prediction_thread
        self._active_prediction_thread = None
        if thread is not None:
            thread.deleteLater()

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """Request bounded worker cleanup if the page is closed during execution."""
        thread = self._active_prediction_thread
        if thread is not None and thread.isRunning():
            self._append_log("Window closing while overpass prediction is active; requesting cancellation.", "WARNING")
            PredictionThread.stop()
            thread.wait(3000)
            self.log_console_card.disable_logging_capture()
        super().closeEvent(event)

    def _load_preferences(self) -> Mapping[str, object]:
        try:
            preferences = self._services.preferences_service.load()
        except PreferencesServiceError as exc:
            self._append_log(f"Unable to load preferences for setup page: {exc}", "ERROR")
            return {}
        self._append_log("Preferences loaded for Overpass Setup & Run static assembly.", "INFO")
        return preferences

    def _notify_observatory_context(self, location: Mapping[str, object]) -> None:
        """Forward loaded/saved observatory location to the dashboard header."""
        if self._observatory_context_callback is not None:
            self._observatory_context_callback(location)

    def _append_log(self, message: str, level: str = "INFO") -> None:
        self.log_console_card.append_message(message, level=level)
        if self._status_callback is not None:
            self._status_callback(message, level)


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
