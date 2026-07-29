"""GUI interface preference page."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtWidgets import QComboBox, QFormLayout, QWidget

from ..services import PreferencesService
from ..shell.navigation_model import NavigationNode
from .configuration_base import ConfigurationCard, ConfigurationPageBase, SHORT_FIELD_WIDTH, set_compact_field_width


class ConfigurationInterfacePage(ConfigurationPageBase):
    """Edit appearance-level settings without live applying them in Task 47B."""

    def __init__(self, *, page: NavigationNode, preferences_service: PreferencesService, parent: QWidget | None = None) -> None:
        super().__init__(page=page, preferences_service=preferences_service, parent=parent)

        card = ConfigurationCard(
            title="Appearance",
            parent=self,
        )
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        self.theme_combo = QComboBox(card)
        self.theme_combo.setObjectName("guiConfigurationThemeCombo")
        self.theme_combo.addItems(("dark", "light"))
        set_compact_field_width(self.theme_combo, width=SHORT_FIELD_WIDTH)
        form.addRow("Theme", self.theme_combo)
        card.layout.addLayout(form)

        self.content_layout.addWidget(card)
        self.content_layout.addStretch(1)
        self.load_from_service()

    def _populate_from_preferences(self, preferences: Mapping[str, Any]) -> None:
        theme = PreferencesService.normalize_theme(preferences.get("theme", "dark"))
        index = self.theme_combo.findText(theme)
        self.theme_combo.setCurrentIndex(index if index >= 0 else 0)

    def _collect_updates(self) -> dict[str, Any]:
        return {"theme": self.theme_combo.currentText().strip().lower()}


__all__ = ("ConfigurationInterfacePage",)
