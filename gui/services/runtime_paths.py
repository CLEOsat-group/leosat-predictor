"""Runtime path resolution for source and frozen GUI execution.

The desktop GUI needs two distinct path domains:

* read-only application resources bundled with the executable; and
* writable per-user state such as preferences, saved locations, and TLE cache.

Keeping those domains explicit prevents frozen applications from attempting to
write into their installation directory and removes current-working-directory
assumptions from GUI startup.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys


_APPLICATION_DIR_NAME = "LEOSatPredictor"


@dataclass(frozen=True, slots=True)
class GuiRuntimePaths:
    """Resolved read-only and writable paths used by the desktop GUI.

    Parameters
    ----------
    resource_root : pathlib.Path
        Root containing bundled read-only resources such as ``config`` and
        ``gui`` package data.
    user_data_root : pathlib.Path
        Writable application data directory for the current user.
    defaults_path : pathlib.Path
        Bundled default configuration JSON file.
    user_preferences_path : pathlib.Path
        Writable per-user preference JSON file.
    user_locations_path : pathlib.Path
        Writable per-user saved-location JSON file.
    tle_cache_dir : pathlib.Path
        Writable TLE cache directory.
    frozen : bool
        Whether paths were resolved for a frozen executable.
    """

    resource_root: Path
    user_data_root: Path
    defaults_path: Path
    user_preferences_path: Path
    user_locations_path: Path
    tle_cache_dir: Path
    frozen: bool

    @classmethod
    def discover(
        cls,
        *,
        frozen: bool | None = None,
        resource_root: str | Path | None = None,
        user_data_root: str | Path | None = None,
    ) -> "GuiRuntimePaths":
        """Resolve runtime paths for source or PyInstaller execution.

        Parameters
        ----------
        frozen : bool, optional
            Explicit frozen-state override, primarily for verification.  When
            omitted, ``sys.frozen`` is inspected.
        resource_root : str or pathlib.Path, optional
            Explicit read-only resource root.
        user_data_root : str or pathlib.Path, optional
            Explicit writable user-data root.

        Returns
        -------
        GuiRuntimePaths
            Fully resolved runtime path set.
        """

        is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
        resolved_resource_root = (
            Path(resource_root).expanduser().resolve()
            if resource_root is not None
            else cls._default_resource_root(is_frozen)
        )
        resolved_user_data_root = (
            Path(user_data_root).expanduser().resolve()
            if user_data_root is not None
            else cls._default_user_data_root(
                frozen=is_frozen,
                resource_root=resolved_resource_root,
            )
        )

        return cls(
            resource_root=resolved_resource_root,
            user_data_root=resolved_user_data_root,
            defaults_path=resolved_resource_root / "config" / "config.json",
            user_preferences_path=resolved_user_data_root / "user_preferences.json",
            user_locations_path=resolved_user_data_root / "user_locations.json",
            tle_cache_dir=resolved_user_data_root / "tle",
            frozen=is_frozen,
        )


    def resolve_tle_cache_dir(self, configured_path: object) -> Path:
        """Resolve a configured TLE cache path for the active runtime mode.

        Parameters
        ----------
        configured_path : object
            Configured ``tle_folder`` value. Absolute paths remain absolute.
            Relative source paths remain repository-relative. Relative frozen
            paths are redirected below the per-user data root; a leading
            ``data`` component is removed to avoid ``data/data`` nesting.

        Returns
        -------
        pathlib.Path
            Writable cache directory for the active runtime.
        """

        path = Path(str(configured_path or "data/tle"))
        if path.is_absolute():
            return path
        if not self.frozen:
            return self.resource_root / path

        parts = path.parts
        if parts and parts[0].lower() == "data":
            parts = parts[1:]
        relative = Path(*parts) if parts else Path("tle")
        return self.user_data_root / relative

    @staticmethod
    def _default_resource_root(frozen: bool) -> Path:
        """Return the default read-only resource root."""

        if frozen:
            bundle_root = getattr(sys, "_MEIPASS", None)
            if bundle_root:
                return Path(str(bundle_root)).resolve()
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _default_user_data_root(*, frozen: bool, resource_root: Path) -> Path:
        """Return the default writable user-data root."""

        override = os.environ.get("LEOSAT_USER_DATA_DIR")
        if override:
            return Path(override).expanduser().resolve()

        if not frozen:
            return resource_root / "data"

        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data).expanduser().resolve() / _APPLICATION_DIR_NAME

        if os.name == "nt":
            return Path.home() / "AppData" / "Local" / _APPLICATION_DIR_NAME
        return Path.home() / ".local" / "share" / _APPLICATION_DIR_NAME


__all__ = ("GuiRuntimePaths",)
