"""Formatting helpers for observatory records and elevation lookup."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import requests


def _coordinate_to_decimal(value: Any, *, field_name: str) -> float:
    """Convert a scalar or degree/minute/second sequence to decimal degrees.

    Parameters
    ----------
    value : object
        Numeric scalar or a one-to-three element coordinate sequence.
    field_name : str
        Field name used in validation messages.

    Returns
    -------
    float
        Decimal-degree value with the sign of the first component preserved.

    Raises
    ------
    ValueError
        If the coordinate cannot be converted or has an unsupported shape.
    """

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts = list(value)
        if not 1 <= len(parts) <= 3:
            raise ValueError(f"{field_name} must have one to three coordinate components.")
        try:
            numeric = [float(part) for part in parts]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} contains a non-numeric component.") from exc
        sign = -1.0 if numeric[0] < 0.0 else 1.0
        return sign * sum(abs(component) / (60.0**index) for index, component in enumerate(numeric))

    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric or a coordinate sequence.") from exc


def _normalize_legacy_west_longitude(value: Any) -> float:
    """Normalize legacy west-positive longitude to signed east-positive degrees.

    The historical observatory catalog stores positive values as degrees west
    of Greenwich.  Values above 180 represent east longitudes through the
    legacy 0--360 west-positive convention.  A negative scalar is accepted as
    an already-standard signed west longitude to support modern additions.
    """

    longitude = _coordinate_to_decimal(value, field_name="longitude")

    if longitude < 0.0:
        normalized = longitude
    elif longitude <= 180.0:
        normalized = -longitude
    elif longitude <= 360.0:
        normalized = 360.0 - longitude
    else:
        raise ValueError("longitude must be within the legacy [0, 360] or signed [-180, 180] range.")

    if not -180.0 <= normalized <= 180.0:
        raise ValueError(f"normalized longitude is outside [-180, 180]: {normalized}")
    return normalized


def set_observatory_data(data_observatory: dict[str, Any]) -> dict[str, Any]:
    """Normalize one legacy observatory record for map and prediction clients.

    Parameters
    ----------
    data_observatory : dict
        Observatory record.  Historical positive longitudes are interpreted as
        degrees west.  Negative scalar longitudes are treated as standard
        signed west longitudes.  Latitude may be decimal or DMS/DM sequence.

    Returns
    -------
    dict
        Copy of the input record with decimal latitude and standard signed
        longitude, where positive longitude is east and negative is west.

    Raises
    ------
    ValueError
        If required coordinates or timezone metadata are invalid.
    """

    if not isinstance(data_observatory, dict):
        raise ValueError("Observatory data must be provided as a dictionary.")
    if "latitude" not in data_observatory or "longitude" not in data_observatory:
        raise ValueError("Observatory data must include latitude and longitude.")
    if "tz" not in data_observatory:
        raise ValueError("Observatory data must include tz.")

    latitude = _coordinate_to_decimal(data_observatory["latitude"], field_name="latitude")
    longitude = _normalize_legacy_west_longitude(data_observatory["longitude"])

    if not -90.0 <= latitude <= 90.0:
        raise ValueError(f"latitude is outside [-90, 90]: {latitude}")

    normalized = dict(data_observatory)
    normalized["latitude"] = latitude
    normalized["longitude"] = longitude
    normalized["tz"] = data_observatory["tz"]
    return normalized


def get_elevation(lat, lon):
    """Fetch SRTM90m elevation for one coordinate pair."""

    url = f"https://api.opentopodata.org/v1/srtm90m?locations={lat},{lon}"
    response = requests.get(url).json()
    if "results" in response:
        return response["results"][0]["elevation"]
    return 0
