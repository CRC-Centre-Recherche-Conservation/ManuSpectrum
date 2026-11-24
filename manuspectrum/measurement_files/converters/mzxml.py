# SPDX-License-Identifier: AGPL-3.0-only
# Written from: the public mzXML 2.x/3.x schema (sashimi project) and the mzXML mass spectra of a public InDoRES demo dataset studied as data (CC BY 4.0)
"""Mass spectra in mzXML (`.mzXML`), as written by MALDI and LC-MS software.

The namespace (mzXML 2.x or 3.x) is ignored. Every `scan` (nested scans
included) with a `peaks` child is read: the text is base64 of (m/z, intensity)
pairs, big-endian (`byteOrder="network"`), `precision` 32 or 64 bits,
`compressionType` `none` or `zlib`. A scan with `pairOrder` other than
`m/z-int`, another byte order or another compression is an unsupported variant.
One scan gives its peaks; several scans on the identical m/z array give the sum
of their intensities; scans on different arrays give no series (raw only,
warning `grids_differ`). The byte-offset `index` of the file is never read.

`peaksCount` is checked against `MAX_CHANNELS` before any decoding, the base64
length against the size `peaksCount` implies, and a zlib stream is inflated
with a bound of that size plus one: any excess or shortfall is `malformed`.
`parentFile` (paths), `operator`, `contact`, `dataProcessing` and every other
element outside the allow-list are never read.
"""

import base64
import binascii
import math
import struct
import zlib

from defusedxml import ElementTree

from .base import MAX_CHANNELS, Fact, Reading, Series, UnreadableFile, span

FORMAT = "mzxml"
READER_VERSION = 1

_ZLIB_SLACK = 64
_VALUE_TAGS = (
    "msManufacturer",
    "msModel",
    "msIonisation",
    "msMassAnalyzer",
    "msDetector",
)


def sniff(head: bytes) -> bool:
    return b"<mzXML" in head


def _local(tag) -> str:
    return tag.rpartition("}")[2] if isinstance(tag, str) else ""


def _children(node, name):
    return [c for c in node if _local(c.tag) == name]


def _decode(node, count: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The m/z and intensity arrays of one `peaks` element."""
    if node.get("byteOrder", "network") != "network":
        raise UnreadableFile("unsupported_variant")
    if node.get("pairOrder", "m/z-int") != "m/z-int":
        raise UnreadableFile("unsupported_variant")
    compression = node.get("compressionType", "none")
    if compression not in ("none", "zlib"):
        raise UnreadableFile("unsupported_variant")
    precision = node.get("precision", "32")
    if precision not in ("32", "64"):
        raise UnreadableFile("unsupported_variant")
    width = int(precision) // 8
    size = count * 2 * width
    text = "".join((node.text or "").split())
    if compression == "none":
        if len(text) != 4 * -(-size // 3):
            raise UnreadableFile("malformed")
    elif not 0 < len(text) <= 4 * -(-(size + size // 1000 + _ZLIB_SLACK) // 3):
        raise UnreadableFile("malformed")
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise UnreadableFile("malformed")
    if compression == "zlib":
        inflater = zlib.decompressobj()
        try:
            raw = inflater.decompress(raw, size + 1)
        except zlib.error:
            raise UnreadableFile("malformed")
        if not inflater.eof or inflater.unused_data:
            raise UnreadableFile("malformed")
    if len(raw) != size:
        raise UnreadableFile("malformed")
    values = struct.unpack(f">{2 * count}{'f' if width == 4 else 'd'}", raw)
    return values[0::2], values[1::2]


def _facts(root) -> list[Fact]:
    facts = []
    for run in _children(root, "msRun"):
        for instrument in _children(run, "msInstrument"):
            found = {}
            for child in instrument:
                tag = _local(child.tag)
                value = (child.get("value") or "").strip()
                if tag in _VALUE_TAGS:
                    if value and tag not in found:
                        found[tag] = value
                elif tag == "software" and child.get("type") == "acquisition":
                    name = (child.get("name") or "").strip()
                    version = (child.get("version") or "").strip()
                    if name and "software" not in found:
                        found["software"] = f"{name} {version}".strip()
            model = " ".join(
                found[k] for k in ("msManufacturer", "msModel") if k in found
            )
            if model:
                facts.append(Fact("instrument", model))
            for key, tag in (
                ("ionisation", "msIonisation"),
                ("mass_analyzer", "msMassAnalyzer"),
                ("detector", "msDetector"),
                ("acquisition_software", "software"),
            ):
                if tag in found:
                    facts.append(Fact(key, found[tag]))
            return facts
    return facts


def read(data: bytes) -> Reading:
    try:
        root = ElementTree.fromstring(data)
    except (ElementTree.ParseError, ValueError, UnicodeError):
        raise UnreadableFile("malformed")
    except Exception as error:
        # DefusedXmlException subclasses (entities, DTD, external references)
        if type(error).__module__.startswith("defusedxml"):
            raise UnreadableFile("malformed")
        raise
    if _local(root.tag) != "mzXML":
        raise UnreadableFile("malformed")

    scans = []
    for scan in root.iter():
        if _local(scan.tag) != "scan":
            continue
        peaks = _children(scan, "peaks")
        if not peaks:
            continue
        try:
            count = int(scan.get("peaksCount", ""))
        except ValueError:
            raise UnreadableFile("malformed")
        if not 0 < count <= MAX_CHANNELS:
            raise UnreadableFile("malformed")
        scans.append(_decode(peaks[0], count))
    if not scans:
        raise UnreadableFile("malformed")

    facts = _facts(root)
    grid = scans[0][0]
    if any(mz != grid for mz, _ in scans):
        return Reading(
            format=FORMAT,
            reader_version=READER_VERSION,
            series=None,
            content_preset=None,
            facts=tuple(facts),
            warnings=("grids_differ",),
        )

    if len(scans) == 1:
        intensity = scans[0][1]
    else:
        intensity = tuple(math.fsum(column) for column in zip(*(s[1] for s in scans)))
    rows = tuple(zip(grid, intensity))
    if not all(math.isfinite(v) for row in rows for v in row):
        raise UnreadableFile("non_finite")
    if any(a[0] >= b[0] for a, b in zip(rows, rows[1:])):
        raise UnreadableFile("duplicate_x")

    facts.append(Fact("spectral_range", span(grid[0], grid[-1]), "m/z"))
    facts.append(Fact("channels", str(len(rows))))
    return Reading(
        format=FORMAT,
        reader_version=READER_VERSION,
        series=Series(("mz", "intensity"), rows),
        content_preset="mass_spec",
        facts=tuple(facts),
    )
