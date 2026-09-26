"""Conditions de mesure read from the Analysis statements (D40).

Usage:
    python manage.py test tests.test_explorer_conditions --settings="tests.test_settings"
"""

from django.test import SimpleTestCase

from manuspectrum.views.explorer.conditions import clean_html, conditions_of

TYPE, CONTENT = "node-type", "node-content"


def statement(html, type_label=None, lang="en"):
    data = {CONTENT: {lang: {"value": html, "direction": "ltr"}}}
    if type_label:
        data[TYPE] = [
            {
                "uri": f"http://aat/{type_label}",
                "labels": [
                    {
                        "value": type_label,
                        "language_id": "en",
                        "list_item_id": f"i-{type_label}",
                        "valuetype_id": "prefLabel",
                    }
                ],
            }
        ]
    return data


class CleanTests(SimpleTestCase):
    def test_scripts_attributes_and_unknown_tags_are_dropped(self):
        dirty = '<p onclick="x()">260 µm</p><script>alert(1)</script><img src=x onerror=alert(1)><a href="javascript:x">l</a>'

        cleaned = clean_html(dirty)

        self.assertTrue(cleaned.startswith("<p>260 µm</p>"))
        for forbidden in (
            "onclick",
            "<script",
            "alert",
            "<img",
            "onerror",
            "<a",
            "javascript",
        ):
            self.assertNotIn(forbidden, cleaned)

    def test_the_allowed_tags_survive(self):
        self.assertEqual(
            clean_html("<p>a<sub>2</sub><br><em>b</em></p><ul><li>c</li></ul>"),
            "<p>a<sub>2</sub><br><em>b</em></p><ul><li>c</li></ul>",
        )


class ConditionsTests(SimpleTestCase):
    def test_typed_statements_come_first_by_label_and_untyped_last(self):
        tiles = [
            statement("<p>100 ms</p>"),
            statement("<p>50 kV</p>", "instrument settings"),
            statement("<p>spot 260 µm</p>", "configuration"),
        ]

        found = conditions_of(tiles, TYPE, CONTENT, "en")

        self.assertEqual(
            [c["type"]["label"]["value"] if c["type"] else None for c in found],
            ["configuration", "instrument settings", None],
        )
        self.assertEqual(found[2]["html"], "<p>100 ms</p>")

    def test_an_empty_statement_is_skipped_and_the_language_falls_back(self):
        tiles = [statement("<p> </p>"), statement("<p>mesure</p>", lang="fr")]

        found = conditions_of(tiles, TYPE, CONTENT, "en")

        self.assertEqual(found, [{"type": None, "html": "<p>mesure</p>", "lang": "fr"}])
