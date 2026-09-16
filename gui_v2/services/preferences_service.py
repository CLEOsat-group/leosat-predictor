"""GUI-v2-owned preference persistence and validation service.

This module is the non-visual boundary between GUI-v2 configuration pages and
project preference files.  It keeps JSON compatibility with the existing
``config/config.json`` and ``data/user_preferences.json`` files while avoiding
imports from legacy GUI preference widgets or dialogs.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping, Sequence

from src.observation_planner.preferences import (
    OBSERVATION_PLANNER_SECTION,
    from_preferences_dict,
    to_preferences_dict,
)

from ..state.preferences_state import (
    PreferenceSavePlan,
    PreferenceSnapshot,
    PreferenceValidationIssue,
    PreferenceValidationResult,
    PreferenceValidationSeverity,
)


class PreferencesServiceError(RuntimeError):
    """Raised when preferences cannot be loaded, saved, or prepared."""


class PreferenceValidationError(PreferencesServiceError):
    """Raised when invalid preferences would otherwise be saved."""

    def __init__(self, result: PreferenceValidationResult) -> None:
        self.result = result
        message = "Invalid preferences."
        if result.error_messages:
            message = "Invalid preferences: " + "; ".join(result.error_messages)
        super().__init__(message)


class PreferencesService:
    """Load, validate, merge, and save GUI-v2 preferences.

    Parameters
    ----------
    project_root : pathlib.Path, optional
        Repository root.  When omitted, it is inferred from this module path.
    defaults_path : pathlib.Path, optional
        Explicit path to the default preference JSON file.
    user_preferences_path : pathlib.Path, optional
        Explicit path to the user preference JSON file.
    """

    VALID_THEMES = frozenset({"dark", "light"})
    VALID_INTERVAL_UNITS = frozenset({"seconds", "minutes", "hours"})
    MAX_DEFAULT_DAYS = 365
    PRESERVED_HIDDEN_PLANNER_KEYS = frozenset()

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        defaults_path: Path | None = None,
        user_preferences_path: Path | None = None,
    ) -> None:
        self._project_root = Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parents[2]
        self._defaults_path = Path(defaults_path) if defaults_path is not None else self._project_root / "config" / "config.json"
        self._user_preferences_path = (
            Path(user_preferences_path)
            if user_preferences_path is not None
            else self._project_root / "data" / "user_preferences.json"
        )

    @property
    def defaults_path(self) -> Path:
        """Path to the default preference file."""

        return self._defaults_path

    @property
    def user_preferences_path(self) -> Path:
        """Path to the user preference override file."""

        return self._user_preferences_path

    def load(self) -> dict[str, Any]:
        """Load merged, normalized preferences for existing GUI-v2 callers.

        Returns
        -------
        dict[str, Any]
            Defensive copy of the effective preference tree.
        """

        return self.load_snapshot().copy_preferences()

    def load_snapshot(self) -> PreferenceSnapshot:
        """Load defaults, user overrides, and the merged normalized snapshot."""

        defaults = self._read_json_file(self._defaults_path, required=True)
        user_preferences = self._read_json_file(self._user_preferences_path, required=False)
        merged = self._recursive_merge(defaults, user_preferences)
        result = self.validate(merged)
        # Loading must be robust for existing users.  Keep the normalized tree
        # even if a later configuration page would block saving the invalid
        # values, because otherwise one bad preference could prevent GUI start.
        return PreferenceSnapshot(
            defaults=deepcopy(defaults),
            user_preferences=deepcopy(user_preferences),
            preferences=result.preferences,
            defaults_path=self._defaults_path,
            user_preferences_path=self._user_preferences_path,
        )

    def validate(self, preferences: Mapping[str, Any]) -> PreferenceValidationResult:
        """Validate and normalize a preference mapping.

        Parameters
        ----------
        preferences : mapping
            Candidate preference tree.

        Returns
        -------
        PreferenceValidationResult
            Normalized preferences plus validation issues.
        """

        if not isinstance(preferences, Mapping):
            return PreferenceValidationResult(
                preferences={},
                issues=(PreferenceValidationIssue("<root>", "Preferences must be a mapping."),),
            )

        normalized = deepcopy(dict(preferences))
        issues: list[PreferenceValidationIssue] = []

        self._normalize_and_validate_default_location(normalized, issues)
        self._normalize_and_validate_prediction_defaults(normalized, issues)
        self._normalize_and_validate_tle_settings(normalized, issues)
        self._normalize_and_validate_observation_planner(normalized, issues)
        normalized["theme"] = self.normalize_theme(normalized.get("theme", "dark"))

        return PreferenceValidationResult(preferences=normalized, issues=tuple(issues))

    def save(self, preferences: Mapping[str, Any]) -> PreferenceSavePlan:
        """Validate and persist preferences to the user-preference store.

        The input may be a partial preference tree.  It is recursively merged
        over the currently effective preferences so unknown keys are preserved.
        Observation Planner updates are accepted only when explicitly supplied
        and are validated through the shared planner preference contract.
        """

        old_snapshot = self.load_snapshot()
        candidate = self._merge_for_save(old_snapshot.preferences, preferences)
        result = self.validate(candidate)
        if not result.is_valid:
            raise PreferenceValidationError(result)

        saved_preferences = result.preferences
        self._write_json_atomically(self._user_preferences_path, saved_preferences)
        return self._build_save_plan(old_snapshot.preferences, saved_preferences)

    def save_and_prepare_application(
        self,
        *,
        old_preferences: Mapping[str, Any] | None,
        new_preferences: Mapping[str, Any],
    ) -> PreferenceSavePlan:
        """Save preferences and return a GUI-side application plan.

        This method keeps compatibility with the legacy service method name
        used by current GUI code while returning the GUI-v2 save-plan type.
        """

        old_tree = deepcopy(dict(old_preferences)) if isinstance(old_preferences, Mapping) else self.load()
        candidate = self._merge_for_save(old_tree, new_preferences)
        result = self.validate(candidate)
        if not result.is_valid:
            raise PreferenceValidationError(result)
        saved_preferences = result.preferences
        self._write_json_atomically(self._user_preferences_path, saved_preferences)
        return self._build_save_plan(old_tree, saved_preferences)

    @classmethod
    def normalize_theme(cls, theme: object) -> str:
        """Normalize a theme value to ``"dark"`` or ``"light"``."""

        normalized = str(theme or "dark").strip().lower()
        return normalized if normalized in cls.VALID_THEMES else "dark"

    def _merge_for_save(self, current_preferences: Mapping[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
        """Merge save updates while preserving unedited planner preference keys."""

        if not isinstance(updates, Mapping):
            raise PreferencesServiceError("Preferences to save must be a mapping.")
        candidate = self._recursive_merge(current_preferences, updates)
        if OBSERVATION_PLANNER_SECTION in updates:
            current_section = current_preferences.get(OBSERVATION_PLANNER_SECTION)
            candidate_section = candidate.get(OBSERVATION_PLANNER_SECTION)
            if isinstance(current_section, Mapping) and isinstance(candidate_section, Mapping):
                update_section = updates.get(OBSERVATION_PLANNER_SECTION)
                candidate[OBSERVATION_PLANNER_SECTION] = self._merge_observation_planner_for_save(
                    current_section,
                    candidate_section,
                    update_section if isinstance(update_section, Mapping) else {},
                )
        return candidate

    def _merge_observation_planner_for_save(
        self,
        current_section: Mapping[str, Any],
        candidate_section: Mapping[str, Any],
        update_section: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return planner preferences with unknown planner keys preserved.

        GUI-v2 now exposes the planner diagnostics and motion-model keys in the
        active Planner Defaults editor.  The merge therefore lets explicit
        planner saves update those values while still preserving future unknown
        keys through the recursive merge.
        """
        merged = self._recursive_merge(current_section, candidate_section)
        update_visibility = update_section.get("visibility")
        if isinstance(update_visibility, Mapping) and isinstance(update_visibility.get("columns"), Mapping):
            merged["column_mapping"] = deepcopy(update_visibility["columns"])
            merged["visibility"] = {"columns": deepcopy(update_visibility["columns"])}
        elif isinstance(update_section.get("column_mapping"), Mapping):
            merged["column_mapping"] = deepcopy(candidate_section["column_mapping"])
            merged["visibility"] = {"columns": deepcopy(candidate_section["column_mapping"])}
        elif isinstance(merged.get("column_mapping"), Mapping):
            merged["visibility"] = {"columns": deepcopy(merged["column_mapping"])}
        for key in self.PRESERVED_HIDDEN_PLANNER_KEYS:
            if key in current_section:
                merged[key] = deepcopy(current_section[key])
        return merged

    def _build_save_plan(
        self,
        old_preferences: Mapping[str, Any],
        saved_preferences: Mapping[str, Any],
    ) -> PreferenceSavePlan:
        """Build a structured save plan for future GUI-v2 propagation."""

        old_theme = self.normalize_theme(old_preferences.get("theme", "dark"))
        new_theme = self.normalize_theme(saved_preferences.get("theme", "dark"))
        changed_paths = self._changed_paths(old_preferences, saved_preferences)
        return PreferenceSavePlan(
            preferences=deepcopy(dict(saved_preferences)),
            old_theme=old_theme,
            new_theme=new_theme,
            theme_changed=old_theme != new_theme,
            apply_observation_planner=any(
                path == OBSERVATION_PLANNER_SECTION or path.startswith(f"{OBSERVATION_PLANNER_SECTION}.")
                for path in changed_paths
            ),
            changed_paths=changed_paths,
        )

    def _normalize_and_validate_observation_planner(
        self,
        preferences: dict[str, Any],
        issues: list[PreferenceValidationIssue],
    ) -> None:
        """Normalize Observation Planner preferences through the shared contract."""
        section = preferences.get(OBSERVATION_PLANNER_SECTION)
        if section is None:
            return
        if not isinstance(section, Mapping):
            issues.append(
                PreferenceValidationIssue(
                    OBSERVATION_PLANNER_SECTION,
                    "Observation Planner preferences must be a mapping.",
                )
            )
            return

        original_section = deepcopy(dict(section))
        try:
            planner_preferences = from_preferences_dict({OBSERVATION_PLANNER_SECTION: original_section})
            normalized_section = to_preferences_dict(planner_preferences)[OBSERVATION_PLANNER_SECTION]
        except ValueError as exc:
            issues.append(
                PreferenceValidationIssue(
                    OBSERVATION_PLANNER_SECTION,
                    str(exc),
                )
            )
            return

        preserved = deepcopy(original_section)
        preserved.update(normalized_section)
        for key in self.PRESERVED_HIDDEN_PLANNER_KEYS:
            if key in original_section:
                preserved[key] = deepcopy(original_section[key])
        preferences[OBSERVATION_PLANNER_SECTION] = preserved

    def _normalize_and_validate_default_location(
        self,
        preferences: dict[str, Any],
        issues: list[PreferenceValidationIssue],
    ) -> None:
        section = preferences.get("default_location")
        if not isinstance(section, Mapping):
            issues.append(PreferenceValidationIssue("default_location", "Default location must be a mapping."))
            preferences["default_location"] = {}
            return

        location = deepcopy(dict(section))
        name = str(location.get("name", "")).strip()
        if not name:
            issues.append(PreferenceValidationIssue("default_location.name", "Location name must not be empty."))
        location["name"] = name

        location["latitude"] = self._validate_float_range(
            location.get("latitude"),
            path="default_location.latitude",
            minimum=-90.0,
            maximum=90.0,
            issues=issues,
        )
        location["longitude"] = self._validate_float_range(
            location.get("longitude"),
            path="default_location.longitude",
            minimum=-180.0,
            maximum=180.0,
            issues=issues,
        )
        location["altitude"] = self._validate_float_range(
            location.get("altitude"),
            path="default_location.altitude",
            minimum=0.0,
            maximum=None,
            issues=issues,
        )
        preferences["default_location"] = location

    def _normalize_and_validate_prediction_defaults(
        self,
        preferences: dict[str, Any],
        issues: list[PreferenceValidationIssue],
    ) -> None:
        preferences["default_days"] = self._validate_int_range(
            preferences.get("default_days"),
            path="default_days",
            minimum=1,
            maximum=self.MAX_DEFAULT_DAYS,
            issues=issues,
        )
        preferences["default_interval"] = self._validate_int_range(
            preferences.get("default_interval"),
            path="default_interval",
            minimum=1,
            maximum=None,
            issues=issues,
        )
        unit = str(preferences.get("default_interval_unit", "seconds") or "seconds").strip().lower()
        if unit not in self.VALID_INTERVAL_UNITS:
            issues.append(
                PreferenceValidationIssue(
                    "default_interval_unit",
                    "Interval unit must be one of seconds, minutes, or hours.",
                )
            )
        else:
            preferences["default_interval_unit"] = unit

        preferences["visibility_margin"] = self._validate_float_range(
            preferences.get("visibility_margin"),
            path="visibility_margin",
            minimum=0.0,
            maximum=None,
            issues=issues,
        )

        constraints = preferences.get("visibility_constraints")
        if not isinstance(constraints, Mapping):
            issues.append(PreferenceValidationIssue("visibility_constraints", "Visibility constraints must be a mapping."))
            constraints_dict: dict[str, Any] = {}
        else:
            constraints_dict = deepcopy(dict(constraints))

        constraints_dict["lowest_altitude_satellite"] = self._validate_float_range(
            constraints_dict.get("lowest_altitude_satellite"),
            path="visibility_constraints.lowest_altitude_satellite",
            minimum=0.0,
            maximum=90.0,
            issues=issues,
        )
        constraints_dict["sun_zenith_highest"] = self._validate_float_range(
            constraints_dict.get("sun_zenith_highest"),
            path="visibility_constraints.sun_zenith_highest",
            minimum=0.0,
            maximum=180.0,
            issues=issues,
        )
        constraints_dict["sun_zenith_lowest"] = self._validate_float_range(
            constraints_dict.get("sun_zenith_lowest"),
            path="visibility_constraints.sun_zenith_lowest",
            minimum=0.0,
            maximum=180.0,
            issues=issues,
        )
        if (
            _is_number(constraints_dict.get("sun_zenith_highest"))
            and _is_number(constraints_dict.get("sun_zenith_lowest"))
            and float(constraints_dict["sun_zenith_highest"]) < float(constraints_dict["sun_zenith_lowest"])
        ):
            issues.append(
                PreferenceValidationIssue(
                    "visibility_constraints.sun_zenith_highest",
                    "Sun zenith highest must be greater than or equal to sun zenith lowest.",
                )
            )
        preferences["visibility_constraints"] = constraints_dict

    def _normalize_and_validate_tle_settings(
        self,
        preferences: dict[str, Any],
        issues: list[PreferenceValidationIssue],
    ) -> None:
        tle_folder = str(preferences.get("tle_folder", "") or "").strip()
        if not tle_folder:
            issues.append(PreferenceValidationIssue("tle_folder", "TLE folder must not be empty."))
        else:
            preferences["tle_folder"] = tle_folder

        preferences["tle_expiration_hours"] = self._validate_float_range(
            preferences.get("tle_expiration_hours"),
            path="tle_expiration_hours",
            minimum=0.0001,
            maximum=None,
            issues=issues,
        )
        preferences["tle_update_interval_hours"] = self._validate_float_range(
            preferences.get("tle_update_interval_hours"),
            path="tle_update_interval_hours",
            minimum=0.0001,
            maximum=None,
            issues=issues,
        )

        allow_batch_download = preferences.get("allow_batch_download")
        if not isinstance(allow_batch_download, bool):
            issues.append(PreferenceValidationIssue("allow_batch_download", "Allow batch download must be true or false."))
        tle_sources = preferences.get("tle_sources")
        if not isinstance(tle_sources, Mapping):
            issues.append(PreferenceValidationIssue("tle_sources", "TLE sources must be a mapping."))
        else:
            preferences["tle_sources"] = deepcopy(dict(tle_sources))

    @staticmethod
    def _validate_float_range(
        value: object,
        *,
        path: str,
        minimum: float | None,
        maximum: float | None,
        issues: list[PreferenceValidationIssue],
    ) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            issues.append(PreferenceValidationIssue(path, "Value must be numeric."))
            return 0.0
        if not math.isfinite(number):
            issues.append(PreferenceValidationIssue(path, "Value must be finite."))
            return 0.0
        if minimum is not None and number < minimum:
            issues.append(PreferenceValidationIssue(path, f"Value must be at least {minimum:g}."))
        if maximum is not None and number > maximum:
            issues.append(PreferenceValidationIssue(path, f"Value must be at most {maximum:g}."))
        return number

    @staticmethod
    def _validate_int_range(
        value: object,
        *,
        path: str,
        minimum: int | None,
        maximum: int | None,
        issues: list[PreferenceValidationIssue],
    ) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            issues.append(PreferenceValidationIssue(path, "Value must be an integer."))
            return 0
        if minimum is not None and number < minimum:
            issues.append(PreferenceValidationIssue(path, f"Value must be at least {minimum}."))
        if maximum is not None and number > maximum:
            issues.append(PreferenceValidationIssue(path, f"Value must be at most {maximum}."))
        return number

    @staticmethod
    def _recursive_merge(defaults: Mapping[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
        """Return a deep recursive merge of ``overrides`` over ``defaults``."""

        merged = deepcopy(dict(defaults))
        if not isinstance(overrides, Mapping):
            return merged
        for key, value in overrides.items():
            if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
                merged[key] = PreferencesService._recursive_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged

    @staticmethod
    def _changed_paths(old_preferences: Mapping[str, Any], new_preferences: Mapping[str, Any]) -> tuple[str, ...]:
        paths: list[str] = []
        PreferencesService._collect_changed_paths(old_preferences, new_preferences, prefix="", output=paths)
        return tuple(paths)

    @staticmethod
    def _collect_changed_paths(
        old_value: object,
        new_value: object,
        *,
        prefix: str,
        output: list[str],
    ) -> None:
        if isinstance(old_value, Mapping) and isinstance(new_value, Mapping):
            keys = tuple(dict.fromkeys((*old_value.keys(), *new_value.keys())))
            for key in keys:
                child_prefix = f"{prefix}.{key}" if prefix else str(key)
                PreferencesService._collect_changed_paths(
                    old_value.get(key),
                    new_value.get(key),
                    prefix=child_prefix,
                    output=output,
                )
            return
        if old_value != new_value:
            output.append(prefix or "<root>")

    @staticmethod
    def _read_json_file(path: Path, *, required: bool) -> dict[str, Any]:
        if not path.exists():
            if required:
                raise PreferencesServiceError(f"Preference file not found: {path}")
            return {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            if not required:
                return {}
            raise PreferencesServiceError(f"Invalid JSON in preference file {path}: {exc}") from exc
        except OSError as exc:
            raise PreferencesServiceError(f"Unable to read preference file {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise PreferencesServiceError(f"Preference file must contain a JSON object: {path}")
        return payload

    @staticmethod
    def _write_json_atomically(path: Path, preferences: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(dict(preferences), handle, indent=4, ensure_ascii=False)
                handle.write("\n")
            temp_path.replace(path)
        except OSError as exc:
            raise PreferencesServiceError(f"Unable to save preferences: {exc}") from exc


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


__all__: Sequence[str] = (
    "PreferenceSavePlan",
    "PreferenceSnapshot",
    "PreferenceValidationError",
    "PreferenceValidationIssue",
    "PreferenceValidationResult",
    "PreferenceValidationSeverity",
    "PreferencesService",
    "PreferencesServiceError",
)
