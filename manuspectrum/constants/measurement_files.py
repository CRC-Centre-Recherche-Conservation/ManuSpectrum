"""Closed vocabularies of the measurement-files batch workflow."""

from django.utils.translation import gettext_noop

RUN_STATES = (
    "collecting",
    "preparing",
    "review",
    "writing",
    "written",
    "undoing",
    "undone",
)
ITEM_ORIGINS = ("upload", "stored")
ITEM_OUTCOMES = (
    "pending",
    "csv",
    "raw_only",
    "unreadable",
    "unsupported",
    "not_measure",
)
ITEM_DECISIONS = ("pending", "ready", "aside")
ITEM_DISPLAY_SOURCES = ("technique", "chosen", "converter", "none")
ITEM_STATES = (
    "queued",
    "claimed",
    "prepared",
    "written",
    "failed",
    "removed",
    "kept",
)

COMMON_CODES = {
    "F": "fors",
    "FORS": "fors",
    "IR": "ftir",
    "FTIR": "ftir",
    "IRTF": "ftir",
    "X": "xrf",
    "XRF": "xrf",
    "R": "raman",
    "RAMAN": "raman",
    "MALDI": "mass_spec",
    "MS": "mass_spec",
}

ALERT_WORDS = ("test", "essai", "blanc", "ref", "blank")

CAUSES = {
    "already_provided": gettext_noop("This file is already provided on the analysis."),
    "same_target": gettext_noop("Several files target the same analysis and role."),
    "unknown_codes": gettext_noop("Some codes in the file name are not known."),
    "name_alert": gettext_noop(
        "The file name contains a word that suggests a test or a reference."
    ),
    "near_name": gettext_noop("Several analyses have a similar name."),
    "format_vs_technique": gettext_noop(
        "The file format does not match the technique of the analysis."
    ),
    "no_display": gettext_noop("No display is configured for this file."),
    "content_vs_display": gettext_noop(
        "The content of the file does not match the chosen display."
    ),
    "other_shelfmark": gettext_noop(
        "The file name points to another manuscript than the document."
    ),
    "no_analysis": gettext_noop("No analysis matches this file."),
    "in_database": gettext_noop("This file is already in the database."),
    "not_measure": gettext_noop("This file is not a measurement."),
    "lab_csv_set_aside": gettext_noop(
        "This CSV comes from the laboratory and is set aside."
    ),
    "too_large": gettext_noop("The converted CSV is too large to be stored."),
}
