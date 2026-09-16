"""Shared package exports for LEOSat Predictor.

This package is used by both the web and GUI products.  Keep this module free
of heavy runtime imports so GUI-only preference/configuration modules can use
shared contracts without requiring optional prediction dependencies at import
time.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

app: Any


def __getattr__(name: str) -> Any:
    """Resolve legacy top-level exports lazily.

    Top-level eager imports of prediction/web services pull optional astronomy
    dependencies into unrelated GUI-v2 configuration workflows.  Lazy export
    resolution preserves the historical public names while keeping package
    import side effects minimal.
    """
    if name == "app":
        return importlib.import_module("src.main").app
    if name == "Config":
        return importlib.import_module("src.config").Config
    if name == "SatellitePredictor":
        return importlib.import_module("src.prediction_core").SatellitePredictor
    if name == "generate_plot":
        return importlib.import_module("src.services").generate_plot
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


try:
    Config = __getattr__("Config")
    logging.basicConfig(
        level=logging.getLevelName(Config().get("LOG_LEVEL", "INFO")),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
except Exception:  # pragma: no cover - defensive package-import guard
    logging.basicConfig(level=logging.INFO)

# Keep noisy third-party debug logs out of normal app output.
logging.getLogger("pyorbital").setLevel(logging.INFO)
logging.getLogger("pyorbital.tlefile").setLevel(logging.INFO)


__all__ = ["app", "SatellitePredictor", "generate_plot", "Config"]
