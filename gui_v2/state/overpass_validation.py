"""Qt-free validation model for GUI v2 overpass setup inputs.

This module deliberately imports no PyQt symbols.  It validates a raw snapshot
collected by the GUI widgets and returns an immutable readiness state that the
page can render without starting prediction execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ValidationSeverity(str, Enum):
    """Severity levels used by overpass setup validation issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Single validation issue for a specific overpass setup field."""

    field_id: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR


@dataclass(frozen=True, slots=True)
class OverpassInputSnapshot:
    """Raw, user-visible overpass setup values captured from GUI cards."""

    location_name: str
    latitude: str
    longitude: str
    altitude: str
    start_date: str
    days: str
    constellation: str
    selected_satellite_count: int
    loaded_satellite_count: int
    selection_confirmed: bool


@dataclass(frozen=True, slots=True)
class OverpassValidationState:
    """Derived readiness state for the Overpass Setup & Run page."""

    is_ready: bool
    issues: tuple[ValidationIssue, ...]
    snapshot: OverpassInputSnapshot

    @property
    def summary(self) -> str:
        """Return a concise, user-facing validation summary."""
        if self.is_ready:
            count = self.snapshot.selected_satellite_count
            return f"Ready to run overpass prediction for {count} satellite(s)."
        if not self.issues:
            return "Overpass setup is incomplete."
        return self.issues[0].message


def validate_overpass_inputs(snapshot: OverpassInputSnapshot) -> OverpassValidationState:
    """Validate a raw overpass setup snapshot.

    Parameters
    ----------
    snapshot : OverpassInputSnapshot
        Raw values captured from GUI-v2 cards.  The function never mutates or
        normalizes the user's input; it only reports readiness and issues.

    Returns
    -------
    OverpassValidationState
        Immutable validation/readiness result.
    """
    issues: list[ValidationIssue] = []

    _validate_location(snapshot, issues)
    _validate_settings(snapshot, issues)
    _validate_tle_selection(snapshot, issues)

    return OverpassValidationState(is_ready=not issues, issues=tuple(issues), snapshot=snapshot)


def _validate_location(snapshot: OverpassInputSnapshot, issues: list[ValidationIssue]) -> None:
    if not snapshot.location_name.strip():
        issues.append(ValidationIssue("location.name", "Location name is required."))

    latitude = _parse_float(snapshot.latitude)
    if latitude is None:
        issues.append(ValidationIssue("location.latitude", "Latitude must be numeric."))
    elif not -90.0 <= latitude <= 90.0:
        issues.append(ValidationIssue("location.latitude", "Latitude must be between -90 and +90 degrees."))

    longitude = _parse_float(snapshot.longitude)
    if longitude is None:
        issues.append(ValidationIssue("location.longitude", "Longitude must be numeric."))
    elif not -180.0 <= longitude <= 180.0:
        issues.append(ValidationIssue("location.longitude", "Longitude must be between -180 and +180 degrees."))

    if _parse_float(snapshot.altitude) is None:
        issues.append(ValidationIssue("location.altitude", "Observer altitude must be numeric."))


def _validate_settings(snapshot: OverpassInputSnapshot, issues: list[ValidationIssue]) -> None:
    if not snapshot.start_date.strip():
        issues.append(ValidationIssue("settings.start_date", "Start date is required."))
    else:
        try:
            datetime.strptime(snapshot.start_date.strip(), "%Y-%m-%d")
        except ValueError:
            issues.append(ValidationIssue("settings.start_date", "Start date must use YYYY-MM-DD format."))

    days_text = snapshot.days.strip()
    if not days_text:
        issues.append(ValidationIssue("settings.days", "Days to predict is required."))
        return
    if not days_text.isdigit():
        issues.append(ValidationIssue("settings.days", "Days to predict must be an integer from 1 to 365."))
        return
    days = int(days_text)
    if not 1 <= days <= 365:
        issues.append(ValidationIssue("settings.days", "Days to predict must be in the range 1–365."))


def _validate_tle_selection(snapshot: OverpassInputSnapshot, issues: list[ValidationIssue]) -> None:
    if not snapshot.constellation.strip():
        issues.append(ValidationIssue("tle.constellation", "Select a TLE constellation."))
        return
    if snapshot.loaded_satellite_count <= 0:
        issues.append(ValidationIssue("tle.loaded", "Load TLE data for the selected constellation."))
        return
    if snapshot.selected_satellite_count <= 0:
        issues.append(ValidationIssue("tle.selection", "Select at least one satellite."))
        return
    if not snapshot.selection_confirmed:
        issues.append(ValidationIssue("tle.selection", "Confirm the satellite selection before running."))


def _parse_float(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
