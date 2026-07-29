"""Qt table model for observation-planner visibility rows."""

from __future__ import annotations

from collections import OrderedDict
from typing import Sequence

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal

from src.observation_planner.schema import get_display_name, mapping_from_table, resolve_column


DEFAULT_VISIBILITY_LOGICAL_COLUMNS = (
    "_checked",
    "satellite",
    "date_ut",
    "ra",
    "dec",
    "elev",
    "solar_phase_angle",
    "date_ts",
    "global_index",
    "base_index",
    "local_index",
)

HIDDEN_VISIBILITY_LOGICAL_COLUMNS = {"date_ts", "global_index", "base_index", "local_index"}


class ObservationVisibilityTableModel(QAbstractTableModel):
    """Model-backed visibility table with a checkable first column.

    Parameters
    ----------
    parent : QObject, optional
        Parent Qt object.
    display_logicals : sequence of str, optional
        Logical columns to expose in the table. Missing optional helper columns
        are ignored, while core data columns must be resolvable by the shared
        observation-planner schema.
    """

    user_check_state_changed = pyqtSignal(int, bool)
    """Emitted only for real user checkbox edits handled through setData.

    Programmatic repaint paths emit Qt dataChanged only; they must not
    re-enter observation-plan business logic.
    """

    _MAX_CACHE_ENTRIES = 50000

    def __init__(self, parent=None, display_logicals: Sequence[str] | None = None):
        super().__init__(parent)
        self._source_dataframe = pd.DataFrame()
        self._display_dataframe = pd.DataFrame()
        self._display_logicals = list(display_logicals or DEFAULT_VISIBILITY_LOGICAL_COLUMNS)
        self._physical_columns: list[str] = []
        self._logical_columns: list[str] = []
        self._values = self._display_dataframe.to_numpy(dtype=object, copy=False)
        self._display_cache: OrderedDict[tuple[int, int], str] = OrderedDict()
        self._column_mapping = mapping_from_table(None)

    def set_dataframe(self, dataframe: pd.DataFrame | None) -> None:
        """Reset the model to display a visibility DataFrame.

        Parameters
        ----------
        dataframe : pandas.DataFrame or None
            Visibility table. The model stores a reference to this table so
            checkbox edits update the same DataFrame used by the planner widget.
        """
        self.beginResetModel()
        self._source_dataframe = dataframe if dataframe is not None else pd.DataFrame()
        self._physical_columns = []
        self._logical_columns = []
        self._column_mapping = mapping_from_table(self._source_dataframe)

        if self._source_dataframe.empty:
            self._display_dataframe = pd.DataFrame()
        else:
            for logical in self._display_logicals:
                required = logical not in HIDDEN_VISIBILITY_LOGICAL_COLUMNS
                physical = resolve_column(
                    self._source_dataframe,
                    logical,
                    required=required,
                    column_mapping=self._column_mapping,
                )
                if physical is None:
                    continue
                self._physical_columns.append(physical)
                self._logical_columns.append(logical)
            self._display_dataframe = self._source_dataframe.loc[:, self._physical_columns]

        self._values = self._display_dataframe.to_numpy(dtype=object, copy=False)
        self._display_cache.clear()
        self.endResetModel()

    def clear(self) -> None:
        """Clear all displayed visibility rows."""
        self.set_dataframe(pd.DataFrame())

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._display_dataframe)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._physical_columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: A003
        if not index.isValid():
            return None

        row = index.row()
        column = index.column()
        if row < 0 or column < 0 or row >= self.rowCount() or column >= self.columnCount():
            return None

        logical = self._logical_columns[column]
        physical = self._physical_columns[column]
        try:
            value = self._values[row, column]
        except Exception:
            value = self._source_dataframe.iloc[row][physical]

        if logical == "_checked":
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if bool(value) else Qt.CheckState.Unchecked
            if role == Qt.ItemDataRole.DisplayRole:
                return ""
            return None

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if logical in {"ra", "dec", "elev", "solar_phase_angle"}:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.UserRole:
            return value

        if role != Qt.ItemDataRole.DisplayRole:
            return None

        cache_key = (row, column)
        cached = self._display_cache.get(cache_key)
        if cached is not None:
            self._display_cache.move_to_end(cache_key)
            return cached

        rendered = self._render_value(value, logical)
        self._display_cache[cache_key] = rendered
        if len(self._display_cache) > self._MAX_CACHE_ENTRIES:
            self._display_cache.popitem(last=False)
        return rendered

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        """Set the checkbox state for the selected visibility row."""
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole:
            return False
        column = index.column()
        if not (0 <= column < len(self._logical_columns)) or self._logical_columns[column] != "_checked":
            return False

        row = index.row()
        physical = self._physical_columns[column]
        checked = value == Qt.CheckState.Checked
        self._source_dataframe.iat[row, self._source_dataframe.columns.get_loc(physical)] = checked
        try:
            self._values[row, column] = checked
        except Exception:
            pass
        self._display_cache.pop((row, column), None)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.user_check_state_changed.emit(row, checked)
        return True

    def flags(self, index: QModelIndex):  # noqa: D401
        """Return selectable table flags and checkability for the first column."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if self._logical_columns[index.column()] == "_checked":
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._logical_columns):
                return get_display_name(self._logical_columns[section], self._column_mapping)
            return None
        return str(section + 1)


    def column_mapping(self) -> dict:
        """Return the effective visibility column mapping used by the model."""
        return self._column_mapping

    def logical_column(self, column: int) -> str | None:
        """Return the logical column name for a model column.

        Parameters
        ----------
        column : int
            Model column index.

        Returns
        -------
        str or None
            Logical column name, or `None` when the index is invalid.
        """
        if 0 <= column < len(self._logical_columns):
            return self._logical_columns[column]
        return None

    def column_for_logical(self, logical_name: str) -> int | None:
        """Return the model column index for a logical column.

        Parameters
        ----------
        logical_name : str
            Logical planner column name.

        Returns
        -------
        int or None
            Model column index, or `None` when not displayed.
        """
        try:
            return self._logical_columns.index(logical_name)
        except ValueError:
            return None


    def refresh_checked_rows(self, rows: Sequence[int]) -> None:
        """Emit targeted checkbox repaint updates for visible row positions.

        Parameters
        ----------
        rows : sequence of int
            Row positions in the displayed DataFrame whose ``_checked`` value
            may have changed through controller-level batch synchronization.

        Notes
        -----
        This method is a programmatic repaint path.  It must not emit
        ``user_check_state_changed``; otherwise generated-plan commits and batch
        synchronization re-enter manual selection handling.
        """
        check_column = self.column_for_logical("_checked")
        if check_column is None or not rows:
            return
        valid_rows = sorted({int(row) for row in rows if 0 <= int(row) < self.rowCount()})
        if not valid_rows:
            return

        physical = self._physical_columns[check_column]
        try:
            physical_index = self._source_dataframe.columns.get_loc(physical)
        except Exception:
            physical_index = None

        for row in valid_rows:
            try:
                if physical_index is not None:
                    source_value = self._source_dataframe.iat[row, physical_index]
                else:
                    source_value = self._source_dataframe.iloc[row][physical]
                self._values[row, check_column] = source_value
            except Exception:
                pass
            self._display_cache.pop((row, check_column), None)

        for first, last in self._iter_consecutive_ranges(valid_rows):
            top_left = self.index(first, check_column)
            bottom_right = self.index(last, check_column)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.CheckStateRole])

    @staticmethod
    def _iter_consecutive_ranges(rows: Sequence[int]) -> list[tuple[int, int]]:
        """Group sorted row positions into consecutive inclusive ranges."""
        if not rows:
            return []
        ranges: list[tuple[int, int]] = []
        start = previous = int(rows[0])
        for row in rows[1:]:
            row = int(row)
            if row == previous + 1:
                previous = row
                continue
            ranges.append((start, previous))
            start = previous = row
        ranges.append((start, previous))
        return ranges

    def dataframe(self) -> pd.DataFrame:
        """Return the underlying displayed DataFrame reference."""
        return self._source_dataframe

    def row_as_plan_record(self, row: int) -> dict[str, object]:
        """Return a visibility row converted to observation-plan fields.

        Parameters
        ----------
        row : int
            Source row index.

        Returns
        -------
        dict of str to object
            Mapping with ``satellite``, ``date_ut``, ``ra``, ``dec``,
            ``elev`` and optional ``solar_phase_angle`` values.
        """
        if row < 0 or row >= len(self._source_dataframe):
            raise IndexError(f"Visibility row out of range: {row}")
        source_row = self._source_dataframe.iloc[row]
        solar_phase_col = resolve_column(
            source_row,
            "solar_phase_angle",
            required=False,
            column_mapping=self._column_mapping,
        )
        record = {
            "satellite": source_row[resolve_column(source_row, "satellite", column_mapping=self._column_mapping)],
            "date_ut": source_row[resolve_column(source_row, "date_ut", column_mapping=self._column_mapping)],
            "ra": source_row[resolve_column(source_row, "ra", column_mapping=self._column_mapping)],
            "dec": source_row[resolve_column(source_row, "dec", column_mapping=self._column_mapping)],
            "elev": source_row[resolve_column(source_row, "elev", column_mapping=self._column_mapping)],
            "solar_phase_angle": source_row[solar_phase_col] if solar_phase_col is not None else "",
        }
        for identity_column in ("global_index", "base_index", "local_index"):
            if identity_column in source_row.index:
                record[identity_column] = source_row[identity_column]
        return record

    @staticmethod
    def _render_value(value: object, logical: str) -> str:
        """Render a visibility-table value for display."""
        if pd.isna(value):
            return ""
        if logical in {"elev", "solar_phase_angle"}:
            try:
                return f"{float(value):.2f}"
            except Exception:
                return str(value)
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)
