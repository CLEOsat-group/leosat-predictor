"""Lazy public exports for shared model utilities."""

from __future__ import annotations

import importlib
from typing import Any

from .observatories import observatories

__all__ = [
    "LocationManager",
    "get_elevation",
    "observatories",
    "set_observatory_data",
]


def __getattr__(name: str) -> Any:
    """Resolve model exports without importing unrelated dependencies."""

    if name == "LocationManager":
        return importlib.import_module("src.models.location_manager").LocationManager
    if name in {"get_elevation", "set_observatory_data"}:
        return getattr(importlib.import_module("src.models.formatter"), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
