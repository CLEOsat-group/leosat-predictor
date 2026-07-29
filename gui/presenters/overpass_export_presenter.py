"""GUI presenter for exporting completed overpass results to CSV."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QWidget

from gui.services.prediction_export_service import (
    PredictionCsvExportRequest,
    PredictionExportError,
    PredictionExportService,
)
from gui.shell.mode_registry import MODE_OVERPASS
from gui.state.overpass_results_state import OverpassResultsState


class OverpassExportPresenter:
    """Coordinate overpass CSV export dialogs and shared-service calls.

    The presenter owns GUI-only dialog interaction.  It deliberately delegates
    the actual CSV write policy to :class:`PredictionExportService` so GUI
    does not duplicate export behavior.
    """

    def __init__(
        self,
        *,
        results_state: OverpassResultsState,
        parent: QWidget,
        export_service: PredictionExportService | None = None,
    ) -> None:
        self._results_state = results_state
        self._parent = parent
        self._export_service = export_service or PredictionExportService()

    def export_csv(self) -> Path | None:
        """Prompt for a CSV destination and export the latest overpass result.

        Returns
        -------
        pathlib.Path or None
            Written CSV path on success. ``None`` is returned for user
            cancellation or recoverable export failure; the state carries the
            error message when a failure occurred.
        """
        if not self._results_state.can_export():
            self._results_state.set_export_error("No overpass results are available for export.")
            return None

        results = self._results_state.latest_results
        snapshot = self._results_state.latest_snapshot
        if results is None:
            self._results_state.set_export_error("No overpass results are available for export.")
            return None
        if snapshot is None:
            self._results_state.set_export_error("Overpass export metadata is missing.")
            return None

        default_path = self._default_export_path(snapshot.constellation, snapshot.days)
        selected_path = self._select_csv_path(default_path)
        if selected_path is None:
            return None

        try:
            export_result = self._export_service.write_csv(
                PredictionCsvExportRequest(
                    mode=MODE_OVERPASS,
                    results=results,
                    csv_path=selected_path,
                )
            )
        except PredictionExportError as exc:
            self._results_state.set_export_error(str(exc))
            return None
        except OSError as exc:
            self._results_state.set_export_error(f"Unable to write CSV file: {exc}")
            return None

        self._results_state.mark_exported(export_result.csv_path)
        return export_result.csv_path

    def _default_export_path(self, constellation: str | None, days: int | str | None) -> Path:
        """Return the default destination path for the save dialog."""
        filename = self._export_service.build_default_filename(
            mode=MODE_OVERPASS,
            constellation=constellation,
            days_to_predict=days,
        )
        return Path.home() / filename

    def _select_csv_path(self, default_path: Path) -> Path | None:
        """Return a user-selected CSV path, or ``None`` if cancelled."""
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self._parent,
            "Export Overpass Results",
            str(default_path),
            "CSV files (*.csv)",
        )
        if not selected:
            return None
        path = Path(selected)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        return path


__all__ = ["OverpassExportPresenter"]
