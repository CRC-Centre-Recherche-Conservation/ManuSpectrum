"""The colour swatch rule: by INHA uri first, by label word second.

Usage:
    python manage.py test tests.test_explorer_swatches --settings="tests.test_settings"
"""

from django.test import SimpleTestCase

from manuspectrum.views.explorer.swatches import (
    SWATCH_BY_URI,
    SWATCH_ORDER,
    colour_rank,
    colour_swatch,
)

INHA = "https://thesaurus.inha.fr/thesaurus/resource/ark:/54721/"
BLUE = INHA + "d549884f-ed29-4a28-87c8-07311d9a14ad"
WHITE = INHA + "2259f089-935b-46ec-af76-cdb5156ee311"


def item(uri, *labels):
    return {
        "uri": uri,
        "labels": [
            {"value": text, "language_id": lang, "valuetype_id": "prefLabel"}
            for lang, text in labels
        ],
    }


class SwatchTests(SimpleTestCase):
    def test_the_list_holds_fifteen_colours_in_a_fixed_order(self):
        self.assertEqual(len(SWATCH_BY_URI), 15)
        self.assertEqual(sorted(SWATCH_ORDER), sorted(SWATCH_BY_URI))
        self.assertEqual(SWATCH_ORDER[0], WHITE)
        self.assertEqual(colour_rank(WHITE), 0)
        self.assertIsNone(colour_rank("http://vocab/blue"))

    def test_the_uri_wins_over_the_label_word(self):
        self.assertEqual(colour_swatch(item(BLUE, ("en", "Red"))), "#2f55a4")

    def test_a_label_word_names_the_colour_of_an_unlisted_uri(self):
        self.assertEqual(
            colour_swatch(
                item("http://vocab/gilded", ("en", "Gilded"), ("fr", "Doré"))
            ),
            "goldenrod",
        )
        self.assertEqual(
            colour_swatch([item("http://vocab/x", ("fr", "Bleu"))]), "royalblue"
        )

    def test_a_value_naming_no_colour_has_no_swatch(self):
        self.assertIsNone(colour_swatch(item("http://vocab/x", ("en", "Chalk"))))
        self.assertIsNone(colour_swatch(None))
