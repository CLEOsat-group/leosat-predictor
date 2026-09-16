"""Application-level theme helpers for the production GUI-v2 client."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gui_v2.styles.theme_tokens import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    PALETTES,
    ThemePalette,
    contrast_ratio,
    normalize_theme_name,
    palette_for,
)


_STYLE_DIR = Path(__file__).resolve().parent
_THEME_PROPERTY = "guiV2Theme"


def load_dashboard_stylesheet(theme: str | None = None) -> str:
    """Return the generated dashboard QSS for the requested theme."""

    theme_name = normalize_theme_name(theme)
    filename = f"dashboard_{theme_name}.qss"
    return (_STYLE_DIR / filename).read_text(encoding="utf-8")


def apply_dashboard_theme(application: Any, theme: str | None = None) -> str:
    """Apply one GUI-v2 theme and publish its identity on the application.

    Parameters
    ----------
    application : QApplication-like object
        Active Qt application instance.
    theme : str, optional
        Requested persisted theme value.

    Returns
    -------
    str
        Normalized theme name that was applied.
    """

    theme_name = normalize_theme_name(theme)
    application.setProperty(_THEME_PROPERTY, theme_name)
    application.setStyleSheet(load_dashboard_stylesheet(theme_name))

    # Refresh only widgets that explicitly opted into repository-owned themed
    # icons. Import lazily to keep the Qt-free token module independent.
    from gui_v2.styles.icon_provider import refresh_themed_icons
    from gui_v2.styles.effects import refresh_card_elevation

    refresh_themed_icons(application)
    refresh_card_elevation()
    return theme_name


def active_theme_name(application: Any | None = None) -> str:
    """Return the active application theme without inspecting stylesheet text."""

    app = application
    if app is None:
        try:
            from PyQt6.QtWidgets import QApplication

            app = QApplication.instance()
        except ImportError:
            app = None
    if app is None:
        return "dark"
    return normalize_theme_name(app.property(_THEME_PROPERTY))


def active_theme_palette(application: Any | None = None) -> ThemePalette:
    """Return the immutable palette for the active application theme."""

    return palette_for(active_theme_name(application))


def repolish(widget: Any) -> None:
    """Recompute QSS for a widget after a dynamic-property change."""

    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


__all__ = (
    "DARK_PALETTE",
    "LIGHT_PALETTE",
    "PALETTES",
    "ThemePalette",
    "active_theme_name",
    "active_theme_palette",
    "apply_dashboard_theme",
    "contrast_ratio",
    "load_dashboard_stylesheet",
    "normalize_theme_name",
    "palette_for",
    "repolish",
)
