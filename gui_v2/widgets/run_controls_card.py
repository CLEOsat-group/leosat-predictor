"""Reusable run-controls card for GUI v2 prediction setup pages."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QWidget

from gui_v2.state.overpass_execution_state import OverpassExecutionState, OverpassRunStatus
from gui_v2.styles.effects import apply_card_elevation
from gui_v2.styles.icon_provider import set_themed_icon


class ValidationStateLike(Protocol):
    """Minimal validation-state interface consumed by ``RunControlsCard``."""

    is_ready: bool
    summary: str


class ExecutionStateLike(Protocol):
    """Minimal execution-state interface consumed by ``RunControlsCard``."""

    status: object
    message: str
    detail: str


LogCallback = Callable[[str, str], None]

_DEFAULT_HANDOFF_BUTTON_TEXT = "Planner Handoff"
_OVERPASS_EXPORT_AVAILABLE_TOOLTIP = "Export current overpass results to CSV."
_RUNNING_STATUS_VALUES = {"running", OverpassRunStatus.RUNNING.value}
_CANCELLING_STATUS_VALUES = {"cancelling", OverpassRunStatus.CANCELLING.value}
_SUCCEEDED_STATUS_VALUES = {"succeeded", OverpassRunStatus.SUCCEEDED.value}
_FAILED_OR_CANCELLED_STATUS_VALUES = {"failed", "cancelled", OverpassRunStatus.FAILED.value, OverpassRunStatus.CANCELLED.value}
_ACTIVE_STATUS_VALUES = _RUNNING_STATUS_VALUES | _CANCELLING_STATUS_VALUES


class RunControlsCard(QFrame):
    """Run-control strip for validated prediction setup and execution state."""

    runRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    exportRequested = pyqtSignal()
    handoffRequested = pyqtSignal()

    def __init__(
        self,
        *,
        log_callback: LogCallback | None = None,
        parent: QWidget | None = None,
        workflow_label: str = "overpass",
        run_button_text: str = "Run Overpass",
        readiness_waiting_text: str | None = None,
        show_export_button: bool = True,
        show_handoff_button: bool = False,
        handoff_button_text: str = _DEFAULT_HANDOFF_BUTTON_TEXT,
    ) -> None:
        super().__init__(parent)
        self._log_callback = log_callback
        self._workflow_label = workflow_label.strip().lower() or "overpass"
        self._workflow_title = self._workflow_label.capitalize()
        self._last_validation_state: ValidationStateLike | None = None
        self._execution_state: ExecutionStateLike = OverpassExecutionState.idle()
        self._export_available = False
        self._handoff_available = False
        self._show_export_button = show_export_button
        self._show_handoff_button = show_handoff_button
        self.setObjectName("guiV2Card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        apply_card_elevation(self)

        grid = QGridLayout(self)
        grid.setContentsMargins(16, 12, 16, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        title = QLabel("Run Controls & Validation Summary", self)
        title.setObjectName("guiV2CardTitle")
        grid.addWidget(title, 0, 0, 1, 5)

        self.readiness_label = QLabel(
            readiness_waiting_text or f"{self._workflow_title} setup validation is waiting for input.",
            self,
        )
        self.readiness_label.setObjectName("guiV2CardBody")
        self.readiness_label.setWordWrap(True)
        grid.addWidget(self.readiness_label, 1, 0, 1, 5)

        self.run_button = QPushButton(run_button_text, self)
        self.run_button.setObjectName(f"guiV2Run{self._workflow_title}Button")
        self.run_button.setProperty("buttonRole", "primary")
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setObjectName(f"guiV2Cancel{self._workflow_title}Button")
        self.cancel_button.setProperty("buttonRole", "danger")
        self.export_button = QPushButton("Export to CSV", self)
        self.export_button.setObjectName(f"guiV2Export{self._workflow_title}Button")
        self.export_button.setProperty("buttonRole", "success")
        self.handoff_button = QPushButton(handoff_button_text, self)
        self.handoff_button.setObjectName(f"guiV2Handoff{self._workflow_title}Button")
        self.handoff_button.setProperty("buttonRole", "secondary")
        set_themed_icon(self.export_button, "save", size=16)
        set_themed_icon(self.handoff_button, "send", size=16)

        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.handoff_button.setEnabled(False)
        self.export_button.setVisible(show_export_button)
        self.handoff_button.setVisible(show_handoff_button)
        self.export_button.setToolTip(f"Export is available after a successful {self._workflow_label} run.")
        self.handoff_button.setToolTip(f"Planner handoff is available after a successful {self._workflow_label} run.")

        grid.addWidget(self.run_button, 2, 1)
        grid.addWidget(self.cancel_button, 2, 2)
        grid.addWidget(self.export_button, 2, 3)
        grid.addWidget(self.handoff_button, 2, 4)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 0)
        grid.setColumnStretch(4, 0)

        self.run_button.clicked.connect(self.runRequested.emit)
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        self.export_button.clicked.connect(self.exportRequested.emit)
        self.handoff_button.clicked.connect(self.handoffRequested.emit)
        self._log(
            f"Run controls created; {self._workflow_label} validation and execution readiness are active.",
            "INFO",
        )

    def set_validation_state(self, state: ValidationStateLike) -> None:
        """Render centralized setup validation state when idle."""
        self._last_validation_state = state
        if _status_value(self._execution_state.status) in _ACTIVE_STATUS_VALUES:
            return
        self.run_button.setEnabled(state.is_ready)
        self.cancel_button.setEnabled(False)
        self.export_button.setEnabled(self._show_export_button and self._export_available)
        self.handoff_button.setEnabled(self._show_handoff_button and self._handoff_available)
        self.readiness_label.setText(state.summary)
        self.run_button.setToolTip(f"Start {self._workflow_label} prediction." if state.is_ready else state.summary)
        self.cancel_button.setToolTip(f"No {self._workflow_label} prediction is currently running.")
        self.export_button.setToolTip(
            f"Export current {self._workflow_label} results to CSV."
            if self._show_export_button and self._export_available
            else f"Export is available after a successful {self._workflow_label} run."
        )
        self.handoff_button.setToolTip(
            f"Send current {self._workflow_label} results to the observation planner."
            if self._show_handoff_button and self._handoff_available
            else f"Planner handoff is available after a successful {self._workflow_label} run."
        )

    def set_execution_state(self, state: ExecutionStateLike) -> None:
        """Render active prediction execution state.

        The card accepts any state object with ``status``, ``message``, and
        ``detail`` attributes. Status comparisons are value-based so overpass
        and precise state models can share this widget without either workflow
        importing the other.
        """
        self._execution_state = state
        status = _status_value(state.status)
        if status in _RUNNING_STATUS_VALUES:
            self.run_button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.export_button.setEnabled(False)
            self.handoff_button.setEnabled(False)
            self.readiness_label.setText(state.message)
            self.run_button.setToolTip(f"{self._workflow_title} prediction is already running.")
            self.cancel_button.setToolTip(f"Cancel the active {self._workflow_label} prediction.")
            return
        if status in _CANCELLING_STATUS_VALUES:
            self.run_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.handoff_button.setEnabled(False)
            self.readiness_label.setText(state.message)
            self.cancel_button.setToolTip(state.detail)
            return
        if status in _SUCCEEDED_STATUS_VALUES:
            self.run_button.setEnabled(bool(self._last_validation_state and self._last_validation_state.is_ready))
            self.cancel_button.setEnabled(False)
            self.export_button.setEnabled(self._show_export_button and self._export_available)
            self.handoff_button.setEnabled(self._show_handoff_button and self._handoff_available)
            self.export_button.setToolTip(
                f"Export current {self._workflow_label} results to CSV."
                if self._show_export_button and self._export_available
                else f"Export is available after a successful {self._workflow_label} run."
            )
            self.handoff_button.setToolTip(
                f"Send current {self._workflow_label} results to the observation planner."
                if self._show_handoff_button and self._handoff_available
                else f"Planner handoff is available after a successful {self._workflow_label} run."
            )
            self.readiness_label.setText(state.message)
            return
        if status in _FAILED_OR_CANCELLED_STATUS_VALUES:
            self.run_button.setEnabled(bool(self._last_validation_state and self._last_validation_state.is_ready))
            self.cancel_button.setEnabled(False)
            self.export_button.setEnabled(self._show_export_button and self._export_available)
            self.handoff_button.setEnabled(self._show_handoff_button and self._handoff_available)
            self.export_button.setToolTip(
                f"Export current {self._workflow_label} results to CSV."
                if self._show_export_button and self._export_available
                else f"Export is available after a successful {self._workflow_label} run."
            )
            self.handoff_button.setToolTip(
                f"Send current {self._workflow_label} results to the observation planner."
                if self._show_handoff_button and self._handoff_available
                else f"Planner handoff is available after a successful {self._workflow_label} run."
            )
            self.readiness_label.setText(state.message if not state.detail else f"{state.message} {state.detail}")
            return
        if self._last_validation_state is not None:
            self.set_validation_state(self._last_validation_state)

    def set_export_available(self, available: bool) -> None:
        """Render whether completed results can be exported from this page."""
        self._export_available = available
        if _status_value(self._execution_state.status) in _ACTIVE_STATUS_VALUES:
            self.export_button.setEnabled(False)
            self.export_button.setToolTip(f"Export is disabled while a {self._workflow_label} prediction is running.")
            return
        self.export_button.setEnabled(self._show_export_button and available)
        self.export_button.setToolTip(
            f"Export current {self._workflow_label} results to CSV."
            if self._show_export_button and available
            else f"Export is available after a successful {self._workflow_label} run."
        )

    def set_handoff_available(self, available: bool) -> None:
        """Render whether completed results can be sent to the planner."""
        self._handoff_available = available
        if _status_value(self._execution_state.status) in _ACTIVE_STATUS_VALUES:
            self.handoff_button.setEnabled(False)
            self.handoff_button.setToolTip(f"Planner handoff is disabled while a {self._workflow_label} prediction is running.")
            return
        self.handoff_button.setEnabled(self._show_handoff_button and available)
        self.handoff_button.setToolTip(
            f"Send current {self._workflow_label} results to the observation planner."
            if self._show_handoff_button and available
            else f"Planner handoff is available after a successful {self._workflow_label} run."
        )

    def _log(self, message: str, level: str = "INFO") -> None:
        if self._log_callback is not None:
            self._log_callback(message, level)


def _status_value(status: object) -> str:
    """Return a lower-case lifecycle status value for enum or string inputs."""
    value = getattr(status, "value", status)
    return str(value).strip().lower()
