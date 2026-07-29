"""Observation-plan table view with semantic full-row hover feedback."""

from __future__ import annotations

import weakref

from PyQt6.QtCore import QEvent, QModelIndex, QRect, QSignalBlocker, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from gui.models.observation_plan_table_model import ObservationPlanRecord, ObservationPlanTableModel
from gui.styles import active_theme_palette


_HOVER_BLEND_ALPHA = 0.20
_SELECTION_BLEND_ALPHA = 0.22
_SELECTED_HOVER_BLEND_ALPHA = 0.0


def _blend_colors(base: QColor, overlay: QColor, alpha: float) -> QColor:
    """Return an opaque linear blend of ``base`` and ``overlay``."""

    factor = max(0.0, min(1.0, float(alpha)))
    inverse = 1.0 - factor
    return QColor(
        round(base.red() * inverse + overlay.red() * factor),
        round(base.green() * inverse + overlay.green() * factor),
        round(base.blue() * inverse + overlay.blue() * factor),
    )


class _PlanRowHoverDelegate(QStyledItemDelegate):
    """Paint a theme-aware row hover without modifying model roles."""

    def __init__(self, table: "ObservationPlanTable") -> None:
        super().__init__(table)
        self._table_ref = weakref.ref(table)

    def initStyleOption(  # noqa: N802
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        """Compose semantic, persistent-selection, and hover backgrounds."""

        super().initStyleOption(option, index)
        table = self._table_ref()
        if table is None:
            return

        palette = active_theme_palette()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = index.row() == table.hovered_row
        base = option.backgroundBrush.color()
        if not base.isValid() or option.backgroundBrush.style() == Qt.BrushStyle.NoBrush:
            base = QColor(palette.surface_alt)

        if selected:
            base = _blend_colors(base, QColor(palette.row_selection_background), _SELECTION_BLEND_ALPHA)
        if hovered:
            hover_alpha = _SELECTED_HOVER_BLEND_ALPHA if selected else _HOVER_BLEND_ALPHA
            base = _blend_colors(base, QColor(palette.row_hover_background), hover_alpha)
        option.backgroundBrush = QBrush(base)

        # Suppress the generic QSS selection fill.  The delegate paints a
        # persistent row selection that preserves generated/manual/past context.
        option.state &= ~QStyle.StateFlag.State_Selected

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex,
    ) -> None:
        """Paint the item and continuous selection/hover row outlines."""

        table = self._table_ref()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = table is not None and index.row() == table.hovered_row
        super().paint(painter, option, index)
        if table is None or not (selected or hovered):
            return

        palette = active_theme_palette()
        painter.save()
        try:
            border = palette.row_selection_border if selected else palette.row_hover_border
            if selected and hovered:
                border = palette.row_hover_border
            pen = QPen(QColor(border))
            pen.setWidthF(2.0 if selected else 1.25)
            painter.setPen(pen)
            rect = option.rect.adjusted(0, 0, -1, -1)
            painter.drawLine(rect.topLeft(), rect.topRight())
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())
            if index.column() == 0:
                painter.drawLine(rect.topLeft(), rect.bottomLeft())
            if index.column() == table.model().columnCount() - 1:
                painter.drawLine(rect.topRight(), rect.bottomRight())
        finally:
            painter.restore()


class ObservationPlanTable(QTableView):
    """QTableView wrapper for the selected/generated observation plan.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget.
    """

    row_selected = pyqtSignal(int)

    #: Compact empty-table widths. These keep the planner workspace usable
    #: before data are present; populated tables are auto-sized from contents.
    _MIN_COLUMN_WIDTHS = (95, 120, 62, 72, 70, 92)

    #: Maximum widths prevent long headers such as ``Solar Phase [deg]`` from
    #: dominating the narrow planner column while still allowing cell contents
    #: to remain readable.
    _MAX_COLUMN_WIDTHS = (140, 165, 82, 92, 82, 115)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("guiPlannerGeneratedPlanTable")
        self.setProperty("visualRole", "dataTable")
        self._hovered_row = -1
        self._model = ObservationPlanTableModel(self)
        self.setModel(self._model)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSortingEnabled(False)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setItemDelegate(_PlanRowHoverDelegate(self))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.verticalHeader().setVisible(True)
        self.selectionModel().selectionChanged.connect(self._emit_selected_row)

        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(45)
        for column in range(self._model.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)

        self._connect_model_resize_signals()
        self.apply_column_widths()

    @property
    def hovered_row(self) -> int:
        """Return the model row currently under the pointer, or ``-1``."""

        return self._hovered_row

    def model(self) -> ObservationPlanTableModel:  # type: ignore[override]
        """Return the strongly typed plan table model."""

        return self._model

    def _connect_model_resize_signals(self) -> None:
        """Connect model mutations to deferred content-aware resizing."""

        self._model.modelReset.connect(self._handle_model_structure_change)
        self._model.rowsInserted.connect(self._handle_model_structure_change)
        self._model.rowsRemoved.connect(self._handle_model_structure_change)
        self._model.layoutChanged.connect(self._handle_model_structure_change)
        self._model.dataChanged.connect(self._schedule_content_resize)

    def _handle_model_structure_change(self, *_) -> None:
        """Clear stale hover state and schedule content-aware resizing."""

        self._set_hovered_row(-1)
        self._schedule_content_resize()

    def _schedule_content_resize(self, *_) -> None:
        """Resize after Qt has completed the current model/view update."""

        QTimer.singleShot(0, self.apply_column_widths)

    def apply_column_widths(self) -> None:
        """Apply compact content-aware column widths.

        The integrated planner has a narrow right-hand workspace. This method
        keeps compact minimum widths while the table is empty and automatically
        grows each populated column to its contents, clamped so one header
        cannot dominate the table.
        """

        header = self.horizontalHeader()
        column_count = self._model.columnCount()
        row_count = self._model.rowCount()

        for column in range(column_count):
            min_width = self._MIN_COLUMN_WIDTHS[column]
            max_width = self._MAX_COLUMN_WIDTHS[column]
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)

            if row_count > 0:
                self.resizeColumnToContents(column)
                content_width = self.columnWidth(column)
                width = max(min_width, min(content_width, max_width))
            else:
                width = min_width

            header.resizeSection(column, width)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Track the row under the pointer without changing selection."""

        row = self.rowAt(event.position().toPoint().y())
        self._set_hovered_row(row)
        super().mouseMoveEvent(event)

    def viewportEvent(self, event: QEvent) -> bool:  # noqa: N802
        """Clear full-row hover when the pointer leaves the viewport."""

        if event.type() == QEvent.Type.Leave:
            self._set_hovered_row(-1)
        return super().viewportEvent(event)

    def _set_hovered_row(self, row: int) -> None:
        """Update hover state and repaint only the old and new rows."""

        normalized = row if 0 <= row < self._model.rowCount() else -1
        if normalized == self._hovered_row:
            return
        previous = self._hovered_row
        self._hovered_row = normalized
        self._update_row(previous)
        self._update_row(normalized)

    def _update_row(self, row: int) -> None:
        """Schedule a viewport repaint for one visible row."""

        if row < 0 or row >= self._model.rowCount():
            return
        top = self.rowViewportPosition(row)
        height = self.rowHeight(row)
        self.viewport().update(QRect(0, top, self.viewport().width(), height))

    def selected_plan_row(self) -> int | None:
        """Return the selected plan row, if any."""

        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        return indexes[0].row()

    def replace_records(self, records: list[ObservationPlanRecord]) -> None:
        """Atomically replace records while preserving stable row selection."""

        selected_row = self.selected_plan_row()
        selected_record = self._model.record_at(selected_row) if selected_row is not None else None
        restored_row: int | None = None
        blocker = QSignalBlocker(self.selectionModel())
        try:
            self._model.replace_records(records, sort_by_time=True)
            restored_row = self._model.row_for_record(selected_record)
            if restored_row is None:
                self.clearSelection()
                self.setCurrentIndex(QModelIndex())
            else:
                index = self._model.index(restored_row, 0)
                self.selectRow(restored_row)
                self.setCurrentIndex(index)
        finally:
            del blocker
        self.viewport().update()
        if selected_record is not None and restored_row is None:
            self.row_selected.emit(-1)

    def clear_plan_selection(self) -> None:
        """Clear plan-table row selection without mutating plan records.

        The standalone selector only transfers a plan row to the Observation
        Info panel when the user presses ``Select Observation``. Generated or
        manually added rows must therefore not leave an implicit active plan
        selection behind.
        """

        self.clearSelection()
        self.setCurrentIndex(QModelIndex())

    def select_record(self, record: ObservationPlanRecord | None) -> None:
        """Select one record by stable identity without emitting a feedback loop."""

        blocker = QSignalBlocker(self.selectionModel())
        try:
            row = self._model.row_for_record(record)
            if row is None:
                self.clearSelection()
                self.setCurrentIndex(QModelIndex())
            else:
                index = self._model.index(row, 0)
                self.selectRow(row)
                self.setCurrentIndex(index)
        finally:
            del blocker
        self.viewport().update()

    def _emit_selected_row(self) -> None:
        """Emit the current row, or -1 when plan selection is cleared."""

        row = self.selected_plan_row()
        self.row_selected.emit(-1 if row is None else row)
