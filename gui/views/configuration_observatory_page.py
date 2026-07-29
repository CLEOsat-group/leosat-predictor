"""GUI Observatory & Location configuration page."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtWidgets import QFormLayout, QLineEdit, QPushButton, QHBoxLayout, QWidget

from ..services import PreferencesService
from ..shell.navigation_model import NavigationNode
from .configuration_base import (
    ConfigurationCard,
    ConfigurationPageBase,
    MEDIUM_FIELD_WIDTH,
    create_float_input,
    parse_float_input,
    set_compact_field_width,
)


class ConfigurationObservatoryPage(ConfigurationPageBase):
    """Edit the persisted default observatory/location preference."""

    def __init__(self, *, page: NavigationNode, preferences_service: PreferencesService, parent: QWidget | None = None) -> None:
        super().__init__(page=page, preferences_service=preferences_service, parent=parent)

        card = ConfigurationCard(
            title="Default observatory/location",
            parent=self,
        )
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.setLabelAlignment(form.labelAlignment())

        self.name_edit = QLineEdit(card)
        self.name_edit.setObjectName("guiConfigurationObservatoryNameEdit")
        set_compact_field_width(self.name_edit, width=MEDIUM_FIELD_WIDTH)
        self.latitude_edit = create_float_input(
            parent=card,
            object_name="guiConfigurationObservatoryLatitudeEdit",
            minimum=-90.0,
            maximum=90.0,
            decimals=6,
        )
        self.longitude_edit = create_float_input(
            parent=card,
            object_name="guiConfigurationObservatoryLongitudeEdit",
            minimum=-180.0,
            maximum=180.0,
            decimals=6,
        )
        self.altitude_edit = create_float_input(
            parent=card,
            object_name="guiConfigurationObservatoryAltitudeEdit",
            minimum=0.0,
            maximum=100000.0,
            decimals=2,
        )

        form.addRow("Location name", self.name_edit)
        form.addRow("Latitude (°)", self.latitude_edit)
        form.addRow("Longitude (°)", self.longitude_edit)
        form.addRow("Altitude (m)", self.altitude_edit)
        card.layout.addLayout(form)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.map_button = QPushButton("Select from Map", card)
        self.map_button.setObjectName("guiConfigurationSelectFromMapButton")
        self.map_button.setProperty("buttonRole", "secondary")
        action_row.addWidget(self.map_button)
        card.layout.addLayout(action_row)
        self.map_button.clicked.connect(self._select_from_map)

        self.content_layout.addWidget(card)
        self.content_layout.addStretch(1)
        self.load_from_service()

    def _populate_from_preferences(self, preferences: Mapping[str, Any]) -> None:
        location = self._mapping(preferences, "default_location")
        self.name_edit.setText(str(location.get("name", "")))
        self.latitude_edit.setText(f"{self._as_float(location.get('latitude'), 0.0):.6f}".rstrip("0").rstrip("."))
        self.longitude_edit.setText(f"{self._as_float(location.get('longitude'), 0.0):.6f}".rstrip("0").rstrip("."))
        self.altitude_edit.setText(f"{self._as_float(location.get('altitude'), 0.0):.2f}".rstrip("0").rstrip("."))

    def _collect_updates(self) -> dict[str, Any]:
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Location name must not be empty.")
        return {
            "default_location": {
                "name": name,
                "latitude": parse_float_input(self.latitude_edit, label="Latitude", minimum=-90.0, maximum=90.0),
                "longitude": parse_float_input(self.longitude_edit, label="Longitude", minimum=-180.0, maximum=180.0),
                "altitude": parse_float_input(self.altitude_edit, label="Altitude", minimum=0.0, maximum=100000.0),
            }
        }

    def _select_from_map(self) -> None:
        try:
            from ..dialogs import LocationMapDialog

            dialog = LocationMapDialog(self)
        except Exception as exc:  # pragma: no cover - depends on local WebEngine availability
            self._set_status(f"Unable to open Select from Map: {exc}", level="error")
            return

        dialog.locationSelected.connect(self._apply_map_location)
        dialog.exec()

    def _apply_map_location(self, latitude: float, longitude: float, altitude: float, name: str) -> None:
        self.name_edit.setText(str(name))
        self.latitude_edit.setText(f"{float(latitude):.6f}".rstrip("0").rstrip("."))
        self.longitude_edit.setText(f"{float(longitude):.6f}".rstrip("0").rstrip("."))
        self.altitude_edit.setText(f"{max(0.0, float(altitude)):.2f}".rstrip("0").rstrip("."))
        self._set_status("Map selection applied to the form. Use Save to persist it.")


__all__ = ("ConfigurationObservatoryPage",)
