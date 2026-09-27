"""GUI column-mapping editor for Observation Planner preferences.

The widget is deliberately GUI-local and depends only on the shared
``src.observation_planner`` column-mapping contract.  It mirrors the donor
settings surface without importing GUI-v1 dialogs: logical names are visible but
not editable, display names and aliases are editable, and width is edited with a
bounded spin box.  Hidden helper columns are preserved in the stored mapping but
are not displayed as editable rows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem, QWidget

from src.observation_planner.column_mapping import is_hidden, normalize_column_mapping


COLUMN_TABLE_HEADERS = ("Logical Name", "Display Name", "Aliases", "Width")


class PlannerColumnMappingTable(QTableWidget):
    """Editable GUI table for donor-compatible planner column mappings.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guiPlannerColumnMappingTable")
        self.setColumnCount(len(COLUMN_TABLE_HEADERS))
        self.setHorizontalHeaderLabels(COLUMN_TABLE_HEADERS)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.setMinimumHeight(320)
        self.setAlternatingRowColors(True)
        self.setShowGrid(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._base_column_mapping: dict[str, dict[str, Any]] = normalize_column_mapping(None)

    def populate(self, column_mapping: Mapping[str, Any] | None) -> None:
        """Populate the table from an integrated or donor-style mapping.

        Parameters
        ----------
        column_mapping : mapping, optional
            Existing column mapping.  Hidden helper columns are retained in the
            base mapping and are not presented as editable table rows.
        """
        mapping = normalize_column_mapping(column_mapping)
        self._base_column_mapping = mapping
        visible_items = [(logical, cfg) for logical, cfg in mapping.items() if not is_hidden(logical, mapping)]

        self.clearContents()
        self.setRowCount(len(visible_items))
        for row, (logical, cfg) in enumerate(visible_items):
            logical_item = QTableWidgetItem(logical)
            logical_item.setFlags(logical_item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable)
            self.setItem(row, 0, logical_item)

            display_item = QTableWidgetItem(str(cfg.get("display", logical)))
            self.setItem(row, 1, display_item)

            aliases_text = ", ".join(str(alias) for alias in cfg.get("aliases", ()))
            aliases_item = QTableWidgetItem(aliases_text)
            self.setItem(row, 2, aliases_item)

            width_spin = QSpinBox(self)
            width_spin.setObjectName(f"guiPlannerColumnWidth_{logical}")
            width_spin.setRange(20, 500)
            try:
                width_spin.setValue(int(cfg.get("width", 100)))
            except (TypeError, ValueError):
                width_spin.setValue(100)
            self.setCellWidget(row, 3, width_spin)

    def collect(self) -> dict[str, dict[str, Any]]:
        """Return the edited donor-compatible column mapping.

        Returns
        -------
        dict
            Normalized logical-column mapping.  Hidden helper rows and future
            unknown mapping keys are preserved from the base mapping.
        """
        mapping = normalize_column_mapping(self._base_column_mapping)
        for row in range(self.rowCount()):
            logical_item = self.item(row, 0)
            if logical_item is None:
                continue
            logical = logical_item.text().strip()
            if not logical:
                continue

            cfg = dict(mapping.get(logical, {"aliases": [logical], "display": logical, "width": 100}))
            display_item = self.item(row, 1)
            aliases_item = self.item(row, 2)
            width_widget = self.cellWidget(row, 3)

            display = display_item.text().strip() if display_item is not None else logical
            aliases_text = aliases_item.text().strip() if aliases_item is not None else ""
            aliases = [alias.strip() for alias in aliases_text.split(",") if alias.strip()]
            width = int(width_widget.value()) if hasattr(width_widget, "value") else int(cfg.get("width", 100))

            cfg["display"] = display or logical
            cfg["aliases"] = aliases or [logical]
            cfg["width"] = width
            cfg["hidden"] = bool(cfg.get("hidden", False))
            mapping[logical] = cfg
        return normalize_column_mapping(mapping)


__all__ = ("PlannerColumnMappingTable",)
