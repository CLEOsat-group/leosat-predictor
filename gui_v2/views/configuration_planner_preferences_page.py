"""Editable GUI-v2 Observation Planner preference page."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QWidget,
)

from src.observation_planner.coordinate_format import COORD_FORMAT_COLON, COORD_FORMAT_COMPACT
from src.observation_planner.preferences import from_preferences_dict, to_preferences_dict
from src.observation_planner.sampling import (
    BINNING_CUSTOM_EDGES,
    BINNING_EQUAL_WIDTH,
    BINNING_FIXED_WIDTH,
    BINNING_QUANTILE,
    DEFAULT_BIN_WIDTH_DEG,
    DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT,
    DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT,
    DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS,
    MAX_BIN_WIDTH_DEG,
    MAX_CANDIDATE_DEPTH,
    MAX_OPTIMIZATION_TRIALS,
    MIN_BIN_WIDTH_DEG,
    OPTIMIZATION_OBJECTIVE_QUALITY,
    OPTIMIZATION_OBJECTIVE_SLEW_AWARE,
    PLAN_METHOD_MAX_ELEVATION,
    PLAN_METHOD_STRATIFIED_ELEVATION,
    PLAN_METHOD_STRATIFIED_SOLAR_PHASE,
)
from src.observation_planner.slew_diagnostics import (
    MAX_SLEW_OVERHEAD_SEC,
    MAX_SLEW_RATE_DEG_PER_SEC,
    MAX_TRANSITION_SAMPLE_LIMIT,
    MIN_SLEW_RATE_DEG_PER_SEC,
    MIN_TRANSITION_SAMPLE_LIMIT,
)
from src.observation_planner.transition_constraints import (
    MAX_TRANSITION_SAFETY_MARGIN_SEC,
    TRANSITION_CONSTRAINT_PHYSICAL,
    TRANSITION_CONSTRAINT_TIME_SPACING,
)

from ..services import PreferencesService
from ..shell.navigation_model import NavigationNode
from ..widgets.planner_column_mapping_table import PlannerColumnMappingTable
from ..widgets.toggle_switch import ToggleSwitch
from .configuration_base import (
    ConfigurationCard,
    ConfigurationPageBase,
    create_float_input,
    create_integer_input,
    parse_float_input,
    parse_integer_input,
    set_compact_field_width,
)

_PLANNER_NUMERIC_FIELD_WIDTH = 76
_PLANNER_MODE_FIELD_WIDTH = 132
_PLANNER_COMBO_FIELD_WIDTH = 220
_PLANNER_FILENAME_FIELD_WIDTH = 300
_CARD_COLUMNS = 2



class ConfigurationPlannerPreferencesPage(ConfigurationPageBase):
    """Edit non-diagnostics Observation Planner preferences."""

    def __init__(self, *, page: NavigationNode, preferences_service: PreferencesService, parent: QWidget | None = None) -> None:
        super().__init__(page=page, preferences_service=preferences_service, parent=parent)
        self._build_tabbed_editor()
        self.load_from_service()

    def _build_tabbed_editor(self) -> None:
        """Create a compact tabbed planner-preferences editor."""
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("guiV2PlannerPreferencesTabs")
        self.tabs.setProperty("visualRole", "workspaceTabs")
        self.tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.tabs.setDocumentMode(True)

        general_tab, general_grid = self._create_scroll_tab("guiV2PlannerPreferencesGeneralTab")
        self._build_general_tab(general_grid)
        self.tabs.addTab(general_tab, "General")

        diagnostics_tab, diagnostics_grid = self._create_scroll_tab("guiV2PlannerPreferencesDiagnosticsTab")
        self._build_diagnostics_tab(diagnostics_grid)
        self.tabs.addTab(diagnostics_tab, "Diagnostics")

        columns_tab, columns_grid = self._create_scroll_tab("guiV2PlannerPreferencesColumnsTab")
        self._build_columns_tab(columns_grid)
        self.tabs.addTab(columns_tab, "Visibility Table Columns")

        self.content_layout.addWidget(self.tabs, 1)

    def _create_scroll_tab(self, object_name: str) -> tuple[QScrollArea, QGridLayout]:
        """Return a scrollable tab page and its two-column card grid."""
        scroll_area = QScrollArea(self.tabs)
        scroll_area.setObjectName(object_name)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)

        content = QWidget(scroll_area)
        content.setObjectName(f"{object_name}Content")
        grid = QGridLayout(content)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for column in range(_CARD_COLUMNS):
            grid.setColumnStretch(column, 1)
        scroll_area.setWidget(content)
        return scroll_area, grid

    @staticmethod
    def _new_field_grid() -> QGridLayout:
        """Create a compact left-aligned field grid for a sub-card."""
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        grid.setColumnMinimumWidth(0, 155)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        return grid

    @staticmethod
    def _new_two_column_field_grid() -> QGridLayout:
        """Create a compact two-column field grid for dense planner defaults."""
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(7)
        grid.setColumnMinimumWidth(0, 145)
        grid.setColumnMinimumWidth(2, 145)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 1)
        return grid

    @staticmethod
    def _add_field(grid: QGridLayout, row: int, label: str, widget: QWidget) -> None:
        """Add one left-aligned labeled configuration field."""
        label_widget = QLabel(label)
        label_widget.setObjectName("guiV2FieldLabel")
        label_widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        grid.addWidget(label_widget, row, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(widget, row, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    @staticmethod
    def _add_field_at(grid: QGridLayout, row: int, column: int, label: str, widget: QWidget) -> None:
        """Add one labeled field into a specific label/widget column pair."""
        label_widget = QLabel(label)
        label_widget.setObjectName("guiV2FieldLabel")
        label_widget.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        label_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        grid.addWidget(label_widget, row, column, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(widget, row, column + 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    @staticmethod
    def _add_checkbox(grid: QGridLayout, row: int, checkbox: QCheckBox) -> None:
        """Add a full-row checkbox without stretching it across the card."""
        grid.addWidget(checkbox, row, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    @staticmethod
    def _add_card(grid: QGridLayout, card: ConfigurationCard, *, row: int, column: int, column_span: int = 1) -> None:
        """Add a sub-card to the tab grid."""
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        grid.addWidget(card, row, column, 1, column_span)

    @staticmethod
    def _attach_field_grid(card: ConfigurationCard, field_grid: QGridLayout) -> None:
        """Attach a compact form grid to a card without vertical centering.

        ``QGridLayout`` can distribute excess vertical space across its rows
        when it is placed directly into a taller card.  Wrapping the grid in a
        maximum-height host keeps short forms pinned directly below the card
        title and leaves any excess row height at the card bottom.
        """
        field_host = QWidget(card)
        field_host.setObjectName("guiV2PlannerPreferenceFieldHost")
        field_host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        field_host.setLayout(field_grid)
        card.layout.addWidget(field_host, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        card.layout.addStretch(1)

    @staticmethod
    def _set_numeric_width(widget: QWidget) -> None:
        """Constrain numeric fields to the expected compact planner width."""
        set_compact_field_width(widget, width=_PLANNER_NUMERIC_FIELD_WIDTH)

    def _build_general_tab(self, grid: QGridLayout) -> None:
        """Create the General tab using compact planner-default cards."""
        output_card = ConfigurationCard(title="Output and display", parent=self)
        output_grid = self._new_field_grid()
        self.filename_pattern_edit = QLineEdit(output_card)
        self.filename_pattern_edit.setObjectName("guiV2PlannerPreference_filename_pattern")
        set_compact_field_width(self.filename_pattern_edit, width=_PLANNER_FILENAME_FIELD_WIDTH)
        self.legend_page_size_edit = create_integer_input(
            parent=output_card,
            object_name="guiV2PlannerPreference_legend_page_size",
            minimum=1,
            maximum=50,
            default=5,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.coordinate_format_combo = QComboBox(output_card)
        self.coordinate_format_combo.setObjectName("guiV2PlannerPreference_default_coordinate_format")
        self.coordinate_format_combo.addItem("Colon RA/DEC", COORD_FORMAT_COLON)
        self.coordinate_format_combo.addItem("Compact RA/DEC", COORD_FORMAT_COMPACT)
        set_compact_field_width(self.coordinate_format_combo, width=_PLANNER_COMBO_FIELD_WIDTH)
        self._add_field(output_grid, 0, "Default plan filename", self.filename_pattern_edit)
        self._add_field(output_grid, 1, "Legend page size", self.legend_page_size_edit)
        self._add_field(output_grid, 2, "Default RA/DEC format", self.coordinate_format_combo)
        self._attach_field_grid(output_card, output_grid)
        self._add_card(grid, output_card, row=0, column=0)

        timing_card = ConfigurationCard(title="Timing and selection limits", parent=self)
        timing_grid = self._new_two_column_field_grid()
        self.exposure_time_edit = create_float_input(
            parent=timing_card,
            object_name="guiV2PlannerPreference_exposure_time_sec",
            minimum=0.1,
            maximum=3600.0,
            decimals=2,
            default=5.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.time_range_edit = create_float_input(
            parent=timing_card,
            object_name="guiV2PlannerPreference_time_range_sec",
            minimum=0.0,
            maximum=3600.0,
            decimals=2,
            default=0.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.min_elevation_edit = create_float_input(
            parent=timing_card,
            object_name="guiV2PlannerPreference_min_elevation_deg",
            minimum=-90.0,
            maximum=90.0,
            decimals=2,
            default=0.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.tolerance_edit = create_float_input(
            parent=timing_card,
            object_name="guiV2PlannerPreference_tolerance_sec",
            minimum=0.0,
            maximum=3600.0,
            decimals=2,
            default=1.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.spacing_edit = create_float_input(
            parent=timing_card,
            object_name="guiV2PlannerPreference_spacing_min",
            minimum=0.1,
            maximum=60.0,
            decimals=2,
            default=3.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self._add_field_at(timing_grid, 0, 0, "Exposure time [s]", self.exposure_time_edit)
        self._add_field_at(timing_grid, 1, 0, "Time range [s]", self.time_range_edit)
        self._add_field_at(timing_grid, 2, 0, "Min elevation [deg]", self.min_elevation_edit)
        self._add_field_at(timing_grid, 0, 2, "Tolerance [s]", self.tolerance_edit)
        self._add_field_at(timing_grid, 1, 2, "Spacing [min]", self.spacing_edit)
        self._attach_field_grid(timing_card, timing_grid)
        self._add_card(grid, timing_card, row=0, column=1)

        method_card = ConfigurationCard(title="Planner method", parent=self)
        method_grid = self._new_field_grid()
        self.default_mode_combo = QComboBox(method_card)
        self.default_mode_combo.setObjectName("guiV2PlannerPreference_default_mode")
        self.default_mode_combo.addItems(("automatic", "json_times"))
        set_compact_field_width(self.default_mode_combo, width=_PLANNER_MODE_FIELD_WIDTH)
        self.plan_method_combo = QComboBox(method_card)
        self.plan_method_combo.setObjectName("guiV2PlannerPreference_default_plan_method")
        self.plan_method_combo.addItem("Max Elevation", PLAN_METHOD_MAX_ELEVATION)
        self.plan_method_combo.addItem("Stratified Elevation Sample", PLAN_METHOD_STRATIFIED_ELEVATION)
        self.plan_method_combo.addItem("Stratified Solar Phase Sample", PLAN_METHOD_STRATIFIED_SOLAR_PHASE)
        set_compact_field_width(self.plan_method_combo, width=_PLANNER_COMBO_FIELD_WIDTH)
        self.binning_mode_combo = QComboBox(method_card)
        self.binning_mode_combo.setObjectName("guiV2PlannerPreference_default_binning_mode")
        self.binning_mode_combo.addItem("Equal-width", BINNING_EQUAL_WIDTH)
        self.binning_mode_combo.addItem("Quantile", BINNING_QUANTILE)
        self.binning_mode_combo.addItem("Custom edges", BINNING_CUSTOM_EDGES)
        self.binning_mode_combo.addItem("Fixed width", BINNING_FIXED_WIDTH)
        self.binning_mode_combo.currentIndexChanged.connect(self._update_binning_control_state)
        set_compact_field_width(self.binning_mode_combo, width=_PLANNER_MODE_FIELD_WIDTH)
        self._add_field(method_grid, 0, "Default mode", self.default_mode_combo)
        self._add_field(method_grid, 1, "Default plan method", self.plan_method_combo)
        self._add_field(method_grid, 2, "Default binning", self.binning_mode_combo)
        self._attach_field_grid(method_card, method_grid)
        self._add_card(grid, method_card, row=1, column=0)

        sampling_card = ConfigurationCard(title="Sampling controls", parent=self)
        sampling_grid = self._new_field_grid()
        self.sample_bins_label = QLabel("Default sampling bins")
        self.sample_bins_label.setObjectName("guiV2FieldLabel")
        self.bin_width_label = QLabel("Default bin width [deg]")
        self.bin_width_label.setObjectName("guiV2FieldLabel")
        self.custom_elevation_edges_label = QLabel("Elevation bin edges")
        self.custom_elevation_edges_label.setObjectName("guiV2FieldLabel")
        self.custom_solar_phase_edges_label = QLabel("Solar phase bin edges")
        self.custom_solar_phase_edges_label.setObjectName("guiV2FieldLabel")
        self.sample_bins_edit = create_integer_input(
            parent=sampling_card,
            object_name="guiV2PlannerPreference_default_sample_bins",
            minimum=1,
            maximum=50,
            default=6,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.bin_width_edit = create_float_input(
            parent=sampling_card,
            object_name="guiV2PlannerPreference_default_bin_width_deg",
            minimum=MIN_BIN_WIDTH_DEG,
            maximum=MAX_BIN_WIDTH_DEG,
            decimals=2,
            default=DEFAULT_BIN_WIDTH_DEG,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.random_seed_edit = create_integer_input(
            parent=sampling_card,
            object_name="guiV2PlannerPreference_random_seed",
            minimum=0,
            maximum=2147483647,
            default=12345,
            width=112,
        )
        self.custom_elevation_edges_edit = QLineEdit(sampling_card)
        self.custom_elevation_edges_edit.setObjectName("guiV2PlannerPreference_custom_elevation_bin_edges")
        set_compact_field_width(self.custom_elevation_edges_edit, width=_PLANNER_FILENAME_FIELD_WIDTH)
        self.custom_solar_phase_edges_edit = QLineEdit(sampling_card)
        self.custom_solar_phase_edges_edit.setObjectName("guiV2PlannerPreference_custom_solar_phase_bin_edges")
        set_compact_field_width(self.custom_solar_phase_edges_edit, width=_PLANNER_FILENAME_FIELD_WIDTH)
        sampling_grid.addWidget(self.sample_bins_label, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        sampling_grid.addWidget(self.sample_bins_edit, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        sampling_grid.addWidget(self.bin_width_label, 1, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        sampling_grid.addWidget(self.bin_width_edit, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._add_field(sampling_grid, 2, "Random seed", self.random_seed_edit)
        sampling_grid.addWidget(self.custom_elevation_edges_label, 3, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        sampling_grid.addWidget(self.custom_elevation_edges_edit, 3, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        sampling_grid.addWidget(self.custom_solar_phase_edges_label, 4, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        sampling_grid.addWidget(self.custom_solar_phase_edges_edit, 4, 1, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._attach_field_grid(sampling_card, sampling_grid)
        self._add_card(grid, sampling_card, row=1, column=1)

        self._build_optimization_repair_cards(grid, row=2)
        grid.setRowStretch(3, 1)

    def _build_optimization_repair_cards(self, grid: QGridLayout, *, row: int) -> None:
        """Add multi-start optimization and compatible repair cards to General."""
        optimizer_card = ConfigurationCard(title="Optimization", parent=self)
        optimizer_grid = self._new_field_grid()
        self.optimization_enabled_check = ToggleSwitch("Enable multi-start optimization for stratified methods", optimizer_card)
        self.optimization_enabled_check.setObjectName("guiV2PlannerPreference_optimization_enabled")
        self.optimization_trials_edit = create_integer_input(
            parent=optimizer_card,
            object_name="guiV2PlannerPreference_optimization_trials",
            minimum=1,
            maximum=MAX_OPTIMIZATION_TRIALS,
            default=32,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.candidate_depth_edit = create_integer_input(
            parent=optimizer_card,
            object_name="guiV2PlannerPreference_candidate_depth",
            minimum=1,
            maximum=MAX_CANDIDATE_DEPTH,
            default=3,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.optimization_objective_combo = QComboBox(optimizer_card)
        self.optimization_objective_combo.setObjectName("guiV2PlannerPreference_optimization_objective")
        self.optimization_objective_combo.addItem("Quality", OPTIMIZATION_OBJECTIVE_QUALITY)
        self.optimization_objective_combo.addItem("Slew-aware", OPTIMIZATION_OBJECTIVE_SLEW_AWARE)
        set_compact_field_width(self.optimization_objective_combo, width=_PLANNER_MODE_FIELD_WIDTH)
        self._add_checkbox(optimizer_grid, 0, self.optimization_enabled_check)
        self._add_field(optimizer_grid, 1, "Optimization trials", self.optimization_trials_edit)
        self._add_field(optimizer_grid, 2, "Candidate depth", self.candidate_depth_edit)
        self._add_field(optimizer_grid, 3, "Optimization objective", self.optimization_objective_combo)
        self._attach_field_grid(optimizer_card, optimizer_grid)
        self._add_card(grid, optimizer_card, row=row, column=0)

        repair_card = ConfigurationCard(title="Compatible local repair", parent=self)
        repair_grid = self._new_field_grid()
        self.local_repair_enabled_check = ToggleSwitch("Enable compatible additive local repair", repair_card)
        self.local_repair_enabled_check.setObjectName("guiV2PlannerPreference_local_repair_enabled")
        self.local_repair_max_additions_edit = create_integer_input(
            parent=repair_card,
            object_name="guiV2PlannerPreference_local_repair_max_additions",
            minimum=0,
            maximum=DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS,
            default=DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.local_repair_candidate_limit_edit = create_integer_input(
            parent=repair_card,
            object_name="guiV2PlannerPreference_local_repair_candidate_limit",
            minimum=0,
            maximum=DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT,
            default=DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.local_repair_attempt_limit_edit = create_integer_input(
            parent=repair_card,
            object_name="guiV2PlannerPreference_local_repair_attempt_limit",
            minimum=0,
            maximum=DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT,
            default=DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self._add_checkbox(repair_grid, 0, self.local_repair_enabled_check)
        self._add_field(repair_grid, 1, "Repair max additions", self.local_repair_max_additions_edit)
        self._add_field(repair_grid, 2, "Repair candidate limit", self.local_repair_candidate_limit_edit)
        self._add_field(repair_grid, 3, "Repair attempt limit", self.local_repair_attempt_limit_edit)
        self._attach_field_grid(repair_card, repair_grid)
        self._add_card(grid, repair_card, row=row, column=1)

    def _build_diagnostics_tab(self, grid: QGridLayout) -> None:
        """Create the diagnostics and motion-model defaults tab."""
        constraint_card = ConfigurationCard(
            title="Transition constraints",
            body="These controls define whether motion assumptions are diagnostic-only or used as an explicit transition feasibility filter.",
            parent=self,
        )
        constraint_grid = self._new_field_grid()
        self.transition_constraint_mode_combo = QComboBox(constraint_card)
        self.transition_constraint_mode_combo.setObjectName("guiV2PlannerPreference_transition_constraint_mode")
        self.transition_constraint_mode_combo.addItem("Time spacing only", TRANSITION_CONSTRAINT_TIME_SPACING)
        self.transition_constraint_mode_combo.addItem("Physical transition constrained", TRANSITION_CONSTRAINT_PHYSICAL)
        set_compact_field_width(self.transition_constraint_mode_combo, width=_PLANNER_COMBO_FIELD_WIDTH)
        self.transition_safety_margin_edit = create_float_input(
            parent=constraint_card,
            object_name="guiV2PlannerPreference_transition_safety_margin_sec",
            minimum=0.0,
            maximum=MAX_TRANSITION_SAFETY_MARGIN_SEC,
            decimals=1,
            default=5.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.slew_diagnostics_enabled_check = ToggleSwitch("Enable slew/path diagnostics", constraint_card)
        self.slew_diagnostics_enabled_check.setObjectName("guiV2PlannerPreference_slew_diagnostics_enabled")
        self._add_field(constraint_grid, 0, "Transition constraint", self.transition_constraint_mode_combo)
        self._add_field(constraint_grid, 1, "Safety margin [s]", self.transition_safety_margin_edit)
        self._add_checkbox(constraint_grid, 2, self.slew_diagnostics_enabled_check)
        self._attach_field_grid(constraint_card, constraint_grid)
        self._add_card(grid, constraint_card, row=0, column=0)

        motion_card = ConfigurationCard(
            title="Slew/path diagnostic model",
            body="Motion values are planning assumptions. They remain diagnostic-only unless physical transition constraints are explicitly selected.",
            parent=self,
        )
        motion_grid = self._new_two_column_field_grid()
        self.slew_az_rate_edit = create_float_input(
            parent=motion_card,
            object_name="guiV2PlannerPreference_slew_az_rate_deg_per_sec",
            minimum=MIN_SLEW_RATE_DEG_PER_SEC,
            maximum=MAX_SLEW_RATE_DEG_PER_SEC,
            decimals=2,
            default=2.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.slew_alt_rate_edit = create_float_input(
            parent=motion_card,
            object_name="guiV2PlannerPreference_slew_alt_rate_deg_per_sec",
            minimum=MIN_SLEW_RATE_DEG_PER_SEC,
            maximum=MAX_SLEW_RATE_DEG_PER_SEC,
            decimals=2,
            default=1.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.slew_settle_time_edit = create_float_input(
            parent=motion_card,
            object_name="guiV2PlannerPreference_slew_settle_time_sec",
            minimum=0.0,
            maximum=MAX_SLEW_OVERHEAD_SEC,
            decimals=1,
            default=5.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.slew_acquisition_time_edit = create_float_input(
            parent=motion_card,
            object_name="guiV2PlannerPreference_slew_acquisition_time_sec",
            minimum=0.0,
            maximum=MAX_SLEW_OVERHEAD_SEC,
            decimals=1,
            default=10.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.slew_exposure_time_edit = create_float_input(
            parent=motion_card,
            object_name="guiV2PlannerPreference_slew_exposure_time_sec",
            minimum=0.0,
            maximum=MAX_SLEW_OVERHEAD_SEC,
            decimals=1,
            default=50.0,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self.slew_transition_sample_limit_edit = create_integer_input(
            parent=motion_card,
            object_name="guiV2PlannerPreference_slew_transition_sample_limit",
            minimum=MIN_TRANSITION_SAMPLE_LIMIT,
            maximum=MAX_TRANSITION_SAMPLE_LIMIT,
            default=5000,
            width=_PLANNER_NUMERIC_FIELD_WIDTH,
        )
        self._add_field_at(motion_grid, 0, 0, "Az rate [deg/s]", self.slew_az_rate_edit)
        self._add_field_at(motion_grid, 1, 0, "Alt rate [deg/s]", self.slew_alt_rate_edit)
        self._add_field_at(motion_grid, 2, 0, "Settle time [s]", self.slew_settle_time_edit)
        self._add_field_at(motion_grid, 0, 2, "Acquisition [s]", self.slew_acquisition_time_edit)
        self._add_field_at(motion_grid, 1, 2, "Exposure/readout [s]", self.slew_exposure_time_edit)
        self._add_field_at(motion_grid, 2, 2, "Sample limit", self.slew_transition_sample_limit_edit)
        self._attach_field_grid(motion_card, motion_grid)
        self._add_card(grid, motion_card, row=0, column=1)
        grid.setRowStretch(1, 1)

    def _build_columns_tab(self, grid: QGridLayout) -> None:
        """Create the donor-equivalent visibility-column mapping tab."""
        card = ConfigurationCard(title="Visibility table columns", parent=self)
        self.column_mapping_table = PlannerColumnMappingTable(card)
        card.layout.addWidget(self.column_mapping_table, 1)
        self._add_card(grid, card, row=0, column=0, column_span=2)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 0)

    def _populate_from_preferences(self, preferences: Mapping[str, Any]) -> None:
        planner_preferences = from_preferences_dict(preferences)
        self.filename_pattern_edit.setText(planner_preferences.filename_pattern)
        self.legend_page_size_edit.setText(str(planner_preferences.legend_page_size))
        self.exposure_time_edit.setText(f"{planner_preferences.exposure_time_sec:g}")
        self.time_range_edit.setText(f"{planner_preferences.time_range_sec:g}")
        self.min_elevation_edit.setText(f"{planner_preferences.min_elevation_deg:g}")
        self.tolerance_edit.setText(f"{planner_preferences.tolerance_sec:g}")
        self.spacing_edit.setText(f"{planner_preferences.spacing_min:g}")
        self._set_combo_text(self.default_mode_combo, planner_preferences.default_mode)
        self._set_combo_data(self.coordinate_format_combo, planner_preferences.default_coordinate_format)
        self._set_combo_data(self.plan_method_combo, planner_preferences.default_plan_method)
        self._set_combo_data(self.binning_mode_combo, planner_preferences.default_binning_mode)
        self.sample_bins_edit.setText(str(planner_preferences.default_sample_bins))
        self.bin_width_edit.setText(f"{planner_preferences.default_bin_width_deg:g}")
        self.custom_elevation_edges_edit.setText(self._edges_to_text(planner_preferences.custom_elevation_bin_edges))
        self.custom_solar_phase_edges_edit.setText(self._edges_to_text(planner_preferences.custom_solar_phase_bin_edges))
        self.random_seed_edit.setText(str(planner_preferences.random_seed))
        self.optimization_enabled_check.setChecked(bool(planner_preferences.optimization_enabled))
        self.optimization_trials_edit.setText(str(planner_preferences.optimization_trials))
        self.candidate_depth_edit.setText(str(planner_preferences.candidate_depth))
        self._set_combo_data(self.optimization_objective_combo, planner_preferences.optimization_objective)
        self.local_repair_enabled_check.setChecked(bool(planner_preferences.local_repair_enabled))
        self.local_repair_max_additions_edit.setText(str(planner_preferences.local_repair_max_additions))
        self.local_repair_candidate_limit_edit.setText(str(planner_preferences.local_repair_candidate_limit))
        self.local_repair_attempt_limit_edit.setText(str(planner_preferences.local_repair_attempt_limit))
        self._set_combo_data(self.transition_constraint_mode_combo, planner_preferences.transition_constraint_mode)
        self.transition_safety_margin_edit.setText(f"{planner_preferences.transition_safety_margin_sec:g}")
        self.slew_diagnostics_enabled_check.setChecked(bool(planner_preferences.slew_diagnostics_enabled))
        self.slew_az_rate_edit.setText(f"{planner_preferences.slew_az_rate_deg_per_sec:g}")
        self.slew_alt_rate_edit.setText(f"{planner_preferences.slew_alt_rate_deg_per_sec:g}")
        self.slew_settle_time_edit.setText(f"{planner_preferences.slew_settle_time_sec:g}")
        self.slew_acquisition_time_edit.setText(f"{planner_preferences.slew_acquisition_time_sec:g}")
        self.slew_exposure_time_edit.setText(f"{planner_preferences.slew_exposure_time_sec:g}")
        self.slew_transition_sample_limit_edit.setText(str(planner_preferences.slew_transition_sample_limit))
        self.column_mapping_table.populate(planner_preferences.column_mapping)
        self._update_binning_control_state()

    def _collect_updates(self) -> dict[str, Any]:
        planner_update = {
            "filename_pattern": self.filename_pattern_edit.text().strip() or "leosat_obs_plan_{date}.csv",
            "default_plan_pattern": self.filename_pattern_edit.text().strip() or "leosat_obs_plan_{date}.csv",
            "legend_page_size": parse_integer_input(self.legend_page_size_edit, label="Legend page size", minimum=1, maximum=50),
            "exposure_time_sec": parse_float_input(self.exposure_time_edit, label="Exposure time", minimum=0.1, maximum=3600.0),
            "time_range_sec": parse_float_input(self.time_range_edit, label="Time range", minimum=0.0, maximum=3600.0),
            "min_elevation_deg": parse_float_input(self.min_elevation_edit, label="Minimum elevation", minimum=-90.0, maximum=90.0),
            "tolerance_sec": parse_float_input(self.tolerance_edit, label="Tolerance", minimum=0.0, maximum=3600.0),
            "spacing_min": parse_float_input(self.spacing_edit, label="Spacing", minimum=0.1, maximum=60.0),
            "default_mode": self.default_mode_combo.currentText().strip(),
            "default_coordinate_format": self.coordinate_format_combo.currentData(),
            "default_plan_method": self.plan_method_combo.currentData(),
            "default_binning_mode": self.binning_mode_combo.currentData(),
            "default_sample_bins": parse_integer_input(self.sample_bins_edit, label="Default sampling bins", minimum=1, maximum=50),
            "default_bin_width_deg": parse_float_input(
                self.bin_width_edit,
                label="Default bin width",
                minimum=MIN_BIN_WIDTH_DEG,
                maximum=MAX_BIN_WIDTH_DEG,
            ),
            "custom_elevation_bin_edges": self.custom_elevation_edges_edit.text().strip(),
            "custom_solar_phase_bin_edges": self.custom_solar_phase_edges_edit.text().strip(),
            "random_seed": parse_integer_input(self.random_seed_edit, label="Random seed", minimum=0, maximum=2147483647),
            "optimization_enabled": self.optimization_enabled_check.isChecked(),
            "optimization_trials": parse_integer_input(
                self.optimization_trials_edit,
                label="Optimization trials",
                minimum=1,
                maximum=MAX_OPTIMIZATION_TRIALS,
            ),
            "candidate_depth": parse_integer_input(
                self.candidate_depth_edit,
                label="Candidate depth",
                minimum=1,
                maximum=MAX_CANDIDATE_DEPTH,
            ),
            "optimization_objective": self.optimization_objective_combo.currentData(),
            "local_repair_enabled": self.local_repair_enabled_check.isChecked(),
            "local_repair_max_additions": parse_integer_input(
                self.local_repair_max_additions_edit,
                label="Repair max additions",
                minimum=0,
                maximum=DEFAULT_LOCAL_REPAIR_MAX_ADDITIONS,
            ),
            "local_repair_candidate_limit": parse_integer_input(
                self.local_repair_candidate_limit_edit,
                label="Repair candidate limit",
                minimum=0,
                maximum=DEFAULT_LOCAL_REPAIR_CANDIDATE_LIMIT,
            ),
            "local_repair_attempt_limit": parse_integer_input(
                self.local_repair_attempt_limit_edit,
                label="Repair attempt limit",
                minimum=0,
                maximum=DEFAULT_LOCAL_REPAIR_ATTEMPT_LIMIT,
            ),
            "transition_constraint_mode": self.transition_constraint_mode_combo.currentData(),
            "transition_safety_margin_sec": parse_float_input(
                self.transition_safety_margin_edit,
                label="Transition safety margin",
                minimum=0.0,
                maximum=MAX_TRANSITION_SAFETY_MARGIN_SEC,
            ),
            "slew_diagnostics_enabled": self.slew_diagnostics_enabled_check.isChecked(),
            "slew_az_rate_deg_per_sec": parse_float_input(
                self.slew_az_rate_edit,
                label="Azimuth slew rate",
                minimum=MIN_SLEW_RATE_DEG_PER_SEC,
                maximum=MAX_SLEW_RATE_DEG_PER_SEC,
            ),
            "slew_alt_rate_deg_per_sec": parse_float_input(
                self.slew_alt_rate_edit,
                label="Altitude slew rate",
                minimum=MIN_SLEW_RATE_DEG_PER_SEC,
                maximum=MAX_SLEW_RATE_DEG_PER_SEC,
            ),
            "slew_settle_time_sec": parse_float_input(
                self.slew_settle_time_edit,
                label="Slew settle time",
                minimum=0.0,
                maximum=MAX_SLEW_OVERHEAD_SEC,
            ),
            "slew_acquisition_time_sec": parse_float_input(
                self.slew_acquisition_time_edit,
                label="Slew acquisition time",
                minimum=0.0,
                maximum=MAX_SLEW_OVERHEAD_SEC,
            ),
            "slew_exposure_time_sec": parse_float_input(
                self.slew_exposure_time_edit,
                label="Slew exposure/readout time",
                minimum=0.0,
                maximum=MAX_SLEW_OVERHEAD_SEC,
            ),
            "slew_transition_sample_limit": parse_integer_input(
                self.slew_transition_sample_limit_edit,
                label="Transition sample limit",
                minimum=MIN_TRANSITION_SAMPLE_LIMIT,
                maximum=MAX_TRANSITION_SAMPLE_LIMIT,
            ),
        }
        column_mapping = self.column_mapping_table.collect()
        planner_update["visibility"] = {"columns": column_mapping}
        planner_update["column_mapping"] = column_mapping
        planner_preferences = from_preferences_dict({"observation_planner": planner_update})
        return to_preferences_dict(planner_preferences)

    def _update_binning_control_state(self) -> None:
        """Enable only the bin-size input used by the selected binning mode."""
        mode = str(self.binning_mode_combo.currentData())
        count_enabled = mode in {BINNING_EQUAL_WIDTH, BINNING_QUANTILE}
        width_enabled = mode == BINNING_FIXED_WIDTH
        custom_enabled = mode == BINNING_CUSTOM_EDGES
        self.sample_bins_label.setEnabled(count_enabled)
        self.sample_bins_edit.setEnabled(count_enabled)
        self.bin_width_label.setEnabled(width_enabled)
        self.bin_width_edit.setEnabled(width_enabled)
        self.custom_elevation_edges_label.setEnabled(custom_enabled)
        self.custom_elevation_edges_edit.setEnabled(custom_enabled)
        self.custom_solar_phase_edges_label.setEnabled(custom_enabled)
        self.custom_solar_phase_edges_edit.setEnabled(custom_enabled)

    @staticmethod
    def _edges_to_text(edges: object) -> str:
        """Render custom bin edges as compact comma-separated text."""
        if not edges:
            return ""
        try:
            return ", ".join(f"{float(edge):g}" for edge in edges)
        except TypeError:
            return str(edges)

    @staticmethod
    def _set_combo_text(combo: QComboBox, value: str) -> None:
        index = combo.findText(str(value))
        combo.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: object) -> None:
        for index in range(combo.count()):
            if str(combo.itemData(index)) == str(value):
                combo.setCurrentIndex(index)
                return
        combo.setCurrentIndex(0)


__all__ = ("ConfigurationPlannerPreferencesPage",)
