"""GUI-v2 Observation Planner diagnostics workspace.

The widgets in this module port the GUI-v1 planner diagnostics behavior into
small GUI-v2 adapters.  They render only backend-provided diagnostics objects;
no planner metrics or scientific decisions are computed in the GUI layer.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

import numpy as np
from PyQt6 import QtCore
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

import pyqtgraph as pg

from gui_v2.styles import repolish, active_theme_name, active_theme_palette
from gui_v2.presenters.planner_diagnostics_presenter import (
    DiagnosticsCardPresentation,
    present_planner_diagnostics_overview,
)
from gui_v2.state.planner_state import PlannerRuntimeSnapshot


PLOT_ROLES: dict[str, dict[str, object]] = {
    "input": {"label": "Input candidates", "symbol": "o", "symbol_size": 4, "pen_width": 1},
    "reduced": {"label": "Reduced candidates", "symbol": "t", "symbol_size": 5, "pen_width": 1},
    "selected": {"label": "Selected observations", "symbol": "x", "symbol_size": 9, "pen_width": 2},
    "repair_added": {"label": "Repair-added observations", "symbol": "star", "symbol_size": 12, "pen_width": 2},
    "spacing_minimum": {"label": "Minimum spacing", "pen_width": 2},
}


class DiagnosticsTableModel(QAbstractTableModel):
    """Read-only model for sectioned planner diagnostics rows."""

    HEADERS = ("Section", "Metric", "Value")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, str, str]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt API.
        """Return the number of diagnostics rows."""
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt API.
        """Return the fixed diagnostics column count."""
        return 0 if parent.isValid() else len(self.HEADERS)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> object:  # noqa: D401
        """Return display data for a diagnostics cell."""
        if not index.isValid() or role not in (Qt.ItemDataRole.DisplayRole, int(Qt.ItemDataRole.DisplayRole)):
            return None
        try:
            return self._rows[index.row()][index.column()]
        except IndexError:
            return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = int(Qt.ItemDataRole.DisplayRole),
    ) -> object:  # noqa: N802 - Qt API.
        """Return diagnostics table headers."""
        if orientation == Qt.Orientation.Horizontal and role in (Qt.ItemDataRole.DisplayRole, int(Qt.ItemDataRole.DisplayRole)):
            try:
                return self.HEADERS[section]
            except IndexError:
                return None
        return None

    def set_rows(self, rows: Iterable[tuple[str, str, str]]) -> None:
        """Replace all rows in one model reset."""
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def clear(self) -> None:
        """Clear all diagnostics rows."""
        self.set_rows(())


class UtcDateAxisItem(pg.AxisItem):
    """UTC fallback date axis for pyqtgraph versions without ``utcOffset``."""

    def tickStrings(self, values, scale, spacing):  # noqa: N802 - PyQtGraph API.
        """Return UTC tick labels for epoch-second positions."""
        labels: list[str] = []
        for value in values:
            try:
                timestamp = datetime.fromtimestamp(float(value), tz=timezone.utc)
            except (OSError, OverflowError, ValueError):
                labels.append("")
                continue
            if spacing >= 24 * 3600:
                labels.append(timestamp.strftime("%Y-%m-%d"))
            elif spacing >= 3600:
                labels.append(timestamp.strftime("%m-%d %H:%M"))
            else:
                labels.append(timestamp.strftime("%H:%M:%S"))
        return labels


def _make_utc_date_axis() -> pg.AxisItem:
    """Return a UTC-aware axis for epoch-second time series."""
    try:
        return pg.DateAxisItem(orientation="bottom", utcOffset=0)
    except TypeError:
        return UtcDateAxisItem(orientation="bottom")


def _role_pen(role: str, *, width: int | None = None, style=None):
    """Return a theme-aware pen for a diagnostics plot role."""
    spec = PLOT_ROLES[role]
    return pg.mkPen(
        active_theme_palette().series_color(role),
        width=int(width if width is not None else spec.get("pen_width", 1)),
        style=style,
    )


def _role_brush(role: str):
    """Return a theme-aware translucent brush for a diagnostics plot role."""
    color = QColor(active_theme_palette().series_color(role))
    color.setAlpha(170 if role != "input" else 95)
    return pg.mkBrush(color)


def _as_finite_array(values: object) -> np.ndarray:
    """Return values as a finite float array without mutating the source."""
    source = [] if values is None else values
    array = np.asarray(source, dtype=float)
    return array[np.isfinite(array)]


def _paired_arrays(x_values: object, y_values: object) -> tuple[np.ndarray, np.ndarray]:
    """Return same-length finite x/y arrays for scatter plotting."""
    x = np.asarray([] if x_values is None else x_values, dtype=float)
    y = np.asarray([] if y_values is None else y_values, dtype=float)
    if x.size == 0 or y.size == 0 or x.size != y.size:
        return np.array([], dtype=float), np.array([], dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


def _format_value(value: object) -> str:
    """Format diagnostics values for compact display."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, (list, tuple)):
        if len(value) > 8:
            return f"{list(value[:8])} … ({len(value)} items)"
        return str(list(value))
    if isinstance(value, Mapping):
        return "; ".join(f"{key}={_format_value(item)}" for key, item in value.items())
    return str(value)


def _diagnostics_title(diagnostics: object | None) -> str:
    """Return a compact diagnostics title from the backend trust summary."""
    if diagnostics is None:
        return "No planner diagnostics available."
    try:
        summary = diagnostics.resolved_optimization_trust_summary()
    except Exception:
        return str(diagnostics.to_log_message()) if hasattr(diagnostics, "to_log_message") else "Planner diagnostics available."
    if not isinstance(summary, Mapping) or not summary.get("trust_summary_available"):
        return str(diagnostics.to_log_message()) if hasattr(diagnostics, "to_log_message") else "Planner diagnostics available."
    assessment = str(summary.get("trust_assessment") or "trust summary")
    interpretation = str(summary.get("recommended_user_interpretation") or "")
    if len(interpretation) > 180:
        interpretation = interpretation[:177].rstrip() + "..."
    return f"Optimization Trust: {assessment} — {interpretation}" if interpretation else f"Optimization Trust: {assessment}"


def _table_rows_from_diagnostics(diagnostics: object | None) -> list[tuple[str, str, str]]:
    """Flatten ``diagnostics.table_sections()`` into display rows."""
    if diagnostics is None or not hasattr(diagnostics, "table_sections"):
        return []
    rows: list[tuple[str, str, str]] = []
    for section, mapping in diagnostics.table_sections():
        section_text = str(section)
        if not isinstance(mapping, Mapping):
            rows.append((section_text, "value", _format_value(mapping)))
            continue
        for key, value in mapping.items():
            key_text = str(key)
            if key == "selected_rows" and isinstance(value, list):
                rows.append((section_text, key_text, f"{len(value)} selected rows"))
                for item in value[:100]:
                    rows.append((section_text, "selected", _format_value(item)))
                if len(value) > 100:
                    rows.append((section_text, "selected", f"… {len(value) - 100} additional rows omitted from display"))
            elif key == "bin_diagnostics" and isinstance(value, list):
                rows.append((section_text, key_text, f"{len(value)} bins"))
                for item in value:
                    rows.append((section_text, "bin", _format_value(item)))
            else:
                rows.append((section_text, key_text, _format_value(value)))
    return rows


def _safe_mapping(value: object) -> dict[str, object]:
    """Return a dictionary copy if ``value`` is mapping-like."""
    return dict(value) if isinstance(value, Mapping) else {}


class DiagnosticsInfoCard(QFrame):
    """Small GUI-v2 diagnostics card used in overview and details tabs."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiV2DiagnosticsCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("guiV2DiagnosticsCardTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.body_label = QLabel("—", self)
        self.body_label.setObjectName("guiV2DiagnosticsCardBody")
        self.body_label.setWordWrap(True)
        layout.addWidget(self.body_label)

    def set_body(self, text: str) -> None:
        """Set body text, using an em dash for empty values."""
        self.body_label.setText(text or "—")

    def set_presentation(self, presentation: DiagnosticsCardPresentation) -> None:
        """Render a human-readable diagnostics-card presentation."""
        self.title_label.setText(presentation.title)
        self.body_label.setText(presentation.body_text() or "—")
        self.setProperty("diagnosticSeverity", presentation.severity)
        repolish(self)


class V2PlannerDiagnosticsPlots(QWidget):
    """Render backend diagnostics plot series using GUI-v2 theme colors.

    The plot workspace uses sub-tabs so each diagnostic concept has its own
    focused plot and explanatory text.  This keeps the diagnostics readable
    while preserving all backend-provided plot series for detailed inspection.
    """

    PLOT_TAB_SAMPLING = "sampling"
    PLOT_TAB_TIME_METRIC = "time_metric"
    PLOT_TAB_SPACING = "spacing"
    PLOT_TAB_METRIC_DISTRIBUTION = "metric_distribution"
    PLOT_TAB_SLEW_PATH = "slew_path"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiV2PlannerDiagnosticsPlots")
        self._diagnostics: object | None = None
        self._rendered_diagnostics_id: int | None = None
        self._plot_graphics: dict[str, pg.GraphicsLayoutWidget] = {}

        self.plot_tabs = QTabWidget(self)
        self.plot_tabs.setObjectName("guiV2PlannerDiagnosticsPlotTabs")
        self.plot_tabs.setProperty("visualRole", "workspaceTabs")
        self.plot_tabs.addTab(
            self._create_plot_page(
                self.PLOT_TAB_SAMPLING,
                "Sampling Coverage",
                "Shows how input, reduced, and selected candidates are distributed across metric bins.",
            ),
            "Sampling Coverage",
        )
        self.plot_tabs.addTab(
            self._create_plot_page(
                self.PLOT_TAB_TIME_METRIC,
                "Time vs Metric",
                "Shows candidate and selected observations over time against the active optimization metric.",
            ),
            "Time vs Metric",
        )
        self.plot_tabs.addTab(
            self._create_plot_page(
                self.PLOT_TAB_SPACING,
                "Spacing",
                "Shows selected-observation spacing and the requested minimum spacing limit.",
            ),
            "Spacing",
        )
        self.plot_tabs.addTab(
            self._create_plot_page(
                self.PLOT_TAB_METRIC_DISTRIBUTION,
                "Metric Distribution",
                "Compares the metric distribution of input, reduced, and selected candidates.",
            ),
            "Metric Distribution",
        )
        self.plot_tabs.addTab(
            self._create_plot_page(
                self.PLOT_TAB_SLEW_PATH,
                "Slew / Path",
                "Shows transition slack, estimated slew time, and axis deltas from existing diagnostics data.",
            ),
            "Slew / Path",
        )

        # Backwards-compatible handle for older static verifiers.  New code
        # should use ``_plot_graphics`` through the helper methods below.
        self.graphics = self._plot_graphics[self.PLOT_TAB_SAMPLING]

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        layout.addWidget(self.plot_tabs, 0, 0)
        layout.setRowStretch(0, 1)
        layout.setColumnStretch(0, 1)

    def _create_plot_page(self, key: str, title: str, description: str) -> QWidget:
        """Create one diagnostics-plot sub-tab."""
        page = QWidget(self)
        page.setObjectName("guiV2PlannerDiagnosticsPlotPage")
        layout = QGridLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        label = QLabel(f"{title}: {description}", page)
        label.setObjectName("guiV2DiagnosticsPlotDescription")
        label.setWordWrap(True)
        graphics = pg.GraphicsLayoutWidget(page)
        graphics.setObjectName(f"guiV2DiagnosticsGraphics_{key}")
        self._plot_graphics[key] = graphics
        self._apply_background(graphics)
        self._set_placeholder(graphics, "Open this tab to render diagnostic plots.")

        layout.addWidget(label, 0, 0)
        layout.addWidget(graphics, 1, 0)
        layout.setRowStretch(0, 0)
        layout.setRowStretch(1, 1)
        layout.setColumnStretch(0, 1)
        return page

    def set_diagnostics(self, diagnostics: object | None, *, render_now: bool = False) -> None:
        """Store diagnostics and optionally render plot items immediately."""
        self._diagnostics = diagnostics
        self._rendered_diagnostics_id = None
        if diagnostics is None:
            self.clear()
            return
        if render_now:
            self.render_pending()
        else:
            for graphics in self._plot_graphics.values():
                self._apply_background(graphics)
                self._set_placeholder(graphics, "Open this tab to render diagnostic plots.")

    def render_pending(self) -> None:
        """Render stored diagnostics if they have not been rendered yet."""
        if self._diagnostics is None:
            self.clear()
            return
        diagnostics_id = id(self._diagnostics)
        if self._rendered_diagnostics_id == diagnostics_id:
            return
        self._rendered_diagnostics_id = diagnostics_id
        self._render(self._diagnostics)

    def clear(self) -> None:
        """Clear all diagnostic plots."""
        self._diagnostics = None
        self._rendered_diagnostics_id = None
        for graphics in self._plot_graphics.values():
            self._apply_background(graphics)
            self._set_placeholder(graphics, "No plan diagnostics available.")

    def release_runtime_resources(self) -> None:
        """Drop pyqtgraph diagnostics items during application shutdown."""
        for graphics in self._plot_graphics.values():
            try:
                graphics.setUpdatesEnabled(False)
            except Exception:
                pass
        self.clear()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API.
        """Refresh pyqtgraph styling after live GUI-v2 theme changes."""
        super().changeEvent(event)
        if event.type() in (
            QtCore.QEvent.Type.StyleChange,
            QtCore.QEvent.Type.PaletteChange,
            QtCore.QEvent.Type.ApplicationPaletteChange,
        ):
            QtCore.QTimer.singleShot(0, self._refresh_plot_theme)

    def _refresh_plot_theme(self) -> None:
        """Repaint diagnostic plots with the active GUI-v2 theme."""
        if self._diagnostics is not None and self._rendered_diagnostics_id == id(self._diagnostics):
            self._rendered_diagnostics_id = None
            self.render_pending()
            return
        for graphics in self._plot_graphics.values():
            self._apply_background(graphics)

    def _render(self, diagnostics: object) -> None:
        """Render each diagnostics plot concept into its own sub-tab."""
        series = dict(getattr(diagnostics, "plot_series", {}) or {})
        spacing_summary = dict(getattr(diagnostics, "spacing_summary", {}) or {})
        for graphics in self._plot_graphics.values():
            self._apply_background(graphics)
            graphics.clear()
        self._plot_bin_counts(series)
        self._plot_time_metric(series)
        self._plot_spacing_histogram(series, spacing_summary=spacing_summary)
        self._plot_metric_distribution(series)
        self._plot_slew_path(series)

    def _graphics(self, key: str) -> pg.GraphicsLayoutWidget:
        """Return the graphics layout for a plot sub-tab."""
        return self._plot_graphics[key]

    def _set_placeholder(self, graphics: pg.GraphicsLayoutWidget, text: str) -> None:
        """Render a placeholder message in one graphics layout."""
        graphics.clear()
        label = pg.LabelItem(text)
        graphics.addItem(label, row=0, col=0)

    def _add_legend(self, plot):
        """Add a compact diagnostics legend at the preferred top-right position.

        PyQtGraph interprets negative offset coordinates relative to the
        right/bottom edge of the plot parent.  A small negative x-offset
        keeps the legend aligned to the right side while retaining a margin
        from the plot frame.
        """
        return plot.addLegend(offset=(-10, 10))

    def _plot_bin_counts(self, series: dict[str, object]) -> None:
        graphics = self._graphics(self.PLOT_TAB_SAMPLING)
        plot = self._prepare_plot(graphics.addPlot(row=0, col=0, title="Sampling bin counts"))
        legend = self._add_legend(plot)
        bin_ids = np.asarray(series.get("bin_ids") or [], dtype=float)
        binning_mode = str(series.get("binning_mode") or "")
        bin_width = series.get("bin_width_deg")
        bin_axis_label = "Sampling bin"
        if binning_mode == "fixed_width" and bin_width is not None:
            bin_axis_label = f"Fixed-width bin ({float(bin_width):g} deg)"
        if bin_ids.size == 0:
            plot.addItem(self._empty_text("No bin diagnostics"))
            self._set_plot_label(plot, "bottom", bin_axis_label)
            self._set_plot_label(plot, "left", "Row count")
            return

        width = 0.25
        role_specs = [
            (-width, "bin_counts_input", "input"),
            (0.0, "bin_counts_reduced", "reduced"),
            (width, "bin_counts_selected", "selected"),
        ]
        for offset, key, role in role_specs:
            values = np.asarray(series.get(key) or [], dtype=float)
            if values.size != bin_ids.size:
                continue
            item = pg.BarGraphItem(x=bin_ids + offset, height=values, width=width, brush=_role_brush(role), pen=_role_pen(role))
            plot.addItem(item)
            legend.addItem(item, str(PLOT_ROLES[role]["label"]))
        self._set_plot_label(plot, "bottom", bin_axis_label)
        self._set_plot_label(plot, "left", "Row count")

    def _plot_time_metric(self, series: dict[str, object]) -> None:
        graphics = self._graphics(self.PLOT_TAB_TIME_METRIC)
        plot = self._prepare_plot(graphics.addPlot(row=0, col=0, title="Time vs metric", axisItems={"bottom": _make_utc_date_axis()}))
        legend = self._add_legend(plot)
        metric_label = str(series.get("metric_label") or series.get("metric_name") or "metric")
        role_series = [
            ("input", "candidate_times", "candidate_metric_values"),
            ("reduced", "reduced_times", "reduced_metric_values"),
            ("selected", "selected_times", "selected_metric_values"),
            ("repair_added", "repair_added_times", "repair_added_metric_values"),
        ]
        plotted_any = False
        for role, time_key, metric_key in role_series:
            x, y = _paired_arrays(series.get(time_key), series.get(metric_key))
            if x.size == 0:
                continue
            spec = PLOT_ROLES[role]
            item = plot.plot(
                x,
                y,
                pen=None,
                symbol=spec["symbol"],
                symbolSize=int(spec["symbol_size"]),
                symbolPen=_role_pen(role),
                symbolBrush=_role_brush(role),
            )
            legend.addItem(item, str(spec["label"]))
            plotted_any = True
        if not plotted_any:
            plot.addItem(self._empty_text("No time/metric diagnostics"))
        self._set_plot_label(plot, "bottom", "UTC time")
        self._set_plot_label(plot, "left", metric_label)

    def _plot_spacing_histogram(self, series: dict[str, object], *, spacing_summary: dict[str, object]) -> None:
        graphics = self._graphics(self.PLOT_TAB_SPACING)
        plot = self._prepare_plot(graphics.addPlot(row=0, col=0, title="Selected spacing histogram"))
        legend = self._add_legend(plot)
        values = _as_finite_array(series.get("spacing_deltas_minutes"))
        if values.size:
            counts, edges = np.histogram(values, bins=min(20, max(1, values.size)))
            centers = 0.5 * (edges[:-1] + edges[1:])
            widths = np.diff(edges)
            item = pg.BarGraphItem(x=centers, height=counts, width=widths, brush=_role_brush("selected"), pen=_role_pen("selected"))
            plot.addItem(item)
            legend.addItem(item, "Selected spacing")
        else:
            plot.addItem(self._empty_text("No spacing deltas"))

        spacing_min = spacing_summary.get("requested_spacing_min")
        try:
            spacing_min = float(spacing_min)
        except (TypeError, ValueError):
            spacing_min = None
        if spacing_min is not None and np.isfinite(spacing_min):
            spacing_pen = _role_pen("spacing_minimum", style=QtCore.Qt.PenStyle.DashLine)
            line = pg.InfiniteLine(pos=spacing_min, angle=90, pen=spacing_pen)
            plot.addItem(line)
            legend_proxy = pg.PlotDataItem([], [], pen=spacing_pen)
            legend.addItem(legend_proxy, str(PLOT_ROLES["spacing_minimum"]["label"]))
        self._set_plot_label(plot, "bottom", "Spacing [min]")
        self._set_plot_label(plot, "left", "Count")

    def _plot_metric_distribution(self, series: dict[str, object]) -> None:
        graphics = self._graphics(self.PLOT_TAB_METRIC_DISTRIBUTION)
        plot = self._prepare_plot(graphics.addPlot(row=0, col=0, title="Metric distribution"))
        legend = self._add_legend(plot)
        metric_label = str(series.get("metric_label") or series.get("metric_name") or "metric")
        datasets = [
            ("input", _as_finite_array(series.get("metric_input_values"))),
            ("reduced", _as_finite_array(series.get("metric_reduced_values"))),
            ("selected", _as_finite_array(series.get("metric_selected_values"))),
        ]
        finite = np.concatenate([data for _, data in datasets if data.size]) if any(data.size for _, data in datasets) else np.array([])
        if finite.size == 0:
            plot.addItem(self._empty_text("No metric values"))
            self._set_plot_label(plot, "bottom", metric_label)
            self._set_plot_label(plot, "left", "Row count")
            return

        bins = min(30, max(5, int(np.sqrt(finite.size))))
        for role, data in datasets:
            if data.size == 0:
                continue
            counts, edges = np.histogram(data, bins=bins)
            centers = 0.5 * (edges[:-1] + edges[1:])
            item = plot.plot(
                centers,
                counts,
                pen=_role_pen(role),
                symbol=PLOT_ROLES[role]["symbol"],
                symbolSize=5,
                symbolPen=_role_pen(role),
                symbolBrush=_role_brush(role),
            )
            legend.addItem(item, str(PLOT_ROLES[role]["label"]))
        self._set_plot_label(plot, "bottom", metric_label)
        self._set_plot_label(plot, "left", "Row count")

    def _plot_slew_path(self, series: dict[str, object]) -> None:
        """Plot transition slack, slew estimate, and axis deltas from existing backend data."""
        graphics = self._graphics(self.PLOT_TAB_SLEW_PATH)
        slack = _as_finite_array(series.get("transition_slack_sec"))
        slew = _as_finite_array(series.get("transition_slew_sec"))
        available = _as_finite_array(series.get("transition_available_time_sec"))
        az_delta = _as_finite_array(series.get("transition_az_delta_deg"))
        alt_delta = _as_finite_array(series.get("transition_alt_delta_deg"))
        violation_flags = _as_finite_array(series.get("transition_violation_flags"))

        if not any(values.size for values in (slack, slew, available, az_delta, alt_delta)):
            plot = self._prepare_plot(graphics.addPlot(row=0, col=0, title="Slew / path diagnostics"))
            plot.addItem(self._empty_text("No slew/path plot series available"))
            self._set_plot_label(plot, "bottom", "Transition index")
            self._set_plot_label(plot, "left", "Value")
            return

        if slack.size or slew.size or available.size:
            plot = self._prepare_plot(graphics.addPlot(row=0, col=0, title="Transition timing"))
            legend = self._add_legend(plot)
            max_len = max(slack.size, slew.size, available.size)
            index = np.arange(max_len, dtype=float)
            if available.size:
                item = plot.plot(index[: available.size], available, pen=pg.mkPen(active_theme_palette().series_reduced, width=2), symbol="o", symbolSize=5)
                legend.addItem(item, "Available time")
            if slew.size:
                item = plot.plot(index[: slew.size], slew, pen=pg.mkPen(active_theme_palette().series_selected, width=2), symbol="t", symbolSize=5)
                legend.addItem(item, "Estimated slew")
            if slack.size:
                item = plot.plot(index[: slack.size], slack, pen=pg.mkPen(active_theme_palette().series_warning, width=2), symbol="x", symbolSize=6)
                legend.addItem(item, "Slack")
            if violation_flags.size:
                violation_index = np.where(violation_flags[:max_len] > 0)[0].astype(float)
                if violation_index.size:
                    y_values = np.zeros_like(violation_index, dtype=float)
                    item = plot.plot(violation_index, y_values, pen=None, symbol="star", symbolSize=10, symbolPen=pg.mkPen(active_theme_palette().error, width=2), symbolBrush=pg.mkBrush(QColor(active_theme_palette().error)))
                    legend.addItem(item, "Violation")
            self._set_plot_label(plot, "bottom", "Transition index")
            self._set_plot_label(plot, "left", "Time [s]")

        if az_delta.size or alt_delta.size:
            plot = self._prepare_plot(graphics.addPlot(row=1, col=0, title="Axis deltas"))
            legend = self._add_legend(plot)
            max_len = max(az_delta.size, alt_delta.size)
            index = np.arange(max_len, dtype=float)
            if az_delta.size:
                item = plot.plot(index[: az_delta.size], az_delta, pen=pg.mkPen(active_theme_palette().series_reduced, width=2), symbol="o", symbolSize=5)
                legend.addItem(item, "Azimuth delta")
            if alt_delta.size:
                item = plot.plot(index[: alt_delta.size], alt_delta, pen=pg.mkPen(active_theme_palette().series_alt, width=2), symbol="t", symbolSize=5)
                legend.addItem(item, "Altitude delta")
            self._set_plot_label(plot, "bottom", "Transition index")
            self._set_plot_label(plot, "left", "Delta [deg]")

    def _prepare_plot(self, plot):
        """Apply the active GUI-v2 plot theme to one pyqtgraph plot."""
        theme = self._plot_theme()
        foreground = theme["foreground"]
        background = theme["background"]
        try:
            plot.getViewBox().setBackgroundColor(background)
        except Exception:
            pass
        for axis_name in ("bottom", "left"):
            axis = plot.getAxis(axis_name)
            axis.setPen(QPen(foreground))
            axis.setTextPen(QPen(foreground))
        plot.showGrid(x=True, y=True, alpha=0.18 if self._uses_dark_theme() else 0.16)
        return plot

    def _set_plot_label(self, plot, axis: str, text: str) -> None:
        """Set one axis label using the active GUI-v2 plot text color."""
        color = self._plot_theme()["foreground"]
        label_color = color.name() if isinstance(color, QColor) else str(color)
        plot.setLabel(axis, text, color=label_color)

    def _empty_text(self, text: str) -> pg.TextItem:
        """Return a theme-aware empty-state text item."""
        return pg.TextItem(text, color=self._plot_theme()["empty_text"])

    def _apply_background(self, graphics: pg.GraphicsLayoutWidget | None = None) -> None:
        """Apply active GUI-v2 background to one or all graphics layouts."""
        background = self._plot_theme()["background"]
        targets = [graphics] if graphics is not None else list(self._plot_graphics.values())
        for target in targets:
            if target is not None:
                target.setBackground(background)

    def _plot_theme(self) -> dict[str, object]:
        """Return plot colors from the active semantic GUI-v2 palette."""
        palette = active_theme_palette()
        return {
            "background": QColor(palette.plot_background),
            "foreground": QColor(palette.plot_foreground),
            "grid": QColor(palette.plot_grid),
            "text": QColor(palette.plot_foreground),
            "empty_text": QColor(palette.plot_foreground),
        }

    @staticmethod
    def _uses_dark_theme() -> bool:
        """Return whether the active semantic GUI-v2 palette is dark."""
        return active_theme_name() == "dark"



class PlannerDiagnosticsWorkspace(QWidget):
    """Tabbed GUI-v2 workspace for planner diagnostics."""

    diagnosticsRefreshRequested = pyqtSignal()
    plotsTabActivated = pyqtSignal()

    TAB_OVERVIEW = 0
    TAB_TABLE = 1
    TAB_PLOTS = 2
    TAB_DETAILS = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiV2PlannerDiagnosticsWorkspace")
        self._diagnostics: object | None = None
        self._snapshot: PlannerRuntimeSnapshot | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.summary_strip = QFrame(self)
        self.summary_strip.setObjectName("guiV2DiagnosticsSummaryStrip")
        summary_layout = QGridLayout(self.summary_strip)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setHorizontalSpacing(10)
        summary_layout.setVerticalSpacing(8)

        self.status_card = DiagnosticsInfoCard("Status", self.summary_strip)
        self.trust_card = DiagnosticsInfoCard("Trust Summary", self.summary_strip)
        self.plan_card = DiagnosticsInfoCard("Plan Size", self.summary_strip)
        self.spacing_card = DiagnosticsInfoCard("Spacing", self.summary_strip)
        for column, card in enumerate((self.status_card, self.trust_card, self.plan_card, self.spacing_card)):
            summary_layout.addWidget(card, 0, column)
            summary_layout.setColumnStretch(column, 1)
        root.addWidget(self.summary_strip)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("guiV2PlannerDiagnosticsTabs")
        self.tabs.setProperty("visualRole", "workspaceTabs")
        self.tabs.currentChanged.connect(self._handle_tab_changed)
        root.addWidget(self.tabs, 1)

        self.overview_tab = self._build_overview_tab()
        self.table_tab = self._build_table_tab()
        self.plots_tab = self._build_plots_tab()
        self.details_tab = self._build_details_tab()
        self.tabs.addTab(self.overview_tab, "Overview")
        self.tabs.addTab(self.table_tab, "Diagnostics Table")
        self.tabs.addTab(self.plots_tab, "Diagnostics Plots")
        self.tabs.addTab(self.details_tab, "Details / Reproducibility")

        self.set_diagnostics(None)

    def set_snapshot(self, snapshot: PlannerRuntimeSnapshot) -> None:
        """Store the latest planner snapshot and refresh empty/stale messages."""
        self._snapshot = snapshot
        self._render_summary()

    def set_diagnostics(self, diagnostics: object | None) -> None:
        """Render a backend diagnostics object without recomputing metrics."""
        self._diagnostics = diagnostics
        self._render_summary()
        self._render_overview()
        self._render_table()
        self._render_details()
        render_plots = self.tabs.currentIndex() == self.TAB_PLOTS and self.isVisible()
        self.diagnostics_plots.set_diagnostics(diagnostics, render_now=render_plots)

    def release_runtime_resources(self) -> None:
        """Release heavy plot resources before shutdown."""
        self.diagnostics_plots.release_runtime_resources()

    def maybe_refresh_stale_diagnostics(self) -> None:
        """Request lazy diagnostics refresh when the snapshot says they are stale."""
        snapshot = self._snapshot
        if snapshot is None:
            return
        readiness = snapshot.readiness
        if readiness.plan_available and not readiness.diagnostics_available:
            self.diagnosticsRefreshRequested.emit()

    def _build_overview_tab(self) -> QWidget:
        """Build overview tab with grouped diagnostics cards."""
        content = QWidget(self)
        content.setObjectName("guiV2PlannerDiagnosticsOverview")
        grid = QGridLayout(content)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.status_overview_card = DiagnosticsInfoCard("Plan Status", content)
        self.quality_card = DiagnosticsInfoCard("Plan Quality", content)
        self.spacing_overview_card = DiagnosticsInfoCard("Spacing", content)
        self.impact_card = DiagnosticsInfoCard("Optimization Impact", content)
        self.slew_card = DiagnosticsInfoCard("Slew / Path", content)
        self.repair_card = DiagnosticsInfoCard("Repair / Multi-start", content)
        self._overview_cards = (
            self.status_overview_card,
            self.quality_card,
            self.spacing_overview_card,
            self.impact_card,
            self.slew_card,
            self.repair_card,
        )
        for index, card in enumerate(self._overview_cards):
            grid.addWidget(card, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(3, 1)
        return self._wrap_scroll_area(content)

    def _build_table_tab(self) -> QWidget:
        """Build diagnostics table tab."""
        tab = QWidget(self)
        layout = QGridLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        self.table_title = QLabel("No plan diagnostics available.", tab)
        self.table_title.setObjectName("guiV2DiagnosticsTableTitle")
        self.table_title.setWordWrap(True)
        self.table_model = DiagnosticsTableModel(tab)
        self.table_view = QTableView(tab)
        self.table_view.setObjectName("guiV2PlannerDiagnosticsTable")
        self.table_view.setModel(self.table_model)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table_view.setWordWrap(False)
        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.table_title, 0, 0)
        layout.addWidget(self.table_view, 1, 0)
        layout.setRowStretch(0, 0)
        layout.setRowStretch(1, 1)
        layout.setColumnStretch(0, 1)
        return tab

    def _build_plots_tab(self) -> QWidget:
        """Build lazy diagnostics plots tab."""
        tab = QWidget(self)
        layout = QGridLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        self.diagnostics_plots = V2PlannerDiagnosticsPlots(tab)
        layout.addWidget(self.diagnostics_plots, 0, 0)
        layout.setRowStretch(0, 1)
        layout.setColumnStretch(0, 1)
        return tab

    def _build_details_tab(self) -> QWidget:
        """Build details/reproducibility tab."""
        content = QWidget(self)
        content.setObjectName("guiV2PlannerDiagnosticsDetailsContent")
        grid = QGridLayout(content)
        grid.setContentsMargins(12, 12, 12, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.details_text = QPlainTextEdit(content)
        self.details_text.setObjectName("guiV2PlannerDiagnosticsDetailsText")
        self.details_text.setReadOnly(True)
        self.details_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        grid.addWidget(self.details_text, 0, 0)
        grid.setRowStretch(0, 1)
        grid.setColumnStretch(0, 1)
        return self._wrap_scroll_area(content)

    def _wrap_scroll_area(self, content: QWidget) -> QScrollArea:
        """Return a resizable scroll area for overflow tabs."""
        scroll = QScrollArea(self)
        scroll.setObjectName("guiV2PlannerDiagnosticsScrollArea")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _handle_tab_changed(self, index: int) -> None:
        """Refresh stale diagnostics and lazily render plots when activated."""
        if index in {self.TAB_TABLE, self.TAB_PLOTS, self.TAB_DETAILS}:
            self.maybe_refresh_stale_diagnostics()
        if index == self.TAB_PLOTS:
            self.plotsTabActivated.emit()
            self.diagnostics_plots.render_pending()

    def _render_summary(self) -> None:
        """Render summary strip from current snapshot and diagnostics."""
        snapshot = self._snapshot
        diagnostics = self._diagnostics
        readiness = snapshot.readiness if snapshot is not None else None
        if diagnostics is None:
            status_text = self._empty_or_stale_message()
            self.status_card.set_body(status_text)
            self.trust_card.set_body("Unavailable until diagnostics are generated or refreshed.")
            plan_rows = getattr(snapshot, "visibility_row_count", 0) if snapshot is not None else 0
            self.plan_card.set_body(f"Visibility rows: {plan_rows}" if plan_rows else "No loaded planner data.")
            self.spacing_card.set_body("No spacing diagnostics available.")
            return

        self.status_card.set_body("Current diagnostics available." if readiness is None or readiness.diagnostics_available else "Diagnostics may be stale; open a diagnostics tab to refresh.")
        self.trust_card.set_body(_diagnostics_title(diagnostics))
        output_summary = _safe_mapping(getattr(diagnostics, "output_summary", {}))
        selected_rows = output_summary.get("selected_rows", getattr(diagnostics, "selected_rows", None))
        self.plan_card.set_body(f"Selected observations: {_format_value(selected_rows)}")
        spacing = _safe_mapping(getattr(diagnostics, "spacing_summary", {}))
        spacing_parts = []
        for key in ("requested_spacing_min", "spacing_violations", "min_actual_spacing_min", "median_actual_spacing_min"):
            if key in spacing:
                spacing_parts.append(f"{key}={_format_value(spacing[key])}")
        self.spacing_card.set_body("; ".join(spacing_parts) if spacing_parts else "Spacing summary unavailable.")

    def _render_overview(self) -> None:
        """Render concise operator-facing overview cards."""
        presentation = present_planner_diagnostics_overview(self._diagnostics)
        cards = getattr(self, "_overview_cards", ())
        if not cards:
            return
        if self._diagnostics is None:
            message = self._empty_or_stale_message()
            for card in cards:
                card.set_body(message)
            return
        for card, card_presentation in zip(cards, presentation.cards, strict=False):
            card.set_presentation(card_presentation)

    def _render_table(self) -> None:
        """Render sectioned diagnostics table."""
        diagnostics = self._diagnostics
        self.table_title.setText(_diagnostics_title(diagnostics) if diagnostics is not None else self._empty_or_stale_message())
        self.table_model.set_rows(_table_rows_from_diagnostics(diagnostics))

    def _render_details(self) -> None:
        """Render reproducibility and raw summary details."""
        diagnostics = self._diagnostics
        if diagnostics is None:
            self.details_text.setPlainText(self._empty_or_stale_message())
            return
        lines = ["Planner Diagnostics Details", "", _diagnostics_title(diagnostics), ""]
        for section, mapping in getattr(diagnostics, "table_sections", lambda: [])():
            lines.append(f"[{section}]")
            if isinstance(mapping, Mapping):
                for key, value in mapping.items():
                    lines.append(f"{key}: {_format_value(value)}")
            else:
                lines.append(_format_value(mapping))
            lines.append("")
        self.details_text.setPlainText("\n".join(lines).strip())

    def _empty_or_stale_message(self) -> str:
        """Return a user-facing empty/stale state message."""
        snapshot = self._snapshot
        if snapshot is None:
            return "No planner diagnostics available yet. Generate a plan to populate diagnostics."
        readiness = snapshot.readiness
        if not readiness.plan_available:
            return "No planner diagnostics available yet. Generate a plan to populate diagnostics."
        if not readiness.diagnostics_available:
            return "Diagnostics are pending refresh after manual plan edits. Open a diagnostics tab to refresh."
        return "Diagnostics are not available for the current plan."


__all__ = (
    "DiagnosticsTableModel",
    "PlannerDiagnosticsWorkspace",
    "V2PlannerDiagnosticsPlots",
)
