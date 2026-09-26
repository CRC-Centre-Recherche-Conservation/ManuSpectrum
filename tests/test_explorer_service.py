"""Rows, facets and free text of the Explorer's search, on real tiles.

Usage:
    python manage.py test tests.test_explorer_service --settings="tests.test_settings"
"""

from uuid import NAMESPACE_URL, uuid5

from django.core.cache import cache
from django.http import QueryDict
from django.test import SimpleTestCase

from arches_controlled_lists.models import List, ListItem, ListItemValue

from manuspectrum.views.explorer.service import (
    TECHNIQUE_PALETTE,
    ancestor_terms,
    corpus_rows,
    document_payload,
    family_colours,
    fold,
    match_payload,
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

    def test_part_colour_and_identified_colour_are_two_facets(self):
        payload = self.search(f"partColour={PART_BLUE}&colour={RED}")

        self.assertEqual(self.ids(payload), {str(self.analyses["open"].pk)})

    def test_each_facet_names_its_group_in_rail_order(self):
        payload = self.search("")

        self.assertEqual(
            [(f["key"], f["group"]) for f in payload["facets"]],
            [
                ("partType", "part"),
                ("partColour", "part"),
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
        swatches = {
            language: {
                key: {v: facet[v]["swatch"] for v in facet}
                for key in ("colour", "partColour", "material")
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
        self.assertEqual(swatches["en"]["partColour"][PART_BLUE], "royalblue")
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
