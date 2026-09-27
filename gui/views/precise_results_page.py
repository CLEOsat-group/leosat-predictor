"""Precise prediction results table and export page for GUI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QShowEvent
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

from gui.models.prediction_results_table_model import PredictionResultsTableModel
from gui.services.prediction_export_service import PredictionExportService
from gui.widgets.prediction_results_view import PredictionResultsView
from gui.presenters.precise_export_presenter import PreciseExportPresenter
from gui.shell.navigation_model import NavigationNode
from gui.styles.icon_provider import set_themed_icon
from gui.state.precise_results_state import PLANNER_HANDOFF_DEFERRED_MESSAGE, PreciseResultsState


class PreciseResultsPage(QWidget):
    """Display the latest precise prediction results in a model-backed workspace."""

    _TIME_COLUMN_WIDTH = 165
    _DEFAULT_COLUMN_WIDTH = 110
    _WIDTH_MAP = {
        "Obs_Time": _TIME_COLUMN_WIDTH,
        "Local_Time": _TIME_COLUMN_WIDTH,
        "UTC_Time": _TIME_COLUMN_WIDTH,
        "Time": _TIME_COLUMN_WIDTH,
        "Sat_ID": 120,
        "SatName": 140,
        "Satellite": 140,
        "Satellite_Name": 150,
        "RA": 105,
        "DEC": 105,
        "Azimuth": 105,
        "Altitude": 105,
        "SatElev": 105,
        "SolarPhaseAngle": 135,
    }

    def __init__(
        self,
        *,
        page: NavigationNode,
        results_state: PreciseResultsState,
        parent: QWidget | None = None,
        export_service: PredictionExportService | None = None,
        planner_handoff_callback: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.page = page
        self._results_state = results_state
        self._planner_handoff_callback = planner_handoff_callback
        self._displayed_table_key: tuple[int, int, tuple[str, ...]] | None = None
        self._export_presenter = PreciseExportPresenter(
            results_state=results_state,
            parent=self,
            export_service=export_service,
        )
        self.setObjectName("guiPreciseResultsPage")

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

    def showEvent(self, event: QShowEvent) -> None:  # type: ignore[override]
        """Refresh result/action state whenever the results page becomes visible.

        This keeps manual navigation to the results page consistent with export
        actions that may have been triggered from the setup page after a run.
        """
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        """Refresh the result summary and model-backed table from shared state."""
        summary = self._results_state.latest_summary
        dataframe = self._results_state.latest_results

        if summary is None or dataframe is None or getattr(dataframe, "empty", True):
            if self._results_state.latest_error:
                self.status_label.setText(f"Last precise run failed: {self._results_state.latest_error}")
            else:
                self.status_label.setText("No precise results have been generated in GUI yet.")
            self.row_count_label.setText("—")
            self.satellite_count_label.setText("—")
            self.time_range_label.setText("—")
            self._clear_table_if_needed()
            self._refresh_action_state()
            return

        self.status_label.setText(
            "Latest precise result summary and model-backed table. Use Export to CSV to save the current table."
        )
        self.row_count_label.setText(str(summary.row_count))
        self.satellite_count_label.setText("—" if summary.satellite_count is None else str(summary.satellite_count))
        self.time_range_label.setText(summary.time_range)
        self._load_table(dataframe)
        self._refresh_action_state()
        self.tabs.setCurrentWidget(self.results_tab)

    def _refresh_action_state(self) -> None:
        """Render compact CSV export and guarded planner-action availability."""
        can_export = self._results_state.can_export()
        self.export_button.setEnabled(can_export)
        if self._results_state.latest_export_error:
            self.export_status_label.setText(f"Export failed: {self._results_state.latest_export_error}")
        elif self._results_state.latest_export_path is not None:
            if self._results_state.latest_export_warning:
                self.export_status_label.setText(
                    f"Last exported CSV: {self._results_state.latest_export_path} "
                    f"({self._results_state.latest_export_warning})"
                )
            else:
                self.export_status_label.setText(f"Last exported CSV: {self._results_state.latest_export_path}")
        elif can_export:
            self.export_status_label.setText("CSV export is available for the current precise result.")
        else:
            self.export_status_label.setText("No exportable precise result is available yet.")

        handoff_available = self._results_state.can_handoff(
            consumer_available=self._planner_handoff_callback is not None
        )
        self.handoff_button.setEnabled(handoff_available)
        if self._results_state.latest_handoff_error:
            self.handoff_status_label.setText(f"Planner handoff failed: {self._results_state.latest_handoff_error}")
        elif self._results_state.latest_handoff_message:
            self.handoff_status_label.setText(self._results_state.latest_handoff_message)
        elif self._results_state.has_results() and self._planner_handoff_callback is None:
            self.handoff_status_label.setText(PLANNER_HANDOFF_DEFERRED_MESSAGE)
        elif self._results_state.has_results():
            self.handoff_status_label.setText("Planner handoff is available for the current precise result.")
        else:
            self.handoff_status_label.setText("No precise result is available for planner handoff yet.")

    def _handle_export_csv(self) -> None:
        """Export the latest precise result table through the shared service."""
        csv_path = self._export_presenter.export_csv()
        self._refresh_action_state()
        if csv_path is not None:
            self.status_label.setText(f"Exported current precise results to: {csv_path}")

    def _handle_handoff_requested(self) -> None:
        """Send completed precise results to the GUI planner consumer."""
        if self._planner_handoff_callback is None:
            self._results_state.set_handoff_message(PLANNER_HANDOFF_DEFERRED_MESSAGE)
            self._refresh_action_state()
            return
        self._planner_handoff_callback()
        self._refresh_action_state()

    def _build_summary_card(self) -> QFrame:
        card = QFrame(self)
        card.setObjectName("guiCard")
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card_layout = QGridLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setHorizontalSpacing(12)
        card_layout.setVerticalSpacing(8)

        title = QLabel("Latest Precise Results", card)
        title.setObjectName("guiCardTitle")
        card_layout.addWidget(title, 0, 0, 1, 4)

        self.status_label = QLabel(card)
        self.status_label.setObjectName("guiCardBody")
        self.status_label.setWordWrap(True)
        card_layout.addWidget(self.status_label, 1, 0, 1, 4)

        self.row_count_label = QLabel(card)
        self.row_count_label.setObjectName("guiCardBody")
        self.satellite_count_label = QLabel(card)
        self.satellite_count_label.setObjectName("guiCardBody")
        self.time_range_label = QLabel(card)
        self.time_range_label.setObjectName("guiCardBody")
        self.time_range_label.setWordWrap(True)

        self.export_button = QPushButton("Export to CSV", card)
        self.export_button.setObjectName("guiExportPreciseResultsButton")
        self.export_button.setProperty("buttonRole", "success")
        set_themed_icon(self.export_button, "save", size=16)
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._handle_export_csv)

        self.handoff_button = QPushButton("Send to Planner", card)
        self.handoff_button.setObjectName("guiHandoffPreciseResultsButton")
        self.handoff_button.setProperty("buttonRole", "secondary")
        set_themed_icon(self.handoff_button, "send", size=16)
        self.handoff_button.setEnabled(False)
        self.handoff_button.setToolTip("Send the current precise result table directly to the Observation Planner.")
        self.handoff_button.clicked.connect(self._handle_handoff_requested)

        self.export_status_label = QLabel("No export has been written for the current precise result.", card)
        self.export_status_label.setObjectName("guiCardBody")
        self.export_status_label.setWordWrap(True)
        self.handoff_status_label = QLabel("No precise result is available for planner handoff yet.", card)
        self.handoff_status_label.setObjectName("guiCardBody")
        self.handoff_status_label.setWordWrap(True)

        self._add_row(card_layout, 2, 0, "Rows:", self.row_count_label)
        self._add_row(card_layout, 2, 2, "Satellites:", self.satellite_count_label)
        self._add_row(card_layout, 3, 0, "Time range:", self.time_range_label, 1, 3)
        card_layout.addWidget(self.export_button, 4, 0)
        card_layout.addWidget(self.export_status_label, 4, 1, 1, 3)
        card_layout.addWidget(self.handoff_button, 5, 0)
        card_layout.addWidget(self.handoff_status_label, 5, 1, 1, 3)
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
            "Precise plotting is not enabled in this workspace. Use the Results Table tab to inspect and export the current precise prediction output.",
            self.visibility_tab,
        )
        self.visibility_placeholder_label.setObjectName("guiCardBody")
        self.visibility_placeholder_label.setWordWrap(True)
        self.visibility_placeholder_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        visibility_layout.addWidget(self.visibility_placeholder_label, 0, 0)
        visibility_layout.setRowStretch(1, 1)
        visibility_layout.setColumnStretch(0, 1)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("guiPreciseResultsTabs")
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
        label.setObjectName("guiFieldLabel")
        layout.addWidget(label, row, label_column, row_span, 1)
        layout.addWidget(value, row, label_column + 1, row_span, value_column_span)


__all__ = ["PreciseResultsPage"]
