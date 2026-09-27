"""Professional placeholder pages for the GUI replacement path."""

from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QWidget

from gui.shell.navigation_model import NavigationNode
from gui.views.workspace_regions import WorkspaceRegionCard


class PlaceholderPage(QWidget):
    """Structured placeholder page for one approved GUI workspace."""

    def __init__(self, page: NavigationNode, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.page = page
        self.setObjectName("guiPlaceholderPage")

        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setHorizontalSpacing(0)
        root.setVerticalSpacing(12)

        grid_host = QWidget(self)
        grid_host.setObjectName("guiWorkspaceGrid")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        for index, region in enumerate(page.regions):
            card = WorkspaceRegionCard(
                title=region,
                body=(
                    "Placeholder region only. This card defines the intended workspace structure; "
                    "it does not show fabricated operational data or execute deferred operations."
                ),
                parent=grid_host,
            )
            row = index // 2
            column = index % 2
            grid.addWidget(card, row, column)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addWidget(grid_host, 0, 0)
        root.setColumnStretch(0, 1)
        root.setRowStretch(0, 1)
