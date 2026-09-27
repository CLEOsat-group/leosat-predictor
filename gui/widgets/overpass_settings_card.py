"""Overpass-specific settings card for GUI."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from PyQt6.QtCore import QDate, QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import QDateEdit, QFrame, QGridLayout, QLabel, QLineEdit, QSizePolicy, QWidget

from gui.styles import repolish
from gui.styles.effects import apply_card_elevation

LogCallback = Callable[[str, str], None]


class OverpassSettingsCard(QFrame):
    """Overpass settings card for start date and prediction duration.

    The card owns only the overpass date window.  It deliberately does not
    embed the legacy page-level time widget because GUI already exposes the
    global time context in the dashboard header.
    """

    stateChanged = pyqtSignal()

    def __init__(
        self,
        *,
        preferences: Mapping[str, Any],
        log_callback: LogCallback | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._preferences = preferences
        self._log_callback = log_callback
        self.setObjectName("guiCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        apply_card_elevation(self)

        grid = QGridLayout(self)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        title = QLabel("Overpass Settings", self)
        title.setObjectName("guiCardTitle")
        grid.addWidget(title, 0, 0, 1, 2)

        self.start_date_edit = QDateEdit(self)
        self.start_date_edit.setObjectName("guiOverpassStartDateEdit")
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setDate(QDate.currentDate())
        self.start_date_edit.setMinimumWidth(132)
        self.start_date_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.days_input = QLineEdit(self)
        self.days_input.setObjectName("guiOverpassDaysInput")
        self.days_input.setText(str(self._default_days()))
        self.days_input.setFixedWidth(54)
        self.days_input.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._add_labeled_field(grid, 1, "Start Date (Local):", self.start_date_edit)
        self._add_labeled_field(grid, 2, "Days to Predict:", self.days_input)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(4, 1)

        self.start_date_edit.dateChanged.connect(lambda _date: self.stateChanged.emit())
        self.days_input.textChanged.connect(lambda _text: self.stateChanged.emit())
        self._log(f"Overpass settings initialized with {self.days_input.text()} day(s) to predict.", "INFO")


    def apply_preferences(self, preferences: Mapping[str, Any], *, preserve_user_edits: bool = True) -> bool:
        """Apply overpass defaults without resetting active user edits.

        The current start date is never changed by preference application.  The
        day-count field is updated only when it still matches the old default
        or is empty.
        """
        old_default_days = self._default_days()
        current_days = self.days_input.text().strip()
        self._preferences = preferences
        new_default_days = self._default_days()
        updated = False

        if (not preserve_user_edits) or current_days in {"", str(old_default_days)}:
            blocker = QSignalBlocker(self.days_input)
            try:
                self.days_input.setText(str(new_default_days))
            finally:
                del blocker
            updated = True

        if updated:
            self._log(f"Overpass default days applied: {new_default_days}.", "INFO")
        else:
            self._log("Overpass default days changed; active Days field preserved.", "INFO")
        self.stateChanged.emit()
        return updated

    def values(self) -> dict[str, object]:
        """Return current raw overpass settings values."""
        return {
            "start_date": self.start_date_edit.date().toString("yyyy-MM-dd"),
            "days": self.days_input.text().strip(),
        }

    def validation_snapshot(self) -> dict[str, object]:
        """Return raw overpass settings consumed by central validation."""
        return self.values()

    def set_field_validity(self, field_id: str, valid: bool, message: str = "") -> None:
        """Apply field-level validation styling without changing layout geometry."""
        field_map = {
            "settings.start_date": self.start_date_edit,
            "settings.days": self.days_input,
        }
        widget = field_map.get(field_id)
        if widget is None:
            return
        _set_validation_state(widget, "valid" if valid else "error", message)

    def _add_labeled_field(self, grid: QGridLayout, row: int, label_text: str, widget: QWidget) -> None:
        label = QLabel(label_text, self)
        label.setObjectName("guiFieldLabel")
        grid.addWidget(label, row, 0)
        grid.addWidget(widget, row, 1)

    def _default_days(self) -> int:
        raw_value = self._preferences.get("default_days", 3)
        try:
            return max(1, min(365, int(raw_value)))
        except (TypeError, ValueError):
            return 3

    def _log(self, message: str, level: str = "INFO") -> None:
        if self._log_callback is not None:
            self._log_callback(message, level)


def _set_validation_state(widget: QWidget, state: str, tooltip: str = "") -> None:
    widget.setProperty("validationState", state)
    widget.setToolTip(tooltip)
    repolish(widget)
