"""Identified materials as ``classifying`` annotations linked to their evidence (C3).

Usage:
    python manage.py test tests.test_iiif_characterizations --settings=tests.test_settings
"""

from django.test import Client

from manuspectrum.iiif import ids
from tests.explorer_fixtures import (
    CANVAS_2,
    CANVAS_3,
    FEATURES,
    POINT,
    RECT,
    IIIFCase,
)
from tests.iiif_schema import assert_valid_iiif

AAT_VERMILION = "http://vocab.getty.edu/aat/300013526"
PROBABLE = "https://ms.example/plugins/controlled-list-manager/item/probable"
AAT_RED = "http://vocab.getty.edu/aat/300126225"
PAINT_LAYER = "https://ms.example/plugins/controlled-list-manager/item/paint-layer"
MERCURY = "http://www.wikidata.org/entity/Q925"
MAJOR = "https://ms.example/plugins/controlled-list-manager/item/major"
LEAD_WHITE = "http://vocab.getty.edu/aat/300013432"
OWN_ZONE = "0c0c0c0c-0000-4000-8000-000000000001"
COMPONENT_ZONE = "0c0c0c0c-0000-4000-8000-000000000002"


class CharacterizationCase(IIIFCase):
    """The IIIFCase corpus; ``Azurite, blue ground`` gets concepts and its own point on f. 2r.

    A second identified material (``Lead white``) has no zone of its own and
    observes a Component whose zone is a rectangle on f. 3r; it cites a
    third analysis that has no zone.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        vermilion = cls.characterization
        cls.tile_values(
            vermilion,
            "characterization",
            identified_material=cls.reference_value(
                AAT_VERMILION, "vermilion", "vermillon"
            ),
            material_confidence=cls.reference_value(PROBABLE, "probable", "probable"),
        )
        cls.tile(
            vermilion, "color_aspect", cls.reference_value(AAT_RED, "red", "rouge")
        )
        cls.tile(
            vermilion,
            "layer_type",
            cls.reference_value(PAINT_LAYER, "paint layer", "couche picturale"),
        )
        unlinked = cls.reference_value(MERCURY, "sulfur", "soufre")
        unlinked[0]["uri"] = ""
        cls.tile_values(
            vermilion,
            "characterization",
            detected_elements=cls.reference_value(MERCURY, "mercury", "mercure")
            + unlinked,
            element_level=cls.reference_value(MAJOR, "major", "majeur"),
        )
        cls.zone(
            vermilion,
            [(OWN_ZONE, CANVAS_2, POINT)],
            alias="location_of_characterization",
        )

        cls.zoned_component = cls.new_resource("component", "f. 3r — ground")
        cls.tile(
            cls.zoned_component,
            "item_visual_is_part_of_document",
            cls.refs(cls.documents["open"]),
        )
        cls.zone(
            cls.zoned_component,
            [(COMPONENT_ZONE, CANVAS_3, RECT)],
            alias="location_in_document",
        )
        cls.unlocated = cls.new_resource("analysis", "X09 — no zone")
        cls.tile(cls.unlocated, "component_observed", cls.refs(cls.zoned_component))
        cls.lead_white = cls.new_resource("characterization", "Lead white, ground")
        cls.tile_values(
            cls.lead_white,
            "characterization",
            identified_material=cls.reference_value(
                LEAD_WHITE, "lead white", "blanc de plomb"
            ),
        )
        cls.tile(cls.lead_white, "object_observed", cls.refs(cls.zoned_component))
        cls.tile(
            cls.lead_white,
            "evidence_analyses",
            cls.refs(cls.unlocated, cls.analyses["on_document"]),
        )

    def setUp(self):
        super().setUp()
        self.visitor = Client()
        self.doc = str(self.documents["open"].pk)

    def get(self, url):
        response = self.visitor.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.json()

    def page(self, n, version=3):
        return self.get(
            f"/iiif/v{version}/characterization-collection/{self.doc}/page-{n}"
        )

    def vermilion(self):
        (annotation,) = self.page(2)["items"]
        return annotation

    def lead_white_annotation(self):
        wanted = ids.annotation(self.lead_white.pk, COMPONENT_ZONE)
        return next(a for a in self.page(3)["items"] if a["id"] == wanted)

    def bodies(self, annotation, purpose=None, kind="SpecificResource"):
        return [
            b
            for b in annotation["body"]
            if b["type"] == kind and (purpose is None or b.get("purpose") == purpose)
        ]


class AnnotationTests(CharacterizationCase):
    def test_a_material_zone_is_a_classifying_annotation(self):
        annotation = self.vermilion()

        self.assertEqual(annotation["type"], "Annotation")
        self.assertEqual(annotation["motivation"], "classifying")
        self.assertEqual(
            annotation["id"], ids.annotation(self.characterization.pk, OWN_ZONE)
        )
        self.assertEqual(
            annotation["label"], {"en": ["vermilion"], "fr": ["vermillon"]}
        )
        self.assertEqual(annotation["target"]["source"]["id"], CANVAS_2)

    def test_each_language_has_its_own_textual_body(self):
        texts = self.bodies(self.vermilion(), kind="TextualBody")

        self.assertEqual([t["language"] for t in texts], ["en", "fr"])
        for text in texts:
            self.assertEqual(text["purpose"], "describing")
            self.assertEqual(text["format"], "text/plain")
        self.assertIn("vermilion (probable)", texts[0]["value"])
        self.assertIn("red", texts[0]["value"])
        self.assertIn("mercury (major)", texts[0]["value"])
        self.assertIn("sulfur (major)", texts[0]["value"])
        self.assertIn("vermillon (probable)", texts[1]["value"])
        self.assertIn("couche picturale", texts[1]["value"])

    def test_concept_bodies_carry_the_stored_uri_and_every_label(self):
        annotation = self.vermilion()
        by_uri = {
            b["source"]: b for b in self.bodies(annotation) if b["purpose"] != "linking"
        }

        self.assertEqual(
            {uri: b["purpose"] for uri, b in by_uri.items()},
            {
                AAT_VERMILION: "classifying",
                PROBABLE: "assessing",
                AAT_RED: "describing",
                PAINT_LAYER: "describing",
                MERCURY: "describing",
            },
        )
        self.assertEqual(
            by_uri[AAT_VERMILION]["label"], {"en": ["vermilion"], "fr": ["vermillon"]}
        )

    def test_a_concept_without_uri_has_no_body(self):
        labels = [b.get("label", {}).get("en") for b in self.bodies(self.vermilion())]

        self.assertNotIn(["sulfur"], labels)

    def test_evidence_links_point_at_the_cited_zones(self):
        links = [b["source"] for b in self.bodies(self.vermilion(), "linking")]

        self.assertEqual(
            sorted(link["id"] for link in links),
            sorted(
                [
                    ids.annotation(self.analyses["open"].pk, FEATURES["open"]),
                    ids.annotation(
                        self.analyses["on_document"].pk, FEATURES["on_document_1"]
                    ),
                    ids.annotation(
                        self.analyses["on_document"].pk, FEATURES["on_document_3"]
                    ),
                ]
            ),
        )
        self.assertEqual({link["type"] for link in links}, {"Annotation"})

    def test_an_unreadable_cited_analysis_gives_no_link(self):
        self.embargo(self.analyses["open"])

        links = [b["source"]["id"] for b in self.bodies(self.vermilion(), "linking")]

        self.assertTrue(links)
        self.assertFalse(any(str(self.analyses["open"].pk) in link for link in links))

    def test_a_cited_analysis_without_a_zone_is_a_see_also_report(self):
        annotation = self.lead_white_annotation()

        self.assertIn(
            ids.report(self.unlocated.pk),
            [link["id"] for link in annotation["seeAlso"]],
        )
        linked = [b["source"]["id"] for b in self.bodies(annotation, "linking")]
        self.assertFalse(any(str(self.unlocated.pk) in link for link in linked))

    def test_a_material_without_its_own_zone_uses_its_components_zones(self):
        annotation = self.lead_white_annotation()

        self.assertEqual(annotation["target"]["source"]["id"], CANVAS_3)
        self.assertEqual(annotation["target"]["selector"]["type"], "FragmentSelector")

    def test_no_metadata_on_a_characterization(self):
        for annotation in (self.vermilion(), self.lead_white_annotation()):
            with self.subTest(id=annotation["id"]):
                self.assertNotIn("metadata", annotation)

    def test_the_characterization_is_its_own_annotation(self):
        single = self.get(f"/iiif/v3/annotation/{self.characterization.pk}/{OWN_ZONE}")
        first = self.get(f"/iiif/v3/annotation/{self.characterization.pk}")

        self.assertEqual(
            single["id"], ids.annotation(self.characterization.pk, OWN_ZONE)
        )
        self.assertEqual(first["id"], single["id"])
        self.assertEqual(single["motivation"], "classifying")


class AnalysisMaterialsTests(CharacterizationCase):
    def test_the_analysis_annotation_lists_its_identified_materials_per_language(self):
        page = self.get(f"/iiif/v3/annotation-collection/{self.doc}/page-3")
        wanted = ids.annotation(
            self.analyses["on_document"].pk, FEATURES["on_document_3"]
        )
        annotation = next(a for a in page["items"] if a["id"] == wanted)
        materials = next(
            m["value"]
            for m in annotation["metadata"]
            if m["label"]["en"] == ["Identified materials"]
        )

        self.assertEqual(set(materials), {"en", "fr"})
        self.assertEqual(
            sorted(materials["en"][0].split(", ")),
            ["lead white", "vermilion (probable)"],
        )
        self.assertEqual(
            sorted(materials["fr"][0].split(", ")),
            ["blanc de plomb", "vermillon (probable)"],
        )

    def test_an_analysis_cited_by_nothing_has_no_materials_entry(self):
        annotation = self.get(f"/iiif/v3/annotation/{self.analyses['draft'].pk}")

        self.assertNotIn(
            ["Identified materials"],
            [m["label"]["en"] for m in annotation.get("metadata", [])],
        )


class PageTests(CharacterizationCase):
    def test_the_characterization_page_and_collection_are_valid(self):
        collection = self.get(f"/iiif/v3/characterization-collection/{self.doc}")

        self.assertNotIn("items", collection)
        self.assertEqual(collection["total"], 2)
        self.assertEqual(
            collection["first"]["id"], ids.page(self.doc, 2, "characterization")
        )
        self.assertEqual(collection["label"]["en"], ["Identified materials of Ms 59"])
        assert_valid_iiif(self, collection)
        for n in (1, 2, 3):
            with self.subTest(n=n):
                assert_valid_iiif(self, self.page(n))

    def test_the_analysis_pages_keep_only_analyses(self):
        page = self.get(f"/iiif/v3/annotation-collection/{self.doc}/page-2")

        self.assertEqual(page["items"], [])

    def test_the_characterization_page_is_part_of_its_collection(self):
        page = self.page(2)

        self.assertEqual(
            page["partOf"][0]["id"], ids.collection(self.doc, "characterization")
        )
        self.assertEqual(page["next"]["id"], ids.page(self.doc, 3, "characterization"))

    def test_a_hidden_characterization_never_appears(self):
        self.embargo(self.characterization)

        self.assertEqual(self.page(2)["items"], [])
        response = self.visitor.get(
            f"/iiif/v3/annotation/{self.characterization.pk}/{OWN_ZONE}"
        )
        self.assertEqual(response.status_code, 401)

    def test_a_characterization_whose_evidence_is_all_hidden_never_appears(self):
        self.embargo(self.analyses["open"])
        self.embargo(self.analyses["on_document"])

        self.assertEqual(self.page(2)["items"], [])


class V2Tests(CharacterizationCase):
    def test_the_v2_characterization_is_oa_classifying_with_one_content_as_text_per_language(
        self,
    ):
        page = self.page(2, version=2)
        (annotation,) = page["resources"]

        self.assertEqual(page["@type"], "sc:AnnotationList")
        self.assertEqual(
            page["within"]["@id"], ids.collection(self.doc, "characterization", 2)
        )
        self.assertEqual(annotation["motivation"], "oa:classifying")
        texts = [r for r in annotation["resource"] if r["@type"] == "cnt:ContentAsText"]
        self.assertEqual([t["language"] for t in texts], ["en", "fr"])
        concepts = [
            r for r in annotation["resource"] if r["@type"] == "oa:SpecificResource"
        ]
        vermilion = next(c for c in concepts if c["full"]["@id"] == AAT_VERMILION)
        self.assertEqual(vermilion["oa:hasPurpose"], "oa:classifying")
        self.assertIn(
            {"@value": "vermillon", "@language": "fr"}, vermilion["full"]["label"]
        )
        linking = [c for c in concepts if c["oa:hasPurpose"] == "oa:linking"]
        self.assertTrue(linking)
        self.assertTrue(
            all(
                c["full"]["@id"].startswith(ids.annotation_first("", 2))
                for c in linking
            )
        )

    def test_the_v2_layer_lists_the_characterization_pages(self):
        layer = self.get(f"/iiif/v2/characterization-collection/{self.doc}")

        self.assertEqual(
            layer["otherContent"],
            [
                ids.page(self.doc, 2, "characterization", 2),
                ids.page(self.doc, 3, "characterization", 2),
            ],
        )
