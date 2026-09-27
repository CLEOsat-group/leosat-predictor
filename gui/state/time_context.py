"""Time-context state helpers for the GUI header.

This module is intentionally Qt-free. It computes display-ready clock values
for lightweight GUI presentation. It does not provide external time synchronization,
observatory authority, astronomical-time calculations, or prediction-time semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any


_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class TimeContextSnapshot:
    """Display-ready time-context values.

    Parameters
    ----------
    local_time : str
        Local wall-clock time formatted for compact header display.
    utc_time : str
        UTC time formatted for compact header display.
    observatory_time : str, default: "Not configured"
        Local civil time at the configured observing site. If the location does
        not provide a usable time-zone name, a bounded fallback is used.
    """

    local_time: str
    utc_time: str
    observatory_time: str = "Not configured"


def create_time_context_snapshot(
    now: datetime | None = None,
    *,
    observatory_context: Mapping[str, Any] | None = None,
) -> TimeContextSnapshot:
    """Create a display-ready time-context snapshot.

    Parameters
    ----------
    now : datetime, optional
        Reference time. Naive values are interpreted as local time and converted
        to an aware local datetime for display.
    observatory_context : Mapping[str, Any], optional
        Optional configured observatory mapping with at least a ``name`` key.

    Returns
    -------
    TimeContextSnapshot
        Formatted local, UTC, and observatory-context values.
    """
    local_now = _as_local_time(now)
    utc_now = local_now.astimezone(timezone.utc)
    return TimeContextSnapshot(
        local_time=local_now.strftime(_TIME_FORMAT),
        utc_time=utc_now.strftime(_TIME_FORMAT),
        observatory_time=_format_observatory_context(observatory_context),
    )


def _as_local_time(value: datetime | None) -> datetime:
    """Return ``value`` as an aware local datetime."""
    if value is None:
        return datetime.now().astimezone()
    if value.tzinfo is None:
        return value.astimezone()
    return value.astimezone()


def _format_observatory_context(context: Mapping[str, Any] | None) -> str:
    """Return local civil time at the configured observing site."""
    if not isinstance(context, Mapping):
        return "Not configured"
    observatory_tz = _observatory_timezone(context)
    return datetime.now(tz=observatory_tz).strftime(_TIME_FORMAT)


def _observatory_timezone(context: Mapping[str, Any]) -> tzinfo:
    """Return the best available time zone for a configured observing site.

    GUI locations currently store latitude/longitude but usually do not yet
    store an IANA time-zone identifier. Task 44A therefore uses a conservative
    order of precedence: explicit ``timezone``/``timezone_name`` field, known
    Chilean observatory location, then a deterministic longitude-based fixed
    offset fallback. The fallback is non-authoritative but keeps the OBS row a
    time value instead of a site-name label.
    """
    timezone_name = str(context.get("timezone") or context.get("timezone_name") or "").strip()
    if timezone_name:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            pass

    name = str(context.get("name", "")).lower()
    latitude = _coerce_float(context.get("latitude"))
    longitude = _coerce_float(context.get("longitude"))
    if "chile" in name or (latitude is not None and longitude is not None and -56.0 <= latitude <= -17.0 and -76.0 <= longitude <= -66.0):
        try:
            return ZoneInfo("America/Santiago")
        except ZoneInfoNotFoundError:
            return timezone(timedelta(hours=-4))

    if longitude is not None:
        offset_hours = max(-12, min(14, round(longitude / 15.0)))
        return timezone(timedelta(hours=offset_hours))
    return datetime.now().astimezone().tzinfo or timezone.utc


def _coerce_float(value: object) -> float | None:
    """Return ``value`` as ``float`` or ``None`` when conversion fails."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
