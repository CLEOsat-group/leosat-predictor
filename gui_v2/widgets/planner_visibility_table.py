"""GUI-v2 adapter for the modular observation-planner visibility table."""

from __future__ import annotations

from PyQt6.QtCore import QItemSelectionModel, QModelIndex, QSignalBlocker, Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QHeaderView, QTableView

from gui_v2.widgets.observation_visibility_table import ObservationVisibilityTable


class PlannerVisibilityTable(ObservationVisibilityTable):
    """GUI-v2 owned adapter around the existing model/view visibility table.

    The wrapped table is a modular QTableView-based component, not the monolithic
    v1 Observation Planner screen. Keeping this adapter thin avoids duplicating
    large-table column-width behavior while preserving a clear GUI-v2 import
    boundary for later promotion work.
    """

    def __init__(self, parent=None):
        """Initialize the GUI-v2 table adapter."""
        super().__init__(parent)
        self.setWordWrap(False)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.verticalHeader().setDefaultSectionSize(22)

    def set_dataframe(self, dataframe) -> None:
        """Display a visibility DataFrame without recursive selection churn.

        Parameters
        ----------
        dataframe : pandas.DataFrame or None
            Current planner visibility table.
        """
        selection_model = self.selectionModel()
        blocker = QSignalBlocker(selection_model) if selection_model is not None else None
        try:
            self.setUpdatesEnabled(False)
            super().set_dataframe(dataframe)
            if selection_model is not None:
                selection_model.clearSelection()
            self.clearSelection()
            self.setCurrentIndex(QModelIndex())
        finally:
            self.setUpdatesEnabled(True)
            if blocker is not None:
                del blocker

    def focus_row(self, row: int) -> None:
        """Scroll to and select one model row using GUI-v2/PyQt6 semantics.

        Parameters
        ----------
        row : int
            Source-model row to select.

        Notes
        -----
        The base table belongs to the legacy ``gui`` package and still exposes a
        Qt5-era selection-flag spelling. GUI-v2 must not patch that file during
        Task 48D, so the adapter owns the PyQt6-specific programmatic selection
        behavior here. Selection-model signals are blocked during this method to
        avoid feeding controller-originated focus changes back into the same
        controller selection path.
        """
        model = self.model()
        if row < 0 or row >= model.rowCount():
            return

        index = model.index(row, 0)
        selection_model = self.selectionModel()
        if selection_model is None:
            return

        flags = (
            QItemSelectionModel.SelectionFlag.ClearAndSelect
            | QItemSelectionModel.SelectionFlag.Rows
        )

        blocker = QSignalBlocker(selection_model)
        try:
            self.scrollTo(index, QTableView.ScrollHint.PositionAtCenter)
            selection_model.select(index, flags)
            self.setCurrentIndex(index)
        finally:
            del blocker

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Toggle the checkbox column explicitly for GUI-v2 users.

        The inherited model already exposes a checkable ``_checked`` column, but
        relying entirely on the default delegate made the GUI-v2 checkbox path
        fragile under row-selection styling. Handling clicks in the adapter keeps
        the fix inside GUI-v2 and still routes the change through ``setData`` so
        the existing ``user_check_state_changed`` signal remains the single
        source of truth for manual plan edits.
        """
        index = self.indexAt(event.position().toPoint())
        if self._is_check_column(index):
            self._toggle_check_state(index.row())
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Toggle the selected-row checkbox with Space for keyboard parity."""
        if event.key() == Qt.Key.Key_Space:
            row = self.selected_source_row()
            if row is not None:
                self._toggle_check_state(row)
                event.accept()
                return
        super().keyPressEvent(event)

    def _is_check_column(self, index) -> bool:
        """Return whether *index* points at the manual-selection checkbox."""
        if not index.isValid():
            return False
        try:
            return self.model().logical_column(index.column()) == "_checked"
        except Exception:
            return False

    def _toggle_check_state(self, row: int) -> bool:
        """Toggle the check state for one source-model row.

        Parameters
        ----------
        row : int
            Source-model row index.

        Returns
        -------
        bool
            `True` when the model accepted the state change.
        """
        model = self.model()
        check_column = model.column_for_logical("_checked")
        if check_column is None or row < 0 or row >= model.rowCount():
            return False
        index = model.index(row, check_column)
        current = model.data(index, Qt.ItemDataRole.CheckStateRole)
        target = Qt.CheckState.Unchecked if current == Qt.CheckState.Checked else Qt.CheckState.Checked
        return bool(model.setData(index, target, Qt.ItemDataRole.CheckStateRole))


__all__ = ("PlannerVisibilityTable",)
