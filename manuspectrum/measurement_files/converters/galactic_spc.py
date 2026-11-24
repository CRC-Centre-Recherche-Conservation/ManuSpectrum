# SPDX-License-Identifier: AGPL-3.0-only
# Written from: the published Galactic/Thermo SPC file format specification (SPC.H) and public demo files studied as data
"""Galactic SPC spectrum (`.spc`, Raman, FTIR, UV-vis...).

Read: the new little-endian format (`fversn` 0x4B), one subfile, Y as float32
(`fexp` 0x80) or int32 scaled by 2^(fexp - 32), X evenly spaced from `ffirst`
to `flast` or given as one float32 array (`TXVALS`). The 0x4C (big-endian) and
0x4D (old) variants, several subfiles, 16-bit Y and XYXY files are recognised
and refused as `unsupported_variant`.

512-byte header (offsets): `ftflgs` 0, `fversn` 1, `fexp` 3, `fnpts` uint32 4,
`ffirst` float64 8, `flast` float64 16, `fnsub` uint32 24, `fxtype` 28, `fdate`
uint32 32 (minutes 6 bits, hours 5, day 5, month 4, year 12, from the low bits;
read as written, so no date-order warning). A 32-byte subfile header precedes
the Y values. The comment and the log block are free text and never read. The
axis is written x-ascending.
"""

import datetime
import math
import struct

from .base import MAX_CHANNELS, Fact, Reading, Series, UnreadableFile, span

FORMAT = "galactic_spc"
READER_VERSION = 1

HEADER = 512
OLD_HEADER = 256
SUBHEADER = 32
FLOAT_EXP = 0x80
TSPREC, TMULTI, TXYXYS, TXVALS = 0x01, 0x04, 0x40, 0x80
_WHOLE_FILE_BELOW = 4096

# fxtype -> (column name, content preset, unit of the spectral-range fact)
_AXES = {
    13: ("raman_shift_cm-1", "raman", "cm-1"),
    1: ("wavenumber_cm-1", None, "cm-1"),
    3: ("wavelength_nm", None, "nm"),
}


def _declared_points(head: bytes) -> int | None:
    """`fnpts` for a plausible SPC header of the three signatures, else None."""
    if len(head) < 2 or head[1] not in (0x4B, 0x4C, 0x4D):
        return None
    if head[1] == 0x4D:
        if len(head) < OLD_HEADER:
            return None
        (points,) = struct.unpack_from("<f", head, 4)
        if not math.isfinite(points) or points != int(points):
            return None
        points = int(points)
    else:
        if len(head) < HEADER:
            return None
        points = struct.unpack_from("<I" if head[1] == 0x4B else ">I", head, 4)[0]
    return points if 0 < points <= MAX_CHANNELS else None


def _expected_length(head: bytes, points: int) -> int:
    xs = 4 * points if head[0] & TXVALS else 0
    return HEADER + xs + SUBHEADER + 4 * points


def sniff(head: bytes) -> bool:
    points = _declared_points(head)
    if points is None:
        return False
    if len(head) < _WHOLE_FILE_BELOW and head[1] == 0x4B:
        return len(head) >= _expected_length(head, points)
    return True


def _acquired_at(packed: int) -> str | None:
    minute, hour = packed & 63, packed >> 6 & 31
    day, month, year = packed >> 11 & 31, packed >> 16 & 15, packed >> 20
    try:
        stamp = datetime.datetime(year, month, day, hour, minute)
    except ValueError:
        return None
    return stamp.strftime("%Y-%m-%d %H:%M")


def read(data: bytes) -> Reading:
    points = _declared_points(data[:HEADER])
    if points is None:
        raise UnreadableFile("malformed")
    if data[1] != 0x4B:
        raise UnreadableFile("unsupported_variant")
    flags, exp = data[0], data[3]
    (nsub,) = struct.unpack_from("<I", data, 24)
    if nsub > 1 or flags & (TSPREC | TMULTI | TXYXYS):
        raise UnreadableFile("unsupported_variant")
    if exp != FLOAT_EXP and exp > 127:
        raise UnreadableFile("unsupported_variant")
    if len(data) < _expected_length(data, points):
        raise UnreadableFile("truncated")
    if points < 2:
        raise UnreadableFile("too_few_points")

    position = HEADER
    if flags & TXVALS:
        xs = struct.unpack_from(f"<{points}f", data, position)
        position += 4 * points
    else:
        first, last = struct.unpack_from("<dd", data, 8)
        step = (last - first) / (points - 1)
        xs = [first + step * i for i in range(points)]
    position += SUBHEADER
    if exp == FLOAT_EXP:
        ys = struct.unpack_from(f"<{points}f", data, position)
    else:
        scale = 2.0 ** (exp - 32)
        ys = [v * scale for v in struct.unpack_from(f"<{points}i", data, position)]

    pairs = list(zip(xs, ys))
    if any(not (math.isfinite(x) and math.isfinite(y)) for x, y in pairs):
        raise UnreadableFile("non_finite")
    if pairs[0][0] > pairs[-1][0]:
        pairs.reverse()
    if any(b[0] == a[0] for a, b in zip(pairs, pairs[1:])):
        raise UnreadableFile("duplicate_x")
    if any(b[0] < a[0] for a, b in zip(pairs, pairs[1:])):
        raise UnreadableFile("malformed")

    name, preset, unit = _AXES.get(data[28], ("x", None, None))
    facts = []
    stamp = _acquired_at(struct.unpack_from("<I", data, 32)[0])
    if stamp:
        facts.append(Fact("acquired_at", stamp))
    low, high = pairs[0][0], pairs[-1][0]
    facts.append(Fact("spectral_range", span(low, high), unit))
    facts.append(Fact("channels", str(points)))
    return Reading(
        format=FORMAT,
        reader_version=READER_VERSION,
        series=Series((name, "intensity"), tuple(pairs)),
        content_preset=preset,
        facts=tuple(facts),
    )
