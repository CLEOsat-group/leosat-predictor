"""Header-level time-context widget for GUI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QWidget

from gui.state.time_context import TimeContextSnapshot, create_time_context_snapshot


class TimeContextWidget(QFrame):
    """Live local/UTC/observatory-local time panel for the GUI header.

    The widget uses a lightweight GUI-thread ``QTimer``. It does not create
    worker threads, perform network synchronization, perform astronomical-time
    calculations, or claim authoritative observatory time.
    """

    def __init__(self, parent: QWidget | None = None, *, interval_ms: int = 1000) -> None:
        super().__init__(parent)
        self.setObjectName("guiTimeContext")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._observatory_context: Mapping[str, Any] | None = None

        self._timer = QTimer(self)
        self._timer.setObjectName("guiTimeContextTimer")
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.refresh)

        layout = QGridLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(3)

        self._local_label = self._create_key_label("LOCAL")
        self._utc_label = self._create_key_label("UTC")
        self._observatory_label = self._create_key_label("OBS")

        self._local_value = self._create_value_label()
        self._utc_value = self._create_value_label()
        self._observatory_value = self._create_value_label()

        layout.addWidget(self._local_label, 0, 0, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._local_value, 0, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._utc_label, 1, 0, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._utc_value, 1, 1, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._observatory_label, 2, 0, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._observatory_value, 2, 1, alignment=Qt.AlignmentFlag.AlignLeft)

        self.refresh()

    @property
    def is_running(self) -> bool:
        """Return whether the GUI-thread timer is active."""
        return self._timer.isActive()

    def configure_observatory_context(self, location: Mapping[str, Any] | None) -> None:
        """Set the configured site used for the OBS local-time row."""
        self._observatory_context = dict(location) if isinstance(location, Mapping) else None
        if isinstance(location, Mapping):
            name = str(location.get("name", "Configured site")).strip() or "Configured site"
            latitude = location.get("latitude", "—")
            longitude = location.get("longitude", "—")
            altitude = location.get("altitude", "—")
            timezone_name = location.get("timezone") or location.get("timezone_name") or "inferred from location"
            self._observatory_value.setToolTip(
                f"Observatory local time for: {name}\n"
                f"Latitude: {latitude}\nLongitude: {longitude}\nAltitude: {altitude} m\n"
                f"Time zone: {timezone_name}"
            )
        else:
            self._observatory_value.setToolTip("No observatory location configured.")
        self.refresh()

    def start(self) -> None:
        """Start the live clock update loop in the widget's GUI thread."""
        self.refresh()
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        """Stop the live clock update loop."""
        if self._timer.isActive():
            self._timer.stop()

    def refresh(self, snapshot: TimeContextSnapshot | None = None) -> None:
        """Refresh displayed time values.

        Parameters
        ----------
        snapshot : TimeContextSnapshot, optional
            Precomputed values, primarily useful for deterministic future tests.
            When omitted, the current local/UTC time is sampled.
        """
        current = snapshot or create_time_context_snapshot(observatory_context=self._observatory_context)
        self._local_value.setText(current.local_time)
        self._utc_value.setText(current.utc_time)
        self._observatory_value.setText(current.observatory_time)

    def _create_key_label(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setObjectName("guiTimeContextKey")
        return label

    def _create_value_label(self) -> QLabel:
        label = QLabel("—", self)
        label.setObjectName("guiTimeContextValue")
        label.setMinimumWidth(168)
        return label
