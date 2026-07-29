"""Persistence for saved observer locations."""

from __future__ import annotations

import json
from pathlib import Path


class LocationManager:
    """Load and save observer locations in a JSON file.

    Parameters
    ----------
    locations_file : str or pathlib.Path, default: "data/user_locations.json"
        Writable JSON file used for saved locations. The default preserves
        source/web compatibility; the frozen GUI injects a per-user path.
    """

    def __init__(
        self,
        locations_file: str | Path = "data/user_locations.json",
    ) -> None:
        self.locations_file = str(locations_file)
        self.default_location = None
        self.ensure_file_exists()

    @property
    def _path(self) -> Path:
        """Return the configured location file as a path object."""

        return Path(self.locations_file)

    def ensure_file_exists(self) -> None:
        """Create the parent directory and location file when missing."""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("[]", encoding="utf-8")

    def load_locations(self) -> list[object]:
        """Load saved locations from JSON."""

        try:
            with self._path.open("r", encoding="utf-8") as handle:
                locations = json.load(handle)
        except json.JSONDecodeError:
            return []
        return locations if isinstance(locations, list) else []

    def save_locations(self, locations: list[object]) -> None:
        """Save the complete location list."""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as handle:
            json.dump(locations, handle, indent=4)

    def save_location(
        self,
        location: dict[str, object],
        set_as_default: bool = False,
    ) -> str:
        """Save or update one location and optionally mark it as default."""

        locations = self.load_locations()
        matched_index = None
        for index, existing in enumerate(locations):
            if not isinstance(existing, dict):
                continue
            if (
                existing.get("latitude") == location.get("latitude")
                and existing.get("longitude") == location.get("longitude")
            ):
                matched_index = index
                break

        if matched_index is None:
            locations.append(location)
            saved_status = "Location saved successfully."
        else:
            locations[matched_index].update(location)
            saved_status = "Location updated successfully."

        self.save_locations(locations)

        if set_as_default:
            self.default_location = location
            return f"Location '{location.get('name')}' set as default."
        return saved_status

    def get_default_location(self):
        """Return the in-memory default location, if one was set."""

        return self.default_location
