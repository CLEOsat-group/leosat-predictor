"""Compact load action button with an integrated state indicator."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from gui.styles import repolish
from gui.styles.icon_provider import set_themed_icon


class PlannerLoadButton(QWidget):
    """Button plus accessible colored state indicator for planner load actions.

    Parameters
    ----------
    text : str
        Button text.
    parent : QWidget, optional
        Parent widget.
    """

    clicked = pyqtSignal()

    _STATE_LABELS = {
        "idle": "Not loaded",
        "loading": "Loading",
        "loaded": "Loaded",
        "error": "Error",
        "disabled": "Disabled",
    }

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_text = text
        self._state = "idle"
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.indicator = QLabel("●", self)
        self.indicator.setFixedWidth(14)
        self.indicator.setObjectName("guiPlannerLoadIndicator")
        layout.addWidget(self.indicator)

        self.button = QPushButton(text, self)
        self.button.setProperty("buttonRole", "secondary")
        set_themed_icon(self.button, "folder_open", size=16)
        self.button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.button.clicked.connect(self.clicked)
        layout.addWidget(self.button)
        self.set_state("idle")

    @property
    def state(self) -> str:
        """Return the current load-state identifier."""
        return self._state

    def set_state(self, state: str, *, detail: str | None = None) -> None:
        """Update the indicator and tooltip.

        Parameters
        ----------
        state : str
            One of ``idle``, ``loading``, ``loaded``, ``error``, or ``disabled``.
        detail : str, optional
            Additional tooltip context.
        """
        normalized = state if state in self._STATE_LABELS else "idle"
        self._state = normalized
        label = self._STATE_LABELS[normalized]
        self.indicator.setProperty("loadState", normalized)
        repolish(self.indicator)
        tooltip = f"{self._base_text}: {label}"
        if detail:
            tooltip = f"{tooltip}. {detail}"
        self.setToolTip(tooltip)
        self.button.setToolTip(tooltip)
        self.indicator.setToolTip(tooltip)
        if normalized == "loaded":
            self.button.setText(f"{self._base_text} ✓")
        elif normalized == "loading":
            self.button.setText(f"{self._base_text}…")
        else:
            self.button.setText(self._base_text)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt override name
        """Enable/disable the embedded button and update disabled state."""
        super().setEnabled(enabled)
        self.button.setEnabled(enabled)
        if not enabled:
            self.set_state("disabled")
        elif self._state == "disabled":
            self.set_state("idle")


__all__ = ("PlannerLoadButton",)
