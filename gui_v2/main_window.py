"""Main window for the GUI v2 baseline."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Protocol

from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget

from gui_v2.services.planner_handoff_service import PlannerHandoffError

from gui_v2.controllers import PlannerController
from gui_v2.shell import DashboardShell, NavigationNode
from gui_v2.shell.navigation_model import iter_pages
from gui_v2.state import StatusEvent
from gui_v2.state.overpass_results_state import OverpassResultsState
from gui_v2.state.preferences_state import PreferenceSavePlan
from gui_v2.state.precise_results_state import PreciseResultsState
from gui_v2.styles import apply_dashboard_theme
from gui_v2.views import (
    ConfigurationGeneralPage,
    ConfigurationPlannerPreferencesPage,
    ConfigurationPredictionDefaultsPage,
    OverpassResultsPage,
    OverpassSetupPage,
    PlaceholderPage,
    PlannerDiagnosticsPage,
    PlannerResultsPage,
    PlannerSetupGenerationPage,
    PreciseResultsPage,
    PreciseSetupPage,
)

_logger = logging.getLogger(__name__)


class _ServiceBundle(Protocol):
    """Structural service-bundle protocol consumed by the GUI v2 window."""

    @property
    def preferences_service(self) -> object: ...

    @property
    def location_service(self) -> object: ...

    @property
    def tle_service(self) -> object: ...

    @property
    def tle_service_factory(self) -> object: ...

    @property
    def prediction_export_service(self) -> object: ...

    @property
    def runtime_paths(self) -> object: ...

    @property
    def planner_handoff_service(self) -> object: ...


class MainWindow(QMainWindow):
    """Top-level GUI v2 window frame.

    The class owns the replacement-path shell and workflow pages.  Long-running
    execution remains delegated to page-specific controllers and services.
    """

    def __init__(self, *, sections: tuple[NavigationNode, ...], services: _ServiceBundle) -> None:
        super().__init__()
        self._services = services
        self._overpass_results_state = OverpassResultsState()
        self._precise_results_state = PreciseResultsState()
        self._current_tle_service = services.tle_service
        self._planner_controller = PlannerController(self)
        self._overpass_setup_page: OverpassSetupPage | None = None
        self._precise_setup_page: PreciseSetupPage | None = None
        self._overpass_results_page: OverpassResultsPage | None = None
        self._precise_results_page: PreciseResultsPage | None = None
        self._planner_results_page: PlannerResultsPage | None = None
        self._configuration_pages: list[QWidget] = []
        self.setObjectName("guiV2Root")
        self.setWindowTitle("LEO Satellite Predictor — GUI v2")

        self._shell = DashboardShell(sections, self)
        self.setCentralWidget(self._shell)
        self._planner_controller.logMessage.connect(
            lambda message: self._set_header_status_from_log(
                message,
                "INFO",
                source="Observation Planner",
            )
        )
        self._connect_planner_activity_lifecycle()
        self._configure_planner_preferences_from_preferences()
        self._planner_controller.preferencesRequested.connect(
            lambda: self._shell.set_current_page("configuration.planner_defaults")
        )
        self._configure_observatory_context_from_preferences()

        for page in iter_pages(sections):
            if page.page_id == "predictions.overpass.setup_run":
                widget = OverpassSetupPage(
                    page=page,
                    services=self._services,
                    observatory_context_callback=self._shell.configure_observatory_context,
                    status_callback=self._set_header_status_from_log,
                    results_state=self._overpass_results_state,
                    result_handoff_callback=self._show_overpass_results,
                    parent=self._shell,
                )
                self._overpass_setup_page = widget
                widget.defaultLocationSaved.connect(self._handle_default_location_saved)
                self._connect_prediction_activity(
                    widget,
                    task_key="overpass_prediction",
                    detail="Overpass Prediction",
                )
            elif page.page_id == "predictions.overpass.results_visualization":
                widget = OverpassResultsPage(
                    page=page,
                    results_state=self._overpass_results_state,
                    parent=self._shell,
                )
                self._overpass_results_page = widget
            elif page.page_id == "predictions.precise.setup_run":
                widget = PreciseSetupPage(
                    page=page,
                    services=self._services,
                    observatory_context_callback=self._shell.configure_observatory_context,
                    results_state=self._precise_results_state,
                    result_handoff_callback=self._show_precise_results,
                    planner_handoff_callback=self._handoff_precise_results_to_planner,
                    status_callback=self._set_header_status_from_log,
                    parent=self._shell,
                )
                self._precise_setup_page = widget
                widget.defaultLocationSaved.connect(self._handle_default_location_saved)
                self._connect_prediction_activity(
                    widget,
                    task_key="precise_prediction",
                    detail="Precise Prediction",
                )
            elif page.page_id == "predictions.precise.results_visualization":
                widget = PreciseResultsPage(
                    page=page,
                    results_state=self._precise_results_state,
                    export_service=getattr(self._services, "prediction_export_service", None),
                    planner_handoff_callback=self._handoff_precise_results_to_planner,
                    parent=self._shell,
                )
                self._precise_results_page = widget
            elif page.page_id == "planner.generate":
                widget = PlannerSetupGenerationPage(
                    page=page,
                    planner_controller=self._planner_controller,
                    parent=self._shell,
                )
            elif page.page_id == "planner.results":
                widget = PlannerResultsPage(
                    page=page,
                    planner_controller=self._planner_controller,
                    parent=self._shell,
                )
                self._planner_results_page = widget
                self._connect_plot_activity_lifecycle(widget)
            elif page.page_id == "planner.diagnostics":
                widget = PlannerDiagnosticsPage(
                    page=page,
                    planner_controller=self._planner_controller,
                    parent=self._shell,
                )
            elif page.page_id == "configuration.general":
                widget = ConfigurationGeneralPage(
                    page=page,
                    preferences_service=self._services.preferences_service,
                    runtime_paths=self._services.runtime_paths,
                    parent=self._shell,
                )
            elif page.page_id == "configuration.prediction_defaults":
                widget = ConfigurationPredictionDefaultsPage(
                    page=page,
                    preferences_service=self._services.preferences_service,
                    parent=self._shell,
                )
            elif page.page_id == "configuration.planner_defaults":
                widget = ConfigurationPlannerPreferencesPage(
                    page=page,
                    preferences_service=self._services.preferences_service,
                    parent=self._shell,
                )
            else:
                widget = PlaceholderPage(page, self._shell)
            self._connect_configuration_page(widget)
            self._shell.add_page(page.page_id, widget)
        self._shell.select_initial_page("predictions.overpass.setup_run")

    def _connect_planner_activity_lifecycle(self) -> None:
        """Connect explicit planner terminal outcomes to unified shell activity."""

        detail = "Observation Planner"
        task_key = "planner_generation"
        self._planner_controller.failed.connect(self._handle_planner_failure)
        self._planner_controller.planGenerationStarted.connect(
            lambda: self._shell.begin_activity(
                task_key,
                "Generating observation plan…",
                detail=detail,
            )
        )
        self._planner_controller.planGenerationProgress.connect(
            lambda message: self._shell.update_activity(task_key, message, detail=detail)
        )
        self._planner_controller.planGenerationSucceeded.connect(
            lambda message: self._shell.end_activity(
                task_key,
                StatusEvent.success(
                    message or "Observation plan generation complete.",
                    detail=detail,
                    auto_clear_ms=7000,
                ),
            )
        )
        self._planner_controller.planGenerationCanceled.connect(
            lambda message: self._shell.end_activity(
                task_key,
                StatusEvent.warning(
                    message or "Observation plan generation canceled.",
                    detail=detail,
                    auto_clear_ms=7000,
                ),
            )
        )
        self._planner_controller.planGenerationFailed.connect(
            lambda message: self._shell.end_activity(
                task_key,
                StatusEvent.error(
                    message or "Observation plan generation failed.",
                    detail=detail,
                ),
            )
        )

    def _connect_prediction_activity(
        self,
        page: OverpassSetupPage | PreciseSetupPage,
        *,
        task_key: str,
        detail: str,
    ) -> None:
        """Connect one prediction page to unified task feedback."""

        page.executionStarted.connect(
            lambda message: self._shell.begin_activity(
                task_key,
                message,
                detail=detail,
            )
        )
        page.executionSucceeded.connect(
            lambda message: self._shell.end_activity(
                task_key,
                StatusEvent.success(message, detail=detail, auto_clear_ms=7000),
            )
        )
        page.executionCanceled.connect(
            lambda message: self._shell.end_activity(
                task_key,
                StatusEvent.warning(message, detail=detail, auto_clear_ms=7000),
            )
        )
        page.executionFailed.connect(
            lambda message: self._shell.end_activity(
                task_key,
                StatusEvent.error(message, detail=detail),
            )
        )

    def _connect_plot_activity_lifecycle(self, page: PlannerResultsPage) -> None:
        """Connect deferred visibility-plot rendering to unified task feedback."""

        detail = "Observation Planner"
        task_key = "planner_plot"
        page.plotRenderStarted.connect(
            lambda message: self._shell.begin_activity(
                task_key,
                message,
                detail=detail,
                overlay_delay_ms=100,
            )
        )
        page.plotRenderProgress.connect(
            lambda message: self._shell.update_activity(task_key, message, detail=detail)
        )
        page.plotRenderSucceeded.connect(
            lambda message: self._shell.end_activity(
                task_key,
                StatusEvent.success(message, detail=detail, auto_clear_ms=5000),
            )
        )
        page.plotRenderCanceled.connect(
            lambda _message: self._shell.end_activity(task_key)
        )
        page.plotRenderFailed.connect(
            lambda message: self._shell.end_activity(
                task_key,
                StatusEvent.error(message, detail=detail),
            )
        )

    def _handle_planner_failure(self, message: str, context: str) -> None:
        """Publish non-generation planner failures without duplicating outcomes."""

        if str(context).strip().lower() == "plan generation":
            return
        self._shell.set_error_status(
            message or f"Observation Planner {context} failed.",
            detail=str(context).strip() or "Observation Planner",
        )

    def _set_header_status_from_log(
        self,
        message: str,
        level: str = "INFO",
        *,
        source: str = "GUI v2",
    ) -> None:
        """Mirror important workflow log messages to the global header status surface.

        Parameters
        ----------
        message : str
            User-facing status message already written to a page-local log.
        level : str, optional
            Logging level name used by setup pages.
        source : str, optional
            Short source label exposed as the header-status tooltip detail.
        """
        text = str(message).strip()
        if not text:
            return
        normalized = str(level or "INFO").strip().upper()
        if normalized == "ERROR":
            self._shell.set_error_status(text, detail=source)
        elif normalized == "WARNING":
            self._shell.set_warning_status(text, detail=source, auto_clear_ms=7000)
        else:
            self._shell.set_info_status(text, detail=source, auto_clear_ms=5000)

    def _connect_configuration_page(self, widget: QWidget) -> None:
        """Connect configuration save notifications to the live-apply coordinator."""
        signal = getattr(widget, "preferencesSaved", None)
        if signal is None:
            return
        signal.connect(self._handle_preferences_saved)
        self._configuration_pages.append(widget)

    def _handle_preferences_saved(self, plan: PreferenceSavePlan) -> None:
        """Apply saved preferences to eligible GUI-v2 runtime components."""
        messages: list[str] = []
        if plan.theme_changed:
            if self._apply_theme(plan.new_theme):
                messages.append(f"theme={plan.new_theme}")

        preferences = plan.copy_preferences()
        if plan.refresh_observatory_context:
            self._refresh_observatory_context(preferences)
            messages.append("observatory")

        tle_service = None
        if plan.refresh_tle_service and self._requires_tle_service_refresh(plan):
            tle_service = self._refresh_tle_service(preferences)
            if tle_service is not None:
                messages.append("TLE service")

        visible_updates = self._apply_preferences_to_setup_pages(preferences, tle_service=tle_service)
        if visible_updates:
            messages.append("setup defaults")

        if plan.apply_observation_planner:
            self._planner_controller.set_preferences(preferences)
            messages.append("planner defaults")
            if self._planner_column_mapping_changed(plan):
                self._planner_controller.set_status_message(
                    "Planner defaults saved. Column mapping applies to the next visibility-data load."
                )

        self._refresh_configuration_status_pages()
        message = "Preferences saved and applied to eligible GUI v2 pages."
        if not messages:
            message = "Preferences saved. No live GUI updates were required."
        sender = self.sender()
        marker = "; ".join(messages) if messages else "none"
        if hasattr(sender, "mark_live_apply_result"):
            sender.mark_live_apply_result(f"{message} Applied: {marker}.")  # type: ignore[attr-defined]
        self._shell.set_success_status(
            message,
            detail=f"Applied: {marker}",
            auto_clear_ms=7000,
        )

    def _apply_theme(self, theme: str) -> bool:
        """Apply the configured GUI-v2 stylesheet to the running application."""
        app = QApplication.instance()
        if app is None:
            _logger.warning("Theme preference saved but no QApplication instance is available for live apply.")
            return False
        try:
            apply_dashboard_theme(app, theme)
        except Exception:  # pragma: no cover - stylesheet file/runtime guard
            _logger.warning("Unable to apply GUI v2 theme '%s'.", theme, exc_info=True)
            return False
        return True

    def _refresh_observatory_context(self, preferences: Mapping[str, Any]) -> None:
        """Refresh the dashboard observatory context from saved preferences."""
        default_location = preferences.get("default_location")
        if isinstance(default_location, Mapping):
            self._shell.configure_observatory_context(default_location)

    @staticmethod
    def _requires_tle_service_refresh(plan: PreferenceSavePlan) -> bool:
        """Return whether changed paths affect future TLE-service operations."""
        prefixes = (
            "tle_folder",
            "tle_expiration_hours",
            "tle_update_interval_hours",
            "allow_batch_download",
            "tle_sources",
        )
        return any(path == prefix or path.startswith(f"{prefix}.") for path in plan.changed_paths for prefix in prefixes)

    @staticmethod
    def _planner_column_mapping_changed(plan: PreferenceSavePlan) -> bool:
        """Return whether a saved planner change affects future visibility loads."""
        prefixes = (
            "observation_planner.column_mapping",
            "observation_planner.visibility.columns",
        )
        return any(path == prefix or path.startswith(f"{prefix}.") for path in plan.changed_paths for prefix in prefixes)

    def _refresh_tle_service(self, preferences: Mapping[str, Any]) -> object | None:
        """Recreate the current TLE service while preserving the old one on failure."""
        factory = getattr(self._services, "tle_service_factory", None)
        if not callable(factory):
            _logger.warning("TLE preferences saved but no GUI-v2 TLE service factory is available.")
            return None
        try:
            self._current_tle_service = factory(preferences)
        except Exception:  # pragma: no cover - file/service construction guard
            _logger.warning("Unable to refresh GUI-v2 TLE service after preferences save.", exc_info=True)
            return None
        return self._current_tle_service

    def _handle_default_location_saved(self, location: Mapping[str, Any]) -> None:
        """Propagate a newly saved default location to both setup pages.

        A "Set as Default" action on one setup page updates the global default,
        so the sibling page and the dashboard observatory context adopt it too.
        The page that raised the signal already holds the values, but is
        re-applied so both pages stay in lock-step.
        """
        if not isinstance(location, Mapping):
            return
        self._shell.configure_observatory_context(location)
        for page in (self._overpass_setup_page, self._precise_setup_page):
            if page is not None:
                page.apply_default_location(location)

    def _apply_preferences_to_setup_pages(
        self,
        preferences: Mapping[str, Any],
        *,
        tle_service: object | None = None,
    ) -> bool:
        """Apply saved preferences to setup pages while preserving active edits."""
        updated = False
        if self._overpass_setup_page is not None:
            updated = self._overpass_setup_page.apply_preferences(preferences, tle_service=tle_service) or updated
        if self._precise_setup_page is not None:
            updated = self._precise_setup_page.apply_preferences(preferences, tle_service=tle_service) or updated
        return updated

    def _refresh_configuration_status_pages(self) -> None:
        """Refresh read-only configuration pages after a successful save.

        The Paths & Export audit now lives inside the General page and is
        refreshed by that page's own ``save`` fan-out, so it is intentionally
        not listed here (refreshing General on another page's save would discard
        the user's unsaved General edits).
        """
        for page in self._configuration_pages:
            if page.objectName() == "guiV2ConfigurationPage" and page is not self.sender():
                refresher = getattr(page, "load_from_service", None)
                if callable(refresher) and page.__class__.__name__ in {
                    "ConfigurationPlannerPreferencesPage",
                }:
                    refresher()


    def _configure_planner_preferences_from_preferences(self) -> None:
        """Initialize GUI-v2 planner runtime defaults from saved preferences."""
        loader = getattr(self._services.preferences_service, "load", None)
        if not callable(loader):
            return
        try:
            preferences = loader()
        except Exception:  # pragma: no cover - defensive planner initialization guard
            _logger.debug("Unable to load preferences for GUI v2 planner defaults.", exc_info=True)
            return
        self._planner_controller.set_preferences(preferences)


    def _handoff_precise_results_to_planner(self) -> bool:
        """Send completed precise results directly to the GUI-v2 planner."""
        planner_handoff_service = getattr(self._services, "planner_handoff_service", None)
        prepare_handoff = getattr(planner_handoff_service, "prepare_precise_handoff", None)
        if not callable(prepare_handoff):
            message = "Planner handoff service is not available."
            self._precise_results_state.set_handoff_error(message)
            _logger.warning(message)
            return False

        snapshot = self._precise_results_state.latest_snapshot
        tle_source_path = getattr(snapshot, "source_file", "") if snapshot is not None else ""
        try:
            payload = prepare_handoff(
                precise_results=self._precise_results_state.latest_results,
                tle_source_path=tle_source_path or None,
                source_label="Precise Prediction",
            )
            missing_columns = getattr(payload, "missing_columns", ())
            if missing_columns:
                _logger.warning(
                    "Precise planner handoff is missing expected column(s): %s",
                    ", ".join(str(column) for column in missing_columns),
                )
            started = self._planner_controller.load_visibility_dataframe(
                payload.dataframe,
                source_label=payload.source_label,
                tle_source_path=payload.tle_source_path,
            )
        except PlannerHandoffError as exc:
            message = str(exc)
            self._precise_results_state.set_handoff_error(message)
            _logger.warning("Precise planner handoff failed: %s", message)
            return False
        except Exception as exc:  # pragma: no cover - defensive GUI handoff guard
            message = f"Failed to send precise results to planner: {exc}"
            self._precise_results_state.set_handoff_error(message)
            _logger.exception(message)
            return False

        if not started:
            message = "The planner could not start loading the precise prediction results."
            self._precise_results_state.set_handoff_error(message)
            return False

        self._precise_results_state.set_handoff_message(
            f"Precise prediction results sent to Observation Planner ({payload.row_count} row(s))."
        )
        _logger.info(
            "Sent precise prediction results to GUI-v2 Observation Planner: %d row(s), %d column(s).",
            payload.row_count,
            payload.column_count,
        )
        return True

    def _show_overpass_results(self) -> None:
        """Refresh and navigate to the overpass results page after a successful run."""
        if self._overpass_results_page is not None:
            self._overpass_results_page.refresh()
        self._shell.set_current_page("predictions.overpass.results_visualization")

    def _show_precise_results(self) -> None:
        """Refresh and navigate to the precise results page after a successful run."""
        if self._precise_results_page is not None:
            self._precise_results_page.refresh()
        self._shell.set_current_page("predictions.precise.results_visualization")

    def _configure_observatory_context_from_preferences(self) -> None:
        """Initialize the header OBS field from the current default location."""
        loader = getattr(self._services.preferences_service, "load", None)
        if not callable(loader):
            return
        try:
            preferences = loader()
        except Exception:  # pragma: no cover - defensive shell initialization guard
            _logger.debug("Unable to load preferences for GUI v2 time context.", exc_info=True)
            return
        if not isinstance(preferences, Mapping):
            return
        default_location = preferences.get("default_location")
        if isinstance(default_location, Mapping):
            self._shell.configure_observatory_context(default_location)

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """Stop live GUI v2 header timers before the window closes."""
        _logger.debug("GUI v2 window closing, releasing runtime resources.")
        if self._planner_results_page is not None:
            try:
                self._planner_results_page.release_runtime_resources()
            except Exception:  # pragma: no cover - defensive plot cleanup
                _logger.debug("Unable to release planner result resources cleanly.", exc_info=True)
        try:
            self._planner_controller.shutdown_workers(wait_msecs=500)
        except Exception:  # pragma: no cover - defensive close cleanup
            _logger.debug("Unable to stop planner workers cleanly during GUI close.", exc_info=True)
        self._shell.clear_activities()
        self._shell.stop_time_context()
        super().closeEvent(event)

