"""GUI-v2 consolidated "General" configuration page.

This page merges the previously separate Observatory, TLE, Interface, and
Paths & Export configuration pages into one nav entry.  Rather than reimplement
their fields, it embeds the existing page widgets as inner sub-tabs and drives
them from a single Save/Revert bar: each child is constructed without its own
action bar (``show_actions=False``), and this page fans preference load/collect
out to the children.  The read-only Paths & Export audit contributes no writable
values, which the aggregate save handles naturally.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtWidgets import QTabWidget, QWidget

from ..services import PreferencesService
from ..services.runtime_paths import GuiRuntimePaths
from ..shell.navigation_model import NavigationNode
from .configuration_base import ConfigurationPageBase
from .configuration_interface_page import ConfigurationInterfacePage
from .configuration_observatory_page import ConfigurationObservatoryPage
from .configuration_paths_page import ConfigurationPathsPage
from .configuration_tle_page import ConfigurationTlePage


class ConfigurationGeneralPage(ConfigurationPageBase):
    """Single configuration page hosting the general-purpose settings sub-tabs."""

    def __init__(
        self,
        *,
        page: NavigationNode,
        preferences_service: PreferencesService,
        runtime_paths: GuiRuntimePaths | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(page=page, preferences_service=preferences_service, parent=parent)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("guiV2ConfigurationGeneralTabs")
        # Reuse the shared workspace-tab theming so the tab pane matches the
        # dark surface of the other configuration pages instead of defaulting to
        # a white pane.
        self.tabs.setProperty("visualRole", "workspaceTabs")

        # Each child page reuses its own fields and populate/collect logic, but
        # without an individual action bar or status line so only this page's
        # unified Save/Revert bar and status label are visible.
        self.observatory_section = ConfigurationObservatoryPage(
            page=page, preferences_service=preferences_service, show_actions=False, parent=self.tabs
        )
        self.tle_section = ConfigurationTlePage(
            page=page, preferences_service=preferences_service, show_actions=False, parent=self.tabs
        )
        self.interface_section = ConfigurationInterfacePage(
            page=page, preferences_service=preferences_service, show_actions=False, parent=self.tabs
        )
        self.paths_section = ConfigurationPathsPage(
            page=page,
            preferences_service=preferences_service,
            runtime_paths=runtime_paths,
            parent=self.tabs,
        )

        # The Paths section is read-only; only the first three contribute writable
        # updates.  Keep the read-only section in a separate tuple so the save
        # fan-out stays explicit.
        self._writable_sections: tuple[ConfigurationPageBase, ...] = (
            self.observatory_section,
            self.tle_section,
            self.interface_section,
        )
        self._all_sections: tuple[ConfigurationPageBase, ...] = (
            *self._writable_sections,
            self.paths_section,
        )
        for section in self._all_sections:
            section.status_label.setVisible(False)

        self.tabs.addTab(self.observatory_section, "Observatory Location")
        self.tabs.addTab(self.tle_section, "TLE Sources & Satellites")
        self.tabs.addTab(self.interface_section, "Interface")
        self.tabs.addTab(self.paths_section, "Paths & Export")

        self.content_layout.addWidget(self.tabs, 1)
        self.load_from_service()

    def _populate_from_preferences(self, preferences: Mapping[str, Any]) -> None:
        """Fan the loaded snapshot out to every embedded section."""
        for section in self._all_sections:
            section._populate_from_preferences(preferences)

    def _collect_updates(self) -> dict[str, Any]:
        """Merge writable-section updates into one preference-save payload."""
        updates: dict[str, Any] = {}
        for section in self._writable_sections:
            updates.update(section._collect_updates())
        return updates


__all__ = ("ConfigurationGeneralPage",)
