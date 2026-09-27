"""Qt-free task-reporting contract for future GUI workflows.

This module defines the vocabulary and value objects that future GUI
presenters and task runners must use when reporting long-running operations.
It is deliberately independent from PyQt and does not start, schedule, or run
any work.  Concrete worker implementations are reserved for later tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from gui.state.status_event import StatusEvent, StatusLevel


class TaskKind(StrEnum):
    """Stable identifiers for future GUI operation families."""

    OVERPASS_PREDICTION = "overpass_prediction"
    PRECISE_PREDICTION = "precise_prediction"
    PLANNER_GENERATION = "planner_generation"
    PLANNER_DIAGNOSTICS = "planner_diagnostics"
    EXPORT = "export"
    LOAD_DATA = "load_data"
    VALIDATION = "validation"


class TaskState(StrEnum):
    """Lifecycle states for future long-running GUI tasks."""

    IDLE = "idle"
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TaskProgress:
    """Optional bounded or indeterminate progress for a task event.

    Parameters
    ----------
    current : int or None, optional
        Current completed unit count.  If provided, it must be non-negative.
    total : int or None, optional
        Total expected unit count.  If provided, it must be positive.
    message : str, optional
        Short progress detail suitable for compact status surfaces.
    """

    current: int | None = None
    total: int | None = None
    message: str = ""

    def __post_init__(self) -> None:
        """Validate progress bounds."""
        if self.current is not None and self.current < 0:
            raise ValueError("TaskProgress.current must be non-negative when provided.")
        if self.total is not None and self.total <= 0:
            raise ValueError("TaskProgress.total must be positive when provided.")
        if self.current is not None and self.total is not None and self.current > self.total:
            raise ValueError("TaskProgress.current cannot exceed TaskProgress.total.")

    def compact_detail(self) -> str:
        """Return a concise display detail for status surfaces."""
        if self.current is not None and self.total is not None:
            return f"{self.current} / {self.total}"
        if self.message:
            return self.message
        if self.current is not None:
            return f"{self.current} completed"
        return ""


@dataclass(frozen=True, slots=True)
class TaskResultSummary:
    """Small completion summary that avoids carrying heavy result data."""

    message: str
    detail: str = ""
    produced_rows: int | None = None

    def __post_init__(self) -> None:
        """Validate result summary fields."""
        if not self.message.strip():
            raise ValueError("TaskResultSummary.message must be non-empty.")
        if self.produced_rows is not None and self.produced_rows < 0:
            raise ValueError("TaskResultSummary.produced_rows must be non-negative when provided.")


@dataclass(frozen=True, slots=True)
class TaskErrorSummary:
    """Safe error summary for compact status and diagnostics surfaces."""

    message: str
    detail: str = ""
    error_type: str = ""

    def __post_init__(self) -> None:
        """Validate error summary fields."""
        if not self.message.strip():
            raise ValueError("TaskErrorSummary.message must be non-empty.")


@dataclass(frozen=True, slots=True)
class CancellationRequest:
    """Cooperative cancellation request for a future task.

    This object represents intent only.  It must not be interpreted as thread
    termination, process termination, or immediate task shutdown.
    """

    task_id: str
    reason: str = "User requested cancellation."
    requested_at: datetime = field(default_factory=lambda: datetime.now().astimezone())

    def __post_init__(self) -> None:
        """Validate cancellation request fields."""
        if not self.task_id.strip():
            raise ValueError("CancellationRequest.task_id must be non-empty.")
        if not self.reason.strip():
            raise ValueError("CancellationRequest.reason must be non-empty.")


@dataclass(frozen=True, slots=True)
class TaskEvent:
    """Immutable event emitted by future presenters or task runners.

    Parameters
    ----------
    task_id : str
        Stable identifier for one task instance.
    kind : TaskKind
        Operation family.
    state : TaskState
        Current task lifecycle state.
    title : str
        Short user-facing title for compact status surfaces.
    message : str, optional
        Optional user-facing event message.
    progress : TaskProgress or None, optional
        Optional progress payload.
    result : TaskResultSummary or None, optional
        Optional lightweight completion summary for successful events.
    error : TaskErrorSummary or None, optional
        Required for failed events.
    timestamp : datetime, optional
        Event creation time.
    """

    task_id: str
    kind: TaskKind
    state: TaskState
    title: str
    message: str = ""
    progress: TaskProgress | None = None
    result: TaskResultSummary | None = None
    error: TaskErrorSummary | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now().astimezone())

    def __post_init__(self) -> None:
        """Validate task-event invariants."""
        if not self.task_id.strip():
            raise ValueError("TaskEvent.task_id must be non-empty.")
        if not self.title.strip():
            raise ValueError("TaskEvent.title must be non-empty.")
        if self.state is TaskState.FAILED and self.error is None:
            raise ValueError("TaskEvent.error is required when state is FAILED.")
        if self.state is TaskState.CANCELLED and self.result is not None:
            raise ValueError("CANCELLED events must not carry result data.")
        if self.state is TaskState.SUCCEEDED and self.error is not None:
            raise ValueError("SUCCEEDED events must not carry error data.")
        if self.state is TaskState.FAILED and self.result is not None:
            raise ValueError("FAILED events must not carry result data.")
        if self.progress is not None and self.state not in {
            TaskState.QUEUED,
            TaskState.RUNNING,
            TaskState.CANCELLING,
        }:
            raise ValueError("Progress is only valid for QUEUED, RUNNING, or CANCELLING events.")


_ALLOWED_TRANSITIONS: Final[MappingProxyType[TaskState, frozenset[TaskState]]] = MappingProxyType(
    {
        TaskState.IDLE: frozenset({TaskState.QUEUED, TaskState.RUNNING}),
        TaskState.QUEUED: frozenset({TaskState.RUNNING, TaskState.CANCELLED}),
        TaskState.RUNNING: frozenset({TaskState.CANCELLING, TaskState.SUCCEEDED, TaskState.FAILED}),
        TaskState.CANCELLING: frozenset({TaskState.CANCELLED, TaskState.FAILED}),
        TaskState.CANCELLED: frozenset(),
        TaskState.SUCCEEDED: frozenset(),
        TaskState.FAILED: frozenset(),
    }
)


_TASK_STATUS_LEVELS: Final[MappingProxyType[TaskState, StatusLevel]] = MappingProxyType(
    {
        TaskState.IDLE: StatusLevel.READY,
        TaskState.QUEUED: StatusLevel.BUSY,
        TaskState.RUNNING: StatusLevel.BUSY,
        TaskState.CANCELLING: StatusLevel.WARNING,
        TaskState.CANCELLED: StatusLevel.WARNING,
        TaskState.SUCCEEDED: StatusLevel.SUCCESS,
        TaskState.FAILED: StatusLevel.ERROR,
    }
)


def allowed_next_states(state: TaskState) -> frozenset[TaskState]:
    """Return the allowed next lifecycle states for ``state``."""
    return _ALLOWED_TRANSITIONS[state]


def can_transition(from_state: TaskState, to_state: TaskState) -> bool:
    """Return whether a state transition is allowed by the contract."""
    return to_state in _ALLOWED_TRANSITIONS[from_state]


def validate_transition(from_state: TaskState, to_state: TaskState) -> None:
    """Raise ``ValueError`` if a lifecycle transition is not allowed."""
    if not can_transition(from_state, to_state):
        raise ValueError(f"Invalid task transition: {from_state.value} -> {to_state.value}")


def status_level_for_task_state(state: TaskState) -> StatusLevel:
    """Return the Task 43H status-strip level for a task state."""
    return _TASK_STATUS_LEVELS[state]


def status_event_from_task_event(event: TaskEvent) -> StatusEvent:
    """Map a task event to a compact Task 43H ``StatusEvent``.

    The returned event is display-ready for the footer status strip, but this
    helper does not import or mutate any widget.
    """
    level = status_level_for_task_state(event.state)
    message = _message_for_task_event(event)
    detail = _detail_for_task_event(event)
    return StatusEvent(level=level, message=message, detail=detail, source="gui.task_contract")


def _message_for_task_event(event: TaskEvent) -> str:
    if event.message:
        return event.message
    if event.state is TaskState.IDLE:
        return "No workflow running."
    if event.state is TaskState.QUEUED:
        return f"{event.title} queued."
    if event.state is TaskState.RUNNING:
        return f"{event.title} running."
    if event.state is TaskState.CANCELLING:
        return f"Cancelling {event.title}..."
    if event.state is TaskState.CANCELLED:
        return f"{event.title} cancelled."
    if event.state is TaskState.SUCCEEDED:
        return event.result.message if event.result else f"{event.title} completed."
    if event.state is TaskState.FAILED:
        return event.error.message if event.error else f"{event.title} failed."
    return event.title


def _detail_for_task_event(event: TaskEvent) -> str:
    if event.progress is not None:
        return event.progress.compact_detail()
    if event.result is not None:
        if event.result.produced_rows is not None:
            return f"{event.result.produced_rows} rows"
        return event.result.detail
    if event.error is not None:
        return event.error.detail or event.error.error_type
    if event.state is TaskState.IDLE:
        return "Ready"
    if event.state is TaskState.QUEUED:
        return "Queued"
    if event.state is TaskState.RUNNING:
        return "Running"
    if event.state is TaskState.CANCELLING:
        return "Cancellation requested"
    if event.state is TaskState.CANCELLED:
        return "Cancelled"
    if event.state is TaskState.SUCCEEDED:
        return "Completed"
    if event.state is TaskState.FAILED:
        return "Failed"
    return ""


__all__ = [
    "CancellationRequest",
    "TaskErrorSummary",
    "TaskEvent",
    "TaskKind",
    "TaskProgress",
    "TaskResultSummary",
    "TaskState",
    "allowed_next_states",
    "can_transition",
    "status_event_from_task_event",
    "status_level_for_task_state",
    "validate_transition",
]
