"""Precise prediction settings card for GUI."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from PyQt6.QtCore import QDate, QSignalBlocker, pyqtSignal
from PyQt6.QtGui import QDoubleValidator, QIntValidator
from PyQt6.QtWidgets import QComboBox, QDateEdit, QFrame, QGridLayout, QLabel, QLineEdit, QSizePolicy, QWidget

from gui.styles import repolish
from gui.styles.effects import apply_card_elevation

LogCallback = Callable[[str, str], None]

_INTERVAL_UNITS = ("seconds", "minutes", "hours")
_RANGE_LABELS = ("Morning", "Evening", "Both")
_RANGE_VALUES = {label.lower(): label for label in _RANGE_LABELS}


class PreciseSettingsCard(QFrame):
    """Precise setup card for time sampling and visibility constraints.

    The card owns only local field state. Cross-card readiness remains in
    ``PreciseSetupPage`` and ``validate_precise_inputs``.
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

        title = QLabel("Prediction Settings", self)
        title.setObjectName("guiCardTitle")
        grid.addWidget(title, 0, 0, 1, 5)

        self.start_date_edit = QDateEdit(self)
        self.start_date_edit.setObjectName("guiPreciseStartDateEdit")
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setDate(QDate.currentDate())
        self.start_date_edit.setMinimumWidth(132)
        self.start_date_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.interval_input = QLineEdit(self)
        self.interval_input.setObjectName("guiPreciseIntervalInput")
        self.interval_input.setValidator(QIntValidator(1, 86400, self.interval_input))
        self.interval_input.setText(str(self._default_interval()))
        self.interval_input.setFixedWidth(64)
        self.interval_input.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.interval_unit = QComboBox(self)
        self.interval_unit.setObjectName("guiPreciseIntervalUnitCombo")
        self.interval_unit.addItems(list(_INTERVAL_UNITS))
        self.interval_unit.setCurrentText(self._default_interval_unit())
        self.interval_unit.setFixedWidth(104)
        self.interval_unit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.prediction_range = QComboBox(self)
        self.prediction_range.setObjectName("guiPrecisePredictionRangeCombo")
        self.prediction_range.addItems(list(_RANGE_LABELS))
        self.prediction_range.setCurrentText(self._normalized_precise_range())
        self.prediction_range.setFixedWidth(104)
        self.prediction_range.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        constraints = self._visibility_constraints()
        double_validator = QDoubleValidator(0.0, 180.0, 2, self)
        double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)

        self.lowest_elevation_input = self._make_float_field(
            "guiPreciseLowestElevationInput",
            constraints.get("lowest_altitude_satellite", 30.0),
            double_validator,
        )
        self.sun_zenith_highest_input = self._make_float_field(
            "guiPreciseSunZenithHighestInput",
            constraints.get("sun_zenith_highest", 112.0),
            double_validator,
        )
        self.sun_zenith_lowest_input = self._make_float_field(
            "guiPreciseSunZenithLowestInput",
            constraints.get("sun_zenith_lowest", 99.0),
            double_validator,
        )

        self._add_label(grid, 1, 0, "Start Date (Local):")
        grid.addWidget(self.start_date_edit, 1, 1, 1, 2)
        self._add_label(grid, 2, 0, "Prediction Interval:")
        grid.addWidget(self.interval_input, 2, 1)
        grid.addWidget(self.interval_unit, 2, 2)
        self._add_label(grid, 3, 0, "Prediction Range:")
        grid.addWidget(self.prediction_range, 3, 1, 1, 2)

        self._add_label(grid, 1, 3, "Lowest Elevation (°):")
        grid.addWidget(self.lowest_elevation_input, 1, 4)
        self._add_label(grid, 2, 3, "Sun Zenith Highest (°):")
        grid.addWidget(self.sun_zenith_highest_input, 2, 4)
        self._add_label(grid, 3, 3, "Sun Zenith Lowest (°):")
        grid.addWidget(self.sun_zenith_lowest_input, 3, 4)

        # self.summary_label = QLabel(
        #     "Precise setup validates sampling interval, time-of-day range, and visibility constraints.",
        #     self,
        # )
        # self.summary_label.setObjectName("guiCardBody")
        # self.summary_label.setWordWrap(True)
        # grid.addWidget(self.summary_label, 4, 0, 1, 5)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 0)
        grid.setColumnStretch(4, 0)
        grid.setRowStretch(5, 1)

        self.start_date_edit.dateChanged.connect(lambda _date: self.stateChanged.emit())
        self.interval_input.textChanged.connect(lambda _text: self.stateChanged.emit())
        self.interval_unit.currentTextChanged.connect(lambda _text: self.stateChanged.emit())
        self.prediction_range.currentTextChanged.connect(lambda _text: self.stateChanged.emit())
        self.lowest_elevation_input.textChanged.connect(lambda _text: self.stateChanged.emit())
        self.sun_zenith_highest_input.textChanged.connect(lambda _text: self.stateChanged.emit())
        self.sun_zenith_lowest_input.textChanged.connect(lambda _text: self.stateChanged.emit())

        self._log(
            f"Precise settings initialized with interval {self.interval_input.text()} {self.interval_unit.currentText()}.",
            "INFO",
        )


    def apply_preferences(self, preferences: Mapping[str, Any], *, preserve_user_edits: bool = True) -> bool:
        """Apply precise defaults while preserving active user edits.

        The current start date is never changed by preference application.
        Other fields are updated only when they still match the old default or
        are empty.
        """
        old_values = self._preference_default_values()
        current = self.values()
        self._preferences = preferences
        new_values = self._preference_default_values()
        updated = False

        def should_update(key: str) -> bool:
            text = str(current.get(key, "")).strip()
            return (not preserve_user_edits) or not text or text == str(old_values.get(key, ""))

        if should_update("interval"):
            self._set_line_edit_text(self.interval_input, str(new_values["interval"]))
            updated = True
        if should_update("lowest_elevation"):
            self._set_line_edit_text(self.lowest_elevation_input, str(new_values["lowest_elevation"]))
            updated = True
        if should_update("sun_zenith_highest"):
            self._set_line_edit_text(self.sun_zenith_highest_input, str(new_values["sun_zenith_highest"]))
            updated = True
        if should_update("sun_zenith_lowest"):
            self._set_line_edit_text(self.sun_zenith_lowest_input, str(new_values["sun_zenith_lowest"]))
            updated = True

        if (not preserve_user_edits) or str(current.get("interval_unit", "")) == str(old_values["interval_unit"]):
            self._set_combo_text(self.interval_unit, str(new_values["interval_unit"]))
            updated = True
        if (not preserve_user_edits) or str(current.get("prediction_range", "")) == str(old_values["prediction_range"]):
            self._set_combo_text(self.prediction_range, str(new_values["prediction_range_label"]))
            updated = True

        if updated:
            self._log("Precise prediction defaults applied to eligible setup fields.", "INFO")
        else:
            self._log("Precise prediction defaults changed; active setup fields preserved.", "INFO")
        self.stateChanged.emit()
        return updated

    def _preference_default_values(self) -> dict[str, str]:
        """Return normalized field strings implied by the current preferences."""
        constraints = self._visibility_constraints()
        range_label = self._normalized_precise_range()
        return {
            "interval": str(self._default_interval()),
            "interval_unit": self._default_interval_unit(),
            "prediction_range": range_label.lower(),
            "prediction_range_label": range_label,
            "lowest_elevation": self._format_float(constraints.get("lowest_altitude_satellite", 30.0)),
            "sun_zenith_highest": self._format_float(constraints.get("sun_zenith_highest", 112.0)),
            "sun_zenith_lowest": self._format_float(constraints.get("sun_zenith_lowest", 99.0)),
        }

    @staticmethod
    def _set_line_edit_text(edit: QLineEdit, text: str) -> None:
        blocker = QSignalBlocker(edit)
        try:
            edit.setText(text)
        finally:
            del blocker

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str) -> None:
        blocker = QSignalBlocker(combo)
        try:
            index = combo.findText(text)
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            del blocker

    def values(self) -> dict[str, object]:
        """Return current raw precise settings values."""
        return {
            "start_date": self.start_date_edit.date().toString("yyyy-MM-dd"),
            "interval": self.interval_input.text().strip(),
            "interval_unit": self.interval_unit.currentText().strip().lower(),
            "prediction_range": self.prediction_range.currentText().strip().lower(),
            "lowest_elevation": self.lowest_elevation_input.text().strip(),
            "sun_zenith_highest": self.sun_zenith_highest_input.text().strip(),
            "sun_zenith_lowest": self.sun_zenith_lowest_input.text().strip(),
        }

    def validation_snapshot(self) -> dict[str, object]:
        """Return raw precise settings consumed by central validation."""
        return self.values()

    def execution_snapshot(self) -> dict[str, object]:
        """Return a future execution-facing snapshot without starting work."""
        return self.values()

    def set_field_validity(self, field_id: str, valid: bool, message: str = "") -> None:
        """Apply field-level validation styling without changing layout geometry."""
        field_map = {
            "settings.start_date": self.start_date_edit,
            "settings.interval": self.interval_input,
            "settings.interval_unit": self.interval_unit,
            "settings.prediction_range": self.prediction_range,
            "constraints.lowest_elevation": self.lowest_elevation_input,
            "constraints.sun_zenith_highest": self.sun_zenith_highest_input,
            "constraints.sun_zenith_lowest": self.sun_zenith_lowest_input,
        }
        widget = field_map.get(field_id)
        if widget is None:
            return
        _set_validation_state(widget, "valid" if valid else "error", message)

    def set_inputs_enabled(self, enabled: bool) -> None:
        """Enable or disable all editable precise setting controls."""
        for widget in (
            self.start_date_edit,
            self.interval_input,
            self.interval_unit,
            self.prediction_range,
            self.lowest_elevation_input,
            self.sun_zenith_highest_input,
            self.sun_zenith_lowest_input,
        ):
            widget.setEnabled(enabled)

    def _add_label(self, grid: QGridLayout, row: int, column: int, text: str) -> None:
        label = QLabel(text, self)
        label.setObjectName("guiFieldLabel")
        grid.addWidget(label, row, column)

    def _make_float_field(self, object_name: str, value: object, validator: QDoubleValidator) -> QLineEdit:
        field = QLineEdit(self)
        field.setObjectName(object_name)
        field.setValidator(validator)
        field.setText(self._format_float(value))
        field.setFixedWidth(74)
        field.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return field

    def _visibility_constraints(self) -> Mapping[str, object]:
        constraints = self._preferences.get("visibility_constraints", {})
        return constraints if isinstance(constraints, Mapping) else {}

    def _default_interval(self) -> int:
        raw_value = self._preferences.get("default_interval", 5)
        try:
            return max(1, int(raw_value))
        except (TypeError, ValueError):
            return 5

    def _default_interval_unit(self) -> str:
        unit = str(self._preferences.get("default_interval_unit", "minutes")).strip().lower()
        return unit if unit in _INTERVAL_UNITS else "minutes"

    def _normalized_precise_range(self) -> str:
        precise_range = str(
            self._preferences.get(
                "prediction_range_precise",
                self._preferences.get("prediction_range", "evening"),
            )
        ).strip().lower()
        if precise_range == "night":
            precise_range = "evening"
        return _RANGE_VALUES.get(precise_range, "Evening")

    @staticmethod
    def _format_float(value: object) -> str:
        try:
            return f"{float(value):g}"
        except (TypeError, ValueError):
            return ""

    def _log(self, message: str, level: str = "INFO") -> None:
        if self._log_callback is not None:
            self._log_callback(message, level)


def _set_validation_state(widget: QWidget, state: str, tooltip: str = "") -> None:
    widget.setProperty("validationState", state)
    widget.setToolTip(tooltip)
    repolish(widget)
