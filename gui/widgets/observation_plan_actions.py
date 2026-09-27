"""Action-button row for the Observation Planner plan table."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QPushButton, QSizePolicy, QSpacerItem, QWidget

from gui.styles.icon_provider import set_themed_icon


class ObservationPlanActions(QWidget):
    """Plan-table action buttons.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget.
    """

    select_requested = pyqtSignal()
    remove_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    export_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("observationPlanActionRow")

        self.select_button = QPushButton("Select Observation")
        self.remove_button = QPushButton("Remove Observation")
        self.clear_button = QPushButton("Clear Plan")
        self.export_button = QPushButton("Export Plan")
        self.select_button.setProperty("buttonRole", "primary")
        self.remove_button.setProperty("buttonRole", "secondary")
        self.clear_button.setProperty("buttonRole", "danger")
        self.export_button.setProperty("buttonRole", "success")
        set_themed_icon(self.export_button, "save", size=16)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setColumnStretch(0, 1)
        layout.addItem(QSpacerItem(20, 1, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum), 0, 0)
        layout.addWidget(self.select_button, 0, 1)
        layout.addWidget(self.remove_button, 0, 2)
        layout.addWidget(self.clear_button, 0, 3)
        layout.addWidget(self.export_button, 0, 4)

        self.select_button.clicked.connect(self.select_requested)
        self.remove_button.clicked.connect(self.remove_requested)
        self.clear_button.clicked.connect(self.clear_requested)
        self.export_button.clicked.connect(self.export_requested)
