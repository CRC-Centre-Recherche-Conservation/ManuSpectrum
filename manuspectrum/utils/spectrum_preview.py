"""A spectrum file read as a stream into the handful of points a sparkline draws.

Which extensions are readable is ``settings.XY_TEXT_FILE_FORMATS``, the same
list the XY reader and ``functions.xy_technique_config`` call canonical: an
instrument export that is not one of them is converted upstream, not parsed
here. Everything else — the binary formats, and ``.mca``, whose channel axis
means nothing without the per-file calibration in its header — has no preview.

The curve is the one the XY reader opens on, not the raw first two columns: the
renderer configuration stamped on the file entry says which column holds x,
which holds the measurement, and whether the measurement is a ratio against a
reference column. That corrective step is ``utils.xy_transforms``, the twin of
the reader's own. Only it is stored — the views a reader picks afterwards
(log(1/R), Kubelka-Munk) are not — so applying it reproduces the reader's
default drawing.

The canonical export reaches 2.8 MB and 136 805 points, so the file is never
held in memory: the parser yields one row at a time and the decimator keeps the
extremes of a bounded number of spans. Peak memory is the same for a ten-line
file and for the largest one.
"""

import math
import os
import re

from django.conf import settings

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


def build_preview(path, n, config=None):
    """The decimated series of one file, or ``None`` when it draws nothing.

    `config` is the stored renderer configuration of the file entry, which
    decides the columns, the normalisation and the direction of x.

    Decoding errors are replaced rather than raised: a text export with one
    stray byte still has a spectrum in it, and the offending row reads as NaN
    and is dropped on its own.
    """
    with open(path, encoding="utf-8", errors="replace") as handle:
        series = decimate(apply_config(parse_rows(handle), config), n)
    if series is not None:
        series["x_reversed"] = is_x_reversed(config)
    return series
