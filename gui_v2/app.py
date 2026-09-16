"""Application bootstrap for the GUI v2 replacement-path application."""

from __future__ import annotations

import logging
import signal
import sys
from collections.abc import Sequence

from PyQt6.QtCore import QCoreApplication, Qt, QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication, QWidget

from gui_v2.composition_root import create_composition
from gui_v2.styles import apply_dashboard_theme

_logger = logging.getLogger(__name__)

#: Preferred initial window size, clamped to the available screen work area.
_PREFERRED_WINDOW_SIZE = (1500, 950)


def run(argv: Sequence[str] | None = None) -> int:
    """Launch the GUI v2 application.

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

    _fit_window_to_screen(composition.window)
    composition.window.show()
    if owns_application:
        _install_console_interrupt_handler(app)
        return int(app.exec())
    return 0


def _fit_window_to_screen(window: QWidget) -> None:
    """Size the window to fit the available screen and center it.

    Without an explicit geometry, Qt sizes the window from its (wide) layout
    size hint and lets the window manager place it, which on smaller monitors
    left part of the window and its controls off-screen.  Clamping the initial
    size to the available work area and centering it keeps every control
    reachable on first launch regardless of monitor size.
    """
    screen = window.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()

    margin = 40
    preferred_width, preferred_height = _PREFERRED_WINDOW_SIZE
    width = min(preferred_width, available.width() - margin)
    height = min(preferred_height, available.height() - margin)
    if width <= 0 or height <= 0:
        return

    window.resize(width, height)
    frame = window.frameGeometry()
    frame.moveCenter(available.center())
    window.move(frame.topLeft())


def _install_console_interrupt_handler(app: QApplication) -> None:
    """Install Ctrl+C handling for console-launched GUI-v2 sessions."""
    try:
        signal.signal(signal.SIGINT, lambda _signum, _frame: app.quit())
    except (ValueError, RuntimeError):
        _logger.debug("Unable to install SIGINT handler for GUI v2.", exc_info=True)
        return

    timer = QTimer(app)
    timer.setInterval(200)
    timer.timeout.connect(lambda: None)
    timer.start()
    app._gui_v2_sigint_timer = timer  # type: ignore[attr-defined]


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
