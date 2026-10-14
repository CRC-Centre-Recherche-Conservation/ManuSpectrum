"""The thesaurus closure of the Explorer's term facets.

Usage:
    python manage.py test tests.test_explorer_terms --settings="tests.test_settings"
"""

from unittest.mock import patch

from arches_controlled_lists.models import List, ListItem, ListItemValue
from django.test import SimpleTestCase, TestCase

from manuspectrum.views.explorer import terms
from manuspectrum.views.explorer.terms import TERM_DEPTH, facet_list, term_closures

V = "http://vocab/"


def item(vocab, uri, order, parent=None, **labels):
    found = ListItem.objects.create(
        list=vocab, uri=V + uri, sortorder=order, parent=parent
    )
    for key, value in labels.items():
        valuetype, language = key.split("_")
        ListItemValue.objects.create(
            list_item=found,
            valuetype_id="prefLabel" if valuetype == "pref" else "altLabel",
            language_id=language,
            value=value,
        )
    return found


class TermClosureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.materials = List.objects.create(name="materials")
        pigment = item(
            cls.materials,
            "blue-pigment",
            0,
            pref_en="Blue pigment",
            pref_fr="Pigment bleu",
            alt_en="Azure",
        )
        mineral = item(cls.materials, "mineral", 1, pref_en="Mineral origin")
        item(cls.materials, "azurite", 0, pigment, pref_en="Azurite")
        item(cls.materials, "azurite", 0, mineral, pref_en="Azurite")
        cls.layers = List.objects.create(name="layers")
        ground = item(cls.layers, "layer-ground", 0, pref_en="Ground layers")
        item(cls.layers, "shared", 0, ground)
        cls.types = List.objects.create(name="types")
        support = item(cls.types, "support", 0, pref_en="Support")
        item(cls.types, "shared", 0, support)

    def lists(self):
        return {
            "material": str(self.materials.pk),
            "layer": str(self.layers.pk),
            "partType": str(self.types.pk),
            "technique": None,
        }

    def test_a_term_reaches_the_ancestors_of_every_occurrence(self):
        closure = term_closures(self.lists(), {"material": {V + "azurite"}}, "en")[
            "material"
        ]
        self.assertEqual(
            closure.reach[V + "azurite"],
            {V + "azurite", V + "blue-pigment", V + "mineral"},
        )
        self.assertEqual(
            closure.parents[V + "azurite"], (V + "blue-pigment", V + "mineral")
        )
        self.assertEqual(closure.parents[V + "mineral"], ())

    def test_one_uri_in_two_lists_is_closed_in_each_list_apart(self):
        found = term_closures(
            self.lists(), {"layer": {V + "shared"}, "partType": {V + "shared"}}, "en"
        )
        self.assertEqual(
            found["layer"].reach[V + "shared"], {V + "shared", V + "layer-ground"}
        )
        self.assertEqual(
            found["partType"].reach[V + "shared"], {V + "shared", V + "support"}
        )

    def test_a_uri_outside_its_list_and_a_key_without_list_close_on_themselves(self):
        found = term_closures(
            self.lists(), {"material": {V + "unknown"}, "technique": {V + "xrf"}}, "en"
        )
        self.assertEqual(found["material"].closed({V + "unknown"}), {V + "unknown"})
        self.assertEqual(found["technique"].closed({V + "xrf"}), {V + "xrf"})

    def test_labels_follow_the_language_then_english_and_terms_hold_every_label_folded(
        self,
    ):
        fr = term_closures(self.lists(), {"material": {V + "azurite"}}, "fr")[
            "material"
        ]
        self.assertEqual(
            fr.labels[V + "blue-pigment"], {"value": "Pigment bleu", "lang": "fr"}
        )
        self.assertEqual(
            fr.labels[V + "mineral"], {"value": "Mineral origin", "lang": "en"}
        )
        self.assertEqual(
            fr.terms[V + "blue-pigment"], {"blue pigment", "pigment bleu", "azure"}
        )

    def test_a_cycle_is_walked_once(self):
        vocab = List.objects.create(name="cyclic")
        a_root = item(vocab, "a", 0)
        b_root = item(vocab, "b", 1)
        item(vocab, "a", 0, b_root)
        item(vocab, "b", 0, a_root)
        closure = term_closures(
            {"technique": str(vocab.pk)}, {"technique": {V + "a"}}, "en"
        )["technique"]
        self.assertEqual(closure.reach[V + "a"], {V + "a", V + "b"})

    def test_the_walk_stops_at_the_depth_bound(self):
        vocab = List.objects.create(name="deep")
        parent = None
        for level in range(TERM_DEPTH + 3):
            parent = item(vocab, f"level-{level}", 0, parent)
        closure = term_closures(
            {"technique": str(vocab.pk)}, {"technique": {parent.uri}}, "en"
        )["technique"]
        self.assertEqual(len(closure.reach[parent.uri]), TERM_DEPTH + 1)

    def test_four_lists_are_read_in_two_queries_and_nothing_used_reads_nothing(self):
        with self.assertNumQueries(2):
            term_closures(
                self.lists(),
                {
                    "material": {V + "azurite"},
                    "layer": {V + "shared"},
                    "partType": {V + "shared"},
                },
                "en",
            )
        with self.assertNumQueries(0):
            term_closures(self.lists(), {"material": set()}, "en")


class FacetListTests(SimpleTestCase):
    def test_the_list_is_the_controlled_list_of_the_facet_node(self):
        index = type("Index", (), {"lists": {"identified_material": "list-1"}})()
        with patch.object(terms.GraphIndex, "for_slug", return_value=index) as for_slug:
            self.assertEqual(facet_list("material"), "list-1")
        for_slug.assert_called_once_with("characterization")

    def test_no_index_is_no_list(self):
        with patch.object(terms.GraphIndex, "for_slug", return_value=None):
            self.assertIsNone(facet_list("technique"))
