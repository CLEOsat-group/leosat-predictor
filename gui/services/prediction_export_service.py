"""Prediction CSV export service for the PyQt GUI.

This module owns non-visual export policy for GUI prediction results.  It does
not import Qt widgets, show dialogs, mutate widget state, or run predictions.
The main window remains responsible for collecting user choices and presenting
feedback to the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

import pandas as pd

from gui.helpers.tle_file_index import copy_tle_file_for_csv
from gui.shell.mode_registry import MODE_OVERPASS, MODE_PRECISE, PREDICTION_MODES
from src.prediction_core.precise_materialization import COLUMN_ORDER_PRECISE_EXPORT


class PredictionExportError(RuntimeError):
    """Raised when a prediction export request cannot be completed."""


@dataclass(frozen=True)
class PredictionCsvExportRequest:
    """Input required to write one prediction CSV export.

    Parameters
    ----------
    mode : str
        Active prediction mode. Supported values are ``"overpass"`` and
        ``"precise"``.
    results : pandas.DataFrame
        Source prediction results from the active completed prediction.
    csv_path : str or pathlib.Path
        Destination CSV path selected by the GUI.
    precise_tle_source_path : str or pathlib.Path, optional
        File-backed TLE source associated with the completed precise prediction.
        This is ignored for overpass exports.
    """

    mode: str
    results: pd.DataFrame
    csv_path: str | Path
    precise_tle_source_path: str | Path | None = None


@dataclass(frozen=True)
class PredictionCsvExportResult:
    """Structured result returned after writing a prediction CSV.

    Parameters
    ----------
    csv_path : pathlib.Path
        Written CSV path.
    export_results : pandas.DataFrame
        DataFrame that was actually written to disk.
    source_row_count : int
        Number of rows in the original source DataFrame.
    source_column_count : int
        Number of columns in the original source DataFrame.
    export_row_count : int
        Number of rows in the public export DataFrame.
    export_column_count : int
        Number of columns in the public export DataFrame.
    missing_columns : tuple[str, ...]
        Expected precise export columns missing from the source DataFrame.
    copied_tle_path : pathlib.Path, optional
        Copied TLE path when a file-backed precise source was available.
    tle_copy_error : str, optional
        Non-fatal TLE copy error. The CSV has still been written.
    """

    csv_path: Path
    export_results: pd.DataFrame
    source_row_count: int
    source_column_count: int
    export_row_count: int
    export_column_count: int
    missing_columns: tuple[str, ...] = field(default_factory=tuple)
    copied_tle_path: Path | None = None
    tle_copy_error: str | None = None


@dataclass(frozen=True)
class PredictionExportProjection:
    """Public export projection for a prediction result table.

    Parameters
    ----------
    dataframe : pandas.DataFrame
        Projected DataFrame suitable for public CSV export or planner handoff.
    missing_columns : tuple[str, ...]
        Expected precise export columns missing from the source DataFrame.
    """

    dataframe: pd.DataFrame
    missing_columns: tuple[str, ...] = field(default_factory=tuple)


class PredictionExportService:
    """Prepare and write GUI prediction CSV exports without UI dependencies."""

    def build_default_filename(
        self,
        *,
        mode: str,
        constellation: str | None,
        days_to_predict: int | str | None = None,
        time_of_day: str | None = None,
        timestamp: str | None = None,
    ) -> str:
        """Return the default CSV filename for the requested prediction mode.

        Parameters
        ----------
        mode : str
            Active prediction mode.
        constellation : str, optional
            Constellation display token from the active TLE widget.
        days_to_predict : int or str, optional
            Overpass prediction horizon used only for overpass filenames.
        time_of_day : str, optional
            Precise prediction range label. ``"both"`` omits the suffix.
        timestamp : str, optional
            Precomputed timestamp token. When omitted, wall-clock time is used.

        Returns
        -------
        str
            Default CSV filename matching the existing GUI convention.
        """
        self._validate_mode(mode)
        constellation_token = constellation if constellation else "unknown"
        timestamp_token = timestamp or self._timestamp_token()

        if mode == MODE_OVERPASS:
            if days_to_predict is None:
                raise PredictionExportError("Overpass CSV export requires days_to_predict.")
            return f"overpasses_{constellation_token}_{days_to_predict}d_{timestamp_token}.csv"

        normalized_time_of_day = (time_of_day or "both").lower()
        if normalized_time_of_day == "both":
            return f"visible_{constellation_token}_{timestamp_token}.csv"
        return f"visible_{constellation_token}_{timestamp_token}_{normalized_time_of_day}.csv"

    def prepare_export_projection(self, results: pd.DataFrame, mode: str) -> PredictionExportProjection:
        """Return the public export projection for a prediction table.

        Parameters
        ----------
        results : pandas.DataFrame
            Source prediction result table.
        mode : str
            Active prediction mode.

        Returns
        -------
        PredictionExportProjection
            Projected export table and any missing precise export columns.
        """
        self._validate_mode(mode)
        if results is None or results.empty:
            raise PredictionExportError("No prediction results are available for export.")

        if mode != MODE_PRECISE:
            return PredictionExportProjection(dataframe=results)

        export_columns = [column for column in COLUMN_ORDER_PRECISE_EXPORT if column in results.columns]
        missing_columns = tuple(column for column in COLUMN_ORDER_PRECISE_EXPORT if column not in results.columns)
        return PredictionExportProjection(
            dataframe=results.loc[:, export_columns].copy(),
            missing_columns=missing_columns,
        )

    def write_csv(self, request: PredictionCsvExportRequest) -> PredictionCsvExportResult:
        """Write one prediction CSV and optionally copy the precise TLE file.

        Parameters
        ----------
        request : PredictionCsvExportRequest
            Export request prepared by the GUI.

        Returns
        -------
        PredictionCsvExportResult
            Structured export result for logging and user feedback.
        """
        projection = self.prepare_export_projection(request.results, request.mode)
        csv_path = Path(request.csv_path)
        projection.dataframe.to_csv(csv_path, index=False)

        copied_tle_path: Path | None = None
        tle_copy_error: str | None = None
        if request.mode == MODE_PRECISE:
            try:
                copied_tle_path = copy_tle_file_for_csv(request.precise_tle_source_path, csv_path)
            except Exception as exc:  # pragma: no cover - defensive filesystem guard
                tle_copy_error = str(exc)

        return PredictionCsvExportResult(
            csv_path=csv_path,
            export_results=projection.dataframe,
            source_row_count=len(request.results),
            source_column_count=len(request.results.columns),
            export_row_count=len(projection.dataframe),
            export_column_count=len(projection.dataframe.columns),
            missing_columns=projection.missing_columns,
            copied_tle_path=copied_tle_path,
            tle_copy_error=tle_copy_error,
        )

    def _timestamp_token(self) -> str:
        """Return the timestamp token used in GUI CSV filenames."""
        return datetime.now().strftime("%Y-%m-%d_%H%M%S")

    @staticmethod
    def _validate_mode(mode: str) -> None:
        if mode not in PREDICTION_MODES:
            raise PredictionExportError(f"CSV export is not available for mode: {mode!r}")


__all__: Sequence[str] = (
    "PredictionCsvExportRequest",
    "PredictionCsvExportResult",
    "PredictionExportError",
    "PredictionExportProjection",
    "PredictionExportService",
)
