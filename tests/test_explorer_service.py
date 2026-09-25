"""Rows, facets and free text of the Explorer's search, on real tiles.

Usage:
    python manage.py test tests.test_explorer_service --settings="tests.test_settings"
"""

from django.http import QueryDict
from django.test import SimpleTestCase

from arches_controlled_lists.models import List, ListItem, ListItemValue

from manuspectrum.views.explorer_service import (
    ancestor_terms,
    corpus_rows,
    fold,
    row_filter,
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


class RowFilterTests(SimpleTestCase):
    def rows(self):
        return [
            {
                "technique": {"uri": "t:xrf"},
                "component": None,
                "year": 2023,
                "projects": [],
                "operators": [],
                "materials": [],
                "colours": [],
                "elements": [],
                "layers": [],
                "text": "ms 59 xrf",
            },
            {
                "technique": {"uri": "t:fors"},
                "component": None,
                "year": 2024,
                "projects": [],
                "operators": [],
                "materials": [],
                "colours": [],
                "elements": [],
                "layers": [],
                "text": "ms 59 fors",
            },
        ]

    def test_keeps_rows_carrying_one_of_the_selected_values(self):
        keep, *_ = row_filter(self.rows(), QueryDict("technique=t:xrf"))
        self.assertEqual([keep(r) for r in self.rows()], [True, False])

    def test_ignores_a_selected_value_outside_the_rows(self):
        keep, *_ = row_filter(self.rows(), QueryDict("technique=t:unknown"))
        self.assertEqual([keep(r) for r in self.rows()], [True, True])

    def test_matches_the_folded_text(self):
        keep, *_ = row_filter(self.rows(), QueryDict("q=FORS"))
        self.assertEqual([keep(r) for r in self.rows()], [False, True])


class ScopedSearchTests(ServiceCase):
    facet = FacetTests.facet

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tile(
            cls.analyses["embargoed"],
            "analysis_technique_used",
            cls.reference_value(XRF, "Portable XRF"),
        )

    def scoped(self, resource, extra=""):
        return search_payload(
            self.query(f"document={resource}{extra}"), self.anonymous, "en"
        )

    def test_scoped_facets_count_only_the_rows_of_the_document(self):
        payload = self.scoped(self.documents["embargoed"].pk)

        techniques = self.facet(payload, "technique")
        self.assertEqual({k: v["count"] for k, v in techniques.items()}, {XRF: 1})
        self.assertNotIn("project", [f["key"] for f in payload["facets"]])
        self.assertEqual(payload["total"], 1)

    def test_a_selected_value_absent_from_the_document_stays_listed_at_zero(self):
        payload = self.scoped(self.documents["embargoed"].pk, f"&technique={FORS}")

        techniques = self.facet(payload, "technique")
        self.assertEqual(techniques[FORS]["count"], 0)
        self.assertTrue(techniques[FORS]["selected"])
        self.assertEqual(payload["results"], [])

    def test_scoped_results_are_the_analyses_of_the_document_in_any_grain(self):
        payload = self.scoped(self.documents["open"].pk, "&grain=documents")

        self.assertEqual({r["type"] for r in payload["results"]}, {"analysis"})
        self.assertEqual(
            {r["id"] for r in payload["results"]},
            {str(self.analyses[k].pk) for k in ("open", "on_document", "draft")},
        )

    def test_an_invisible_unknown_or_malformed_document_gives_an_empty_scope(self):
        self.embargo(self.documents["embargoed"])

        for resource in (
            self.documents["embargoed"].pk,
            "00000000-0000-4000-8000-00000000000a",
            "not-a-uuid",
        ):
            payload = self.scoped(resource)
            self.assertEqual(
                (payload["total"], payload["facets"], payload["results"]),
                (0, [], []),
                resource,
            )
            self.assertNotIn("Ms 211", str(payload))


class PageSizeTests(ServiceCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for n in range(11):
            cls.new_resource("document", f"Ms {300 + n}")

    def page(self, extra=""):
        return search_payload(
            self.query(f"grain=documents&empty=1{extra}"), self.anonymous, "en"
        )

    def test_the_page_size_is_ten_by_default_and_follows_an_allowed_size(self):
        self.assertEqual(self.page()["page"]["size"], 10)
        self.assertEqual(self.page()["page"]["count"], 10)
        self.assertEqual(
            self.page("&size=25")["page"], {"number": 1, "size": 25, "count": 13}
        )

    def test_a_size_outside_the_allowed_ones_gives_the_default(self):
        for size in ("7", "1000", "x"):
            self.assertEqual(self.page(f"&size={size}")["page"]["size"], 10, size)

    def test_a_page_beyond_the_last_gives_an_empty_chunk(self):
        payload = self.page("&size=10&page=99")

        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["total"], 13)
        self.assertEqual(payload["page"], {"number": 99, "size": 10, "count": 0})


class DocumentsWithoutAnalysesTests(ServiceCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.bare = cls.new_resource("document", "Ms 300 sans analyse")

    def search_documents(self, extra=""):
        return search_payload(
            self.query(f"grain=documents{extra}"), self.anonymous, "en"
        )

    def test_a_document_without_analyses_is_left_out_and_counted_by_default(self):
        payload = self.search_documents()

        self.assertNotIn(str(self.bare.pk), [r["id"] for r in payload["results"]])
        self.assertEqual(payload["withoutAnalyses"], 1)

    def test_empty_includes_the_document_without_analyses(self):
        payload = self.search_documents("&empty=1")

        hits = {r["id"]: r for r in payload["results"]}
        self.assertEqual(hits[str(self.bare.pk)]["analysisCount"], 0)
        self.assertEqual(payload["withoutAnalyses"], 1)

    def test_the_count_follows_the_free_text_and_the_facet_filters(self):
        self.assertEqual(self.search_documents("&q=sans+analyse")["withoutAnalyses"], 1)
        self.assertEqual(self.search_documents("&q=ms+59")["withoutAnalyses"], 0)
        self.assertEqual(
            self.search_documents(f"&technique={XRF}")["withoutAnalyses"], 0
        )

    def test_the_old_only_with_analyses_parameter_is_ignored(self):
        self.assertEqual(
            self.search_documents("&onlyWithAnalyses=false"), self.search_documents()
        )

    def test_the_analyses_grain_counts_no_document(self):
        payload = search_payload(self.query(), self.anonymous, "en")

        self.assertEqual(payload["withoutAnalyses"], 0)


class DocumentHitTests(ServiceCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        document = cls.documents["open"]
        cls.tile_values(
            document,
            "document",
            value_of_identifier=cls.string_value("https://arca.example/ark:/1"),
            type_of_identifier=cls.reference_value("http://vocab/ark", "ARK"),
        )
        cls.tile_values(
            document,
            "document",
            value_of_identifier=cls.string_value("Latin 8055"),
            type_of_identifier=cls.reference_value(
                "http://vocab/shelfmark", "Shelfmark", "Cote"
            ),
        )
        cls.tile(document, "current_owner", cls.refs(cls.operator))
        cls.tile_values(
            document,
            "document",
            date_start_of_production_time="1301-01-01",
            date_end_of_production_time="1400-12-31",
        )
        cls.tile(
            document,
            "content_of_statement",
            cls.string_value(
                "<p>Psalter <em>with</em> &amp; gilded initials.</p>"
                + "<p>"
                + " ".join(["folio"] * 60)
                + "</p>",
                "<p>Psautier</p>",
            ),
        )
        cls.tile(
            document,
            "type",
            cls.reference_value("http://vocab/ms", "Manuscript", "Manuscrit"),
        )

    def hit(self, language="en"):
        payload = search_payload(
            self.query("grain=documents"), self.anonymous, language
        )
        return next(
            r for r in payload["results"] if r["id"] == str(self.documents["open"].pk)
        )

    def test_a_document_hit_carries_its_shelfmark_holding_dates_and_type(self):
        hit = self.hit()

        self.assertEqual(hit["shelfmark"], {"value": "Latin 8055", "lang": "en"})
        self.assertEqual(hit["holding"]["value"], "Robinet, L.")
        self.assertEqual(hit["dates"], {"start": "1301-01-01", "end": "1400-12-31"})
        self.assertEqual(hit["documentType"], {"value": "Manuscript", "lang": "en"})
        self.assertEqual(self.hit("fr")["documentType"]["value"], "Manuscrit")

    def test_the_description_is_plain_text_cut_on_a_word(self):
        description = self.hit()["description"]

        self.assertTrue(
            description["value"].startswith("Psalter with & gilded initials. folio")
        )
        self.assertNotIn("<", description["value"])
        self.assertLessEqual(len(description["value"]), 221)
        self.assertTrue(description["value"].endswith(" folio…"))
        self.assertEqual(
            self.hit("fr")["description"], {"value": "Psautier", "lang": "fr"}
        )

    def test_the_first_identifier_is_the_shelfmark_when_none_is_typed_so(self):
        other = self.documents["embargoed"]
        self.tile(other, "value_of_identifier", self.string_value("MS 211 bis"))
        payload = search_payload(self.query("grain=documents"), self.anonymous, "en")

        hit = next(r for r in payload["results"] if r["id"] == str(other.pk))
        self.assertEqual(hit["shelfmark"]["value"], "MS 211 bis")
        self.assertIsNone(hit["dates"])
        self.assertIsNone(hit["description"])
        self.assertIsNone(hit["documentType"])
        self.assertIsNone(hit["holding"])

    def test_an_identifier_that_is_a_link_is_never_the_shelfmark(self):
        other = self.documents["embargoed"]
        for link in ("https://gallica.example/ark:/12148/b1", "ark:/12148/b2"):
            self.tile(other, "value_of_identifier", self.string_value(link))
        payload = search_payload(self.query("grain=documents"), self.anonymous, "en")
        hit = next(r for r in payload["results"] if r["id"] == str(other.pk))
        self.assertIsNone(hit["shelfmark"])

        self.tile(other, "value_of_identifier", self.string_value("MS 12"))
        payload = search_payload(self.query("grain=documents"), self.anonymous, "en")
        hit = next(r for r in payload["results"] if r["id"] == str(other.pk))
        self.assertEqual(hit["shelfmark"]["value"], "MS 12")
