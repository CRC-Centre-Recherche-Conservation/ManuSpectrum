"""IIIF language maps (Presentation 3 §4.4) and their v2 form.

Usage:
    python manage.py test tests.test_iiif_language --settings=tests.test_settings
"""

from pathlib import Path
from unittest import mock

import polib
from django.conf import settings
from django.core.management import get_commands, load_command_class
from django.test import SimpleTestCase, override_settings

from manuspectrum.iiif import language


def reference(*labels):
    """One controlled-list reference item with ``(language, valuetype, value)`` labels."""
    return {
        "uri": "http://vocab.getty.edu/aat/300013526",
        "list_id": "l1",
        "labels": [
            {"language_id": lang, "valuetype_id": kind, "value": value}
            for lang, kind, value in labels
        ],
    }


@override_settings(LANGUAGES=[("en", "English"), ("fr", "French")])
class LanguageMapTests(SimpleTestCase):
    def test_languages_are_the_configured_codes_in_order(self):
        self.assertEqual(language.languages(), ["en", "fr"])

    def test_from_texts_drops_empty_values(self):
        self.assertEqual(
            language.from_texts({"en": " Ms 59 ", "fr": "", "de": None}),
            {"en": ["Ms 59"]},
        )
        self.assertEqual(language.from_texts({}), {})

    def test_none_never_guesses_a_language(self):
        self.assertEqual(language.none("EMMA", "", None), {"none": ["EMMA"]})
        self.assertEqual(language.none("", None), {})

    def test_gettext_map_renders_every_configured_language(self):
        self.assertEqual(
            language.gettext_map("Operators"),
            {"en": ["Operators"], "fr": ["Opérateurs"]},
        )

    def test_a_msgid_is_translated_once_per_process(self):
        with mock.patch.object(
            language, "gettext", wraps=language.gettext
        ) as translate:
            renders = [language.gettext_map("Operators") for _ in range(3)]

        self.assertEqual(renders[0], renders[2])
        self.assertLessEqual(translate.call_count, len(language.languages()))
        renders[0]["en"].append("changed")
        self.assertEqual(language.gettext_map("Operators")["en"], ["Operators"])

    @override_settings(LANGUAGES=[("fr", "French")])
    def test_a_language_setting_change_renders_the_new_languages(self):
        self.assertEqual(language.gettext_map("Operators"), {"fr": ["Opérateurs"]})

    def test_gettext_map_fills_placeholders_from_strings_and_maps(self):
        rendered = language.gettext_map(
            "%(name)s, %(canvas)s",
            name={"en": ["Ms 59"], "fr": ["Ms 59 (fr)"]},
            canvas="f. 2r",
        )
        self.assertEqual(
            rendered, {"en": ["Ms 59, f. 2r"], "fr": ["Ms 59 (fr), f. 2r"]}
        )

    def test_joined_keeps_one_string_per_language(self):
        joined = language.joined(
            [
                {"en": ["vermilion"], "fr": ["vermillon"]},
                {"en": ["lead white"], "fr": ["blanc de plomb"]},
            ]
        )
        self.assertEqual(
            joined,
            {"en": ["vermilion, lead white"], "fr": ["vermillon, blanc de plomb"]},
        )

    def test_joined_falls_back_to_none_when_a_language_is_missing(self):
        joined = language.joined(
            [{"en": ["vermilion"], "fr": ["vermillon"]}, {"none": ["Hg"]}], sep="; "
        )
        self.assertEqual(joined, {"en": ["vermilion; Hg"], "fr": ["vermillon; Hg"]})

    def test_joined_falls_back_to_the_first_language_of_a_map(self):
        joined = language.joined(
            [{"en": ["Ms 59"], "fr": ["Ms 59"]}, {"fr": ["Initiale P"]}]
        )
        self.assertEqual(
            joined, {"en": ["Ms 59, Initiale P"], "fr": ["Ms 59, Initiale P"]}
        )

    def test_joined_of_untagged_values_stays_untagged(self):
        self.assertEqual(
            language.joined([{"none": ["A"]}, {}, {"none": ["B"]}]), {"none": ["A, B"]}
        )
        self.assertEqual(language.joined([]), {})

    def test_descriptor_names_reads_every_language(self):
        descriptors = {
            "en": {"name": "Ms 59", "description": "x"},
            "fr": {"name": "Ms 59 (fr)"},
            "de": {"name": "  "},
            "it": "not a descriptor",
        }
        self.assertEqual(
            language.descriptor_names(descriptors),
            {"en": ["Ms 59"], "fr": ["Ms 59 (fr)"]},
        )
        self.assertEqual(language.descriptor_names(None), {})

    def test_reference_labels_prefer_pref_label_then_alt_label_per_language(self):
        value = [
            reference(
                ("en", "altLabel", "HgS"),
                ("en", "prefLabel", "vermilion"),
                ("fr", "altLabel", "cinabre"),
            )
        ]
        self.assertEqual(
            language.reference_labels(value), {"en": ["vermilion"], "fr": ["cinabre"]}
        )

    def test_reference_labels_join_several_items(self):
        value = [
            reference(("en", "prefLabel", "red")),
            reference(("en", "prefLabel", "blue")),
        ]
        self.assertEqual(language.reference_labels(value), {"en": ["red, blue"]})

    def test_to_v2_omits_the_language_of_none(self):
        self.assertEqual(
            language.to_v2({"en": ["Ms 59"], "none": ["EMMA"]}),
            [
                {"@value": "Ms 59", "@language": "en"},
                {"@value": "EMMA"},
            ],
        )


class CatalogueTests(SimpleTestCase):
    FRENCH = Path(settings.APP_ROOT) / "locale" / "fr" / "LC_MESSAGES" / "django.po"
    IIIF_SOURCES = (
        "iiif/",
        "views/iiif/",
        "templates/iiif/",
        "utils/instrument_formats.py",
    )

    def entries(self):
        return [entry for entry in polib.pofile(str(self.FRENCH)) if not entry.obsolete]

    def test_the_msgids_given_to_the_language_map_helpers_are_extracted(self):
        msgids = {entry.msgid for entry in self.entries()}
        for msgid in (
            "Analyses of %(name)s, %(canvas)s",
            "Identified materials of %(name)s",
            "Status",
            "Draft",
            "Operators",
            "Colour: %(colours)s",
            "%(file)s, series",
            "Without a position on the image",
            "Selection of %(count)d page of %(document)s",
        ):
            with self.subTest(msgid=msgid):
                self.assertIn(msgid, msgids)

    def test_makemessages_is_the_project_command_with_the_helper_keywords(self):
        command = load_command_class(get_commands()["makemessages"], "makemessages")

        self.assertEqual(get_commands()["makemessages"], "manuspectrum")
        self.assertIn("--keyword=gettext_map", command.xgettext_options)
        self.assertIn("--keyword=ngettext_map:1,2", command.xgettext_options)

    def test_every_iiif_string_has_a_french_translation(self):
        for entry in self.entries():
            if not any(
                path.startswith(self.IIIF_SOURCES) for path, _ in entry.occurrences
            ):
                continue
            with self.subTest(msgid=entry.msgid[:60]):
                self.assertTrue(entry.translated())
                self.assertNotIn("fuzzy", entry.flags)
