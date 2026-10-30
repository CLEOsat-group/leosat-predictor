"""Convert Celestrak OMM CSV data into three-line TLE text.

Celestrak ran out of 5-digit catalog numbers on 2026-07-11, and its
``FORMAT=tle`` output silently omits every object numbered 100000 or above.
The OMM CSV format carries all objects, so the app downloads CSV and converts
each row into a standard TLE here.  Catalog numbers 100000-339999 use the
Alpha-5 scheme (``A0000``-``Z9999``, skipping I and O), which the propagators
(pyorbital, ephem) accept; larger numbers cannot be represented and are skipped.

Keeping the cache in TLE form means everything downstream -- propagation, the
GUI TLE fields, planner "Copy TLE", and TLE sidecar files -- is unchanged.
"""

from __future__ import annotations

import csv
import io
import logging
import math
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

_ALPHA5_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_MAX_ALPHA5 = 339999
_TLE_FORMATS = {"tle", "3le", "2le"}


def is_omm_csv(text: str) -> bool:
    """Return whether downloaded text is OMM CSV rather than TLE text."""
    first_line = text.lstrip("﻿ \t\r\n").split("\n", 1)[0]
    return first_line.upper().startswith("OBJECT_NAME,")


def to_omm_csv_url(url: str) -> str:
    """Rewrite a Celestrak ``FORMAT=tle``/``3le``/``2le`` URL to ``FORMAT=csv``.

    Saved user preferences may still hold TLE-format URLs; non-Celestrak URLs
    and other formats are returned unchanged.
    """
    parts = urlsplit(url)
    if not parts.hostname or not parts.hostname.lower().endswith("celestrak.org"):
        return url
    query = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key.upper() == "FORMAT" and value.lower() in _TLE_FORMATS for key, value in query):
        return url
    query = [(key, "csv" if key.upper() == "FORMAT" else value) for key, value in query]
    return urlunsplit(parts._replace(query=urlencode(query, safe=",")))


def omm_csv_to_tle_text(text: str) -> str:
    """Convert OMM CSV text into three-line TLE text.

    Rows that cannot be converted (missing fields, or catalog numbers above the
    Alpha-5 range) are skipped and counted in a log warning.
    """
    blocks: list[str] = []
    skipped_range = 0
    skipped_invalid = 0
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        try:
            catalog = int(float(row["NORAD_CAT_ID"]))
            satnum = format_catalog_number(catalog)
            if satnum is None:
                skipped_range += 1
                continue
            line1, line2 = _row_to_tle_lines(row, satnum)
        except (KeyError, TypeError, ValueError):
            skipped_invalid += 1
            continue
        name = (row.get("OBJECT_NAME") or "").strip() or f"NORAD {catalog}"
        blocks.append(f"{name}\n{line1}\n{line2}\n")
    if skipped_range:
        logger.warning(
            "Skipped %d OMM object(s) with catalog numbers above %d (not representable as TLE).",
            skipped_range,
            _MAX_ALPHA5,
        )
    if skipped_invalid:
        logger.warning("Skipped %d OMM row(s) with missing or invalid fields.", skipped_invalid)
    return "".join(blocks)


def format_catalog_number(catalog: int) -> str | None:
    """Return the 5-character TLE catalog field, using Alpha-5 above 99999."""
    if 0 <= catalog <= 99999:
        return f"{catalog:05d}"
    if catalog <= _MAX_ALPHA5:
        return f"{_ALPHA5_LETTERS[catalog // 10000 - 10]}{catalog % 10000:04d}"
    return None


def tle_checksum(line: str) -> int:
    """Return the modulo-10 TLE checksum of the first 68 characters."""
    return sum(int(char) if char.isdigit() else int(char == "-") for char in line[:68]) % 10


def _row_to_tle_lines(row: dict[str, str], satnum: str) -> tuple[str, str]:
    """Format one OMM CSV row as TLE lines 1 and 2."""
    classification = (row.get("CLASSIFICATION_TYPE") or "U").strip()[:1] or "U"
    ephemeris_type = int(float(row.get("EPHEMERIS_TYPE") or 0)) % 10
    element_set = int(float(row.get("ELEMENT_SET_NO") or 0)) % 10000
    revolutions = int(float(row.get("REV_AT_EPOCH") or 0)) % 100000

    line1 = (
        f"1 {satnum}{classification} {_international_designator(row.get('OBJECT_ID') or ''):<8} "
        f"{_tle_epoch(row['EPOCH'])} {_tle_first_derivative(float(row['MEAN_MOTION_DOT']))} "
        f"{_tle_exponent(float(row.get('MEAN_MOTION_DDOT') or 0))} {_tle_exponent(float(row['BSTAR']))} "
        f"{ephemeris_type} {element_set:>4}"
    )
    eccentricity = f"{float(row['ECCENTRICITY']):.7f}"[2:]
    line2 = (
        f"2 {satnum} {float(row['INCLINATION']):8.4f} {float(row['RA_OF_ASC_NODE']):8.4f} "
        f"{eccentricity} {float(row['ARG_OF_PERICENTER']):8.4f} {float(row['MEAN_ANOMALY']):8.4f} "
        f"{float(row['MEAN_MOTION']):11.8f}{revolutions:5d}"
    )
    if len(line1) != 68 or len(line2) != 68:
        raise ValueError("OMM values do not fit the TLE field widths")
    return f"{line1}{tle_checksum(line1)}", f"{line2}{tle_checksum(line2)}"


def _international_designator(object_id: str) -> str:
    """Convert ``2026-123A`` to the TLE form ``26123A``."""
    object_id = object_id.strip()
    if len(object_id) >= 9 and object_id[4] == "-":
        return f"{object_id[2:4]}{object_id[5:8]}{object_id[8:11]}"
    return ""


def _tle_epoch(epoch: str) -> str:
    """Convert an ISO 8601 epoch to the TLE ``YYDDD.DDDDDDDD`` form."""
    moment = datetime.fromisoformat(epoch.strip().replace("Z", ""))
    seconds = moment.hour * 3600 + moment.minute * 60 + moment.second + moment.microsecond / 1e6
    day_of_year = moment.timetuple().tm_yday + seconds / 86400.0
    return f"{moment.year % 100:02d}{day_of_year:012.8f}"


def _tle_first_derivative(value: float) -> str:
    """Format the first mean-motion derivative as `` .00012345``."""
    sign = "-" if value < 0 else " "
    # "0.00012345"[1:] drops the leading zero; |value| >= 1 cannot fit and is
    # rejected by the line-length check.
    return sign + f"{abs(value):.8f}"[1:]


def _tle_exponent(value: float) -> str:
    """Format a value in the TLE assumed-decimal exponent form `` 12345-3``."""
    if value == 0:
        return " 00000+0"
    sign = "-" if value < 0 else " "
    exponent = math.floor(math.log10(abs(value))) + 1
    mantissa = round(abs(value) / 10**exponent * 1e5)
    if mantissa >= 100000:
        mantissa //= 10
        exponent += 1
    if abs(exponent) > 9:
        return " 00000-0"
    return f"{sign}{mantissa:05d}{'-' if exponent < 0 else '+'}{abs(exponent)}"
