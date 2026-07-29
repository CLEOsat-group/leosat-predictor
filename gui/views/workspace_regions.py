"""Reusable card widgets for GUI placeholder workspaces."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QSizePolicy, QWidget


class WorkspaceRegionCard(QFrame):
    """Card that marks a future workflow region without showing fake data."""

    def __init__(self, title: str, body: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QGridLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setHorizontalSpacing(0)
        layout.setVerticalSpacing(10)

        title_label = QLabel(title, self)
        title_label.setObjectName("guiCardTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label, 0, 0)

        body_label = QLabel(body, self)
        body_label.setObjectName("guiCardBody")
        body_label.setWordWrap(True)
        body_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(body_label, 1, 0)
        layout.setColumnStretch(0, 1)
        layout.setRowStretch(0, 0)
        layout.setRowStretch(1, 1)
