"""GUI paths and export audit page."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from PyQt6.QtWidgets import QFormLayout, QWidget

from ..services import PreferencesService
from ..shell.navigation_model import NavigationNode
from .configuration_base import ConfigurationCard, ConfigurationPageBase, create_read_only_value


class ConfigurationPathsPage(ConfigurationPageBase):
    """Show path-related preference state without inventing unused path settings."""

    def __init__(self, *, page: NavigationNode, preferences_service: PreferencesService, parent: QWidget | None = None) -> None:
        super().__init__(page=page, preferences_service=preferences_service, show_actions=False, parent=parent)

        card = ConfigurationCard(
            title="Path audit",
            parent=self,
        )
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.defaults_path_label = create_read_only_value("—", card)
        self.user_path_label = create_read_only_value("—", card)
        self.tle_folder_label = create_read_only_value("—", card)
        self.data_dir_label = create_read_only_value("—", card)
        form.addRow("Default config file", self.defaults_path_label)
        form.addRow("User preferences file", self.user_path_label)
        form.addRow("Configured TLE folder", self.tle_folder_label)
        form.addRow("Data directory", self.data_dir_label)
        card.layout.addLayout(form)
        self.content_layout.addWidget(card)
        self.content_layout.addStretch(1)
        self.load_from_service()

    def _populate_from_preferences(self, preferences: Mapping[str, Any]) -> None:
        self.defaults_path_label.setText(str(self._preferences_service.defaults_path))
        self.user_path_label.setText(str(self._preferences_service.user_preferences_path))
        tle_folder = str(preferences.get("tle_folder", ""))
        self.tle_folder_label.setText(tle_folder or "—")
        self.data_dir_label.setText(str(Path(self._preferences_service.user_preferences_path).parent))

    def _collect_updates(self) -> dict[str, Any]:
        return {}


__all__ = ("ConfigurationPathsPage",)
