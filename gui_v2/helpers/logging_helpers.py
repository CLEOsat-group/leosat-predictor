"""GUI-v2 logging helpers for routing backend logs into Qt consoles.

The prediction backend uses the standard :mod:`logging` package and writes
progress messages to the process console.  GUI-v1 attached a Qt text-edit
handler to the same logging stream, so long-running prediction diagnostics were
visible inside the application as well.  GUI-v2 keeps that behavior local to the
active setup page by attaching this handler only while a prediction is running.
"""

from __future__ import annotations

import logging
import re

from PyQt6.QtCore import Q_ARG, QMetaObject, QObject, Qt, pyqtSlot
from PyQt6.QtWidgets import QPlainTextEdit

ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\-_]|\[[0-?]*[ -/]*[@-~])")
GUI_LOG_FORMAT = "[%(asctime)s] %(levelname)-7s %(message)s"
GUI_LOG_DATE_FORMAT = "%H:%M:%S"
GUI_LOG_FORMATTER = logging.Formatter(GUI_LOG_FORMAT, datefmt=GUI_LOG_DATE_FORMAT)


def append_log_line(text_edit: QPlainTextEdit, message: str) -> None:
    """Append one log line, keeping the newest line visible at its start.

    The console must always show the latest line, anchored to its first
    character so long no-wrap messages read from the left rather than the
    tail.  Two subtleties make this load-bearing:

    * ``appendPlainText`` does not move this read-only widget's persistent text
      cursor to the new line, so it still sits at the ``StartOfBlock`` position
      left by the previous append.  Re-anchoring on that stale cursor pins the
      viewport to an older line while new content grows below it, which reads
      as the console "jumping to the top".  Moving the cursor to the document
      end first guarantees it lands on the line just appended.
    * QPlainTextEdit relayouts asynchronously, so ``setTextCursor`` (whose
      deferred ensure-cursor-visible pass anchors the viewport to the cursor
      column) is combined with explicit scrollbar resets to cover appends that
      do not trigger a relayout at all.
    """
    text_edit.appendPlainText(message)
    cursor = text_edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.movePosition(cursor.MoveOperation.StartOfBlock)
    text_edit.setTextCursor(cursor)
    horizontal_scrollbar = text_edit.horizontalScrollBar()
    if horizontal_scrollbar is not None:
        horizontal_scrollbar.setValue(horizontal_scrollbar.minimum())
    vertical_scrollbar = text_edit.verticalScrollBar()
    if vertical_scrollbar is not None:
        vertical_scrollbar.setValue(vertical_scrollbar.maximum())


class _GuiThreadLogAppender(QObject):
    """GUI-thread proxy so worker-thread log records append safely."""

    def __init__(self, text_edit: QPlainTextEdit) -> None:
        # Parenting to the destination widget pins this proxy to the GUI
        # thread and ties its lifetime to the widget's.
        super().__init__(text_edit)
        self._text_edit = text_edit

    @pyqtSlot(str)
    def append(self, message: str) -> None:
        append_log_line(self._text_edit, message)


class QtPlainTextEditLogHandler(logging.Handler):
    """Append standard logging records to a ``QPlainTextEdit`` safely.

    Parameters
    ----------
    text_edit : QPlainTextEdit
        Destination widget.  Records can be emitted from worker threads; the
        handler uses a queued Qt invocation so widget updates remain on the GUI
        thread.
    """

    def __init__(self, text_edit: QPlainTextEdit) -> None:
        super().__init__()
        self.text_edit = text_edit
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._appender = _GuiThreadLogAppender(text_edit)

    def emit(self, record: logging.LogRecord) -> None:
        """Format and append one logging record to the Qt console."""
        try:
            message = self.format(record)
        except Exception:
            self.handleError(record)
            return
        if message:
            message = ANSI_ESCAPE_RE.sub("", message)
        try:
            QMetaObject.invokeMethod(
                self._appender,
                "append",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, message),
            )
        except RuntimeError:
            # The destination widget can be destroyed while a worker is ending.
            # Dropping late log records is safer than keeping the GUI alive.
            return


__all__ = (
    "ANSI_ESCAPE_RE",
    "GUI_LOG_FORMAT",
    "GUI_LOG_DATE_FORMAT",
    "GUI_LOG_FORMATTER",
    "QtPlainTextEditLogHandler",
    "append_log_line",
)
