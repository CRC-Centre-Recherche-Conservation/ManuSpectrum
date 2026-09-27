"""The v2 (Presentation 2.1 / Open Annotation) routes carry the v3 content.

Usage:
    python manage.py test tests.test_iiif_v2 --settings=tests.test_settings
"""

from django.test import Client, SimpleTestCase, override_settings

from manuspectrum.iiif import ids, v2
from tests.explorer_fixtures import CANVAS, FEATURES, MANIFEST, IIIFCase

P2 = "http://iiif.io/api/presentation/2/context.json"


class V2RouteTests(IIIFCase):
    def setUp(self):
        super().setUp()
        self.visitor = Client()
        self.doc = str(self.documents["open"].pk)

    def get(self, url):
        response = self.visitor.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.json()

    def test_the_v2_page_is_an_annotation_list_within_its_layer(self):
        page = self.get(f"/iiif/v2/annotation-collection/{self.doc}/page-1")

        self.assertEqual(page["@context"], P2)
        self.assertEqual(page["@type"], "sc:AnnotationList")
        self.assertEqual(page["@id"], ids.page(self.doc, 1, version=2))
        self.assertEqual(page["within"]["@id"], ids.collection(self.doc, version=2))
        self.assertEqual(page["within"]["@type"], "sc:Layer")
        self.assertEqual(len(page["resources"]), 3)
        for annotation in page["resources"]:
            self.assertEqual(annotation["@type"], "oa:Annotation")
            self.assertEqual(annotation["motivation"], "oa:commenting")
            self.assertTrue(annotation["@id"].startswith(ids.annotation_first("", 2)))

    def test_labels_are_value_lists_with_their_language(self):
        page = self.get(f"/iiif/v2/annotation-collection/{self.doc}/page-1")

        self.assertIn(
            {"@value": "Analyses of Ms 59, f. 1v", "@language": "en"}, page["label"]
        )
        self.assertEqual({v["@language"] for v in page["label"]}, {"en", "fr"})

    def test_a_none_value_has_no_language(self):
        annotation = self.get(f"/iiif/v2/annotation/{self.analyses['open'].pk}")

        project = next(
            m
            for m in annotation["metadata"]
            if {"@value": "Project", "@language": "en"} in m["label"]
        )
        self.assertEqual(project["value"], [{"@value": "EMMA"}])

    def test_the_v2_layer_lists_its_pages(self):
        layer = self.get(f"/iiif/v2/annotation-collection/{self.doc}")

        self.assertEqual(layer["@type"], "sc:Layer")
        self.assertEqual(
            layer["otherContent"],
            [ids.page(self.doc, 1, version=2), ids.page(self.doc, 3, version=2)],
        )

    def test_the_v2_point_is_an_oa_choice(self):
        annotation = self.get(f"/iiif/v2/annotation/{self.analyses['open'].pk}")

        self.assertEqual(annotation["on"]["full"], CANVAS)
        self.assertEqual(annotation["on"]["selector"]["@type"], "oa:Choice")
        self.assertEqual(
            annotation["on"]["within"], {"@id": MANIFEST, "@type": "sc:Manifest"}
        )

    def test_the_v2_rectangle_is_a_canvas_fragment(self):
        analysis = self.analyses["on_document"].pk
        annotation = self.get(
            f"/iiif/v2/annotation/{analysis}/{FEATURES['on_document_3']}"
        )

        self.assertRegex(
            annotation["on"],
            r"^https://example.org/iiif/ms59/canvas/f3r#xywh=\d+,\d+,\d+,\d+$",
        )
        self.assertEqual(
            annotation["@id"], ids.annotation(analysis, FEATURES["on_document_3"], 2)
        )

    def test_the_v2_file_body_is_a_dataset(self):
        file_id = self.stored_file(self.analyses["open"], "X01.csv", b"x,y\n1,2\n")
        annotation = self.get(f"/iiif/v2/annotation/{self.analyses['open'].pk}")

        body = next(
            r for r in annotation["resource"] if r["@id"] == ids.data_raw(file_id)
        )
        self.assertEqual(body["@type"], "dctypes:Dataset")
        self.assertEqual(body["format"], "text/csv")
        self.assertEqual({v["@language"] for v in body["label"]}, {"en", "fr"})


@override_settings(IIIF_POINT_RADIUS=12)
class V2ConverterTests(SimpleTestCase):
    """The v2 converter carries concept, linking and ``xyReading`` content (PO ruling of 27/09)."""

    def annotation(self, **extra):
        return {
            "@context": [
                "https://ms.example/iiif/context/xy-reading/1.jsonld",
                "http://iiif.io/api/presentation/3/context.json",
            ],
            "id": ids.annotation("c1", "f1"),
            "type": "Annotation",
            "motivation": "classifying",
            "label": {"en": ["vermilion"], "fr": ["vermillon"]},
            "target": {
                "type": "SpecificResource",
                "source": {
                    "id": CANVAS,
                    "type": "Canvas",
                    "partOf": [{"id": MANIFEST, "type": "Manifest"}],
                },
                "selector": [
                    {"type": "SvgSelector", "value": "<svg/>"},
                    {"type": "FragmentSelector", "value": "xywh=1,2,3,4"},
                ],
            },
            **extra,
        }

    def test_v2_carries_concept_and_linking_bodies_with_their_purpose(self):
        converted = v2.annotation(
            self.annotation(
                body=[
                    {
                        "type": "TextualBody",
                        "purpose": "describing",
                        "value": "vermillon",
                        "language": "fr",
                        "format": "text/plain",
                    },
                    {
                        "type": "SpecificResource",
                        "purpose": "classifying",
                        "source": {
                            "id": "http://vocab.getty.edu/aat/300013526",
                            "label": {"en": ["vermilion"]},
                        },
                    },
                    {
                        "type": "SpecificResource",
                        "purpose": "linking",
                        "source": {
                            "id": ids.annotation("a1", "f1"),
                            "type": "Annotation",
                        },
                    },
                ]
            )
        )

        text, concept, link = converted["resource"]
        self.assertEqual(converted["motivation"], "oa:classifying")
        self.assertEqual(
            text,
            {
                "@type": "cnt:ContentAsText",
                "chars": "vermillon",
                "format": "text/plain",
                "language": "fr",
                "oa:hasPurpose": "oa:describing",
            },
        )
        self.assertEqual(concept["@type"], "oa:SpecificResource")
        self.assertEqual(concept["oa:hasPurpose"], "oa:classifying")
        self.assertEqual(concept["full"]["@id"], "http://vocab.getty.edu/aat/300013526")
        self.assertEqual(
            concept["full"]["label"], [{"@value": "vermilion", "@language": "en"}]
        )
        self.assertEqual(link["oa:hasPurpose"], "oa:linking")
        self.assertEqual(
            link["full"],
            {"@id": ids.annotation("a1", "f1", 2), "@type": "oa:Annotation"},
        )

    def test_v2_keeps_the_xy_reading_of_a_dataset_and_lists_its_context_first(self):
        reading = {"type": "XYReading", "columns": [{"index": 0, "role": "x"}]}
        converted = v2.annotation(
            self.annotation(
                body=[
                    {
                        "id": ids.data_series("f"),
                        "type": "Dataset",
                        "format": "text/csv",
                        "xyReading": reading,
                    }
                ]
            )
        )

        self.assertEqual(converted["resource"][0]["xyReading"], reading)
        self.assertEqual(
            converted["@context"],
            ["https://ms.example/iiif/context/xy-reading/1.jsonld", P2],
        )

    def test_the_v2_polygon_defaults_to_its_fragment(self):
        on = v2.annotation(self.annotation())["on"]

        self.assertEqual(on["selector"]["default"]["value"], "xywh=1,2,3,4")
        self.assertEqual(
            on["selector"]["item"], {"@type": "oa:SvgSelector", "value": "<svg/>"}
        )
