"""Rows, facets and free text of the Explorer's search, on real tiles.

Usage:
    python manage.py test tests.test_explorer_service --settings="tests.test_settings"
"""

from django.http import QueryDict

from arches_controlled_lists.models import List, ListItem, ListItemValue

from manuspectrum.views.explorer_service import (
    ancestor_terms,
    corpus_rows,
    fold,
    search_payload,
)
from tests.explorer_fixtures import ExplorerCase

XRF, FORS, AZURITE, BLUE = (
    "http://vocab/pxrf",
    "http://vocab/fors",
    "http://vocab/azurite",
    "http://vocab/blue",
)


class ServiceCase(ExplorerCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        tile, ref = cls.tile, cls.reference_value
        tile(
            cls.analyses["open"],
            "analysis_technique_used",
            ref(XRF, "Portable XRF", "XRF portable", alt="pXRF"),
        )
        tile(
            cls.analyses["on_document"],
            "analysis_technique_used",
            ref(FORS, "Reflectance (FORS)"),
        )
        tile(cls.analyses["open"], "performed_by_actor", cls.refs(cls.operator))
        tile(cls.analyses["open"], "analysis_start_date", "2024-05-14")
        tile(
            cls.characterization,
            "identified_material",
            ref(AZURITE, "Azurite", "Azurite"),
        )
        tile(cls.characterization, "color_aspect", ref(BLUE, "Blue", "Bleu"))

    def query(self, text=""):
        return QueryDict(text)


class RowsTests(ServiceCase):
    def test_rows_hold_the_visible_analyses_with_their_chain(self):
        self.embargo(self.documents["embargoed"])
        rows = {r["id"]: r for r in corpus_rows(self.anonymous, "en")}

        self.assertEqual(
            set(rows),
            {
                str(self.analyses["open"].pk),
                str(self.analyses["on_document"].pk),
                str(self.analyses["draft"].pk),
            },
        )
        self.assertIs(rows[str(self.analyses["draft"].pk)]["unpublished"], True)
        self.assertIs(rows[str(self.analyses["open"].pk)]["unpublished"], False)
        opened = rows[str(self.analyses["open"].pk)]
        self.assertEqual(opened["document"], str(self.documents["open"].pk))
        self.assertEqual(opened["component"], str(self.components["open"].pk))
        self.assertEqual(opened["year"], 2024)
        self.assertEqual([m["uri"] for m in opened["materials"]], [AZURITE])

    def test_a_dangling_component_link_is_ignored_in_rows(self):
        self.tile(
            self.analyses["on_document"],
            "component_observed",
            [{"resourceId": "00000000-0000-4000-8000-000000000001"}],
        )

        rows = {r["id"]: r for r in corpus_rows(self.anonymous, "en")}

        self.assertEqual(
            rows[str(self.analyses["on_document"].pk)]["document"],
            str(self.documents["open"].pk),
        )

    def test_fold_removes_accents_and_case(self):
        self.assertEqual(fold("Enluminée ÉTÉ"), "enluminee ete")


class FacetTests(ServiceCase):
    def facet(self, payload, key):
        return {
            v["id"]: v
            for f in payload["facets"]
            if f["key"] == key
            for v in f["values"]
        }

    def test_a_technique_filter_keeps_its_own_facet_open(self):
        payload = search_payload(self.query(f"technique={XRF}"), self.anonymous, "en")

        self.assertEqual(
            [r["id"] for r in payload["results"]], [str(self.analyses["open"].pk)]
        )
        techniques = self.facet(payload, "technique")
        self.assertEqual((techniques[XRF]["count"], techniques[FORS]["count"]), (1, 1))
        self.assertTrue(techniques[XRF]["selected"])

    def test_filters_of_two_facets_combine_with_and(self):
        payload = search_payload(
            self.query(f"technique={FORS}&material={AZURITE}"), self.anonymous, "en"
        )

        self.assertEqual(
            [r["id"] for r in payload["results"]],
            [str(self.analyses["on_document"].pk)],
        )

    def test_a_facet_with_no_value_on_the_visible_set_is_absent(self):
        payload = search_payload(self.query(), self.anonymous, "en")

        self.assertNotIn("layer", [f["key"] for f in payload["facets"]])

    def test_free_text_finds_an_alt_label_and_a_material(self):
        by_alt = search_payload(self.query("q=pxrf"), self.anonymous, "en")
        by_material = search_payload(self.query("q=AZURITE"), self.anonymous, "en")

        self.assertEqual(
            [r["id"] for r in by_alt["results"]], [str(self.analyses["open"].pk)]
        )
        self.assertEqual(len(by_material["results"]), 2)

    def test_the_documents_grain_counts_matching_analyses(self):
        self.embargo(self.documents["embargoed"])
        payload = search_payload(self.query("grain=documents"), self.anonymous, "en")

        self.assertEqual(
            [(r["id"], r["analysisCount"]) for r in payload["results"]],
            [(str(self.documents["open"].pk), 3)],
        )


class AncestorTermsTests(ServiceCase):
    def test_a_parent_term_label_is_found_for_its_child(self):
        vocab = List.objects.create(name="techniques")
        parent = ListItem.objects.create(
            list=vocab, uri="http://vocab/xrf-family", sortorder=0
        )
        child = ListItem.objects.create(list=vocab, uri=XRF, sortorder=1, parent=parent)
        ListItemValue.objects.create(
            list_item=parent, valuetype_id="prefLabel", language_id="en", value="XRF"
        )

        self.assertIn("XRF", ancestor_terms([str(child.pk)])[str(child.pk)])
