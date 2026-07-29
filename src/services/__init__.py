"""Lazy public exports for shared services."""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["TleSatellite", "TleService", "generate_plot"]


def __getattr__(name: str) -> Any:
    """Resolve shared service exports without eager optional imports."""

    if name == "generate_plot":
        return importlib.import_module("src.services.plotter").generate_plot
    if name in {"TleSatellite", "TleService"}:
        return getattr(importlib.import_module("src.services.tle_service"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
