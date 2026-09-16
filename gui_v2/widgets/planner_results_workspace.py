"""GUI-v2 Observation Planner results workspace adapters.

This module owns the GUI-v2 results workspace composition.  It still reuses
small donor widgets where they remain appropriate, but Observation Info is now
implemented as a native GUI-v2 card so it can present the selected observation,
copy fields, TLE copy support, and start-time display without importing the
legacy v1 info panel.
"""

from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QLabel,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import pandas as pd
import pyqtgraph as pg

from gui_v2.models.observation_plan_table_model import (
    COORD_FORMAT_COLON,
    ObservationPlanRecord,
    format_coordinate_value,
    normalize_coordinate_format,
)
from gui_v2.plots.observation_visibility_plot import ObservationVisibilityPlot
from gui_v2.widgets.observation_plan_actions import ObservationPlanActions
from gui_v2.widgets.observation_plan_table import ObservationPlanTable
from gui_v2.widgets.planner_visibility_table import PlannerVisibilityTable



class V2PlannerVisibilityPlot(ObservationVisibilityPlot):
    """GUI-v2 planner visibility plot using the shared scientific palette."""

    def _create_plot(self) -> pg.PlotWidget:
        """Create the shared theme-aware visibility plot."""

        return super()._create_plot()


class PlannerResultCard(QFrame):
    """Styled GUI-v2 result card with an optional title and body."""

    def __init__(
        self,
        *,
        title: str,
        body: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("guiV2Card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 12, 14, 12)
        self.layout.setSpacing(8)

        title_label = QLabel(title, self)
        title_label.setObjectName("guiV2CardTitle")
        title_label.setWordWrap(True)
        self.layout.addWidget(title_label)

        if body:
            body_label = QLabel(body, self)
            body_label.setObjectName("guiV2CardBody")
            body_label.setWordWrap(True)
            self.layout.addWidget(body_label)


class PlannerPlotWorkspace(PlannerResultCard):
    """Top-row planner workspace with tabbed visibility plot and data table.

    The plot remains the primary surface, but the same filtered visibility view
    is also exposed as a full-functionality data table on a second tab so the
    plot and table can be compared without leaving the Results page.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            title="Visibility",
            parent=parent,
        )
        self.setObjectName("guiV2PlannerPlotWorkspace")
        self.setMinimumHeight(240)
        self.setMaximumHeight(460)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("guiV2PlannerVisibilityTabs")

        self.visibility_plot = V2PlannerVisibilityPlot(self.tabs)
        self.visibility_plot.setObjectName("guiV2PlannerVisibilityPlot")
        self.visibility_plot.setMinimumHeight(160)
        self.tabs.addTab(self.visibility_plot, "Plot")

        self.visibility_table = PlannerVisibilityTable(self.tabs)
        self.visibility_table.setObjectName("guiV2PlannerResultsVisibilityTable")
        self.visibility_table.setMinimumHeight(160)
        self.tabs.addTab(self.visibility_table, "Table")

        self.layout.addWidget(self.tabs, 1)

    def set_visibility_data(self, dataframe: object, color_map: object | None = None) -> None:
        """Request asynchronous display of visibility rows."""

        colors = dict(color_map) if isinstance(color_map, dict) else {}
        self.visibility_plot.set_dataframe(dataframe, satellite_colors=colors)

    def cancel_visibility_render(self, message: str = "Visibility plot rendering paused.") -> None:
        """Cancel current plot work when the Results page is hidden."""

        self.visibility_plot.cancel_render(message)

    def update_selected_highlight(self, row: int) -> None:
        """Highlight the selected visibility row in the plot."""
        self.visibility_plot.update_selected_highlight(row)

    def replace_manual_highlights(self, records: Iterable[ObservationPlanRecord]) -> None:
        """Replace manual-row highlights in the plot."""
        self.visibility_plot.replace_manual_highlights(records)

    def update_generated_highlights(self, records: Iterable[ObservationPlanRecord]) -> None:
        """Replace generated-plan highlights in the plot."""
        self.visibility_plot.update_generated_highlights(records)

    def update_plan_selection_highlight(self, record: ObservationPlanRecord | None) -> None:
        """Highlight the currently selected plan row."""
        self.visibility_plot.update_plan_selection_highlight(record)

    def clear(self) -> None:
        """Clear the embedded plot."""
        self.visibility_plot.clear()

    def release_runtime_resources(self) -> None:
        """Release plot resources before shutdown."""
        self.visibility_plot.release_runtime_resources()


class PlannerObservationInfoWorkspace(PlannerResultCard):
    """GUI-v2 Observation Info card with copy controls and start time."""

    exposureTimeChanged = pyqtSignal(int)

    _COPY_FIELD_WIDTH = 108
    _COPY_BUTTON_WIDTH = 126
    _DETAIL_VALUE_WIDTH = 130

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(title="Observation Info", parent=parent)
        self.setObjectName("guiV2PlannerObservationInfoWorkspace")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(560)
        self.setMaximumWidth(640)

        self._coordinate_format = COORD_FORMAT_COLON
        self._current_observation: dict[str, object] | None = None
        self._tle_clipboard_text = ""
        self._exposure_time_seconds = 5

        self._build_content()

    def _build_content(self) -> None:
        """Build the native observation-info layout without overlap."""
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        self.layout.addLayout(body, 1)

        content_grid = QGridLayout()
        content_grid.setContentsMargins(0, 0, 0, 0)
        content_grid.setHorizontalSpacing(12)
        content_grid.setVerticalSpacing(8)
        body.addLayout(content_grid)

        details_frame = QFrame(self)
        details_frame.setObjectName("guiV2ObservationDetailsFrame")
        details_frame.setFrameShape(QFrame.Shape.StyledPanel)
        details_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(10, 8, 10, 8)
        details_layout.setSpacing(6)

        # details_title = QLabel("Observation Details", details_frame)
        # details_title.setObjectName("guiV2ObservationInfoSectionTitle")
        # details_layout.addWidget(details_title, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        details = QGridLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setHorizontalSpacing(10)
        details.setVerticalSpacing(4)
        details_layout.addLayout(details)

        self.satellite_value = self._detail_value_label()
        self.date_value = self._detail_value_label()
        self.elevation_value = self._detail_value_label()
        self.solar_phase_value = self._detail_value_label()

        self._add_detail_row(details, 0, "Satellite", self.satellite_value)
        self._add_detail_row(details, 1, "Date UT", self.date_value)
        self._add_detail_row(details, 2, "Elev. [deg]", self.elevation_value)
        self._add_detail_row(details, 3, "Solar phase [deg]", self.solar_phase_value)
        details.setColumnStretch(0, 0)
        details.setColumnStretch(1, 1)

        copy_widget = QWidget(self)
        copy_widget.setObjectName("guiV2ObservationCopyBlock")
        copy_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        copy_grid = QGridLayout(copy_widget)
        copy_grid.setContentsMargins(0, 0, 0, 0)
        copy_grid.setHorizontalSpacing(6)
        copy_grid.setVerticalSpacing(6)

        self.satellite_edit_value = self._copy_line_edit()
        self.ra_edit_value = self._copy_line_edit()
        self.dec_edit_value = self._copy_line_edit()

        self.copy_satellite_button = self._copy_button("Copy Satellite")
        self.copy_ra_button = self._copy_button("Copy RA")
        self.copy_dec_button = self._copy_button("Copy Dec")

        self._add_copy_row(copy_grid, 0, "Satellite", self.satellite_edit_value, self.copy_satellite_button)
        self._add_copy_row(copy_grid, 1, "RA [hr]", self.ra_edit_value, self.copy_ra_button)
        self._add_copy_row(copy_grid, 2, "Dec [deg]", self.dec_edit_value, self.copy_dec_button)
        copy_grid.setColumnStretch(0, 0)
        copy_grid.setColumnStretch(1, 0)
        copy_grid.setColumnStretch(2, 0)

        exposure_widget = QWidget(self)
        exposure_widget.setObjectName("guiV2ObservationExposureBlock")
        exposure_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        exposure_layout = QHBoxLayout(exposure_widget)
        exposure_layout.setContentsMargins(0, 0, 0, 0)
        exposure_layout.setSpacing(6)
        exposure_label = QLabel("Exposure [sec]:", exposure_widget)
        exposure_label.setObjectName("guiV2ObservationInfoName")
        self.exposure_time_edit = QLineEdit(exposure_widget)
        self.exposure_time_edit.setObjectName("guiV2ObservationExposureInput")
        self.exposure_time_edit.setValidator(QIntValidator(0, 3600, self.exposure_time_edit))
        self.exposure_time_edit.setFixedWidth(58)
        self.exposure_time_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.exposure_time_edit.setText(str(self._exposure_time_seconds))
        exposure_layout.addWidget(exposure_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        exposure_layout.addWidget(self.exposure_time_edit, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        start_block = QWidget(self)
        start_block.setObjectName("guiV2ObservationStartBlock")
        start_block.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        start_layout = QVBoxLayout(start_block)
        start_layout.setContentsMargins(0, 2, 0, 0)
        start_layout.setSpacing(2)
        start_label = QLabel("Start Obs @ UTC:", start_block)
        start_label.setObjectName("guiV2ObservationStartLabel")
        self.start_obs_value = QLabel("", start_block)
        self.start_obs_value.setObjectName("observationStartTime")
        self.start_obs_value.setMinimumWidth(180)
        self.start_obs_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.start_obs_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        start_layout.addWidget(start_label, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        start_layout.addWidget(self.start_obs_value, alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        content_grid.addWidget(details_frame, 0, 0, 2, 2, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        content_grid.addWidget(copy_widget, 2, 1, 1, 2, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        content_grid.addWidget(start_block, 3, 0, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        content_grid.addWidget(exposure_widget, 3, 1, 1, 2, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        content_grid.setColumnStretch(0, 1)
        content_grid.setColumnStretch(1, 0)

        action_widget = QWidget(self)
        action_widget.setObjectName("guiV2ObservationActionBlock")
        action_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)

        action_row = QHBoxLayout(action_widget)
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.copy_tle_button = self._copy_button("Copy TLE")
        self.copy_tle_button.setEnabled(False)
        self.clear_button = QPushButton("Clear Observation", self)
        self.clear_button.setProperty("buttonRole", "danger")
        for button in (self.copy_tle_button, self.clear_button):
            button.setFixedWidth(self._COPY_BUTTON_WIDTH)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            action_row.addWidget(button)

        content_grid.addWidget(
            action_widget,
            4,
            1,
            1,
            2,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )
        body.addStretch(0)

        self.copy_satellite_button.clicked.connect(lambda: self._copy_text(self.satellite_edit_value.text()))
        self.copy_ra_button.clicked.connect(lambda: self._copy_text(self.ra_edit_value.text()))
        self.copy_dec_button.clicked.connect(lambda: self._copy_text(self.dec_edit_value.text()))
        self.copy_tle_button.clicked.connect(lambda: self._copy_text(self._tle_clipboard_text))
        self.clear_button.clicked.connect(self.clear)
        self.exposure_time_edit.textChanged.connect(self._handle_exposure_time_edited)

    def _detail_value_label(self) -> QLabel:
        """Create a selectable detail-value label."""
        label = QLabel("", self)
        label.setObjectName("guiV2ObservationInfoValue")
        label.setMinimumWidth(self._DETAIL_VALUE_WIDTH)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setWordWrap(False)
        return label

    def _copy_line_edit(self) -> QLineEdit:
        """Create a compact read-only copy field."""
        line_edit = QLineEdit(self)
        line_edit.setReadOnly(True)
        line_edit.setFixedWidth(self._COPY_FIELD_WIDTH)
        line_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return line_edit

    def _copy_button(self, text: str) -> QPushButton:
        """Create a fixed-width secondary copy/action button."""
        button = QPushButton(text, self)
        button.setProperty("buttonRole", "secondary")
        button.setFixedWidth(self._COPY_BUTTON_WIDTH)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return button

    def _add_detail_row(self, layout: QGridLayout, row: int, label_text: str, value_label: QLabel) -> None:
        """Add one left-side observation-detail row."""
        label = QLabel(f"{label_text}:", self)
        label.setObjectName("guiV2ObservationInfoName")
        label.setFixedWidth(96)
        layout.addWidget(label, row, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(value_label, row, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    def _add_copy_row(self, layout: QGridLayout, row: int, label_text: str, field: QLineEdit, button: QPushButton) -> None:
        """Add one right-side copy row."""
        label = QLabel(f"{label_text}:", self)
        label.setObjectName("guiV2ObservationInfoName")
        label.setFixedWidth(58)
        layout.addWidget(label, row, 0, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(field, row, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(button, row, 2, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def set_coordinate_format(self, coordinate_format: str | None) -> None:
        """Set the RA/DEC display and copy format."""
        normalized = normalize_coordinate_format(coordinate_format)
        if normalized == self._coordinate_format:
            return
        self._coordinate_format = normalized
        self._render_current_observation(clear_tle=False)

    def set_observation(self, record: ObservationPlanRecord | dict[str, object] | None, tle_clipboard_text: str = "") -> None:
        """Display the selected observation and its TLE clipboard text."""
        if record is None:
            self.clear()
            return
        if isinstance(record, ObservationPlanRecord):
            self._current_observation = {
                "satellite": record.satellite,
                "date_ut": record.date_ut,
                "ra": record.ra,
                "dec": record.dec,
                "elev": record.elev,
                "solar_phase_angle": record.solar_phase_angle,
            }
        else:
            self._current_observation = {
                "satellite": record.get("satellite", ""),
                "date_ut": record.get("date_ut", ""),
                "ra": record.get("ra", ""),
                "dec": record.get("dec", ""),
                "elev": record.get("elev", ""),
                "solar_phase_angle": record.get("solar_phase_angle", ""),
            }
        self._render_current_observation(clear_tle=True)
        self.set_tle_clipboard_text(tle_clipboard_text)

    def _render_current_observation(self, *, clear_tle: bool) -> None:
        """Render the cached raw observation with the active coordinate format."""
        if self._current_observation is None:
            return
        satellite = self._current_observation.get("satellite", "")
        date_ut = self._current_observation.get("date_ut", "")
        ra = self._current_observation.get("ra", "")
        dec = self._current_observation.get("dec", "")
        elev = self._current_observation.get("elev", "")
        solar_phase = self._current_observation.get("solar_phase_angle", "")

        sat_text = self._format_text(satellite)
        clean_satellite = "-".join(sat_text.split("-")[:-2]) if "-ID" in sat_text else sat_text

        self.satellite_value.setText(sat_text)
        self.date_value.setText(self._format_datetime(date_ut))
        self.elevation_value.setText(self._format_float(elev))
        self.solar_phase_value.setText(self._format_float(solar_phase))
        self.satellite_edit_value.setText(clean_satellite)
        self.ra_edit_value.setText(format_coordinate_value(ra, self._coordinate_format))
        self.dec_edit_value.setText(format_coordinate_value(dec, self._coordinate_format))
        self.update_start_obs_time()
        if clear_tle:
            self.set_tle_clipboard_text("")

    def set_tle_clipboard_text(self, text: str | None) -> None:
        """Set three-line TLE clipboard text and update Copy TLE enablement."""
        self._tle_clipboard_text = str(text or "")
        self.copy_tle_button.setEnabled(bool(self._tle_clipboard_text.strip()))

    def set_exposure_time_seconds(self, seconds: int | float) -> None:
        """Set the exposure time used to compute start-observation time."""
        value = self._normalize_exposure_time(seconds)
        self._exposure_time_seconds = value
        previous = self.exposure_time_edit.blockSignals(True)
        try:
            self.exposure_time_edit.setText(str(value))
        finally:
            self.exposure_time_edit.blockSignals(previous)
        self.update_start_obs_time()

    def _handle_exposure_time_edited(self, _text: str) -> None:
        """Update start-observation time and publish user exposure edits."""
        value = self._normalize_exposure_time(self.exposure_time_edit.text())
        if value == self._exposure_time_seconds:
            self.update_start_obs_time()
            return
        self._exposure_time_seconds = value
        self.update_start_obs_time()
        self.exposureTimeChanged.emit(value)

    @staticmethod
    def _normalize_exposure_time(seconds: int | float | str) -> int:
        """Return a bounded integer exposure time in seconds."""
        try:
            value = int(round(float(str(seconds).strip())))
        except (TypeError, ValueError):
            value = 0
        return max(0, min(3600, value))

    def update_start_obs_time(self) -> None:
        """Update the start-observation time from selected UTC time and exposure."""
        if self._current_observation is None:
            self.start_obs_value.clear()
            return
        date_value = self._current_observation.get("date_ut", "")
        try:
            timestamp = pd.to_datetime(date_value)
            if pd.isna(timestamp):
                self.start_obs_value.clear()
                return
            start_time = timestamp - pd.to_timedelta(self._exposure_time_seconds / 2, unit="s")
            self.start_obs_value.setText(start_time.strftime("%H:%M:%S"))
        except Exception:
            self.start_obs_value.setText("Invalid observation time")

    def clear(self) -> None:
        """Clear displayed observation information."""
        for widget in (
            self.satellite_value,
            self.date_value,
            self.elevation_value,
            self.solar_phase_value,
            self.start_obs_value,
            self.satellite_edit_value,
            self.ra_edit_value,
            self.dec_edit_value,
        ):
            widget.clear()
        self._current_observation = None
        self.set_tle_clipboard_text("")

    @staticmethod
    def _format_text(value: object) -> str:
        """Return display text for a possibly missing value."""
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
        return str(value)

    @classmethod
    def _format_datetime(cls, value: object) -> str:
        """Return a compact UTC timestamp display string."""
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    @staticmethod
    def _format_float(value: object) -> str:
        """Return a compact decimal display string for numeric fields."""
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass
        try:
            return f"{float(value):.2f}"
        except Exception:
            return str(value)

    @staticmethod
    def _copy_text(text: str) -> None:
        """Copy non-empty text to the QApplication clipboard."""
        if text:
            QApplication.clipboard().setText(text)


class PlannerGeneratedPlanWorkspace(PlannerResultCard):
    """Lower-right generated-plan table and action workspace."""

    selectRequested = pyqtSignal()
    removeRequested = pyqtSignal()
    clearRequested = pyqtSignal()
    exportRequested = pyqtSignal()
    rowSelected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            title="Observation Plan",
            parent=parent,
        )
        self.setObjectName("guiV2PlannerGeneratedPlanWorkspace")
        self.setMinimumHeight(240)

        self.plan_table = ObservationPlanTable(self)
        self.plan_table.setObjectName("guiV2PlannerGeneratedPlanTable")
        self.plan_table.setMinimumHeight(180)
        self.layout.addWidget(self.plan_table, 1)

        self.actions = ObservationPlanActions(self)
        self.actions.setObjectName("guiV2PlannerGeneratedPlanActions")
        self.layout.addWidget(self.actions)

        self.plan_table.row_selected.connect(self.rowSelected.emit)
        self.actions.select_requested.connect(self.selectRequested.emit)
        self.actions.remove_requested.connect(self.removeRequested.emit)
        self.actions.clear_requested.connect(self.clearRequested.emit)
        self.actions.export_requested.connect(self.exportRequested.emit)
        self.set_actions_enabled(False)
        self.set_export_enabled(False)

    def set_records(self, records: Iterable[ObservationPlanRecord]) -> None:
        """Replace generated-plan rows with controller-owned records."""
        records = list(records)
        self.plan_table.replace_records(records)
        self.set_actions_enabled(self.plan_table.model().rowCount() > 0)

    def clear(self) -> None:
        """Clear the generated-plan table."""
        self.plan_table.model().clear()
        self.set_actions_enabled(False)
        self.set_export_enabled(False)

    def selected_record(self) -> ObservationPlanRecord | None:
        """Return the selected generated-plan record, if any."""
        row = self.plan_table.selected_plan_row()
        if row is None:
            return None
        return self.plan_table.model().record_at(row)

    def select_record(self, record: ObservationPlanRecord | None) -> None:
        """Synchronize visible table selection to a controller-owned record."""

        self.plan_table.select_record(record)

    def set_coordinate_format(self, coordinate_format: str | None) -> None:
        """Forward coordinate-format changes to the generated-plan model."""
        self.plan_table.model().set_coordinate_format(coordinate_format)

    def set_actions_enabled(self, enabled: bool) -> None:
        """Enable or disable plan actions based on real plan availability."""
        for button in (
            self.actions.select_button,
            self.actions.remove_button,
            self.actions.clear_button,
        ):
            button.setEnabled(bool(enabled))
        self.set_export_enabled(enabled)

    def set_export_enabled(self, enabled: bool) -> None:
        """Enable or disable the Results-page export action."""
        self.actions.export_button.setEnabled(bool(enabled))
        self.actions.export_button.setToolTip(
            "Export the current observation plan."
            if enabled
            else "Generate or manually add observations before exporting."
        )


class PlannerResultsWorkspace(QWidget):
    """Concrete GUI-v2 2x2 planner results workspace."""

    selectObservationRequested = pyqtSignal()
    removeObservationRequested = pyqtSignal()
    clearPlanRequested = pyqtSignal()
    exportPlanRequested = pyqtSignal()
    planRowSelected = pyqtSignal(int)
    plotPointSelected = pyqtSignal(int)
    exposureTimeChanged = pyqtSignal(int)
    plotRenderStarted = pyqtSignal(str)
    plotRenderProgress = pyqtSignal(str)
    plotRenderSucceeded = pyqtSignal(str)
    plotRenderCanceled = pyqtSignal(str)
    plotRenderFailed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiV2PlannerResultsWorkspace")

        self.plot_workspace = PlannerPlotWorkspace(self)
        self.observation_info_workspace = PlannerObservationInfoWorkspace(self)
        self.generated_plan_workspace = PlannerGeneratedPlanWorkspace(self)
        self._current_plan_records: list[ObservationPlanRecord] = []
        self._selected_visibility_row = -1
        self._selected_plan_record: ObservationPlanRecord | None = None

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.addWidget(self.plot_workspace, 0, 0, 1, 2)
        grid.addWidget(self.observation_info_workspace, 1, 0)
        grid.addWidget(self.generated_plan_workspace, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 4)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 2)

        self.generated_plan_workspace.selectRequested.connect(self.selectObservationRequested.emit)
        self.generated_plan_workspace.removeRequested.connect(self.removeObservationRequested.emit)
        self.generated_plan_workspace.clearRequested.connect(self.clearPlanRequested.emit)
        self.generated_plan_workspace.exportRequested.connect(self.exportPlanRequested.emit)
        self.generated_plan_workspace.rowSelected.connect(self.planRowSelected.emit)
        plot = self.plot_workspace.visibility_plot
        plot.point_selected.connect(self.plotPointSelected.emit)
        plot.render_started.connect(self.plotRenderStarted.emit)
        plot.render_progress.connect(self.plotRenderProgress.emit)
        plot.render_succeeded.connect(self._handle_plot_render_succeeded)
        plot.render_canceled.connect(self.plotRenderCanceled.emit)
        plot.render_failed.connect(self.plotRenderFailed.emit)
        self.observation_info_workspace.exposureTimeChanged.connect(self.exposureTimeChanged.emit)

    def set_visibility_data(self, dataframe: object, color_map: object | None = None) -> None:
        """Refresh the plot and replay current plan highlights.

        Results pages are constructed while hidden and large visibility plots are
        rendered lazily on first show.  A plan can therefore be generated before
        the Results page has rendered its first visibility plot.  Rebuilding the
        plot clears highlight layers, so the current plan records must be
        replayed after each data refresh.
        """
        self.plot_workspace.set_visibility_data(dataframe, color_map)

    def set_plan_records(self, records: Iterable[ObservationPlanRecord]) -> None:
        """Refresh generated/manual plan rows and plot highlights."""
        self._current_plan_records = list(records)
        self.generated_plan_workspace.set_records(self._current_plan_records)
        self._refresh_plot_highlights(self._current_plan_records)

    def selected_record(self) -> ObservationPlanRecord | None:
        """Return the selected generated-plan record, if any."""
        return self.generated_plan_workspace.selected_record()

    def set_coordinate_format(self, coordinate_format: str | None) -> None:
        """Forward coordinate-format changes to all result surfaces."""
        self.generated_plan_workspace.set_coordinate_format(coordinate_format)
        self.observation_info_workspace.set_coordinate_format(coordinate_format)

    def set_export_enabled(self, enabled: bool) -> None:
        """Enable or disable the generated-plan export action."""
        self.generated_plan_workspace.set_export_enabled(enabled)

    def set_observation(self, record: ObservationPlanRecord | None, tle_clipboard_text: str = "") -> None:
        """Display the selected observation in the Observation Info card."""
        self.observation_info_workspace.set_observation(record, tle_clipboard_text)

    def set_exposure_time_seconds(self, seconds: int | float) -> None:
        """Forward exposure-time changes to Observation Info."""
        self.observation_info_workspace.set_exposure_time_seconds(seconds)

    def update_visibility_selection(self, row: int) -> None:
        """Synchronize plot selection to the current visibility row."""

        self._selected_visibility_row = int(row)
        self.plot_workspace.update_selected_highlight(row)

    def update_plan_selection(self, record: ObservationPlanRecord | None) -> None:
        """Synchronize table and plot plan-selection state."""

        self._selected_plan_record = record
        self.generated_plan_workspace.select_record(record)
        self.plot_workspace.update_plan_selection_highlight(record)

    def cancel_visibility_render(self, message: str = "Visibility plot rendering paused.") -> None:
        """Cancel current plot work while preserving the latest source payload."""

        self.plot_workspace.cancel_visibility_render(message)

    def is_visibility_rendering(self) -> bool:
        """Return whether plot preparation/rendering is active."""

        return self.plot_workspace.visibility_plot.is_rendering

    def _handle_plot_render_succeeded(self, message: str) -> None:
        """Replay the newest highlight state after scene construction."""

        self._refresh_plot_highlights(self._current_plan_records)
        if self._selected_plan_record is not None:
            self.plot_workspace.update_plan_selection_highlight(self._selected_plan_record)
        elif self._selected_visibility_row >= 0:
            self.plot_workspace.update_selected_highlight(self._selected_visibility_row)
        self.plotRenderSucceeded.emit(message)

    def _refresh_plot_highlights(self, records: Iterable[ObservationPlanRecord]) -> None:
        """Refresh generated and manual highlights from controller-owned plan records."""
        records = list(records)
        manual_records = [record for record in records if record.source == "manual"]
        generated_records = [record for record in records if record.source != "manual"]
        self.plot_workspace.replace_manual_highlights(manual_records)
        self.plot_workspace.update_generated_highlights(generated_records)

    def clear(self) -> None:
        """Clear all result workspace surfaces and cached selection state."""

        self._current_plan_records = []
        self._selected_visibility_row = -1
        self._selected_plan_record = None
        self.plot_workspace.clear()
        self.plot_workspace.visibility_table.set_dataframe(pd.DataFrame())
        self.observation_info_workspace.clear()
        self.generated_plan_workspace.clear()

    def release_runtime_resources(self) -> None:
        """Release large plot/table state before shutdown."""

        self._current_plan_records = []
        self._selected_visibility_row = -1
        self._selected_plan_record = None
        self.plot_workspace.release_runtime_resources()
        self.plot_workspace.visibility_table.set_dataframe(pd.DataFrame())
        self.generated_plan_workspace.clear()


__all__ = (
    "PlannerGeneratedPlanWorkspace",
    "PlannerObservationInfoWorkspace",
    "PlannerPlotWorkspace",
    "PlannerResultCard",
    "PlannerResultsWorkspace",
)
