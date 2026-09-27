"""TLE and satellite-selection card for GUI overpass setup."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStyle,
    QWidget,
)

_CONSTELLATION_PLACEHOLDER = "Select Constellation"
_SATELLITE_LIST_MINIMUM_ROWS = 4


def _filter_satellites(
    satellites: list[dict[str, object]],
    query: str,
) -> list[dict[str, object]]:
    """Filter satellites by numeric range or case-insensitive name match.

    Parameters
    ----------
    satellites : list of dict[str, object]
        Satellite dictionaries containing at least a ``name`` field.
    query : str
        Filter text entered by the user. A two-sided numeric range such as
        ``1000-3500`` matches satellites whose digit-only name component falls
        within the inclusive range. Non-range input falls back to
        case-insensitive substring matching.

    Returns
    -------
    list of dict[str, object]
        Filtered satellite dictionaries in their original order.
    """
    normalized_query = query.strip()
    if not normalized_query:
        return list(satellites)

    if "-" in normalized_query:
        range_parts = [part.strip() for part in normalized_query.split("-", 1)]
        if len(range_parts) == 2 and range_parts[0].isdigit() and range_parts[1].isdigit():
            low = int(range_parts[0])
            high = int(range_parts[1])
            if low > high:
                low, high = high, low

            filtered: list[dict[str, object]] = []
            for satellite in satellites:
                name_digits = "".join(
                    character for character in str(satellite.get("name", "")) if character.isdigit()
                )
                if name_digits and low <= int(name_digits) <= high:
                    filtered.append(satellite)
            return filtered

    lowered_query = normalized_query.lower()
    return [
        satellite
        for satellite in satellites
        if lowered_query in str(satellite.get("name", "")).lower()
    ]

from gui.styles import repolish
from gui.styles.effects import apply_card_elevation
from gui.styles.icon_provider import set_themed_icon
from gui.widgets.toggle_switch import ToggleSwitch

LogCallback = Callable[[str, str], None]


class TleServiceProtocol(Protocol):
    """Structural TLE-service protocol consumed by the GUI card."""

    def list_constellations(self) -> list[str]: ...

    def fetch_or_load_constellation(
        self,
        constellation: str,
        *,
        force_download: bool = False,
        default_only: bool = False,
    ) -> tuple[list[dict[str, object]], Path]: ...


class TleSelectionCard(QFrame):
    """TLE selection card backed by the shared ``TleService``.

    The layout mirrors the legacy TLE-selection grid where possible without
    reusing parent-coupled legacy widgets.  Fetching and filtering remain local
    to this card; readiness decisions are centralized in ``OverpassSetupPage``.
    """

    stateChanged = pyqtSignal()

    def __init__(
        self,
        *,
        tle_service: TleServiceProtocol,
        log_callback: LogCallback | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tle_service = tle_service
        self._log_callback = log_callback
        self._satellites: list[dict[str, object]] = []
        self._visible_satellites: list[dict[str, object]] = []
        self._last_source_file: Path | None = None
        self._selection_confirmed = False

        self.setObjectName("guiCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        apply_card_elevation(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        grid = QGridLayout(self)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(_style_spacing(self, QStyle.PixelMetric.PM_LayoutHorizontalSpacing))
        grid.setVerticalSpacing(_style_spacing(self, QStyle.PixelMetric.PM_LayoutVerticalSpacing))

        title = QLabel("TLE Selection", self)
        title.setObjectName("guiCardTitle")
        grid.addWidget(title, 0, 0, 1, 4)

        self.constellation_combo = QComboBox(self)
        self.constellation_combo.setObjectName("guiTleConstellationCombo")
        self.constellation_combo.setMinimumContentsLength(20)
        self.constellation_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.constellation_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.fetch_button = QPushButton("Fetch TLE", self)
        self.fetch_button.setObjectName("guiTleFetchButton")
        self.fetch_button.setProperty("buttonRole", "primary")
        self.fetch_button.setEnabled(False)
        self._configure_command_button(self.fetch_button)

        self.filter_edit = QLineEdit(self)
        self.filter_edit.setObjectName("guiTleFilterEdit")
        self.filter_edit.setPlaceholderText("e.g. 1000-3500 or ONEWEB-0101")
        self.filter_edit.setEnabled(False)
        self.filter_edit.setMinimumWidth(0)
        self.filter_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.apply_filter_button = QPushButton("Apply Filter", self)
        self.apply_filter_button.setObjectName("guiTleApplyFilterButton")
        self.apply_filter_button.setProperty("buttonRole", "primary")
        set_themed_icon(self.apply_filter_button, "search", size=16)
        self.apply_filter_button.setEnabled(False)
        self._configure_command_button(self.apply_filter_button)
        self.clear_filter_button = QPushButton("Clear Filter", self)
        self.clear_filter_button.setObjectName("guiTleClearFilterButton")
        self.clear_filter_button.setProperty("buttonRole", "secondary")
        self.clear_filter_button.setEnabled(False)
        self._configure_command_button(self.clear_filter_button)

        self.satellite_list = QListWidget(self)
        self.satellite_list.setObjectName("guiTleSatelliteList")
        self.satellite_list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.satellite_list.setMinimumHeight(self._satellite_list_minimum_height())
        self.satellite_list.setMinimumWidth(0)
        self.satellite_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.confirm_button = QPushButton("Confirm", self)
        self.confirm_button.setObjectName("guiTleConfirmButton")
        self.confirm_button.setProperty("buttonRole", "success")
        self._configure_command_button(self.confirm_button)
        self.reset_button = QPushButton("Reset", self)
        self.reset_button.setObjectName("guiTleResetButton")
        self.reset_button.setProperty("buttonRole", "secondary")
        self._configure_command_button(self.reset_button)
        self.select_all_checkbox = ToggleSwitch("Select All", self)
        self.select_all_checkbox.setObjectName("guiTleSelectAllCheck")
        self.select_all_checkbox.setEnabled(False)
        self.defaults_only_check = ToggleSwitch("Show Defaults Only", self)
        self.defaults_only_check.setObjectName("guiTleDefaultsOnlyCheck")

        self.selected_name_edit = QLineEdit(self)
        self.selected_name_edit.setObjectName("guiTleSelectedNameEdit")
        self.tle_line1_edit = QLineEdit(self)
        self.tle_line1_edit.setObjectName("guiTleLine1Edit")
        self.tle_line2_edit = QLineEdit(self)
        self.tle_line2_edit.setObjectName("guiTleLine2Edit")
        for edit in (self.selected_name_edit, self.tle_line1_edit, self.tle_line2_edit):
            edit.setReadOnly(True)
            edit.setMinimumHeight(edit.sizeHint().height())
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.summary_label = QLabel("No TLE data loaded yet.", self)
        self.summary_label.setObjectName("guiCardBody")
        self.summary_label.setWordWrap(True)
        self.summary_label.setMinimumHeight(self.summary_label.sizeHint().height())
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._add_label(grid, 1, 0, "Constellation:")
        grid.addWidget(self.constellation_combo, 1, 1)
        grid.addWidget(self.fetch_button, 1, 2)

        self._add_label(grid, 2, 0, "Filter Satellites:")
        grid.addWidget(self.filter_edit, 2, 1)
        grid.addWidget(self.apply_filter_button, 2, 2)
        grid.addWidget(self.clear_filter_button, 2, 3)

        self._add_label(grid, 3, 0, "Select Satellite:")
        grid.addWidget(self.satellite_list, 3, 1, 4, 1)
        grid.addWidget(self.confirm_button, 3, 2)
        grid.addWidget(self.reset_button, 3, 3)
        grid.addWidget(self.select_all_checkbox, 4, 2, 1, 2)
        grid.addWidget(self.defaults_only_check, 5, 2, 1, 2)

        self._add_label(grid, 7, 0, "Satellite Name:")
        grid.addWidget(self.selected_name_edit, 7, 1, 1, 3)
        self._add_label(grid, 8, 0, "TLE Line 1:")
        grid.addWidget(self.tle_line1_edit, 8, 1, 1, 3)
        self._add_label(grid, 9, 0, "TLE Line 2:")
        grid.addWidget(self.tle_line2_edit, 9, 1, 1, 3)
        grid.addWidget(self.summary_label, 10, 0, 1, 4)

        grid.setColumnStretch(0, 0)
        grid.setColumnMinimumWidth(2, max(self.fetch_button.sizeHint().width(), self.confirm_button.sizeHint().width()))
        grid.setColumnMinimumWidth(3, max(self.clear_filter_button.sizeHint().width(), self.reset_button.sizeHint().width()))
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 0)
        for row in (1, 2, 7, 8, 9):
            grid.setRowMinimumHeight(row, self.selected_name_edit.sizeHint().height())
        for row in range(1, 11):
            grid.setRowStretch(row, 0)
        for row in (3, 4, 5, 6):
            grid.setRowStretch(row, 1)

        self._set_control_size_hints()

        self.fetch_button.clicked.connect(lambda: self._fetch_tles(force_download=True))
        self.constellation_combo.currentIndexChanged.connect(lambda: self._fetch_tles(force_download=False))
        self.defaults_only_check.stateChanged.connect(lambda: self._fetch_tles(force_download=False))
        self.apply_filter_button.clicked.connect(self._apply_filter)
        self.clear_filter_button.clicked.connect(self._clear_filter)
        self.filter_edit.returnPressed.connect(self._apply_filter)
        self.satellite_list.itemSelectionChanged.connect(self._handle_selection_changed)
        self.confirm_button.clicked.connect(self._confirm_selection)
        self.reset_button.clicked.connect(self._reset_selection)
        self.select_all_checkbox.stateChanged.connect(self._toggle_select_all)

        self._populate_constellations()
        self._set_tle_fields_for_empty_selection()

    @staticmethod
    def _configure_command_button(button: QPushButton) -> None:
        """Keep TLE command buttons compact using their style-derived hints."""
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def _set_control_size_hints(self) -> None:
        """Apply style-derived local control minimum heights."""
        for widget in (
            self.constellation_combo,
            self.filter_edit,
            self.fetch_button,
            self.apply_filter_button,
            self.clear_filter_button,
            self.confirm_button,
            self.reset_button,
        ):
            widget.setMinimumHeight(widget.sizeHint().height())

    def _satellite_list_minimum_height(self) -> int:
        """Return a style-aware minimum height for the satellite list."""
        row_height = self.satellite_list.fontMetrics().lineSpacing()
        frame_width = self.satellite_list.style().pixelMetric(
            QStyle.PixelMetric.PM_DefaultFrameWidth,
            None,
            self.satellite_list,
        )
        spacing = _style_spacing(self.satellite_list, QStyle.PixelMetric.PM_LayoutVerticalSpacing)
        return row_height * _SATELLITE_LIST_MINIMUM_ROWS + 2 * frame_width + spacing

    def current_constellation(self) -> str:
        """Return the service-facing constellation identifier."""
        constellation_data = self.constellation_combo.currentData()
        return str(constellation_data).strip() if constellation_data else ""

    def selected_satellites(self) -> list[dict[str, object]]:
        """Return selected satellite dictionaries using the v1 selection semantics."""
        if self.select_all_checkbox.isChecked():
            return list(self._satellites)
        selected: list[dict[str, object]] = []
        for item in self.satellite_list.selectedItems():
            data = item.data(1)
            if isinstance(data, dict):
                selected.append(data)
        return selected

    def validation_snapshot(self) -> dict[str, object]:
        """Return raw TLE/selection values consumed by central validation."""
        return {
            "constellation": self.current_constellation(),
            "loaded_satellite_count": len(self._satellites),
            "selected_satellite_count": len(self.selected_satellites()),
            "selection_confirmed": self._selection_confirmed,
            "source_file": str(self._last_source_file) if self._last_source_file else "",
        }


    def set_tle_service(self, tle_service: TleServiceProtocol, *, preserve_loaded_data: bool = True) -> bool:
        """Replace the backing TLE service for future operations.

        Loaded TLE data and confirmed selections are preserved by default.  If
        no TLE data is currently loaded, the constellation list is refreshed
        immediately from the new service.
        """
        self._tle_service = tle_service
        if preserve_loaded_data and self._satellites:
            self.summary_label.setText(
                "TLE preferences updated for future loads. Current loaded TLE data and selection were preserved."
            )
            self._log("TLE service refreshed; current loaded TLE data preserved.", "INFO")
            return False

        self._clear_loaded_tles("TLE preferences updated. Select a constellation to load data.", emit_state=False)
        self._populate_constellations()
        self._log("TLE service refreshed and constellation list reloaded.", "INFO")
        self.stateChanged.emit()
        return True

    def set_field_validity(self, field_id: str, valid: bool, message: str = "") -> None:
        """Apply validation styling for TLE selection controls."""
        if field_id == "tle.constellation":
            _set_validation_state(self.constellation_combo, "valid" if valid else "error", message)
        elif field_id in {"tle.loaded", "tle.selection"}:
            _set_validation_state(self.satellite_list, "valid" if valid else "error", message)

    def _add_label(self, grid: QGridLayout, row: int, column: int, text: str) -> None:
        label = QLabel(text, self)
        label.setObjectName("guiFieldLabel")
        grid.addWidget(label, row, column)

    def _set_selection_controls_enabled(self, enabled: bool) -> None:
        """Enable or freeze selection controls after confirmation/reset."""
        has_satellites = bool(self._satellites)
        self.satellite_list.setEnabled(enabled and has_satellites)
        self.confirm_button.setEnabled(enabled and has_satellites)
        self.defaults_only_check.setEnabled(enabled)
        self.select_all_checkbox.setEnabled(enabled and has_satellites)
        self.filter_edit.setEnabled(enabled and has_satellites)
        self.apply_filter_button.setEnabled(enabled and has_satellites)
        self.clear_filter_button.setEnabled(
            enabled and has_satellites and bool(self.filter_edit.text().strip())
        )

    def has_confirmed_selection(self) -> bool:
        """Return whether the current visible selection was explicitly confirmed."""
        return self._selection_confirmed

    def _populate_constellations(self) -> None:
        blocker = QSignalBlocker(self.constellation_combo)
        try:
            self.constellation_combo.clear()
            self.constellation_combo.addItem(_CONSTELLATION_PLACEHOLDER, "")
            try:
                constellations = self._tle_service.list_constellations()
            except Exception as exc:  # pragma: no cover - defensive service guard
                self.summary_label.setText(f"Unable to list TLE constellations: {exc}")
                self._log(f"Unable to list TLE constellations: {exc}", "ERROR")
                constellations = []
            for constellation in constellations:
                self.constellation_combo.addItem(str(constellation).upper(), constellation)
        finally:
            del blocker
        self.fetch_button.setEnabled(self.constellation_combo.count() > 1)
        self._log(f"Loaded {max(0, self.constellation_combo.count() - 1)} TLE constellation option(s).", "INFO")
        self.stateChanged.emit()

    def _fetch_tles(self, *, force_download: bool) -> None:
        constellation = self.current_constellation()
        if not constellation:
            self._clear_loaded_tles("Select a constellation before fetching TLE data.", emit_state=True)
            return
        try:
            satellites, source_path = self._tle_service.fetch_or_load_constellation(
                constellation,
                force_download=force_download,
                default_only=self.defaults_only_check.isChecked(),
            )
        except Exception as exc:  # pragma: no cover - network/file guard
            self._clear_loaded_tles(f"Unable to load TLE data: {exc}", emit_state=True)
            self._log(f"Unable to load TLE data for {constellation}: {exc}", "ERROR")
            return

        list_blocker = QSignalBlocker(self.satellite_list)
        select_all_blocker = QSignalBlocker(self.select_all_checkbox)
        try:
            self._selection_confirmed = False
            self._last_source_file = Path(source_path)
            self._satellites = list(satellites)
            self._visible_satellites = list(satellites)
            self.select_all_checkbox.setChecked(False)
            self._populate_satellite_list(self._visible_satellites)
            self._set_selection_controls_enabled(True)
            self.clear_filter_button.setEnabled(False)
        finally:
            del select_all_blocker
            del list_blocker
        self.summary_label.setText(
            f"Loaded {len(self._satellites)} satellite(s) from {self._last_source_file.name}. "
            "Select at least one satellite to enable readiness."
        )
        self._log(
            f"TLE data loaded for {constellation}: {len(self._satellites)} satellite(s) from {self._last_source_file}.",
            "INFO",
        )
        self.stateChanged.emit()

    def _populate_satellite_list(self, satellites: list[dict[str, object]]) -> None:
        self.satellite_list.clear()
        if not satellites:
            self._set_tle_fields_for_empty_selection()
            return
        for satellite in satellites:
            name = str(satellite.get("name", "Unnamed satellite"))
            item = QListWidgetItem(name)
            item.setData(1, satellite)
            self.satellite_list.addItem(item)
        self._set_tle_fields_for_empty_selection()

    def _apply_filter(self) -> None:
        query = self.filter_edit.text().strip()
        list_blocker = QSignalBlocker(self.satellite_list)
        select_all_blocker = QSignalBlocker(self.select_all_checkbox)
        try:
            self._selection_confirmed = False
            self._visible_satellites = _filter_satellites(self._satellites, query)
            self.select_all_checkbox.setChecked(False)
            self._populate_satellite_list(self._visible_satellites)
        finally:
            del select_all_blocker
            del list_blocker
        self.clear_filter_button.setEnabled(bool(query))
        self.summary_label.setText(f"Filter shows {len(self._visible_satellites)} of {len(self._satellites)} satellite(s).")
        self._log(f"Satellite filter applied: {len(self._visible_satellites)} visible satellite(s).", "INFO")
        self.stateChanged.emit()

    def _clear_filter(self) -> None:


        self._selection_confirmed = False
        self.filter_edit.clear()
        self._visible_satellites = list(self._satellites)
        self.select_all_checkbox.setChecked(False)
        self._populate_satellite_list(self._visible_satellites)

        self.clear_filter_button.setEnabled(False)
        self.summary_label.setText(f"Filter cleared. {len(self._visible_satellites)} satellite(s) visible.")
        self._log("Satellite filter cleared.", "INFO")
        self.stateChanged.emit()

    def _toggle_select_all(self) -> None:
        self._selection_confirmed = False
        checked = self.select_all_checkbox.isChecked()
        if checked:
            for index in range(self.satellite_list.count()):
                self.satellite_list.item(index).setSelected(False)
        self._update_selected_fields()
        self.stateChanged.emit()

    def _reset_selection(self) -> None:

        self._selection_confirmed = False
        self.select_all_checkbox.setChecked(False)
        for index in range(self.satellite_list.count()):
            self.satellite_list.item(index).setSelected(False)
        self._set_tle_fields_for_empty_selection()
        self._set_selection_controls_enabled(True)

        self.summary_label.setText("Satellite selection reset.")
        self._log("Satellite selection reset.", "INFO")
        self.stateChanged.emit()

    def _confirm_selection(self) -> None:
        count = len(self.selected_satellites())
        if count == 0:
            # self.summary_label.setText("No satellites selected yet. Select at least one satellite.")
            self._log("No satellites selected.", "WARNING")
            self.stateChanged.emit()
            return
        self._selection_confirmed = True
        self._set_selection_controls_enabled(False)
        # self.summary_label.setText(f"{count} satellite(s) confirmed for overpass validation.")
        self._log(f"Satellite selection confirmed: {count} satellite(s).", "INFO")
        self.stateChanged.emit()

    def _handle_selection_changed(self) -> None:
        self._selection_confirmed = False
        self._update_selected_fields()
        self.stateChanged.emit()

    def _update_selected_fields(self) -> None:
        if self.select_all_checkbox.isChecked():
            count = len(self._satellites)
            self.selected_name_edit.setText(f"All satellites selected ({count})")
            self.tle_line1_edit.setText("Multiple satellites selected")
            self.tle_line2_edit.setText("Multiple satellites selected")
            return
        selected = self.selected_satellites()
        if len(selected) == 1:
            satellite = selected[0]
            self.selected_name_edit.setText(str(satellite.get("name", "")))
            self.tle_line1_edit.setText(str(satellite.get("tle1", "")))
            self.tle_line2_edit.setText(str(satellite.get("tle2", "")))
            return
        if len(selected) > 1:
            self.selected_name_edit.setText(f"{len(selected)} satellites selected")
            self.tle_line1_edit.setText("Multiple satellites selected")
            self.tle_line2_edit.setText("Multiple satellites selected")
            return
        self._set_tle_fields_for_empty_selection()

    def _set_tle_fields_for_empty_selection(self) -> None:
        self.selected_name_edit.setText("Select Satellite")
        self.tle_line1_edit.clear()
        self.tle_line2_edit.clear()

    def _clear_loaded_tles(self, message: str, *, emit_state: bool = False) -> None:

        self._selection_confirmed = False
        self._last_source_file = None
        self._satellites = []
        self._visible_satellites = []
        self.satellite_list.clear()
        self.select_all_checkbox.setChecked(False)
        self.filter_edit.clear()
        self.filter_edit.setEnabled(False)
        self.filter_edit.setMinimumWidth(0)
        self.filter_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.apply_filter_button.setEnabled(False)
        self.clear_filter_button.setEnabled(False)
        self.select_all_checkbox.setEnabled(False)
        self.confirm_button.setEnabled(False)
        self.satellite_list.setEnabled(False)
        self.summary_label.setText(message)
        self._set_tle_fields_for_empty_selection()

        if emit_state:
            self.stateChanged.emit()

    def _log(self, message: str, level: str = "INFO") -> None:
        if self._log_callback is not None:
            self._log_callback(message, level)


def _style_spacing(widget: QWidget, metric: QStyle.PixelMetric) -> int:
    """Return style-provided layout spacing with a font-derived fallback."""
    spacing = widget.style().pixelMetric(metric, None, widget)
    if spacing >= 0:
        return spacing
    return max(1, widget.fontMetrics().lineSpacing() // 3)


def _set_validation_state(widget: QWidget, state: str, tooltip: str = "") -> None:
    widget.setProperty("validationState", state)
    widget.setToolTip(tooltip)
    repolish(widget)
