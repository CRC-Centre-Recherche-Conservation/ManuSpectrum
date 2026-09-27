"""A spectrum file read as a stream into the handful of points a sparkline draws.

The text formats read are ``settings.XY_TEXT_FILE_FORMATS``, the same list
the XY reader and ``functions.xy_technique_config`` call canonical. Two raw
instrument formats are read natively (``utils.instrument_formats``): ELIO
``.mca``, whose energy axis comes from the calibration in its own header, and
ASD ``.asd``. Every other format has no preview.

The curve is the one the XY reader opens on, not the raw first two columns: the
renderer configuration stamped on the file entry says which column holds x,
which holds the measurement, and whether the measurement is a ratio against a
reference column. That corrective step is ``utils.xy_transforms``, the twin of
the reader's own. Only it is stored — the views a reader picks afterwards
(log(1/R), Kubelka-Munk) are not — so applying it reproduces the reader's
default drawing.

The canonical export reaches 2.8 MB and 136 805 points, so the preview never
holds the file in memory: the parser yields one row at a time and the decimator
keeps the extremes of a bounded number of spans. Peak memory is the same for a
ten-line file and for the largest one. ``series_points`` streams every point,
for the exports that must not decimate; ``read_series`` holds them in memory.
"""

import itertools
import math
import os
import re
from contextlib import contextmanager

from django.conf import settings

from manuspectrum.utils.instrument_formats import (
    format_source,
    is_native,
    read_native,
)
from manuspectrum.utils.xy_transforms import apply_config

# The separators a canonical export has been seen to use, alone or repeated:
# comma first, then semicolon, tab and space, which cost nothing to accept.
_FIELDS = re.compile(r"[,;\t ]+")


def is_supported(path):
    """Whether the extension of `path` is one of `XY_TEXT_FILE_FORMATS`."""
    extension = os.path.splitext(path)[1].lstrip(".").lower()
    return extension in {
        entry.lower().lstrip(".") for entry in settings.XY_TEXT_FILE_FORMATS
    }


def is_readable(path, name=None):
    """Whether ``read_series`` reads the format (``format_source``): a supported text format or a native one."""
    source = format_source(path, name)
    return is_supported(source) or is_native(source)


def parse_rows(lines):
    """Yield each data row of an XY export as a list of floats.

    Blank lines, ``#`` comments and rows of a single field are skipped; a
    field that is not a number reads as NaN, which is what drops a column
    header without having to recognise one.
    """
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = [field for field in _FIELDS.split(stripped) if field]
        if len(fields) < 2:
            continue
        yield [_number(field) for field in fields]


def _number(field):
    try:
        return float(field)
    except ValueError:
        return math.nan


def is_x_reversed(config):
    """Whether the reader draws this configuration from right to left."""
    return bool(((config or {}).get("display") or {}).get("xReversed"))


def decimate(points, n):
    """Reduce a stream of points to at most `n` of them, extremes kept.

    The series is folded into spans of equal length, each holding the point of
    lowest and the point of highest y it saw; both are emitted, in x order, so
    a peak narrower than a span still reaches the drawing. The span length is
    not known in advance — the caller hands over an iterator — so it starts at
    one point and doubles whenever the spans held outgrow the budget, adjacent
    ones merging in pairs. A last pass groups what is left into exactly ``n/2``
    spans.

    Returns ``{"x", "y", "n_source", "decimated"}``, or ``None`` for a series
    of fewer than two points, which draws nothing.
    """
    budget = max(1, n // 2)
    ceiling = 2 * budget
    spans = []  # [lowest point, highest point] per span, spans in x order
    filled = 0  # points already folded into the last span
    length = 1  # points per span
    n_source = 0
    for point in points:
        n_source += 1
        if spans and filled < length:
            span = spans[-1]
            if point[1] < span[0][1]:
                span[0] = point
            if point[1] > span[1][1]:
                span[1] = point
            filled += 1
        else:
            spans.append([point, point])
            filled = 1
        if len(spans) > ceiling:
            # An even ceiling makes this length odd, so the last span is the
            # one left unpaired and `filled` still describes it.
            spans = _merge_pairs(spans)
            length *= 2

    if n_source < 2:
        return None
    if len(spans) > budget:
        spans = _regroup(spans, budget)

    xs, ys = [], []
    for low, high in spans:
        first, last = (low, high) if low[0] <= high[0] else (high, low)
        xs.append(first[0])
        ys.append(first[1])
        if last is not first:
            xs.append(last[0])
            ys.append(last[1])
    return {
        "x": xs,
        "y": ys,
        "n_source": n_source,
        "decimated": len(xs) < n_source,
    }


def _merge_pairs(spans):
    """Halve the spans held, each merged span keeping both extremes."""
    merged = []
    for index in range(0, len(spans) - 1, 2):
        left, right = spans[index], spans[index + 1]
        merged.append(
            [
                left[0] if left[0][1] <= right[0][1] else right[0],
                left[1] if left[1][1] >= right[1][1] else right[1],
            ]
        )
    if len(spans) % 2:
        merged.append(spans[-1])
    return merged


def _regroup(spans, budget):
    """Spread `spans` over exactly `budget` groups, extremes kept."""
    total = len(spans)
    groups = []
    current = -1
    for index, span in enumerate(spans):
        group = index * budget // total
        if group != current:
            groups.append([span[0], span[1]])
            current = group
        else:
            held = groups[-1]
            if span[0][1] < held[0][1]:
                held[0] = span[0]
            if span[1][1] > held[1][1]:
                held[1] = span[1]
    return groups


@contextmanager
def _points(path, config, name=None):
    """The configured points of one file, streamed from a single open.

    The extension of *name* (else of *path*) names the format. Decoding
    errors are replaced rather than raised: a text export with one stray
    byte still has a spectrum in it, and the offending row reads as NaN and
    is dropped on its own. A native format is read whole by ``read_native``
    under its own configuration; *config* is not consulted.
    """
    if is_native(format_source(path, name)):
        native = read_native(path, name)
        yield apply_config(native.rows, native.config) if native else iter(())
        return
    with open(path, encoding="utf-8", errors="replace") as handle:
        yield apply_config(parse_rows(handle), config)


def series_points(path, config=None, name=None):
    """Every ``(x, y)`` of one file as the reader draws it, streamed; nothing when it holds fewer than two.

    `config` is the stored renderer configuration of the file entry, which
    decides the columns and the normalisation of a text format; a native
    format reads under its own. The extension of *name* (else of *path*)
    names the format. A text file is read one row at a time, never decimated.
    """
    with _points(path, config, name) as points:
        first = list(itertools.islice(points, 2))
        if len(first) < 2:
            return
        yield from first
        yield from points


def x_reversed(path, config=None, name=None):
    """Whether the reader draws x reversed: a text format's configuration says so; a native one never."""
    return not is_native(format_source(path, name)) and is_x_reversed(config)


def read_series(path, config=None, name=None):
    """Every point of one file (``series_points``) held in memory, or ``None`` when it draws nothing.

    Returns ``{"x", "y", "x_reversed"}``.
    """
    xs, ys = [], []
    for x, y in series_points(path, config, name):
        xs.append(x)
        ys.append(y)
    if not xs:
        return None
    return {"x": xs, "y": ys, "x_reversed": x_reversed(path, config, name)}


def build_preview(path, n, config=None, name=None):
    """The decimated series of one file, or ``None`` when it draws nothing.

    The points are those ``read_series`` reads, streamed into ``decimate``
    without holding the series in memory; the extension of *name* (else of
    *path*) names the format.
    """
    with _points(path, config, name) as points:
        series = decimate(points, n)
    if series is not None:
        series["x_reversed"] = x_reversed(path, config, name)
    return series
