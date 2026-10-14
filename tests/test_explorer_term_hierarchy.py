"""A selected parent term of a controlled list keeps its descendants, in rows, facets, document match and Compare.

Usage:
    python manage.py test tests.test_explorer_term_hierarchy --settings="tests.test_settings"
"""

import json

from django.core.cache import cache
from django.http import QueryDict

from manuspectrum.utils.public_visibility import visible_set
from manuspectrum.views.explorer.home import homepage_techniques
from manuspectrum.views.explorer.scopes import resolve_scope
from manuspectrum.views.explorer.service import (
    build_bundle,
    facet_payload,
    home_payload,
    match_payload,
    search_payload,
)
from manuspectrum.views.explorer.synthesis import synthesis_payload
from tests.explorer_fixtures import CANVAS
from tests.test_explorer_service import (
    AZURITE,
    BLUE,
    FORS,
    LEAD_WHITE,
    RED,
    XRF,
    ServiceCase,
)

SPECTROMETRY = "http://vocab/spectrometry"
XRF_FAMILY = "http://vocab/xrf-family"
BLUE_PIGMENT = "http://vocab/blue-pigment"
MINERAL = "http://vocab/mineral"
GROUND_LAYERS = "http://vocab/ground-layers"
SUPPORT = "http://vocab/support"
SHARED = "http://vocab/shared"
POINT = {"type": "Point", "coordinates": [10, 10]}


class HierarchyCase(ServiceCase):
    """Techniques, materials, layers and component types as controlled lists with parents.

    The open analysis (pXRF) and the one on the document (FORS) cite the
    azurite material, which sits under two parents; a lead white material
    with a red colour is cited by the open analysis only. The open component
    and the material's layer carry one uri that two lists hold under
    different parents.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        both = lambda en, fr=None, **more: {
            "en": en,
            **({"fr": fr} if fr else {}),
            **more,
        }
        cls.term_list(
            "analysis",
            "analysis_technique_used",
            [
                (SPECTROMETRY, None, both("Spectrometry", "Spectrométrie")),
                (XRF_FAMILY, SPECTROMETRY, both("X-ray fluorescence")),
                (XRF, XRF_FAMILY, both("Portable XRF", "XRF portable")),
                (FORS, SPECTROMETRY, both("Reflectance (FORS)")),
            ],
        )
        cls.term_list(
            "characterization",
            "identified_material",
            [
                (
                    BLUE_PIGMENT,
                    None,
                    both("Blue pigment", "Pigment bleu", alt="azure pigment"),
                ),
                (MINERAL, None, both("Mineral origin")),
                (AZURITE, BLUE_PIGMENT, both("Azurite", "Azurite")),
                (AZURITE, MINERAL, both("Azurite", "Azurite")),
                (LEAD_WHITE, None, both("Lead white", "Blanc de plomb")),
            ],
        )
        cls.term_list(
            "characterization",
            "layer_type",
            [
                (GROUND_LAYERS, None, both("Ground layers")),
                (SHARED, GROUND_LAYERS, both("Shared")),
            ],
        )
        cls.term_list(
            "component",
            "type",
            [
                (SUPPORT, None, both("Support")),
                (SHARED, SUPPORT, both("Shared")),
            ],
        )
        ref = cls.reference_value
        cls.tile(cls.components["open"], "type", ref(SHARED, "Shared"))
        cls.tile(cls.characterization, "layer_type", ref(SHARED, "Shared"))
        cls.lead = cls.new_resource("characterization", "Lead white, red ground")
        cls.tile(cls.lead, "object_observed", cls.refs(cls.components["open"]))
        cls.tile(cls.lead, "evidence_analyses", cls.refs(cls.analyses["open"]))
        cls.tile(cls.lead, "identified_material", ref(LEAD_WHITE, "Lead white"))
        cls.tile(cls.lead, "color_aspect", ref(RED, "Red", "Rouge"))

    def id(self, key):
        return str(self.analyses[key].pk)

    def search(self, text=""):
        return search_payload(self.query(text), self.anonymous, "en")

    def kept(self, text):
        return {r["id"] for r in self.search(f"{text}&size=50")["results"]}

    def facet(self, payload, key):
        return {
            v["id"]: v
            for f in payload["facets"]
            if f["key"] == key
            for v in f["values"]
        }

    def citing_azurite(self):
        return {self.id("open"), self.id("on_document")}

    def on_open_component(self):
        return {self.id("open"), self.id("draft")}


class ParentKeepsDescendantsTests(HierarchyCase):
    def test_a_parent_technique_keeps_the_rows_of_its_descendants(self):
        self.assertEqual(
            self.kept(f"technique={SPECTROMETRY}"),
            {self.id("open"), self.id("on_document")},
        )
        self.assertEqual(self.kept(f"technique={XRF_FAMILY}"), {self.id("open")})

    def test_a_parent_material_is_honoured_instead_of_ignored(self):
        self.assertEqual(self.kept(f"material={BLUE_PIGMENT}"), self.citing_azurite())

    def test_a_parent_counts_each_row_once(self):
        technique = self.facet(self.search(), "technique")

        self.assertEqual(
            (technique[SPECTROMETRY]["count"], technique[XRF_FAMILY]["count"]),
            (2, 1),
        )

    def test_a_parent_and_its_own_descendant_in_one_url_keep_the_parent_rows(self):
        self.assertEqual(
            self.kept(f"technique={XRF_FAMILY},{XRF}"),
            self.kept(f"technique={XRF_FAMILY}"),
        )


class PolyhierarchyTests(HierarchyCase):
    def test_a_material_under_two_parents_is_kept_by_either(self):
        self.assertEqual(
            self.kept(f"material={MINERAL}"), self.kept(f"material={BLUE_PIGMENT}")
        )
        self.assertEqual(self.kept(f"material={MINERAL}"), self.citing_azurite())

    def test_each_parent_counts_a_row_once(self):
        materials = self.facet(self.search(), "material")

        self.assertEqual(materials[AZURITE]["count"], 2)
        self.assertEqual(materials[BLUE_PIGMENT]["count"], 2)
        self.assertEqual(materials[MINERAL]["count"], 2)


class SharedUriTests(HierarchyCase):
    def test_a_uri_in_two_lists_follows_each_list_only(self):
        self.assertEqual(self.kept(f"partType={SUPPORT}"), self.on_open_component())
        self.assertEqual(self.kept(f"layer={GROUND_LAYERS}"), self.citing_azurite())
        payload = self.search()
        self.assertNotIn(GROUND_LAYERS, self.facet(payload, "partType"))
        self.assertNotIn(SUPPORT, self.facet(payload, "layer"))


class OneMaterialTests(HierarchyCase):
    def test_a_parent_and_a_colour_hold_on_one_identified_material(self):
        self.assertEqual(
            self.kept(f"material={BLUE_PIGMENT}&colour={BLUE}"), self.citing_azurite()
        )
        self.assertEqual(self.kept(f"material={BLUE_PIGMENT}&colour={RED}"), set())

    def test_match_keeps_the_materials_under_a_selected_parent(self):
        match = match_payload(
            self.documents["open"].pk,
            self.query(f"material={BLUE_PIGMENT}"),
            self.anonymous,
            "en",
        )

        self.assertEqual(
            match["kept"]["characterizations"], [str(self.characterization.pk)]
        )


class FreeTextTests(HierarchyCase):
    def test_free_text_never_finds_a_material_through_its_ancestor(self):
        self.assertEqual(self.kept("q=mineral origin"), set())

    def test_free_text_still_finds_a_technique_through_its_ancestor(self):
        self.assertEqual(
            self.kept("q=spectrometry"), {self.id("open"), self.id("on_document")}
        )


class MarksTests(HierarchyCase):
    def test_carried_techniques_keep_their_mark_and_an_implied_ancestor_has_none(self):
        bundle = build_bundle(self.anonymous, "en", visible_set(self.anonymous))

        self.assertIn(XRF, bundle.marks)
        self.assertNotIn(SPECTROMETRY, bundle.marks)
        self.assertEqual(bundle.carried["technique"], {XRF, FORS})
        self.assertEqual(
            bundle.labels["technique"][SPECTROMETRY]["value"], "Spectrometry"
        )

    def test_the_trees_hold_the_parents_of_every_universe_value(self):
        bundle = build_bundle(self.anonymous, "en", visible_set(self.anonymous))

        self.assertEqual(
            bundle.trees["material"][AZURITE], tuple(sorted((BLUE_PIGMENT, MINERAL)))
        )
        self.assertEqual(bundle.trees["technique"][SPECTROMETRY], ())
        self.assertEqual(
            bundle.trees["place"][str(self.places["paris"].pk)],
            (str(self.places["france"].pk),),
        )

    def test_an_implied_material_is_found_by_its_list_labels(self):
        bundle = build_bundle(self.anonymous, "en", visible_set(self.anonymous))

        self.assertIn("azure pigment", bundle.material_terms[BLUE_PIGMENT])


class SynthesisExactTests(HierarchyCase):
    def test_the_synthesis_lists_the_exact_identified_materials_never_their_ancestors(
        self,
    ):
        self.tile(
            self.characterization,
            "location_of_characterization",
            self.annotation_value(CANVAS, POINT),
        )
        scope = resolve_scope(QueryDict(f"ids=ch:{self.characterization.pk}:-"), "en")

        text = json.dumps(synthesis_payload(scope))

        self.assertIn(AZURITE, text)
        self.assertNotIn(BLUE_PIGMENT, text)
        self.assertNotIn(MINERAL, text)


class FacetPayloadTests(HierarchyCase):
    def values(self, key, query="", lang="en"):
        facet = facet_payload(key, self.query(query), self.anonymous, lang)
        return facet, {v["id"]: v for v in facet["values"]}

    def test_values_name_every_parent_in_the_request_language(self):
        _, materials = self.values("material")

        self.assertEqual(materials[AZURITE]["parents"], sorted((BLUE_PIGMENT, MINERAL)))
        self.assertEqual(materials[BLUE_PIGMENT]["parents"], [])
        _, french = self.values("material", lang="fr")
        self.assertEqual(french[BLUE_PIGMENT]["label"]["value"], "Pigment bleu")

    def test_find_names_its_matches_and_keeps_ancestors_and_descendants(self):
        facet, values = self.values("material", "find=pigment")

        self.assertEqual(facet["found"], [BLUE_PIGMENT])
        self.assertTrue({BLUE_PIGMENT, AZURITE} <= set(values))
        self.assertNotIn(LEAD_WHITE, values)

    def test_find_reaches_an_ancestor_through_its_synonym(self):
        facet, _ = self.values("material", "find=azure pigment")

        self.assertEqual(facet["found"], [BLUE_PIGMENT])

    def test_find_keeps_the_ancestors_of_a_match_and_of_a_selected_value(self):
        _, values = self.values("technique", f"find=portable&technique={FORS}")

        self.assertEqual(set(values), {XRF, XRF_FAMILY, SPECTROMETRY, FORS})

    def test_without_find_found_is_null(self):
        facet, _ = self.values("material")

        self.assertIsNone(facet["found"])

    def test_a_place_value_has_at_most_one_parent(self):
        _, places = self.values("place")
        paris, france = (str(self.places[k].pk) for k in ("paris", "france"))

        self.assertEqual(places[paris]["parents"], [france])
        self.assertTrue(
            all(len(v["parents"]) <= 1 for v in places.values()),
        )
        self.assertTrue(any(v["parents"] == [] for v in places.values()))

    def test_the_other_facets_name_no_parents(self):
        for key in ("colour", "project"):
            _, values = self.values(key)
            self.assertTrue(values)
            self.assertTrue(all(v["parents"] == [] for v in values.values()))

    def test_narrower_follows_the_universe_not_the_counts(self):
        _, techniques = self.values("technique")
        self.assertTrue(techniques[XRF_FAMILY]["narrower"])
        self.assertTrue(techniques[SPECTROMETRY]["narrower"])
        self.assertFalse(techniques[XRF]["narrower"])
        self.assertFalse(techniques[FORS]["narrower"])

        _, kept = self.values("technique", f"technique={XRF_FAMILY}&colour={RED}")
        self.assertNotIn(FORS, kept)
        self.assertTrue(kept[XRF_FAMILY]["narrower"])
        _, other = self.values(
            "technique", f"technique={XRF_FAMILY}&material={LEAD_WHITE}"
        )
        self.assertTrue(other[XRF_FAMILY]["narrower"])

    def test_no_place_is_narrower(self):
        _, places = self.values("place")

        self.assertFalse(any(v["narrower"] for v in places.values()))

    def test_the_document_facet_names_parents_too(self):
        facet = facet_payload(
            "material",
            self.query(f"document={self.documents['open'].pk}"),
            self.anonymous,
            "en",
        )
        values = {v["id"]: v for v in facet["values"]}

        self.assertEqual(values[AZURITE]["parents"], sorted((BLUE_PIGMENT, MINERAL)))
        self.assertTrue(values[BLUE_PIGMENT]["narrower"])


class HomesTests(HierarchyCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def explorer_home(self):
        return home_payload("2026-10-13", self.anonymous, "en")["techniques"]

    def test_the_explorer_home_lists_only_carried_techniques(self):
        self.assertEqual({t["id"] for t in self.explorer_home()}, {XRF, FORS})

    def test_the_homepage_lists_only_carried_techniques(self):
        self.assertEqual({t["id"] for t in homepage_techniques("en")}, {XRF, FORS})


class NestedHomesTests(HierarchyCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        family = cls.new_resource("analysis", "Family-level analysis")
        cls.tile(family, "component_observed", cls.refs(cls.components["open"]))
        cls.tile(
            family,
            "analysis_technique_used",
            cls.reference_value(XRF_FAMILY, "X-ray fluorescence"),
        )

    def setUp(self):
        super().setUp()
        cache.clear()

    def explorer_home(self):
        values = home_payload("2026-10-13", self.anonymous, "en")["techniques"]
        return values, {v["id"]: v for v in values}

    def test_a_carried_parent_counts_its_descendants_rows(self):
        _, values = self.explorer_home()

        self.assertEqual(values[XRF_FAMILY]["count"], 2)
        self.assertEqual(values[XRF]["count"], 1)

    def test_a_narrower_carried_technique_is_nested_under_its_carried_parent(self):
        ordered, values = self.explorer_home()
        ids = [v["id"] for v in ordered]

        self.assertEqual(values[XRF]["parents"], [XRF_FAMILY])
        self.assertEqual(ids.index(XRF), ids.index(XRF_FAMILY) + 1)
        self.assertEqual(values[FORS]["parents"], [])
        self.assertEqual(values[XRF_FAMILY]["parents"], [])
        self.assertNotIn(SPECTROMETRY, values)

    def test_the_homepage_gives_each_technique_its_depth(self):
        depths = {t["id"]: t["depth"] for t in homepage_techniques("en")}

        self.assertEqual(depths, {XRF_FAMILY: 0, XRF: 1, FORS: 0})
