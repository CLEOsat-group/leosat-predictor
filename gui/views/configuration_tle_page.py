"""GUI TLE configuration page."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtWidgets import QFormLayout, QLineEdit, QPlainTextEdit, QWidget

from ..services import PreferencesService
from ..shell.navigation_model import NavigationNode
from ..widgets.toggle_switch import ToggleSwitch
from .configuration_base import (
    ConfigurationCard,
    ConfigurationPageBase,
    LONG_FIELD_WIDTH,
    create_float_input,
    parse_float_input,
    set_compact_field_width,
)


class ConfigurationTlePage(ConfigurationPageBase):
    """Edit TLE cache behavior and review configured sources."""

    def __init__(self, *, page: NavigationNode, preferences_service: PreferencesService, parent: QWidget | None = None) -> None:
        super().__init__(page=page, preferences_service=preferences_service, parent=parent)

        settings_card = ConfigurationCard(
            title="TLE cache settings",
            parent=self,
        )
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.tle_folder_edit = QLineEdit(settings_card)
        self.tle_folder_edit.setObjectName("guiConfigurationTleFolderEdit")
        set_compact_field_width(self.tle_folder_edit, width=LONG_FIELD_WIDTH)
        self.expiration_edit = create_float_input(
            parent=settings_card,
            object_name="guiConfigurationTleExpirationEdit",
            minimum=0.0001,
            maximum=100000.0,
            decimals=2,
            default=8.0,
        )
        self.update_edit = create_float_input(
            parent=settings_card,
            object_name="guiConfigurationTleUpdateEdit",
            minimum=0.0001,
            maximum=100000.0,
            decimals=2,
            default=8.0,
        )
        self.allow_batch_check = ToggleSwitch("Allow batch TLE download", settings_card)
        self.allow_batch_check.setObjectName("guiConfigurationTleAllowBatchCheck")

        form.addRow("TLE folder", self.tle_folder_edit)
        form.addRow("TLE expiration (h)", self.expiration_edit)
        form.addRow("TLE update interval (h)", self.update_edit)
        form.addRow("Batch download", self.allow_batch_check)
        settings_card.layout.addLayout(form)
        self.content_layout.addWidget(settings_card)

        source_card = ConfigurationCard(
            title="Configured TLE sources",
            parent=self,
        )
        self.sources_text = QPlainTextEdit(source_card)
        self.sources_text.setObjectName("guiConfigurationTleSourcesText")
        self.sources_text.setReadOnly(True)
        self.sources_text.setMinimumHeight(180)
        source_card.layout.addWidget(self.sources_text)
        self.content_layout.addWidget(source_card)
        self.content_layout.addStretch(1)
        self.load_from_service()

    def _populate_from_preferences(self, preferences: Mapping[str, Any]) -> None:
        self.tle_folder_edit.setText(str(preferences.get("tle_folder", "")))
        self.expiration_edit.setText(f"{self._as_float(preferences.get('tle_expiration_hours'), 8.0):.2f}".rstrip("0").rstrip("."))
        self.update_edit.setText(f"{self._as_float(preferences.get('tle_update_interval_hours'), 8.0):.2f}".rstrip("0").rstrip("."))
        self.allow_batch_check.setChecked(bool(preferences.get("allow_batch_download", False)))
        self.sources_text.setPlainText(self._format_sources(preferences))

    def _collect_updates(self) -> dict[str, Any]:
        tle_folder = self.tle_folder_edit.text().strip()
        if not tle_folder:
            raise ValueError("TLE folder must not be empty.")
        return {
            "tle_folder": tle_folder,
            "tle_expiration_hours": parse_float_input(
                self.expiration_edit,
                label="TLE expiration",
                minimum=0.0001,
                maximum=100000.0,
            ),
            "tle_update_interval_hours": parse_float_input(
                self.update_edit,
                label="TLE update interval",
                minimum=0.0001,
                maximum=100000.0,
            ),
            "allow_batch_download": bool(self.allow_batch_check.isChecked()),
        }

    @staticmethod
    def _format_sources(preferences: Mapping[str, Any]) -> str:
        sources = preferences.get("tle_sources")
        if not isinstance(sources, Mapping) or not sources:
            return "No TLE sources are configured."
        lines: list[str] = []
        for name, payload in sources.items():
            if isinstance(payload, Mapping):
                url = payload.get("url") or payload.get("source") or payload.get("api") or "—"
                default_satellites = payload.get("default_satellites") or payload.get("defaults") or ()
                count = len(default_satellites) if hasattr(default_satellites, "__len__") else 0
                lines.append(f"{name}: {url}  | defaults: {count}")
            else:
                lines.append(f"{name}: {payload}")
        return "\n".join(lines)


__all__ = ("ConfigurationTlePage",)
