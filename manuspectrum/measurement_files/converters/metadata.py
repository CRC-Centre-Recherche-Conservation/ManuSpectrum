"""Text of the « description » of a converted CSV file.

Only the facts of `FACT_LABELS` and the warnings of `WARNINGS` reach the
text, in every configured language, one per line. Values and the source name
go through `views.explorer.series.neutralise` (one line, no `"`, formulas
defused), except a fact value made only of numbers (`_PLAIN_NUMBERS`, a
negative range or calibration), which cannot carry a formula. A quantity without a unit says so, any other fact prints its value alone; dates stay as written.
"""

import re

from django.conf import settings
from django.utils.translation import gettext_noop

from manuspectrum.iiif.language import gettext_map
from manuspectrum.views.explorer.series import neutralise

from .base import FACT_LABELS, QUANTITY_KEYS, WARNINGS, Reading

_NUM = r"[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][-+]?\d+)?"
_PLAIN_NUMBERS = re.compile(rf"{_NUM}(?:\s*[;\u2013]\s*{_NUM})*", re.ASCII)
"""Numbers joined by `;` or an en dash: no operator, so no spreadsheet formula."""

NOTE = gettext_noop("Note")
UNIT_ABSENT = gettext_noop("unit not stated in the file")
SOURCE_FILE = gettext_noop("Source file")
CONVERTED_BY = gettext_noop("Converted by")
# Translators: one line of a file description, "<label>: <value>"
LINE = gettext_noop("%(label)s: %(value)s")


def describe(reading: Reading, *, source_name: str, sha256: str) -> dict[str, str]:
    absent = gettext_map(UNIT_ABSENT)
    produced_by = (
        f"ManuSpectrum {settings.APP_VERSION}, "
        f"{reading.format} reader v{reading.reader_version}"
    )
    lines = []

    def add(label, value):
        lines.append(gettext_map(LINE, label=label, value=value))

    for fact in reading.facts:
        plain = _PLAIN_NUMBERS.fullmatch(fact.value)
        value = fact.value if plain else neutralise(fact.value)
        if fact.unit is None and fact.key not in QUANTITY_KEYS:
            shown = value
        elif fact.unit is None:
            shown = {lang: [f"{value} ({t[0]})"] for lang, t in absent.items()}
        else:
            shown = f"{value} {neutralise(fact.unit)}"
        add(gettext_map(FACT_LABELS[fact.key]), shown)
    for code in reading.warnings:
        add(gettext_map(NOTE), gettext_map(WARNINGS[code]))
    add(gettext_map(SOURCE_FILE), neutralise(source_name))
    add("SHA-256", sha256)
    add(gettext_map(CONVERTED_BY), produced_by)
    return {lang: "\n".join(line[lang][0] for line in lines) for lang in absent}
