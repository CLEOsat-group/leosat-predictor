"""Semantic GUI-v2 theme palettes and accessibility helpers.

The module is deliberately Qt-free.  It is the single source of truth for
application QSS generation, custom-painted widgets, table models, and
PyQtGraph adapters.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ThemePalette:
    """Immutable semantic color palette for one GUI-v2 theme."""

    name: str
    canvas: str
    surface: str
    surface_alt: str
    surface_raised: str
    surface_hover: str
    border: str
    border_strong: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    focus: str
    selected_text: str
    info: str
    success: str
    success_hover: str
    warning: str
    error: str
    error_hover: str
    info_surface: str
    success_surface: str
    warning_surface: str
    error_surface: str
    disabled_surface: str
    disabled_text: str
    plot_background: str
    plot_foreground: str
    plot_grid: str
    overlay: str
    spinner: str
    icon_color: str
    row_manual_background: str
    row_generated_background: str
    row_past_background: str
    row_hover_background: str
    row_hover_border: str
    row_selection_background: str
    row_selection_border: str
    row_manual_foreground: str
    row_generated_foreground: str
    row_past_foreground: str
    series_input: str
    series_reduced: str
    series_selected: str
    series_repair: str
    series_warning: str
    series_alt: str

    def qss_tokens(self) -> dict[str, str]:
        """Return string-template values used by ``dashboard.qss.in``."""

        return {key: str(value) for key, value in asdict(self).items() if key != "name"}

    def series_color(self, role: str) -> str:
        """Return a plot-series color for a semantic role."""

        normalized = str(role or "input").strip().lower().replace("-", "_")
        mapping = {
            "input": self.series_input,
            "reduced": self.series_reduced,
            "selected": self.series_selected,
            "generated": self.series_selected,
            "manual": self.series_alt,
            "repair": self.series_repair,
            "repair_added": self.series_repair,
            "warning": self.series_warning,
            "violation": self.error,
            "spacing_minimum": self.series_warning,
            "alternate": self.series_alt,
        }
        return mapping.get(normalized, self.accent)


DARK_PALETTE = ThemePalette(
    name="dark",
    canvas="#111820",
    surface="#17212B",
    surface_alt="#1D2935",
    surface_raised="#243240",
    surface_hover="#2B3A49",
    border="#344658",
    border_strong="#466078",
    text_primary="#E5ECF3",
    text_secondary="#ABB8C6",
    text_muted="#8796A6",
    accent="#3473A5",
    accent_hover="#2E6896",
    focus="#68A9D7",
    selected_text="#FFFFFF",
    info="#3473A5",
    success="#2F7D5A",
    success_hover="#2A7051",
    warning="#D49A3A",
    error="#A83D49",
    error_hover="#973742",
    info_surface="#1D3347",
    success_surface="#1B382D",
    warning_surface="#3A2E19",
    error_surface="#3B2228",
    disabled_surface="#202A34",
    disabled_text="#6F7D8B",
    plot_background="#FFFFFF",
    plot_foreground="#2C3947",
    plot_grid="#D2DCE6",
    overlay="rgba(11, 17, 24, 178)",
    spinner="#68A9D7",
    icon_color="#FFFFFF",
    row_manual_background="#315E7A",
    row_generated_background="#2C624B",
    row_past_background="#7A434D",
    row_hover_background="#68A9D7",
    row_hover_border="#D5ECFA",
    row_selection_background="#68A9D7",
    row_selection_border="#8FC7E9",
    row_manual_foreground="#E5ECF3",
    row_generated_foreground="#E5ECF3",
    row_past_foreground="#F4D8DC",
    series_input="#6F7E8D",
    series_reduced="#2E75B6",
    series_selected="#257453",
    series_repair="#7E57A6",
    series_warning="#A76612",
    series_alt="#6D5AA8",
)

LIGHT_PALETTE = ThemePalette(
    name="light",
    canvas="#F1F4F7",
    surface="#FFFFFF",
    surface_alt="#F7F9FB",
    surface_raised="#E9EEF3",
    surface_hover="#E3EBF2",
    border="#CBD5DF",
    border_strong="#AAB8C6",
    text_primary="#24303D",
    text_secondary="#5A6877",
    text_muted="#667585",
    accent="#2E6F9F",
    accent_hover="#255D86",
    focus="#2E7FB8",
    selected_text="#FFFFFF",
    info="#2E6F9F",
    success="#257453",
    success_hover="#1E6146",
    warning="#8A5A0A",
    error="#A8323E",
    error_hover="#8F2A35",
    info_surface="#E4F0F8",
    success_surface="#E5F3EC",
    warning_surface="#FFF2D8",
    error_surface="#FBE7E9",
    disabled_surface="#EDF1F4",
    disabled_text="#7B8794",
    plot_background="#FFFFFF",
    plot_foreground="#2C3947",
    plot_grid="#D2DCE6",
    overlay="rgba(36, 48, 61, 76)",
    spinner="#2E7FB8",
    icon_color="#000000",
    row_manual_background="#E4F0FA",
    row_generated_background="#E4F3EB",
    row_past_background="#F8E5E7",
    row_hover_background="#2E7FB8",
    row_hover_border="#1E6594",
    row_selection_background="#2E7FB8",
    row_selection_border="#174F76",
    row_manual_foreground="#24303D",
    row_generated_foreground="#24303D",
    row_past_foreground="#6E2830",
    series_input="#6F7E8D",
    series_reduced="#2E75B6",
    series_selected="#257453",
    series_repair="#7E57A6",
    series_warning="#A76612",
    series_alt="#6D5AA8",
)

PALETTES: Mapping[str, ThemePalette] = MappingProxyType(
    {"dark": DARK_PALETTE, "light": LIGHT_PALETTE}
)


def normalize_theme_name(theme: str | None) -> str:
    """Normalize a persisted theme identifier to ``dark`` or ``light``."""

    return "light" if str(theme or "dark").strip().lower() == "light" else "dark"


def palette_for(theme: str | None) -> ThemePalette:
    """Return the immutable palette for ``theme``."""

    return PALETTES[normalize_theme_name(theme)]


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the WCAG relative-luminance contrast ratio for two hex colors."""

    def luminance(value: str) -> float:
        match = re.fullmatch(r"#([0-9a-fA-F]{6})", str(value).strip())
        if match is None:
            raise ValueError(f"Expected #RRGGBB color, received {value!r}.")
        rgb = [int(match.group(1)[index : index + 2], 16) / 255.0 for index in (0, 2, 4)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in rgb]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first = luminance(foreground)
    second = luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


__all__ = (
    "DARK_PALETTE",
    "LIGHT_PALETTE",
    "PALETTES",
    "ThemePalette",
    "contrast_ratio",
    "normalize_theme_name",
    "palette_for",
)
