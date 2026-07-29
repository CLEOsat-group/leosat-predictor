"""Qt-free validation model for GUI precise setup inputs.

This module deliberately imports no PyQt symbols. It validates the raw values
collected by GUI cards and returns an immutable readiness state. Execution,
results, export, plotting, and planner handoff are intentionally outside this
Task 45A boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ValidationSeverity(str, Enum):
    """Severity levels used by precise setup validation issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Single validation issue for a specific precise setup field."""

    field_id: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR


@dataclass(frozen=True, slots=True)
class PreciseInputSnapshot:
    """Raw, user-visible precise setup values captured from GUI cards."""

    location_name: str
    latitude: str
    longitude: str
    altitude: str
    start_date: str
    interval: str
    interval_unit: str
    prediction_range: str
    lowest_elevation: str
    sun_zenith_highest: str
    sun_zenith_lowest: str
    constellation: str
    loaded_satellite_count: int
    selected_satellite_count: int
    selection_confirmed: bool


@dataclass(frozen=True, slots=True)
class PreciseValidationState:
    """Derived readiness state for the Precise Setup & Run page."""

    is_ready: bool
    issues: tuple[ValidationIssue, ...]
    snapshot: PreciseInputSnapshot

    @property
    def summary(self) -> str:
        """Return a concise, user-facing validation summary."""
        if self.is_ready:
            count = self.snapshot.selected_satellite_count
            return f"Ready to run precise prediction for {count} satellite(s)."
        if not self.issues:
            return "Precise setup is incomplete."
        return self.issues[0].message


def validate_precise_inputs(snapshot: PreciseInputSnapshot) -> PreciseValidationState:
    """Validate a raw precise setup snapshot.

    Parameters
    ----------
    snapshot : PreciseInputSnapshot
        Raw values captured from GUI cards. The function never mutates or
        normalizes the user's input; it only reports readiness and issues.

    Returns
    -------
    PreciseValidationState
        Immutable validation/readiness result.
    """
    issues: list[ValidationIssue] = []

    _validate_location(snapshot, issues)
    _validate_settings(snapshot, issues)
    _validate_constraints(snapshot, issues)
    _validate_tle_selection(snapshot, issues)

    return PreciseValidationState(is_ready=not issues, issues=tuple(issues), snapshot=snapshot)


def _validate_location(snapshot: PreciseInputSnapshot, issues: list[ValidationIssue]) -> None:
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

    altitude = _parse_float(snapshot.altitude)
    if altitude is None:
        issues.append(ValidationIssue("location.altitude", "Observer altitude must be numeric."))
    elif altitude < 0.0:
        issues.append(ValidationIssue("location.altitude", "Observer altitude must be non-negative."))


def _validate_settings(snapshot: PreciseInputSnapshot, issues: list[ValidationIssue]) -> None:
    if not snapshot.start_date.strip():
        issues.append(ValidationIssue("settings.start_date", "Start date is required."))
    else:
        try:
            datetime.strptime(snapshot.start_date.strip(), "%Y-%m-%d")
        except ValueError:
            issues.append(ValidationIssue("settings.start_date", "Start date must use YYYY-MM-DD format."))

    interval_text = snapshot.interval.strip()
    if not interval_text:
        issues.append(ValidationIssue("settings.interval", "Prediction interval is required."))
    elif not interval_text.isdigit():
        issues.append(ValidationIssue("settings.interval", "Prediction interval must be a positive integer."))
    elif int(interval_text) < 1:
        issues.append(ValidationIssue("settings.interval", "Prediction interval must be at least 1."))

    if snapshot.interval_unit.strip().lower() not in {"seconds", "minutes", "hours"}:
        issues.append(ValidationIssue("settings.interval_unit", "Prediction interval unit must be seconds, minutes, or hours."))

    if snapshot.prediction_range.strip().lower() not in {"morning", "evening", "both"}:
        issues.append(ValidationIssue("settings.prediction_range", "Prediction range must be morning, evening, or both."))


def _validate_constraints(snapshot: PreciseInputSnapshot, issues: list[ValidationIssue]) -> None:
    lowest_elevation = _parse_float(snapshot.lowest_elevation)
    if lowest_elevation is None:
        issues.append(ValidationIssue("constraints.lowest_elevation", "Lowest elevation must be numeric."))
    elif not 0.0 <= lowest_elevation <= 90.0:
        issues.append(ValidationIssue("constraints.lowest_elevation", "Lowest elevation must be between 0 and 90 degrees."))

    sun_zenith_highest = _parse_float(snapshot.sun_zenith_highest)
    if sun_zenith_highest is None:
        issues.append(ValidationIssue("constraints.sun_zenith_highest", "Sun zenith highest must be numeric."))
    elif not 0.0 <= sun_zenith_highest <= 180.0:
        issues.append(ValidationIssue("constraints.sun_zenith_highest", "Sun zenith highest must be between 0 and 180 degrees."))

    sun_zenith_lowest = _parse_float(snapshot.sun_zenith_lowest)
    if sun_zenith_lowest is None:
        issues.append(ValidationIssue("constraints.sun_zenith_lowest", "Sun zenith lowest must be numeric."))
    elif not 0.0 <= sun_zenith_lowest <= 180.0:
        issues.append(ValidationIssue("constraints.sun_zenith_lowest", "Sun zenith lowest must be between 0 and 180 degrees."))


def _validate_tle_selection(snapshot: PreciseInputSnapshot, issues: list[ValidationIssue]) -> None:
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
    text = value.strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
