"""Shared elevation/shadow helpers for GUI-v2 elevated-surface widgets.

``QGraphicsDropShadowEffect`` sits outside the QSS/``repolish()`` cascade
entirely, so theme-aware shadow tint needs its own explicit refresh call on
theme switch, mirroring the ``icon_provider`` registry/refresh-sweep pattern.
"""

from __future__ import annotations

from weakref import WeakSet

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from gui_v2.styles import active_theme_palette


_ELEVATION_HOSTS: "WeakSet[QWidget]" = WeakSet()
_DEFAULT_BLUR_RADIUS = 18
_Y_OFFSET = 3
_DARK_SHADOW_ALPHA = 140
_LIGHT_SHADOW_ALPHA = 60


def _shadow_color() -> QColor:
    palette = active_theme_palette()
    alpha = _LIGHT_SHADOW_ALPHA if palette.name == "light" else _DARK_SHADOW_ALPHA
    return QColor(0, 0, 0, alpha)


def apply_card_elevation(widget: QWidget, *, blur_radius: int = _DEFAULT_BLUR_RADIUS) -> None:
    """Attach (or refresh) a theme-aware drop shadow on one elevated surface.

    Idempotent: reuses an existing ``QGraphicsDropShadowEffect`` if the widget
    already has one, so this is safe to call once per widget in ``__init__``.
    """

    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsDropShadowEffect):
        effect = QGraphicsDropShadowEffect(widget)
        effect.setXOffset(0)
        effect.setYOffset(_Y_OFFSET)
        widget.setGraphicsEffect(effect)
    effect.setBlurRadius(blur_radius)
    effect.setColor(_shadow_color())
    _ELEVATION_HOSTS.add(widget)


def refresh_card_elevation() -> None:
    """Refresh shadow color on every registered elevated surface after a theme switch."""

    color = _shadow_color()
    for widget in tuple(_ELEVATION_HOSTS):
        effect = widget.graphicsEffect()
        if isinstance(effect, QGraphicsDropShadowEffect):
            effect.setColor(color)


__all__ = ("apply_card_elevation", "refresh_card_elevation")
