"""TLE file parsing and lookup helpers for planner clipboard workflows.

The helpers in this module deliberately do not fetch TLEs or infer missing TLE
lines.  They parse a user-provided or predictor-copied TLE text file and expose
stable lookup utilities for the Observation Planner.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Iterable


@dataclass(frozen=True)
class TleEntry:
    """One valid satellite TLE entry.

    Parameters
    ----------
    name : str
        Satellite name line associated with the two-line element set. Source
        spacing is preserved except for trailing newline removal.
    line1 : str
        TLE line 1, preserved except for trailing newline removal.
    line2 : str
        TLE line 2, preserved except for trailing newline removal.
    catalog_number : str, optional
        Parsed catalog identifier from line 1/2 when available.
    """

    name: str
    line1: str
    line2: str
    catalog_number: str = ""

    @property
    def clipboard_text(self) -> str:
        """Return the complete three-line TLE block.

        The Observation Planner ``Copy TLE`` action should place the satellite
        name line followed by TLE line 1 and TLE line 2 on the clipboard.  The
        helper preserves the source spacing of each parsed line except for
        trailing newline characters.
        """
        return f"{self.name}\n{self.line1}\n{self.line2}"


class TleFileIndex:
    """Lookup index for a loaded TLE text file."""

    def __init__(self, entries: Iterable[TleEntry] = (), *, source_path: str | Path | None = None):
        self.source_path = Path(source_path) if source_path else None
        self.entries = list(entries)
        self._by_name: dict[str, TleEntry] = {}
        self._by_catalog: dict[str, TleEntry] = {}
        for entry in self.entries:
            for key in _candidate_name_keys(entry.name):
                self._by_name.setdefault(key, entry)
            if entry.catalog_number:
                self._by_catalog.setdefault(entry.catalog_number, entry)

    def __len__(self) -> int:
        return len(self.entries)

    def lookup(self, satellite_name: object) -> TleEntry | None:
        """Return a matching TLE entry for a satellite display name.

        Parameters
        ----------
        satellite_name : object
            Satellite identifier from the visibility or observation table.

        Returns
        -------
        TleEntry or None
            Matching entry, or ``None`` when no loaded TLE matches.
        """
        for key in _candidate_name_keys(satellite_name):
            entry = self._by_name.get(key)
            if entry is not None:
                return entry
            catalog = _extract_catalog_candidate(key)
            if catalog:
                entry = self._by_catalog.get(catalog)
                if entry is not None:
                    return entry
        return None


def load_tle_file_index(path: str | Path) -> TleFileIndex:
    """Load and parse a standard three-line TLE text file.

    Parameters
    ----------
    path : str or pathlib.Path
        TLE text file path.

    Returns
    -------
    TleFileIndex
        Lookup index containing all valid entries.
    """
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8", errors="replace")
    return TleFileIndex(parse_tle_text(text), source_path=file_path)


def parse_tle_text(text: str) -> list[TleEntry]:
    """Parse valid three-line TLE entries from text.

    Blank lines are ignored.  Satellite name and TLE line spacing are preserved
    except for trailing newline removal.  Invalid triplets are skipped.
    """
    lines = [line.rstrip("\r\n") for line in text.splitlines() if line.strip()]
    entries: list[TleEntry] = []
    index = 0
    while index + 2 < len(lines):
        name = lines[index].rstrip("\r\n")
        line1 = lines[index + 1].rstrip("\r\n")
        line2 = lines[index + 2].rstrip("\r\n")
        if _is_valid_tle_pair(line1, line2):
            entries.append(
                TleEntry(
                    name=name,
                    line1=line1,
                    line2=line2,
                    catalog_number=_parse_catalog_number(line1, line2),
                )
            )
            index += 3
            continue
        index += 1
    return entries


def copy_tle_file_for_csv(source_tle_path: str | Path | None, csv_path: str | Path) -> Path | None:
    """Copy the complete source TLE file next to a saved precise CSV.

    Parameters
    ----------
    source_tle_path : str, pathlib.Path, or None
        Source TLE file used for the completed prediction.  ``None`` disables
        copying.
    csv_path : str or pathlib.Path
        Written precise CSV path.

    Returns
    -------
    pathlib.Path or None
        Destination path when copied, otherwise ``None``.
    """
    if not source_tle_path:
        return None
    source = Path(source_tle_path)
    if not source.is_file():
        return None
    destination = Path(csv_path).with_name(f"{Path(csv_path).stem}_tle.txt")
    shutil.copy2(source, destination)
    return destination


def _is_valid_tle_pair(line1: str, line2: str) -> bool:
    return bool(line1.startswith("1 ") and line2.startswith("2 "))


def _parse_catalog_number(line1: str, line2: str) -> str:
    for line in (line1, line2):
        parts = line.split()
        if len(parts) >= 2:
            catalog = re.sub(r"\D+$", "", parts[1])
            if catalog:
                return catalog
    return ""


def _candidate_name_keys(value: object) -> list[str]:
    raw = "" if value is None else str(value).strip()
    if not raw:
        return []
    candidates = [raw]
    if "-ID" in raw:
        candidates.append(raw.split("-ID", 1)[0])
    if " ID" in raw:
        candidates.append(raw.split(" ID", 1)[0])
    normalized: list[str] = []
    for candidate in candidates:
        key = _normalize_name(candidate)
        if key and key not in normalized:
            normalized.append(key)
    return normalized


def _normalize_name(value: str) -> str:
    return " ".join(str(value).strip().upper().split())


def _extract_catalog_candidate(key: str) -> str:
    match = re.search(r"(\d{3,})", key)
    return match.group(1) if match else ""
