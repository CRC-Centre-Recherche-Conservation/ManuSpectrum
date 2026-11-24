# SPDX-License-Identifier: AGPL-3.0-only
# Written from: plain-text column exports (tab, semicolon, comma or space separated) studied as data; no vendor format
"""Fallback reader for numeric text columns.

Tried by the registry after every content-signed reader and after the known
unread formats. Column names are `x`, `y`, `y2`, `y3`…: header text is never
read. Decoding: UTF-16 when a BOM says so, else UTF-8 (BOM allowed), else
Windows-1252. The separator is the first of tab, `;`, `,` and a run of spaces
that gives at least two numeric fields on most of the first 50 candidate rows;
a decimal comma is accepted only when the separator is not `,`. Data starts at
the first run of 5 consecutive numeric rows (else the first numeric run) and
ends at the first non-numeric row; a numeric row after that is `malformed`.
Rows are sorted ascending by x.
"""

import codecs
import math
import re

from .base import MAX_CHANNELS, Reading, Series, UnreadableFile

FORMAT = "delimited"
READER_VERSION = 1

MIN_RUN = 5
PROBE_ROWS = 50
_NUMBER = re.compile(r"[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?")
_UTF16_BOMS = (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)
_SEPARATORS = ("\t", ";", ",", None)


def sniff(head: bytes) -> bool:
    if head.startswith(_UTF16_BOMS):
        return True
    return bool(head) and b"\x00" not in head


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


def _numeric(parts: list[str], separator: str | None) -> list[float] | None:
    """The floats of a row of at least two numeric fields, else None."""
    if len(parts) < 2:
        return None
    values = []
    for part in parts:
        if not _NUMBER.fullmatch(part):
            return None
        if "," in part:
            if separator == ",":
                return None
            part = part.replace(",", ".")
        values.append(float(part))
    return values


def _separator(lines: list[str]) -> str | None:
    probe = lines[:PROBE_ROWS]
    for separator in _SEPARATORS:
        good = sum(
            _numeric(_fields(line, separator), separator) is not None for line in probe
        )
        if probe and good * 2 > len(probe):
            return separator
    return _SEPARATORS[0]


def read(data: bytes) -> Reading:
    text = _decode(data)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    separator = _separator(lines)
    parsed = [_numeric(_fields(ln, separator), separator) for ln in lines]

    start = None
    run = 0
    for index, row in enumerate(parsed):
        run = run + 1 if row is not None else 0
        if run == MIN_RUN:
            start = index - MIN_RUN + 1
            break
    if start is None:
        start = next((i for i, row in enumerate(parsed) if row is not None), None)
    if start is None:
        raise UnreadableFile("no_numeric_columns")

    width = len(parsed[start])
    rows = []
    end = start
    while end < len(parsed) and parsed[end] is not None and len(parsed[end]) == width:
        rows.append(tuple(parsed[end]))
        end += 1
    if any(row is not None for row in parsed[end:]):
        raise UnreadableFile("malformed")
    if len(rows) > MAX_CHANNELS:
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
