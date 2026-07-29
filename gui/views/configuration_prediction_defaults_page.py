"""GUI prediction-default configuration page."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtWidgets import QComboBox, QFormLayout, QWidget

from ..services import PreferencesService
from ..shell.navigation_model import NavigationNode
from .configuration_base import (
    ConfigurationCard,
    ConfigurationPageBase,
    SHORT_FIELD_WIDTH,
    create_float_input,
    create_integer_input,
    parse_float_input,
    parse_integer_input,
    set_compact_field_width,
)


_PRECISE_RANGE_OPTIONS = ("morning", "evening", "both")
_OVERPASS_RANGE_OPTIONS = ("night", "morning", "evening", "both")
_INTERVAL_UNIT_OPTIONS = ("seconds", "minutes", "hours")


class ConfigurationPredictionDefaultsPage(ConfigurationPageBase):
    """Edit defaults consumed by overpass and precise setup workflows."""

    def __init__(self, *, page: NavigationNode, preferences_service: PreferencesService, parent: QWidget | None = None) -> None:
        super().__init__(page=page, preferences_service=preferences_service, parent=parent)

        overpass_card = ConfigurationCard(
            title="Overpass defaults",
            parent=self,
        )
        overpass_form = QFormLayout()
        overpass_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)

        self.default_days_edit = create_integer_input(
            parent=overpass_card,
            object_name="guiConfigurationDefaultOverpassDaysEdit",
            minimum=1,
            maximum=365,
            default=2,
        )
        self.overpass_range_combo = QComboBox(overpass_card)
        self.overpass_range_combo.setObjectName("guiConfigurationOverpassRangeCombo")
        self.overpass_range_combo.addItems(_OVERPASS_RANGE_OPTIONS)
        set_compact_field_width(self.overpass_range_combo, width=SHORT_FIELD_WIDTH)

        overpass_form.addRow("Default days", self.default_days_edit)
        overpass_form.addRow("Default overpass range", self.overpass_range_combo)
        overpass_card.layout.addLayout(overpass_form)
        self.content_layout.addWidget(overpass_card)

        precise_card = ConfigurationCard(
            title="Precise prediction defaults",
            parent=self,
        )
        precise_form = QFormLayout()
        precise_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)

        self.default_interval_edit = create_integer_input(
            parent=precise_card,
            object_name="guiConfigurationDefaultPreciseIntervalEdit",
            minimum=1,
            maximum=100000,
            default=1,
        )
        self.interval_unit_combo = QComboBox(precise_card)
        self.interval_unit_combo.setObjectName("guiConfigurationDefaultIntervalUnitCombo")
        self.interval_unit_combo.addItems(_INTERVAL_UNIT_OPTIONS)
        set_compact_field_width(self.interval_unit_combo, width=SHORT_FIELD_WIDTH)
        self.precise_range_combo = QComboBox(precise_card)
        self.precise_range_combo.setObjectName("guiConfigurationPreciseRangeCombo")
        self.precise_range_combo.addItems(_PRECISE_RANGE_OPTIONS)
        set_compact_field_width(self.precise_range_combo, width=SHORT_FIELD_WIDTH)

        precise_form.addRow("Default interval", self.default_interval_edit)
        precise_form.addRow("Default interval unit", self.interval_unit_combo)
        precise_form.addRow("Default precise range", self.precise_range_combo)
        precise_card.layout.addLayout(precise_form)
        self.content_layout.addWidget(precise_card)

        constraint_card = ConfigurationCard(
            title="Precise visibility constraints",
            parent=self,
        )
        constraint_form = QFormLayout()
        constraint_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)

        self.visibility_margin_edit = create_float_input(
            parent=constraint_card,
            object_name="guiConfigurationVisibilityMarginEdit",
            minimum=0.0,
            maximum=100000.0,
            decimals=2,
            default=5.0,
        )
        self.lowest_altitude_edit = create_float_input(
            parent=constraint_card,
            object_name="guiConfigurationLowestAltitudeEdit",
            minimum=0.0,
            maximum=90.0,
            decimals=2,
            default=30.0,
        )
        self.sun_high_edit = create_float_input(
            parent=constraint_card,
            object_name="guiConfigurationSunZenithHighEdit",
            minimum=0.0,
            maximum=180.0,
            decimals=2,
            default=112.0,
        )
        self.sun_low_edit = create_float_input(
            parent=constraint_card,
            object_name="guiConfigurationSunZenithLowEdit",
            minimum=0.0,
            maximum=180.0,
            decimals=2,
            default=99.0,
        )

        constraint_form.addRow("Visibility margin (min)", self.visibility_margin_edit)
        constraint_form.addRow("Lowest satellite elevation (°)", self.lowest_altitude_edit)
        constraint_form.addRow("Sun zenith highest (°)", self.sun_high_edit)
        constraint_form.addRow("Sun zenith lowest (°)", self.sun_low_edit)
        constraint_card.layout.addLayout(constraint_form)
        self.content_layout.addWidget(constraint_card)
        self.content_layout.addStretch(1)
        self.load_from_service()

    def _populate_from_preferences(self, preferences: Mapping[str, Any]) -> None:
        self.default_days_edit.setText(str(self._as_int(preferences.get("default_days"), 2)))
        self.default_interval_edit.setText(str(self._as_int(preferences.get("default_interval"), 1)))
        self._set_combo(self.interval_unit_combo, str(preferences.get("default_interval_unit", "seconds")).lower())
        precise_range = str(preferences.get("prediction_range_precise", preferences.get("prediction_range", "evening"))).lower()
        self._set_combo(self.precise_range_combo, precise_range)
        self._set_combo(self.overpass_range_combo, str(preferences.get("prediction_range_overpass", "night")).lower())
        self.visibility_margin_edit.setText(f"{self._as_float(preferences.get('visibility_margin'), 5.0):.2f}".rstrip("0").rstrip("."))

        constraints = self._mapping(preferences, "visibility_constraints")
        self.lowest_altitude_edit.setText(
            f"{self._as_float(constraints.get('lowest_altitude_satellite'), 30.0):.2f}".rstrip("0").rstrip(".")
        )
        self.sun_high_edit.setText(
            f"{self._as_float(constraints.get('sun_zenith_highest'), 112.0):.2f}".rstrip("0").rstrip(".")
        )
        self.sun_low_edit.setText(
            f"{self._as_float(constraints.get('sun_zenith_lowest'), 99.0):.2f}".rstrip("0").rstrip(".")
        )

    def _collect_updates(self) -> dict[str, Any]:
        sun_high = parse_float_input(self.sun_high_edit, label="Sun zenith highest", minimum=0.0, maximum=180.0)
        sun_low = parse_float_input(self.sun_low_edit, label="Sun zenith lowest", minimum=0.0, maximum=180.0)
        if sun_high < sun_low:
            raise ValueError("Sun zenith highest must be greater than or equal to sun zenith lowest.")
        precise_range = self.precise_range_combo.currentText().strip().lower()
        return {
            "default_days": parse_integer_input(self.default_days_edit, label="Default overpass days", minimum=1, maximum=365),
            "default_interval": parse_integer_input(
                self.default_interval_edit,
                label="Default precise interval",
                minimum=1,
                maximum=100000,
            ),
            "default_interval_unit": self.interval_unit_combo.currentText().strip().lower(),
            "prediction_range": precise_range,
            "prediction_range_precise": precise_range,
            "prediction_range_overpass": self.overpass_range_combo.currentText().strip().lower(),
            "visibility_margin": parse_float_input(
                self.visibility_margin_edit,
                label="Visibility margin",
                minimum=0.0,
                maximum=100000.0,
            ),
            "visibility_constraints": {
                "lowest_altitude_satellite": parse_float_input(
                    self.lowest_altitude_edit,
                    label="Lowest satellite elevation",
                    minimum=0.0,
                    maximum=90.0,
                ),
                "sun_zenith_highest": sun_high,
                "sun_zenith_lowest": sun_low,
            },
        }

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        combo.setCurrentIndex(index if index >= 0 else 0)


__all__ = ("ConfigurationPredictionDefaultsPage",)
