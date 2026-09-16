"""Custom results view for scalable predictor output display."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import QApplication, QTableView


class PredictionResultsView(QTableView):
    """QTableView with copy support tailored for large result sets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("guiV2PredictionResultsTable")
        self.setProperty("visualRole", "dataTable")

    def keyPressEvent(self, event):  # noqa: D401
        """Handle common copy shortcuts while preserving normal table behavior."""
        if event.matches(QKeySequence.Copy):
            self.copy_selection_to_clipboard()
            event.accept()
            return
        super().keyPressEvent(event)

    def copy_selection_to_clipboard(self) -> None:
        """Copy the current selection as tab-separated text."""
        selection_model = self.selectionModel()
        model = self.model()
        if selection_model is None or model is None:
            return

        indexes = selection_model.selectedIndexes()
        if not indexes:
            return

        indexes = sorted(indexes, key=lambda idx: (idx.row(), idx.column()))
        rows: dict[int, dict[int, str]] = {}
        min_col = min(idx.column() for idx in indexes)
        max_col = max(idx.column() for idx in indexes)

        for index in indexes:
            rows.setdefault(index.row(), {})[index.column()] = str(model.data(index, Qt.ItemDataRole.DisplayRole) or "")

        lines = []
        for row in sorted(rows):
            line = [rows[row].get(col, "") for col in range(min_col, max_col + 1)]
            lines.append("\t".join(line))

        QApplication.clipboard().setText("\n".join(lines))
