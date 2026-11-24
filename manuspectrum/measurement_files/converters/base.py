"""Types shared by every instrument reader.

A reader takes the bytes of a file and returns a `Reading`; it raises
`UnreadableFile` when the file is of a known format but cannot be read, and
`UnsupportedFormat` when no reader exists. Facts are a closed allow-list
(`FACT_LABELS`): operator, user, path, history, free comments and sample names
are never read into a `Fact`.
"""

import math
from dataclasses import dataclass

from django.utils.translation import gettext_noop

MAX_CHANNELS = 1_048_576
MIN_ROWS = 2

UNREADABLE_CODES = frozenset(
    {
        "truncated",
        "malformed",
        "unsupported_variant",
        "no_numeric_columns",
        "too_few_points",
        "duplicate_x",
        "non_finite",
        "ambiguous_result",
    }
)

UNREADABLE_LABELS = {
    "truncated": gettext_noop("The file is cut short."),
    "malformed": gettext_noop("The file does not follow its format."),
    "unsupported_variant": gettext_noop("This variant of the format is not supported."),
    "no_numeric_columns": gettext_noop("The file holds no columns of numbers."),
    "too_few_points": gettext_noop("The spectrum has fewer than two points."),
    "duplicate_x": gettext_noop("Two points share the same x value."),
    "non_finite": gettext_noop("The spectrum holds a value that is not finite."),
    "ambiguous_result": gettext_noop(
        "The file holds several result spectra and does not say which to use."
    ),
}
"""English wording of each `UnreadableFile` code (msgids; French in the catalogue)."""

FACT_LABELS = {
    "instrument": gettext_noop("Instrument"),
    "serial_number": gettext_noop("Serial number"),
    "acquired_at": gettext_noop("Acquisition date and time (instrument clock)"),
    "reference_acquired_at": gettext_noop(
        "Reference acquisition date and time (instrument clock)"
    ),
    "tube_anode": gettext_noop("Tube anode"),
    "tube_voltage": gettext_noop("Tube voltage"),
    "tube_current": gettext_noop("Tube current"),
    "real_time": gettext_noop("Real time"),
    "live_time": gettext_noop("Live time"),
    "dead_time": gettext_noop("Dead time"),
    "measurement_time": gettext_noop("Measurement time"),
    "integration_time": gettext_noop("Integration time"),
    "averages": gettext_noop("Averages"),
    "sample_scans": gettext_noop("Sample scans"),
    "background_scans": gettext_noop("Background scans"),
    "dark_scans": gettext_noop("Dark scans"),
    "reference_scans": gettext_noop("Reference scans"),
    "detector_gains": gettext_noop("Detector gains"),
    "resolution": gettext_noop("Resolution"),
    "spectral_range": gettext_noop("Spectral range"),
    "channels": gettext_noop("Channels"),
    "calibration": gettext_noop("Calibration"),
    "laser_wavelength": gettext_noop("Laser wavelength"),
    "filter": gettext_noop("Filter"),
    "detector": gettext_noop("Detector"),
    "accessory": gettext_noop("Accessory"),
    "beam_splitter": gettext_noop("Beam splitter"),
    "source": gettext_noop("Source"),
    "apodization": gettext_noop("Apodization"),
    "zero_filling": gettext_noop("Zero filling"),
    "result_spectrum": gettext_noop("Result spectrum"),
    "excitation_angle": gettext_noop("Excitation angle"),
    "detection_angle": gettext_noop("Detection angle"),
    "working_distance": gettext_noop("Working distance"),
    "beam_size": gettext_noop("Beam size"),
    "atmosphere": gettext_noop("Atmosphere"),
    "ionisation": gettext_noop("Ionisation"),
    "mass_analyzer": gettext_noop("Mass analyzer"),
    "acquisition_software": gettext_noop("Acquisition software"),
}

QUANTITY_KEYS = frozenset(
    {
        "tube_voltage",
        "tube_current",
        "real_time",
        "live_time",
        "dead_time",
        "measurement_time",
        "integration_time",
        "resolution",
        "spectral_range",
        "laser_wavelength",
        "excitation_angle",
        "detection_angle",
        "working_distance",
        "beam_size",
        "calibration",
    }
)
"""Facts that carry a physical unit; every other key is unitless."""

WARNINGS = {
    "no_calibration": gettext_noop(
        "The file holds no energy calibration: the axis stays in channels."
    ),
    "date_order_unknown": gettext_noop(
        "The date is given as written; its day/month order is unknown."
    ),
    "detector_jumps_uncorrected": gettext_noop(
        "Detector jumps are not corrected in this spectrum."
    ),
    "h2o_compensation_not_applied": gettext_noop(
        "The file names a water-vapour compensation; it was not applied to this CSV."
    ),
    "grids_differ": gettext_noop(
        "The spectra of this file are on different x grids: they are not summed "
        "and only the raw file is kept."
    ),
}


def span(low: float, high: float) -> str:
    """A spectral range as a fact value: two numbers and an en dash, no words."""
    return f"{low:.10g}\u2013{high:.10g}"


@dataclass(frozen=True)
class Series:
    columns: tuple[str, ...]
    rows: tuple[tuple[float, ...], ...]


def check_series(series: Series) -> None:
    """Raise `UnreadableFile` unless `series` can be written as a contract CSV.

    Fewer than `MIN_ROWS` rows is `too_few_points`, a non-finite value
    `non_finite`, a row of the wrong length or x going down `malformed`, an x
    repeated `duplicate_x`.
    """
    if len(series.rows) < MIN_ROWS:
        raise UnreadableFile("too_few_points")
    width = len(series.columns)
    if any(len(row) != width for row in series.rows):
        raise UnreadableFile("malformed")
    if not all(math.isfinite(v) for row in series.rows for v in row):
        raise UnreadableFile("non_finite")
    for a, b in zip(series.rows, series.rows[1:]):
        if b[0] == a[0]:
            raise UnreadableFile("duplicate_x")
        if b[0] < a[0]:
            raise UnreadableFile("malformed")


@dataclass(frozen=True)
class Fact:
    key: str
    value: str
    unit: str | None = None

    def __post_init__(self):
        if self.key not in FACT_LABELS:
            raise ValueError(f"Unknown fact key: {self.key!r}")


@dataclass(frozen=True)
class Reading:
    """`series=None` means raw only; `content_preset` is the `XY_PRESETS` key
    the content implies, or None when the content says nothing."""

    format: str
    reader_version: int
    series: Series | None
    content_preset: str | None
    facts: tuple[Fact, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self):
        for code in self.warnings:
            if code not in WARNINGS:
                raise ValueError(f"Unknown warning code: {code!r}")


class UnreadableFile(Exception):
    """A file of a known format that cannot be read. `format` is the detected
    format, filled by `registry.convert` when the reader does not know it."""

    def __init__(self, code: str, format: str | None = None):
        if code not in UNREADABLE_CODES:
            raise ValueError(f"Unknown unreadable code: {code!r}")
        super().__init__(code)
        self.code = code
        self.format = format


class UnsupportedFormat(Exception):
    """A known format without a reader, or None when nothing matched."""

    def __init__(self, format: str | None):
        super().__init__(format)
        self.format = format
