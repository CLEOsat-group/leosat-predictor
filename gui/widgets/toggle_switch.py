"""Animated theme-aware toggle switch, a drop-in ``QCheckBox`` replacement."""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, pyqtProperty
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QCheckBox, QWidget

from gui.styles import active_theme_palette


_TOGGLE_ANIMATION_DURATION_MS = 220
_TOGGLE_ANIMATION_EASING = QEasingCurve.Type.OutCubic
_KNOB_MARGIN = 3.0
_LABEL_SPACING = 8


class ToggleSwitch(QCheckBox):
    """Animated sliding toggle switch.

    Extends ``QCheckBox`` directly so ``isChecked()``/``setChecked()``, the
    ``stateChanged``/``toggled`` signals, and any ``objectName``-based QSS
    selectors on the widget itself keep working unchanged. The constructor
    signature matches ``QCheckBox``'s own ``(text, parent)`` order, so
    existing ``QCheckBox("label", parent)`` call sites are drop-in
    replacements.

    Painting is fully custom (track, knob, and label text) rather than
    layering on top of Qt's native checkbox indicator, since Qt's default
    ``CE_CheckBox`` control draws the indicator and text as one unit and
    cannot be told to render only the text half.
    """

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        track_width: int = 40,
        track_height: int = 22,
    ) -> None:
        super().__init__(text, parent)
        self._track_width = track_width
        self._track_height = track_height
        self._knob_position = self._on_position() if self.isChecked() else self._off_position()
        self._animation = QPropertyAnimation(self, b"knobPosition", self)
        self._animation.setDuration(_TOGGLE_ANIMATION_DURATION_MS)
        self._animation.setEasingCurve(_TOGGLE_ANIMATION_EASING)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self._animate_to_state)

    def _off_position(self) -> float:
        return _KNOB_MARGIN

    def _on_position(self) -> float:
        return self._track_width - self._track_height + _KNOB_MARGIN

    def _animate_to_state(self, checked: bool) -> None:
        self._animation.stop()
        self._animation.setStartValue(self._knob_position)
        self._animation.setEndValue(self._on_position() if checked else self._off_position())
        self._animation.start()

    def getKnobPosition(self) -> float:
        """Return the current knob x-offset (animated Qt property)."""

        return self._knob_position

    def setKnobPosition(self, value: float) -> None:
        """Set the knob x-offset and repaint (animated Qt property)."""

        self._knob_position = value
        self.update()

    knobPosition = pyqtProperty(float, getKnobPosition, setKnobPosition)

    def hitButton(self, pos) -> bool:  # noqa: N802 - Qt API
        return self.contentsRect().contains(pos)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt API
        metrics = self.fontMetrics()
        text = self.text()
        text_width = metrics.horizontalAdvance(text) if text else 0
        spacing = _LABEL_SPACING if text else 0
        width = self._track_width + spacing + text_width + 4
        height = max(self._track_height + 6, metrics.height() + 6)
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt API
        return self.sizeHint()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Paint the track, knob, and label text; no native indicator is drawn."""

        del event
        palette = active_theme_palette()
        enabled = self.isEnabled()

        track_rect = QRectF(
            0.0,
            (self.height() - self._track_height) / 2.0,
            float(self._track_width),
            float(self._track_height),
        )
        if not enabled:
            track_color = QColor(palette.disabled_surface)
        elif self.isChecked():
            track_color = QColor(palette.accent)
        else:
            track_color = QColor(palette.border_strong)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        radius = self._track_height / 2.0
        painter.drawRoundedRect(track_rect, radius, radius)

        knob_diameter = self._track_height - 2 * _KNOB_MARGIN
        knob_rect = QRectF(
            self._knob_position,
            track_rect.top() + _KNOB_MARGIN,
            knob_diameter,
            knob_diameter,
        )
        knob_color = QColor(palette.disabled_text) if not enabled else QColor("#FFFFFF")
        painter.setBrush(knob_color)
        painter.drawEllipse(knob_rect)

        text = self.text()
        if text:
            text_color = QColor(palette.text_primary if enabled else palette.disabled_text)
            painter.setPen(text_color)
            text_rect = QRectF(
                self._track_width + _LABEL_SPACING,
                0.0,
                max(0.0, self.width() - self._track_width - _LABEL_SPACING),
                float(self.height()),
            )
            painter.drawText(
                text_rect,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                text,
            )
        painter.end()


__all__ = ("ToggleSwitch",)
