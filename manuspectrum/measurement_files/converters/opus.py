# SPDX-License-Identifier: AGPL-3.0-only
# Written from: public Bruker OPUS demo files (InDoRES, CC BY 4.0) and files of our own studied as data; brukeropus 1.4.3 (MIT) read to understand the block directory and the parameter block encoding; no code or label table translated from it
"""Bruker OPUS binary (`.0`, `.1`, ..., also `.spc.0`): FTIR result spectra.

No public specification exists; the layout below was read off files. A file
opens with the magic `0A 0A FE FE`, a float64 program version, then int32
values: directory offset (12), capacity (16), block count (20). The directory
is `count` entries of three int32: a type word, a size in 32-bit words and a
byte offset. The type word packs six fields from its low bits: 2, 2, 6, 7, 2
and 3 bits. Field 2 > 0 marks a parameter block (1 = data status of a data
block); field 1 is 1 for the sample, 2 for the reference, 3 for a result;
field 3, modulo 32, is the kind (4 absorbance, 5 transmittance, 12
reflectance); field 5 is 0 for a plain data block. Kind 13 and field 5 = 5 are blocks that
are not the spectrum itself (never read as a result). A field 3 of 32 or more
means several channels; `% 32` leaves its kind, and `_KINDS` then refuses it
as `unsupported_variant`. Blocks that overlap are `malformed`, so the
parameter walks never read more than the file holds.

A parameter block is a run of `KKK\\0`, int16 value type, int16 size in words
and the value (type 0 int32, 1 float64, otherwise a NUL-terminated Latin-1
string), ended by `END`. A result block holds float32 (`DPF` 1) or int32
(`DPF` 2) values, and its data status block (same fields except 2)
gives `NPT`, `FXV`, `LXV` (x spread evenly between them), `CSF` (scale of y),
`DXU` (`WN`: wavenumber) and `DAT`/`TIM`.

The result is the block named by the acquisition parameter `PLF`; without it,
the only result block, never the first single-channel one. A file with several
result blocks and no `PLF` is `ambiguous_result`. Only the parameters of the
allow-list are read: the history block, the sample name and form and every
path or experiment-file parameter never are. x is written ascending.
"""

import math
import struct

from .base import MAX_CHANNELS, Fact, Reading, Series, UnreadableFile, span

FORMAT = "opus"
READER_VERSION = 1

MAGIC = b"\x0a\x0a\xfe\xfe"
_MAX_BLOCKS = 4096

# kind of result block -> (column name, content preset)
_KINDS = {
    4: ("absorbance", "ftir"),
    5: ("transmittance", None),
    12: ("reflectance", "ftir_reflection"),
}
# `PLF` value -> kind
_PLF_KINDS = {"AB": 4, "TR": 5, "RFL": 12, "RF": 12, "R": 12}

# (fact key, parameter, unit)
_FACTS = (
    ("instrument", "INS", None),
    ("serial_number", "SRN", None),
    ("accessory", "ACC", None),
    ("detector", "DTC", None),
    ("source", "SRC", None),
    ("beam_splitter", "BMS", None),
    ("resolution", "RES", "cm-1"),
    ("sample_scans", "NSS", None),
    ("background_scans", "NSR", None),
    ("apodization", "APF", None),
    ("zero_filling", "ZFF", None),
)
_WANTED = {code for _, code, _ in _FACTS} | {"PLF", "TCL"}


def sniff(head: bytes) -> bool:
    return head[:4] == MAGIC


def _fields(word: int) -> tuple[int, ...]:
    return (
        word & 3,
        word >> 2 & 3,
        word >> 4 & 63,
        word >> 10 & 127,
        word >> 17 & 3,
        word >> 19 & 7,
    )


def _directory(data: bytes) -> list[tuple[tuple[int, ...], int, int]]:
    if len(data) < 24:
        raise UnreadableFile("truncated")
    start, _, count = struct.unpack_from("<3i", data, 12)
    if not 0 <= count <= _MAX_BLOCKS or start < 24:
        raise UnreadableFile("malformed")
    if start + 12 * count > len(data):
        raise UnreadableFile("truncated")
    blocks = []
    for index in range(count):
        word, words, offset = struct.unpack_from("<3i", data, start + 12 * index)
        if offset <= 0:
            break
        size = words * 4
        if words < 0 or offset + size > len(data):
            raise UnreadableFile("truncated")
        blocks.append((_fields(word), offset, size))
    spans = sorted((offset, offset + size) for _, offset, size in blocks if size)
    if any(b[0] < a[1] for a, b in zip(spans, spans[1:])):
        raise UnreadableFile("malformed")
    return blocks


def _params(data: bytes, offset: int, size: int, only=None) -> dict:
    """Parameters of one block; `only` limits the codes whose value is decoded."""
    end = offset + size
    out: dict[str, int | float | str] = {}
    at = offset
    while at + 8 <= end:
        code = data[at : at + 3].decode("latin-1")
        if code == "END":
            break
        kind, words = struct.unpack_from("<2h", data, at + 4)
        length = words * 2
        if words < 0 or at + 8 + length > end:
            raise UnreadableFile("malformed")
        if only is None or code in only:
            if kind == 0 and length >= 4:
                value = struct.unpack_from("<i", data, at + 8)[0]
            elif kind == 1 and length >= 8:
                value = struct.unpack_from("<d", data, at + 8)[0]
            elif kind in (0, 1):
                raise UnreadableFile("malformed")
            else:
                text = data[at + 8 : at + 8 + length].split(b"\x00")[0]
                value = text.decode("latin-1").strip()
            out.setdefault(code, value)
        at += 8 + length
    return out


def _text(value) -> str:
    if isinstance(value, float):
        return f"{value:.10g}"
    return str(value)


def _names_compensation(value) -> bool:
    """`TCL` (post-processing) lists the commands applied after acquisition."""
    return isinstance(value, str) and "h2ocomp" in value.lower()


def read(data: bytes) -> Reading:
    blocks = _directory(data)

    acquisition: dict[str, int | float | str] = {}
    for fields, offset, size in blocks:
        if fields[2] > 1 and fields[1] != 2:
            for code, value in _params(data, offset, size, _WANTED).items():
                acquisition.setdefault(code, value)

    results = [
        b
        for b in blocks
        if b[0][1] == 3 and b[0][2] == 0 and b[0][3] not in (0, 13) and b[0][5] != 5
    ]
    plf = acquisition.get("PLF")
    if isinstance(plf, str) and plf:
        if plf.upper() not in _PLF_KINDS:
            raise UnreadableFile("unsupported_variant")
        kind = _PLF_KINDS[plf.upper()]
        results = [b for b in results if b[0][3] % 32 == kind]
        if not results:
            raise UnreadableFile("malformed")
    if not results:
        raise UnreadableFile("malformed")
    if len(results) > 1:
        raise UnreadableFile("ambiguous_result")
    fields, offset, size = results[0]
    if fields[3] not in _KINDS or fields[5] != 0:
        raise UnreadableFile("unsupported_variant")
    column, preset = _KINDS[fields[3]]

    status = next(
        (
            b
            for b in blocks
            if b[0][2] == 1 and b[0][:2] == fields[:2] and b[0][3:] == fields[3:]
        ),
        None,
    )
    if status is None:
        raise UnreadableFile("malformed")
    header = _params(data, status[1], status[2])
    try:
        points = int(header["NPT"])
        first, last = float(header["FXV"]), float(header["LXV"])
        scale = float(header.get("CSF", 1.0))
        point_format = int(header.get("DPF", 1))
    except (KeyError, ValueError):
        raise UnreadableFile("malformed")
    if header.get("DXU") != "WN" or point_format not in (1, 2):
        raise UnreadableFile("unsupported_variant")
    if points > MAX_CHANNELS:
        raise UnreadableFile("too_large")
    if points < 2:
        raise UnreadableFile("too_few_points")
    if size < 4 * points:
        raise UnreadableFile("truncated")

    letter = "f" if point_format == 1 else "i"
    ys = struct.unpack_from(f"<{points}{letter}", data, offset)
    step = (last - first) / (points - 1)
    pairs = [(first + step * i, scale * y) for i, y in enumerate(ys)]
    if any(not (math.isfinite(x) and math.isfinite(y)) for x, y in pairs):
        raise UnreadableFile("non_finite")
    if pairs[0][0] > pairs[-1][0]:
        pairs.reverse()
    if any(b[0] <= a[0] for a, b in zip(pairs, pairs[1:])):
        raise UnreadableFile("duplicate_x")

    facts = []
    warnings = []
    for key, code, unit in _FACTS:
        value = _text(acquisition[code]) if code in acquisition else ""
        if value:
            facts.append(Fact(key, value, unit))
    if header.get("DAT") and header.get("TIM"):
        facts.append(Fact("acquired_at", f"{header['DAT']} {header['TIM']}"))
        warnings.append("date_order_unknown")
    if isinstance(plf, str) and plf:
        facts.append(Fact("result_spectrum", plf))
    facts.append(Fact("spectral_range", span(pairs[0][0], pairs[-1][0]), "cm-1"))
    if _names_compensation(acquisition.get("TCL")):
        warnings.append("h2o_compensation_not_applied")
    return Reading(
        format=FORMAT,
        reader_version=READER_VERSION,
        series=Series(("wavenumber_cm-1", column), tuple(pairs)),
        content_preset=preset,
        facts=tuple(facts),
        warnings=tuple(warnings),
    )
