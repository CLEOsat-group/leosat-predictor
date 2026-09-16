"""State/value objects for GUI v2."""

from __future__ import annotations

from gui_v2.state.activity_state import ActivityEntry, ActivityState
from gui_v2.state.status_event import DEFAULT_READY_EVENT, StatusEvent, StatusLevel
from gui_v2.state.time_context import TimeContextSnapshot, create_time_context_snapshot
from gui_v2.state.task_contract import (
    CancellationRequest,
    TaskErrorSummary,
    TaskEvent,
    TaskKind,
    TaskProgress,
    TaskResultSummary,
    TaskState,
    allowed_next_states,
    can_transition,
    status_event_from_task_event,
    status_level_for_task_state,
    validate_transition,
)

__all__ = [
    "ActivityEntry",
    "ActivityState",
    "DEFAULT_READY_EVENT",
    "StatusEvent",
    "StatusLevel",
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
    "TimeContextSnapshot",
    "create_time_context_snapshot",
    "PreciseInputSnapshot",
    "PreciseValidationIssue",
    "PreciseValidationSeverity",
    "PreciseValidationState",
    "validate_precise_inputs",
    "PreciseExecutionSnapshot",
    "PreciseExecutionState",
    "PreciseRunStatus",
    "PreciseResultSummary",
    "PreciseResultsState",
    "summarize_precise_results",
    "PreferenceSnapshot",
    "PreferenceSavePlan",
    "PreferenceValidationIssue",
    "PreferenceValidationResult",
    "PreferenceValidationSeverity",
]

from gui_v2.state.overpass_execution_state import (
    OverpassExecutionSnapshot,
    OverpassExecutionState,
    OverpassRunStatus,
)
from gui_v2.state.overpass_results_state import (
    OverpassResultSummary,
    OverpassResultsState,
    summarize_overpass_results,
)

from gui_v2.state.precise_execution_state import (
    PreciseExecutionSnapshot,
    PreciseExecutionState,
    PreciseRunStatus,
)
from gui_v2.state.precise_results_state import (
    PreciseResultSummary,
    PreciseResultsState,
    summarize_precise_results,
)

from gui_v2.state.precise_validation import (
    PreciseInputSnapshot,
    PreciseValidationState,
    ValidationIssue as PreciseValidationIssue,
    ValidationSeverity as PreciseValidationSeverity,
    validate_precise_inputs,
)


from gui_v2.state.preferences_state import (
    PreferenceSavePlan,
    PreferenceSnapshot,
    PreferenceValidationIssue,
    PreferenceValidationResult,
    PreferenceValidationSeverity,
)
