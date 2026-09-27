"""IIIF language maps (Presentation 3 §4.4) and their v2 form.

Usage:
    python manage.py test tests.test_iiif_language --settings=tests.test_settings
"""

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
