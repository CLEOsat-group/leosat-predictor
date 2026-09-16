"""GUI-v2 presenter for exporting Observation Planner results."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QFileDialog, QWidget

from gui_v2.controllers import PlannerController
from gui_v2.helpers.planner_export_naming import (
    DEFAULT_PLANNER_EXPORT_PATTERN,
    build_planner_export_filename,
)
from gui_v2.state.planner_state import PlannerExportResult


class PlannerExportPresenter:
    """Coordinate planner export dialogs and controller-owned file writing.

    The presenter owns GUI-only file-dialog interaction.  The controller remains
    the source of truth for current plan rows, coordinate format, diagnostics
    refresh, and calls to the shared planner export helpers.
    """

    def __init__(self, *, planner_controller: PlannerController, parent: QWidget) -> None:
        self._planner_controller = planner_controller
        self._parent = parent
        self._last_export_dir: Path | None = None

    def export_plan(self) -> PlannerExportResult | None:
        """Prompt for a destination and export the current planner rows.

        Returns
        -------
        PlannerExportResult or None
            Export metadata on success. ``None`` is returned when no plan is
            available, the user cancels the dialog, or export fails in a
            recoverable way.
        """
        snapshot = self._planner_controller.current_snapshot()
        if not snapshot.readiness.plan_available:
            self._planner_controller.append_log("No observation plan to export.")
            self._planner_controller.set_status_message("No observation plan to export.")
            return None

        selected_path = self._select_export_path(self._default_export_path())
        if selected_path is None:
            return None

        try:
            result = self._planner_controller.export_current_plan(
                selected_path,
                coordinate_format=snapshot.coordinate_format,
                refresh_diagnostics=True,
            )
        except Exception as exc:
            message = f"Failed to export observation plan: {exc}"
            self._planner_controller.append_log(message)
            self._planner_controller.set_status_message(message)
            return None

        self._last_export_dir = result.plan_path.parent
        return result

    def _default_export_path(self) -> Path:
        """Return the default destination shown in the save dialog."""
        filename = self._default_filename()
        export_dir = self._last_export_dir or self._snapshot_export_dir() or self._documents_dir()
        return export_dir / filename

    def _default_filename(self) -> str:
        """Return a method-aware filename for the current observation plan."""
        now = datetime.now(UTC)
        pattern = str(getattr(self._planner_controller.preferences, "filename_pattern", "") or "").strip()
        return build_planner_export_filename(
            pattern or DEFAULT_PLANNER_EXPORT_PATTERN,
            plan_method=self._planner_controller.current_plan_export_method(),
            timestamp=now,
        )

    def _snapshot_export_dir(self) -> Path | None:
        """Return a directory inferred from the last exported or loaded file."""
        snapshot = self._planner_controller.current_snapshot()
        for value in (snapshot.last_export_path, snapshot.visibility_file_path):
            if not value:
                continue
            path = Path(str(value))
            # In-memory precise handoffs store human labels rather than real paths.
            if path.parent != Path(".") and path.parent.exists():
                return path.parent
        return None

    @staticmethod
    def _documents_dir() -> Path:
        """Return a writable user documents directory with a home fallback."""
        location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if location:
            return Path(location)
        return Path.home()

    def _select_export_path(self, default_path: Path) -> Path | None:
        """Return the user-selected export path, or ``None`` on cancellation."""
        selected, selected_filter = QFileDialog.getSaveFileName(
            self._parent,
            "Save Observation Plan",
            str(default_path),
            "CSV Files (*.csv);;TXT Files (*.txt);;All Files (*)",
        )
        if not selected:
            return None
        path = Path(selected)
        if path.suffix:
            return path
        if "TXT" in selected_filter.upper():
            return path.with_suffix(".txt")
        return path.with_suffix(".csv")


__all__ = ["PlannerExportPresenter"]
