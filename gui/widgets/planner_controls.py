"""GUI Observation Planner setup and generation controls."""

from __future__ import annotations

from PyQt6.QtCore import QLocale, Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator, QIntValidator
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.planner_load_button import PlannerLoadButton
from src.observation_planner.coordinate_format import COORD_FORMAT_COLON, COORD_FORMAT_COMPACT
from src.observation_planner.normalize import ALL_SATELLITES_LABEL
from src.observation_planner.preferences import ObservationPlannerPreferences, normalize_mode
from src.observation_planner.sampling import (
    BINNING_EQUAL_WIDTH,
    BINNING_FIXED_WIDTH,
    BINNING_QUANTILE,
    DEFAULT_BIN_WIDTH_DEG,
    MAX_BIN_WIDTH_DEG,
    MIN_BIN_WIDTH_DEG,
    PLAN_METHOD_MAX_ELEVATION,
    PLAN_METHOD_STRATIFIED_ELEVATION,
    PLAN_METHOD_STRATIFIED_SOLAR_PHASE,
)

_NUMERIC_FIELD_WIDTH = 76
_SHORT_COMBO_WIDTH = 150
_MEDIUM_COMBO_WIDTH = 190
_LONG_COMBO_WIDTH = 240
_ACTION_BUTTON_COLUMN_WIDTH = 220
_ACTION_BUTTON_SPACER_WIDTH = 24
_LOAD_INDICATOR_OFFSET = 18


class _IntegerField(QLineEdit):
    """Compact bounded integer line-edit field."""

    def __init__(self, minimum: int, maximum: int, value: int, parent: QWidget | None = None) -> None:
        super().__init__(str(int(value)), parent)
        self._minimum = int(minimum)
        self._maximum = int(maximum)
        self.setValidator(QIntValidator(self._minimum, self._maximum, self))
        self.setMaximumWidth(_NUMERIC_FIELD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def value(self) -> int:
        """Return the current clamped integer value."""
        try:
            value = int(self.text().strip())
        except ValueError:
            value = self._minimum
        return max(self._minimum, min(self._maximum, value))

    def set_value(self, value: int | float) -> None:
        """Set the displayed value after clamping."""
        clamped = max(self._minimum, min(self._maximum, int(round(float(value)))))
        self.setText(str(clamped))


class _FloatField(QLineEdit):
    """Compact bounded floating-point line-edit field."""

    def __init__(
        self,
        minimum: float,
        maximum: float,
        value: float,
        *,
        decimals: int = 1,
        parent: QWidget | None = None,
    ) -> None:
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._decimals = int(decimals)
        super().__init__(self._format(float(value)), parent)
        validator = QDoubleValidator(self._minimum, self._maximum, self._decimals, self)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        validator.setLocale(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
        self.setValidator(validator)
        self.setMaximumWidth(_NUMERIC_FIELD_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def value(self) -> float:
        """Return the current clamped floating-point value."""
        try:
            value = float(self.text().strip())
        except ValueError:
            value = self._minimum
        return max(self._minimum, min(self._maximum, value))

    def set_value(self, value: int | float) -> None:
        """Set the displayed value after clamping."""
        clamped = max(self._minimum, min(self._maximum, float(value)))
        self.setText(self._format(clamped))

    def _format(self, value: float) -> str:
        """Format a floating-point value without unnecessary trailing zeroes."""
        return f"{float(value):.{self._decimals}f}".rstrip("0").rstrip(".") or "0"


class _PlannerControlsSection(QFrame):
    """Compact grouped section used by Observation Planner setup controls."""

    def __init__(self, title: str, parent: QWidget | None = None, *, field_columns: int = 1) -> None:
        super().__init__(parent)
        self.setObjectName("guiPlannerControlsSection")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._field_columns = max(1, min(2, int(field_columns)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title_label = QLabel(title, self)
        title_label.setObjectName("guiCompactCardTitle")
        layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.field_grid = QGridLayout()
        self.field_grid.setContentsMargins(0, 0, 0, 0)
        self.field_grid.setHorizontalSpacing(10)
        self.field_grid.setVerticalSpacing(6)
        for column in range(self._field_columns):
            label_column = column * 2
            field_column = label_column + 1
            self.field_grid.setColumnMinimumWidth(label_column, 124)
            self.field_grid.setColumnStretch(label_column, 0)
            self.field_grid.setColumnStretch(field_column, 1)
        layout.addLayout(self.field_grid)
        layout.addStretch(1)

    def add_field(self, row: int, label_text: str, widget: QWidget, *, column_pair: int = 0) -> None:
        """Add one left-aligned label/widget pair to the section grid."""
        pair = max(0, min(self._field_columns - 1, int(column_pair)))
        label_column = pair * 2
        field_column = label_column + 1
        label = QLabel(label_text, self)
        label.setObjectName("guiFieldLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.field_grid.addWidget(label, row, label_column, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.field_grid.addWidget(widget, row, field_column, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


class _PlannerButtonSection(QFrame):
    """Compact action-card arranging planner buttons in aligned columns."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiPlannerControlsSection")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        title_label = QLabel(title, self)
        title_label.setObjectName("guiCompactCardTitle")
        layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.button_grid = QGridLayout()
        self.button_grid.setObjectName("guiPlannerActionGrid")
        self.button_grid.setContentsMargins(0, 0, 0, 0)
        self.button_grid.setHorizontalSpacing(0)
        self.button_grid.setVerticalSpacing(8)
        self.button_grid.setColumnMinimumWidth(0, _ACTION_BUTTON_COLUMN_WIDTH)
        self.button_grid.setColumnMinimumWidth(1, _ACTION_BUTTON_SPACER_WIDTH)
        self.button_grid.setColumnMinimumWidth(2, _ACTION_BUTTON_COLUMN_WIDTH)
        self.button_grid.setColumnStretch(0, 0)
        self.button_grid.setColumnStretch(1, 1)
        self.button_grid.setColumnStretch(2, 0)
        layout.addLayout(self.button_grid)
        layout.addStretch(1)

    def add_button(self, row: int, column: int, widget: QWidget) -> None:
        """Add an action button to one of two vertically aligned button columns."""
        if row not in {0, 1, 2}:
            raise ValueError(f"Planner action row out of range: {row}")
        if column not in {0, 1}:
            raise ValueError(f"Planner action column out of range: {column}")

        widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        target = widget if isinstance(widget, PlannerLoadButton) else self._wrap_plain_button(widget)
        grid_column = 0 if column == 0 else 2
        self.button_grid.addWidget(target, row, grid_column, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _wrap_plain_button(self, widget: QWidget) -> QWidget:
        """Indent ordinary buttons so they align with load-button text columns."""
        host = QWidget(self)
        host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(_LOAD_INDICATOR_OFFSET, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return host


class PlannerControlsCard(QFrame):
    """Compact planner setup controls mirroring the v1 control surface."""

    loadVisibilityRequested = pyqtSignal()
    loadTleRequested = pyqtSignal()
    loadTargetsRequested = pyqtSignal()
    applyTargetsToggled = pyqtSignal(bool)
    satelliteFilterChanged = pyqtSignal(str)
    generatePlanRequested = pyqtSignal()
    cancelGenerationRequested = pyqtSignal()
    exposureTimeChanged = pyqtSignal(int)
    timeRangeChanged = pyqtSignal(int)
    coordinateFormatChanged = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._preferred_default_mode = "automatic"
        self._build_ui()
        self._connect_signals()
        self._update_binning_control_state()
        self.set_generation_available(False, reason="Load visibility data before plan generation.")
        self.set_tle_available(False)
        self.set_targets_available(False, has_times=False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(9)

        title = QLabel("Observation Planner Controls", self)
        title.setObjectName("guiCardTitle")
        root.addWidget(title)

        self._create_control_widgets()
        self._build_settings_grid(root)

    def _create_control_widgets(self) -> None:
        """Create controls once so grouped cards can arrange them compactly."""
        self.load_visibility_button = PlannerLoadButton("Load Visibility Data", self)
        self.load_tle_button = PlannerLoadButton("Load TLE File", self)
        self.load_targets_button = PlannerLoadButton("Load Targets (JSON)", self)
        self.apply_targets_button = QPushButton("Apply Targets (JSON)", self)
        self.apply_targets_button.setProperty("buttonRole", "primary")
        self.apply_targets_button.setCheckable(True)
        self.generate_button = QPushButton("Generate Plan", self)
        self.generate_button.setProperty("buttonRole", "success")
        self.cancel_generation_button = QPushButton("Cancel", self)
        self.cancel_generation_button.setProperty("buttonRole", "danger")
        self.cancel_generation_button.setEnabled(False)
        for widget in (
            self.load_visibility_button,
            self.load_tle_button,
            self.load_targets_button,
            self.apply_targets_button,
            self.generate_button,
            self.cancel_generation_button,
        ):
            widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.satellite_selector = QComboBox(self)
        self.satellite_selector.addItem(ALL_SATELLITES_LABEL)
        self.satellite_selector.setMinimumWidth(170)
        self.satellite_selector.setMaximumWidth(_LONG_COMBO_WIDTH)

        self.coordinate_format_selector = QComboBox(self)
        self.coordinate_format_selector.addItem("Colon RA/DEC", COORD_FORMAT_COLON)
        self.coordinate_format_selector.addItem("Compact RA/DEC", COORD_FORMAT_COMPACT)
        self.coordinate_format_selector.setMinimumWidth(_SHORT_COMBO_WIDTH)
        self.coordinate_format_selector.setMaximumWidth(_MEDIUM_COMBO_WIDTH)

        self.mode_selector = QComboBox(self)
        self.mode_selector.addItem("Automatic", "automatic")
        self.mode_selector.addItem("JSON times", "json_times")
        self.mode_selector.setMinimumWidth(120)
        self.mode_selector.setMaximumWidth(_SHORT_COMBO_WIDTH)

        self.min_elevation_field = _FloatField(0.0, 90.0, 0.0, decimals=1, parent=self)
        self.exposure_time_field = _IntegerField(0, 3600, 5, self)
        self.time_range_field = _IntegerField(0, 3600, 0, self)
        self.tolerance_field = _IntegerField(0, 3600, 1, self)
        self.spacing_field = _FloatField(0.0, 60.0, 3.0, decimals=1, parent=self)

        self.plan_method_selector = QComboBox(self)
        self.plan_method_selector.addItem("Max Elevation", PLAN_METHOD_MAX_ELEVATION)
        self.plan_method_selector.addItem("Stratified Elevation", PLAN_METHOD_STRATIFIED_ELEVATION)
        self.plan_method_selector.addItem("Stratified Solar Phase", PLAN_METHOD_STRATIFIED_SOLAR_PHASE)
        self.plan_method_selector.setMinimumWidth(_MEDIUM_COMBO_WIDTH)
        self.plan_method_selector.setMaximumWidth(_LONG_COMBO_WIDTH)

        self.binning_mode_selector = QComboBox(self)
        self.binning_mode_selector.addItem("Equal-width", BINNING_EQUAL_WIDTH)
        self.binning_mode_selector.addItem("Quantile", BINNING_QUANTILE)
        self.binning_mode_selector.addItem("Fixed width", BINNING_FIXED_WIDTH)
        self.binning_mode_selector.setMinimumWidth(130)
        self.binning_mode_selector.setMaximumWidth(_MEDIUM_COMBO_WIDTH)

        self.sample_bins_field = _IntegerField(1, 50, 6, self)
        self.bin_width_field = _FloatField(
            MIN_BIN_WIDTH_DEG,
            MAX_BIN_WIDTH_DEG,
            DEFAULT_BIN_WIDTH_DEG,
            decimals=1,
            parent=self,
        )
        self.bin_width_field.setToolTip("Fixed-width bin size in degrees; used only when Binning is Fixed width.")
        self._build_binning_option_stack()

    def _build_binning_option_stack(self) -> None:
        """Create a compact stack that shows only the active bin-size control."""
        self.binning_option_stack = QStackedWidget(self)
        self.binning_option_stack.setObjectName("guiPlannerBinningOptionStack")
        self.binning_option_stack.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.binning_option_stack.setMaximumWidth(220)

        sample_page = QWidget(self.binning_option_stack)
        sample_layout = QHBoxLayout(sample_page)
        sample_layout.setContentsMargins(0, 0, 0, 0)
        sample_layout.setSpacing(8)
        self.sample_bins_label = self._label("Bins")
        sample_layout.addWidget(self.sample_bins_label)
        sample_layout.addWidget(self.sample_bins_field)
        sample_layout.addStretch(1)
        self.binning_option_stack.addWidget(sample_page)

        width_page = QWidget(self.binning_option_stack)
        width_layout = QHBoxLayout(width_page)
        width_layout.setContentsMargins(0, 0, 0, 0)
        width_layout.setSpacing(8)
        self.bin_width_label = self._label("Width [deg]")
        width_layout.addWidget(self.bin_width_label)
        width_layout.addWidget(self.bin_width_field)
        width_layout.addStretch(1)
        self.binning_option_stack.addWidget(width_page)

    def _build_settings_grid(self, root: QVBoxLayout) -> None:
        """Add compact grouped action and settings cards."""
        settings_grid = QGridLayout()
        settings_grid.setContentsMargins(0, 0, 0, 0)
        settings_grid.setHorizontalSpacing(10)
        settings_grid.setVerticalSpacing(10)
        settings_grid.addWidget(self._build_button_card(), 0, 0)
        settings_grid.addWidget(self._build_general_settings_card(), 0, 1)
        settings_grid.addWidget(self._build_planner_settings_card(), 1, 0)
        settings_grid.addWidget(self._build_time_settings_card(), 1, 1)
        settings_grid.setColumnStretch(0, 1)
        settings_grid.setColumnStretch(1, 1)
        root.addLayout(settings_grid)

    def _build_button_card(self) -> _PlannerButtonSection:
        """Build the compact two-column action button card."""
        section = _PlannerButtonSection("Planner Actions", self)
        section.add_button(0, 0, self.load_visibility_button)
        section.add_button(0, 1, self.load_tle_button)
        section.add_button(1, 0, self.load_targets_button)
        section.add_button(1, 1, self.apply_targets_button)
        section.add_button(2, 0, self.generate_button)
        section.add_button(2, 1, self.cancel_generation_button)
        return section

    def _build_general_settings_card(self) -> _PlannerControlsSection:
        """Build satellite/mode/format controls."""
        section = _PlannerControlsSection("General Settings", self)
        section.add_field(0, "Select Satellite", self.satellite_selector)
        section.add_field(1, "Default RA/DEC format", self.coordinate_format_selector)
        section.add_field(2, "Default mode", self.mode_selector)
        return section

    def _build_time_settings_card(self) -> _PlannerControlsSection:
        """Build compact timing and selection-limit controls."""
        section = _PlannerControlsSection("Time Settings", self, field_columns=2)
        section.add_field(0, "Exposure time [sec]", self.exposure_time_field)
        section.add_field(0, "Time range [sec]", self.time_range_field, column_pair=1)
        section.add_field(1, "Min elevation [deg]", self.min_elevation_field)
        section.add_field(1, "Tolerance [sec]", self.tolerance_field, column_pair=1)
        section.add_field(2, "Spacing [min]", self.spacing_field)
        return section

    def _build_planner_settings_card(self) -> _PlannerControlsSection:
        """Build compact method/binning controls."""
        section = _PlannerControlsSection("Planner Settings", self)
        section.add_field(0, "Planner method", self.plan_method_selector)
        section.add_field(1, "Default binning", self.binning_mode_selector)
        section.add_field(2, "Binning option", self.binning_option_stack)
        return section

    @staticmethod
    def _label(label_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("guiFieldLabel")
        return label

    def _connect_signals(self) -> None:
        self.load_visibility_button.clicked.connect(self.loadVisibilityRequested)
        self.load_tle_button.clicked.connect(self.loadTleRequested)
        self.load_targets_button.clicked.connect(self.loadTargetsRequested)
        self.apply_targets_button.toggled.connect(self.applyTargetsToggled)
        self.satellite_selector.currentTextChanged.connect(self.satelliteFilterChanged)
        self.generate_button.clicked.connect(self.generatePlanRequested)
        self.cancel_generation_button.clicked.connect(self.cancelGenerationRequested)
        self.exposure_time_field.textChanged.connect(lambda _: self.exposureTimeChanged.emit(self.exposure_time_field.value()))
        self.time_range_field.textChanged.connect(lambda _: self.timeRangeChanged.emit(self.time_range_field.value()))
        self.binning_mode_selector.currentIndexChanged.connect(self._update_binning_control_state)
        self.coordinate_format_selector.currentIndexChanged.connect(
            lambda _: self.coordinateFormatChanged.emit(self.selected_coordinate_format())
        )

    def apply_preferences(self, preferences: ObservationPlannerPreferences) -> None:
        """Apply persisted Observation Planner runtime defaults to controls."""
        widgets = (
            self.min_elevation_field,
            self.exposure_time_field,
            self.time_range_field,
            self.tolerance_field,
            self.spacing_field,
            self.sample_bins_field,
            self.bin_width_field,
            self.plan_method_selector,
            self.binning_mode_selector,
            self.coordinate_format_selector,
            self.mode_selector,
        )
        previous_block_states = {widget: widget.blockSignals(True) for widget in widgets}
        try:
            self.min_elevation_field.set_value(preferences.min_elevation_deg)
            self.exposure_time_field.set_value(preferences.exposure_time_sec)
            self.time_range_field.set_value(preferences.time_range_sec)
            self.tolerance_field.set_value(preferences.tolerance_sec)
            self.spacing_field.set_value(preferences.spacing_min)
            self.sample_bins_field.set_value(preferences.default_sample_bins)
            self.bin_width_field.set_value(preferences.default_bin_width_deg)
            self._set_combo_by_data(self.plan_method_selector, preferences.default_plan_method)
            self._set_combo_by_data(self.binning_mode_selector, preferences.default_binning_mode)
            self._set_combo_by_data(self.coordinate_format_selector, preferences.default_coordinate_format)
            self._preferred_default_mode = normalize_mode(preferences.default_mode)
            self._apply_default_mode_selection()
        finally:
            for widget, was_blocked in previous_block_states.items():
                widget.blockSignals(was_blocked)
        self._update_binning_control_state()

    def set_exposure_time_seconds(self, seconds: int | float) -> None:
        """Apply a controller-owned exposure-time update without re-emitting."""
        previous = self.exposure_time_field.blockSignals(True)
        try:
            self.exposure_time_field.set_value(seconds)
        finally:
            self.exposure_time_field.blockSignals(previous)

    def _update_binning_control_state(self) -> None:
        mode = self.selected_binning_mode()
        sample_enabled = mode in {BINNING_EQUAL_WIDTH, BINNING_QUANTILE}
        width_enabled = mode == BINNING_FIXED_WIDTH
        self.sample_bins_label.setEnabled(sample_enabled)
        self.sample_bins_field.setEnabled(sample_enabled)
        self.bin_width_label.setEnabled(width_enabled)
        self.bin_width_field.setEnabled(width_enabled)
        self.binning_option_stack.setCurrentIndex(1 if width_enabled else 0)

    @staticmethod
    def _set_combo_by_data(combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if str(combo.itemData(index)) == str(value) or combo.itemText(index) == str(value):
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)

    def selected_plan_method(self) -> str:
        return str(self.plan_method_selector.currentData())

    def selected_binning_mode(self) -> str:
        return str(self.binning_mode_selector.currentData())

    def selected_coordinate_format(self) -> str:
        return str(self.coordinate_format_selector.currentData())

    def selected_sample_bins(self) -> int:
        return self.sample_bins_field.value()

    def selected_bin_width_deg(self) -> float:
        return self.bin_width_field.value()

    def use_json_times(self) -> bool:
        return str(self.mode_selector.currentData()) == "json_times"

    def selected_tolerance_sec(self) -> int:
        return self.tolerance_field.value()

    def selected_spacing_min(self) -> float:
        return self.spacing_field.value()

    def selected_min_elevation(self) -> float:
        return self.min_elevation_field.value()

    def selected_time_range_sec(self) -> int:
        return self.time_range_field.value()

    def set_satellites(self, satellites: list[str]) -> None:
        current = self.satellite_selector.currentText()
        self.satellite_selector.blockSignals(True)
        self.satellite_selector.clear()
        self.satellite_selector.addItem(ALL_SATELLITES_LABEL)
        self.satellite_selector.addItems(sorted(str(sat) for sat in satellites))
        index = self.satellite_selector.findText(current)
        self.satellite_selector.setCurrentIndex(index if index >= 0 else 0)
        self.satellite_selector.blockSignals(False)

    def set_load_state(self, kind: str, state: str, *, detail: str | None = None) -> None:
        buttons = {
            "visibility": self.load_visibility_button,
            "tle": self.load_tle_button,
            "targets": self.load_targets_button,
        }
        button = buttons.get(kind)
        if button is not None:
            button.set_state(state, detail=detail)

    def set_tle_available(self, available: bool) -> None:
        self.load_tle_button.setEnabled(bool(available))
        if available and self.load_tle_button.state == "disabled":
            self.load_tle_button.set_state("idle")

    def set_targets_available(self, available: bool, *, has_times: bool) -> None:
        self.apply_targets_button.setEnabled(available)
        if has_times:
            self.mode_selector.setToolTip("Use times from the loaded JSON target file.")
        else:
            self.mode_selector.setToolTip("Automatic timing is used unless loaded JSON targets contain usable times.")
        self._apply_default_mode_selection()

    def _apply_default_mode_selection(self) -> None:
        self._set_combo_by_data(self.mode_selector, self._preferred_default_mode)

    def set_apply_targets_processing(self) -> None:
        self.apply_targets_button.setEnabled(False)
        self.apply_targets_button.setText("Processing…")

    def set_apply_targets_state(self, checked: bool, *, available: bool = True) -> None:
        self.apply_targets_button.blockSignals(True)
        self.apply_targets_button.setChecked(bool(checked))
        self.apply_targets_button.blockSignals(False)
        self.apply_targets_button.setEnabled(bool(available))
        self.apply_targets_button.setText("Revert Targets" if checked else "Apply Targets (JSON)")

    def set_generation_available(self, available: bool, *, reason: str | None = None) -> None:
        """Enable or disable the plan-generation button."""
        self.generate_button.setEnabled(bool(available))
        self.generate_button.setText("Generate Plan")
        self.generate_button.setToolTip(reason or "Generate an observation plan from the loaded visibility data.")
        self.cancel_generation_button.setEnabled(False)
        self.cancel_generation_button.setToolTip("No plan generation is currently running.")

    def set_generation_processing(self) -> None:
        """Show active generation state and enable cancellation."""
        self.generate_button.setEnabled(False)
        self.generate_button.setText("Generating…")
        self.generate_button.setToolTip("Observation plan generation is running.")
        self.cancel_generation_button.setEnabled(True)
        self.cancel_generation_button.setToolTip("Request cooperative cancellation at the next planner checkpoint.")

    def set_generation_canceling(self) -> None:
        """Show that cancellation has been requested."""
        self.generate_button.setEnabled(False)
        self.generate_button.setText("Canceling…")
        self.generate_button.setToolTip("Waiting for the planner worker to reach a cancellation checkpoint.")
        self.cancel_generation_button.setEnabled(False)
        self.cancel_generation_button.setToolTip("Cancellation has already been requested.")

    def set_generation_state(self, *, ready_for_generation: bool, running: bool, canceling: bool) -> None:
        """Apply generation button state from controller readiness/status."""
        if canceling:
            self.set_generation_canceling()
            return
        if running:
            self.set_generation_processing()
            return
        if ready_for_generation:
            self.set_generation_available(True)
            return
        self.set_generation_available(False, reason="Load visibility data before plan generation.")


__all__ = ("PlannerControlsCard",)
