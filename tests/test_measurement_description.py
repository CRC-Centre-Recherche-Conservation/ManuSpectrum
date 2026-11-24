from django.conf import settings
from django.test import SimpleTestCase
from django.utils import translation

from manuspectrum.measurement_files.converters.base import (
    FACT_LABELS,
    WARNINGS,
    Fact,
    Reading,
)
from manuspectrum.measurement_files.converters.metadata import describe

FIXED_MSGIDS = (
    "Note",
    "unit not stated in the file",
    "Source file",
    "Converted by",
)
SAME_IN_FRENCH = {"Instrument", "Source", "Ionisation"}
SHA = "ab" * 32


def _reading(facts=(), warnings=()):
    return Reading(
        format="elio_mca",
        reader_version=1,
        series=None,
        content_preset=None,
        facts=tuple(facts),
        warnings=tuple(warnings),
    )


class DescribeTests(SimpleTestCase):
    def test_describes_each_fact_in_every_language(self):
        reading = _reading(
            [Fact("tube_voltage", "20"), Fact("resolution", "4", "cm-1")]
        )
        text = describe(reading, source_name="a.mca", sha256=SHA)
        self.assertEqual(set(text), {"en", "fr"})
        en = text["en"].split("\n")
        fr = text["fr"].split("\n")
        self.assertEqual(en[0], "Tube voltage: 20 (unit not stated in the file)")
        self.assertEqual(en[1], "Resolution: 4 cm-1")
        self.assertEqual(fr[0], "Tension du tube : 20 (unité absente du fichier)")
        self.assertEqual(fr[1], "Résolution : 4 cm-1")

    def test_adds_a_line_per_warning(self):
        text = describe(
            _reading(warnings=["no_calibration"]), source_name="a.mca", sha256=SHA
        )
        self.assertIn(
            "Note: The file holds no energy calibration: the axis stays in channels.",
            text["en"].split("\n"),
        )
        self.assertIn(
            "Remarque : Le fichier ne contient pas d'étalonnage en énergie : l'axe reste en canaux.",
            text["fr"].split("\n"),
        )

    def test_carries_the_provenance(self):
        text = describe(_reading(), source_name="a.mca", sha256=SHA)
        for lang in ("en", "fr"):
            self.assertIn("a.mca", text[lang])
            self.assertIn(f"SHA-256{' :' if lang == 'fr' else ':'} {SHA}", text[lang])
            self.assertIn(
                f"ManuSpectrum {settings.APP_VERSION}, elio_mca reader v1", text[lang]
            )
        self.assertIn("Source file: a.mca", text["en"])
        self.assertIn("Fichier source : a.mca", text["fr"])
        self.assertIn("Converted by: ManuSpectrum", text["en"])

    def test_neutralises_header_text(self):
        reading = _reading([Fact("instrument", '=cmd|"/c calc"!A1\r\n<script>')])
        text = describe(reading, source_name="+x.mca", sha256=SHA)
        for lang, body in text.items():
            lines = body.split("\n")
            self.assertEqual(len(lines), 4, lang)
            self.assertNotIn("\r", body)
            self.assertNotIn('"', body)
            self.assertIn(": '=cmd|", lines[0])
            self.assertTrue(lines[1].endswith(": '+x.mca"))


class CatalogueTests(SimpleTestCase):
    def test_every_label_and_warning_has_a_french_translation(self):
        from django.utils.translation import gettext

        msgids = [*FACT_LABELS.values(), *WARNINGS.values(), *FIXED_MSGIDS]
        with translation.override("fr"):
            missing = [m for m in msgids if m not in SAME_IN_FRENCH and gettext(m) == m]
        self.assertEqual(missing, [])
