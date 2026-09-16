"""Theme-aware loading feedback for existing asynchronous GUI operations."""

from __future__ import annotations

from collections import OrderedDict
from time import monotonic

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from gui_v2.styles import active_theme_palette
from gui_v2.styles.effects import apply_card_elevation


_SPINNER_ROTATION_DURATION_MS = 900
_SPINNER_SHADOW_BLUR_RADIUS = 10


class LoadingSpinner(QWidget):
    """Small timer-driven custom-painted loading spinner.

    The widget paints only the spinner arc.  Parent overlay geometry is managed
    outside ``paintEvent`` so painting never mutates layout state.
    """

    def __init__(self, parent: QWidget | None = None, *, logical_size: int = 34) -> None:
        super().__init__(parent)
        self.setObjectName("guiV2LoadingSpinner")
        self.setFixedSize(logical_size, logical_size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        apply_card_elevation(self, blur_radius=_SPINNER_SHADOW_BLUR_RADIUS)
        self._angle = 0
        self._rotation_animation = QVariantAnimation(self)
        self._rotation_animation.setStartValue(0)
        self._rotation_animation.setEndValue(360)
        self._rotation_animation.setDuration(_SPINNER_ROTATION_DURATION_MS)
        self._rotation_animation.setLoopCount(-1)
        # Linear per-lap is intentional: constant angular velocity is correct for
        # a perpetual spinner. An eased curve (e.g. InOutCubic) would cause a
        # visible "pulse" every revolution instead of smooth continuous motion.
        self._rotation_animation.setEasingCurve(QEasingCurve.Type.Linear)
        self._rotation_animation.valueChanged.connect(self._set_angle)

    @property
    def is_running(self) -> bool:
        """Return whether the rotation animation is active."""

        return self._rotation_animation.state() == QAbstractAnimation.State.Running

    def start(self) -> None:
        """Start animation without changing widget geometry."""

        if self._rotation_animation.state() != QAbstractAnimation.State.Running:
            self._rotation_animation.start()
        self.show()
        self.update()

    def stop(self) -> None:
        """Stop animation and reset the arc angle."""

        self._rotation_animation.stop()
        self._angle = 0
        self.update()

    def _set_angle(self, value: object) -> None:
        self._angle = int(value)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        """Paint a high-DPI-safe antialiased spinner arc."""

        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(active_theme_palette().spinner), 4.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        inset = 5.0
        arc_rect = QRectF(inset, inset, self.width() - 2 * inset, self.height() - 2 * inset)
        painter.translate(QPointF(self.width() / 2.0, self.height() / 2.0))
        painter.rotate(float(self._angle))
        painter.translate(QPointF(-self.width() / 2.0, -self.height() / 2.0))
        painter.drawArc(arc_rect, 0, 16 * 270)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.stop()
        super().hideEvent(event)


class LoadingOverlay(QWidget):
    """Delayed, task-keyed loading overlay for asynchronous GUI operations.

    Multiple operations may overlap.  Ending one task never hides the overlay
    while another task remains active.
    """

    def __init__(
        self,
        parent: QWidget,
        *,
        default_delay_ms: int = 250,
        minimum_visible_ms: int = 350,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("guiV2LoadingOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._default_delay_ms = max(0, int(default_delay_ms))
        self._minimum_visible_ms = max(0, int(minimum_visible_ms))
        self._tasks: OrderedDict[str, str] = OrderedDict()
        self._shown_at: float | None = None

        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._show_if_active)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_now)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.addStretch(1)

        self.panel = QFrame(self)
        self.panel.setObjectName("guiV2LoadingPanel")
        apply_card_elevation(self.panel)
        self.panel.setMaximumWidth(560)
        panel_layout = QHBoxLayout(self.panel)
        panel_layout.setContentsMargins(18, 14, 18, 14)
        panel_layout.setSpacing(12)

        self.spinner = LoadingSpinner(self.panel)
        panel_layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignVCenter)
        self.message_label = QLabel("Working…", self.panel)
        self.message_label.setObjectName("guiV2LoadingMessage")
        self.message_label.setWordWrap(True)
        panel_layout.addWidget(self.message_label, 1, Qt.AlignmentFlag.AlignVCenter)

        root.addWidget(self.panel, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(1)

        parent.installEventFilter(self)
        self.hide()
        self._sync_geometry()

    @property
    def active_task_keys(self) -> tuple[str, ...]:
        """Return active task keys in insertion order."""

        return tuple(self._tasks)

    def begin(self, task_key: str, message: str, *, delay_ms: int | None = None) -> None:
        """Start or update one loading task."""

        key = self._normalize_task_key(task_key)
        self._tasks[key] = str(message or "Working…").strip() or "Working…"
        self._tasks.move_to_end(key)
        self._update_message()
        self._hide_timer.stop()
        if self.isVisible():
            self.raise_()
            self.spinner.start()
            return
        wait_ms = self._default_delay_ms if delay_ms is None else max(0, int(delay_ms))
        self._show_timer.start(wait_ms)

    def update(self, task_key: str, message: str) -> None:
        """Update an active task message without changing overlap state."""

        key = self._normalize_task_key(task_key)
        if key not in self._tasks:
            return
        self._tasks[key] = str(message or "Working…").strip() or "Working…"
        self._tasks.move_to_end(key)
        self._update_message()

    def end(self, task_key: str) -> None:
        """End one task and hide only when no tasks remain."""

        key = self._normalize_task_key(task_key)
        self._tasks.pop(key, None)
        if self._tasks:
            self._update_message()
            return
        self._show_timer.stop()
        if not self.isVisible():
            self.spinner.stop()
            return
        elapsed_ms = 0 if self._shown_at is None else int((monotonic() - self._shown_at) * 1000)
        remaining_ms = max(0, self._minimum_visible_ms - elapsed_ms)
        if remaining_ms:
            self._hide_timer.start(remaining_ms)
        else:
            self._hide_now()

    def clear(self) -> None:
        """Clear all tasks and hide immediately during shutdown/reset."""

        self._tasks.clear()
        self._show_timer.stop()
        self._hide_timer.stop()
        self._hide_now()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        if watched is self.parentWidget() and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
            QEvent.Type.Show,
            QEvent.Type.LayoutRequest,
        ):
            self._sync_geometry()
        return super().eventFilter(watched, event)

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.StyleChange,
            QEvent.Type.PaletteChange,
            QEvent.Type.ApplicationPaletteChange,
        ):
            self.spinner.update()
            QWidget.update(self)

    def _show_if_active(self) -> None:
        if not self._tasks:
            return
        self._sync_geometry()
        self._shown_at = monotonic()
        self._update_message()
        self.show()
        self.raise_()
        self.spinner.start()

    def _hide_now(self) -> None:
        self._hide_timer.stop()
        self.spinner.stop()
        self._shown_at = None
        self.hide()

    def _update_message(self) -> None:
        if self._tasks:
            self.message_label.setText(next(reversed(self._tasks.values())))

    def _sync_geometry(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())

    @staticmethod
    def _normalize_task_key(task_key: str) -> str:
        key = str(task_key or "").strip()
        if not key:
            raise ValueError("Loading task key must not be empty.")
        return key


__all__ = ("LoadingOverlay", "LoadingSpinner")
