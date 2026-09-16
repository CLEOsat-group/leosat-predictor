"""GUI-v2 Observation Planner results workspace page.

Task 48C delivered the 2x2 workspace shell. Task 48D wires the results workspace to the controller-owned plan-generation
workflow.  Task 48F activates the export action from this existing Results page.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, pyqtSignal
from PyQt6.QtGui import QHideEvent, QShowEvent
from PyQt6.QtWidgets import QWidget

from gui_v2.controllers import PlannerController
from gui_v2.presenters import PlannerExportPresenter
from gui_v2.shell.navigation_model import NavigationNode
from gui_v2.state.planner_state import PlannerRuntimeSnapshot
from gui_v2.views.planner_setup_generation_page import PlannerPageShell
from gui_v2.widgets.planner_results_workspace import PlannerResultsWorkspace


class PlannerResultsPage(PlannerPageShell):
    """Concrete 2x2 results workspace for the GUI-v2 Observation Planner."""

    plotRenderStarted = pyqtSignal(str)
    plotRenderProgress = pyqtSignal(str)
    plotRenderSucceeded = pyqtSignal(str)
    plotRenderCanceled = pyqtSignal(str)
    plotRenderFailed = pyqtSignal(str)

    def __init__(
        self,
        *,
        page: NavigationNode,
        planner_controller: PlannerController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(page=page, planner_controller=planner_controller, parent=parent)

        self.results_workspace = PlannerResultsWorkspace(self.content_host)
        self.content_layout.addWidget(self.results_workspace, 1)
        self._pending_plot_payload: tuple[object, object | None] | None = None
        self._latest_plot_payload: tuple[object, object | None] | None = None
        self._export_presenter = PlannerExportPresenter(
            planner_controller=planner_controller,
            parent=self,
        )

        self.results_workspace.selectObservationRequested.connect(
            self._planner_controller.select_current_plan_observation
        )
        self.results_workspace.removeObservationRequested.connect(
            self._planner_controller.remove_selected_plan_record
        )
        self.results_workspace.clearPlanRequested.connect(self._planner_controller.clear_plan)
        self.results_workspace.exportPlanRequested.connect(self._export_plan)
        self.results_workspace.planRowSelected.connect(self._handle_plan_row_selected)
        self.results_workspace.plotPointSelected.connect(self._planner_controller.focus_visibility_row)
        self.results_workspace.exposureTimeChanged.connect(self._planner_controller.set_exposure_time_seconds)
        self.results_workspace.plotRenderStarted.connect(self.plotRenderStarted.emit)
        self.results_workspace.plotRenderProgress.connect(self.plotRenderProgress.emit)
        self.results_workspace.plotRenderSucceeded.connect(self.plotRenderSucceeded.emit)
        self.results_workspace.plotRenderCanceled.connect(self.plotRenderCanceled.emit)
        self.results_workspace.plotRenderFailed.connect(self.plotRenderFailed.emit)

        self._planner_controller.plotDataChanged.connect(self._handle_plot_data_changed)
        self._planner_controller.planRecordsChanged.connect(self.results_workspace.set_plan_records)
        self._planner_controller.visibilitySelectionChanged.connect(self.results_workspace.update_visibility_selection)
        self._planner_controller.planSelectionChanged.connect(self.results_workspace.update_plan_selection)
        self._planner_controller.observationInfoChanged.connect(self.results_workspace.set_observation)
        self._planner_controller.exposureTimeChanged.connect(self.results_workspace.set_exposure_time_seconds)

        # The Results page mirrors the setup-page Visibility Data table on a tab
        # next to the plot so plot and table share the same filtered view and
        # full interaction (row selection, focus, and manual-plan checkboxes).
        self._visibility_table = self.results_workspace.plot_workspace.visibility_table
        self._planner_controller.visibilityTableChanged.connect(self._visibility_table.set_dataframe)
        self._planner_controller.visibilityTableFocusRequested.connect(self._visibility_table.focus_row)
        self._planner_controller.checkedRowsChanged.connect(self._handle_results_checked_rows_changed)
        self._visibility_table.row_selected.connect(self._planner_controller.select_visibility_row)
        self._visibility_table.model().user_check_state_changed.connect(
            self._handle_results_user_check_state_changed
        )

        snapshot = planner_controller.current_snapshot()
        self.results_workspace.set_plan_records(planner_controller.plan_records())
        self.results_workspace.set_coordinate_format(snapshot.coordinate_format)
        self.results_workspace.set_exposure_time_seconds(planner_controller.exposure_time_seconds())
        self.results_workspace.set_export_enabled(snapshot.readiness.plan_available)

    def _handle_plot_data_changed(self, dataframe: object, color_map: object | None = None) -> None:
        """Render plot data only while the results page is visible.

        The GUI-v2 shell constructs all pages up front.  Rendering the planner
        plot while this page is hidden makes visibility-file loading feel slow
        because pyqtgraph still builds graphics items on the GUI thread.  This
        method stores the newest payload and applies it on first show, matching
        the GUI-v1 deferred-display pattern used for large handoffs.
        """
        payload = (dataframe, color_map)
        self._latest_plot_payload = payload
        if not self.isVisible():
            self._pending_plot_payload = payload
            return
        self._pending_plot_payload = None
        self.results_workspace.set_visibility_data(dataframe, color_map)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Apply only the newest deferred plot payload when visible."""

        super().showEvent(event)
        if self._pending_plot_payload is None:
            return
        dataframe, color_map = self._pending_plot_payload
        self._pending_plot_payload = None
        self.results_workspace.set_visibility_data(dataframe, color_map)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        """Cancel expensive hidden rendering and retain the latest payload."""

        if self.results_workspace.is_visibility_rendering():
            self.results_workspace.cancel_visibility_render(
                "Visibility plot rendering paused while the page is hidden."
            )
            self._pending_plot_payload = self._latest_plot_payload
        super().hideEvent(event)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        """Mark hidden plot data dirty after an application theme change."""

        super().changeEvent(event)
        if event.type() not in (
            QEvent.Type.StyleChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        ):
            return
        if not self.isVisible() and self._latest_plot_payload is not None:
            self._pending_plot_payload = self._latest_plot_payload

    def release_runtime_resources(self) -> None:
        """Release plot/table resources before application shutdown."""

        self._pending_plot_payload = None
        self._latest_plot_payload = None
        self.results_workspace.release_runtime_resources()

    def _handle_results_user_check_state_changed(self, row: int, checked: bool) -> None:
        """Route a Results-tab visibility checkbox edit into the manual plan.

        The Results page has no spacing control, so the controller reuses its
        last-known spacing value for the diagnostics refresh.
        """
        self._planner_controller.add_or_remove_manual_row(row, checked)

    def _handle_results_checked_rows_changed(self, updates: object) -> None:
        """Refresh changed checkbox rows in the Results-tab visibility table."""
        rows = []
        if isinstance(updates, dict):
            rows = list(updates.get("data_view", []))
        self._visibility_table.model().refresh_checked_rows(rows)

    def _handle_plan_row_selected(self, row: int) -> None:
        """Forward selected plan-table record to the controller."""
        if row < 0:
            self._planner_controller.select_plan_record(None)
            return
        self._planner_controller.select_plan_record(self.results_workspace.selected_record())

    def _handle_planner_state_changed(self, snapshot: PlannerRuntimeSnapshot) -> None:
        """Refresh page and result-surface state from controller metadata."""
        super()._handle_planner_state_changed(snapshot)
        if hasattr(self, "results_workspace"):
            self.results_workspace.set_coordinate_format(snapshot.coordinate_format)
            self.results_workspace.set_export_enabled(snapshot.readiness.plan_available)

    def _export_plan(self) -> None:
        """Export the current observation plan through the GUI-v2 presenter."""
        self._export_presenter.export_plan()


__all__ = ("PlannerResultsPage",)
