"""GUI-v2 Observation Planner diagnostics page."""

from __future__ import annotations

from PyQt6.QtGui import QShowEvent
from PyQt6.QtWidgets import QWidget

from gui_v2.controllers import PlannerController
from gui_v2.shell.navigation_model import NavigationNode
from gui_v2.state.planner_state import PlannerRuntimeSnapshot
from gui_v2.views.planner_setup_generation_page import PlannerPageShell
from gui_v2.widgets.planner_diagnostics_workspace import PlannerDiagnosticsWorkspace


class PlannerDiagnosticsPage(PlannerPageShell):
    """Diagnostics page for GUI-v2 Observation Planner parity."""

    def __init__(
        self,
        *,
        page: NavigationNode,
        planner_controller: PlannerController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(page=page, planner_controller=planner_controller, parent=parent)

        self.diagnostics_workspace = PlannerDiagnosticsWorkspace(self.content_host)
        self.content_layout.addWidget(self.diagnostics_workspace, 1)

        self.diagnostics_workspace.diagnosticsRefreshRequested.connect(self._refresh_current_plan_diagnostics)
        self.diagnostics_workspace.plotsTabActivated.connect(self._refresh_current_plan_diagnostics)
        self._planner_controller.diagnosticsChanged.connect(self.diagnostics_workspace.set_diagnostics)

        self.diagnostics_workspace.set_snapshot(planner_controller.current_snapshot())
        self.diagnostics_workspace.set_diagnostics(planner_controller.current_diagnostics())

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt API.
        """Refresh stale diagnostics lazily when the diagnostics page opens."""
        super().showEvent(event)
        self.diagnostics_workspace.maybe_refresh_stale_diagnostics()

    def release_runtime_resources(self) -> None:
        """Release heavy diagnostics plot resources before shutdown."""
        if hasattr(self, "diagnostics_workspace"):
            self.diagnostics_workspace.release_runtime_resources()

    def _refresh_current_plan_diagnostics(self) -> None:
        """Refresh diagnostics only when a current plan exists and data are stale."""
        snapshot = self._planner_controller.current_snapshot()
        if not snapshot.readiness.plan_available or snapshot.readiness.diagnostics_available:
            return
        diagnostics = self._planner_controller.refresh_diagnostics_for_current_plan()
        self.diagnostics_workspace.set_diagnostics(diagnostics)

    def _handle_planner_state_changed(self, snapshot: PlannerRuntimeSnapshot) -> None:
        """Refresh diagnostics page state from controller metadata."""
        super()._handle_planner_state_changed(snapshot)
        if hasattr(self, "diagnostics_workspace"):
            self.diagnostics_workspace.set_snapshot(snapshot)


__all__ = ("PlannerDiagnosticsPage",)
