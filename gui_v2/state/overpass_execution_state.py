"""Qt-free execution state for GUI-v2 overpass runs.

The objects in this module describe one validated overpass run request and its
current GUI execution state.  They deliberately hold no widget references.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OverpassRunStatus(str, Enum):
    """Controlled GUI-v2 overpass execution states."""

    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OverpassExecutionSnapshot:
    """Immutable, widget-free input snapshot for one overpass run."""

    latitude_deg: float
    longitude_deg: float
    altitude_m: float
    start_datetime_utc: datetime
    days: int
    constellation: str
    satellites: tuple[dict[str, Any], ...]
    constraints: dict[str, Any]
    source_file: str = ""

    @property
    def satellite_count(self) -> int:
        """Return the number of satellites included in this run request."""
        return len(self.satellites)


@dataclass(frozen=True, slots=True)
class OverpassExecutionState:
    """Display-ready execution state for the overpass setup page."""

    status: OverpassRunStatus
    message: str
    detail: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def idle(cls, message: str = "Ready for overpass setup.") -> "OverpassExecutionState":
        """Create an idle execution state."""
        return cls(status=OverpassRunStatus.IDLE, message=message)

    @classmethod
    def running(cls, *, satellite_count: int, started_at: datetime | None = None) -> "OverpassExecutionState":
        """Create a running state for an active overpass worker."""
        timestamp = started_at or datetime.now().astimezone()
        return cls(
            status=OverpassRunStatus.RUNNING,
            message=f"Running overpass prediction for {satellite_count} satellite(s).",
            detail="Cancel is available while the worker is active.",
            started_at=timestamp,
        )

    @classmethod
    def cancelling(cls) -> "OverpassExecutionState":
        """Create a cancelling state after a user cancellation request."""
        return cls(
            status=OverpassRunStatus.CANCELLING,
            message="Cancelling overpass prediction.",
            detail="Waiting for the worker to acknowledge cancellation.",
        )

    @classmethod
    def succeeded(cls, *, row_count: int) -> "OverpassExecutionState":
        """Create a succeeded state after results are received."""
        return cls(
            status=OverpassRunStatus.SUCCEEDED,
            message=f"Overpass run finished with {row_count} result row(s).",
            detail="Results are available on the Overpass Results page.",
            completed_at=datetime.now().astimezone(),
        )

    @classmethod
    def failed(cls, message: str) -> "OverpassExecutionState":
        """Create a failed state with a user-facing error message."""
        return cls(status=OverpassRunStatus.FAILED, message="Overpass prediction failed.", detail=message)

    @classmethod
    def cancelled(cls) -> "OverpassExecutionState":
        """Create a cancelled state after worker cancellation is acknowledged."""
        return cls(status=OverpassRunStatus.CANCELLED, message="Overpass prediction cancelled.")


__all__ = ["OverpassExecutionSnapshot", "OverpassExecutionState", "OverpassRunStatus"]
