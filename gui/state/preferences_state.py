"""Qt-free preference state and validation objects for GUI.

The classes in this module are deliberately small value objects.  They are used
by the GUI preference service and future configuration pages to exchange
validated preference data without importing Qt widgets, dialogs, or legacy GUI
preference components.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class PreferenceValidationSeverity(str, Enum):
    """Severity for a preference validation issue."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class PreferenceValidationIssue:
    """A single validation issue associated with a preference path.

    Parameters
    ----------
    path : str
        Dot-separated preference path, for example ``"default_location.latitude"``.
    message : str
        Human-readable validation message.
    severity : PreferenceValidationSeverity, optional
        Issue severity.  Errors block saving; warnings are informational.
    """

    path: str
    message: str
    severity: PreferenceValidationSeverity = PreferenceValidationSeverity.ERROR


@dataclass(frozen=True, slots=True)
class PreferenceValidationResult:
    """Validation outcome for a preference tree.

    Parameters
    ----------
    preferences : dict[str, Any]
        Normalized defensive copy of the validated preference tree.
    issues : tuple[PreferenceValidationIssue, ...]
        Validation issues discovered during normalization.
    """

    preferences: dict[str, Any]
    issues: tuple[PreferenceValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        """Return ``True`` when no error-severity issues are present."""

        return not any(issue.severity is PreferenceValidationSeverity.ERROR for issue in self.issues)

    @property
    def error_messages(self) -> tuple[str, ...]:
        """Return compact error messages suitable for service exceptions."""

        return tuple(
            f"{issue.path}: {issue.message}"
            for issue in self.issues
            if issue.severity is PreferenceValidationSeverity.ERROR
        )


@dataclass(frozen=True, slots=True)
class PreferenceSnapshot:
    """Loaded preference state used by GUI configuration workflows.

    Parameters
    ----------
    defaults : dict[str, Any]
        Raw default preferences loaded from ``config/config.json``.
    user_preferences : dict[str, Any]
        Raw user override preferences loaded from ``data/user_preferences.json``.
    preferences : dict[str, Any]
        Merged and normalized preference tree used by the GUI.
    defaults_path : pathlib.Path
        Path used for default preferences.
    user_preferences_path : pathlib.Path
        Path used for user preference overrides.
    """

    defaults: dict[str, Any]
    user_preferences: dict[str, Any]
    preferences: dict[str, Any]
    defaults_path: Path
    user_preferences_path: Path

    def copy_preferences(self) -> dict[str, Any]:
        """Return a defensive copy of the merged preference tree."""

        return deepcopy(self.preferences)


@dataclass(frozen=True, slots=True)
class PreferenceSavePlan:
    """Instructions produced after successfully saving preferences.

    The field names intentionally mirror the legacy GUI preference application
    plan where possible so GUI propagation can consume the same semantic
    contract without importing legacy GUI modules.
    """

    preferences: dict[str, Any]
    old_theme: str
    new_theme: str
    theme_changed: bool
    apply_observation_planner: bool = False
    apply_prediction_widgets: bool = True
    update_prediction_settings: bool = True
    update_tle_widgets: bool = True
    update_location_widgets: bool = True
    refresh_tle_service: bool = True
    refresh_observatory_context: bool = True
    success_message: str = "Preferences saved successfully."
    changed_paths: tuple[str, ...] = field(default_factory=tuple)

    def copy_preferences(self) -> dict[str, Any]:
        """Return a defensive copy of the saved preference tree."""

        return deepcopy(self.preferences)


__all__ = (
    "PreferenceSnapshot",
    "PreferenceSavePlan",
    "PreferenceValidationIssue",
    "PreferenceValidationResult",
    "PreferenceValidationSeverity",
)
