"""Python twin of ``media/js/utils/xy-transforms.js`` ``referenceNormalize``;
the preset rule lives in ``constants/xy_presets.py``.

The corrective step a renderer configuration declares is applied twice in this
project: in the browser by the XY reader, over the parsed file, and here, over
the stream the spectrum preview decimates. The file itself never travels to the
popup — two hundred points do — so the arithmetic is reimplemented rather than
shared, and it must not drift:

- ``tests/fixtures/xy/fors_reference.{csv,expected.json}`` is read by a test on
  each side, so the two implementations are compared against the same numbers;
- ``SUPPORTED_ROLES`` and ``SUPPORTED_MULTI_Y`` are asserted against every
  preset, so a preset declaring a correction this module does not implement
  fails the suite instead of being drawn raw under an axis naming a quantity it
  never computed.
"""

import math

# What this twin implements. A preset outside these is a preset whose curve the
# preview cannot reproduce.
SUPPORTED_ROLES = frozenset({"x", "yLeft", "reference", "dark"})
SUPPORTED_MULTI_Y = frozenset({"separate", "reference-normalize"})

# A denominator below this is noise; the reader drops the point rather than
# plot the ratio (EPSILON in xy-transforms.js).
EPSILON = 1e-12

_ROLE_KEYS = {"x": "x", "yLeft": "y", "reference": "reference", "dark": "dark"}


def resolve_columns(config):
    """The column index of each role the preview reads, or ``None``.

    ``display.columnAssignments`` of the renderer configuration names them; the
    first assignment of a role wins, so a file with several measurement columns
    is drawn on its first one. A configuration that assigns nothing — and a file
    that carries none — reads column 0 against column 1, the shape of a
    canonical export.
    """
    columns = {"x": 0, "y": 1, "reference": None, "dark": None}
    display = (config or {}).get("display") or {}
    assignments = display.get("columnAssignments")
    if not isinstance(assignments, list):
        return columns
    taken = set()
    for assignment in assignments:
        if not isinstance(assignment, dict):
            continue
        key = _ROLE_KEYS.get(assignment.get("role"))
        if key is None or key in taken:
            continue
        try:
            index = int(assignment.get("columnIndex"))
        except (TypeError, ValueError):
            continue
        if index < 0:
            continue
        columns[key] = index
        taken.add(key)
    return columns


def multi_y_handling(config):
    """``reference-normalize``, or ``separate`` for anything else."""
    handling = (config or {}).get("multiYHandling")
    return handling if handling == "reference-normalize" else "separate"


def reference_normalize(row_values, columns):
    """``(y - dark) / (reference - dark)`` for one row, or NaN.

    Dark is zero when the configuration names no dark column. NaN stands for
    every row the reader leaves out of the chart: one too short for its
    columns, and one whose denominator is not finite or is too small to divide
    by.
    """
    try:
        measurement = row_values[columns["y"]]
        dark = 0.0 if columns["dark"] is None else row_values[columns["dark"]]
        denominator = row_values[columns["reference"]] - dark
    except (IndexError, TypeError):
        return math.nan
    if not math.isfinite(denominator) or abs(denominator) < EPSILON:
        return math.nan
    return (measurement - dark) / denominator


def apply_config(rows, config):
    """Yield the ``(x, y)`` the XY reader plots, row by row.

    Under ``reference-normalize`` with a reference column, y is the normalised
    ratio; under any other handling it is the measurement column as it stands.
    A row missing a column it needs, or holding a value that is not finite, is
    left out — as it is left out of the chart.
    """
    columns = resolve_columns(config)
    normalize = (
        multi_y_handling(config) == "reference-normalize"
        and columns["reference"] is not None
    )
    x_index, y_index = columns["x"], columns["y"]
    for row in rows:
        try:
            x = row[x_index]
            y = reference_normalize(row, columns) if normalize else row[y_index]
        except IndexError:
            continue
        if math.isfinite(x) and math.isfinite(y):
            yield (x, y)
