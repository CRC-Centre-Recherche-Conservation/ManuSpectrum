"""The bare CSV contract and its checker.

UTF-8 without BOM, comma separator, dot decimal, one header row of column
names, then finite numbers only, x strictly ascending, every row the same
length, `\\n` line endings, no comment line.
"""

import csv
import io
import math
import re
from pathlib import PurePosixPath

from django.conf import settings

from .base import MIN_ROWS, Series

_NUMBER = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$", re.ASCII)
_HEADER_CELL = re.compile(r"^[^\W\d_][\w .()/%+\-]*$")
_OPUS_EXTENSION = re.compile(r"\.\d+$")


def format_number(value: float) -> str:
    if value.is_integer() and abs(value) < 2**53:
        return str(int(value))
    return repr(value)


def write_csv(series: Series) -> bytes:
    width = len(series.columns)
    previous = None
    for row in series.rows:
        if len(row) != width:
            raise ValueError("Rows of unequal length")
        if not all(math.isfinite(v) for v in row):
            raise ValueError("Non-finite value")
        if previous is not None and not row[0] > previous:
            raise ValueError("x is not strictly ascending")
        previous = row[0]
    lines = [",".join(series.columns)]
    lines.extend(",".join(format_number(float(v)) for v in row) for row in series.rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def check_csv(data: bytes) -> tuple[str, ...]:
    """Return the first contract violation of `data` as a one-code tuple, or `()`.

    The codes are closed: `bom`, `not_utf8`, `line_ending`, `no_header`,
    `header_invalid`, `comment_line`, `separator`, `too_few_columns`, `quoted`,
    `row_length`, `not_numeric`, `non_finite`, `x_not_ascending`,
    `too_few_rows`. A header cell must match `_HEADER_CELL`: it starts with a
    letter and holds letters, digits, `_`, space and `. ( ) / % + -` only, so a
    number, a formula, markup or a leading space is `header_invalid`. A quote
    anywhere is `quoted`; fewer than two columns is `too_few_columns`
    (`separator` when the header holds a `;` or a tab).

    A body cell must match `_NUMBER` exactly (no sign `+`, spaces, digit
    separators or non-ASCII digits): anything else is `not_numeric`, so `nan`
    and `inf` written as words are `not_numeric` too. `non_finite` is a cell
    that matches but overflows to infinity (`1e999`).
    """
    if data.startswith(b"\xef\xbb\xbf"):
        return ("bom",)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ("not_utf8",)
    if "\r" in text:
        return ("line_ending",)
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return ("no_header",)
    if '"' in text:
        return ("quoted",)
    rows = list(csv.reader(lines, delimiter=","))
    header = rows[0]
    if not all(_HEADER_CELL.match(c) for c in header):
        if len(header) < 2 and (";" in lines[0] or "\t" in lines[0]):
            return ("separator",)
        return ("header_invalid",)
    body = rows[1:]
    if any(line.lstrip().startswith("#") for line in lines[1:]):
        return ("comment_line",)
    if len(header) < 2:
        return ("too_few_columns",)
    if any(len(r) != len(header) for r in body):
        return ("row_length",)
    values = []
    for row in body:
        parsed = []
        for cell in row:
            if not _NUMBER.match(cell):
                return ("not_numeric",)
            parsed.append(float(cell))
        values.append(parsed)
    if any(not math.isfinite(v) for row in values for v in row):
        return ("non_finite",)
    if any(b[0] <= a[0] for a, b in zip(values, values[1:])):
        return ("x_not_ascending",)
    if len(values) < MIN_ROWS:
        return ("too_few_rows",)
    return ()


def fits_viewer(csv_bytes: bytes) -> bool:
    """Whether the viewer can draw a CSV of this size.

    `SPECTRUM_PREVIEW_MAX_BYTES` is the ceiling of the spectrum preview, the
    full series, `series.csv` and the IIIF clean CSV: a larger CSV is never
    drawn, so the caller keeps the raw file alone and says `too_large`.
    """
    return len(csv_bytes) <= settings.SPECTRUM_PREVIEW_MAX_BYTES


def csv_name(raw_name: str) -> str:
    """Replace the last extension by `.csv`, keeping an OPUS numeric one.

    Takes a file name: any directory part is dropped first.
    """
    raw_name = PurePosixPath(raw_name).name
    if _OPUS_EXTENSION.search(raw_name):
        return raw_name + ".csv"
    stem, dot, _ = raw_name.rpartition(".")
    return (stem if dot and stem else raw_name) + ".csv"
