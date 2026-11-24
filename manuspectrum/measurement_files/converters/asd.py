# SPDX-License-Identifier: AGPL-3.0-only
# Written from: the published « ASD File Format version 8 » documentation and public demo files studied as data
"""ASD FieldSpec spectrum (`.asd`, FORS), version 8 files.

Read: raw files (`data_type` 0, the counts the instrument has already
dark-corrected) that carry a white-reference block. The series holds the
target and the white reference side by side; reflectance is never computed
here (the `fors` preset does it). Reflectance, radiance and other data types,
files without a reference block and file versions other than 8 are recognised
and refused as `unsupported_variant`. The detector jumps are not corrected.

Layout (offsets from the start): `as8` 0, comment 3 (157 bytes, never read),
`data_type` 186, `ch1_wavel` float32 191, `wavel_step` float32 195,
`data_format` 199 (0 float32, 1 int32, 2 float64), `channels` uint16 204,
`it` uint32 390 (milliseconds, as stored), `instrument_number` uint16 400,
`dark_current_count` 425, `ref_count` 427, `sample_count` 429 (uint16),
`instrument` 431, `swir1_gain` / `swir2_gain` uint16 436 / 438. The target
spectrum starts at 484 in `data_format`. The reference block follows: a flag
(0xFFFF when present), two OLE automation dates (reference time, spectrum
time, both the instrument's clock), a length-prefixed description (never
read), then `channels` float64 values.
"""

import datetime
import math
import struct

from .base import MAX_CHANNELS, Fact, Reading, Series, UnreadableFile, span

FORMAT = "asd"
READER_VERSION = 1

HEADER = 484
RAW_DATA_TYPE = 0
_DATA_FORMATS = {0: ("f", 4), 1: ("i", 4), 2: ("d", 8)}
_INSTRUMENTS = {
    1: "PSII",
    2: "LabSpec VNIR",
    3: "FieldSpec VNIR",
    4: "FieldSpec FR",
    5: "FieldSpec NIR",
    6: "ChemRx",
    7: "LabSpec Pro",
    10: "HandHeld",
}
_OLE_EPOCH = datetime.datetime(1899, 12, 30)


def sniff(head: bytes) -> bool:
    return head[:2] == b"as" and len(head) > 2 and head[2] in b"12345678"


def _ole_date(value: float) -> str | None:
    try:
        stamp = _OLE_EPOCH + datetime.timedelta(seconds=round(value * 86400))
    except (OverflowError, ValueError):
        return None
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def read(data: bytes) -> Reading:
    if len(data) < HEADER:
        raise UnreadableFile("truncated")
    if data[2] != ord("8"):
        raise UnreadableFile("unsupported_variant")
    if data[186] != RAW_DATA_TYPE or data[199] not in _DATA_FORMATS:
        raise UnreadableFile("unsupported_variant")
    first, step = struct.unpack_from("<ff", data, 191)
    (channels,) = struct.unpack_from("<H", data, 204)
    if channels > MAX_CHANNELS:
        raise UnreadableFile("too_large")
    if not (math.isfinite(first) and math.isfinite(step)):
        raise UnreadableFile("malformed")
    if channels < 2:
        raise UnreadableFile("too_few_points")
    if step <= 0:
        raise UnreadableFile("malformed")

    code, width = _DATA_FORMATS[data[199]]
    position = HEADER + channels * width
    if len(data) < position + 2:
        raise UnreadableFile("truncated")
    target = struct.unpack_from(f"<{channels}{code}", data, HEADER)
    flag = data[position : position + 2]
    if flag == b"\x00\x00":
        raise UnreadableFile("unsupported_variant")
    if flag != b"\xff\xff":
        raise UnreadableFile("malformed")
    if len(data) < position + 20:
        raise UnreadableFile("truncated")
    reference_time, spectrum_time = struct.unpack_from("<dd", data, position + 2)
    (description,) = struct.unpack_from("<h", data, position + 18)
    if description < 0:
        raise UnreadableFile("malformed")
    position += 20 + description
    if len(data) < position + channels * 8:
        raise UnreadableFile("truncated")
    reference = struct.unpack_from(f"<{channels}d", data, position)

    if any(not math.isfinite(v) for v in (*target, *reference)):
        raise UnreadableFile("non_finite")
    rows = tuple(
        (first + i * step, float(t), r)
        for i, (t, r) in enumerate(zip(target, reference))
    )

    facts = []
    if data[431] in _INSTRUMENTS:
        facts.append(Fact("instrument", _INSTRUMENTS[data[431]]))
    (serial,) = struct.unpack_from("<H", data, 400)
    if serial:
        facts.append(Fact("serial_number", str(serial)))
    (integration,) = struct.unpack_from("<I", data, 390)
    facts.append(Fact("integration_time", str(integration), "ms"))
    dark, refs, samples = struct.unpack_from("<HHH", data, 425)
    facts += [
        Fact("averages", str(samples)),
        Fact("dark_scans", str(dark)),
        Fact("reference_scans", str(refs)),
    ]
    gains = struct.unpack_from("<HH", data, 436)
    facts.append(Fact("detector_gains", f"{gains[0]}; {gains[1]}"))
    for key, value in (
        ("acquired_at", spectrum_time),
        ("reference_acquired_at", reference_time),
    ):
        stamp = _ole_date(value)
        if stamp:
            facts.append(Fact(key, stamp))
    facts.append(Fact("channels", str(channels)))
    facts.append(Fact("spectral_range", span(rows[0][0], rows[-1][0]), "nm"))
    return Reading(
        format=FORMAT,
        reader_version=READER_VERSION,
        series=Series(("wavelength_nm", "target_dn", "white_reference_dn"), rows),
        content_preset="fors",
        facts=tuple(facts),
        warnings=("detector_jumps_uncorrected",),
    )
