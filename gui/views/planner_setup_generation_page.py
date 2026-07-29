"""GUI Observation Planner setup/generation page."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gui.controllers import PlannerController
from gui.helpers.logging_helpers import append_log_line
from gui.shell.navigation_model import NavigationNode
from gui.state.planner_state import PlannerGenerationStatus, PlannerRuntimeSnapshot
from gui.widgets.planner_controls import PlannerControlsCard
from gui.widgets.planner_visibility_table import PlannerVisibilityTable



class PlannerShellCard(QFrame):
    """Styled planner card used by GUI planner pages."""

    def __init__(self, *, title: str, body: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 16)
        self.layout.setSpacing(10)

        title_label = QLabel(title, self)
        title_label.setObjectName("guiCardTitle")
        title_label.setWordWrap(True)
        self.layout.addWidget(title_label)

        if body:
            body_label = QLabel(body, self)
            body_label.setObjectName("guiCardBody")
            body_label.setWordWrap(True)
            self.layout.addWidget(body_label)


class PlannerPageShell(QWidget):
    """Base shell for concrete GUI planner pages."""

    def __init__(
        self,
        *,
        page: NavigationNode,
        planner_controller: PlannerController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.page = page
        self._planner_controller = planner_controller
        self.setObjectName("guiPlannerPageShell")

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(12)

        self.status_label = QLabel(planner_controller.current_snapshot().status_message, self)
        self.status_label.setObjectName("guiWorkspaceStatusLine")
        self.status_label.setWordWrap(True)
        self.root_layout.addWidget(self.status_label)

        self.content_host = QWidget(self)
        self.content_host.setObjectName("guiWorkspaceGrid")
        self.content_layout = QVBoxLayout(self.content_host)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        self.root_layout.addWidget(self.content_host, 1)

        planner_controller.stateChanged.connect(self._handle_planner_state_changed)

    def _handle_planner_state_changed(self, snapshot: PlannerRuntimeSnapshot) -> None:
        """Refresh page-level status text from the planner controller."""
        self.status_label.setText(snapshot.status_message)


def _disabled_action_button(
    text: str,
    *,
    tooltip: str = "",
    parent: QWidget | None = None,
) -> QPushButton:
    """Create a disabled planner action button for deferred workflows.

    Parameters
    ----------
    text : str
        Text displayed on the button.
    tooltip : str, optional
        Tooltip explaining why the action is disabled.
    parent : QWidget, optional
        Parent widget.

    Returns
    -------
    QPushButton
        Disabled secondary-style button.
    """
    button = QPushButton(text, parent)
    button.setEnabled(False)
    button.setProperty("buttonRole", "secondary")
    if tooltip:
        button.setToolTip(tooltip)
    return button


def _add_buttons(layout: QHBoxLayout, buttons: tuple[QPushButton, ...]) -> None:
    """Add planner action buttons to a horizontal layout with trailing stretch."""
    for button in buttons:
        layout.addWidget(button)
    layout.addStretch(1)



class PlannerSetupGenerationPage(PlannerPageShell):
    """Planner setup/generation page with v1-equivalent controls and table."""

    def __init__(
        self,
        *,
        page: NavigationNode,
        planner_controller: PlannerController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(page=page, planner_controller=planner_controller, parent=parent)

        self.controls = PlannerControlsCard(self.content_host)
        self.controls.apply_preferences(self._planner_controller.preferences)
        self.content_layout.addWidget(self.controls)

        splitter = QSplitter(Qt.Orientation.Horizontal, self.content_host)
        splitter.setObjectName("guiPlannerSetupSplitter")

        table_card = PlannerShellCard(
            title="Visibility Data",
            parent=splitter,
        )
        self.visibility_table = PlannerVisibilityTable(table_card)
        self.visibility_table.setObjectName("guiPlannerVisibilityTable")
        self.visibility_table.setMinimumHeight(260)
        table_card.layout.addWidget(self.visibility_table, 1)
        splitter.addWidget(table_card)

        log_card = PlannerShellCard(
            title="Planner Log",
            parent=splitter,
        )
        log_card.setMinimumWidth(280)
        self.log_console = QPlainTextEdit(log_card)
        self.log_console.setObjectName("guiPlannerLogConsole")
        self.log_console.setReadOnly(True)
        self.log_console.setMinimumHeight(260)
        self.log_console.setPlainText("Planner setup ready. Load visibility data to begin.")
        log_card.layout.addWidget(self.log_console, 1)
        splitter.addWidget(log_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        self.content_layout.addWidget(splitter, 1)

        self._connect_controls()
        self._connect_controller()
        self._handle_planner_preferences_changed(planner_controller.preferences)
        self._handle_planner_state_changed(planner_controller.current_snapshot())

    def _connect_controls(self) -> None:
        self.controls.loadVisibilityRequested.connect(self._choose_visibility_file)
        self.controls.loadTleRequested.connect(self._choose_tle_file)
        self.controls.loadTargetsRequested.connect(self._choose_targets_file)
        self.controls.applyTargetsToggled.connect(self._apply_or_revert_targets)
        self.controls.satelliteFilterChanged.connect(self._planner_controller.filter_by_satellite)
        self.controls.generatePlanRequested.connect(self._generate_plan)
        self.controls.cancelGenerationRequested.connect(self._cancel_plan_generation)
        self.controls.exposureTimeChanged.connect(self._planner_controller.set_exposure_time_seconds)
        self.controls.coordinateFormatChanged.connect(self._planner_controller.set_coordinate_format)
        self.visibility_table.row_selected.connect(self._planner_controller.select_visibility_row)
        self.visibility_table.model().user_check_state_changed.connect(self._handle_user_check_state_changed)

    def _connect_controller(self) -> None:
        self._planner_controller.logMessage.connect(self._append_log_message)
        self._planner_controller.visibilityTableChanged.connect(self.visibility_table.set_dataframe)
        self._planner_controller.satellitesChanged.connect(self.controls.set_satellites)
        self._planner_controller.targetsAvailabilityChanged.connect(self.controls.set_targets_available)
        self._planner_controller.loadStateChanged.connect(self._handle_load_state_changed)
        self._planner_controller.failed.connect(self._handle_controller_failure)
        self._planner_controller.checkedRowsChanged.connect(self._handle_checked_rows_changed)
        self._planner_controller.visibilityTableFocusRequested.connect(self.visibility_table.focus_row)
        self._planner_controller.preferencesChanged.connect(self._handle_planner_preferences_changed)
        self._planner_controller.exposureTimeChanged.connect(self.controls.set_exposure_time_seconds)

    def _handle_planner_preferences_changed(self, preferences: object) -> None:
        """Apply saved planner defaults to the setup controls."""
        self.controls.apply_preferences(preferences)  # type: ignore[arg-type]

    def _generate_plan(self) -> None:
        """Start real planner generation from the current control values."""
        self._planner_controller.generate_plan(
            use_json_times=self.controls.use_json_times(),
            tolerance_sec=self.controls.selected_tolerance_sec(),
            spacing_min=self.controls.selected_spacing_min(),
            min_elevation=self.controls.selected_min_elevation(),
            time_range_sec=self.controls.selected_time_range_sec(),
            plan_method=self.controls.selected_plan_method(),
            binning_mode=self.controls.selected_binning_mode(),
            sample_bins=self.controls.selected_sample_bins(),
            bin_width_deg=self.controls.selected_bin_width_deg(),
        )

    def _cancel_plan_generation(self) -> None:
        """Request cooperative cancellation of the active planner worker."""
        if not self._planner_controller.cancel_plan_generation():
            self._planner_controller.append_log("No observation plan generation is currently running.")

    def _handle_user_check_state_changed(self, row: int, checked: bool) -> None:
        """Synchronize manual checkbox edits with the controller-owned plan."""
        self._planner_controller.add_or_remove_manual_row(
            row,
            checked,
            spacing_min=self.controls.selected_spacing_min(),
        )

    def _handle_checked_rows_changed(self, updates: object) -> None:
        """Refresh changed checkbox rows in the current visibility table."""
        rows = []
        if isinstance(updates, dict):
            rows = list(updates.get("data_view", []))
        self.visibility_table.model().refresh_checked_rows(rows)

    def _choose_visibility_file(self) -> None:
        file_path = self._choose_open_file(
            "Load Visibility Data",
            "Visibility data (*.csv *.txt *.dat);;CSV files (*.csv);;All files (*.*)",
        )
        if file_path is not None:
            self._planner_controller.load_visibility_file(file_path)

    def _choose_tle_file(self) -> None:
        file_path = self._choose_open_file(
            "Load TLE File",
            "TLE files (*.txt *.tle);;Text files (*.txt);;All files (*.*)",
        )
        if file_path is not None:
            self._planner_controller.load_tle_file(file_path)

    def _choose_targets_file(self) -> None:
        file_path = self._choose_open_file(
            "Load Targets JSON",
            "Target JSON (*.json);;All files (*.*)",
        )
        if file_path is not None:
            self._planner_controller.load_targets_file(file_path)

    def _choose_open_file(self, title: str, filters: str) -> Path | None:
        file_path, _ = QFileDialog.getOpenFileName(self, title, "", filters)
        return Path(file_path) if file_path else None

    def _apply_or_revert_targets(self, checked: bool) -> None:
        self.controls.set_apply_targets_processing()
        if not self._planner_controller.apply_or_revert_targets(checked):
            self.controls.set_apply_targets_state(False, available=False)

    def _append_log_message(self, message: str) -> None:
        if message:
            append_log_line(self.log_console, message)

    def _handle_load_state_changed(self, kind: str, state: str, detail: str) -> None:
        self.controls.set_load_state(kind, state, detail=detail or None)

    def _handle_controller_failure(self, message: str, context: str) -> None:
        summary = message.splitlines()[0] if message else "Unknown error"
        append_log_line(self.log_console, f"ERROR [{context}]: {summary}")

    def _handle_planner_state_changed(self, snapshot: PlannerRuntimeSnapshot) -> None:
        super()._handle_planner_state_changed(snapshot)
        readiness = snapshot.readiness
        self.controls.set_tle_available(readiness.visibility_loaded)
        self.controls.set_targets_available(readiness.targets_loaded and readiness.visibility_loaded, has_times=snapshot.target_has_times)
        self.controls.set_apply_targets_state(snapshot.targets_applied, available=readiness.targets_loaded and readiness.visibility_loaded)
        status = snapshot.generation_status
        self.controls.set_generation_state(
            ready_for_generation=readiness.ready_for_generation,
            running=status == PlannerGenerationStatus.GENERATING,
            canceling=status == PlannerGenerationStatus.CANCELING,
        )


__all__ = (
    "PlannerPageShell",
    "PlannerSetupGenerationPage",
    "_add_buttons",
    "_disabled_action_button",
    "PlannerShellCard",
)
