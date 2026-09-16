"""Qt-free status/event state model for GUI v2.

The state object defined here is intentionally independent from PyQt so it can
be used by future presenters, verifiers, and tests without importing the GUI
runtime.  The visual rendering belongs to the shell-owned header status widget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class StatusLevel(StrEnum):
    """Controlled GUI v2 status levels.

    The vocabulary is intentionally small.  ``BUSY`` is reserved for the later
    async-task contract, but defining it now prevents status vocabulary churn.
    """

    READY = "ready"
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    BUSY = "busy"


@dataclass(frozen=True, slots=True)
class StatusEvent:
    """Display-ready status/event message for the GUI v2 global status surface.

    Parameters
    ----------
    level : StatusLevel
        Semantic level of the event.
    message : str
        Primary user-facing message.
    detail : str, optional
        Short contextual detail exposed through the status-surface tooltip.
    source : str, optional
        Non-visual source identifier.  Defaults to ``"gui_v2"``.
    timestamp : datetime, optional
        Creation timestamp.  The default uses the local timezone-aware time.
    auto_clear_ms : int or None, optional
        Optional GUI-side auto-clear interval for temporary messages.  The
        model only stores the policy; the status widget owns the QTimer.
    """

    level: StatusLevel
    message: str
    detail: str = ""
    source: str = "gui_v2"
    timestamp: datetime = field(default_factory=lambda: datetime.now().astimezone())
    auto_clear_ms: int | None = None

    @classmethod
    def ready(cls, message: str, *, detail: str = "", source: str = "gui_v2") -> "StatusEvent":
        """Create a calm baseline-ready status event."""
        return cls(level=StatusLevel.READY, message=message, detail=detail, source=source)

    @classmethod
    def info(
        cls,
        message: str,
        *,
        detail: str = "",
        source: str = "gui_v2",
        auto_clear_ms: int | None = None,
    ) -> "StatusEvent":
        """Create an informational status event."""
        return cls(
            level=StatusLevel.INFO,
            message=message,
            detail=detail,
            source=source,
            auto_clear_ms=auto_clear_ms,
        )

    @classmethod
    def success(
        cls,
        message: str,
        *,
        detail: str = "",
        source: str = "gui_v2",
        auto_clear_ms: int | None = None,
    ) -> "StatusEvent":
        """Create a successful-action status event."""
        return cls(
            level=StatusLevel.SUCCESS,
            message=message,
            detail=detail,
            source=source,
            auto_clear_ms=auto_clear_ms,
        )

    @classmethod
    def warning(
        cls,
        message: str,
        *,
        detail: str = "",
        source: str = "gui_v2",
        auto_clear_ms: int | None = None,
    ) -> "StatusEvent":
        """Create a warning status event."""
        return cls(
            level=StatusLevel.WARNING,
            message=message,
            detail=detail,
            source=source,
            auto_clear_ms=auto_clear_ms,
        )

    @classmethod
    def error(cls, message: str, *, detail: str = "", source: str = "gui_v2") -> "StatusEvent":
        """Create an error status event."""
        return cls(level=StatusLevel.ERROR, message=message, detail=detail, source=source)

    @classmethod
    def busy(cls, message: str, *, detail: str = "", source: str = "gui_v2") -> "StatusEvent":
        """Create a reserved busy status event for future async-task reporting."""
        return cls(level=StatusLevel.BUSY, message=message, detail=detail, source=source)


DEFAULT_READY_EVENT = StatusEvent.ready(
    "Ready.",
    detail="Idle",
)

__all__ = ["DEFAULT_READY_EVENT", "StatusEvent", "StatusLevel"]
