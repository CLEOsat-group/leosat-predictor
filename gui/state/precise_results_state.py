"""GUI-local storage for the latest precise prediction results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

PLANNER_HANDOFF_DEFERRED_MESSAGE = (
    "Send to Planner is visible but disabled until a GUI planner consumer is implemented."
)


if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

    from gui.state.precise_execution_state import PreciseExecutionSnapshot


@dataclass(frozen=True, slots=True)
class PreciseResultSummary:
    """Small defensive summary for a completed precise result table."""

    row_count: int
    satellite_count: int | None
    time_range: str
    columns: tuple[str, ...]


class PreciseResultsState:
    """Mutable GUI result cache for the latest precise run."""

    def __init__(self) -> None:
        self.latest_results: "pd.DataFrame | None" = None
        self.latest_summary: PreciseResultSummary | None = None
        self.latest_error: str | None = None
        self.latest_started_at: datetime | None = None
        self.latest_completed_at: datetime | None = None
        self.latest_snapshot: "PreciseExecutionSnapshot | None" = None
        self.latest_export_path: Path | None = None
        self.latest_exported_at: datetime | None = None
        self.latest_export_error: str | None = None
        self.latest_export_warning: str | None = None
        self.latest_handoff_message: str | None = None
        self.latest_handoff_error: str | None = None
        self.latest_handoff_at: datetime | None = None

    def clear(self) -> None:
        """Clear the latest precise result state."""
        self.latest_results = None
        self.latest_summary = None
        self.latest_error = None
        self.latest_started_at = None
        self.latest_completed_at = None
        self.latest_snapshot = None
        self._clear_action_metadata()

    def mark_started(
        self,
        started_at: datetime,
        snapshot: "PreciseExecutionSnapshot | None" = None,
    ) -> None:
        """Record when the latest run started and clear stale failure/action data.

        Parameters
        ----------
        started_at : datetime.datetime
            Local timestamp when the run was started.
        snapshot : PreciseExecutionSnapshot, optional
            Immutable execution request associated with the run.
        """
        self.latest_started_at = started_at
        self.latest_completed_at = None
        self.latest_error = None
        if snapshot is not None:
            self.latest_snapshot = snapshot
        self._clear_action_metadata()

    def set_error(self, message: str) -> None:
        """Record a failed precise run without replacing previous results."""
        self.latest_error = message
        self.latest_completed_at = datetime.now().astimezone()

    def set_results(
        self,
        results: "pd.DataFrame",
        snapshot: "PreciseExecutionSnapshot | None" = None,
    ) -> PreciseResultSummary:
        """Store the latest result frame and return its defensive summary.

        Parameters
        ----------
        results : pandas.DataFrame
            Completed precise prediction results.
        snapshot : PreciseExecutionSnapshot, optional
            Immutable run metadata. When provided, it replaces the current
            snapshot and is later used for default export filenames and TLE copy.
        """
        self.latest_results = results
        self.latest_completed_at = datetime.now().astimezone()
        self.latest_error = None
        if snapshot is not None:
            self.latest_snapshot = snapshot
        self._clear_action_metadata()
        summary = summarize_precise_results(results)
        self.latest_summary = summary
        return summary

    def has_results(self) -> bool:
        """Return whether a non-empty precise result frame is available."""
        return self.latest_results is not None and not getattr(self.latest_results, "empty", True)

    def can_export(self) -> bool:
        """Return whether the latest completed precise results can be exported."""
        return self.has_results()

    def can_handoff(self, *, consumer_available: bool = False) -> bool:
        """Return whether precise results can be sent to a real GUI planner consumer.

        The action is intentionally gated until a concrete planner receiving
        boundary exists.  This prevents a misleading navigation-only handoff
        while keeping the precise workflow controls visually complete.
        """
        return self.has_results() and consumer_available

    def mark_exported(self, csv_path: str | Path, *, warning: str | None = None) -> None:
        """Record successful CSV export metadata."""
        self.latest_export_path = Path(csv_path)
        self.latest_exported_at = datetime.now().astimezone()
        self.latest_export_error = None
        self.latest_export_warning = warning

    def set_export_error(self, message: str) -> None:
        """Record a CSV export error without changing the result table."""
        self.latest_export_error = message
        self.latest_export_warning = None

    def set_handoff_message(self, message: str) -> None:
        """Record an honest planner-action status message."""
        self.latest_handoff_message = message
        self.latest_handoff_error = None
        self.latest_handoff_at = datetime.now().astimezone()

    def set_handoff_error(self, message: str) -> None:
        """Record a planner handoff error without changing the result table."""
        self.latest_handoff_error = message
        self.latest_handoff_message = None
        self.latest_handoff_at = datetime.now().astimezone()

    def _clear_action_metadata(self) -> None:
        """Clear stale export and planner-action metadata after lifecycle changes."""
        self.latest_export_path = None
        self.latest_exported_at = None
        self.latest_export_error = None
        self.latest_export_warning = None
        self.latest_handoff_message = None
        self.latest_handoff_error = None
        self.latest_handoff_at = None


def summarize_precise_results(results: "pd.DataFrame") -> PreciseResultSummary:
    """Create a defensive summary without assuming one fixed precise schema."""
    columns = tuple(str(column) for column in getattr(results, "columns", ()))
    row_count = int(len(results))
    satellite_count = _satellite_count(results, columns)
    time_range = _time_range(results, columns)
    return PreciseResultSummary(
        row_count=row_count,
        satellite_count=satellite_count,
        time_range=time_range,
        columns=columns,
    )


def _satellite_count(results: "pd.DataFrame", columns: tuple[str, ...]) -> int | None:
    for column in ("Sat_ID", "Satellite", "Satellite_Name", "Name", "satellite"):
        if column in columns:
            try:
                return int(results[column].nunique(dropna=True))
            except Exception:
                return None
    return None


def _time_range(results: "pd.DataFrame", columns: tuple[str, ...]) -> str:
    """Return a compact time range for known precise result schemas."""
    for start_column, end_column in (
        ("Obs_Time", "Obs_Time"),
        ("Local_Time", "Local_Time"),
        ("UTC_Time", "UTC_Time"),
        ("Time", "Time"),
        ("Start_Time", "Start_Time"),
        ("Max_Elev_Time", "Max_Elev_Time"),
        ("rise_time_utc", "set_time_utc"),
        ("rise_time_loc", "set_time_loc"),
    ):
        if start_column in columns and end_column in columns:
            return _range_from_columns(results, start_column, end_column)
    return "—"


def _range_from_columns(results: "pd.DataFrame", start_column: str, end_column: str) -> str:
    """Return a defensive min-start to max-end range from two result columns."""
    try:
        start_values = results[start_column].dropna()
        end_values = results[end_column].dropna()
        if start_values.empty or end_values.empty:
            return "—"
        start_value = start_values.min()
        end_value = end_values.max()
        return f"{_format_time_value(start_value)} → {_format_time_value(end_value)}"
    except Exception:
        return "—"


def _format_time_value(value: object) -> str:
    """Format a time-like value without assuming one concrete pandas dtype."""
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return str(value)


__all__ = [
    "PLANNER_HANDOFF_DEFERRED_MESSAGE",
    "PreciseResultSummary",
    "PreciseResultsState",
    "summarize_precise_results",
]
