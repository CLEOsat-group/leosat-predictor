"""Qt-free task-keyed activity state for the GUI-v2 shell."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    """One active GUI operation.

    Parameters
    ----------
    task_key : str
        Stable identifier used to update and finish the operation.
    message : str
        Current user-facing progress message.
    detail : str, optional
        Short source or workflow description.
    sequence : int, optional
        Monotonic update sequence used to select the most recent activity.
    """

    task_key: str
    message: str
    detail: str = ""
    sequence: int = 0


class ActivityState:
    """Maintain overlapping activities without depending on Qt.

    The newest started or updated activity owns the visible progress message,
    while older entries remain registered until their matching task key ends.
    """

    def __init__(self) -> None:
        self._entries: OrderedDict[str, ActivityEntry] = OrderedDict()
        self._sequence = 0

    @property
    def is_busy(self) -> bool:
        """Return whether at least one activity is active."""

        return bool(self._entries)

    @property
    def active_task_keys(self) -> tuple[str, ...]:
        """Return active task keys in presentation order."""

        return tuple(self._entries)

    @property
    def current(self) -> ActivityEntry | None:
        """Return the most recently started or updated activity."""

        if not self._entries:
            return None
        return next(reversed(self._entries.values()))

    def begin(self, task_key: str, message: str, *, detail: str = "") -> ActivityEntry:
        """Start or replace one task-keyed activity."""

        key = self._normalize_key(task_key)
        entry = ActivityEntry(
            task_key=key,
            message=self._normalize_message(message),
            detail=str(detail or "").strip(),
            sequence=self._next_sequence(),
        )
        self._entries[key] = entry
        self._entries.move_to_end(key)
        return entry

    def update(self, task_key: str, message: str, *, detail: str | None = None) -> ActivityEntry | None:
        """Update an existing activity and make it the visible activity."""

        key = self._normalize_key(task_key)
        previous = self._entries.get(key)
        if previous is None:
            return None
        entry = ActivityEntry(
            task_key=key,
            message=self._normalize_message(message),
            detail=previous.detail if detail is None else str(detail or "").strip(),
            sequence=self._next_sequence(),
        )
        self._entries[key] = entry
        self._entries.move_to_end(key)
        return entry

    def end(self, task_key: str) -> ActivityEntry | None:
        """Remove and return one activity, or ``None`` for an unknown key."""

        key = self._normalize_key(task_key)
        return self._entries.pop(key, None)

    def clear(self) -> None:
        """Remove all active activities."""

        self._entries.clear()

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    @staticmethod
    def _normalize_key(task_key: str) -> str:
        key = str(task_key or "").strip()
        if not key:
            raise ValueError("Activity task key must not be empty.")
        return key

    @staticmethod
    def _normalize_message(message: str) -> str:
        return str(message or "Working…").strip() or "Working…"


__all__ = ["ActivityEntry", "ActivityState"]
