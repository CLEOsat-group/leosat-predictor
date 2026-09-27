"""Precise-prediction to Observation Planner handoff service.

This module prepares typed, non-visual payloads for direct in-memory handoff
from completed precise predictions to the Observation Planner.  It does not
call widgets, open dialogs, write temporary CSV files, or switch GUI modes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import pandas as pd

from gui.services.prediction_export_service import PredictionExportService
from gui.shell.mode_registry import MODE_PRECISE


class PlannerHandoffError(RuntimeError):
    """Raised when precise prediction results cannot be handed to the planner."""


@dataclass(frozen=True)
class PlannerHandoffPayload:
    """Payload consumed by the GUI-level Observation Planner widget call.

    Parameters
    ----------
    dataframe : pandas.DataFrame
        Public precise export projection to load into the planner.
    source_label : str
        Human-readable source label for planner logs and status text.
    tle_source_path : pathlib.Path, optional
        File-backed TLE source associated with the completed precise prediction.
    row_count : int
        Number of rows in the handoff DataFrame.
    column_count : int
        Number of columns in the handoff DataFrame.
    missing_columns : tuple[str, ...]
        Expected precise export columns missing from the source DataFrame.
    """

    dataframe: pd.DataFrame
    source_label: str
    tle_source_path: Path | None
    row_count: int
    column_count: int
    missing_columns: tuple[str, ...] = field(default_factory=tuple)


class PlannerHandoffService:
    """Prepare direct precise-result handoff payloads without UI dependencies."""

    def __init__(self, export_service: PredictionExportService | None = None):
        self._export_service = export_service or PredictionExportService()

    def prepare_precise_handoff(
        self,
        *,
        precise_results: pd.DataFrame | None,
        tle_source_path: str | Path | None = None,
        source_label: str = "Precise Prediction",
    ) -> PlannerHandoffPayload:
        """Prepare a public precise projection for Observation Planner loading.

        Parameters
        ----------
        precise_results : pandas.DataFrame or None
            Completed precise prediction results from the precise cache.
        tle_source_path : str or pathlib.Path, optional
            File-backed TLE source captured by the completed precise prediction.
        source_label : str, default: "Precise Prediction"
            Human-readable label passed to the planner load path.

        Returns
        -------
        PlannerHandoffPayload
            Typed handoff payload ready for the GUI widget boundary.
        """
        if precise_results is None or precise_results.empty:
            raise PlannerHandoffError(
                "No completed precise prediction results are available to send to the planner."
            )

        projection = self._export_service.prepare_export_projection(precise_results, MODE_PRECISE)
        dataframe = projection.dataframe
        return PlannerHandoffPayload(
            dataframe=dataframe,
            source_label=source_label,
            tle_source_path=Path(tle_source_path) if tle_source_path else None,
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
            missing_columns=projection.missing_columns,
        )


__all__: Sequence[str] = (
    "PlannerHandoffError",
    "PlannerHandoffPayload",
    "PlannerHandoffService",
)
