"""Composition root for the production GUI-v2 application.

The composition root is the single place where services and the main window are
constructed.  It keeps dependency wiring visible, separates bundled resources
from writable user data, and prevents views from constructing services ad hoc.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
import logging
from typing import Any

from gui_v2.main_window import MainWindow
from gui_v2.services import (
    LocationService,
    PlannerHandoffService,
    PredictionExportService,
    PreferencesService,
)
from gui_v2.services.runtime_paths import GuiRuntimePaths
from gui_v2.shell.navigation_model import build_navigation_tree
from src.models.location_manager import LocationManager
from src.services.tle_service import TleService

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceBundle:
    """GUI-local services available to the production desktop application."""

    prediction_export_service: PredictionExportService
    planner_handoff_service: PlannerHandoffService
    location_service: LocationService
    preferences_service: PreferencesService
    tle_service: Any
    tle_service_factory: Callable[[Mapping[str, Any] | None], Any]


@dataclass(frozen=True)
class Composition:
    """Top-level composed objects for GUI v2."""

    window: MainWindow
    services: ServiceBundle


def build_services(runtime_paths: GuiRuntimePaths | None = None) -> ServiceBundle:
    """Construct services used by the production GUI.

    Parameters
    ----------
    runtime_paths : GuiRuntimePaths, optional
        Explicit runtime paths.  When omitted, paths are discovered from the
        current source or frozen execution environment.

    Returns
    -------
    ServiceBundle
        Fully wired GUI service bundle.
    """

    paths = runtime_paths or GuiRuntimePaths.discover()
    _logger.debug(
        "Building GUI-v2 service bundle (frozen=%s, resources=%s, user_data=%s).",
        paths.frozen,
        paths.resource_root,
        paths.user_data_root,
    )

    prediction_export_service = PredictionExportService()
    preferences_service = PreferencesService(
        project_root=paths.resource_root,
        defaults_path=paths.defaults_path,
        user_preferences_path=paths.user_preferences_path,
    )
    try:
        preferences = preferences_service.load()
    except Exception as exc:  # pragma: no cover - defensive composition guard
        _logger.warning(
            "Unable to load preferences for TLE service; falling back to default config: %s",
            exc,
        )
        preferences = None

    tle_factory = partial(create_tle_service_from_preferences, runtime_paths=paths)
    return ServiceBundle(
        prediction_export_service=prediction_export_service,
        planner_handoff_service=PlannerHandoffService(
            export_service=prediction_export_service
        ),
        location_service=LocationService(
            location_manager=LocationManager(paths.user_locations_path)
        ),
        preferences_service=preferences_service,
        tle_service=tle_factory(preferences),
        tle_service_factory=tle_factory,
    )


def create_tle_service_from_preferences(
    preferences: Mapping[str, Any] | None,
    *,
    runtime_paths: GuiRuntimePaths | None = None,
) -> TleService:
    """Create a GUI-v2 TLE service from saved preferences.

    Parameters
    ----------
    preferences : mapping, optional
        Saved effective preference mapping.
    runtime_paths : GuiRuntimePaths, optional
        Runtime path set controlling bundled defaults and writable cache.

    Returns
    -------
    src.services.tle_service.TleService
        Shared TLE service wired to the GUI's writable cache directory.
    """

    paths = runtime_paths or GuiRuntimePaths.discover()
    normalized = dict(preferences) if isinstance(preferences, Mapping) else None
    configured_cache = (normalized or {}).get("tle_folder", "data/tle")
    return TleService(
        preferences=normalized,
        project_root=paths.resource_root,
        cache_dir=paths.resolve_tle_cache_dir(configured_cache),
    )


def create_composition(runtime_paths: GuiRuntimePaths | None = None) -> Composition:
    """Create the GUI-v2 main window and non-visual service bundle.

    Parameters
    ----------
    runtime_paths : GuiRuntimePaths, optional
        Explicit source/frozen runtime path set.

    Returns
    -------
    Composition
        Composed main window and service bundle.
    """

    services = build_services(runtime_paths=runtime_paths)
    sections = build_navigation_tree()
    window = MainWindow(sections=sections, services=services)
    _logger.info("GUI v2 composition created with %d navigation sections.", len(sections))
    return Composition(window=window, services=services)
