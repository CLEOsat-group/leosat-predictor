"""Qt table model for the generated observation plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from gui.styles import active_theme_palette
from src.observation_planner.coordinate_format import COORD_FORMAT_COLON, format_coordinate_value, normalize_coordinate_format

SOURCE_ROLE = Qt.ItemDataRole.UserRole.value + 1

PLAN_COLUMNS = ("satellite", "date_ut", "ra", "dec", "elev", "solar_phase_angle")
PLAN_HEADERS = (
    "Satellite",
    "Date [UT]",
    "RA [hr]",
    "DEC [deg]",
    "Elev. [deg]",
    "Solar Phase [deg]",
)
MANUAL_SOURCE = "manual"
GENERATED_SOURCE = "plan"


@dataclass(frozen=True)
class ObservationPlanRecord:
    """One observation-plan row.

    Parameters
    ----------
    satellite : object
        Satellite identifier or display name.
    date_ut : object
        Observation timestamp in UTC.
    ra : object
        Right ascension value.
    dec : object
        Declination value.
    elev : object
        Satellite elevation value.
    solar_phase_angle : object, optional
        Solar phase angle value in degrees.  This is optional so legacy
        selector/manual rows that do not provide the field remain valid.
    source : str, optional
        Row source marker, either ``"manual"`` or ``"plan"``.
    global_index, base_index, local_index : object, optional
        Hidden row-identity fields propagated from visibility data when
        available.  They are not displayed in the plan table, but they allow
        diagnostics to be refreshed after manual plan edits without losing the
        original source-row identity.
    """

    satellite: object
    date_ut: object
    ra: object
    dec: object
    elev: object
    solar_phase_angle: object = ""
    source: str = GENERATED_SOURCE
    global_index: object = None
    base_index: object = None
    local_index: object = None

    def as_tuple(self) -> tuple[object, object, object, object, object, object]:
        """Return the display fields as a tuple."""
        return (
            self.satellite,
            self.date_ut,
            self.ra,
            self.dec,
            self.elev,
            self.solar_phase_angle,
        )


def plan_record_key(
    record: ObservationPlanRecord | None,
    *,
    include_source: bool = True,
) -> tuple[object, ...] | None:
    """Return the stable identity key shared by controller and table view.

    Parameters
    ----------
    record : ObservationPlanRecord or None
        Record to identify.
    include_source : bool, optional
        Include the manual/generated source marker when distinguishing rows.

    Returns
    -------
    tuple or None
        Stable helper-column identity when available, otherwise satellite/time.
    """

    if record is None:
        return None
    suffix: tuple[object, ...] = (str(record.source),) if include_source else ()
    for identity_column in ("global_index", "base_index", "local_index"):
        value = getattr(record, identity_column, None)
        if _valid_identity(value):
            return (identity_column, _normalized_identity(value), *suffix)
    return (str(record.satellite), str(record.date_ut), *suffix)


def _valid_identity(value: object) -> bool:
    if value is None:
        return False
    try:
        return not bool(pd.isna(value))
    except Exception:
        return True


def _normalized_identity(value: object) -> object:
    """Normalize scalar NumPy/float identities without changing equality."""

    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


class ObservationPlanTableModel(QAbstractTableModel):
    """Model-backed observation-plan table.

    Parameters
    ----------
    parent : QObject, optional
        Parent Qt object.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[ObservationPlanRecord] = []
        self._coordinate_format = COORD_FORMAT_COLON

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(PLAN_COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: A003
        if not index.isValid():
            return None
        row = index.row()
        column = index.column()
        if row < 0 or column < 0 or row >= len(self._records) or column >= len(PLAN_COLUMNS):
            return None

        record = self._records[row]
        value = record.as_tuple()[column]

        if role == Qt.ItemDataRole.DisplayRole:
            return self._render_value(value, PLAN_COLUMNS[column], self._coordinate_format)
        if role == Qt.ItemDataRole.UserRole:
            return value
        if role == SOURCE_ROLE:
            return record.source
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if PLAN_COLUMNS[column] in {"ra", "dec", "elev", "solar_phase_angle"}:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.BackgroundRole:
            palette = active_theme_palette()
            if self._is_past(record.date_ut):
                return QColor(palette.row_past_background)
            if record.source == MANUAL_SOURCE:
                return QColor(palette.row_manual_background)
            return QColor(palette.row_generated_background)
        if role == Qt.ItemDataRole.ForegroundRole:
            palette = active_theme_palette()
            if self._is_past(record.date_ut):
                return QColor(palette.row_past_foreground)
            if record.source == MANUAL_SOURCE:
                return QColor(palette.row_manual_foreground)
            return QColor(palette.row_generated_foreground)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(PLAN_HEADERS):
                return PLAN_HEADERS[section]
            return None
        return str(section + 1)

    def flags(self, index: QModelIndex):  # noqa: D401
        """Return read-only selectable table-item flags."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def coordinate_format(self) -> str:
        """Return the active RA/DEC display-format identifier."""
        return self._coordinate_format

    def set_coordinate_format(self, coordinate_format: str | None) -> None:
        """Set the RA/DEC display format without mutating raw records.

        Parameters
        ----------
        coordinate_format : str or None
            Requested coordinate-format identifier.
        """
        normalized = normalize_coordinate_format(coordinate_format)
        if normalized == self._coordinate_format:
            return
        self._coordinate_format = normalized
        if not self._records:
            return
        first_column = PLAN_COLUMNS.index("ra")
        last_column = PLAN_COLUMNS.index("dec")
        top_left = self.index(0, first_column)
        bottom_right = self.index(len(self._records) - 1, last_column)
        self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])

    def add_record(self, record: ObservationPlanRecord, *, sort_after: bool = True) -> None:
        """Append one record to the observation plan.

        Parameters
        ----------
        record : ObservationPlanRecord
            Record to add.
        sort_after : bool, optional
            If `True`, sort by observation time after insertion.
        """
        row = len(self._records)
        self.beginInsertRows(QModelIndex(), row, row)
        self._records.append(record)
        self.endInsertRows()
        if sort_after:
            self.sort_by_time()

    def add_records(self, records: Iterable[ObservationPlanRecord], *, sort_after: bool = True) -> None:
        """Append multiple records to the observation plan."""
        records = list(records)
        if not records:
            return
        start = len(self._records)
        end = start + len(records) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self._records.extend(records)
        self.endInsertRows()
        if sort_after:
            self.sort_by_time()

    def remove_row(self, row: int) -> ObservationPlanRecord | None:
        """Remove and return the row at a model index.

        Parameters
        ----------
        row : int
            Model row to remove.

        Returns
        -------
        ObservationPlanRecord or None
            Removed record, or `None` if the row was invalid.
        """
        if row < 0 or row >= len(self._records):
            return None
        self.beginRemoveRows(QModelIndex(), row, row)
        record = self._records.pop(row)
        self.endRemoveRows()
        return record

    def clear_generated(self) -> list[ObservationPlanRecord]:
        """Remove generated rows while preserving manually checked rows.

        Returns
        -------
        list of ObservationPlanRecord
            Removed generated records.
        """
        removed = [record for record in self._records if record.source == GENERATED_SOURCE]
        kept = [record for record in self._records if record.source != GENERATED_SOURCE]
        if len(kept) == len(self._records):
            return []
        self.beginResetModel()
        self._records = kept
        self.endResetModel()
        return removed

    def clear(self) -> None:
        """Remove all observation-plan rows."""
        self.beginResetModel()
        self._records = []
        self.endResetModel()

    def replace_records(self, records: Iterable[ObservationPlanRecord], *, sort_by_time: bool = True) -> None:
        """Replace all records in one model reset.

        Sorting occurs before the reset so the view observes one atomic model
        mutation rather than clear/insert/layout-change sequences.
        """

        replacement = list(records)
        if sort_by_time:
            replacement.sort(key=lambda record: pd.to_datetime(record.date_ut, errors="coerce"))
        self.beginResetModel()
        self._records = replacement
        self.endResetModel()

    def row_for_record(self, record: ObservationPlanRecord | None) -> int | None:
        """Return the row matching ``record`` by stable plan identity."""

        target = plan_record_key(record)
        if target is None:
            return None
        for row, candidate in enumerate(self._records):
            if plan_record_key(candidate) == target:
                return row
        return None

    def record_at(self, row: int) -> ObservationPlanRecord | None:
        """Return one record without removing it."""
        if 0 <= row < len(self._records):
            return self._records[row]
        return None

    def records(self) -> list[ObservationPlanRecord]:
        """Return a copy of all plan records."""
        return list(self._records)

    def sort_by_time(self) -> None:
        """Sort the observation plan by UTC observation time."""
        if len(self._records) < 2:
            return
        self.layoutAboutToBeChanged.emit()
        self._records.sort(key=lambda record: pd.to_datetime(record.date_ut, errors="coerce"))
        self.layoutChanged.emit()

    def refresh_time_state(self) -> None:
        """Refresh row backgrounds affected by past/future time state."""
        if not self._records:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._records) - 1, len(PLAN_COLUMNS) - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.BackgroundRole])

    def to_dataframe(self, *, include_metadata: bool = False) -> pd.DataFrame:
        """Return the current plan as a DataFrame accepted by export helpers.

        Parameters
        ----------
        include_metadata : bool, optional
            If `True`, include hidden non-display fields used by diagnostics
            (`source`, `global_index`, `base_index`, `local_index`).  The
            default keeps the public/export table schema unchanged.
        """
        rows = [record.as_tuple() for record in self._records]
        dataframe = pd.DataFrame(rows, columns=list(PLAN_COLUMNS))
        if include_metadata:
            dataframe["source"] = [record.source for record in self._records]
            dataframe["global_index"] = [record.global_index for record in self._records]
            dataframe["base_index"] = [record.base_index for record in self._records]
            dataframe["local_index"] = [record.local_index for record in self._records]
        return dataframe

    @staticmethod
    def from_plan_dataframe(plan_df: pd.DataFrame, *, source: str = GENERATED_SOURCE) -> list[ObservationPlanRecord]:
        """Convert a shared-core plan DataFrame into table records.

        Parameters
        ----------
        plan_df : pandas.DataFrame
            Plan table returned by ``generate_observation_plan``.
        source : str, optional
            Source marker to apply to all records.

        Returns
        -------
        list of ObservationPlanRecord
            Converted plan records.
        """
        from src.observation_planner.schema import resolve_column

        if plan_df is None or plan_df.empty:
            return []
        sat_col = resolve_column(plan_df, "satellite")
        date_col = resolve_column(plan_df, "date_ut", required=False) or "datetime"
        ra_col = resolve_column(plan_df, "ra")
        dec_col = resolve_column(plan_df, "dec")
        elev_col = resolve_column(plan_df, "elev")
        solar_phase_col = resolve_column(plan_df, "solar_phase_angle", required=False)
        def _optional_value(row, column_name: str):
            return row[column_name] if column_name in plan_df.columns else None

        records = []
        for _, row in plan_df.iterrows():
            records.append(
                ObservationPlanRecord(
                    satellite=row[sat_col],
                    date_ut=row[date_col],
                    ra=row[ra_col],
                    dec=row[dec_col],
                    elev=row[elev_col],
                    solar_phase_angle=(row[solar_phase_col] if solar_phase_col is not None else ""),
                    source=source,
                    global_index=_optional_value(row, "global_index"),
                    base_index=_optional_value(row, "base_index"),
                    local_index=_optional_value(row, "local_index"),
                )
            )
        return records

    @staticmethod
    def _render_value(value: object, logical: str, coordinate_format: str = COORD_FORMAT_COLON) -> str:
        """Render a plan-table value for display."""
        if pd.isna(value):
            return ""
        if logical in {"ra", "dec"}:
            return format_coordinate_value(value, coordinate_format)
        if logical in {"elev", "solar_phase_angle"}:
            try:
                return f"{float(value):.2f}"
            except Exception:
                return str(value)
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    @staticmethod
    def _is_past(value: object) -> bool:
        """Return whether a row timestamp is in the past."""
        try:
            timestamp = pd.to_datetime(value, utc=True, errors="coerce")
            if pd.isna(timestamp):
                return False
            return timestamp < pd.Timestamp.utcnow()
        except Exception:
            return False


__all__ = [
    "GENERATED_SOURCE",
    "MANUAL_SOURCE",
    "ObservationPlanRecord",
    "ObservationPlanTableModel",
    "PLAN_COLUMNS",
    "PLAN_HEADERS",
    "SOURCE_ROLE",
    "plan_record_key",
]
