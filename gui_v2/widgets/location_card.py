"""Location and observatory-context card for GUI v2 overpass setup."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from typing import Any

from PyQt6.QtCore import QSignalBlocker, pyqtSignal
from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QPushButton, QWidget

from gui_v2.styles import repolish
from gui_v2.styles.effects import apply_card_elevation
from gui_v2.services.location_service import LocationRecord, LocationService, LocationValidationError
from gui_v2.services.preferences_service import PreferencesService

LogCallback = Callable[[str, str], None]
ObservatoryContextCallback = Callable[[Mapping[str, object]], None]


class LocationCard(QFrame):
    """Location setup card backed by ``LocationService``.

    The visual layout intentionally mirrors the legacy GUI v1 grid without
    reusing parent-coupled legacy widgets.  The card emits raw-state changes
    and delegates readiness decisions to ``OverpassSetupPage``.
    """

    stateChanged = pyqtSignal()
    defaultLocationSaved = pyqtSignal(object)

    def __init__(
        self,
        *,
        location_service: LocationService,
        preferences: Mapping[str, Any],
        preferences_service: PreferencesService | None = None,
        log_callback: LogCallback | None = None,
        observatory_context_callback: ObservatoryContextCallback | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._location_service = location_service
        self._preferences = preferences
        self._preferences_service = preferences_service
        self._log_callback = log_callback
        self._observatory_context_callback = observatory_context_callback
        self.setObjectName("guiV2Card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        apply_card_elevation(self)

        grid = QGridLayout(self)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        title = QLabel("Location", self)
        title.setObjectName("guiV2CardTitle")
        grid.addWidget(title, 0, 0, 1, 3)

        self.name_edit = QLineEdit(self)
        self.name_edit.setObjectName("guiV2LocationNameEdit")
        self.name_edit.setPlaceholderText("Enter Location Name")
        self.latitude_edit = QLineEdit(self)
        self.latitude_edit.setObjectName("guiV2LocationLatitudeEdit")
        self.latitude_edit.setPlaceholderText("-90.0 … +90.0")
        self.longitude_edit = QLineEdit(self)
        self.longitude_edit.setObjectName("guiV2LocationLongitudeEdit")
        self.longitude_edit.setPlaceholderText("-180.0 … +180.0")
        self.altitude_edit = QLineEdit(self)
        self.altitude_edit.setObjectName("guiV2LocationAltitudeEdit")
        self.altitude_edit.setPlaceholderText("metres")

        self.select_map_button = QPushButton("Select from Map", self)
        self.select_map_button.setObjectName("guiV2LocationSelectMapButton")
        self.select_map_button.setProperty("buttonRole", "primary")
        self.select_map_button.setToolTip("Open the map dialog and apply a selected observer location.")

        self.set_default_button = QPushButton("Set as Default", self)
        self.set_default_button.setObjectName("guiV2LocationSetDefaultButton")
        self.set_default_button.setProperty("buttonRole", "success")
        self.clear_button = QPushButton("Clear", self)
        self.clear_button.setObjectName("guiV2LocationClearButton")
        self.clear_button.setProperty("buttonRole", "danger")

        self._add_labeled_field(grid, 1, "Location Name:", self.name_edit)
        grid.addWidget(self.select_map_button, 1, 2)
        self._add_labeled_field(grid, 2, "Latitude:", self.latitude_edit)
        grid.addWidget(self.set_default_button, 2, 2)
        self._add_labeled_field(grid, 3, "Longitude:", self.longitude_edit)
        self._add_labeled_field(grid, 4, "Observer Altitude (m):", self.altitude_edit)
        grid.addWidget(self.clear_button, 4, 2)

        self.status_label = QLabel("Location values are editable and validated by the active prediction setup page.", self)
        self.status_label.setObjectName("guiV2CardBody")
        self.status_label.setWordWrap(True)
        grid.addWidget(self.status_label, 5, 0, 1, 3)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setRowStretch(6, 1)

        self.clear_button.clicked.connect(self.clear_fields)
        self.set_default_button.clicked.connect(self._save_default_location)
        self.select_map_button.clicked.connect(self._select_from_map)
        self._connect_state_signals()
        self._load_default_location()


    def apply_preferences(self, preferences: Mapping[str, Any], *, preserve_user_edits: bool = True) -> bool:
        """Apply a saved default location when visible fields are safe to update.

        The backing preference reference is always updated.  Visible fields are
        refreshed only when they are empty or still match the old default, so a
        user editing an active prediction setup is not silently overwritten.
        """
        old_preferences = self._preferences
        self._preferences = preferences
        if preserve_user_edits and not self._location_fields_can_refresh(old_preferences):
            self.status_label.setText(
                "Default location preference changed. Active location edits were preserved."
            )
            self._log("Default location preference updated; active location fields preserved.", "INFO")
            return False

        self._load_default_location()
        self._log("Default location preference applied to setup fields.", "INFO")
        return True

    def _location_fields_can_refresh(self, old_preferences: Mapping[str, Any]) -> bool:
        """Return whether visible fields are empty or still equal to old defaults."""
        current = self.values()
        if not any(current.values()):
            return True
        old_default = old_preferences.get("default_location")
        if not isinstance(old_default, Mapping):
            return False
        try:
            record = self._location_service.normalize_mapping(old_default)
        except LocationValidationError:
            return False
        expected = {
            "name": record.name,
            "latitude": f"{record.latitude:.6f}",
            "longitude": f"{record.longitude:.6f}",
            "altitude": f"{record.altitude:.1f}",
        }
        return all(
            not current[key] or current[key] == expected[key]
            for key in ("name", "latitude", "longitude", "altitude")
        )

    def values(self) -> dict[str, str]:
        """Return current raw location form values."""
        return {
            "name": self.name_edit.text().strip(),
            "latitude": self.latitude_edit.text().strip(),
            "longitude": self.longitude_edit.text().strip(),
            "altitude": self.altitude_edit.text().strip(),
        }

    def validation_snapshot(self) -> dict[str, str]:
        """Return the raw location values consumed by central validation."""
        return self.values()

    def set_field_validity(self, field_id: str, valid: bool, message: str = "") -> None:
        """Apply field-level validation styling without changing layout geometry."""
        field_map = {
            "location.name": self.name_edit,
            "location.latitude": self.latitude_edit,
            "location.longitude": self.longitude_edit,
            "location.altitude": self.altitude_edit,
        }
        widget = field_map.get(field_id)
        if widget is None:
            return
        _set_validation_state(widget, "valid" if valid else "error", message)

    def clear_fields(self) -> None:
        """Clear visible location fields without altering preferences."""
        self.name_edit.clear()
        self.latitude_edit.clear()
        self.longitude_edit.clear()
        self.altitude_edit.clear()
        self.status_label.setText("Location fields cleared. Saved defaults were not changed.")
        self._log("Location fields cleared; no preference or location file was modified.", "INFO")
        self.stateChanged.emit()

    def _add_labeled_field(self, grid: QGridLayout, row: int, label_text: str, widget: QWidget) -> None:
        label = QLabel(label_text, self)
        label.setObjectName("guiV2FieldLabel")
        grid.addWidget(label, row, 0)
        grid.addWidget(widget, row, 1)

    def _connect_state_signals(self) -> None:
        for edit in (self.name_edit, self.latitude_edit, self.longitude_edit, self.altitude_edit):
            edit.textChanged.connect(lambda _text: self.stateChanged.emit())

    def _load_default_location(self) -> None:
        default_location = self._preferences.get("default_location")
        if not isinstance(default_location, Mapping):
            self._log("No default_location mapping found in preferences.", "WARNING")
            return
        try:
            record = self._location_service.normalize_mapping(default_location)
        except LocationValidationError as exc:
            self.status_label.setText(f"Default location could not be loaded: {exc}")
            self._log(f"Default location rejected by LocationService: {exc}", "WARNING")
            return

        blockers = (
            QSignalBlocker(self.name_edit),
            QSignalBlocker(self.latitude_edit),
            QSignalBlocker(self.longitude_edit),
            QSignalBlocker(self.altitude_edit),
        )
        try:
            self.name_edit.setText(record.name)
            self.name_edit.setCursorPosition(0)
            self.latitude_edit.setText(f"{record.latitude:.6f}")
            self.longitude_edit.setText(f"{record.longitude:.6f}")
            self.altitude_edit.setText(f"{record.altitude:.1f}")
        finally:
            del blockers
        self.status_label.setText("Default location loaded from preferences.")
        self._notify_observatory_context(record)
        self._log(f"Default location loaded: {record.name}", "INFO")
        self.stateChanged.emit()

    def _save_default_location(self) -> None:
        try:
            record = self._location_service.normalize(
                name=self.name_edit.text(),
                latitude=self.latitude_edit.text(),
                longitude=self.longitude_edit.text(),
                altitude=self.altitude_edit.text(),
            )
        except LocationValidationError as exc:
            self.status_label.setText(str(exc))
            self._log(f"Location default save rejected: {exc}", "WARNING")
            self.stateChanged.emit()
            return
        self._commit_default(record)

    def _commit_default(self, record: LocationRecord) -> None:
        """Persist ``record`` as the default and broadcast the change."""
        try:
            result = self._location_service.save(record, set_as_default=True)
        except Exception as exc:  # pragma: no cover - persistence guard
            self.status_label.setText(f"Unable to save default location: {exc}")
            self._log(f"Unable to save default location: {exc}", "ERROR")
            self.stateChanged.emit()
            return

        if result.success:
            self._persist_default_to_preferences(record)
            self._notify_observatory_context(record)
        self.status_label.setText(result.message)
        level = "INFO" if result.success else "WARNING"
        self._log(f"Default location save requested: {result.message}", level)
        self.stateChanged.emit()

    def _persist_default_to_preferences(self, record: LocationRecord) -> None:
        """Persist the default location to preferences so it survives restart.

        ``LocationService.save`` only writes the saved-locations file and the
        location manager's in-memory default.  The setup pages load their
        default location from ``preferences["default_location"]`` on startup, so
        the choice must also be written there to take effect after a restart.
        """
        default_location = record.as_location_manager_dict()
        if self._preferences_service is not None:
            try:
                self._preferences_service.save({"default_location": default_location})
            except Exception as exc:  # pragma: no cover - persistence guard
                self._log(
                    f"Default location saved to file but not to preferences: {exc}",
                    "WARNING",
                )
                return
        if isinstance(self._preferences, MutableMapping):
            self._preferences["default_location"] = default_location
        # Broadcast the new global default so sibling setup pages and the
        # dashboard header can adopt it.  Individual (non-default) selections
        # applied from the map remain page-local and do not emit this.
        self.defaultLocationSaved.emit(default_location)

    def apply_default_location(self, location: Mapping[str, Any]) -> None:
        """Force the visible fields to a new global default location.

        Unlike :meth:`apply_preferences`, this always overwrites the fields
        because it is triggered by an explicit "Set as Default" action on
        another setup page.  Persistence is intentionally skipped: the page that
        raised the default already wrote it to preferences.
        """
        if not isinstance(location, Mapping):
            return
        try:
            record = self._location_service.normalize_mapping(location)
        except LocationValidationError as exc:
            self._log(f"Propagated default location rejected: {exc}", "WARNING")
            return
        if isinstance(self._preferences, MutableMapping):
            self._preferences["default_location"] = record.as_location_manager_dict()
        blockers = (
            QSignalBlocker(self.name_edit),
            QSignalBlocker(self.latitude_edit),
            QSignalBlocker(self.longitude_edit),
            QSignalBlocker(self.altitude_edit),
        )
        try:
            self.name_edit.setText(record.name)
            self.name_edit.setCursorPosition(0)
            self.latitude_edit.setText(f"{record.latitude:.6f}")
            self.longitude_edit.setText(f"{record.longitude:.6f}")
            self.altitude_edit.setText(f"{record.altitude:.1f}")
        finally:
            del blockers
        self.status_label.setText("Default location updated from another setup page.")
        self._notify_observatory_context(record)
        self._log(f"Default location adopted: {record.name}", "INFO")
        self.stateChanged.emit()

    def _notify_observatory_context(self, record: object) -> None:
        """Notify the dashboard header that an observatory location is configured."""
        if self._observatory_context_callback is None:
            return
        location = {
            "name": getattr(record, "name", ""),
            "latitude": getattr(record, "latitude", None),
            "longitude": getattr(record, "longitude", None),
            "altitude": getattr(record, "altitude", None),
        }
        self._observatory_context_callback(location)

    def _select_from_map(self) -> None:
        """Open the GUI-v2-native map dialog and apply a selected location."""
        try:
            from ..dialogs.location_map_dialog import LocationMapDialog

            dialog = LocationMapDialog(self, show_set_default=True)
        except Exception as exc:  # pragma: no cover - optional WebEngine/runtime guard
            self.status_label.setText(
                f"Unable to open Select from Map. Manual location entry remains available: {exc}"
            )
            self._log(f"Unable to open Select from Map: {exc}", "ERROR")
            self.stateChanged.emit()
            return

        dialog.locationSelected.connect(self._apply_map_location)
        dialog.defaultLocationRequested.connect(self._set_default_from_map)
        self.status_label.setText("Map dialog opened. Select a point or observatory and apply it.")
        self._log("Select from Map dialog opened.", "INFO")
        dialog.exec()

    def _normalize_map_selection(
        self, latitude: float, longitude: float, altitude: float, name: str
    ) -> LocationRecord | None:
        """Normalize a map selection, reporting rejection to the status label."""
        try:
            return self._location_service.normalize(
                name=name,
                latitude=latitude,
                longitude=longitude,
                altitude=altitude,
            )
        except LocationValidationError as exc:
            self.status_label.setText(f"Map selection rejected: {exc}")
            self._log(f"Map selection rejected by LocationService: {exc}", "WARNING")
            self.stateChanged.emit()
            return None

    def _set_record_fields(self, record: LocationRecord) -> None:
        """Write a normalized record into the visible location fields."""
        self.name_edit.setText(record.name)
        self.name_edit.setCursorPosition(0)
        self.latitude_edit.setText(f"{record.latitude:.6f}")
        self.longitude_edit.setText(f"{record.longitude:.6f}")
        self.altitude_edit.setText(f"{record.altitude:.1f}")

    def _apply_map_location(self, latitude: float, longitude: float, altitude: float, name: str) -> None:
        """Normalize and apply a location selected from the map dialog."""
        record = self._normalize_map_selection(latitude, longitude, altitude, name)
        if record is None:
            return

        self._set_record_fields(record)
        self._notify_observatory_context(record)
        self.status_label.setText(
            "Map location applied. Use Set as Default only if this location should be saved as your default."
        )
        self._log(
            f"Map location applied: {record.name} "
            f"({record.latitude:.6f}, {record.longitude:.6f}, {record.altitude:.1f} m).",
            "INFO",
        )
        self.stateChanged.emit()

    def _set_default_from_map(self, latitude: float, longitude: float, altitude: float, name: str) -> None:
        """Apply a map selection to the fields and save it as the default."""
        record = self._normalize_map_selection(latitude, longitude, altitude, name)
        if record is None:
            return
        self._set_record_fields(record)
        self._commit_default(record)

    def _log(self, message: str, level: str = "INFO") -> None:
        if self._log_callback is not None:
            self._log_callback(message, level)


def _set_validation_state(widget: QWidget, state: str, tooltip: str = "") -> None:
    widget.setProperty("validationState", state)
    widget.setToolTip(tooltip)
    repolish(widget)
