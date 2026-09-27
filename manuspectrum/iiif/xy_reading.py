"""``xyReading``: how a client reads the curve out of a spectrum body (a JSON-LD extension, version 1).

The clean CSV of a file (``/iiif/data/<file>/series.csv``) carries a reading
of its two columns: ``dialect`` (the CSV this module writes), ``columns``,
the ``x`` and ``y`` axes (label as a language map, quantity, UCUM unit, and
whether x is drawn reversed), ``corrections`` (none: the curve is already
corrected) and ``derivedFrom``, the raw file it comes from. The raw file of a
text format carries the reading ``read_series`` applies to it: the columns
``apply_config`` reads (``x``, ``yLeft``, ``reference``, ``dark``), and under
``reference-normalize`` that correction. A native instrument format
(``utils.instrument_formats``) reads from its own header and carries none.
Nothing else is published: every key is one the Python reader honours.

Axes: a native file states its own; a configuration with a ``presetKey``
takes the row of ``QUANTITIES`` (labels rendered in every language); any
other configuration gives its display labels under ``none`` and no
quantity. The CSV header is the English label of each axis, made safe for
xyviewer's header rules (``csv_header``).

``context_document`` is the JSON-LD 1.1 context of the extension, served at
``ids.xy_context()``; its terms live in the namespace ``ids.xy_doc() + "#"``,
the documentation page.
"""

import re
from collections import namedtuple

from django.utils.translation import gettext_noop

from manuspectrum.iiif import ids
from manuspectrum.iiif import language as lang
from manuspectrum.utils.instrument_formats import (
    COUNTS,
    ENERGY,
    REFLECTANCE,
    WAVELENGTH,
    Axis,
    is_native,
    native_axes,
)
from manuspectrum.utils.spectrum_preview import is_supported, read_series
from manuspectrum.utils.xy_transforms import (
    EPSILON,
    multi_y_handling,
    resolve_columns,
)
from manuspectrum.views.explorer.values import _display

RawFile = namedtuple("RawFile", "id name media_type path")

WAVENUMBER = Axis(gettext_noop("Wavenumber (cm⁻¹)"), "wavenumber", "cm-1")
ABSORBANCE = Axis(gettext_noop("Absorbance"), "absorbance", "1")
ARBITRARY = Axis(gettext_noop("Intensity (a.u.)"), "intensity", "[arb'U]")
INTENSITY_COUNTS = Axis(gettext_noop("Intensity (counts)"), "count", "{counts}")

QUANTITIES = {
    "xrf": (ENERGY, COUNTS),
    "ftir": (WAVENUMBER, ABSORBANCE),
    "ftir_reflection": (WAVENUMBER, REFLECTANCE),
    "raman": (
        Axis(gettext_noop("Raman shift (cm⁻¹)"), "ramanShift", "cm-1"),
        ARBITRARY,
    ),
    "fors": (WAVELENGTH, REFLECTANCE),
    "mass_spec": (Axis(gettext_noop("m/z"), "massToCharge", "1"), ARBITRARY),
    "xrd": (Axis(gettext_noop("2θ (°)"), "twoTheta", "deg"), INTENSITY_COUNTS),
    "uv_vis": (WAVELENGTH, ABSORBANCE),
    "libs": (WAVELENGTH, INTENSITY_COUNTS),
    "luminescence": (WAVELENGTH, ARBITRARY),
    "colorimetry": (WAVELENGTH, REFLECTANCE),
}

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


def _native(file):
    if file is None or not is_native(file.name):
        return None
    return native_axes(file.path, file.name)


def axes(config, file=None):
    """``(x, y, translated)``: the ``Axis`` of each side, and whether their labels are msgids."""
    native = _native(file)
    if native:
        return native[0], native[1], True
    preset = QUANTITIES.get((config or {}).get("presetKey") or "")
    if preset:
        return preset[0], preset[1], True
    display = _display(config)
    return (
        Axis(str(display.get("xAxisLabel") or "").strip()),
        Axis(str(display.get("yAxisLabel") or "").strip()),
        False,
    )


def _axis(axis, translated):
    found = {}
    if axis.label:
        found["label"] = (
            lang.gettext_map(axis.label) if translated else lang.none(axis.label)
        )
    if axis.quantity:
        found["quantity"] = axis.quantity
    if axis.unit:
        found["unit"] = axis.unit
    return found


def _title(text, fallback, prefix):
    text = " ".join(_CONTROL.sub(" ", str(text or "")).replace(",", ";").split())
    text = text.replace('"', "'")
    if not text:
        return fallback
    if _JS_NUMBER.match(text) or text.startswith("#"):
        return f"{prefix} {text}"
    return text


def csv_header(config, file=None):
    """``(x title, y title)`` of the clean CSV: English, no comma, never read as a number, y never taken for x."""
    x_axis, y_axis, _ = axes(config, file)
    x = _title(x_axis.label, "x", "X")
    y = _title(y_axis.label, "y", "Y")
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
    x_axis, y_axis, translated = axes(config, file)
    reversed_x = False if _native(file) else bool(_display(config).get("xReversed"))
    return {
        "type": "XYReading",
        "dialect": dict(DIALECT),
        "columns": [{"index": 0, "role": "x"}, {"index": 1, "role": "yLeft"}],
        "x": {**_axis(x_axis, translated), "reversed": reversed_x},
        "y": [{"axis": "left", **_axis(y_axis, translated)}],
        "corrections": [],
        "derivedFrom": derived_from(file, config),
    }


def csv_lines(file, config):
    """The clean CSV of *file* as an iterator of text chunks; None when it holds fewer than two points.

    The series is read whole first (``read_series``), then written in file
    order with ``repr(float)``, never decimated.
    """
    series = read_series(file.path, config)
    if series is None:
        return None
    header = ",".join(csv_header(config, file)) + "\r\n"

    def lines():
        yield header
        chunk = []
        for x, y in zip(series["x"], series["y"]):
            chunk.append(f"{x!r},{y!r}\r\n")
            if len(chunk) == ROWS_PER_CHUNK:
                yield "".join(chunk)
                chunk = []
        if chunk:
            yield "".join(chunk)

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
