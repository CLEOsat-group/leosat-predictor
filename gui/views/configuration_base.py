"""Shared widgets and helpers for GUI configuration pages.

The configuration pages are intentionally page-based rather than modal-dialog
based.  They share persistence, status, and card helpers while each concrete
page owns its own fields and preference mapping.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDoubleValidator, QIntValidator
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..services import PreferenceValidationError, PreferencesService, PreferencesServiceError
from ..shell.navigation_model import NavigationNode

from gui.styles import repolish
from gui.styles.effects import apply_card_elevation
from gui.styles.icon_provider import set_themed_icon


NUMERIC_FIELD_WIDTH = 130
SHORT_FIELD_WIDTH = 180
MEDIUM_FIELD_WIDTH = 280
LONG_FIELD_WIDTH = 420


def set_compact_field_width(widget: QWidget, *, width: int = SHORT_FIELD_WIDTH) -> QWidget:
    """Constrain a form field so configuration inputs do not span the page.

    Configuration values are explicit text choices rather than document-style
    free text.  Keeping those controls compact improves scanning and mirrors
    the legacy preference dialog while still allowing the surrounding card to
    resize naturally.
    """
    widget.setFixedWidth(width)
    return widget


def _format_numeric_value(value: object, *, default: float | int, decimals: int | None = None) -> str:
    """Return a compact text representation for numeric configuration fields."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    if decimals is None:
        return str(int(round(number)))
    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")


def create_integer_input(
    *,
    parent: QWidget,
    object_name: str,
    minimum: int,
    maximum: int,
    default: int = 0,
    width: int = NUMERIC_FIELD_WIDTH,
) -> QLineEdit:
    """Create a plain validated integer input without spin-box step arrows.

    The legacy preferences dialog used line edits with validators for numeric
    fields.  GUI follows that pattern for configuration values that are
    edited as explicit numbers rather than incremented interactively.
    """
    edit = QLineEdit(parent)
    edit.setObjectName(object_name)
    edit.setValidator(QIntValidator(minimum, maximum, edit))
    edit.setText(_format_numeric_value(default, default=default, decimals=None))
    set_compact_field_width(edit, width=width)
    return edit


def create_float_input(
    *,
    parent: QWidget,
    object_name: str,
    minimum: float,
    maximum: float,
    decimals: int,
    default: float = 0.0,
    width: int = NUMERIC_FIELD_WIDTH,
) -> QLineEdit:
    """Create a plain validated floating-point input without spin-box arrows."""
    edit = QLineEdit(parent)
    edit.setObjectName(object_name)
    validator = QDoubleValidator(minimum, maximum, decimals, edit)
    validator.setNotation(QDoubleValidator.Notation.StandardNotation)
    edit.setValidator(validator)
    edit.setText(_format_numeric_value(default, default=default, decimals=decimals))
    set_compact_field_width(edit, width=width)
    return edit


def parse_integer_input(edit: QLineEdit, *, label: str, minimum: int, maximum: int) -> int:
    """Parse and range-check an integer configuration field."""
    text = edit.text().strip()
    try:
        value = int(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer.") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}.")
    return value


def parse_float_input(edit: QLineEdit, *, label: str, minimum: float, maximum: float) -> float:
    """Parse and range-check a floating-point configuration field."""
    text = edit.text().strip()
    try:
        value = float(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return value


class ConfigurationCard(QFrame):
    """Styled card used by GUI configuration pages."""

    def __init__(self, *, title: str, body: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        apply_card_elevation(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 16, 18, 16)
        self.layout.setSpacing(10)

        title_label = QLabel(title, self)
        title_label.setObjectName("guiCardTitle")
        title_label.setWordWrap(True)
        self.layout.addWidget(title_label)

        if body:
            body_label = QLabel(body, self)
            body_label.setObjectName("guiCardBody")
            body_label.setWordWrap(True)
            self.layout.addWidget(body_label)


class ConfigurationPageBase(QWidget):
    """Base class for concrete GUI configuration pages.

    Subclasses provide fields by adding widgets to ``self.content_layout`` and
    implement ``_populate_from_preferences`` plus ``_collect_updates``.
    """

    preferencesSaved = pyqtSignal(object)

    def __init__(
        self,
        *,
        page: NavigationNode,
        preferences_service: PreferencesService,
        show_actions: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.page = page
        self._preferences_service = preferences_service
        self._show_actions = show_actions
        self._snapshot_preferences: dict[str, Any] = {}
        self.setObjectName("guiConfigurationPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        content_host = QWidget(self)
        content_host.setObjectName("guiWorkspaceGrid")
        self.content_layout = QVBoxLayout(content_host)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        root.addWidget(content_host, 1)

        self.status_label = QLabel("Load preferences to begin editing.", self)
        self.status_label.setObjectName("guiCardBody")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        if show_actions:
            action_host = QWidget(self)
            action_layout = QHBoxLayout(action_host)
            action_layout.setContentsMargins(0, 0, 0, 0)
            action_layout.setSpacing(8)
            action_layout.addStretch(1)

            self.save_button = QPushButton("Save", action_host)
            self.save_button.setObjectName("guiConfigurationSaveButton")
            self.save_button.setProperty("buttonRole", "primary")
            set_themed_icon(self.save_button, "save", size=16)
            self.revert_button = QPushButton("Revert", action_host)
            self.revert_button.setObjectName("guiConfigurationRevertButton")
            self.revert_button.setProperty("buttonRole", "secondary")
            action_layout.addWidget(self.revert_button)
            action_layout.addWidget(self.save_button)
            root.addWidget(action_host)

            self.save_button.clicked.connect(self.save)
            self.revert_button.clicked.connect(self.revert)
        else:
            self.save_button = None
            self.revert_button = None

    def load_from_service(self) -> None:
        """Load the latest persisted preferences and populate page fields."""
        try:
            snapshot = self._preferences_service.load_snapshot()
        except PreferencesServiceError as exc:
            self._snapshot_preferences = {}
            self._set_status(f"Unable to load preferences: {exc}", level="error")
            return
        self._snapshot_preferences = snapshot.copy_preferences()
        self._populate_from_preferences(self._snapshot_preferences)
        self._set_status("Preferences loaded. Save changes to apply them to eligible GUI pages.")

    def revert(self) -> None:
        """Revert visible fields to the last persisted snapshot."""
        self.load_from_service()
        self._set_status("Reverted to persisted preferences.")

    def save(self) -> None:
        """Persist the concrete page update through ``PreferencesService``."""
        try:
            updates = self._collect_updates()
            plan = self._preferences_service.save(updates)
        except PreferenceValidationError as exc:
            self._set_status("Unable to save preferences: " + "; ".join(exc.result.error_messages), level="error")
            return
        except PreferencesServiceError as exc:
            self._set_status(f"Unable to save preferences: {exc}", level="error")
            return
        except ValueError as exc:
            self._set_status(f"Unable to save preferences: {exc}", level="error")
            return

        self._snapshot_preferences = plan.copy_preferences()
        self._populate_from_preferences(self._snapshot_preferences)
        changed = ", ".join(plan.changed_paths[:6])
        suffix = f" Changed: {changed}." if changed else " No values changed."
        self._set_status(
            "Preferences saved. Applying eligible GUI updates." + suffix,
            level="success",
        )
        self.preferencesSaved.emit(plan)

    def mark_live_apply_result(self, message: str, *, level: str = "success") -> None:
        """Render the result of main-window-owned live preference application."""
        self._set_status(message, level=level)

    def _set_status(self, message: str, *, level: str = "info") -> None:
        self.status_label.setText(message)
        self.status_label.setProperty("level", level)
        repolish(self.status_label)

    @staticmethod
    def _mapping(preferences: Mapping[str, Any], key: str) -> dict[str, Any]:
        value = preferences.get(key)
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _as_float(value: object, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_int(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _populate_from_preferences(self, preferences: Mapping[str, Any]) -> None:
        raise NotImplementedError

    def _collect_updates(self) -> dict[str, Any]:
        raise NotImplementedError


def create_read_only_value(text: str, parent: QWidget | None = None) -> QLabel:
    """Return a consistently styled read-only value label."""
    label = QLabel(text, parent)
    label.setObjectName("guiCardBody")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label
