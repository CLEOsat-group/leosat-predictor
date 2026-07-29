"""Compatibility wrapper for the shared TLE service.

New GUI and web code should import :class:`src.services.tle_service.TleService`
directly.  This wrapper preserves the legacy ``TLEManager`` import path for any
remaining external or archival callers during the Task 38 transition.
"""

from __future__ import annotations

from src.services.tle_service import TleService


class TLEManager(TleService):
    """Backward-compatible alias for :class:`TleService`."""
