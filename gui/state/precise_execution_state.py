"""Qt-free execution state for GUI precise prediction runs.

The objects in this module describe one validated precise prediction request and
its current GUI execution state. They deliberately contain no PyQt objects or
widget references so they can be tested and reused without a running
application.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class PreciseRunStatus(str, Enum):
    """Controlled GUI precise execution states."""

    IDLE = "idle"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PreciseExecutionSnapshot:
    """Immutable, widget-free input snapshot for one precise prediction run.

    Parameters
    ----------
    latitude_deg : float
        Observer latitude in degrees.
    longitude_deg : float
        Observer longitude in degrees.
    altitude_m : float
        Observer altitude in metres.
    start_datetime : datetime.datetime
        Start of the v1-compatible precise prediction window.
    end_datetime : datetime.datetime
        End of the v1-compatible precise prediction window.
    interval_seconds : int
        Sampling interval in seconds.
    constellation : str
        Selected constellation identifier.
    satellites : tuple of dict
        Selected satellite dictionaries with ``name``, ``tle1``, and ``tle2``
        fields preserved for the shared prediction worker.
    constraints : dict
        Precise visibility constraints passed to the worker.
    visibility_margin_minutes : int
        Visibility margin passed to the worker.
    source_file : str, optional
        Source TLE file path captured from the TLE selection card.
    """

    latitude_deg: float
    longitude_deg: float
    altitude_m: float
    start_datetime: datetime
    end_datetime: datetime
    interval_seconds: int
    constellation: str
    satellites: tuple[dict[str, Any], ...]
    constraints: dict[str, Any]
    visibility_margin_minutes: int
    source_file: str = ""

    @property
    def satellite_count(self) -> int:
        """Return the number of satellites included in this run request."""
        return len(self.satellites)


@dataclass(frozen=True, slots=True)
class PreciseExecutionState:
    """Display-ready execution state for the precise setup page."""

    status: PreciseRunStatus
    message: str
    detail: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def idle(cls, message: str = "Ready for precise setup.") -> "PreciseExecutionState":
        """Create an idle execution state."""
        return cls(status=PreciseRunStatus.IDLE, message=message)

    @classmethod
    def running(cls, *, satellite_count: int, started_at: datetime | None = None) -> "PreciseExecutionState":
        """Create a running state for an active precise worker."""
        timestamp = started_at or datetime.now().astimezone()
        return cls(
            status=PreciseRunStatus.RUNNING,
            message=f"Running precise prediction for {satellite_count} satellite(s).",
            detail="Cancel is available while the worker is active.",
            started_at=timestamp,
        )

    @classmethod
    def cancelling(cls) -> "PreciseExecutionState":
        """Create a cancelling state after a user cancellation request."""
        return cls(
            status=PreciseRunStatus.CANCELLING,
            message="Cancelling precise prediction.",
            detail="Waiting for the worker to acknowledge cancellation.",
        )

    @classmethod
    def succeeded(cls, *, row_count: int) -> "PreciseExecutionState":
        """Create a succeeded state after results are received."""
        return cls(
            status=PreciseRunStatus.SUCCEEDED,
            message=f"Precise run finished with {row_count} result row(s).",
            detail="The Precise Results page contains the model-backed table and CSV export actions.",
            completed_at=datetime.now().astimezone(),
        )

    @classmethod
    def failed(cls, message: str) -> "PreciseExecutionState":
        """Create a failed state with a user-facing error message."""
        return cls(status=PreciseRunStatus.FAILED, message="Precise prediction failed.", detail=message)

    @classmethod
    def cancelled(cls) -> "PreciseExecutionState":
        """Create a cancelled state after worker cancellation is acknowledged."""
        return cls(status=PreciseRunStatus.CANCELLED, message="Precise prediction cancelled.")


__all__ = ["PreciseExecutionSnapshot", "PreciseExecutionState", "PreciseRunStatus"]
