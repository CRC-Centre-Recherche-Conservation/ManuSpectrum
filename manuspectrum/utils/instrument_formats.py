"""Raw instrument files read natively: ELIO X-ray fluorescence ``.mca`` and ASD FieldSpec ``.asd``.

A native file decides its own reading; a renderer configuration stamped on it
is not consulted. ``read_native`` returns its rows (lists of floats, the
shape ``xy_transforms.apply_config`` takes), the renderer configuration that
reads them, and what its two axes hold (``Axis``: English label, quantity,
UCUM unit). A file that does not have the expected shape gives None.

ELIO ``.mca`` (XGLab/Bruker ELIO text export): ``# key: value`` header lines,
then one count per line, in channel order. ``# CalibrationN: <channel>
<energy in keV>`` lines (decimal comma or point; ``0 0`` is an empty slot)
give the energy axis: a least-squares line through two or more points of
distinct channels. Without it, x is the channel index.

ASD ``.asd`` (ASD Inc. binary, versions ``as1``–``as8``, little-endian): a
484-byte header (data type at byte 186, first wavelength and step as float32
at 191 and 195, data format at 199, channel count as uint16 at 204), the
spectrum, then from ``as2`` on a reference block (a 20-byte header whose
bytes 18-19 give the length of a description that follows) and the white
reference spectrum. A raw spectrum (type 0) with its reference reads as the
reflectance ``target / reference``; a reflectance spectrum (type 1) as
stored; other types are not read.
"""

import math
import os
import re
import struct
from dataclasses import dataclass, field

from django.utils.translation import gettext_noop

MCA = ".mca"
ASD = ".asd"
NATIVE_EXTENSIONS = frozenset({MCA, ASD})

_CALIBRATION = re.compile(r"^#\s*Calibration\d+\s*:\s*(\S+)\s+(\S+)\s*$", re.I)
_ASD_VERSIONS = {f"as{n}" for n in range(1, 9)}
_ASD_HEADER = 484
_ASD_FORMATS = {0: ("f", 4), 1: ("i", 4), 2: ("d", 8)}
_ASD_RAW, _ASD_REFLECTANCE = 0, 1
# Calibrated energies are rounded to 1e-12 keV, below any detector's
# resolution, which drops the float noise of the least-squares line.
ENERGY_DECIMALS = 12


@dataclass(frozen=True)
class Axis:
    """What an axis holds: its English label (a gettext msgid), quantity and UCUM unit."""

    label: str
    quantity: str | None = None
    unit: str | None = None


ENERGY = Axis(gettext_noop("Energy (keV)"), "energy", "keV")
CHANNEL = Axis(gettext_noop("Channel"), "channel", "1")
COUNTS = Axis(gettext_noop("Counts"), "count", "{counts}")
WAVELENGTH = Axis(gettext_noop("Wavelength (nm)"), "wavelength", "nm")
REFLECTANCE = Axis(gettext_noop("Reflectance (0-1)"), "reflectance", "1")


@dataclass(frozen=True)
class Native:
    """The reading of a native file: rows, the configuration applied to them, its axes."""

    rows: list
    x: Axis
    y: Axis
    config: dict = field(default_factory=dict)


def is_native(path):
    """Whether the extension of *path* is one of the formats read here."""
    return os.path.splitext(str(path))[1].lower() in NATIVE_EXTENSIONS


def read_native(path, name=None):
    """The ``Native`` reading of an ``.mca`` or ``.asd`` file; None when it is neither or is malformed.

    The extension of *name* (else of *path*) names the format.
    """
    extension = os.path.splitext(str(name or path))[1].lower()
    try:
        if extension == MCA:
            return _read_mca(path)
        if extension == ASD:
            return _read_asd(path)
    except (OSError, ValueError, struct.error):
        return None
    return None


def native_axes(path, name=None):
    """``(x, y)`` a native file states, read from its header alone; None when it states none.

    The extension of *name* (else of *path*) names the format. The data is
    not read: a file whose header is sound and whose data is not states axes
    that ``read_native`` then refuses.
    """
    extension = os.path.splitext(str(name or path))[1].lower()
    try:
        if extension == MCA:
            return _mca_axes(path)
        if extension == ASD:
            with open(path, "rb") as handle:
                header = handle.read(_ASD_HEADER)
            if (
                len(header) == _ASD_HEADER
                and header[:3].decode("latin-1") in _ASD_VERSIONS
                and header[186] in (_ASD_RAW, _ASD_REFLECTANCE)
            ):
                return WAVELENGTH, REFLECTANCE
    except (OSError, ValueError):
        return None
    return None


def _mca_axes(path):
    points, header = [], False
    with open(path, encoding="utf-8", errors="strict", newline=None) as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if not stripped.startswith("#"):
                break
            header = True
            found = _CALIBRATION.match(stripped)
            if found:
                points.append((_number(found[1]), _number(found[2])))
    if not header:
        return None
    return (CHANNEL if _calibration(points) is None else ENERGY), COUNTS


def _number(text):
    return float(text.replace(",", "."))


def _calibration(points):
    """``(intercept, slope)`` of the least-squares line through *points*; None with fewer than two channels."""
    points = [(c, e) for c, e in points if (c, e) != (0.0, 0.0)]
    if len({c for c, _ in points}) < 2:
        return None
    n = len(points)
    mean_c = sum(c for c, _ in points) / n
    mean_e = sum(e for _, e in points) / n
    slope = sum((c - mean_c) * (e - mean_e) for c, e in points) / sum(
        (c - mean_c) ** 2 for c, _ in points
    )
    return mean_e - slope * mean_c, slope


def _read_mca(path):
    points, counts, header = [], [], False
    with open(path, encoding="utf-8", errors="strict", newline=None) as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                header = True
                found = _CALIBRATION.match(stripped)
                if found:
                    points.append((_number(found[1]), _number(found[2])))
                continue
            value = float(stripped)
            if not math.isfinite(value):
                raise ValueError(stripped)
            counts.append(value)
    if not header or len(counts) < 2:
        return None
    line = _calibration(points)
    if line is None:
        x_axis, xs = CHANNEL, [float(i) for i in range(len(counts))]
    else:
        intercept, slope = line
        x_axis = ENERGY
        xs = [round(intercept + slope * i, ENERGY_DECIMALS) for i in range(len(counts))]
    return Native(
        rows=[[x, y] for x, y in zip(xs, counts)],
        x=x_axis,
        y=COUNTS,
        config={"display": {"xAxisLabel": x_axis.label, "yAxisLabel": COUNTS.label}},
    )


def _read_asd(path):
    with open(path, "rb") as handle:
        data = handle.read()
    if len(data) < _ASD_HEADER or data[:3].decode("latin-1") not in _ASD_VERSIONS:
        return None
    kind = data[186]
    start, step = struct.unpack_from("<ff", data, 191)
    code, width = _ASD_FORMATS.get(data[199], (None, None))
    channels = struct.unpack_from("<H", data, 204)[0]
    if code is None or channels < 2 or kind not in (_ASD_RAW, _ASD_REFLECTANCE):
        return None
    size = channels * width
    target = struct.unpack_from(f"<{channels}{code}", data, _ASD_HEADER)
    wavelengths = [start + step * i for i in range(channels)]
    if kind == _ASD_REFLECTANCE:
        rows = [[x, float(y)] for x, y in zip(wavelengths, target)]
        config = {}
    else:
        if data[:3] == b"as1":
            return None
        offset = _ASD_HEADER + size
        described = struct.unpack_from("<H", data, offset + 18)[0]
        reference = struct.unpack_from(
            f"<{channels}{code}", data, offset + 20 + described
        )
        rows = [
            [x, float(t), float(r)] for x, t, r in zip(wavelengths, target, reference)
        ]
        config = {
            "display": {
                "columnAssignments": [
                    {"columnIndex": 0, "role": "x"},
                    {"columnIndex": 1, "role": "yLeft"},
                    {"columnIndex": 2, "role": "reference"},
                ]
            },
            "multiYHandling": "reference-normalize",
        }
    config.setdefault("display", {}).update(
        xAxisLabel=WAVELENGTH.label, yAxisLabel=REFLECTANCE.label
    )
    return Native(rows=rows, x=WAVELENGTH, y=REFLECTANCE, config=config)
