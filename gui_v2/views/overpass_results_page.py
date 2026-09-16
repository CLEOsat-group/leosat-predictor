"""Overpass results table workspace for GUI v2 Task 44D."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabWidget,
    QWidget,
)

from gui_v2.models.prediction_results_table_model import PredictionResultsTableModel
from gui_v2.widgets.prediction_results_view import PredictionResultsView
from gui_v2.presenters.overpass_export_presenter import OverpassExportPresenter
from gui_v2.shell.navigation_model import NavigationNode
from gui_v2.styles.icon_provider import set_themed_icon
from gui_v2.state.overpass_results_state import OverpassResultsState


class OverpassResultsPage(QWidget):
    """Display the latest overpass results in a model-backed workspace."""

    _TIME_COLUMN_WIDTH = 165
    _DEFAULT_COLUMN_WIDTH = 110
    _WIDTH_MAP = {
        "Sat_ID": 120,
        "rise_time_loc": _TIME_COLUMN_WIDTH,
        "max_time_loc": _TIME_COLUMN_WIDTH,
        "set_time_loc": _TIME_COLUMN_WIDTH,
        "rise_time_utc": _TIME_COLUMN_WIDTH,
        "max_time_utc": _TIME_COLUMN_WIDTH,
        "set_time_utc": _TIME_COLUMN_WIDTH,
    }

    def __init__(
        self,
        *,
        page: NavigationNode,
        results_state: OverpassResultsState,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.page = page
        self._results_state = results_state
        self._displayed_table_key: tuple[int, int, tuple[str, ...]] | None = None
        self._export_presenter = OverpassExportPresenter(results_state=results_state, parent=self)
        self.setObjectName("guiV2OverpassResultsPage")

        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setHorizontalSpacing(0)
        root.setVerticalSpacing(12)
        root.addWidget(self._build_summary_card(), 0, 0)
        root.addWidget(self._build_workspace_tabs(), 1, 0)
        root.setRowStretch(0, 0)
        root.setRowStretch(1, 1)
        root.setColumnStretch(0, 1)
        self.refresh()

    def refresh(self) -> None:
        """Refresh the result summary and model-backed table from shared state."""
        summary = self._results_state.latest_summary
        dataframe = self._results_state.latest_results

        if summary is None or dataframe is None or getattr(dataframe, "empty", True):
            if self._results_state.latest_error:
                self.status_label.setText(f"Last overpass run failed: {self._results_state.latest_error}")
            else:
                self.status_label.setText("No overpass results have been generated in GUI v2 yet.")
            self.row_count_label.setText("—")
            self.satellite_count_label.setText("—")
            self.time_range_label.setText("—")
            self._clear_table_if_needed()
            self._refresh_export_state()
            return

        self.status_label.setText(
            "Latest overpass result summary and model-backed table. Use Export CSV to save the current table."
        )
        self.row_count_label.setText(str(summary.row_count))
        self.satellite_count_label.setText("—" if summary.satellite_count is None else str(summary.satellite_count))
        self.time_range_label.setText(summary.time_range)
        self._load_table(dataframe)
        self._refresh_export_state()
        self.tabs.setCurrentWidget(self.results_tab)

    def _refresh_export_state(self) -> None:
        """Render compact CSV export availability and metadata."""
        can_export = self._results_state.can_export()
        self.export_button.setEnabled(can_export)
        if self._results_state.latest_export_error:
            self.export_status_label.setText(f"Export failed: {self._results_state.latest_export_error}")
            return
        if self._results_state.latest_export_path is not None:
            self.export_status_label.setText(f"Last exported CSV: {self._results_state.latest_export_path}")
            return
        if can_export:
            self.export_status_label.setText("CSV export is available for the current overpass result.")
        else:
            self.export_status_label.setText("No exportable overpass result is available yet.")

    def _handle_export_csv(self) -> None:
        """Export the latest overpass result table through the shared service."""
        csv_path = self._export_presenter.export_csv()
        self._refresh_export_state()
        if csv_path is not None:
            self.status_label.setText(f"Exported current overpass results to: {csv_path}")

    def _build_summary_card(self) -> QFrame:
        card = QFrame(self)
        card.setObjectName("guiV2Card")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QGridLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setHorizontalSpacing(12)
        card_layout.setVerticalSpacing(8)

        title = QLabel("Latest Overpass Results", card)
        title.setObjectName("guiV2CardTitle")
        card_layout.addWidget(title, 0, 0, 1, 4)

        self.status_label = QLabel(card)
        self.status_label.setObjectName("guiV2CardBody")
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label, 1, 0, 1, 4)

        self.row_count_label = QLabel(card)
        self.row_count_label.setObjectName("guiV2CardBody")
        self.satellite_count_label = QLabel(card)
        self.satellite_count_label.setObjectName("guiV2CardBody")
        self.time_range_label = QLabel(card)
        self.time_range_label.setObjectName("guiV2CardBody")
        self.time_range_label.setWordWrap(True)

        self.export_button = QPushButton("Export CSV", card)
        self.export_button.setObjectName("guiV2ExportOverpassResultsButton")
        self.export_button.setProperty("buttonRole", "success")
        set_themed_icon(self.export_button, "save", size=16)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._handle_export_csv)

        self.export_status_label = QLabel("No export has been written for the current result.", card)
        self.export_status_label.setObjectName("guiV2CardBody")
        self.export_status_label.setWordWrap(True)

        self._add_row(card_layout, 2, 0, "Rows:", self.row_count_label)
        self._add_row(card_layout, 2, 2, "Satellites:", self.satellite_count_label)
        self._add_row(card_layout, 3, 0, "Time range:", self.time_range_label, 1, 3)
        card_layout.addWidget(self.export_button, 4, 0)
        card_layout.addWidget(self.export_status_label, 4, 1, 1, 3)
        card_layout.setColumnStretch(0, 0)
        card_layout.setColumnStretch(1, 1)
        card_layout.setColumnStretch(2, 0)
        card_layout.setColumnStretch(3, 1)
        return card

    def _build_workspace_tabs(self) -> QTabWidget:
        self.table = PredictionResultsView(self)
        self.table_model = PredictionResultsTableModel(self.table)
        self.table.setModel(self.table_model)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)

        self.results_tab = QWidget(self)
        results_layout = QGridLayout(self.results_tab)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setHorizontalSpacing(0)
        results_layout.setVerticalSpacing(0)
        results_layout.addWidget(self.table, 0, 0)
        results_layout.setRowStretch(0, 1)
        results_layout.setColumnStretch(0, 1)

        self.visibility_tab = QWidget(self)
        visibility_layout = QGridLayout(self.visibility_tab)
        visibility_layout.setContentsMargins(12, 12, 12, 12)
        visibility_layout.setHorizontalSpacing(8)
        visibility_layout.setVerticalSpacing(8)
        self.visibility_placeholder_label = QLabel(
            "Overpass visibility plotting is deferred. The current task displays and exports the model-backed results table.",
            self.visibility_tab,
        )
        self.visibility_placeholder_label.setObjectName("guiV2CardBody")
        self.visibility_placeholder_label.setWordWrap(True)
        self.visibility_placeholder_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        visibility_layout.addWidget(self.visibility_placeholder_label, 0, 0)
        visibility_layout.setRowStretch(1, 1)
        visibility_layout.setColumnStretch(0, 1)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("guiV2OverpassResultsTabs")
        self.tabs.setProperty("visualRole", "workspaceTabs")
        self.tabs.addTab(self.results_tab, "Results Table")
        self.tabs.addTab(self.visibility_tab, "Visibility")
        return self.tabs

    def _load_table(self, dataframe: Any) -> None:
        columns = tuple(str(column) for column in dataframe.columns)
        table_key = (id(dataframe), len(dataframe), columns)
        if table_key == self._displayed_table_key:
            return

        display_columns = list(dataframe.columns)
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        try:
            self.table_model.set_dataframe(dataframe, display_columns)
            self._displayed_table_key = table_key
            self._apply_table_presentation_defaults()
        finally:
            self.table.setSortingEnabled(True)
            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()

    def _clear_table_if_needed(self) -> None:
        if self._displayed_table_key is None and self.table_model.rowCount() == 0:
            return
        self.table.setSortingEnabled(False)
        self.table_model.clear()
        self.table.setSortingEnabled(True)
        self._displayed_table_key = None

    def _apply_table_presentation_defaults(self) -> None:
        header = self.table.horizontalHeader()
        header.setDefaultSectionSize(self._DEFAULT_COLUMN_WIDTH)
        for index, column_name in enumerate(self.table_model.dataframe.columns):
            width = self._WIDTH_MAP.get(str(column_name))
            if width is not None:
                self.table.setColumnWidth(index, width)
        if self.table_model.columnCount() > 0:
            self.table.scrollToTop()

    def _add_row(
        self,
        layout: QGridLayout,
        row: int,
        label_column: int,
        label_text: str,
        value: QLabel,
        row_span: int = 1,
        value_column_span: int = 1,
    ) -> None:
        label = QLabel(label_text, self)
        label.setObjectName("guiV2FieldLabel")
        layout.addWidget(label, row, label_column, row_span, 1)
        layout.addWidget(value, row, label_column + 1, row_span, value_column_span)


__all__ = ["OverpassResultsPage"]
