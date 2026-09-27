"""Page-local setup log card for GUI setup and handoff messages."""

from __future__ import annotations

from datetime import datetime
import logging

from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QPlainTextEdit, QWidget

from gui.helpers.logging_helpers import GUI_LOG_FORMATTER, QtPlainTextEditLogHandler, append_log_line
from gui.styles.effects import apply_card_elevation


class LogConsoleCard(QFrame):
    """Read-only page-local log console for setup and execution-handoff messages.

    The console reports page-local initialization, preference, location, TLE,
    validation, and workflow handoff messages without owning worker execution
    or result persistence.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        apply_card_elevation(self)
        self._logging_handler: QtPlainTextEditLogHandler | None = None

        grid = QGridLayout(self)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(10)

        title = QLabel("Setup Log", self)
        title.setObjectName("guiCardTitle")
        grid.addWidget(title, 0, 0)
        #
        # body = QLabel(
        #     "Page-local messages for preferences, location, TLE setup, "
        #     "validation, and workflow handoff.",
        #     self,
        # )
        # body.setObjectName("guiCardBody")
        # body.setWordWrap(True)
        # grid.addWidget(body, 1, 0)

        self._console = QPlainTextEdit(self)
        self._console.setObjectName("guiLogConsole")
        self._console.setReadOnly(True)
        # No-wrap from the start: the logging handler also enforces this on
        # attach, but flipping the mode mid-session (first prediction run)
        # forces a full relayout of existing wrapped content while worker logs
        # are flooding in, which raced the horizontal-scroll anchoring.
        self._console.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._console.setPlaceholderText("Setup log messages will appear here.")
        grid.addWidget(self._console, 2, 0)
        grid.setColumnStretch(0, 1)
        grid.setRowStretch(2, 1)

    def append_message(self, message: str, *, level: str = "INFO") -> None:
        """Append one timestamped setup message.

        Parameters
        ----------
        message : str
            Human-readable setup message.
        level : str, default: "INFO"
            Short message level label.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        normalized_level = str(level or "INFO").upper()
        append_log_line(self._console, f"[{timestamp}] {normalized_level:<7} {message}")
        self._console.verticalScrollBar().setValue(self._console.verticalScrollBar().maximum())


    def enable_logging_capture(self, *, level: int = logging.INFO) -> None:
        """Route standard backend logging into this page-local console.

        The handler is attached lazily and idempotently so prediction progress
        logs are visible in the active GUI page without duplicating handlers on
        repeated runs.

        Parameters
        ----------
        level : int, default: logging.INFO
            Minimum logging level captured in the GUI console.
        """
        if self._logging_handler is not None:
            return
        handler = QtPlainTextEditLogHandler(self._console)
        handler.setLevel(level)
        handler.setFormatter(GUI_LOG_FORMATTER)
        logging.getLogger().addHandler(handler)
        self._logging_handler = handler

    def disable_logging_capture(self) -> None:
        """Detach this console from the standard logging stream."""
        handler = self._logging_handler
        if handler is None:
            return
        root_logger = logging.getLogger()
        try:
            root_logger.removeHandler(handler)
        except ValueError:
            pass
        handler.close()
        self._logging_handler = None

    def clear_log(self) -> None:
        """Clear all page-local setup messages."""
        self._console.clear()
