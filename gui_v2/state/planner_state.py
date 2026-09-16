"""Qt-free runtime state for the GUI-v2 Observation Planner port.

The state objects in this module intentionally avoid Qt imports.  They store
workflow readiness and lightweight metadata while large DataFrames and planner
backend objects are retained in :class:`PlannerRuntimeState`.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class PlannerGenerationStatus(Enum):
    """Lifecycle states for the GUI-v2 planner workflow."""

    IDLE = "idle"
    READY = "ready"
    LOADING = "loading"
    GENERATING = "generating"
    CANCELING = "canceling"
    COMPLETE = "complete"
    CANCELED = "canceled"
    ERROR = "error"


class PlannerLoadState(Enum):
    """Per-input loading states for planner setup data."""

    IDLE = "idle"
    LOADING = "loading"
    LOADED = "loaded"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class PlannerExportResult:
    """Qt-free result metadata for a completed planner export.

    Parameters
    ----------
    plan_path : pathlib.Path
        Main exported plan path.
    sidecar_path : pathlib.Path or None
        Optional diagnostics sidecar path written beside the plan.
    row_count : int
        Number of observation-plan rows exported.
    exported_at : datetime
        UTC timestamp captured when the export completed.
    """

    plan_path: Path
    sidecar_path: Path | None
    row_count: int
    exported_at: datetime


@dataclass(frozen=True, slots=True)
class PlannerDataReadiness:
    """Readiness flags for planner data surfaces."""

    visibility_loaded: bool = False
    tle_loaded: bool = False
    targets_loaded: bool = False
    plan_available: bool = False
    diagnostics_available: bool = False

    @property
    def ready_for_generation(self) -> bool:
        """Return whether the minimum planned inputs are available.

        GUI-v2 preserves GUI-v1 Observation Planner parity: plan generation
        requires loaded visibility rows only.  Loading a TLE file is an
        optional follow-up action used by Observation Info to enable Copy TLE
        for the currently selected satellite; it must not block generation.
        """
        return self.visibility_loaded


@dataclass(frozen=True, slots=True)
class PlannerSelectionSnapshot:
    """Stable identities for currently selected planner rows/items."""

    visibility_identity: object | None = None
    plan_identity: object | None = None


@dataclass(frozen=True, slots=True)
class PlannerRuntimeSnapshot:
    """Immutable snapshot of GUI-v2 planner runtime metadata."""

    readiness: PlannerDataReadiness = field(default_factory=PlannerDataReadiness)
    generation_status: PlannerGenerationStatus = PlannerGenerationStatus.IDLE
    visibility_file_path: str | None = None
    tle_file_path: str | None = None
    target_file_path: str | None = None
    visibility_row_count: int = 0
    visible_row_count: int = 0
    satellite_count: int = 0
    target_row_count: int = 0
    target_has_times: bool = False
    targets_applied: bool = False
    current_satellite_filter: str = "All Satellites"
    visibility_load_state: PlannerLoadState = PlannerLoadState.IDLE
    tle_load_state: PlannerLoadState = PlannerLoadState.DISABLED
    targets_load_state: PlannerLoadState = PlannerLoadState.IDLE
    coordinate_format: str = "colon"
    selected: PlannerSelectionSnapshot = field(default_factory=PlannerSelectionSnapshot)
    log_lines: tuple[str, ...] = ()
    status_message: str = "Planner setup is ready. Load visibility data to begin."
    last_error: str | None = None
    last_generated_plan_method: str | None = None
    last_export_path: str | None = None
    last_export_sidecar_path: str | None = None
    last_export_row_count: int = 0
    last_exported_at: datetime | None = None

    def with_status(
        self,
        message: str,
        *,
        generation_status: PlannerGenerationStatus | None = None,
        last_error: str | None = None,
    ) -> "PlannerRuntimeSnapshot":
        """Return a copy with an updated user-facing status message."""
        return replace(
            self,
            status_message=message,
            generation_status=generation_status or self.generation_status,
            last_error=last_error,
        )

    def with_log_line(self, message: str, *, max_lines: int = 200) -> "PlannerRuntimeSnapshot":
        """Return a copy with one appended log line."""
        if not message:
            return self
        lines = (*self.log_lines, message)
        if max_lines > 0:
            lines = lines[-max_lines:]
        return replace(self, log_lines=lines)

    def with_updates(self, **updates: object) -> "PlannerRuntimeSnapshot":
        """Return a copy with selected dataclass fields changed."""
        return replace(self, **updates)


@dataclass(slots=True)
class PlannerRuntimeState:
    """Mutable GUI-v2 planner state holder.

    Large data objects are intentionally typed as ``object | None`` here so the
    Qt-free state layer does not import pandas or planner backend modules.
    """

    snapshot: PlannerRuntimeSnapshot = field(default_factory=PlannerRuntimeSnapshot)
    visibility_dataframe: object | None = None
    base_dataframe: object | None = None
    view_dataframe: object | None = None
    target_dataframe: object | None = None
    generated_plan: object | None = None
    diagnostics: object | None = None
    tle_index: object | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def reset(self) -> PlannerRuntimeSnapshot:
        """Clear planner runtime state and return the new empty snapshot."""
        self.snapshot = PlannerRuntimeSnapshot()
        self.visibility_dataframe = None
        self.base_dataframe = None
        self.view_dataframe = None
        self.target_dataframe = None
        self.generated_plan = None
        self.diagnostics = None
        self.tle_index = None
        self.metadata.clear()
        return self.snapshot

    def update_snapshot(self, snapshot: PlannerRuntimeSnapshot) -> PlannerRuntimeSnapshot:
        """Store and return a new immutable snapshot."""
        self.snapshot = snapshot
        return self.snapshot


__all__ = (
    "PlannerDataReadiness",
    "PlannerExportResult",
    "PlannerGenerationStatus",
    "PlannerLoadState",
    "PlannerRuntimeSnapshot",
    "PlannerRuntimeState",
    "PlannerSelectionSnapshot",
)
