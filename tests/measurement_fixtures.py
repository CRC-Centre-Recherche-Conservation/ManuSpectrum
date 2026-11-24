"""Synthetic instrument files built by the tests; no lab file is involved.

`expected` and `assert_matches` compare a reading with the values an
independent library produced (`fixtures/measurement_files/oracle.py`).
"""

import json
import math
import struct
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "measurement_files"


def elio_mca(
    counts,
    *,
    calibration=((722, "8,046"), (1926, "22,163")),
    crlf=False,
    title="synthetic example",
):
    """Elio-style text export with invented header values."""
    lines = [
        f"# {title}",
        "# 11/05/2031 09:41:07",
        "# SN000",
        "# Fluorescence beam: 12,5",
        "# Incident beam angle: 45",
        "# Sample to detector distance: 2,5",
        "# Tube Anode:  Ag",
        "# Tube Voltage: 35",
        "# Tube Current: 150",
        "# Measurement time: 120000",
        "# Live time: 118,5",
        "# Deadtime: 1,25",
        f"# MCA Channels: {len(counts)}",
        f"# Calibration1: {calibration[0][0]} {calibration[0][1]}",
        f"# Calibration2: {calibration[1][0]} {calibration[1][1]}",
        "# Calibration3: 0 0",
        "#",
    ]
    lines += [f"{count:.8E}" for count in counts]
    eol = "\r\n" if crlf else "\n"
    return (eol.join(lines) + eol).encode("ascii")


def expected(name: str) -> dict:
    """The oracle entry of a fixture, keyed by its path under `FIXTURES`."""
    return json.loads((FIXTURES / "expected.json").read_text())[name]


def assert_matches(testcase, reading, name: str) -> None:
    """Columns, row count and preset exactly; head, tail and per-column sums
    to a relative 1e-9; no `forbidden` string in any fact value."""
    want = expected(name)
    rows = reading.series.rows
    testcase.assertEqual(list(reading.series.columns), want["columns"])
    testcase.assertEqual(len(rows), want["rows"])
    testcase.assertEqual(reading.content_preset, want["content_preset"])

    def close(got, wanted):
        testcase.assertEqual(len(got), len(wanted))
        for a, b in zip(got, wanted):
            testcase.assertTrue(math.isclose(a, b, rel_tol=1e-9, abs_tol=0), (a, b))

    for got, wanted in zip(rows[:5], want["head"]):
        close(got, wanted)
    for got, wanted in zip(rows[-5:], want["tail"]):
        close(got, wanted)
    close([math.fsum(r[i] for r in rows) for i in range(len(rows[0]))], want["sums"])
    for bad in want.get("forbidden", ()):
        for fact in reading.facts:
            testcase.assertNotIn(bad, fact.value)


def galactic_spc(
    ys,
    *,
    version=0x4B,
    flags=0,
    exp=0x80,
    xtype=13,
    first=100.0,
    last=200.0,
    nsub=1,
    date=(2031, 5, 11, 9, 41),
    comment=b"invented comment",
    x=None,
):
    """Single-subfile SPC with invented header values and a log block."""
    year, month, day, hour, minute = date
    packed = minute | hour << 6 | day << 11 | month << 16 | year << 20
    if x is not None:
        flags |= 0x80
    header = bytearray(512)
    header[0:4] = bytes((flags, version, 0, exp))
    struct.pack_into("<I", header, 4, len(ys))
    struct.pack_into("<dd", header, 8, first, last)
    struct.pack_into("<I", header, 24, nsub)
    header[28] = xtype
    struct.pack_into("<I", header, 32, packed)
    header[88 : 88 + len(comment)] = comment
    body = bytearray(32)
    xs = struct.pack(f"<{len(x)}f", *x) if x is not None else b""
    if exp == 0x80:
        body += struct.pack(f"<{len(ys)}f", *ys)
    else:
        body += struct.pack(f"<{len(ys)}i", *ys)
    struct.pack_into("<I", header, 248, 512 + len(xs) + len(body))
    return bytes(header) + xs + bytes(body) + b"\x00" * 64 + b"private log text"
