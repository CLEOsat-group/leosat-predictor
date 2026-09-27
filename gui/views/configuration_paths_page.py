"""GUI paths and export audit page.

The page reports the *resolved* runtime locations the application actually reads
from and writes to, distinguishing read-only bundled resources from the
writable per-user data directory.  Showing resolved absolute paths (rather than
the relative ``tle_folder`` configuration string) lets a user of the packaged
Windows build find where their downloaded TLEs and preferences really live.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QPushButton, QWidget

from ..services import PreferencesService
from ..services.runtime_paths import GuiRuntimePaths
from ..shell.navigation_model import NavigationNode
from .configuration_base import ConfigurationCard, ConfigurationPageBase, create_read_only_value


class ConfigurationPathsPage(ConfigurationPageBase):
    """Show resolved runtime paths and reveal the writable folders on disk."""

    def __init__(
        self,
        *,
        page: NavigationNode,
        preferences_service: PreferencesService,
        runtime_paths: GuiRuntimePaths | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(page=page, preferences_service=preferences_service, show_actions=False, parent=parent)

        # Fall back to discovery so the page is self-sufficient even if it is
        # constructed without an explicit path set (mirrors composition_root and
        # the TLE service factory, which both use ``or GuiRuntimePaths.discover``).
        self._runtime_paths = runtime_paths or GuiRuntimePaths.discover()
        self._tle_cache_dir: Path | None = None

        card = ConfigurationCard(
            title="Path audit",
            body=(
                "Resolved locations the application reads from and writes to. "
                "Bundled resources are read-only; your data lives in the user "
                "data directory below."
            ),
            parent=self,
        )
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.mode_label = create_read_only_value("—", card)
        self.resource_root_label = create_read_only_value("—", card)
        self.defaults_path_label = create_read_only_value("—", card)
        self.user_data_label = create_read_only_value("—", card)
        self.user_prefs_label = create_read_only_value("—", card)
        self.tle_folder_label = create_read_only_value("—", card)
        self.tle_cache_label = create_read_only_value("—", card)

        form.addRow("Storage mode", self.mode_label)
        form.addRow(
            "Application resources",
            self._path_field(self.resource_root_label, self._open_resource_root, "guiPathsOpenResourcesButton"),
        )
        form.addRow("Default config file", self.defaults_path_label)
        form.addRow(
            "User data directory",
            self._path_field(self.user_data_label, self._open_user_data_dir, "guiPathsOpenDataButton"),
        )
        form.addRow("User preferences file", self.user_prefs_label)
        form.addRow("Configured TLE folder", self.tle_folder_label)
        form.addRow(
            "TLE cache directory",
            self._path_field(self.tle_cache_label, self._open_tle_cache_dir, "guiPathsOpenTleButton"),
        )

        card.layout.addLayout(form)
        self.content_layout.addWidget(card)
        self.content_layout.addStretch(1)
        self.load_from_service()

    def _path_field(self, value_label: QLabel, on_open, object_name: str) -> QWidget:
        """Return a value label paired with an 'Open' button for a directory row."""
        host = QWidget(self)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(value_label, 1)

        button = QPushButton("Open", host)
        button.setObjectName(object_name)
        button.setProperty("buttonRole", "secondary")
        button.setToolTip("Open this folder in your file manager.")
        button.clicked.connect(on_open)
        row.addWidget(button, 0)
        return host

    def _populate_from_preferences(self, preferences: Mapping[str, Any]) -> None:
        paths = self._runtime_paths
        self.mode_label.setText(
            "Installed application (frozen)" if paths.frozen else "Development (source checkout)"
        )
        self.resource_root_label.setText(str(paths.resource_root))
        self.defaults_path_label.setText(str(paths.defaults_path))
        self.user_data_label.setText(str(paths.user_data_root))
        self.user_prefs_label.setText(str(paths.user_preferences_path))

        tle_folder = str(preferences.get("tle_folder", "") or "")
        self.tle_folder_label.setText(tle_folder or "—")
        self._tle_cache_dir = paths.resolve_tle_cache_dir(tle_folder or "data/tle")
        self.tle_cache_label.setText(str(self._tle_cache_dir))

    def _collect_updates(self) -> dict[str, Any]:
        return {}

    def _open_resource_root(self) -> None:
        # Bundled resources are read-only; never create the directory.
        self._open_directory(self._runtime_paths.resource_root, create=False)

    def _open_user_data_dir(self) -> None:
        self._open_directory(self._runtime_paths.user_data_root, create=True)

    def _open_tle_cache_dir(self) -> None:
        # The cache is created lazily on first download, so it may not exist yet.
        self._open_directory(self._tle_cache_dir, create=True)

    def _open_directory(self, path: Path | None, *, create: bool) -> None:
        """Reveal ``path`` in the OS file manager, creating writable dirs first."""
        if path is None:
            self._set_status("No folder is available for this entry.", level="error")
            return
        path = Path(path)
        if create:
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._set_status(f"Unable to create {path}: {exc}", level="error")
                return
        if not path.exists():
            self._set_status(f"Folder does not exist yet: {path}", level="error")
            return
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self._set_status(f"Opened {path} in your file manager.")
        else:
            self._set_status(f"Unable to open {path} in your file manager.", level="error")


__all__ = ("ConfigurationPathsPage",)
