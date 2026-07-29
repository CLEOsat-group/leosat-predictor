"""Application bootstrap for the GUI replacement-path application."""

from __future__ import annotations

import logging
import signal
import sys
from collections.abc import Sequence

from PyQt6.QtCore import QCoreApplication, Qt, QTimer
from PyQt6.QtWidgets import QApplication

from gui.composition_root import create_composition
from gui.styles import apply_dashboard_theme

_logger = logging.getLogger(__name__)


def run(argv: Sequence[str] | None = None) -> int:
    """Launch the GUI application.

    Parameters
    ----------
    argv : sequence of str, optional
        Command-line arguments.  When omitted, ``sys.argv`` is used.

    Returns
    -------
    int
        Qt application exit code.
    """
    arguments = list(argv if argv is not None else sys.argv)
    app = QApplication.instance()
    owns_application = app is None
    if app is None:
        _prepare_qt_webengine_runtime()
        app = QApplication(arguments)

    composition = create_composition()
    theme = _safe_theme(composition.services.preferences_service)
    apply_dashboard_theme(app, theme)

    composition.window.show()
    if owns_application:
        _install_console_interrupt_handler(app)
        return int(app.exec())
    return 0


def _install_console_interrupt_handler(app: QApplication) -> None:
    """Install Ctrl+C handling for console-launched GUI sessions."""
    try:
        signal.signal(signal.SIGINT, lambda _signum, _frame: app.quit())
    except (ValueError, RuntimeError):
        _logger.debug("Unable to install SIGINT handler for GUI.", exc_info=True)
        return

    timer = QTimer(app)
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()
    app._gui_sigint_timer = timer  # type: ignore[attr-defined]


def _prepare_qt_webengine_runtime() -> None:
    """Set the Qt attribute required by the lazily imported map dialog.

    Importing ``PyQt6.QtWebEngineWidgets`` during application bootstrap loads a
    large native dependency set before the main window can appear.  Qt only
    requires the shared OpenGL-context attribute to be set before the first
    ``QCoreApplication`` instance when WebEngine is imported later.  The map
    dialog therefore remains fully available while normal startup avoids the
    WebEngine import cost.
    """
    if QCoreApplication.instance() is not None:
        _logger.debug(
            "QCoreApplication already exists; Qt WebEngine runtime attributes "
            "cannot be changed at this point."
        )
        return

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)


def _safe_theme(preferences_service: object) -> str:
    """Return the configured theme, falling back to dark on persistence errors."""
    try:
        preferences = preferences_service.load()  # type: ignore[attr-defined]
    except Exception:
        _logger.warning("Failed to load theme preference, falling back to dark.", exc_info=True)
        return "dark"
    theme = preferences.get("theme", "dark") if isinstance(preferences, dict) else "dark"
    return str(theme or "dark")
