"""Shared TLE cache, download, and parsing service.

This service is intentionally independent of the desktop GUI and Flask route
handlers.  GUI widgets and web routes should call this module instead of owning
separate cache, network, and parser implementations.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Any

import requests

from src.config import Config
from src.services.omm_csv import is_omm_csv, omm_csv_to_tle_text, to_omm_csv_url

logger = logging.getLogger(__name__)

# Celestrak refreshes GP data every 2 hours and allows only one download per
# update per IP address; repeated HTTP errors (50 in 2 hours) get the IP
# firewalled, so never request more often than this.
MIN_DOWNLOAD_INTERVAL = timedelta(hours=2)

# Celestrak GROUP names that no longer exist, mapped to their replacement.
_RETIRED_GROUPS = {"noaa": "weather"}


class TleRateLimitedError(RuntimeError):
    """Raised when a TLE source refuses a download due to rate limiting.

    Celestrak returns HTTP 403 from both the supplemental (``sup-gp.php``) and
    the regular (``gp.php``) endpoints when the same data is re-requested from
    the same IP address before the next 2-hourly update -- even when the earlier
    download was made by another program or computer on the same network.
    Callers can catch this and fall back to a cached copy.
    """


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
        wants_download = force_download or cached_file is None or self.is_tle_expired(cached_file)
        if wants_download and cached_file is not None and self._age(cached_file) < MIN_DOWNLOAD_INTERVAL:
            # Celestrak has no newer data yet; a request would only be refused.
            logger.info(
                "TLE cache for %s is less than %s old; Celestrak updates every 2 hours, using %s.",
                normalized,
                MIN_DOWNLOAD_INTERVAL,
                cached_file.name,
            )
            wants_download = False
        if wants_download and self._is_blocked(normalized):
            # A recent 403 means another request would be refused again and
            # count toward Celestrak's firewall limit, so do not send one.
            if cached_file is None:
                raise TleRateLimitedError(self._rate_limit_message(normalized, self._blocked_detail(normalized)))
            logger.warning(
                "TLE download for %s was refused recently; using cached file %s.",
                normalized,
                cached_file.name,
            )
            wants_download = False

        if wants_download:
            try:
                tle_data = self.download_tle_data(normalized)
                cached_file = self.save_tle_to_cache(normalized, tle_data)
                self._blocked_marker(normalized).unlink(missing_ok=True)
            except RuntimeError as exc:
                # Download failed (rate limit via TleRateLimitedError, network
                # error, or server error).  Fall back to the newest cached copy
                # when one exists so a refresh inside the window still works.
                if isinstance(exc, TleRateLimitedError):
                    self._mark_blocked(normalized, str(exc))
                if cached_file is None:
                    if isinstance(exc, TleRateLimitedError):
                        raise TleRateLimitedError(self._rate_limit_message(normalized, str(exc))) from exc
                    raise
                logger.warning(
                    "TLE download for %s failed (%s); using cached file %s.",
                    normalized,
                    exc,
                    cached_file.name,
                )
                tle_data = cached_file.read_text(encoding="utf-8")
        else:
            tle_data = cached_file.read_text(encoding="utf-8")

        satellites = self.parse_tle_text(tle_data, normalized, default_only=default_only)
        return [satellite.to_dict() for satellite in satellites], cached_file

    def download_tle_data(self, constellation: str) -> str:
        """Download three-line TLE text for a configured constellation.

        Tries the configured ``url`` first, then an optional ``fallback_url``
        (e.g. the regular ``gp.php?GROUP=`` data for a constellation whose
        primary source is the supplemental ``sup-gp.php`` endpoint).  Celestrak
        URLs are requested as OMM CSV, which includes objects with 6-digit
        catalog numbers, and converted to TLE text (see
        :mod:`src.services.omm_csv`).

        Raises
        ------
        TleRateLimitedError
            When every candidate source refused with HTTP 403 (rate limiting).
        RuntimeError
            When the sources failed for any other reason.
        """
        normalized = self._normalize_constellation(constellation)
        source = self._tle_sources().get(normalized, {})
        url = source.get("url")
        if not url:
            raise ValueError(f"No URL found for constellation: {constellation}")

        candidates = [("primary", self._current_url(url))]
        fallback_url = source.get("fallback_url")
        if fallback_url:
            candidates.append(("fallback", self._current_url(fallback_url)))

        rate_limited = False
        failures: list[str] = []
        for label, candidate_url in candidates:
            try:
                response = requests.get(candidate_url, timeout=30)
            except requests.RequestException as exc:
                failures.append(f"{label} {candidate_url}: {exc}")
                continue
            if response.status_code == 200:
                tle_data = omm_csv_to_tle_text(response.text) if is_omm_csv(response.text) else response.text
                if not self.parse_tle_text(tle_data, normalized):
                    # Celestrak answers some bad queries with HTTP 200 and a
                    # message such as 'Invalid query: ... not found'; never
                    # cache that as satellite data.
                    reason = " ".join(response.text.split())[:200]
                    failures.append(f"{label} {candidate_url}: HTTP 200 without satellite data ({reason})")
                    continue
                if label != "primary":
                    logger.warning(
                        "TLE primary source for %s was unavailable; used %s source %s.",
                        normalized,
                        label,
                        candidate_url,
                    )
                return tle_data
            failure = f"{label} {candidate_url}: HTTP {response.status_code}"
            if response.status_code == 403:
                rate_limited = True
                # Celestrak explains the refusal in the body, e.g. "...since
                # your last successful download of GROUP=starlink at <time>".
                reason = " ".join(response.text.split())[:200]
                if reason:
                    failure = f"{failure} ({reason})"
            failures.append(failure)

        detail = "; ".join(failures)
        if rate_limited:
            raise TleRateLimitedError(
                f"TLE source rate-limited for {constellation}: {detail}"
            )
        raise RuntimeError(f"Failed to download TLE data for {constellation}: {detail}")

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

    def _current_url(self, url: str) -> str:
        """Upgrade a URL saved by an older version to the current Celestrak form.

        Saved user preferences override the bundled defaults, so they may still
        request ``FORMAT=tle`` or a retired ``GROUP``.
        """
        upgraded = to_omm_csv_url(url)
        for old_group, new_group in _RETIRED_GROUPS.items():
            upgraded = re.sub(
                rf"([?&]GROUP=){old_group}(?=&|$)", rf"\g<1>{new_group}", upgraded, flags=re.IGNORECASE
            )
        return upgraded

    def _age(self, path: Path) -> timedelta:
        """Return how long ago a file was last modified."""
        last_modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return datetime.now(timezone.utc) - last_modified

    def _blocked_marker(self, constellation: str) -> Path:
        """Return the marker file recording a recent rate-limit refusal."""
        return self.cache_dir / f"tle_{constellation}.blocked"

    def _mark_blocked(self, constellation: str, detail: str) -> None:
        """Record a rate-limit refusal so no request is sent for a while."""
        try:
            self._blocked_marker(constellation).write_text(detail, encoding="utf-8")
        except OSError as exc:  # pragma: no cover - cache dir not writable
            logger.warning("Unable to record TLE rate limit for %s: %s", constellation, exc)

    def _is_blocked(self, constellation: str) -> bool:
        """Return whether a rate-limit refusal was recorded recently."""
        marker = self._blocked_marker(constellation)
        return marker.exists() and self._age(marker) < MIN_DOWNLOAD_INTERVAL

    def _blocked_detail(self, constellation: str) -> str:
        """Return the recorded refusal detail, or an empty string."""
        try:
            return self._blocked_marker(constellation).read_text(encoding="utf-8")
        except OSError:
            return ""

    def _rate_limit_message(self, constellation: str, detail: str) -> str:
        """Return a user-facing explanation for a rate-limited download."""
        message = (
            "Celestrak allows one download per data update (every ~2 hours) per network. "
            f"Another app or computer on your network has already downloaded {constellation.upper()} "
            "and there is no cached copy here. Try again after the next update."
        )
        return f"{message} Details: {detail}" if detail else message

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
