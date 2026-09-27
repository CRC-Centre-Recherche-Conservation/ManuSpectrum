"""``xyReading``: how a client reads the curve out of a spectrum body (a JSON-LD extension, version 1).

The clean CSV of a file (``/iiif/data/<file>/series.csv``) carries a reading
of its two columns: ``dialect`` (the CSV this module writes), ``columns``,
the ``x`` and ``y`` axes (label as a language map, and whether x is drawn
reversed), ``corrections`` (none: the curve is already corrected) and
``derivedFrom``, the raw file it comes from. The raw file of a
text format carries the reading ``read_series`` applies to it: the columns
``apply_config`` reads (``x``, ``yLeft``, ``reference``, ``dark``), and under
``reference-normalize`` that correction. Nothing else is published: every key
is one the Python reader honours.

Axes: the axis titles and the x direction of the configuration the file is
shown with, as stored (``display`` of its ``renderer_config`` row), under
``none`` and without quantity. The CSV header is the label of each axis, made
safe for xyviewer's header rules (``csv_header``).

``context_document`` is the JSON-LD 1.1 context of the extension, served at
``ids.xy_context()``; its terms live in the namespace ``ids.xy_doc() + "#"``,
the documentation page. Inside ``xyReading`` it defines ``id``, ``type``,
``label`` and ``Dataset`` as Presentation 3 does, so the extension reads the
same under the Presentation 2 context.
"""

import itertools
import re
from collections import namedtuple

from manuspectrum.iiif import ids
from manuspectrum.iiif import language as lang
from manuspectrum.utils.spectrum_preview import is_supported, series_points
from manuspectrum.utils.xy_transforms import (
    EPSILON,
    multi_y_handling,
    resolve_columns,
)

RawFile = namedtuple("RawFile", "id name media_type path")

DIALECT = {"delimiter": ",", "headerRowCount": 1, "encoding": "utf-8"}
REFERENCE_NORMALIZE = {
    "type": "reference-normalize",
    "expression": "(y - dark) / (reference - dark)",
    "darkDefault": 0,
    "epsilon": EPSILON,
    "onInvalid": "drop-point",
}
ROWS_PER_CHUNK = 2000

# xyviewer reads a header cell as a number when parseFloat does, and takes
# as x the first column whose header matches one of these.
_JS_NUMBER = re.compile(r"^\s*[+-]?(Infinity|(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)")
_X_PATTERN = re.compile(
    r"^(x$|wavelength|wavenumber|energy|frequency|channel|position|time|index"
    r"|nm$|ev$|kev$)",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def raw_label(file):
    return lang.gettext_map("%(file)s, raw file", file=file.name)


def _stored_display(config):
    """The ``display`` block of the configuration, as stored."""
    display = (config or {}).get("display")
    return display if isinstance(display, dict) else {}


def axes(config):
    """``(x, y)``: the axis titles of the configuration, as stored; ``""`` for a side without one."""
    display = _stored_display(config)
    return (
        str(display.get("xAxisLabel") or "").strip(),
        str(display.get("yAxisLabel") or "").strip(),
    )


def _axis(label):
    return {"label": lang.none(label)} if label else {}


def _title(text, fallback, prefix):
    text = " ".join(_CONTROL.sub(" ", str(text or "")).replace(",", ";").split())
    text = text.replace('"', "'")
    if not text:
        return fallback
    if _JS_NUMBER.match(text) or text.startswith("#"):
        return f"{prefix} {text}"
    return text


def csv_header(config):
    """``(x title, y title)`` of the clean CSV: English, no comma, never read as a number, y never taken for x."""
    x_axis, y_axis = axes(config)
    x = _title(x_axis, "x", "X")
    y = _title(y_axis, "y", "Y")
    if _X_PATTERN.match(y):
        y = f"Y {y}"
    return x, y


def raw_reading(config):
    """The reading ``read_series`` applies to a raw text file under *config*."""
    columns = resolve_columns(config)
    roles = [("x", "x"), ("y", "yLeft"), ("reference", "reference"), ("dark", "dark")]
    listed = sorted(
        (columns[key], role) for key, role in roles if columns[key] is not None
    )
    reading = {
        "type": "XYReading",
        "columns": [{"index": index, "role": role} for index, role in listed],
    }
    normalize = (
        multi_y_handling(config) == "reference-normalize"
        and columns["reference"] is not None
    )
    if normalize:
        reading["multiY"] = "reference-normalize"
    reading["corrections"] = [dict(REFERENCE_NORMALIZE)] if normalize else []
    return reading


def derived_from(file, config):
    """The raw file a clean CSV comes from, with its reading when it is a text format."""
    derived = {
        "id": ids.data_raw(file.id),
        "type": "Dataset",
        "format": file.media_type,
        "label": raw_label(file),
    }
    if is_supported(file.name):
        derived["xyReading"] = raw_reading(config)
    return derived


def xy_reading(file, config):
    """The ``xyReading`` of the clean CSV of *file* read under *config*."""
    x_axis, y_axis = axes(config)
    reversed_x = bool(_stored_display(config).get("xReversed"))
    return {
        "type": "XYReading",
        "dialect": dict(DIALECT),
        "columns": [{"index": 0, "role": "x"}, {"index": 1, "role": "yLeft"}],
        "x": {**_axis(x_axis), "reversed": reversed_x},
        "y": [{"axis": "left", **_axis(y_axis)}],
        "corrections": [],
        "derivedFrom": derived_from(file, config),
    }


def csv_lines(file, config):
    """The clean CSV of *file* as an iterator of text chunks; None when it holds fewer than two points.

    The points are streamed from the file (``series_points``) and written in file order with ``repr(float)``,
    never decimated.
    """
    points = series_points(file.path, config)
    first = next(points, None)
    if first is None:
        return None
    header = ",".join(csv_header(config)) + "\r\n"

    def lines():
        try:
            yield header
            chunk = []
            for x, y in itertools.chain([first], points):
                chunk.append(f"{x!r},{y!r}\r\n")
                if len(chunk) == ROWS_PER_CHUNK:
                    yield "".join(chunk)
                    chunk = []
            if chunk:
                yield "".join(chunk)
        finally:
            points.close()

    return lines()


def context_document():
    """The JSON-LD 1.1 context of ``xyReading`` (version 1)."""
    return {
        "@context": {
            "@version": 1.1,
            "ms_xy": ids.xy_doc() + "#",
            "csvw": "http://www.w3.org/ns/csvw#",
            "prov": "http://www.w3.org/ns/prov#",
            "xsd": "http://www.w3.org/2001/XMLSchema#",
            "xyReading": {
                "@id": "ms_xy:xyReading",
                "@context": {
                    "id": "@id",
                    "type": "@type",
                    "label": {
                        "@id": "http://www.w3.org/2000/01/rdf-schema#label",
                        "@container": ["@language", "@set"],
                        "@context": {"none": "@none"},
                    },
                    "Dataset": "http://purl.org/dc/dcmitype/Dataset",
                    "XYReading": "ms_xy:XYReading",
                    "dialect": {
                        "@id": "csvw:dialect",
                        "@context": {
                            "delimiter": "csvw:delimiter",
                            "headerRowCount": {
                                "@id": "csvw:headerRowCount",
                                "@type": "xsd:integer",
                            },
                            "encoding": "csvw:encoding",
                        },
                    },
                    "columns": {"@id": "ms_xy:column", "@container": "@list"},
                    "index": {"@id": "ms_xy:columnIndex", "@type": "xsd:integer"},
                    "role": {
                        "@id": "ms_xy:role",
                        "@type": "@vocab",
                        "@context": {
                            "x": "ms_xy:x",
                            "yLeft": "ms_xy:yLeft",
                            "yRight": "ms_xy:yRight",
                            "reference": "ms_xy:reference",
                            "dark": "ms_xy:dark",
                            "ignore": "ms_xy:ignore",
                        },
                    },
                    "x": "ms_xy:xAxis",
                    "y": {"@id": "ms_xy:yAxis", "@container": "@list"},
                    "axis": "ms_xy:axisSide",
                    "quantity": "ms_xy:quantity",
                    "unit": "ms_xy:ucumCode",
                    "reversed": {"@id": "ms_xy:reversed", "@type": "xsd:boolean"},
                    "multiY": "ms_xy:multiYHandling",
                    "corrections": {"@id": "ms_xy:correction", "@container": "@list"},
                    "expression": "ms_xy:expression",
                    "darkDefault": {"@id": "ms_xy:darkDefault", "@type": "xsd:double"},
                    "epsilon": {"@id": "ms_xy:epsilon", "@type": "xsd:double"},
                    "onInvalid": "ms_xy:onInvalid",
                    "derivedFrom": {"@id": "prov:wasDerivedFrom"},
                },
            },
        }
    }
