"""Selector-compatible plot preparation for Observation Planner visibility data.

The module contains no Qt or pyqtgraph objects.  It prepares compact numerical
payloads that can be produced in a worker thread and later committed by the GUI
thread without changing selector row identity.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .schema import resolve_column


@dataclass(frozen=True, slots=True)
class SelectorPlotPointIdentity:
    """Row identity carried by each plotted selector point.

    Attributes
    ----------
    global_index : int
        Row index in the master visibility table.
    base_index : int
        Row index in the current base table after optional target filtering.
    local_index : int
        Row index in the current visible view after satellite filtering.
    """

    global_index: int
    base_index: int
    local_index: int


@dataclass(frozen=True, slots=True)
class SelectorPlotGroup:
    """Compact plot arrays for one satellite in stable input order."""

    satellite: str
    x_values: np.ndarray
    y_values: np.ndarray
    global_indices: np.ndarray
    base_indices: np.ndarray
    local_indices: np.ndarray

    @property
    def point_count(self) -> int:
        """Return the number of finite plotted points in the group."""

        return int(self.x_values.size)


@dataclass(frozen=True, slots=True)
class SelectorPlotPayload:
    """Thread-safe plain-data payload consumed by the planner plot widget."""

    groups: tuple[SelectorPlotGroup, ...]
    identity_row_maps: dict[str, dict[str, int]]
    x_values: np.ndarray
    y_values: np.ndarray
    local_rows: np.ndarray
    x_min: float | None
    x_max: float | None
    y_min: float | None
    y_max: float | None

    @property
    def point_count(self) -> int:
        """Return the total number of finite points across all groups."""

        return int(self.x_values.size)

    @property
    def satellite_count(self) -> int:
        """Return the number of satellite groups, including empty groups."""

        return len(self.groups)


CancelCallback = Callable[[], bool]


def prepare_selector_plot_payload(
    data_view: pd.DataFrame,
    *,
    cancel_callback: CancelCallback | None = None,
) -> SelectorPlotPayload:
    """Prepare compact selector-compatible plot arrays.

    Parameters
    ----------
    data_view : pandas.DataFrame
        Current visible planner table.  Must contain ``date_ts``, elevation,
        and selector row-identity helper columns.
    cancel_callback : callable, optional
        Cooperative cancellation callback.  When it returns ``True``, an
        :class:`InterruptedError` is raised at a safe preparation checkpoint.

    Returns
    -------
    SelectorPlotPayload
        Compact grouped arrays plus interaction caches.  No Qt or pyqtgraph
        objects are created.

    Raises
    ------
    InterruptedError
        If cooperative cancellation is requested.
    ValueError
        If timestamps are invalid/mis-scaled or row identities are invalid.
    KeyError
        If required plot columns are missing.
    """

    _raise_if_canceled(cancel_callback)
    if data_view is None or data_view.empty:
        empty_float = _readonly(np.asarray([], dtype="float64"))
        empty_int = _readonly(np.asarray([], dtype="int64"))
        return SelectorPlotPayload(
            groups=(),
            identity_row_maps={},
            x_values=empty_float,
            y_values=empty_float,
            local_rows=empty_int,
            x_min=None,
            x_max=None,
            y_min=None,
            y_max=None,
        )

    satellite_col = resolve_column(data_view, "satellite")
    date_ts_col = resolve_column(data_view, "date_ts")
    elev_col = resolve_column(data_view, "elev")
    for identity_column in ("global_index", "base_index", "local_index"):
        if identity_column not in data_view.columns:
            raise KeyError(f"Required selector identity column is missing: {identity_column}")

    satellite_values = data_view[satellite_col].astype(str).to_numpy(dtype=object, copy=False)
    x_values = pd.to_numeric(data_view[date_ts_col], errors="coerce").to_numpy(dtype="float64", copy=False)
    y_values = pd.to_numeric(data_view[elev_col], errors="coerce").to_numpy(dtype="float64", copy=False)
    identity_values = {
        name: pd.to_numeric(data_view[name], errors="coerce").to_numpy(dtype="float64", copy=False)
        for name in ("global_index", "base_index", "local_index")
    }

    finite_mask = np.isfinite(x_values) & np.isfinite(y_values)
    finite_positions = np.flatnonzero(finite_mask)
    if finite_positions.size:
        minimum_timestamp = float(np.min(x_values[finite_positions]))
        if minimum_timestamp < 1.0e9:
            raise ValueError(
                "Observation Planner plot received a mis-scaled timestamp: "
                f"date_ts={minimum_timestamp}. Expected modern epoch seconds."
            )
        for name, values in identity_values.items():
            if not np.isfinite(values[finite_positions]).all():
                raise ValueError(f"Observation Planner plot received an invalid {name} value.")

    _raise_if_canceled(cancel_callback)

    codes, unique_satellites = pd.factorize(satellite_values, sort=False)
    grouped_positions: dict[int, np.ndarray] = {}
    if finite_positions.size:
        valid_codes = codes[finite_positions]
        stable_order = np.argsort(valid_codes, kind="stable")
        ordered_positions = finite_positions[stable_order]
        ordered_codes = valid_codes[stable_order]
        split_points = np.flatnonzero(np.diff(ordered_codes)) + 1
        for positions in np.split(ordered_positions, split_points):
            if positions.size:
                grouped_positions[int(codes[int(positions[0])])] = positions

    groups: list[SelectorPlotGroup] = []
    for code, satellite in enumerate(unique_satellites):
        _raise_if_canceled(cancel_callback)
        positions = grouped_positions.get(code, np.asarray([], dtype="int64"))
        groups.append(
            SelectorPlotGroup(
                satellite=str(satellite),
                x_values=_readonly(np.asarray(x_values[positions], dtype="float64")),
                y_values=_readonly(np.asarray(y_values[positions], dtype="float64")),
                global_indices=_readonly(np.asarray(identity_values["global_index"][positions], dtype="int64")),
                base_indices=_readonly(np.asarray(identity_values["base_index"][positions], dtype="int64")),
                local_indices=_readonly(np.asarray(identity_values["local_index"][positions], dtype="int64")),
            )
        )

    identity_row_maps: dict[str, dict[str, int]] = {}
    for name, values in identity_values.items():
        mapping: dict[str, int] = {}
        for row_number, value in enumerate(values):
            if not np.isfinite(value):
                continue
            mapping.setdefault(str(int(value)), int(row_number))
        identity_row_maps[name] = mapping

    plot_x = _readonly(np.asarray(x_values[finite_positions], dtype="float64"))
    plot_y = _readonly(np.asarray(y_values[finite_positions], dtype="float64"))
    plot_local = _readonly(np.asarray(identity_values["local_index"][finite_positions], dtype="int64"))
    _raise_if_canceled(cancel_callback)

    return SelectorPlotPayload(
        groups=tuple(groups),
        identity_row_maps=identity_row_maps,
        x_values=plot_x,
        y_values=plot_y,
        local_rows=plot_local,
        x_min=float(np.min(plot_x)) if plot_x.size else None,
        x_max=float(np.max(plot_x)) if plot_x.size else None,
        y_min=float(np.min(plot_y)) if plot_y.size else None,
        y_max=float(np.max(plot_y)) if plot_y.size else None,
    )


def build_selector_plot_spots(data_view: pd.DataFrame, satellite_colors: dict[str, Any]) -> dict[str, tuple[list[dict], Any]]:
    """Build the legacy selector spot dictionaries grouped by satellite.

    This compatibility adapter now uses the compact vectorized payload builder,
    avoiding repeated full-table filtering and ``DataFrame.iterrows()`` while
    preserving the public dictionary contract.
    """

    payload = prepare_selector_plot_payload(data_view)
    prepared: dict[str, tuple[list[dict], Any]] = {}
    for group in payload.groups:
        color = satellite_colors.get(group.satellite)
        spots = [
            {
                "pos": (float(timestamp), float(elevation)),
                "data": {
                    "global": int(global_index),
                    "base": int(base_index),
                    "local": int(local_index),
                },
                "brush": color,
                "size": 5,
                "symbol": "o",
                "pen": None,
            }
            for timestamp, elevation, global_index, base_index, local_index in zip(
                group.x_values,
                group.y_values,
                group.global_indices,
                group.base_indices,
                group.local_indices,
                strict=True,
            )
        ]
        prepared[group.satellite] = (spots, color)
    return prepared


def selector_plot_range(data_view: pd.DataFrame) -> tuple[float, float, float, float] | None:
    """Return finite x/y bounds for selector visibility data."""

    if data_view is None or data_view.empty:
        return None

    date_ts_col = resolve_column(data_view, "date_ts")
    elev_col = resolve_column(data_view, "elev")
    x_values = pd.to_numeric(data_view[date_ts_col], errors="coerce")
    y_values = pd.to_numeric(data_view[elev_col], errors="coerce")
    valid = x_values.notna() & y_values.notna() & np.isfinite(x_values) & np.isfinite(y_values)
    if not valid.any():
        return None

    x_min = float(x_values[valid].min())
    x_max = float(x_values[valid].max())
    y_min = float(y_values[valid].min())
    y_max = float(y_values[valid].max())
    if x_min < 1.0e9:
        raise ValueError(
            "Observation Planner plot range received mis-scaled timestamps: "
            f"x_min={x_min}, x_max={x_max}."
        )
    return x_min, x_max, y_min, y_max


def _readonly(array: np.ndarray) -> np.ndarray:
    """Return ``array`` with mutation disabled by convention and NumPy flags."""

    array.setflags(write=False)
    return array


def _raise_if_canceled(cancel_callback: CancelCallback | None) -> None:
    """Raise ``InterruptedError`` at cooperative preparation checkpoints."""

    if cancel_callback is not None and cancel_callback():
        raise InterruptedError("Visibility plot preparation canceled.")


__all__ = [
    "SelectorPlotGroup",
    "SelectorPlotPayload",
    "SelectorPlotPointIdentity",
    "build_selector_plot_spots",
    "prepare_selector_plot_payload",
    "selector_plot_range",
]
