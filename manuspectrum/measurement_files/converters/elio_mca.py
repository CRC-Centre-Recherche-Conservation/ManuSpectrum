# SPDX-License-Identifier: AGPL-3.0-only
# Written from: ManuSpectrum's own text-export reader (30/10) and files studied as data; not Amptek PMCA
"""Text MCA export of a portable XRF spectrometer.

Layout: `# <title>`, `# <date time>`, `# <serial>`, `# Key: value` lines with
decimal commas, a bare `#`, then one count per line (`0.00000000E+00`). The
title is never read into a fact. Energy = offset + gain x channel from the two
usable `CalibrationN: <channel> <energy>` points (those that are not 0 0), with
channels numbered from 0; the calibration is never refitted. The date is kept as
written.
"""

from .base import MAX_CHANNELS, Fact, Reading, Series, UnreadableFile

FORMAT = "elio_mca"
READER_VERSION = 1

_FACT_KEYS = (
    ("tube_anode", "Tube Anode"),
    ("tube_voltage", "Tube Voltage"),
    ("tube_current", "Tube Current"),
    ("measurement_time", "Measurement time"),
    ("live_time", "Live time"),
    ("dead_time", "Deadtime"),
    ("channels", "MCA Channels"),
    ("excitation_angle", "Incident beam angle"),
    ("working_distance", "Sample to detector distance"),
    ("beam_size", "Fluorescence beam"),
)


def sniff(head: bytes) -> bool:
    return head.startswith(b"#") and b"# MCA Channels:" in head


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _calibration(header: dict[str, str]):
    """The non-zero points as (channel, energy, written text) or None."""
    points = []
    for key in ("Calibration1", "Calibration2", "Calibration3"):
        written = header.get(key)
        if written is None:
            continue
        parts = written.split()
        if len(parts) != 2:
            raise UnreadableFile("malformed")
        channel, energy = _num(parts[0]), _num(parts[1])
        if (channel, energy) != (0.0, 0.0):
            points.append((channel, energy, " ".join(parts)))
    if len(points) != 2 or points[0][0] == points[1][0]:
        return None
    return points


def read(data: bytes) -> Reading:
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise UnreadableFile("malformed")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(lines) < 4:
        raise UnreadableFile("malformed")
    stamp, serial = lines[1][1:].strip(), lines[2][1:].strip()
    header: dict[str, str] = {}
    body = []
    for line in lines[3:]:
        stripped = line.strip()
        if not stripped or stripped == "#":
            continue
        if stripped.startswith("#"):
            if ":" not in stripped:
                raise UnreadableFile("malformed")
            key, value = stripped[1:].split(":", 1)
            header[key.strip()] = value.strip()
        else:
            body.append(stripped)
    try:
        declared = int(_num(header["MCA Channels"]))
    except (KeyError, ValueError):
        raise UnreadableFile("malformed")
    if not 0 < declared <= MAX_CHANNELS or len(body) != declared:
        raise UnreadableFile("malformed")
    counts = []
    for item in body:
        value = float(item)
        if value != int(value):
            raise UnreadableFile("malformed")
        counts.append(int(value))
    points = _calibration(header)

    warnings = ["date_order_unknown"]
    if points is None:
        columns, preset = ("channel", "counts"), "xrf_channel"
        rows = tuple((float(i), float(c)) for i, c in enumerate(counts))
        warnings.append("no_calibration")
    else:
        (c1, e1, _), (c2, e2, _) = points
        gain = (e2 - e1) / (c2 - c1)
        offset = e1 - gain * c1
        columns, preset = ("energy_keV", "counts"), "xrf"
        rows = tuple((offset + gain * i, float(c)) for i, c in enumerate(counts))

    facts = [Fact("acquired_at", stamp), Fact("serial_number", serial)]
    facts += [Fact(k, header[h]) for k, h in _FACT_KEYS if h in header]
    if points is not None:
        facts.append(Fact("calibration", f"{points[0][2]}; {points[1][2]}"))
    return Reading(
        format=FORMAT,
        reader_version=READER_VERSION,
        series=Series(columns, rows),
        content_preset=preset,
        facts=tuple(facts),
        warnings=tuple(warnings),
    )
