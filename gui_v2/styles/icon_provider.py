"""Theme-aware SVG icon loading for GUI v2.

Only repository-owned, licensed assets under :mod:`gui_v2.assets.icons` are
loaded.  Icons are rendered into cached pixmaps for the active semantic theme;
widgets retain their text labels and receive an empty icon if an asset cannot
be loaded.
"""

from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
import re
from weakref import WeakSet

from PyQt6.QtCore import QByteArray, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QAbstractButton, QApplication, QWidget

from gui_v2.styles.theme_tokens import ThemePalette, palette_for


_LOGGER = logging.getLogger(__name__)
_ICON_ROOT = Path(__file__).resolve().parents[1] / "assets" / "icons"
_ICON_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")
_PAINT_PATTERN = re.compile(
    rb"(?P<prefix>\b(?:fill|stroke)\s*(?:=\s*[\"']|:)\s*)"
    rb"#[0-9a-fA-F]{3,8}"
)
_RENDER_SIZES = (16, 18, 24, 32, 36)
_REGISTERED_HOSTS: WeakSet[QWidget] = WeakSet()
_THEME_PROPERTY = "guiV2Theme"
_ICON_NAME_PROPERTY = "guiV2ThemedIconName"
_ICON_SIZE_PROPERTY = "guiV2ThemedIconSize"


def _active_theme_name(application: QApplication | None = None) -> str:
    """Return the normalized theme name without importing package helpers."""

    app = application or QApplication.instance()
    if app is None:
        return "dark"
    configured = str(app.property(_THEME_PROPERTY) or "dark").strip().lower()
    return "light" if configured == "light" else "dark"


def _asset_path(icon_name: str) -> Path:
    """Return the validated path for one icon asset.

    Parameters
    ----------
    icon_name : str
        Icon basename without the ``icon_`` prefix or ``.svg`` suffix.

    Returns
    -------
    pathlib.Path
        Repository/frozen-runtime asset path.

    Raises
    ------
    ValueError
        If the name contains path separators or unsupported characters.
    """

    normalized = str(icon_name).strip().lower()
    if not _ICON_NAME_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid GUI icon name: {icon_name!r}.")
    return _ICON_ROOT / f"icon_{normalized}.svg"


@lru_cache(maxsize=64)
def _source_svg(icon_name: str) -> bytes:
    """Read one SVG asset once."""

    path = _asset_path(icon_name)
    try:
        return path.read_bytes()
    except OSError as exc:
        _LOGGER.warning("Unable to load GUI icon asset %s: %s", path, exc)
        return b""


def _recolored_svg(source: bytes, color: str) -> bytes:
    """Return SVG bytes with painted fills/strokes replaced by ``color``."""

    replacement = color.encode("ascii")
    return _PAINT_PATTERN.sub(lambda match: match.group("prefix") + replacement, source)


def _render_pixmap(renderer: QSvgRenderer, size: int) -> QPixmap:
    """Render one validated SVG renderer into a transparent square pixmap."""

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    return pixmap


def _mode_colors(palette: ThemePalette) -> dict[tuple[QIcon.Mode, QIcon.State], str]:
    """Return stable high-contrast colors for every Qt icon mode.

    Qt may request ``Active`` or ``Selected`` pixmaps for hovered, checked, or
    selected controls.  Those modes must not silently switch light-theme icons
    back to white.  Use one explicit foreground for every enabled mode and
    retain the semantic disabled color only for disabled controls.
    """

    enabled_color = palette.icon_color
    return {
        (QIcon.Mode.Normal, QIcon.State.Off): enabled_color,
        (QIcon.Mode.Normal, QIcon.State.On): enabled_color,
        (QIcon.Mode.Active, QIcon.State.Off): enabled_color,
        (QIcon.Mode.Active, QIcon.State.On): enabled_color,
        (QIcon.Mode.Selected, QIcon.State.Off): enabled_color,
        (QIcon.Mode.Selected, QIcon.State.On): enabled_color,
        (QIcon.Mode.Disabled, QIcon.State.Off): palette.disabled_text,
        (QIcon.Mode.Disabled, QIcon.State.On): palette.disabled_text,
    }


@lru_cache(maxsize=128)
def _cached_icon(icon_name: str, theme_name: str) -> QIcon:
    """Build and cache a multi-resolution icon for one theme."""

    source = _source_svg(icon_name)
    if not source:
        return QIcon()

    icon = QIcon()
    pixmaps_by_color: dict[str, tuple[tuple[int, QPixmap], ...]] = {}
    for (mode, state), color in _mode_colors(palette_for(theme_name)).items():
        pixmaps = pixmaps_by_color.get(color)
        if pixmaps is None:
            renderer = QSvgRenderer(QByteArray(_recolored_svg(source, color)))
            if not renderer.isValid():
                _LOGGER.warning("Unable to render GUI icon asset: %s", icon_name)
                pixmaps = ()
            else:
                pixmaps = tuple(
                    (size, _render_pixmap(renderer, size))
                    for size in _RENDER_SIZES
                )
            pixmaps_by_color[color] = pixmaps
        for _size, pixmap in pixmaps:
            icon.addPixmap(pixmap, mode, state)
    return icon


def themed_icon(icon_name: str, application: QApplication | None = None) -> QIcon:
    """Return a cached icon rendered for the active theme.

    Parameters
    ----------
    icon_name : str
        Icon basename without ``icon_`` or ``.svg``.
    application : QApplication, optional
        Application whose active theme property should be read.
    """

    normalized = str(icon_name).strip().lower()
    try:
        _asset_path(normalized)
    except ValueError:
        _LOGGER.warning("Rejected invalid GUI icon name: %r", icon_name)
        return QIcon()
    return _cached_icon(normalized, _active_theme_name(application))


def set_themed_icon(button: QAbstractButton, icon_name: str, *, size: int = 18) -> None:
    """Assign a refreshable semantic icon to an existing text-labelled button."""

    logical_size = max(12, min(32, int(size)))
    button.setProperty(_ICON_NAME_PROPERTY, str(icon_name).strip().lower())
    button.setProperty(_ICON_SIZE_PROPERTY, logical_size)
    button.setIconSize(QSize(logical_size, logical_size))
    button.setIcon(themed_icon(icon_name))


def register_icon_host(host: QWidget) -> None:
    """Register a widget that owns non-button icons requiring theme refresh."""

    _REGISTERED_HOSTS.add(host)


def refresh_themed_icons(application: QApplication | None = None) -> None:
    """Refresh registered button and item icons after a live theme change."""

    app = application or QApplication.instance()
    if app is None:
        return

    for widget in QApplication.allWidgets():
        if not isinstance(widget, QAbstractButton):
            continue
        icon_name = widget.property(_ICON_NAME_PROPERTY)
        if not icon_name:
            continue
        size = widget.property(_ICON_SIZE_PROPERTY)
        try:
            logical_size = int(size)
        except (TypeError, ValueError):
            logical_size = 18
        widget.setIconSize(QSize(logical_size, logical_size))
        widget.setIcon(themed_icon(str(icon_name), app))

    for host in tuple(_REGISTERED_HOSTS):
        refresh = getattr(host, "refresh_theme_icons", None)
        if callable(refresh):
            refresh()


__all__ = (
    "refresh_themed_icons",
    "register_icon_host",
    "set_themed_icon",
    "themed_icon",
)
