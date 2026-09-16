"""GUI-v2 presenter for exporting completed precise prediction results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import QFileDialog, QWidget

from gui_v2.services.prediction_export_service import (
    PredictionCsvExportRequest,
    PredictionExportError,
    PredictionExportService,
)
from gui_v2.shell.mode_registry import MODE_PRECISE
from gui_v2.state.precise_results_state import PreciseResultsState


class PreciseExportPresenter:
    """Coordinate precise CSV export dialogs and shared-service calls.

    The presenter owns GUI-only dialog interaction.  The actual CSV projection,
    precise public-column contract, and optional TLE sidecar copy remain owned by
    :class:`PredictionExportService` so GUI v2 does not duplicate export policy.
    """

    def __init__(
        self,
        *,
        results_state: PreciseResultsState,
        parent: QWidget,
        export_service: PredictionExportService | None = None,
    ) -> None:
        self._results_state = results_state
        self._parent = parent
        self._export_service = export_service or PredictionExportService()

    def export_csv(self) -> Path | None:
        """Prompt for a CSV destination and export the latest precise result.

        Returns
        -------
        pathlib.Path or None
            Written CSV path on success. ``None`` is returned for user
            cancellation or recoverable export failure; the state carries the
            error message when a failure occurred.
        """
        if not self._results_state.can_export():
            self._results_state.set_export_error("No precise results are available for export.")
            return None

        results = self._results_state.latest_results
        snapshot = self._results_state.latest_snapshot
        if results is None:
            self._results_state.set_export_error("No precise results are available for export.")
            return None
        if snapshot is None:
            self._results_state.set_export_error("Precise export metadata is missing.")
            return None

        default_path = self._default_export_path(
            constellation=snapshot.constellation,
            time_of_day=_prediction_range_label(snapshot.constraints),
        )
        selected_path = self._select_csv_path(default_path)
        if selected_path is None:
            return None

        try:
            export_result = self._export_service.write_csv(
                PredictionCsvExportRequest(
                    mode=MODE_PRECISE,
                    results=results,
                    csv_path=selected_path,
                    precise_tle_source_path=snapshot.source_file,
                )
            )
        except PredictionExportError as exc:
            self._results_state.set_export_error(str(exc))
            return None
        except OSError as exc:
            self._results_state.set_export_error(f"Unable to write CSV file: {exc}")
            return None

        warning = None
        if export_result.tle_copy_error:
            warning = f"TLE file could not be copied: {export_result.tle_copy_error}"
        self._results_state.mark_exported(export_result.csv_path, warning=warning)
        return export_result.csv_path

    def _default_export_path(self, *, constellation: str | None, time_of_day: str | None) -> Path:
        """Return the default destination path for the save dialog."""
        filename = self._export_service.build_default_filename(
            mode=MODE_PRECISE,
            constellation=constellation,
            time_of_day=time_of_day,
        )
        return Path.home() / filename

    def _select_csv_path(self, default_path: Path) -> Path | None:
        """Return a user-selected CSV path, or ``None`` if cancelled."""
        selected, _selected_filter = QFileDialog.getSaveFileName(
            self._parent,
            "Export Precise Results",
            str(default_path),
            "CSV files (*.csv)",
        )
        if not selected:
            return None
        path = Path(selected)
        if path.suffix.lower() != ".csv":
            path = path.with_suffix(".csv")
        return path


def _prediction_range_label(constraints: dict[str, Any]) -> str:
    """Return the precise time-of-day label captured by the execution snapshot."""
    value = constraints.get("prediction_range_precise", "both")
    label = str(value).strip().lower()
    return label or "both"


__all__ = ["PreciseExportPresenter"]
