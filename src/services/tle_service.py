"""Shared TLE cache, download, and parsing service.

This service is intentionally independent of the desktop GUI and Flask route
handlers.  GUI widgets and web routes should call this module instead of owning
separate cache, network, and parser implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Any

import requests

from src.config import Config


@dataclass(frozen=True)
class TleSatellite:
    """Parsed TLE satellite entry.

    Parameters
    ----------
    name : str
        Satellite display name.
    tle1 : str
        TLE line 1.
    tle2 : str
        TLE line 2.
    is_default : bool, optional
        Whether the satellite appears in the configured default list.
    """

    name: str
    tle1: str
    tle2: str
    is_default: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return a JSON/UI-friendly dictionary representation."""
        return {
            "name": self.name,
            "tle1": self.tle1,
            "tle2": self.tle2,
            "is_default": self.is_default,
        }


class TleService:
    """Shared GUI/web TLE service.

    Parameters
    ----------
    preferences : Mapping, optional
        Preference/configuration mapping.  GUI callers should pass their loaded
        preferences; web callers may omit this and use ``src.config.Config``.
    project_root : str or pathlib.Path, optional
        Repository root used to resolve relative cache directories.
    cache_dir : str or pathlib.Path, optional
        Explicit writable cache directory.  When supplied, this takes
        precedence over the relative ``tle_folder`` preference.
    """

    def __init__(
        self,
        preferences: Mapping[str, Any] | None = None,
        *,
        project_root: str | Path | None = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.preferences: Mapping[str, Any] = preferences if preferences is not None else Config().get_all()
        self.project_root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]
        self.cache_dir = (
            Path(cache_dir)
            if cache_dir is not None
            else self._resolve_cache_dir(self.preferences.get("tle_folder", "data/tle/"))
        )
        self.expiration_hours = float(self.preferences.get("tle_expiration_hours", 8))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def list_constellations(self) -> list[str]:
        """Return configured constellation names."""
        return list(self._tle_sources().keys())

    def get_cached_tle_file(self, constellation: str) -> Path | None:
        """Return the newest cached TLE file for a constellation.

        The file may be expired.  Call :meth:`is_tle_expired` when freshness is
        required.
        """
        normalized = self._normalize_constellation(constellation)
        files = sorted(
            self.cache_dir.glob(f"tle_{normalized}_*.txt"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return files[0] if files else None

    def is_tle_expired(self, cached_file: str | Path | None) -> bool:
        """Return whether a cached TLE file is missing or expired."""
        if cached_file is None:
            return True
        path = Path(cached_file)
        if not path.exists():
            return True
        last_modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return datetime.now(timezone.utc) - last_modified >= timedelta(hours=self.expiration_hours)

    def fetch_or_load_constellation(
        self,
        constellation: str,
        *,
        force_download: bool = False,
        default_only: bool = False,
    ) -> tuple[list[dict[str, object]], Path]:
        """Return parsed satellites and the TLE source file path.

        Parameters
        ----------
        constellation : str
            Configured constellation key.
        force_download : bool, optional
            If `True`, bypass the cache and download the source again.
        default_only : bool, optional
            If `True`, keep only configured default satellites.  For backward
            compatibility, an empty configured default list means return all
            satellites.
        """
        normalized = self._normalize_constellation(constellation)
        cached_file = self.get_cached_tle_file(normalized)
        if force_download or cached_file is None or self.is_tle_expired(cached_file):
            tle_data = self.download_tle_data(normalized)
            cached_file = self.save_tle_to_cache(normalized, tle_data)
        else:
            tle_data = cached_file.read_text(encoding="utf-8")

        satellites = self.parse_tle_text(tle_data, normalized, default_only=default_only)
        return [satellite.to_dict() for satellite in satellites], cached_file

    def download_tle_data(self, constellation: str) -> str:
        """Download raw TLE text for a configured constellation."""
        normalized = self._normalize_constellation(constellation)
        source = self._tle_sources().get(normalized, {})
        url = source.get("url")
        if not url:
            raise ValueError(f"No URL found for constellation: {constellation}")

        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Failed to download TLE data for {constellation}: {response.status_code}")
        return response.text

    def save_tle_to_cache(self, constellation: str, tle_data: str) -> Path:
        """Save raw TLE text to the cache and return the written path."""
        normalized = self._normalize_constellation(constellation)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        file_path = self.cache_dir / f"tle_{normalized}_{timestamp}.txt"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(tle_data, encoding="utf-8", newline="")
        return file_path

    def parse_tle_text(self, tle_data: str, constellation: str, *, default_only: bool = False) -> list[TleSatellite]:
        """Parse raw TLE text into satellite entries."""
        normalized = self._normalize_constellation(constellation)
        default_satellites = self._default_satellites(normalized)
        lines = [line.strip() for line in tle_data.splitlines() if line.strip()]
        satellites: list[TleSatellite] = []

        for index in range(0, len(lines), 3):
            if index + 2 >= len(lines):
                continue
            name = lines[index].strip()
            tle1 = lines[index + 1].strip()
            tle2 = lines[index + 2].strip()
            is_default = name in default_satellites
            if default_only and default_satellites and not is_default:
                continue
            satellites.append(TleSatellite(name=name, tle1=tle1, tle2=tle2, is_default=is_default))
        return satellites

    def get_satellite_tle(self, constellation: str, satellite_name: str) -> dict[str, object] | None:
        """Return one satellite TLE entry from the newest cached file."""
        normalized = self._normalize_constellation(constellation)
        cached_file = self.get_cached_tle_file(normalized)
        if cached_file is None:
            return None
        tle_data = cached_file.read_text(encoding="utf-8")
        for satellite in self.parse_tle_text(tle_data, normalized, default_only=False):
            if satellite.name == satellite_name:
                return satellite.to_dict()
        return None

    def _resolve_cache_dir(self, configured_cache_dir: object) -> Path:
        """Resolve a configured cache directory against the repository root."""
        path = Path(str(configured_cache_dir))
        return path if path.is_absolute() else self.project_root / path

    def _tle_sources(self) -> Mapping[str, Any]:
        """Return configured TLE sources keyed by lowercase constellation."""
        sources = self.preferences.get("tle_sources", {})
        return {str(key).lower(): value for key, value in sources.items()}

    def _normalize_constellation(self, constellation: str) -> str:
        """Normalize a constellation name for config/cache lookup."""
        return str(constellation).strip().lower()

    def _default_satellites(self, constellation: str) -> set[str]:
        """Return configured default satellite names for a constellation."""
        source = self._tle_sources().get(self._normalize_constellation(constellation), {})
        return set(source.get("default_satellites", []) or [])
