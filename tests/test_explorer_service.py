"""Rows, facets and free text of the Explorer's search, on real tiles.

Usage:
    python manage.py test tests.test_explorer_service --settings="tests.test_settings"
"""

from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid4, uuid5

from django.core.cache import cache
from django.db import connection
from django.http import QueryDict
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from arches.app.models.models import IIIFManifest, Node, TileModel

from arches_controlled_lists.models import List, ListItem, ListItemValue

from manuspectrum.utils.public_visibility import visible_set
from manuspectrum.views.explorer import service as explorer_service
from manuspectrum.views.explorer.service import (
    TECHNIQUE_PALETTE,
    analysis_payload,
    ancestor_terms,
    build_bundle,
    cited_analysis,
    corpus_rows,
    document_payload,
    place_closure,
    family_colours,
    fold,
    manifest_json,
    facet_payload,
    match_payload,
    meets,
    row_filter,
    search_payload,
)
from tests.explorer_fixtures import DRAFT, ExplorerCase

INHA = "https://thesaurus.inha.fr/thesaurus/resource/ark:/54721/"
INHA_BLUE = (
    "https://thesaurus.inha.fr/thesaurus/resource/ark:/54721/"
    "d549884f-ed29-4a28-87c8-07311d9a14ad"
)
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

    def test_a_document_deleted_while_the_bundle_builds_is_left_out(self):
        gone = str(self.documents["open"].pk)
        real = explorer_service.names

        def names_without_the_deleted(ids, language, user):
            return {k: v for k, v in real(ids, language, user).items() if k != gone}

        visible = visible_set(self.anonymous)
        with patch.object(explorer_service, "names", names_without_the_deleted):
            bundle = build_bundle(self.anonymous, "en", visible)

        self.assertIn(gone, visible.documents)
        self.assertNotIn(gone, bundle.documents)
        self.assertNotIn(gone, bundle.by_document)
        self.assertFalse([r for r in bundle.rows if r["document"] == gone])

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
                "partTypes": [],
                "partColours": [],
                "characterizations": [],
                "places": [],
                "periods": {"production": None, "modification": None},
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
                "partTypes": [],
                "partColours": [],
                "characterizations": [],
                "places": [],
                "periods": {"production": None, "modification": None},
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

    def test_meets_holds_each_wanted_key_and_nothing_else(self):
        values = {"material": {"a"}, "colour": {"x", "y"}, "colourPart": set()}

        self.assertTrue(meets(values, []))
        self.assertTrue(meets(values, [("colour", {"y", "z"})]))
        self.assertTrue(meets(values, [("material", {"a"}), ("colour", {"x"})]))
        self.assertFalse(meets(values, [("colourPart", {"x"})]))
        self.assertFalse(meets(values, [("material", {"b"}), ("colour", {"x"})]))

    def test_a_row_without_characterization_entries_reads_no_colour_scope(self):
        keep, *_ = row_filter(self.rows(), QueryDict("colourScope=part"))
        self.assertEqual([keep(r) for r in self.rows()], [True, True])


class DocumentMatchTests(ServiceCase):
    facet = FacetTests.facet

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tile(
            cls.analyses["embargoed"],
            "analysis_technique_used",
            cls.reference_value(XRF, "Portable XRF"),
        )

    def match(self, resource, extra=""):
        return match_payload(resource, self.query(extra), self.anonymous, "en")

    def test_facets_count_only_the_analyses_of_the_document(self):
        payload = self.match(self.documents["embargoed"].pk)

        techniques = self.facet(payload, "technique")
        self.assertEqual({k: v["count"] for k, v in techniques.items()}, {XRF: 1})
        self.assertNotIn("project", [f["key"] for f in payload["facets"]])
        self.assertEqual(payload["total"], 1)

    def test_a_selected_value_absent_from_the_document_stays_listed_at_zero(self):
        payload = self.match(self.documents["embargoed"].pk, f"technique={FORS}")

        techniques = self.facet(payload, "technique")
        self.assertEqual(techniques[FORS]["count"], 0)
        self.assertEqual(payload["kept"]["analyses"], [])
        self.assertEqual(payload["total"], 0)

    def test_without_an_active_filter_every_analysis_is_kept_as_null(self):
        for text in (
            "",
            "grain=documents&page=3",
            "q=",
            "technique=http://vocab/nowhere",
        ):
            payload = self.match(self.documents["open"].pk, text)

            self.assertIsNone(payload["kept"]["analyses"], text or "none")
            self.assertEqual(payload["total"], 3, text or "none")

    def test_an_active_filter_lists_the_analyses_it_keeps(self):
        payload = self.match(self.documents["open"].pk, f"technique={XRF}")

        self.assertEqual(payload["kept"]["analyses"], [str(self.analyses["open"].pk)])
        self.assertEqual(payload["total"], 1)

    def test_the_match_and_the_search_keep_the_same_analyses(self):
        for text in (f"technique={XRF}", "q=azurite", f"material={AZURITE}"):
            found = {
                r["id"]
                for r in search_payload(
                    self.query(f"{text}&size=50"), self.anonymous, "en"
                )["results"]
                if r["document"]["id"] == str(self.documents["open"].pk)
            }
            kept = self.match(self.documents["open"].pk, text)["kept"]["analyses"]
            self.assertEqual(set(kept), found, text)

    def test_an_identified_material_is_kept_by_its_own_values_only(self):
        mine = str(self.characterization.pk)

        for text, kept in (
            ("", True),
            (f"material={AZURITE}", True),
            ("material=http://vocab/nowhere", True),
            (f"colour={BLUE}&material={AZURITE}", True),
            (f"technique={FORS}", True),
            ("q=nothing-carries-this", True),
        ):
            payload = self.match(self.documents["open"].pk, text)
            self.assertIs(
                mine in payload["kept"]["characterizations"], kept, text or "none"
            )

    def test_an_invisible_unknown_or_malformed_document_has_no_match(self):
        self.embargo(self.documents["embargoed"])

        for resource in (
            self.documents["embargoed"].pk,
            "00000000-0000-4000-8000-00000000000a",
            "not-a-uuid",
        ):
            self.assertIsNone(self.match(resource), resource)


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
        self.assertEqual(
            hit["dates"], {"start": "1401-01", "end": "1500-12", "approximate": True}
        )
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


LEAD_WHITE, RED, LAPIS = (
    "http://vocab/lead-white",
    "http://vocab/red",
    "http://vocab/lapis",
)
ILLUMINATION, INITIAL, PART_BLUE = (
    "http://vocab/illumination",
    "http://vocab/initial",
    "http://vocab/part-blue",
)


class LevelCase(ServiceCase):
    """The open analysis is cited by « Azurite, blue » and by « Lead white, red »; its component is a blue illumination."""

    facet = FacetTests.facet

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        ref = cls.reference_value
        cls.second = cls.new_resource("characterization", "Lead white, red ground")
        cls.tile(cls.second, "object_observed", cls.refs(cls.components["open"]))
        cls.tile(cls.second, "evidence_analyses", cls.refs(cls.analyses["open"]))
        cls.tile(
            cls.second,
            "identified_material",
            ref(LEAD_WHITE, "Lead white", "Blanc de plomb"),
        )
        cls.tile(cls.second, "color_aspect", ref(RED, "Red", "Rouge"))
        cls.tile(
            cls.components["open"],
            "type",
            ref(ILLUMINATION, "Illumination", "Enluminure"),
        )
        cls.tile(
            cls.components["open"], "color_features", ref(PART_BLUE, "Blue", "Bleu")
        )
        cls.tile(
            cls.components["embargoed"], "type", ref(INITIAL, "Initial", "Lettrine")
        )

    def ids(self, payload):
        return {r["id"] for r in payload["results"]}

    def search(self, text):
        return search_payload(self.query(text), self.anonymous, "en")


class CharacterizationLevelTests(LevelCase):
    def test_two_values_of_different_characterizations_do_not_combine(self):
        payload = self.search(f"material={LEAD_WHITE}&colour={BLUE}")

        self.assertEqual(self.ids(payload), set())

    def test_two_values_of_one_characterization_combine(self):
        payload = self.search(f"material={AZURITE}&colour={BLUE}")

        self.assertEqual(
            self.ids(payload),
            {str(self.analyses["open"].pk), str(self.analyses["on_document"].pk)},
        )

    def test_counts_in_the_characterization_group_follow_the_same_characterization(
        self,
    ):
        payload = self.search(f"colour={BLUE}")

        materials = self.facet(payload, "material")
        self.assertEqual(materials[AZURITE]["count"], 2)
        self.assertNotIn(LEAD_WHITE, materials)
        colours = self.facet(payload, "colour")
        self.assertEqual((colours[BLUE]["count"], colours[RED]["count"]), (2, 1))

    def test_the_document_match_follows_the_same_characterization(self):
        rows = {
            r["id"]: r
            for r in corpus_rows(self.anonymous, "en")
            if r["document"] == str(self.documents["open"].pk)
        }
        keep, *_ = row_filter(
            list(rows.values()), self.query(f"material={LEAD_WHITE}&colour={BLUE}")
        )
        self.assertFalse(keep(rows[str(self.analyses["open"].pk)]))
        keep, *_ = row_filter(
            list(rows.values()), self.query(f"material={LEAD_WHITE}&colour={RED}")
        )
        self.assertTrue(keep(rows[str(self.analyses["open"].pk)]))

    def test_the_document_keeps_the_identified_materials_that_carry_the_selection(
        self,
    ):
        azurite, lead_white = str(self.characterization.pk), str(self.second.pk)

        def kept(text):
            return set(
                match_payload(
                    self.documents["open"].pk, self.query(text), self.anonymous, "en"
                )["kept"]["characterizations"]
            )

        self.assertEqual(kept(""), {azurite, lead_white})
        self.assertEqual(kept(f"material={LEAD_WHITE}"), {lead_white})
        self.assertEqual(kept(f"material={AZURITE}&colour={RED}"), set())
        self.assertEqual(kept(f"colour={BLUE}&colour={RED}"), {azurite, lead_white})

    def test_free_text_matches_any_characterization(self):
        payload = self.search("q=lead+white")

        self.assertEqual(self.ids(payload), {str(self.analyses["open"].pk)})


class ColourTests(LevelCase):
    """One colour facet: the part's colour extends to its identified materials, in OR."""

    def kept(self, text):
        return set(
            match_payload(
                self.documents["open"].pk, self.query(text), self.anonymous, "en"
            )["kept"]["characterizations"]
        )

    def test_a_part_colour_alone_keeps_the_row(self):
        payload = self.search(f"colour={PART_BLUE}")

        self.assertEqual(
            self.ids(payload),
            {str(self.analyses["open"].pk), str(self.analyses["draft"].pk)},
        )

    def test_an_identified_colour_alone_keeps_the_row(self):
        payload = self.search(f"colour={RED}")

        self.assertEqual(self.ids(payload), {str(self.analyses["open"].pk)})

    def test_colour_and_material_hold_on_the_same_identified_material_with_the_part_colour_extended(
        self,
    ):
        self.assertEqual(
            self.ids(self.search(f"material={LEAD_WHITE}&colour={BLUE}")), set()
        )
        self.tile(
            self.components["open"],
            "color_features",
            self.reference_value(BLUE, "Blue", "Bleu"),
        )

        payload = self.search(f"material={LEAD_WHITE}&colour={BLUE}")

        self.assertEqual(self.ids(payload), {str(self.analyses["open"].pk)})

    def test_colour_scope_part_reads_the_component_only(self):
        self.assertEqual(self.ids(self.search(f"colour={RED}&colourScope=part")), set())
        self.assertEqual(
            self.ids(self.search(f"colour={BLUE}&colourScope=part")), set()
        )
        payload = self.search(
            f"colour={PART_BLUE}&material={LEAD_WHITE}&colourScope=part"
        )

        self.assertEqual(self.ids(payload), {str(self.analyses["open"].pk)})
        self.assertEqual(
            self.ids(
                self.search(f"colour={PART_BLUE}&material={AZURITE}&colourScope=part")
            ),
            {str(self.analyses["open"].pk)},
        )

    def test_colour_scope_material_reads_color_aspect_only(self):
        self.assertEqual(
            self.ids(self.search(f"colour={PART_BLUE}&colourScope=material")), set()
        )
        self.assertEqual(
            self.ids(self.search(f"colour={RED}&colourScope=material")),
            {str(self.analyses["open"].pk)},
        )
        self.assertEqual(
            self.ids(self.search(f"colour={BLUE}&colourScope=material")),
            {str(self.analyses["open"].pk), str(self.analyses["on_document"].pk)},
        )

    def test_an_unknown_colour_scope_reads_all(self):
        self.assertEqual(
            self.ids(self.search(f"colour={PART_BLUE}&colourScope=everything")),
            self.ids(self.search(f"colour={PART_BLUE}")),
        )

    def test_counts_of_material_under_a_colour_follow_the_scope(self):
        def counts(text):
            return {
                uri: value["count"]
                for uri, value in self.facet(self.search(text), "material").items()
            }

        self.assertEqual(counts(f"colour={BLUE}"), {AZURITE: 2})
        self.assertEqual(counts(f"colour={PART_BLUE}"), {AZURITE: 1, LEAD_WHITE: 1})
        self.assertEqual(counts(f"colour={BLUE}&colourScope=part"), {})

    def test_counts_of_colour_are_per_scope_values_of_the_kept_entries(self):
        colours = self.facet(self.search(""), "colour")

        self.assertEqual(
            {uri: colours[uri]["count"] for uri in (BLUE, RED, PART_BLUE)},
            {BLUE: 2, RED: 1, PART_BLUE: 2},
        )
        part = self.facet(self.search("colourScope=part"), "colour")
        self.assertEqual(
            {uri: part[uri]["count"] for uri in (BLUE, RED, PART_BLUE)},
            {BLUE: 0, RED: 0, PART_BLUE: 2},
        )

    def test_kept_characterizations_extend_the_part_colour(self):
        azurite, lead_white = str(self.characterization.pk), str(self.second.pk)

        self.assertEqual(self.kept(f"colour={PART_BLUE}"), {azurite, lead_white})
        self.assertEqual(self.kept(f"colour={PART_BLUE}&colourScope=material"), set())
        self.assertEqual(self.kept(f"colour={RED}&colourScope=part"), set())
        self.assertEqual(self.kept(f"colour={PART_BLUE}&material={AZURITE}"), {azurite})


class ColourListTests(LevelCase):
    """The colour facet lists every item of the color_aspect list, in a fixed order."""

    WHITE = INHA + "2259f089-935b-46ec-af76-cdb5156ee311"
    GOLD = INHA + "c1e1850f-9eb1-48f4-b8b8-6154a3a1623c"
    ODD = "http://vocab/odd"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        controlled = List.objects.create(name="colours")
        for order, (uri, en, fr) in enumerate(
            (
                (cls.ODD, "Odd", "Bizarre"),
                (INHA_BLUE, "Blue", "Bleu"),
                (cls.GOLD, "Gold", "Doré"),
                (cls.WHITE, "White", "Blanc"),
            )
        ):
            item = ListItem.objects.create(list=controlled, uri=uri, sortorder=order)
            for language, value in (("en", en), ("fr", fr)):
                ListItemValue.objects.create(
                    list_item=item,
                    valuetype_id="prefLabel",
                    language_id=language,
                    value=value,
                )
        Node.objects.filter(
            pk=cls.nodes[("characterization", "color_aspect")].pk
        ).update(config={"controlledList": str(controlled.pk)})

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

    def order(self, language):
        payload = search_payload(self.query(), self.anonymous, language)
        return [
            v["id"]
            for f in payload["facets"]
            if f["key"] == "colour"
            for v in f["values"]
        ]

    def test_the_colour_facet_lists_every_item_in_swatch_order_with_zero_counts(self):
        payload = search_payload(self.query(), self.anonymous, "en")
        colour = self.facet(payload, "colour")

        expected = [self.WHITE, INHA_BLUE, self.GOLD, self.ODD, BLUE, PART_BLUE, RED]
        self.assertEqual(self.order("en"), expected)
        self.assertEqual(self.order("fr"), expected)
        self.assertEqual(
            [colour[u]["count"] for u in (self.WHITE, INHA_BLUE, self.GOLD, self.ODD)],
            [0, 0, 0, 0],
        )
        self.assertEqual(colour[self.WHITE]["label"]["value"], "White")
        self.assertEqual(colour[self.WHITE]["swatch"], "#f5f0e4")
        self.assertEqual(colour[INHA_BLUE]["swatch"], "#2f55a4")
        self.assertIsNone(colour[self.ODD]["swatch"])

    def test_a_selection_keeps_every_item_listed(self):
        payload = search_payload(self.query(f"colour={RED}"), self.anonymous, "en")

        self.assertEqual(
            {
                v["id"]
                for f in payload["facets"]
                if f["key"] == "colour"
                for v in f["values"]
            },
            {self.WHITE, INHA_BLUE, self.GOLD, self.ODD, BLUE, PART_BLUE, RED},
        )

    def test_the_facet_route_lists_the_same_items_and_a_document_lists_what_it_carries(
        self,
    ):
        from manuspectrum.views.explorer.service import facet_payload

        whole = facet_payload("colour", self.query(), self.anonymous, "en")
        document = facet_payload(
            "colour",
            self.query(f"document={self.documents['open'].pk}"),
            self.anonymous,
            "en",
        )

        self.assertEqual(len(whole["values"]), 7)
        self.assertEqual([v["id"] for v in document["values"]], [BLUE, PART_BLUE, RED])


class PartLevelTests(LevelCase):
    def test_part_type_and_part_colour_filter_the_analyses_of_the_part(self):
        payload = self.search(f"partType={ILLUMINATION}&partColour={PART_BLUE}")

        self.assertEqual(
            self.ids(payload),
            {str(self.analyses["open"].pk), str(self.analyses["draft"].pk)},
        )
        types = self.facet(payload, "partType")
        self.assertEqual(types[ILLUMINATION]["count"], 2)
        self.assertEqual(types[ILLUMINATION]["label"]["value"], "Illumination")

    def test_part_colour_and_identified_colour_are_one_facet(self):
        payload = self.search(f"partColour={PART_BLUE}&colour={RED}")

        self.assertEqual(
            self.ids(payload),
            {str(self.analyses["open"].pk), str(self.analyses["draft"].pk)},
        )

    def test_each_facet_names_its_group_in_rail_order(self):
        payload = self.search("")

        self.assertEqual(
            [(f["key"], f["group"]) for f in payload["facets"]],
            [
                ("place", "document"),
                ("partType", "part"),
                ("part", "part"),
                ("project", "analysis"),
                ("technique", "analysis"),
                ("operator", "analysis"),
                ("year", "analysis"),
                ("material", "characterization"),
                ("colour", "characterization"),
            ],
        )

    def test_a_colour_concept_has_one_swatch_in_every_language(self):
        gilded = "http://vocab/gilded"
        self.tile(
            self.characterization,
            "color_aspect",
            self.reference_value(gilded, "Gilded", "Doré"),
        )
        self.tile(
            self.characterization,
            "color_aspect",
            self.reference_value(INHA_BLUE, "Bleu", "Bleu"),
        )
        self.tile(
            self.components["open"],
            "color_features",
            self.reference_value(INHA_BLUE, "Bleu", "Bleu"),
        )
        swatches = {
            language: {
                key: {v: facet[v]["swatch"] for v in facet}
                for key in ("colour", "material")
                for facet in [
                    self.facet(
                        search_payload(self.query(), self.anonymous, language), key
                    )
                ]
            }
            for language in ("en", "fr")
        }

        self.assertEqual(swatches["en"], swatches["fr"])
        self.assertEqual(swatches["en"]["colour"][gilded], "goldenrod")
        self.assertEqual(swatches["en"]["colour"][BLUE], "royalblue")
        self.assertEqual(swatches["en"]["colour"][INHA_BLUE], "#2f55a4")
        self.assertEqual(swatches["en"]["colour"][PART_BLUE], "royalblue")
        self.assertEqual(set(swatches["en"]["material"].values()), {None})

    def test_the_french_label_of_a_part_type(self):
        payload = search_payload(self.query(), self.anonymous, "fr")

        self.assertEqual(
            self.facet(payload, "partType")[ILLUMINATION]["label"]["value"],
            "Enluminure",
        )


XRF_FAMILY, MICRO_XRF, RAMAN = (
    "http://vocab/xrf",
    "http://vocab/micro-xrf",
    "http://vocab/raman",
)


class TechniqueMarkTests(ServiceCase):
    """pXRF and µXRF are children of XRF in the thesaurus; Raman has no parent used in the corpus."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        vocab = List.objects.create(name="techniques")
        items = {}
        for order, uri in enumerate((XRF_FAMILY, XRF, MICRO_XRF, RAMAN, FORS)):
            items[uri] = ListItem.objects.create(
                id=uuid5(NAMESPACE_URL, uri), list=vocab, uri=uri, sortorder=order
            )
        for child in (XRF, MICRO_XRF):
            items[child].parent = items[XRF_FAMILY]
            items[child].save()
        ref = cls.reference_value
        cls.more = {
            "xrf": cls.new_resource("analysis", "X10"),
            "micro": cls.new_resource("analysis", "X11"),
            "raman": cls.new_resource("analysis", "R01"),
            "raman_open": cls.new_resource("analysis", "R02"),
        }
        for key, analysis in cls.more.items():
            component = "open" if key == "raman_open" else "embargoed"
            cls.tile(
                analysis, "component_observed", cls.refs(cls.components[component])
            )
        cls.tile(
            cls.more["xrf"],
            "analysis_technique_used",
            ref(XRF_FAMILY, "X-ray fluorescence", "Fluorescence X", alt="XRF"),
        )
        cls.tile(
            cls.more["micro"],
            "analysis_technique_used",
            ref(
                MICRO_XRF, "X-ray microfluorescence", "Microfluorescence X", alt="µXRF"
            ),
        )
        for key in ("raman", "raman_open"):
            cls.tile(
                cls.more[key],
                "analysis_technique_used",
                ref(RAMAN, "Raman spectrometry", "Spectrométrie Raman"),
            )
        cls.tile(
            cls.analyses["draft"],
            "analysis_technique_used",
            ref(XRF, "Portable XRF", "XRF portable", alt="pXRF"),
        )

    def marks(self, language="en"):
        return {
            r["technique"]["uri"]: {
                k: r["technique"][k] for k in ("code", "colour", "family")
            }
            for r in corpus_rows(self.anonymous, language)
            if r["technique"]
        }

    def test_the_code_is_the_acronym_and_the_family_shares_one_colour(self):
        marks = self.marks()

        self.assertEqual(
            [marks[u]["code"] for u in (XRF_FAMILY, XRF, MICRO_XRF)],
            ["XRF", "pXRF", "µXRF"],
        )
        self.assertEqual(
            {marks[u]["colour"] for u in (XRF_FAMILY, XRF, MICRO_XRF)},
            {marks[XRF_FAMILY]["colour"]},
        )
        self.assertIsNotNone(marks[XRF_FAMILY]["colour"])
        self.assertEqual(
            {marks[u]["family"] for u in (XRF_FAMILY, XRF, MICRO_XRF)}, {XRF_FAMILY}
        )
        self.assertEqual(marks[RAMAN]["family"], RAMAN)

    def test_a_technique_without_acronym_takes_first_letters_unique_in_the_corpus(
        self,
    ):
        marks = self.marks()

        codes = [m["code"] for m in marks.values()]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertTrue(marks[RAMAN]["code"].startswith("R"))
        self.assertTrue(marks[FORS]["code"].startswith("R"))

    def test_marks_are_the_same_in_every_language(self):
        self.assertEqual(self.marks("en"), self.marks("fr"))

    def test_marks_are_the_same_in_two_documents(self):
        def techniques(document):
            return document_payload(document.pk, self.anonymous, "en")["techniques"]

        first = techniques(self.documents["open"])
        second = techniques(self.documents["embargoed"])
        self.assertEqual(first[RAMAN], second[RAMAN])

    def test_families_take_distinct_colours_keyed_by_their_uri(self):
        marks = self.marks()

        colours = [marks[u]["colour"] for u in (XRF_FAMILY, RAMAN, FORS)]
        self.assertEqual(len(set(colours)), 3)
        self.assertEqual(
            colours, [family_colours([u])[u] for u in (XRF_FAMILY, RAMAN, FORS)]
        )

    def test_a_family_keeps_its_colour_when_analysis_counts_change(self):
        before = self.marks()
        for name in ("F10", "F11", "F12"):
            analysis = self.new_resource("analysis", name)
            self.tile(
                analysis, "component_observed", self.refs(self.components["open"])
            )
            self.tile(
                analysis,
                "analysis_technique_used",
                self.reference_value(FORS, "Reflectance (FORS)"),
            )

        cache.clear()
        self.assertEqual(self.marks(), before)

    def test_the_technique_facet_value_carries_the_same_mark(self):
        payload = search_payload(self.query(), self.anonymous, "fr")
        rows = self.marks("fr")

        facet = next(f for f in payload["facets"] if f["key"] == "technique")
        for value in facet["values"]:
            self.assertEqual(value["mark"], rows[value["id"]])
        other = next(f for f in payload["facets"] if f["key"] == "project")
        self.assertEqual({v["mark"] for v in other["values"]}, {None})


def colliding_pair():
    """Two uris whose hash puts them on the same colour when each is alone."""
    home = {}
    for n in range(100):
        uri = f"http://vocab/t{n}"
        slot = family_colours([uri])[uri]
        if slot in home:
            return home[slot], uri
        home[slot] = uri
    raise AssertionError("no collision in 100 uris")


class FamilyColourTests(SimpleTestCase):
    def test_a_family_alone_takes_its_colour_whatever_the_others(self):
        alone = {u: family_colours([u])[u] for u in (XRF_FAMILY, RAMAN, FORS)}

        together = family_colours([FORS, RAMAN, XRF_FAMILY])

        self.assertEqual(len(set(alone.values())), 3)
        self.assertEqual(together, alone)
        self.assertEqual(
            family_colours([RAMAN, XRF_FAMILY]), family_colours([XRF_FAMILY, RAMAN])
        )

    def test_two_families_on_the_same_hue_are_told_apart_the_first_uri_keeping_it(
        self,
    ):
        first, second = sorted(colliding_pair())

        colours = family_colours([second, first])

        self.assertEqual(colours[first], family_colours([first])[first])
        self.assertNotEqual(colours[second], colours[first])
        self.assertIsNotNone(colours[second])

    def test_beyond_the_palette_a_family_has_no_colour(self):
        uris = [f"http://vocab/f{n}" for n in range(TECHNIQUE_PALETTE + 1)]

        colours = family_colours(uris)

        given = [c for c in colours.values() if c is not None]
        self.assertEqual(sorted(given), list(range(1, TECHNIQUE_PALETTE + 1)))
        self.assertEqual(list(colours.values()).count(None), 1)


@override_settings(PUBLIC_SERVER_ADDRESS="https://manuspectrum.example/")
class ManifestJsonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.globalid = uuid4()
        IIIFManifest.objects.create(
            label="Local",
            url=f"/manifest/{cls.globalid}",
            manifest={"id": "stored"},
            globalid=cls.globalid,
        )

    def test_a_local_manifest_with_a_query_or_a_fragment_is_read_from_the_database(
        self,
    ):
        urls = [
            f"/manifest/{self.globalid}?version=2",
            f"/manifest/{self.globalid}/#top",
            f"https://manuspectrum.example/manifest/{self.globalid}?x=1#y",
        ]
        with patch("manuspectrum.iiif.sources.CanvasIIIF.fetch_manifest") as fetch:
            found = [manifest_json(url) for url in urls]

        self.assertEqual(found, [{"id": "stored"}] * len(urls))
        fetch.assert_not_called()

    def test_a_manifest_named_only_in_the_query_of_an_external_url_is_fetched(self):
        url = f"https://iiif.example/iiif?next=/manifest/{self.globalid}"
        with patch(
            "manuspectrum.iiif.sources.CanvasIIIF.fetch_manifest",
            return_value={"id": "fetched"},
        ) as fetch:
            found = manifest_json(url)

        self.assertEqual(found, {"id": "fetched"})
        fetch.assert_called_once_with(url)


class UnresolvedRoleWarningTests(SimpleTestCase):
    def values(self, keys, resolved=()):
        with (
            patch.object(
                explorer_service,
                "role_node",
                side_effect=lambda slug, alias: (
                    object() if (slug, alias) in resolved else None
                ),
            ),
            patch.object(
                explorer_service, "readable_nodegroup_ids", return_value=set()
            ),
        ):
            explorer_service.Values([], keys, None)

    def test_missing_layer_roles_warn_once_per_process(self):
        keys = list(explorer_service.LAYER_KEYS)
        with patch.object(explorer_service, "_unresolved_optional_warned", False):
            with self.assertLogs(explorer_service.logger, "WARNING") as first:
                self.values(keys)
                self.values(keys)
        self.assertEqual(len(first.records), 1)

    def test_a_missing_core_role_still_warns_each_time(self):
        with self.assertLogs(explorer_service.logger, "WARNING") as logged:
            self.values(["files"])
            self.values(["files"])
        self.assertEqual(len(logged.records), 2)


class AuthorTests(ServiceCase):
    def authors_of_summary(self, *authors):
        self.tile(self.characterization, "authors_of_inference", self.refs(*authors))
        payload = document_payload(self.documents["open"].pk, self.anonymous, "en")
        summary = next(
            s
            for s in payload["characterizations"]
            if s["id"] == str(self.characterization.pk)
        )
        return [(a["id"], a["model"], a["name"]["value"]) for a in summary["authors"]]

    def test_authors_keep_the_stored_order_and_their_model(self):
        project, group, person = self.projects["main"], self.group, self.operator

        authors = self.authors_of_summary(project, group, person)

        self.assertEqual(
            authors,
            [
                (str(project.pk), "project", "EMMA"),
                (str(group.pk), "group", "CNRS, CRC"),
                (str(person.pk), "person", "Robinet, L."),
            ],
        )

    def test_a_project_author_is_listed_with_its_model(self):
        authors = self.authors_of_summary(self.projects["side"])

        self.assertEqual(
            authors, [(str(self.projects["side"].pk), "project", "Side project")]
        )

    def test_a_group_author_with_a_comma_is_cited_literally(self):
        row = {
            "id": str(self.analyses["open"].pk),
            "name": {"value": "X01"},
            "date": "2024-05-14",
        }
        label_of = {
            str(self.group.pk): {"value": "CNRS, CRC"},
            str(self.operator.pk): {"value": "Robinet, L."},
        }
        slug_of = {str(self.group.pk): "group", str(self.operator.pk): "person"}

        cited = cited_analysis(
            row,
            None,
            label_of,
            [str(self.group.pk), str(self.operator.pk)],
            [],
            slug_of,
        )

        self.assertEqual(
            cited.authors,
            ({"literal": "CNRS, CRC"}, {"family": "Robinet", "given": "L."}),
        )

    def test_operators_keep_the_stored_order(self):
        self.tile(
            self.analyses["on_document"],
            "performed_by_actor",
            self.refs(self.projects["main"], self.group, self.operator),
        )

        rows = {r["id"]: r for r in corpus_rows(self.anonymous, "en")}

        self.assertEqual(
            rows[str(self.analyses["on_document"].pk)]["operators"],
            [str(self.projects["main"].pk), str(self.group.pk), str(self.operator.pk)],
        )

    def test_the_analysis_cites_a_group_operator_literally(self):
        self.tile(self.analyses["open"], "performed_by_actor", self.refs(self.group))

        payload = analysis_payload(self.analyses["open"].pk, self.anonymous, "en")

        self.assertIn("CNRS, CRC", payload["citation"]["text"])
        self.assertIn("{CNRS, CRC}", payload["citation"]["bibtex"])


ROW_KEYS = {
    "id",
    "name",
    "technique",
    "document",
    "component",
    "canvas",
    "date",
    "year",
    "projects",
    "operators",
    "materials",
    "colours",
    "layers",
    "elements",
    "characterizations",
    "partTypes",
    "partColours",
    "swatches",
    "dataKinds",
    "unpublished",
    "text",
    "places",
    "periods",
}


class PlaceTests(ServiceCase):
    def place_ids(self, *keys):
        return sorted(str(self.places[k].pk) for k in keys)

    def row(self, key="open"):
        rows = {r["id"]: r for r in corpus_rows(self.anonymous, "en")}
        return rows[str(self.analyses[key].pk)]

    def chain(self, count):
        """*count* places, each within the next; returns them from the bottom."""
        made = [self.new_resource("place", f"Level {i}") for i in range(count)]
        for child, parent in zip(made, made[1:]):
            self.tile(child, "part_of_places", self.refs(parent))
        return made

    def test_a_row_carries_its_places_and_their_ancestors(self):
        self.assertEqual(
            self.row("on_document")["places"],
            self.place_ids("paris", "france", "europe"),
        )

    def test_component_and_document_places_are_united(self):
        self.assertEqual(
            self.row("open")["places"],
            self.place_ids("paris", "france", "europe", "lyon"),
        )

    def test_a_hidden_place_cuts_the_chain(self):
        self.embargo(self.places["france"])

        self.assertEqual(self.row("on_document")["places"], self.place_ids("paris"))

    def test_a_hidden_ancestor_keeps_what_lies_below_it(self):
        self.embargo(self.places["europe"])

        self.assertEqual(
            self.row("on_document")["places"], self.place_ids("paris", "france")
        )

    def test_a_hidden_own_place_is_left_out(self):
        self.embargo(self.places["paris"])

        self.assertEqual(self.row("on_document")["places"], [])

    def test_a_draft_place_is_listed_unpublished(self):
        bundle = build_bundle(self.anonymous, "en", visible_set(self.anonymous))

        france, paris = (str(self.places[k].pk) for k in ("france", "paris"))
        self.assertIs(bundle.places[france]["unpublished"], True)
        self.assertIs(bundle.places[paris]["unpublished"], False)
        self.assertEqual(bundle.places[paris]["parent"], france)
        self.assertIsNone(bundle.places[str(self.places["europe"].pk)]["parent"])
        self.assertEqual(
            set(bundle.places), set(self.place_ids("paris", "france", "europe", "lyon"))
        )

    def test_an_unreadable_part_of_nodegroup_flattens_the_tree(self):
        self.restrict_nodegroup(
            self.nodes[("place", "part_of_places")].nodegroup_id, self.editor
        )

        self.assertEqual(self.row("on_document")["places"], self.place_ids("paris"))

    def test_an_unreadable_production_nodegroup_leaves_dates_and_places_out(self):
        self.restrict_nodegroup(
            self.nodes[("document", "production_at_place")].nodegroup_id, self.editor
        )
        row = self.row("on_document")

        self.assertEqual(row["places"], [])
        self.assertIsNone(row["periods"]["production"])

    def test_the_closure_stops_at_depth(self):
        made = self.chain(20)
        depth = explorer_service.PLACE_DEPTH

        reach, parents = place_closure([made[0].pk], self.anonymous)

        self.assertEqual(reach[str(made[0].pk)], {str(p.pk) for p in made[: depth + 1]})
        self.assertIsNone(parents[str(made[depth].pk)])

    def test_the_closure_survives_a_cycle(self):
        a, b, c = self.chain(3)
        self.tile(c, "part_of_places", self.refs(a))

        reach, parents = place_closure([a.pk], self.anonymous)

        self.assertEqual(reach[str(a.pk)], {str(a.pk), str(b.pk), str(c.pk)})
        self.assertEqual(set(parents), set(reach[str(a.pk)]))

    def test_a_place_with_several_parents_hangs_under_the_smallest_id(self):
        self.tile(
            self.places["paris"], "part_of_places", self.refs(self.places["lyon"])
        )

        _, parents = place_closure([self.places["paris"].pk], self.anonymous)

        expected = min(str(self.places[k].pk) for k in ("france", "lyon"))
        self.assertEqual(parents[str(self.places["paris"].pk)], expected)

    def test_reading_places_costs_the_same_queries_for_one_place_or_many(self):
        counts = []
        place_closure([self.places["paris"].pk], self.anonymous)
        for own in ([self.places["paris"].pk], [p.pk for p in self.places.values()]):
            with CaptureQueriesContext(connection) as queries:
                place_closure(own, self.anonymous)
            counts.append(len(queries))

        self.assertEqual(counts[0], counts[1])
        self.assertLessEqual(counts[0], 10)


class PeriodTests(ServiceCase):
    def production(self, key="open"):
        rows = {r["id"]: r for r in corpus_rows(self.anonymous, "en")}
        return rows[str(self.analyses[key].pk)]["periods"]["production"]

    def test_a_row_carries_the_document_production_in_years(self):
        self.assertEqual(self.production("on_document"), (1401, 1500, True))
        for row in corpus_rows(self.anonymous, "en"):
            self.assertIsNone(row["periods"]["modification"])

    def test_the_component_production_wins_over_the_document_s(self):
        self.tile_values(
            self.components["open"],
            "component",
            date_start_of_production_time="1250-05-02",
            date_end_of_production_time="1275",
            type_of_production_time=False,
        )

        self.assertEqual(self.production("open"), (1250, 1275, False))
        self.assertEqual(self.production("on_document"), (1401, 1500, True))

    def test_the_approximate_flag_is_read_from_the_same_tile(self):
        document = self.documents["embargoed"]
        self.tile_values(
            document,
            "document",
            date_start_of_production_time="1301",
            type_of_production_time=False,
        )
        self.tile_values(document, "document", type_of_production_time=True)

        self.assertEqual(self.production("embargoed"), (1301, 1301, False))

    def test_a_row_without_a_bound_has_no_period(self):
        self.assertIsNone(self.production("embargoed"))

    def test_a_single_bound_stands_for_both(self):
        self.tile_values(
            self.documents["embargoed"],
            "document",
            date_end_of_production_time="1350-06-01",
        )

        self.assertEqual(self.production("embargoed"), (1350, 1350, False))

    def test_a_bound_that_is_not_a_year_is_ignored(self):
        self.tile_values(
            self.documents["embargoed"],
            "document",
            date_start_of_production_time="[..1350]",
            date_end_of_production_time="1350-06-01",
        )

        self.assertEqual(self.production("embargoed"), (1350, 1350, False))

    def test_the_bundle_keeps_the_bounds_of_its_dated_rows(self):
        bundle = build_bundle(self.anonymous, "en", visible_set(self.anonymous))

        self.assertEqual(
            bundle.period_bounds, {"production": (1401, 1500), "modification": None}
        )

    def test_the_bundle_has_no_bounds_without_a_dated_row(self):
        TileModel.objects.filter(
            resourceinstance=self.documents["open"],
            nodegroup_id=self.nodes[
                ("document", "date_start_of_production_time")
            ].nodegroup_id,
        ).delete()
        bundle = build_bundle(self.anonymous, "en", visible_set(self.anonymous))

        self.assertEqual(
            bundle.period_bounds, {"production": None, "modification": None}
        )

    def test_the_corpus_rows_shape(self):
        rows = corpus_rows(self.anonymous, "en")

        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(set(row), ROW_KEYS)
            self.assertIsInstance(row["places"], list)
            self.assertEqual(set(row["periods"]), {"production", "modification"})

    def test_history_carries_the_production_line(self):
        payload = document_payload(self.documents["open"].pk, self.anonymous, "en")

        self.assertEqual(
            payload["history"],
            [
                {
                    "type": "production",
                    "places": [
                        {
                            "id": str(self.places["paris"].pk),
                            "name": {"value": "Paris", "lang": "en"},
                        }
                    ],
                    "date": {"start": "1401-01", "end": "1500-12", "approximate": True},
                }
            ],
        )

    def test_history_is_empty_without_a_bound_or_a_readable_place(self):
        payload = document_payload(self.documents["embargoed"].pk, self.anonymous, "en")

        self.assertEqual(payload["history"], [])

    def test_history_lists_a_draft_place_and_leaves_a_hidden_one_out(self):
        self.tile_values(
            self.documents["embargoed"],
            "document",
            production_at_place=self.refs(
                self.places["hidden"], self.places["france"], self.places["lyon"]
            ),
        )
        self.embargo(self.places["hidden"])

        payload = document_payload(self.documents["embargoed"].pk, self.anonymous, "en")

        self.assertEqual(
            [p["name"]["value"] for p in payload["history"][0]["places"]],
            ["France", "Lyon"],
        )
        self.assertEqual(
            payload["history"][0]["date"],
            {"start": None, "end": None, "approximate": False},
        )

    def test_a_document_hit_carries_approximate(self):
        def hits():
            payload = search_payload(
                self.query("grain=documents"), self.anonymous, "en"
            )
            return {r["id"]: r for r in payload["results"]}

        self.assertEqual(
            hits()[str(self.documents["open"].pk)]["dates"],
            {"start": "1401-01", "end": "1500-12", "approximate": True},
        )
        self.tile_values(
            self.documents["embargoed"],
            "document",
            date_start_of_production_time="1301-01-01",
        )
        self.assertEqual(
            hits()[str(self.documents["embargoed"].pk)]["dates"],
            {"start": "1301-01-01", "end": None, "approximate": False},
        )


class PlaceFilterTests(ServiceCase):
    facet = FacetTests.facet

    def place(self, key):
        return str(self.places[key].pk)

    def search(self, text=""):
        return search_payload(self.query(text), self.anonymous, "en")

    def found(self, text):
        return {r["id"] for r in self.search(text)["results"]}

    def rows(self, *keys):
        return {str(self.analyses[k].pk) for k in keys}

    def test_a_place_keeps_the_rows_carrying_it_as_their_own_or_as_an_ancestor(self):
        self.assertEqual(
            self.found(f"place={self.place('europe')}"),
            self.rows("open", "on_document", "draft"),
        )
        self.assertEqual(
            self.found(f"place={self.place('lyon')}"), self.rows("open", "draft")
        )

    def test_several_places_are_ored(self):
        self.assertEqual(
            self.found(f"place={self.place('lyon')}&place={self.place('paris')}"),
            self.rows("open", "on_document", "draft"),
        )
        self.assertEqual(
            self.found(f"place={self.place('lyon')},{self.place('paris')}"),
            self.rows("open", "on_document", "draft"),
        )

    def test_a_place_combines_with_another_facet_by_and(self):
        self.assertEqual(
            self.found(f"place={self.place('europe')}&technique={FORS}"),
            self.rows("on_document"),
        )

    def test_a_place_no_row_carries_is_ignored(self):
        self.assertEqual(
            self.found("place=00000000-0000-4000-8000-000000000001"),
            self.rows("open", "on_document", "draft", "embargoed"),
        )

    def test_a_parent_counts_each_row_once_and_a_child_only_its_own(self):
        places = self.facet(self.search(), "place")

        self.assertEqual(places[self.place("europe")]["count"], 3)
        self.assertEqual(places[self.place("france")]["count"], 3)
        self.assertEqual(places[self.place("paris")]["count"], 3)
        self.assertEqual(places[self.place("lyon")]["count"], 2)

    def test_a_place_facet_is_open_to_the_other_selections(self):
        places = self.facet(self.search(f"technique={FORS}"), "place")

        self.assertEqual(places[self.place("europe")]["count"], 1)
        self.assertNotIn(self.place("lyon"), places)

    def test_a_place_value_names_its_parent_and_its_state(self):
        places = self.facet(self.search(), "place")

        self.assertIsNone(places[self.place("europe")]["parent"])
        self.assertEqual(places[self.place("france")]["parent"], self.place("europe"))
        self.assertEqual(places[self.place("paris")]["parent"], self.place("france"))
        self.assertIs(places[self.place("france")]["unpublished"], True)
        self.assertIs(places[self.place("paris")]["unpublished"], False)
        self.assertEqual(
            places[self.place("paris")]["label"], {"value": "Paris", "lang": "en"}
        )

    def test_the_other_facets_carry_no_parent_and_are_published(self):
        for value in self.facet(self.search(), "technique").values():
            self.assertIsNone(value["parent"])
            self.assertIs(value["unpublished"], False)

    def test_find_on_place_returns_matches_with_their_ancestors(self):
        facet = facet_payload("place", self.query("find=pari"), self.anonymous, "en")

        self.assertEqual(
            {v["id"] for v in facet["values"]},
            {self.place("paris"), self.place("france"), self.place("europe")},
        )
        self.assertEqual(facet["total"], 4)

    def test_find_on_place_keeps_the_selected_ones(self):
        facet = facet_payload(
            "place",
            self.query(f"find=lyon&place={self.place('paris')}"),
            self.anonymous,
            "en",
        )

        self.assertEqual(
            {v["id"] for v in facet["values"]},
            {self.place("lyon"), self.place("paris")},
        )

    def test_a_match_applies_the_place_rule_of_the_search(self):
        payload = match_payload(
            self.documents["open"].pk,
            self.query(f"place={self.place('lyon')}"),
            self.anonymous,
            "en",
        )

        self.assertEqual(set(payload["kept"]["analyses"]), self.rows("open", "draft"))
        self.assertEqual(payload["total"], 2)

    def test_a_restricted_place_nodegroup_leaves_the_facet_out(self):
        for slug in ("document", "component"):
            self.restrict_nodegroup(
                self.nodes[(slug, "production_at_place")].nodegroup_id, self.editor
            )

        self.assertNotIn("place", [f["key"] for f in self.search()["facets"]])


class PeriodFilterTests(ServiceCase):
    """Open, on_document and draft rows are produced 1401-1500 (the Document's); embargoed is undated."""

    facet = FacetTests.facet

    def search(self, text=""):
        return search_payload(self.query(text), self.anonymous, "en")

    def found(self, text):
        return {r["id"] for r in self.search(text)["results"]}

    def rows(self, *keys):
        return {str(self.analyses[k].pk) for k in keys}

    DATED = ("open", "on_document", "draft")

    def test_overlap_keeps_a_row_touching_the_bounds(self):
        for text in ("1500,1600", "1300,1401", "1450,1460", "1000,2000"):
            self.assertEqual(self.found(f"period={text}"), self.rows(*self.DATED), text)
        for text in ("1501,1600", "1300,1400"):
            self.assertEqual(self.found(f"period={text}"), set(), text)

    def test_within_keeps_only_rows_inside(self):
        self.assertEqual(
            self.found("period=1401,1500&periodMatch=within"), self.rows(*self.DATED)
        )
        self.assertEqual(self.found("period=1402,1500&periodMatch=within"), set())
        self.assertEqual(self.found("period=1401,1499&periodMatch=within"), set())

    def test_undated_rows_are_excluded_unless_asked(self):
        self.assertNotIn(
            str(self.analyses["embargoed"].pk), self.found("period=1000,2000")
        )
        self.assertEqual(
            self.found("period=1000,2000&undated=1"),
            self.rows(*self.DATED, "embargoed"),
        )
        self.assertEqual(
            self.found("period=1501,1600&undated=1"), self.rows("embargoed")
        )

    def test_undated_alone_filters_nothing(self):
        self.assertEqual(self.found("undated=1"), self.rows(*self.DATED, "embargoed"))

    def test_the_component_production_wins_over_the_document_s(self):
        self.tile_values(
            self.components["open"],
            "component",
            date_start_of_production_time="1250",
            date_end_of_production_time="1275",
        )

        self.assertEqual(self.found("period=1260,1270"), self.rows("open", "draft"))
        self.assertEqual(self.found("period=1450,1460"), self.rows("on_document"))

    def test_an_invalid_period_is_ignored_without_400(self):
        everything = self.rows(*self.DATED, "embargoed")
        for text in ("abc", "1600,1500", "1400", "1400,1500,1600", ",", "12345,99999"):
            self.assertEqual(self.found(f"period={text}"), everything, text)

    def test_an_invalid_option_falls_back_to_its_default(self):
        self.assertEqual(
            self.found("period=1500,1600&periodMatch=bogus&periodEvent=bogus"),
            self.rows(*self.DATED),
        )

    def test_period_event_modification_dates_nothing(self):
        everything = self.rows(*self.DATED, "embargoed")
        self.assertEqual(self.found("period=1000,2000&periodEvent=modification"), set())
        self.assertEqual(
            self.found("period=1000,2000&periodEvent=modification&undated=1"),
            everything,
        )

    def test_the_range_facet_counts_each_century_a_row_overlaps_open_to_the_other_selections(
        self,
    ):
        self.tile_values(
            self.documents["embargoed"],
            "document",
            date_start_of_production_time="1390",
            date_end_of_production_time="1410",
        )

        facet = self.search()["period"]
        self.assertEqual(
            facet,
            {
                "key": "period",
                "group": "document",
                "event": "production",
                "min": 1390,
                "max": 1500,
                "buckets": [
                    {"from": 1301, "to": 1400, "count": 1},
                    {"from": 1401, "to": 1500, "count": 4},
                ],
                "undated": 0,
            },
        )
        narrowed = self.search(f"technique={FORS}&period=1000,1100")["period"]
        self.assertEqual([b["count"] for b in narrowed["buckets"]], [0, 1])
        self.assertEqual(narrowed["undated"], 0)

    def test_the_range_facet_counts_the_undated_rows_the_other_filters_keep(self):
        facet = self.search()["period"]
        self.assertEqual(facet["undated"], 1)
        self.assertEqual(
            [(b["from"], b["to"], b["count"]) for b in facet["buckets"]],
            [(1401, 1500, 3)],
        )
        self.assertEqual(self.search(f"technique={FORS}")["period"]["undated"], 0)

    def test_the_range_facet_is_absent_without_a_dated_row_or_facets(self):
        self.assertIsNone(self.search("facets=0")["period"])
        TileModel.objects.filter(
            resourceinstance=self.documents["open"],
            nodegroup_id=self.nodes[
                ("document", "date_start_of_production_time")
            ].nodegroup_id,
        ).delete()

        self.assertIsNone(self.search()["period"])
        self.assertIsNone(facet_payload("period", self.query(), self.anonymous, "en"))

    def test_the_range_facet_of_the_modification_event_is_absent(self):
        self.assertIsNone(self.search("periodEvent=modification")["period"])

    def test_the_facet_route_answers_the_range_facet_of_the_corpus_or_a_document(self):
        corpus = facet_payload("period", self.query(), self.anonymous, "en")
        own = facet_payload(
            "period",
            self.query(f"document={self.documents['open'].pk}&find=zzz"),
            self.anonymous,
            "en",
        )
        none = facet_payload(
            "period",
            self.query(f"document={self.documents['embargoed'].pk}"),
            self.anonymous,
            "en",
        )

        self.assertEqual(corpus, self.search()["period"])
        self.assertEqual(own["undated"], 0)
        self.assertEqual(own["buckets"], [{"from": 1401, "to": 1500, "count": 3}])
        self.assertIsNone(none)

    def test_a_match_applies_the_period_rule_and_carries_the_range_facet(self):
        payload = match_payload(
            self.documents["open"].pk,
            self.query("period=1501,1600"),
            self.anonymous,
            "en",
        )

        self.assertEqual(payload["kept"]["analyses"], [])
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["period"]["min"], 1401)
        self.assertEqual(payload["period"]["buckets"][0]["count"], 3)
        self.assertIsNone(
            match_payload(
                self.documents["embargoed"].pk, self.query(), self.anonymous, "en"
            )["period"]
        )

    def test_a_period_makes_a_match_filtered(self):
        payload = match_payload(
            self.documents["open"].pk,
            self.query("period=1000,2000"),
            self.anonymous,
            "en",
        )

        self.assertEqual(len(payload["kept"]["analyses"]), 3)

    def test_the_documents_grain_lists_the_documents_with_a_kept_row(self):
        payload = search_payload(
            self.query("grain=documents&period=1000,2000"),
            self.anonymous,
            "en",
        )

        self.assertEqual(
            [r["id"] for r in payload["results"]], [str(self.documents["open"].pk)]
        )
