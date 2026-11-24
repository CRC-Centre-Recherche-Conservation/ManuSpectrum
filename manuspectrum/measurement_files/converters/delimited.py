# SPDX-License-Identifier: AGPL-3.0-only
# Written from: plain-text column exports (tab, semicolon, comma or space separated) studied as data; no vendor format
"""Fallback reader for numeric text columns.

Tried by the registry after every content-signed reader and after the known
unread formats. Column names are `x`, `y`, `y2`, `y3`…: header text is never
read. Decoding: UTF-16 when a BOM says so, else UTF-8 (BOM allowed), else
Windows-1252. The separator is the one of tab, `;`, `,` and a run of spaces
(in that order on a tie) that gives at least two numeric fields on the most of
the first 2000 lines; a decimal comma is accepted only when the separator is
not `,`. A text is sniffed as a measurement only when two lines of its head
read as numeric rows, so JSON, HTML or prose is `UnsupportedFormat(None)`. Data
starts at the first run of 5 consecutive numeric rows (else the first numeric
run) and ends at the first non-numeric row; a numeric row after that is
`malformed`. At most `MAX_CHANNELS` rows are converted. Rows are sorted
ascending by x.
"""

import codecs
import math
import re

from .base import MAX_CHANNELS, Reading, Series, UnreadableFile

FORMAT = "delimited"
READER_VERSION = 1

MIN_RUN = 5
PROBE_LINES = 2000
_NUMBER = re.compile(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?")
_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_SEPARATORS = ("\t", ";", ",", None)


def sniff(head: bytes, truncated: bool = False) -> bool:
    """Whether the head of a file holds two numeric rows.

    `truncated` says the head stops before the end of the file: its last line
    may be cut and is not read."""
    if not head.startswith(_UTF16_BOMS) and b"\x00" in head:
        return False
    if head.startswith(_UTF16_BOMS):
        text = head.decode("utf-16", errors="ignore")
    else:
        text = head.decode("utf-8-sig", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if truncated and not head.startswith(_UTF16_BOMS):
        lines = lines[:-1]
    return any(
        sum(_is_row(_fields(ln, sep), sep) for ln in lines) >= 2 for sep in _SEPARATORS
    )


def _decode(data: bytes) -> str:
    try:
        if data.startswith(_UTF16_BOMS):
            return data.decode("utf-16")
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            return data.decode("cp1252")
    except UnicodeDecodeError:
        raise UnreadableFile("malformed") from None


def _fields(line: str, separator: str | None) -> list[str]:
    parts = [p.strip() for p in line.split(separator)]
    while parts and not parts[-1]:
        parts.pop()
    return parts


def _is_row(parts: list[str], separator: str | None) -> bool:
    """Whether the fields are at least two numbers (no float conversion)."""
    if len(parts) < 2:
        return False
    for part in parts:
        if not _NUMBER.fullmatch(part) or ("," in part and separator == ","):
            return False
    return True


def _values(parts: list[str]) -> tuple[float, ...]:
    return tuple(float(part.replace(",", ".")) for part in parts)


def _separator(lines: list[str]) -> str | None:
    best, best_count = _SEPARATORS[0], 0
    for separator in _SEPARATORS:
        count = sum(
            _is_row(_fields(line, separator), separator) for line in lines[:PROBE_LINES]
        )
        if count > best_count:
            best, best_count = separator, count
    return best


def read(data: bytes) -> Reading:
    text = _decode(data)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    separator = _separator(lines)
    numeric = [_is_row(_fields(ln, separator), separator) for ln in lines]

    start = None
    run = 0
    for index, flag in enumerate(numeric):
        run = run + 1 if flag else 0
        if run == MIN_RUN:
            start = index - MIN_RUN + 1
            break
    if start is None:
        start = next((i for i, flag in enumerate(numeric) if flag), None)
    if start is None:
        raise UnreadableFile("no_numeric_columns")

    width = len(_fields(lines[start], separator))
    rows = []
    end = start
    while end < len(lines) and numeric[end]:
        parts = _fields(lines[end], separator)
        if len(parts) != width:
            break
        rows.append(_values(parts))
        end += 1
        if len(rows) > MAX_CHANNELS:
            raise UnreadableFile("too_large")
    if any(numeric[end:]):
        raise UnreadableFile("malformed")
    if len(rows) < 2:
        raise UnreadableFile("too_few_points")
    if not all(math.isfinite(v) for row in rows for v in row):
        raise UnreadableFile("non_finite")
    rows.sort(key=lambda row: row[0])
    if any(a[0] == b[0] for a, b in zip(rows, rows[1:])):
        raise UnreadableFile("duplicate_x")
    columns = ("x", "y") + tuple(f"y{n}" for n in range(2, width))
    return Reading(
        format=FORMAT,
        reader_version=READER_VERSION,
        series=Series(columns, tuple(rows)),
        content_preset=None,
    )
