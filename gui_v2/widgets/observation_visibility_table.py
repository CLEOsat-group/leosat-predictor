"""Visibility table view for the observation planner."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QItemSelectionModel, QTimer, pyqtSignal
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from gui_v2.models.observation_visibility_table_model import ObservationVisibilityTableModel


class ObservationVisibilityTable(QTableView):
    """QTableView wrapper for visibility data.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget.
    """

    row_selected = pyqtSignal(int)

    #: Hidden helper columns are retained in the model for plot/selection
    #: identity, but must never consume visible table width.
    _HIDDEN_LOGICAL_COLUMNS = {"date_ts", "global_index", "base_index", "local_index"}

    #: Compact empty-table widths.  These keep the planner workspace usable
    #: before data are present; populated tables are auto-sized from contents.
    _MIN_COLUMN_WIDTHS = {
        "_checked": 28,
        "satellite": 90,
        "date_ut": 120,
        "ra": 62,
        "dec": 72,
        "elev": 70,
        "solar_phase_angle": 92,
    }

    #: Maximum widths prevent long headers from dominating the planner table
    #: while still allowing cell contents to remain readable.
    _MAX_COLUMN_WIDTHS = {
        "_checked": 32,
        "satellite": 140,
        "date_ut": 165,
        "ra": 82,
        "dec": 92,
        "elev": 82,
        "solar_phase_angle": 115,
    }

    _DEFAULT_MIN_COLUMN_WIDTH = 70
    _DEFAULT_MAX_COLUMN_WIDTH = 135

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("guiV2PlannerVisibilityTable")
        self.setProperty("visualRole", "dataTable")
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSortingEnabled(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.verticalHeader().setVisible(True)
        self.horizontalHeader().setStretchLastSection(False)
        self._model = ObservationVisibilityTableModel(self)
        self.setModel(self._model)
        self.selectionModel().selectionChanged.connect(self._emit_selected_row)
        self._resize_pending = False
        self._connect_model_resize_signals()
        self.apply_column_widths()

    def model(self) -> ObservationVisibilityTableModel:  # type: ignore[override]
        """Return the strongly typed visibility table model."""
        return self._model

    def _connect_model_resize_signals(self) -> None:
        """Connect model mutations to deferred content-aware resizing."""
        self._model.modelReset.connect(self._schedule_content_resize)
        self._model.rowsInserted.connect(self._schedule_content_resize)
        self._model.rowsRemoved.connect(self._schedule_content_resize)
        self._model.layoutChanged.connect(self._schedule_content_resize)

    def _schedule_content_resize(self, *_) -> None:
        """Resize once after Qt has completed the current model/view update.

        Large visibility CSVs can contain tens of thousands of rows.  The
        previous implementation scheduled a full resize every time Qt emitted
        a model-change signal.  Coalescing keeps loading responsive and avoids
        repeated table scans.
        """
        if self._resize_pending:
            return
        self._resize_pending = True
        QTimer.singleShot(0, self._apply_scheduled_column_widths)

    def _apply_scheduled_column_widths(self) -> None:
        """Apply pending column-width update."""
        self._resize_pending = False
        self.apply_column_widths()

    def _column_min_width(self, logical: str) -> int:
        """Return the compact empty-state width for one logical column."""
        return self._MIN_COLUMN_WIDTHS.get(logical, self._DEFAULT_MIN_COLUMN_WIDTH)

    def _column_max_width(self, logical: str) -> int:
        """Return the maximum auto-sized width for one logical column."""
        return self._MAX_COLUMN_WIDTHS.get(logical, self._DEFAULT_MAX_COLUMN_WIDTH)

    def apply_column_widths(self) -> None:
        """Apply compact, fast column widths and hide helper columns.

        Full-column Qt auto-sizing asks the model for every visible cell in a
        column.  That is acceptable for the small Observation Plan table, but
        too slow for visibility CSVs with tens of thousands of rows.  This
        table therefore estimates populated widths from a bounded sample while
        preserving compact minimum widths and maximum clamps.
        """
        header = self.horizontalHeader()
        row_count = self._model.rowCount()

        for column in range(self._model.columnCount()):
            logical = self._model.logical_column(column)
            if logical is None:
                continue

            if logical in self._HIDDEN_LOGICAL_COLUMNS:
                self.setColumnHidden(column, True)
                continue

            self.setColumnHidden(column, False)
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)

            min_width = self._column_min_width(logical)
            max_width = self._column_max_width(logical)
            if row_count > 0:
                content_width = self._estimate_column_width(column, logical)
                width = max(min_width, min(content_width, max_width))
            else:
                width = min_width

            header.resizeSection(column, width)

    def _estimate_column_width(self, column: int, logical: str) -> int:
        """Estimate column width from header text and a bounded row sample.

        Parameters
        ----------
        column : int
            Model column index.
        logical : str
            Logical planner column name.

        Returns
        -------
        int
            Estimated pixel width including cell padding.
        """
        del logical  # kept for symmetry with width policy helpers.
        row_count = self._model.rowCount()
        if row_count <= 0:
            return self._DEFAULT_MIN_COLUMN_WIDTH

        font_metrics = self.fontMetrics()
        header_text = self._model.headerData(column, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) or ""
        widest = font_metrics.horizontalAdvance(str(header_text))

        for row in self._sample_rows(row_count):
            index = self._model.index(row, column)
            value = self._model.data(index, Qt.ItemDataRole.DisplayRole)
            if value is None:
                continue
            widest = max(widest, font_metrics.horizontalAdvance(str(value)))

        # QTableView needs modest padding for grid, sort margin, and checkbox
        # columns.  Keep the value intentionally small to preserve compactness.
        return widest + 18

    @staticmethod
    def _sample_rows(row_count: int, sample_size: int = 150) -> list[int]:
        """Return representative row indexes without scanning the full table."""
        if row_count <= sample_size:
            return list(range(row_count))
        head = list(range(min(75, row_count)))
        tail_start = max(len(head), row_count - 75)
        tail = list(range(tail_start, row_count))
        return head + tail

    def set_dataframe(self, dataframe) -> None:
        """Display a new visibility DataFrame."""
        self._model.set_dataframe(dataframe)

    def selected_source_row(self) -> int | None:
        """Return the currently selected model row, if any."""
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        return indexes[0].row()

    def focus_row(self, row: int) -> None:
        """Scroll to and select one model row."""
        if row < 0 or row >= self._model.rowCount():
            return
        index = self._model.index(row, 0)
        self.scrollTo(index, QTableView.ScrollHint.PositionAtCenter)
        self.selectionModel().clearSelection()
        self.selectionModel().select(index, QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self.setCurrentIndex(index)

    def _emit_selected_row(self) -> None:
        """Emit the selected row when the table selection changes."""
        row = self.selected_source_row()
        if row is not None:
            self.row_selected.emit(row)
