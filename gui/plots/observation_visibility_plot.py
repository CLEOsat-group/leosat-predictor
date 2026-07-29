"""Pyqtgraph visibility plot for the observation planner."""

from __future__ import annotations

import datetime as dt
import logging
import math
import time

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QToolTip, QVBoxLayout, QWidget

from gui.models.observation_plan_table_model import GENERATED_SOURCE, MANUAL_SOURCE, ObservationPlanRecord
from gui.styles import active_theme_palette
from gui.workers.observation_planner_workers import PrepareVisibilityPlotWorker
from src.observation_planner.preferences import DEFAULT_LEGEND_PAGE_SIZE, legend_page_slice
from src.observation_planner.schema import resolve_column
from src.observation_planner.selector_plot_contract import SelectorPlotGroup, SelectorPlotPayload

_logger = logging.getLogger(__name__)


class DateAxisItem(pg.AxisItem):
    """Axis item displaying epoch-second values as UTC date strings."""

    def tickStrings(self, values, scale, spacing):  # noqa: N802
        """Return UTC tick labels for epoch-second values."""
        labels = []
        for value in values:
            try:
                labels.append(dt.datetime.fromtimestamp(float(value), dt.UTC).strftime("%Y-%m-%d %H:%M"))
            except Exception:
                labels.append("")
        return labels


class ObservationVisibilityPlot(QWidget):
    """Visibility elevation plot with selector-compatible interaction.

    The rendering path intentionally mirrors the standalone
    ``leosat-obs-selector.py`` plot path: a fresh ``PlotWidget`` with a
    ``DateAxisItem`` is created for each loaded data view, one scatter item is
    added per satellite, and the moving time marker / red past region are kept
    as first-class selector features.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget.
    """

    point_selected = pyqtSignal(int)
    time_markers_updated = pyqtSignal()
    render_started = pyqtSignal(str)
    render_progress = pyqtSignal(str)
    render_succeeded = pyqtSignal(str)
    render_canceled = pyqtSignal(str)
    render_failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._data_view = pd.DataFrame()
        self._satellite_colors: dict[str, object] = {}
        self._scatter_items: list[pg.ScatterPlotItem] = []
        self._selected_items: list[object] = []
        self._checked_items: list[object] = []
        self._generated_items: list[object] = []
        self._manual_items_by_key: dict[str, list[object]] = {}
        self._generated_items_by_key: dict[str, list[object]] = {}
        self._time_region_left: float | None = None
        self._identity_row_maps: dict[str, dict[str, int]] = {}
        self._plot_x_values = np.asarray([], dtype="float64")
        self._plot_y_values = np.asarray([], dtype="float64")
        self._plot_local_rows = np.asarray([], dtype="int64")
        self._legend_page = 0
        self._legend_page_size = DEFAULT_LEGEND_PAGE_SIZE
        self._satellite_legend = None
        self._legend_page_label = None
        self._time_timer = QtCore.QTimer(self)
        self._time_timer.setInterval(1000)
        self._time_timer.timeout.connect(self.update_time_markers)
        self._render_timer = QtCore.QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_next_slice)
        self._render_generation = 0
        self._plot_workers: set[PrepareVisibilityPlotWorker] = set()
        self._render_payload: SelectorPlotPayload | None = None
        self._render_group_index = 0
        self._render_group_offset = 0
        self._render_identity_data: list[dict[str, int]] = []
        self._render_points_committed = 0
        self._rendering = False
        self._released = False
        self._theme_restart_pending = False
        self._plot = self._create_plot()
        self._layout.addWidget(self._plot)
        self._add_placeholder()

    @property
    def is_rendering(self) -> bool:
        """Return whether plot preparation or incremental rendering is active."""

        return self._rendering

    def release_runtime_resources(self) -> None:
        """Cancel plot work and drop large references before shutdown."""

        self._released = True
        self._render_generation += 1
        workers = tuple(self._plot_workers)
        self._cancel_active_render()
        for worker in workers:
            try:
                if worker.isRunning() and not worker.wait(1000):
                    _logger.warning("Visibility-plot worker did not stop within the shutdown wait window.")
            except RuntimeError:
                pass
        try:
            self._time_timer.stop()
        except RuntimeError:
            pass
        QToolTip.hideText()
        self._data_view = pd.DataFrame()
        self._satellite_colors = {}
        self._scatter_items = []
        self._selected_items = []
        self._checked_items = []
        self._generated_items = []
        self._manual_items_by_key = {}
        self._generated_items_by_key = {}
        self._identity_row_maps = {}
        self._plot_x_values = np.asarray([], dtype="float64")
        self._plot_y_values = np.asarray([], dtype="float64")
        self._plot_local_rows = np.asarray([], dtype="int64")
        self._satellite_legend = None
        self._legend_page_label = None
        try:
            self._plot.setUpdatesEnabled(False)
            self._plot.clear()
        except Exception:
            pass

    def cancel_render(self, message: str = "Visibility plot rendering canceled.") -> None:
        """Cancel the current request cooperatively and invalidate late results."""

        was_active = self._rendering
        self._render_generation += 1
        self._cancel_active_render()
        if was_active:
            self.render_canceled.emit(str(message or "Visibility plot rendering canceled."))

    def _cancel_active_render(self) -> None:
        """Stop render slices and request interruption from all live workers."""

        self._render_timer.stop()
        for worker in tuple(self._plot_workers):
            try:
                worker.request_cancel()
            except RuntimeError:
                pass
        self._render_payload = None
        self._render_group_index = 0
        self._render_group_offset = 0
        self._render_identity_data = []
        self._render_points_committed = 0
        self._rendering = False

    def set_legend_page_size(self, page_size: int) -> None:
        """Set donor-equivalent satellite legend page size.

        Parameters
        ----------
        page_size : int
            Maximum number of satellites displayed on one legend page.
        """
        self._legend_page_size = max(1, int(page_size))
        self._legend_page = 0

    def set_dataframe(self, dataframe: pd.DataFrame | None, satellite_colors: dict[str, object] | None = None) -> None:
        """Request asynchronous preparation and incremental rendering."""

        self._released = False
        was_rendering = self._rendering
        self._render_generation += 1
        generation = self._render_generation
        self._cancel_active_render()
        self._data_view = dataframe.copy(deep=False) if dataframe is not None else pd.DataFrame()
        self._satellite_colors = dict(satellite_colors or {})
        self._reset_render_surfaces()

        if self._data_view.empty:
            self._reset_plot_widget()
            self._add_placeholder()
            if was_rendering:
                self.render_canceled.emit("Visibility plot rendering canceled because no data remain.")
            return

        self._rendering = True
        self._reset_plot_widget()
        self._add_status_placeholder("Preparing visibility plot…")
        self.render_started.emit("Preparing visibility plot…")

        worker = PrepareVisibilityPlotWorker(self._data_view, generation)
        worker.prepared.connect(self._handle_payload_prepared)
        worker.preparationFailed.connect(self._handle_payload_failed)
        worker.canceled.connect(self._handle_payload_canceled)
        worker.finished.connect(lambda w=worker: self._forget_plot_worker(w))
        self._plot_workers.add(worker)
        worker.start()

    def clear(self) -> None:
        """Clear the plot and show its placeholder."""

        self.set_dataframe(pd.DataFrame())

    def update_selected_highlight(self, row_index: int | None) -> None:
        """Draw the red selected-row highlight."""
        self._clear_items(self._selected_items)
        self._selected_items = []
        if row_index is None or self._data_view.empty or row_index < 0 or row_index >= len(self._data_view):
            return
        row = self._data_view.iloc[row_index]
        self._selected_items = self._add_highlight_for_row(
            row,
            color=self._theme_color("error", 180),
            line_style=Qt.PenStyle.DashLine,
            size=14,
        )

    def update_checked_highlights(self, data_master: pd.DataFrame | None) -> None:
        """Backward-compatible checked-highlight refresh.

        This method is retained for broad refresh paths.  Manual interaction
        paths should use ``update_manual_highlight_for_record`` or
        ``replace_manual_highlights`` so a single checkbox click does not redraw
        generated highlights.
        """
        _ = data_master
        self._clear_items(self._checked_items)
        self._checked_items = []
        if self._data_view.empty or "_checked" not in self._data_view.columns:
            return
        checked = self._data_view[self._data_view["_checked"]]
        for _, row in checked.iterrows():
            self._checked_items.extend(
                self._add_highlight_for_row(
                    row,
                    color=self._theme_color("manual", 170),
                    line_style=Qt.PenStyle.DotLine,
                    size=10,
                )
            )

    def replace_manual_highlights(self, records: list[ObservationPlanRecord]) -> None:
        """Replace blue highlights for manually selected plan rows only."""
        self._clear_highlight_dict(self._manual_items_by_key)
        self._manual_items_by_key = {}
        for record in records:
            if record.source != MANUAL_SOURCE:
                continue
            self.update_manual_highlight_for_record(record, True)

    def update_manual_highlight_for_record(self, record: ObservationPlanRecord, checked: bool) -> None:
        """Add or remove one manual-row highlight by plan-record identity."""
        key = self._record_highlight_key(record)
        if key is None:
            return
        existing = self._manual_items_by_key.pop(key, None)
        if existing:
            self._clear_items(existing)
        if not checked:
            return
        row = self._matching_row_for_plan_record(record)
        if row is not None:
            items = self._add_highlight_for_row(
                row,
                color=self._theme_color("manual", 170),
                line_style=Qt.PenStyle.DotLine,
                size=10,
            )
        else:
            try:
                timestamp = pd.to_datetime(record.date_ut, utc=True).timestamp()
                elevation = float(record.elev)
                if not math.isfinite(timestamp) or not math.isfinite(elevation):
                    return
                items = self._add_highlight(
                    timestamp,
                    elevation,
                    color=self._theme_color("manual", 170),
                    line_style=Qt.PenStyle.DotLine,
                    size=10,
                )
            except Exception:
                return
        if items:
            self._manual_items_by_key[key] = items

    def update_generated_highlights(self, records: list[ObservationPlanRecord]) -> None:
        """Draw green highlights for generated observation-plan rows only."""
        self._clear_highlight_dict(self._generated_items_by_key)
        self._generated_items_by_key = {}
        self._generated_items = []
        for record in records:
            if record.source != GENERATED_SOURCE:
                continue
            key = self._record_highlight_key(record)
            if key is None:
                continue
            row = self._matching_row_for_plan_record(record)
            if row is not None:
                items = self._add_highlight_for_row(
                    row,
                    color=self._theme_color("generated", 190),
                    line_style=Qt.PenStyle.DashLine,
                    size=12,
                )
            else:
                try:
                    timestamp = pd.to_datetime(record.date_ut, utc=True).timestamp()
                    elevation = float(record.elev)
                    if not math.isfinite(timestamp) or not math.isfinite(elevation):
                        continue
                    items = self._add_highlight(
                        timestamp,
                        elevation,
                        color=self._theme_color("generated", 190),
                        line_style=Qt.PenStyle.DashLine,
                        size=12,
                    )
                except Exception:
                    continue
            if items:
                self._generated_items_by_key[key] = items
                self._generated_items.extend(items)

    def clear_observation_highlights(self) -> None:
        """Clear manual, generated, and selected observation highlight layers."""
        self._clear_items(self._selected_items)
        self._selected_items = []
        self._clear_highlight_dict(self._manual_items_by_key)
        self._manual_items_by_key = {}
        self._clear_highlight_dict(self._generated_items_by_key)
        self._generated_items_by_key = {}
        self._clear_items(self._checked_items)
        self._checked_items = []
        self._clear_items(self._generated_items)
        self._generated_items = []

    def update_plan_selection_highlight(self, record: ObservationPlanRecord | None) -> None:
        """Draw the selected-plan-row highlight in the visibility plot.

        Selecting a row in the Observation Plan table should identify the same
        observation point in the visibility plot, but it must not transfer the
        row into the Observation Info panel.  That transfer remains controlled
        only by the explicit Select Observation button.

        Parameters
        ----------
        record : ObservationPlanRecord or None
            Selected plan-table record.  Passing `None` clears the selected
            highlight.
        """
        self._clear_items(self._selected_items)
        self._selected_items = []
        if record is None:
            return

        row = self._matching_row_for_plan_record(record)
        if row is not None:
            self._selected_items = self._add_highlight_for_row(
                row,
                color=self._theme_color("error", 180),
                line_style=Qt.PenStyle.DashLine,
                size=14,
            )
            return

        try:
            timestamp = pd.to_datetime(record.date_ut, utc=True).timestamp()
            elevation = float(record.elev)
            if not math.isfinite(timestamp) or not math.isfinite(elevation):
                return
        except Exception:
            return
        self._selected_items = self._add_highlight(
            timestamp,
            elevation,
            color=self._theme_color("error", 180),
            line_style=Qt.PenStyle.DashLine,
            size=14,
        )

    def start_time_markers(self) -> None:
        """Start updating the selector now marker and red past region."""
        if self._data_view.empty:
            return
        try:
            date_ts_col = resolve_column(self._data_view, "date_ts")
            timestamps = pd.to_numeric(self._data_view[date_ts_col], errors="coerce").dropna()
            self._time_region_left = float(timestamps.min()) if not timestamps.empty else time.time() - 24 * 3600
        except Exception:
            self._time_region_left = time.time() - 24 * 3600
        self._ensure_time_items()
        if not self._time_timer.isActive():
            self._time_timer.start()

    def stop_time_markers(self) -> None:
        """Stop and detach time marker items from the current plot."""
        if self._time_timer.isActive():
            self._time_timer.stop()
        for name in ("_time_line", "_past_region"):
            item = getattr(self, name, None)
            if item is not None:
                try:
                    self._plot.removeItem(item)
                except Exception:
                    pass

    def update_time_markers(self) -> None:
        """Update the selector now marker and red past region."""
        if self._data_view.empty:
            return
        self._ensure_time_items()
        now_ts = time.time()
        if hasattr(self, "_time_line"):
            self._time_line.setValue(now_ts)
        if hasattr(self, "_past_region"):
            left = self._time_region_left if self._time_region_left is not None else now_ts - 24 * 3600
            self._past_region.setRegion((left, left if now_ts <= left else now_ts))
        self.time_markers_updated.emit()

    def _create_plot(self) -> pg.PlotWidget:
        axis = DateAxisItem(orientation="bottom")
        axis.enableAutoSIPrefix(False)
        plot = pg.PlotWidget(axisItems={"bottom": axis})
        plot.setLabel("bottom", "Date [UT]")
        plot.setLabel("left", "Elevation [deg]")
        self._apply_plot_theme(plot)
        plot.scene().sigMouseClicked.connect(self._on_plot_clicked)
        return plot

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Refresh or rebuild plot graphics after an application theme change."""

        super().changeEvent(event)
        if event.type() not in (
            QtCore.QEvent.Type.StyleChange,
            QtCore.QEvent.Type.PaletteChange,
            QtCore.QEvent.Type.ApplicationPaletteChange,
        ):
            return
        if self._data_view.empty or not self.isVisible():
            QtCore.QTimer.singleShot(0, lambda: self._apply_plot_theme(self._plot))
            return
        if self._theme_restart_pending:
            return
        self._theme_restart_pending = True
        QtCore.QTimer.singleShot(0, self._restart_render_for_theme)

    def _restart_render_for_theme(self) -> None:
        """Rebuild scene-owned colors once after a live theme transition."""

        self._theme_restart_pending = False
        if self._released:
            return
        if self._data_view.empty or not self.isVisible():
            self._apply_plot_theme(self._plot)
            return
        self.set_dataframe(self._data_view, self._satellite_colors)

    def _apply_plot_theme(self, plot: pg.PlotWidget) -> None:
        """Apply the shared active scientific-plot palette without rebuilding data."""

        palette = active_theme_palette()
        background = QtGui.QColor(palette.plot_background)
        foreground = QtGui.QColor(palette.plot_foreground)
        plot.setBackground(background)
        try:
            plot.getPlotItem().getViewBox().setBackgroundColor(background)
        except Exception:
            pass
        for axis_name in ("bottom", "left"):
            axis = plot.getAxis(axis_name)
            axis.setPen(QtGui.QPen(foreground))
            axis.setTextPen(QtGui.QPen(foreground))
        plot.setLabel("bottom", "Date [UT]", color=palette.plot_foreground)
        plot.setLabel("left", "Elevation [deg]", color=palette.plot_foreground)
        plot.showGrid(x=True, y=True, alpha=0.20)
        if hasattr(self, "_time_line"):
            self._time_line.setPen(pg.mkPen(self._theme_color("error", 200), width=1.5))
        if hasattr(self, "_past_region"):
            self._past_region.setBrush(pg.mkBrush(self._theme_color("error", 90)))

    @staticmethod
    def _theme_color(role: str, alpha: int = 255) -> QtGui.QColor:
        """Return one theme-aware semantic plot color."""

        palette = active_theme_palette()
        colors = {
            "error": palette.error,
            "manual": palette.series_alt,
            "generated": palette.series_selected,
            "muted": palette.plot_foreground,
            "foreground": palette.plot_foreground,
        }
        color = QtGui.QColor(colors.get(role, palette.accent))
        color.setAlpha(max(0, min(255, int(alpha))))
        return color

    def _reset_plot_widget(self) -> None:
        """Replace the PlotWidget as done by the standalone selector."""
        old_plot = getattr(self, "_plot", None)
        if old_plot is not None:
            try:
                self.stop_time_markers()
            except Exception:
                pass
            self._layout.removeWidget(old_plot)
            old_plot.deleteLater()
        self._plot = self._create_plot()
        self._layout.addWidget(self._plot)

    def _reset_render_surfaces(self) -> None:
        """Reset scene-owned references before a new plot request."""

        self._scatter_items = []
        self._selected_items = []
        self._checked_items = []
        self._generated_items = []
        self._manual_items_by_key = {}
        self._generated_items_by_key = {}
        self._time_region_left = None
        self._satellite_legend = None
        self._legend_page_label = None
        self._identity_row_maps = {}
        self._plot_x_values = np.asarray([], dtype="float64")
        self._plot_y_values = np.asarray([], dtype="float64")
        self._plot_local_rows = np.asarray([], dtype="int64")

    def _handle_payload_prepared(self, generation: int, payload: SelectorPlotPayload) -> None:
        """Accept only the newest worker payload and start the render pump."""

        if self._released or generation != self._render_generation:
            return
        self._render_payload = payload
        self._identity_row_maps = {name: dict(mapping) for name, mapping in payload.identity_row_maps.items()}
        self._plot_x_values = payload.x_values
        self._plot_y_values = payload.y_values
        self._plot_local_rows = payload.local_rows
        self._render_group_index = 0
        self._render_group_offset = 0
        self._render_identity_data = []
        self._render_points_committed = 0
        self._reset_plot_widget()
        if payload.point_count == 0:
            self._rendering = False
            self._render_payload = None
            self._add_status_placeholder("No finite visibility points to plot.")
            self.render_succeeded.emit("Visibility plot contains no finite points.")
            return
        self.render_progress.emit(
            f"Rendering visibility plot: 0/{payload.point_count} points…"
        )
        self._render_timer.start(0)

    def _handle_payload_failed(self, generation: int, message: str) -> None:
        """Render a preparation failure only when it belongs to the active request."""

        if self._released or generation != self._render_generation:
            return
        self._rendering = False
        self._render_payload = None
        self._reset_plot_widget()
        self._reset_render_surfaces()
        summary = str(message or "Unable to prepare visibility plot.").splitlines()[0]
        self._add_status_placeholder(f"Unable to render visibility plot: {summary}")
        self.render_failed.emit(summary)

    def _handle_payload_canceled(self, generation: int) -> None:
        """Ignore stale cancellation and close the active request quietly."""

        if self._released or generation != self._render_generation:
            return
        self._rendering = False
        self._render_payload = None
        self.render_canceled.emit("Visibility plot preparation canceled.")

    def _forget_plot_worker(self, worker: PrepareVisibilityPlotWorker) -> None:
        """Release a completed worker without touching current render state."""

        self._plot_workers.discard(worker)
        worker.deleteLater()

    def _render_next_slice(self) -> None:
        """Commit plot groups within a bounded GUI-thread time slice."""

        payload = self._render_payload
        generation = self._render_generation
        if self._released or not self._rendering or payload is None:
            return

        deadline = time.perf_counter() + 0.014
        try:
            while self._render_group_index < len(payload.groups):
                if generation != self._render_generation:
                    return
                group = payload.groups[self._render_group_index]
                if self._render_group_offset < group.point_count:
                    end = min(self._render_group_offset + 1024, group.point_count)
                    self._render_identity_data.extend(
                        {
                            "global": int(global_index),
                            "base": int(base_index),
                            "local": int(local_index),
                        }
                        for global_index, base_index, local_index in zip(
                            group.global_indices[self._render_group_offset:end],
                            group.base_indices[self._render_group_offset:end],
                            group.local_indices[self._render_group_offset:end],
                            strict=True,
                        )
                    )
                    self._render_group_offset = end
                    if time.perf_counter() >= deadline:
                        self._render_timer.start(0)
                        return

                self._commit_satellite_group(group, self._render_identity_data)
                self._render_points_committed += group.point_count
                self._render_group_index += 1
                self._render_group_offset = 0
                self._render_identity_data = []
                self.render_progress.emit(
                    "Rendering visibility plot: "
                    f"{self._render_points_committed}/{payload.point_count} points "
                    f"({self._render_group_index}/{payload.satellite_count} satellites)…"
                )
                if time.perf_counter() >= deadline:
                    self._render_timer.start(0)
                    return
        except Exception as exc:
            self._rendering = False
            self._render_payload = None
            self._reset_plot_widget()
            self._reset_render_surfaces()
            self._add_status_placeholder(f"Unable to render visibility plot: {exc}")
            self.render_failed.emit(str(exc) or "Unable to render visibility plot.")
            return

        self._finish_render(payload)

    def _commit_satellite_group(self, group: SelectorPlotGroup, identity_data: list[dict[str, int]]) -> None:
        """Create and attach one pyqtgraph scatter item on the GUI thread."""

        color = self._satellite_color(group.satellite)
        scatter = pg.ScatterPlotItem(
            x=group.x_values,
            y=group.y_values,
            data=identity_data,
            pen=pg.mkPen(None),
            brush=color,
            size=5,
            name=group.satellite,
            hoverable=True,
            hoverSymbol="o",
            hoverSize=8,
            hoverBrush=self._theme_color("error", 120),
        )
        scatter.setToolTip("")
        scatter.sigHovered.connect(lambda points, sat=group.satellite: self._on_hover(points, sat))
        if "tip" in scatter.opts:
            scatter.opts["tip"] = None
        else:
            scatter.hoverEvent = lambda event: None
        self._plot.addItem(scatter)
        self._scatter_items.append(scatter)

    def _finish_render(self, payload: SelectorPlotPayload) -> None:
        """Finalize legends and time markers after the latest render completes."""

        if self._released or not self._rendering or payload is not self._render_payload:
            return
        satellites = [group.satellite for group in payload.groups]
        self._build_highlight_legend()
        self._build_satellite_legend(satellites)
        self.start_time_markers()
        self._rendering = False
        self._render_payload = None
        self.render_succeeded.emit(
            f"Visibility plot ready: {payload.point_count} points across {payload.satellite_count} satellites."
        )

    def _satellite_color(self, satellite: str):
        """Return one GUI-thread pyqtgraph color for a satellite."""

        value = self._satellite_colors.get(str(satellite))
        if isinstance(value, int):
            return pg.intColor(value, hues=max(1, len(self._satellite_colors)))
        return value

    def _add_status_placeholder(self, text: str) -> None:
        """Display a centered plot status message."""

        now = dt.datetime.now(dt.UTC)
        start = dt.datetime(now.year, now.month, now.day, tzinfo=dt.UTC)
        end = start + dt.timedelta(days=1)
        self._plot.setXRange(start.timestamp(), end.timestamp())
        placeholder = pg.TextItem(text=text, color=self._theme_color("muted"), anchor=(0.5, 0.5))
        placeholder.setPos((start.timestamp() + end.timestamp()) / 2, 45)
        self._plot.addItem(placeholder)

    def _add_placeholder(self) -> None:
        now = dt.datetime.now(dt.UTC)
        start = dt.datetime(now.year, now.month, now.day, tzinfo=dt.UTC)
        end = start + dt.timedelta(days=1)
        self._plot.setXRange(start.timestamp(), end.timestamp())
        placeholder = pg.TextItem(text="Load visibility data to plot", color=self._theme_color("muted"), anchor=(0.5, 0.5))
        placeholder.setPos((start.timestamp() + end.timestamp()) / 2, 45)
        self._plot.addItem(placeholder)

    def _on_hover(self, points, satellite: str) -> None:
        if not points or self._data_view.empty:
            QToolTip.hideText()
            return
        try:
            local_row = int(points[0].data().get("local"))
            row = self._data_view.iloc[local_row]
            date_text = str(row[resolve_column(self._data_view, "date_ut")])
            elevation = float(row[resolve_column(self._data_view, "elev")])
            clean_name = "-".join(str(satellite).split("-")[:-2]) if "-ID" in str(satellite) else str(satellite)
            tooltip_lines = [f"🛰️ {clean_name}", f"{date_text} UTC", f"Elev {elevation:.1f}°"]
            phase_col = resolve_column(self._data_view, "solar_phase_angle", required=False)
            if phase_col:
                try:
                    tooltip_lines.append(f"Solar phase {float(row[phase_col]):.1f}°")
                except Exception:
                    pass
            QToolTip.showText(QtGui.QCursor.pos(), "\n".join(tooltip_lines), self)
        except Exception:
            QToolTip.hideText()

    def _on_plot_clicked(self, event) -> None:
        if event.double() or self._data_view.empty:
            return
        mouse_point = self._plot.plotItem.vb.mapSceneToView(event.scenePos())
        local_row = self._nearest_row(mouse_point.x(), mouse_point.y())
        if local_row is None:
            return
        self.point_selected.emit(local_row)
        self.update_selected_highlight(local_row)

    def _nearest_row(self, x_value: float, y_value: float) -> int | None:
        try:
            if self._plot_x_values.size == 0 or self._plot_y_values.size == 0:
                return None
            x_span = float(np.nanmax(self._plot_x_values) - np.nanmin(self._plot_x_values)) or 1.0
            y_span = float(np.nanmax(self._plot_y_values) - np.nanmin(self._plot_y_values)) or 1.0
            distance = ((self._plot_x_values - float(x_value)) / x_span) ** 2 + (
                (self._plot_y_values - float(y_value)) / y_span
            ) ** 2
            nearest = int(np.nanargmin(distance))
            return int(self._plot_local_rows[nearest])
        except Exception:
            return None

    @staticmethod
    def _identity_key(value: object) -> str | None:
        """Return a normalized key for helper row identities."""
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except Exception:
            pass
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return str(value)

    def _record_highlight_key(self, record: ObservationPlanRecord) -> str | None:
        """Return a stable highlight key for a plan record."""
        for identity_column in ("global_index", "base_index", "local_index"):
            key = self._identity_key(getattr(record, identity_column, None))
            if key is not None:
                return f"{identity_column}:{key}"
        if record.satellite is None or record.date_ut is None:
            return None
        return f"sat-time:{record.satellite}|{record.date_ut}"

    def _clear_highlight_dict(self, items_by_key: dict[str, list[object]]) -> None:
        """Remove all highlight items stored in a keyed layer."""
        for items in list(items_by_key.values()):
            self._clear_items(items)

    def _matching_row_for_plan_record(self, record: ObservationPlanRecord) -> pd.Series | None:
        """Return the visible data row matching a plan-table record.

        Matching by satellite and UTC timestamp preserves row identity between
        the plan table and the visibility plot.  The fallback in
        ``update_plan_selection_highlight`` is only used when the selected plan
        row is not currently present in the filtered visibility view.

        Parameters
        ----------
        record : ObservationPlanRecord
            Observation-plan row to locate in the current visibility view.

        Returns
        -------
        pandas.Series or None
            Matching visible row, or `None` if the row is not currently visible.
        """
        if self._data_view.empty:
            return None
        try:
            for identity_column in ("local_index", "base_index", "global_index"):
                key = self._identity_key(getattr(record, identity_column, None))
                if key is None:
                    continue
                row_number = self._identity_row_maps.get(identity_column, {}).get(key)
                if row_number is not None and 0 <= row_number < len(self._data_view):
                    return self._data_view.iloc[int(row_number)]
            satellite_col = resolve_column(self._data_view, "satellite")
            date_col = resolve_column(self._data_view, "date_ut")
            mask = (self._data_view[satellite_col].astype(str) == str(record.satellite)) & (
                self._data_view[date_col].astype(str) == str(record.date_ut)
            )
            matches = self._data_view.loc[mask]
            if matches.empty:
                return None
            return matches.iloc[0]
        except Exception:
            return None

    def _add_highlight_for_row(self, row: pd.Series, *, color, line_style, size: int) -> list[object]:
        try:
            timestamp = float(row[resolve_column(row, "date_ts")])
            elevation = float(row[resolve_column(row, "elev")])
            if not math.isfinite(timestamp) or not math.isfinite(elevation):
                return []
        except Exception:
            return []
        return self._add_highlight(timestamp, elevation, color=color, line_style=line_style, size=size)

    def _add_highlight(self, timestamp: float, elevation: float, *, color, line_style, size: int) -> list[object]:
        line = pg.InfiniteLine(pos=timestamp, angle=90, pen=pg.mkPen(color=color, width=1.5, style=line_style))
        point = pg.ScatterPlotItem([timestamp], [elevation], brush=pg.mkBrush(color), size=size, pen=pg.mkPen(active_theme_palette().plot_background, width=1))
        line.setZValue(30)
        point.setZValue(31)
        self._plot.addItem(line)
        self._plot.addItem(point)
        return [line, point]

    def _clear_items(self, items: list[object]) -> None:
        for item in list(items):
            try:
                self._plot.removeItem(item)
            except Exception:
                pass

    def _build_satellite_legend(self, satellites: list[str]) -> None:
        """Build the donor-style paged satellite legend.

        The standalone selector displays at most ``legend_page_size`` satellites
        and advances pages by clicking a page label.  This implementation keeps
        the same wrapping page behavior and does not affect plotted data.
        """
        if self._satellite_legend is not None:
            try:
                if self._satellite_legend.scene() is self._plot.scene():
                    self._plot.scene().removeItem(self._satellite_legend)
            except Exception:
                pass
        if self._legend_page_label is not None:
            try:
                if self._legend_page_label.scene() is self._plot.scene():
                    self._plot.scene().removeItem(self._legend_page_label)
            except Exception:
                pass

        page_sats, page_index, total_pages = legend_page_slice(
            satellites,
            self._legend_page,
            self._legend_page_size,
        )
        self._legend_page = page_index
        self._satellite_legend = pg.LegendItem(offset=(-10, 10))
        self._satellite_legend.setParentItem(self._plot.graphicsItem())
        for satellite in page_sats:
            color = self._satellite_color(satellite)
            dummy = pg.ScatterPlotItem(pen=None, brush=color, size=8)
            self._satellite_legend.addItem(dummy, satellite)

        page_text = (
            f"<span style='color:{active_theme_palette().focus}; text-decoration:underline; "
            f"cursor:pointer;'>Page {page_index + 1}/{total_pages}</span>"
        )
        self._legend_page_label = pg.LabelItem(page_text)
        self._legend_page_label.setParentItem(self._plot.graphicsItem())
        self._legend_page_label.anchor(itemPos=(1, 0), parentPos=(1, 0))

        def advance_page(event):
            self._legend_page = (self._legend_page + 1) % total_pages
            self._build_satellite_legend(satellites)

        self._legend_page_label.mousePressEvent = advance_page

    def _build_highlight_legend(self) -> None:
        legend = pg.LegendItem(offset=(40, 5))
        legend.setParentItem(self._plot.graphicsItem())
        legend.addItem(pg.ScatterPlotItem(pen=None, brush=pg.mkBrush(self._theme_color("error", 180)), size=8), "Selected")
        legend.addItem(pg.ScatterPlotItem(pen=None, brush=pg.mkBrush(self._theme_color("manual", 180)), size=8), "Checked")
        legend.addItem(pg.ScatterPlotItem(pen=None, brush=pg.mkBrush(self._theme_color("generated", 180)), size=8), "Generated")

    def _ensure_time_items(self) -> None:
        """Create/attach the selector red past region and now marker."""
        now_ts = time.time()
        left = self._time_region_left if self._time_region_left is not None else now_ts - 24 * 3600

        if not hasattr(self, "_time_line"):
            self._time_line = pg.InfiniteLine(pos=now_ts, angle=90, pen=pg.mkPen(self._theme_color("error", 200), width=1.5))
            self._time_line.setZValue(200)
            try:
                self._time_line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self._time_line.setAcceptHoverEvents(False)
            except Exception:
                pass

        if not hasattr(self, "_past_region"):
            self._past_region = pg.LinearRegionItem(values=(left, now_ts))
            self._past_region.setBrush(pg.mkBrush(self._theme_color("error", 90)))
            self._past_region.setZValue(-100)
            self._past_region.setMovable(False)
            try:
                self._past_region.setBounds((left, None))
            except Exception:
                pass
            try:
                self._past_region.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self._past_region.setAcceptHoverEvents(False)
            except Exception:
                pass

        attach_items = now_ts >= left
        if attach_items:
            try:
                self._past_region.setRegion((left, now_ts))
            except Exception:
                pass
            if self._past_region not in self._plot.items():
                self._plot.addItem(self._past_region)
            if self._time_line not in self._plot.items():
                self._plot.addItem(self._time_line)
        else:
            try:
                self._past_region.setRegion((left, left))
            except Exception:
                pass
