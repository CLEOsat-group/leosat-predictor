"""Location normalization and persistence service for the PyQt GUI.

This module owns non-visual location policy for GUI workflows.  It converts
raw form or map values into a typed record, validates numeric bounds, and
persists the resulting dictionary through the existing location manager.  It
must not import Qt classes, read widgets, show dialogs, or mutate visible state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from src.models.location_manager import LocationManager



class LocationPersistence(Protocol):
    """Minimal persistence protocol required by ``LocationService``."""

    def save_location(self, location: dict[str, str | float], set_as_default: bool = False) -> str:
        """Persist one location dictionary and return status text."""


class LocationServiceError(RuntimeError):
    """Raised when a location request cannot be completed."""


class LocationValidationError(LocationServiceError):
    """Raised when raw location values cannot form a valid location record."""


@dataclass(frozen=True)
class LocationRecord:
    """Typed location record used at the GUI service boundary.

    Parameters
    ----------
    name : str
        Human-readable location name.
    latitude : float
        Geodetic latitude in degrees.  Valid range is -90 to +90.
    longitude : float
        Geodetic longitude in degrees.  Valid range is -180 to +180.
    altitude : float
        Observer altitude in metres.  Negative values are rejected to match the
        existing prediction-input validation policy.
    """

    name: str
    latitude: float
    longitude: float
    altitude: float

    def as_location_manager_dict(self) -> dict[str, str | float]:
        """Return the dictionary shape consumed by ``LocationManager``.

        Returns
        -------
        dict[str, str | float]
            Dictionary with ``name``, ``latitude``, ``longitude`` and
            ``altitude`` keys.
        """
        return {
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "altitude": self.altitude,
        }


@dataclass(frozen=True)
class LocationSaveResult:
    """Structured result returned after saving a location.

    Parameters
    ----------
    record : LocationRecord
        Normalized location record that was submitted for persistence.
    message : str
        User-facing status text returned by the persistence layer.
    success : bool
        ``True`` when the persistence result indicates a successful save,
        update, or default-location change.
    """

    record: LocationRecord
    message: str
    success: bool


class LocationService:
    """Normalize, validate, and persist location records without UI coupling."""

    def __init__(self, location_manager: LocationPersistence | None = None) -> None:
        """Create the service.

        Parameters
        ----------
        location_manager : LocationPersistence, optional
            Existing persistence component.  A default instance is created when
            omitted.
        """
        self._location_manager = location_manager or _create_default_location_manager()

    def normalize(
        self,
        *,
        name: object,
        latitude: object,
        longitude: object,
        altitude: object,
    ) -> LocationRecord:
        """Convert raw values into a validated location record.

        Parameters
        ----------
        name : object
            Raw location name from a form, map selection, or caller.
        latitude : object
            Raw latitude value.
        longitude : object
            Raw longitude value.
        altitude : object
            Raw altitude value.

        Returns
        -------
        LocationRecord
            Normalized and validated location record.

        Raises
        ------
        LocationValidationError
            If a value cannot be converted or is outside the accepted range.
        """
        normalized_name = self._normalize_name(name)
        lat = self._coerce_float(latitude, "Latitude")
        lon = self._coerce_float(longitude, "Longitude")
        alt = self._coerce_float(altitude, "Altitude")

        if not -90.0 <= lat <= 90.0:
            raise LocationValidationError("Latitude must be between -90 and 90 degrees.")
        if not -180.0 <= lon <= 180.0:
            raise LocationValidationError("Longitude must be between -180 and 180 degrees.")
        if alt < 0.0:
            raise LocationValidationError("Altitude must be greater than or equal to 0 metres.")

        return LocationRecord(
            name=normalized_name,
            latitude=lat,
            longitude=lon,
            altitude=alt,
        )

    def save(self, record: LocationRecord, *, set_as_default: bool = False) -> LocationSaveResult:
        """Persist one validated location record.

        Parameters
        ----------
        record : LocationRecord
            Validated location to persist.
        set_as_default : bool, default: False
            Whether the existing persistence layer should mark this location as
            default.

        Returns
        -------
        LocationSaveResult
            Structured persistence result for visible status handling.
        """
        message = self._location_manager.save_location(
            record.as_location_manager_dict(),
            set_as_default=set_as_default,
        )
        return LocationSaveResult(
            record=record,
            message=message,
            success=self._is_success_message(message),
        )

    def normalize_mapping(self, raw_location: Mapping[str, object]) -> LocationRecord:
        """Normalize a dictionary-style location source.

        Parameters
        ----------
        raw_location : Mapping[str, object]
            Mapping containing ``name``, ``latitude``, ``longitude`` and
            ``altitude`` keys.

        Returns
        -------
        LocationRecord
            Normalized location record.
        """
        return self.normalize(
            name=raw_location.get("name", ""),
            latitude=raw_location.get("latitude", ""),
            longitude=raw_location.get("longitude", ""),
            altitude=raw_location.get("altitude", ""),
        )

    @staticmethod
    def _normalize_name(value: object) -> str:
        name = str(value).strip() if value is not None else ""
        if not name:
            raise LocationValidationError("Location name is required.")
        return name

    @staticmethod
    def _coerce_float(value: object, field_name: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise LocationValidationError(f"{field_name} must be a valid number.") from exc

    @staticmethod
    def _is_success_message(message: str) -> bool:
        normalized = message.lower()
        return any(
            marker in normalized
            for marker in (
                "saved successfully",
                "updated successfully",
                "set as default",
            )
        )


def _create_default_location_manager() -> LocationPersistence:
    """Create the shared location persistence component."""

    return LocationManager()


__all__: Sequence[str] = (
    "LocationPersistence",
    "LocationRecord",
    "LocationSaveResult",
    "LocationService",
    "LocationServiceError",
    "LocationValidationError",
)
