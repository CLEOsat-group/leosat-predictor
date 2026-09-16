"""Header-integrated global status surface for GUI v2."""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QWidget

from gui_v2.styles import repolish
from gui_v2.state import DEFAULT_READY_EVENT, StatusEvent


class HeaderStatusWidget(QFrame):
    """Compact global status surface for the GUI v2 header.

    The widget renders the Qt-free :class:`~gui_v2.state.StatusEvent` model as a
    bounded header capsule.  It intentionally displays only a semantic level and
    a short message; detailed workflow traces remain in the page-local log
    consoles.
    """

    _MINIMUM_MESSAGE_WIDTH = 220
    _MAXIMUM_WIDGET_WIDTH = 680

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiV2HeaderStatusWidget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(360)
        # self.setMaximumWidth(self._MAXIMUM_WIDGET_WIDTH)

        self._ready_event = DEFAULT_READY_EVENT
        self._current_event = self._ready_event
        self._full_message = ""

        self._auto_clear_timer = QTimer(self)
        self._auto_clear_timer.setSingleShot(True)
        self._auto_clear_timer.timeout.connect(self.clear)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self._level_label = QLabel(self)
        self._level_label.setObjectName("guiV2HeaderStatusLevel")
        self._level_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._level_label.setMinimumWidth(68)
        layout.addWidget(self._level_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._message_label = QLabel(self)
        self._message_label.setObjectName("guiV2HeaderStatusMessage")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._message_label.setWordWrap(False)
        self._message_label.setMinimumWidth(0)
        # self._message_label.setMinimumWidth(self._MINIMUM_MESSAGE_WIDTH)
        self._message_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._message_label, 1, Qt.AlignmentFlag.AlignVCenter)

        self.set_event(self._ready_event)

    @property
    def current_event(self) -> StatusEvent:
        """Return the currently displayed status event."""
        return self._current_event

    def set_event(self, event: StatusEvent) -> None:
        """Render ``event`` and configure optional auto-clear behavior.

        Parameters
        ----------
        event : StatusEvent
            Qt-free status event to display in the header capsule.
        """
        self._auto_clear_timer.stop()
        self._current_event = event
        level = event.level.value
        self.setProperty("level", level)
        self._level_label.setProperty("level", level)
        self._message_label.setProperty("level", level)

        self._level_label.setText(event.level.value.upper())
        self._full_message = event.message.strip() or event.detail.strip() or "Ready."
        self._update_elided_message()
        self._update_tooltip(event)
        self._refresh_style()

        if event.auto_clear_ms is not None and event.auto_clear_ms > 0:
            self._auto_clear_timer.start(event.auto_clear_ms)

    def clear(self) -> None:
        """Return to the default ready event."""
        self.set_event(self._ready_event)

    def set_ready(self, message: str, detail: str = "") -> None:
        """Display a ready-level status message."""
        self.set_event(StatusEvent.ready(message, detail=detail))

    def set_info(self, message: str, detail: str = "", auto_clear_ms: int | None = None) -> None:
        """Display an informational status message."""
        self.set_event(StatusEvent.info(message, detail=detail, auto_clear_ms=auto_clear_ms))

    def set_success(self, message: str, detail: str = "", auto_clear_ms: int | None = None) -> None:
        """Display a success-level status message."""
        self.set_event(StatusEvent.success(message, detail=detail, auto_clear_ms=auto_clear_ms))

    def set_warning(self, message: str, detail: str = "", auto_clear_ms: int | None = None) -> None:
        """Display a warning-level status message."""
        self.set_event(StatusEvent.warning(message, detail=detail, auto_clear_ms=auto_clear_ms))

    def set_error(self, message: str, detail: str = "") -> None:
        """Display an error-level status message."""
        self.set_event(StatusEvent.error(message, detail=detail))

    def set_busy(self, message: str, detail: str = "") -> None:
        """Display a busy-level status message for active work."""
        self.set_event(StatusEvent.busy(message, detail=detail))

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Refresh message elision when the header allocates a new width."""
        super().resizeEvent(event)
        self._update_elided_message()

    def _update_elided_message(self) -> None:
        """Render the primary message with stable header-width elision."""
        available = max(self._MINIMUM_MESSAGE_WIDTH, self._message_label.width())
        metrics = QFontMetrics(self._message_label.font())
        text = metrics.elidedText(self._full_message, Qt.TextElideMode.ElideRight, available)
        self._message_label.setText(text)

    def _update_tooltip(self, event: StatusEvent) -> None:
        """Expose the full message/detail without expanding the header."""
        tooltip_parts = [event.message.strip()]
        if event.detail.strip():
            tooltip_parts.append(event.detail.strip())
        tooltip = "\n".join(part for part in tooltip_parts if part)
        self.setToolTip(tooltip)
        self._level_label.setToolTip(tooltip)
        self._message_label.setToolTip(tooltip)

    def _refresh_style(self) -> None:
        """Re-polish property-driven QSS after a level change."""
        for widget in (self, self._level_label, self._message_label):
            repolish(widget)
            widget.update()


__all__ = ["HeaderStatusWidget"]
