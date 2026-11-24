# SPDX-License-Identifier: AGPL-3.0-only
# Written from: the XML of public Bruker XRF .spx demo files studied as data (InDoRES, CC BY 4.0)
"""Bruker XRF spectrum, XML (`.spx`).

The root holds `ClassInstance` children; the one of `Type="TRTSpectrum"` carries
the header classes (`TRTGeneratorHeader`, `TRTRFAHeader`, `TRTXrfHeader`,
`TRTESMAHeader`, ...), `TRTSpectrumHeader` and `Channels`, comma-separated
integer counts. Header values are found by element name inside that instance,
whichever class carries them. Decimals are commas, the prolog declares the
encoding (Windows-1252 in the files seen). Energy = `CalibAbs` + `CalibLin` x
channel, channels numbered from 0; without both `CalibAbs` and a non-zero
`CalibLin` the axis stays in channels. Dates are kept as written. `User`, `Name` and every other element
outside the allow-list are never read. A nested `TRTSpectrum` instance (a
fitted background, a result) is never entered.
"""

from defusedxml import ElementTree

from .base import MAX_CHANNELS, Fact, Reading, Series, UnreadableFile

FORMAT = "bruker_spx"
READER_VERSION = 1

_FACT_KEYS = (
    ("tube_voltage", "HighVoltage"),
    ("tube_current", "TubeCurrent"),
    ("tube_anode", "Anode"),
    ("real_time", "RealTime"),
    ("live_time", "LifeTime"),
    ("dead_time", "DeadTime"),
    ("serial_number", "SerialNo"),
    ("filter", "Filter"),
    ("atmosphere", "Atmosphere"),
    ("excitation_angle", "ExcitationAngle"),
    ("detection_angle", "DetectionAngle"),
)


def sniff(head: bytes) -> bool:
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return head.startswith(b"<?xml") and b"TRTSpectrum" in head


def _num(text: str) -> float:
    return float(text.strip().replace(",", "."))


def read(data: bytes) -> Reading:
    try:
        root = ElementTree.fromstring(data)
    except (ElementTree.ParseError, ValueError, UnicodeError):
        # defusedxml's refusals (entities, DTD, external references) are ValueErrors
        raise UnreadableFile("malformed") from None
    instance = next(
        (c for c in root.findall("ClassInstance") if c.get("Type") == "TRTSpectrum"),
        None,
    )
    if instance is None:
        raise UnreadableFile("malformed")

    values: dict[str, str] = {}

    def collect(node):
        for child in node:
            if child.tag == "ClassInstance" and child.get("Type") == "TRTSpectrum":
                continue
            text = (child.text or "").strip()
            if text and child.tag != "Channels" and child.tag not in values:
                values[child.tag] = text
            collect(child)

    collect(instance)
    channels = instance.find("Channels")
    if channels is not None and (channels.text or "").strip():
        values["Channels"] = channels.text.strip()

    try:
        declared = int(values["ChannelCount"])
        written = values["Channels"]
        calibrated = "CalibAbs" in values and "CalibLin" in values
        offset = _num(values["CalibAbs"]) if calibrated else 0.0
        gain = _num(values["CalibLin"]) if calibrated else 0.0
    except (KeyError, ValueError):
        raise UnreadableFile("malformed") from None
    if declared > MAX_CHANNELS:
        raise UnreadableFile("too_large")
    if declared <= 0 or written.count(",") + 1 != declared:
        raise UnreadableFile("malformed")
    try:
        counts = [int(v) for v in written.split(",")]
    except ValueError:
        raise UnreadableFile("malformed") from None

    warnings = ["date_order_unknown"]
    if gain == 0.0:
        columns, preset = ("channel", "counts"), "xrf_channel"
        rows = tuple((float(i), float(c)) for i, c in enumerate(counts))
        warnings.append("no_calibration")
    else:
        columns, preset = ("energy_keV", "counts"), "xrf"
        rows = tuple((offset + gain * i, float(c)) for i, c in enumerate(counts))

    facts = []
    if "Date" in values and "Time" in values:
        facts.append(Fact("acquired_at", f"{values['Date']} {values['Time']}"))
    facts += [Fact(k, values[h]) for k, h in _FACT_KEYS if h in values]
    facts.append(Fact("channels", str(declared)))
    if calibrated and gain != 0.0:
        facts.append(Fact("calibration", f"{values['CalibAbs']}; {values['CalibLin']}"))
    return Reading(
        format=FORMAT,
        reader_version=READER_VERSION,
        series=Series(columns, rows),
        content_preset=preset,
        facts=tuple(facts),
        warnings=tuple(warnings),
    )
