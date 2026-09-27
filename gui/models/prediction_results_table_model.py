"""Qt table model for scalable prediction-result display."""

from __future__ import annotations

from collections import OrderedDict
from typing import Sequence

import pandas as pd
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


class PredictionResultsTableModel(QAbstractTableModel):
    """Model-backed table view over a pandas DataFrame.

    The model stores the full displayed DataFrame but only materializes cell text
    on demand, which scales much better than populating a ``QTableWidget`` with
    one ``QTableWidgetItem`` per cell.
    """

    _MAX_CACHE_ENTRIES = 50000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dataframe = pd.DataFrame()
        self._display_columns: list[str] = []
        self._values = self._dataframe.to_numpy(dtype=object, copy=False)
        self._display_cache: OrderedDict[tuple[int, int], str] = OrderedDict()

    def set_dataframe(self, dataframe: pd.DataFrame | None, display_columns: Sequence[str] | None = None) -> None:
        """Reset the model to use the provided DataFrame and display columns."""
        self.beginResetModel()
        if dataframe is None or dataframe.empty:
            self._dataframe = pd.DataFrame()
            self._display_columns = []
        else:
            columns = list(display_columns) if display_columns is not None else list(dataframe.columns)
            self._dataframe = dataframe.loc[:, columns].reset_index(drop=True)
            self._display_columns = columns
        self._values = self._dataframe.to_numpy(dtype=object, copy=False)
        self._display_cache.clear()
        self.endResetModel()

    def clear(self) -> None:
        """Clear all displayed data from the model."""
        self.set_dataframe(pd.DataFrame())

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._dataframe)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._display_columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: A003
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        if role == Qt.ItemDataRole.TextAlignmentRole:
            value = self._values[row, col]
            if pd.api.types.is_number(value) and not isinstance(value, bool):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        if role == Qt.ItemDataRole.UserRole:
            return self._values[row, col]

        if role != Qt.ItemDataRole.DisplayRole:
            return None

        cache_key = (row, col)
        cached = self._display_cache.get(cache_key)
        if cached is not None:
            # Refresh LRU position.
            self._display_cache.move_to_end(cache_key)
            return cached

        value = self._values[row, col]
        rendered = self._render_value(value)
        self._display_cache[cache_key] = rendered
        if len(self._display_cache) > self._MAX_CACHE_ENTRIES:
            self._display_cache.popitem(last=False)
        return rendered

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None

        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._display_columns):
                return self._display_columns[section]
            return None

        return str(section + 1)

    def flags(self, index: QModelIndex):  # noqa: D401
        """Return standard selectable, enabled table-item flags."""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:  # noqa: N802
        """Sort the displayed DataFrame in-place by the selected column."""
        if not (0 <= column < len(self._display_columns)) or self._dataframe.empty:
            return

        column_name = self._display_columns[column]
        ascending = order == Qt.SortOrder.AscendingOrder

        self.layoutAboutToBeChanged.emit()
        try:
            sorted_df = self._sorted_dataframe(self._dataframe, column_name, ascending)
            self._dataframe = sorted_df.reset_index(drop=True)
            self._values = self._dataframe.to_numpy(dtype=object, copy=False)
            self._display_cache.clear()
        finally:
            self.layoutChanged.emit()

    def get_value(self, row: int, column: int):
        """Return the raw cell value for copy/export helpers."""
        if row < 0 or column < 0:
            return None
        if row >= self.rowCount() or column >= self.columnCount():
            return None
        return self._values[row, column]

    @staticmethod
    def _render_value(value) -> str:
        """Render a raw cell value for display without excessive formatting work."""
        if value is None:
            return ""
        if isinstance(value, float):
            return format(value, ".10g")
        if isinstance(value, pd.Timestamp):
            return value.isoformat(sep=" ")
        return str(value)

    @staticmethod
    def _sorted_dataframe(dataframe: pd.DataFrame, column_name: str, ascending: bool) -> pd.DataFrame:
        """Return a sorted copy of the provided DataFrame.

        Sorting tries to preserve numeric and datetime semantics when possible,
        while falling back to case-insensitive string sorting for mixed columns.
        """
        series = dataframe[column_name]

        # Preserve native numeric/datetime sorting when already typed correctly.
        if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
            return dataframe.sort_values(by=column_name, ascending=ascending, kind="mergesort")

        # Try datetime sorting for common time/date columns stored as strings.
        lower_name = column_name.lower()
        if any(token in lower_name for token in ("time", "date", "obs_")):
            parsed = pd.to_datetime(series, errors="coerce")
            if parsed.notna().any():
                return dataframe.assign(__sort_key=parsed).sort_values(
                    by="__sort_key", ascending=ascending, kind="mergesort"
                ).drop(columns="__sort_key")

        # Try numeric sorting for columns stored as strings.
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().any():
            return dataframe.assign(__sort_key=numeric).sort_values(
                by="__sort_key", ascending=ascending, kind="mergesort"
            ).drop(columns="__sort_key")

        normalized = series.astype(str).str.casefold()
        return dataframe.assign(__sort_key=normalized).sort_values(
            by="__sort_key", ascending=ascending, kind="mergesort"
        ).drop(columns="__sort_key")

    @property
    def dataframe(self) -> pd.DataFrame:
        """Return the currently displayed DataFrame."""
        return self._dataframe
