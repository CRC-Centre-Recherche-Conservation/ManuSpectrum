# SPDX-License-Identifier: AGPL-3.0-only
# Written from: the public mzXML 2.x/3.x schema (sashimi project) and the mzXML mass spectra of a public InDoRES demo dataset studied as data (CC BY 4.0)
"""Mass spectra in mzXML (`.mzXML`), as written by MALDI and LC-MS software.

The namespace (mzXML 2.x or 3.x) is ignored. Every `scan` (nested scans
included) with a `peaks` child is read: the text is base64 of (m/z, intensity)
pairs, big-endian (`byteOrder="network"`), `precision` 32 or 64 bits,
`compressionType` `none` or `zlib`. Another byte order, compression, `pairOrder`
(2.x) or `contentType` (3.x) than `m/z-int` is an unsupported variant. A scan
with `peaksCount="0"` is skipped. One scan gives its peaks; several scans on the
identical m/z array give the sum of their intensities, accumulated as each scan
is decoded; scans on different arrays give no series (raw only, warning
`grids_differ`, found at the first mismatch). The byte-offset `index` of the
file is never read.

The sum of every `peaksCount` is checked against `MAX_CHANNELS` before any
decoding, the base64 length against the size `peaksCount` implies, and a zlib
stream is inflated with a bound of that size plus one: any excess or shortfall
is `malformed`. `parentFile` (paths), `operator`, `contact`, `dataProcessing`
and every other element outside the allow-list are never read.
"""

import base64
import binascii
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
    if node.get("contentType", "m/z-int") != "m/z-int":
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
        # defusedxml's refusals (entities, DTD, external references) are ValueErrors
        raise UnreadableFile("malformed") from None
    if _local(root.tag) != "mzXML":
        raise UnreadableFile("malformed")

    pending = []
    total = 0
    for scan in root.iter():
        if _local(scan.tag) != "scan":
            continue
        peaks = _children(scan, "peaks")
        if not peaks:
            continue
        try:
            count = int(scan.get("peaksCount", ""))
        except ValueError:
            raise UnreadableFile("malformed") from None
        if count < 0:
            raise UnreadableFile("malformed")
        if count == 0:
            continue
        total += count
        if total > MAX_CHANNELS:
            raise UnreadableFile("too_large")
        pending.append((peaks[0], count))
    if not pending:
        raise UnreadableFile("malformed")

    facts = _facts(root)
    grid = summed = None
    for node, count in pending:
        mz, intensity = _decode(node, count)
        if grid is None:
            grid, summed = mz, list(intensity)
        elif mz != grid:
            return Reading(
                format=FORMAT,
                reader_version=READER_VERSION,
                series=None,
                content_preset=None,
                facts=tuple(facts),
                warnings=("grids_differ",),
            )
        else:
            summed = [a + b for a, b in zip(summed, intensity)]

    rows = tuple(zip(grid, summed))
    facts.append(Fact("spectral_range", span(grid[0], grid[-1]), "m/z"))
    facts.append(Fact("channels", str(len(rows))))
    return Reading(
        format=FORMAT,
        reader_version=READER_VERSION,
        series=Series(("mz", "intensity"), rows),
        content_preset="mass_spec",
        facts=tuple(facts),
    )
