"""GUI-owned service package with lazy public exports.

Service modules are imported lazily so lightweight verification tools and
configuration-only workflows can import one service without triggering optional
prediction, planner, or Qt-backed dependencies.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "LocalMapAssetServer",
    "LocationRecord",
    "LocationSaveResult",
    "LocationService",
    "LocationServiceError",
    "LocationValidationError",
    "MapAssetRequestHandler",
    "PlannerHandoffError",
    "PlannerHandoffPayload",
    "PlannerHandoffService",
    "PreferenceSavePlan",
    "PreferenceSnapshot",
    "PreferenceValidationError",
    "PreferenceValidationIssue",
    "PreferenceValidationResult",
    "PreferenceValidationSeverity",
    "PreferencesService",
    "PreferencesServiceError",
    "PredictionCsvExportRequest",
    "PredictionCsvExportResult",
    "PredictionExportError",
    "PredictionExportProjection",
    "PredictionExportService",
    "GuiRuntimePaths",
]

_LOCATION_EXPORTS = {
    "LocationRecord",
    "LocationSaveResult",
    "LocationService",
    "LocationServiceError",
    "LocationValidationError",
}

_MAP_EXPORTS = {
    "LocalMapAssetServer",
    "MapAssetRequestHandler",
}

_HANDOFF_EXPORTS = {
    "PlannerHandoffError",
    "PlannerHandoffPayload",
    "PlannerHandoffService",
}

_EXPORT_SERVICE_EXPORTS = {
    "PredictionCsvExportRequest",
    "PredictionCsvExportResult",
    "PredictionExportError",
    "PredictionExportProjection",
    "PredictionExportService",
}


_RUNTIME_PATH_EXPORTS = {
    "GuiRuntimePaths",
}

_PREFERENCES_EXPORTS = {
    "PreferenceSavePlan",
    "PreferenceSnapshot",
    "PreferenceValidationError",
    "PreferenceValidationIssue",
    "PreferenceValidationResult",
    "PreferenceValidationSeverity",
    "PreferencesService",
    "PreferencesServiceError",
}


def __getattr__(name: str) -> Any:
    """Lazily expose service classes without importing unrelated services."""
    if name in _LOCATION_EXPORTS:
        from gui.services import location_service as module

        return getattr(module, name)
    if name in _MAP_EXPORTS:
        from gui.services import map_asset_server as module

        return getattr(module, name)
    if name in _HANDOFF_EXPORTS:
        from gui.services import planner_handoff_service as module

        return getattr(module, name)
    if name in _EXPORT_SERVICE_EXPORTS:
        from gui.services import prediction_export_service as module

        return getattr(module, name)
    if name in _PREFERENCES_EXPORTS:
        from gui.services import preferences_service as module

        return getattr(module, name)
    if name in _RUNTIME_PATH_EXPORTS:
        from gui.services import runtime_paths as module

        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
