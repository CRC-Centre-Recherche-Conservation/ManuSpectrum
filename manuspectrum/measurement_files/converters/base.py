"""Types shared by every instrument reader.

A reader takes the bytes of a file and returns a `Reading`; it raises
`UnreadableFile` when the file is of a known format but cannot be read, and
`UnsupportedFormat` when no reader exists. Facts are a closed allow-list
(`FACT_LABELS`): operator, user, path, history, free comments and sample names
are never read into a `Fact`.
"""

from dataclasses import dataclass

from django.utils.translation import gettext_noop

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

FACT_LABELS = {
    "instrument": gettext_noop("Instrument"),
    "serial_number": gettext_noop("Serial number"),
    "acquired_at": gettext_noop("Acquisition date and time"),
    "reference_acquired_at": gettext_noop("Reference acquisition date and time"),
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
    "calibration_source": gettext_noop("Calibration source"),
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

WARNINGS = {
    "no_calibration": gettext_noop("The file carries no calibration."),
    "date_order_unknown": gettext_noop(
        "The date is given as written; its day/month order is unknown."
    ),
    "detector_jumps_uncorrected": gettext_noop(
        "Detector jumps are not corrected in this spectrum."
    ),
    "h2o_compensation_not_applied": gettext_noop(
        "Water vapour compensation was not applied."
    ),
    "grids_differ": gettext_noop(
        "The spectra of this file do not share the same x grid."
    ),
    "no_reader": gettext_noop(
        "No reader exists for this format; the raw file is kept."
    ),
}


@dataclass(frozen=True)
class Series:
    columns: tuple[str, ...]
    rows: tuple[tuple[float, ...], ...]


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
    def __init__(self, code: str):
        if code not in UNREADABLE_CODES:
            raise ValueError(f"Unknown unreadable code: {code!r}")
        super().__init__(code)
        self.code = code


class UnsupportedFormat(Exception):
    """A known format without a reader, or None when nothing matched."""

    def __init__(self, format: str | None):
        super().__init__(format)
        self.format = format
