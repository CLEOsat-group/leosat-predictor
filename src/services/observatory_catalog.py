"""Shared observatory catalog normalization for GUI and web map clients.

This module is deliberately free of Qt and Flask imports.  Both delivery paths
consume the same normalized observatory records so coordinate handling and map
metadata cannot drift between the GUI and web applications.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.models.formatter import set_observatory_data
from src.models.observatories import observatories as DEFAULT_OBSERVATORIES


MAP_GROUP_DECIMAL_PLACES = 3


def observatory_map_group(latitude: float, longitude: float) -> str:
    """Return a stable map-site grouping key for nearby observatories.

    Parameters
    ----------
    latitude : float
        Standard signed latitude in degrees.
    longitude : float
        Standard signed longitude in degrees, positive east.

    Returns
    -------
    str
        Rounded coordinate key used by both map clients to present closely
        colocated instruments through one marker with an explicit chooser.
    """

    return f"{latitude:.{MAP_GROUP_DECIMAL_PLACES}f},{longitude:.{MAP_GROUP_DECIMAL_PLACES}f}"


def build_observatory_catalog(
    source: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the normalized observatory catalog shared by GUI and web.

    Parameters
    ----------
    source : mapping, optional
        Observatory records keyed by stable identifier.  When omitted, the
        repository catalog from :mod:`src.models.observatories` is used.

    Returns
    -------
    list of dict
        JSON-serializable observatory records in insertion order.  Every record
        contains ``id``, normalized coordinates, and a ``map_group`` key.

    Raises
    ------
    ValueError
        If an observatory identifier, coordinate, or required field is invalid.
    """

    records = DEFAULT_OBSERVATORIES if source is None else source
    catalog: list[dict[str, Any]] = []

    for raw_identifier, raw_record in records.items():
        identifier = str(raw_identifier).strip()
        if not identifier:
            raise ValueError("Observatory identifiers must be non-empty strings.")
        if not isinstance(raw_record, Mapping):
            raise ValueError(f"Observatory {identifier!r} must be a mapping.")

        try:
            normalized = set_observatory_data(dict(raw_record))
            name = str(normalized["name"]).strip()
            latitude = float(normalized["latitude"])
            longitude = float(normalized["longitude"])
            altitude = float(normalized.get("altitude", 0.0))
            timezone_offset = normalized["tz"]
            float(timezone_offset)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid observatory record {identifier!r}: {exc}") from exc

        if not name:
            raise ValueError(f"Observatory {identifier!r} must define a non-empty name.")
        if not -90.0 <= latitude <= 90.0:
            raise ValueError(
                f"Observatory {identifier!r} latitude must be within [-90, 90], got {latitude}."
            )
        if not -180.0 <= longitude <= 180.0:
            raise ValueError(
                f"Observatory {identifier!r} longitude must be within [-180, 180], got {longitude}."
            )

        explicit_map_group = raw_record.get("map_group")
        if explicit_map_group is None:
            map_group = observatory_map_group(latitude, longitude)
        else:
            map_group = str(explicit_map_group).strip()
            if not map_group:
                raise ValueError(
                    f"Observatory {identifier!r} defines an empty map_group."
                )

        record = dict(normalized)
        record.update(
            {
                "id": identifier,
                "name": name,
                "latitude": latitude,
                "longitude": longitude,
                "altitude": altitude,
                "tz": timezone_offset,
                "map_group": map_group,
            }
        )
        catalog.append(record)

    return catalog


__all__ = (
    "MAP_GROUP_DECIMAL_PLACES",
    "build_observatory_catalog",
    "observatory_map_group",
)
