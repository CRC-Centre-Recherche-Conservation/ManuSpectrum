"""The v2 (Presentation 2.1 / Open Annotation) routes carry the v3 content.

Usage:
    python manage.py test tests.test_iiif_v2 --settings=tests.test_settings
"""

from django.test import Client, SimpleTestCase, override_settings

from manuspectrum.iiif import ids, v2
from manuspectrum.iiif.constants import IIIF_V2_MEDIA_TYPE
from tests.explorer_fixtures import (
    CANVAS,
    CANVAS_3,
    FEATURES,
    MANIFEST,
    IIIFCase,
)

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
        self.assertEqual(
            project["value"],
            [{"@value": f'<a href="{ids.report(self.projects["main"].pk)}">EMMA</a>'}],
        )

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

    def test_the_v2_rectangle_is_a_fragment_of_its_canvas_within_the_manifest(self):
        analysis = self.analyses["on_document"].pk
        annotation = self.get(
            f"/iiif/v2/annotation/{analysis}/{FEATURES['on_document_3']}"
        )

        on = annotation["on"]
        self.assertEqual(on["@type"], "oa:SpecificResource")
        self.assertEqual(on["full"], "https://example.org/iiif/ms59/canvas/f3r")
        self.assertEqual(on["selector"]["@type"], "oa:FragmentSelector")
        self.assertRegex(on["selector"]["value"], r"^xywh=\d+,\d+,\d+,\d+$")
        self.assertEqual(on["within"]["@type"], "sc:Manifest")
        self.assertEqual(
            annotation["@id"], ids.annotation(analysis, FEATURES["on_document_3"], 2)
        )

    def test_the_human_pages_are_related_and_the_raw_files_renderings(self):
        file_id = self.stored_file(self.analyses["open"], "X01.csv", b"x,y\n1,2\n")
        annotation = self.get(f"/iiif/v2/annotation/{self.analyses['open'].pk}")

        self.assertNotIn("seeAlso", annotation)
        self.assertEqual(
            annotation["related"][0]["@id"], ids.report(self.analyses["open"].pk)
        )
        raw = next(
            r for r in annotation["rendering"] if r["@id"] == ids.data_raw(file_id)
        )
        self.assertEqual(raw["@type"], "dctypes:Dataset")
        self.assertEqual(raw["service"]["profile"], "http://iiif.io/api/auth/1/login")

    def test_a_401_on_a_v2_route_is_a_presentation_2_description(self):
        response = self.visitor.get(
            f"/iiif/v2/annotation/{self.analyses['open'].pk}",
            HTTP_AUTHORIZATION="Bearer nonsense",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response["Content-Type"], f'application/ld+json;profile="{P2}"'
        )
        body = response.json()
        self.assertEqual(body["@context"], P2)
        self.assertEqual(body["@type"], "oa:Annotation")
        self.assertTrue(
            body["@id"].endswith(f"/iiif/v2/annotation/{self.analyses['open'].pk}")
        )
        self.assertEqual(body["service"]["profile"], "http://iiif.io/api/auth/1/login")

    def test_a_401_on_a_v3_route_stays_presentation_3(self):
        response = self.visitor.get(
            f"/iiif/v3/annotation/{self.analyses['open'].pk}",
            HTTP_AUTHORIZATION="Bearer nonsense",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["type"], "Annotation")

    def test_the_v2_file_body_is_a_dataset(self):
        file_id = self.stored_file(self.analyses["open"], "X01.csv", b"x,y\n1,2\n")
        annotation = self.get(f"/iiif/v2/annotation/{self.analyses['open'].pk}")

        body = next(
            r for r in annotation["resource"] if r["@id"] == ids.data_series(file_id)
        )
        self.assertEqual(body["@type"], "dctypes:Dataset")
        self.assertEqual(body["format"], "text/csv")
        self.assertEqual({v["@language"] for v in body["label"]}, {"en", "fr"})


V2_SOURCE = {
    "@context": "http://iiif.io/api/presentation/2/context.json",
    "@id": MANIFEST,
    "@type": "sc:Manifest",
    "label": "Ms 59",
    "sequences": [
        {
            "@type": "sc:Sequence",
            "canvases": [
                {
                    "@id": canvas,
                    "@type": "sc:Canvas",
                    "label": label,
                    "width": 4000,
                    "height": 5000,
                    "images": [
                        {
                            "@type": "oa:Annotation",
                            "motivation": "sc:painting",
                            "on": canvas,
                            "resource": {
                                "@id": f"https://img.example/{label}/full/full/0/default.jpg",
                                "@type": "dctypes:Image",
                                "service": {"@id": f"https://img.example/{label}"},
                            },
                        }
                    ],
                }
                for canvas, label in ((CANVAS, "f1"), (CANVAS_3, "f3"))
            ],
        }
    ],
}


V3_PAINTED = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": MANIFEST,
    "type": "Manifest",
    "label": {"none": ["Ms 59"]},
    "items": [
        {
            "id": canvas,
            "type": "Canvas",
            "label": {"none": [label]},
            "width": 4000,
            "height": 5000,
            "items": [
                {
                    "id": f"{canvas}/page",
                    "type": "AnnotationPage",
                    "items": [
                        {
                            "id": f"{canvas}/painting",
                            "type": "Annotation",
                            "motivation": "painting",
                            "target": canvas,
                            "body": {
                                "id": f"https://img.example/{label}/full/max/0/default.jpg",
                                "type": "Image",
                                "format": "image/jpeg",
                                "service": [
                                    {
                                        "id": f"https://img.example/{label}",
                                        "type": "ImageService2",
                                        "profile": "level1",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
        for canvas, label in ((CANVAS, "f1"), (CANVAS_3, "f3"))
    ],
}


class V2ManifestTests(IIIFCase):
    def setUp(self):
        super().setUp()
        self.doc = str(self.documents["open"].pk)
        self.url = f"/iiif/v2/manifest/{self.doc}"

    def manifest(self):
        response = Client().get(self.url)
        self.assertEqual(response.status_code, 200)
        return response

    def test_v2_route_media_type(self):
        self.assertEqual(self.manifest()["Content-Type"], IIIF_V2_MEDIA_TYPE)

    def test_v2_manifest_shape(self):
        body = self.manifest().json()
        v3 = Client().get(f"/iiif/v3/manifest/{self.doc}").json()

        self.assertEqual(body["@context"], P2)
        self.assertEqual(body["@type"], "sc:Manifest")
        self.assertEqual(body["@id"], ids.as_version(v3["id"], 2))
        self.assertEqual(len(body["sequences"]), 1)
        self.assertEqual(body["sequences"][0]["@type"], "sc:Sequence")
        self.assertEqual(
            [c["@id"] for c in body["sequences"][0]["canvases"]],
            [c["id"] for c in v3["items"]],
        )
        self.assertEqual(body["sequences"][0]["canvases"][0]["@type"], "sc:Canvas")
        self.assertEqual(body["sequences"][0]["canvases"][0]["width"], 4000)
        self.assertIn("attribution", body)
        self.assertEqual(body["related"][0]["@id"], ids.report(self.doc))

    def test_v2_invalid_bearer_is_401(self):
        response = Client().get(self.url, HTTP_AUTHORIZATION="Bearer nope")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"], IIIF_V2_MEDIA_TYPE)

    @override_settings(EXPLORER_MANIFEST_MAX_CANVASES=1)
    def test_v2_over_max_canvases_is_a_bodyless_413(self):
        response = Client().get(self.url)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_v2_image_of_a_v3_source_names_its_service_and_level(self):
        self.fetch.side_effect = lambda url: V3_PAINTED if url == MANIFEST else None
        canvas = self.manifest().json()["sequences"][0]["canvases"][0]
        (image,) = canvas["images"]

        self.assertEqual(image["@type"], "oa:Annotation")
        self.assertEqual(image["motivation"], "sc:painting")
        self.assertEqual(image["on"], CANVAS)
        self.assertEqual(
            image["resource"]["@id"], "https://img.example/f1/full/max/0/default.jpg"
        )
        self.assertEqual(
            image["resource"]["service"],
            {
                "@context": "http://iiif.io/api/image/2/context.json",
                "@id": "https://img.example/f1",
                "profile": "http://iiif.io/api/image/2/level1.json",
            },
        )

    def test_v2_other_content_names_v2_pages(self):
        canvases = self.manifest().json()["sequences"][0]["canvases"]

        self.assertEqual(
            canvases[0]["otherContent"],
            [{"@id": ids.page(self.doc, 1, version=2), "@type": "sc:AnnotationList"}],
        )

    def test_v2_metadata_value_lists(self):
        body = self.manifest().json()

        self.assertTrue(body["metadata"])
        for entry in body["metadata"]:
            self.assertIsInstance(entry["label"], list)
            self.assertIsInstance(entry["value"], list)
            self.assertIn("@value", entry["value"][0])
        self.assertIn("@value", body["description"][0])

    def test_v2_copies_v2_source_canvas(self):
        self.fetch.side_effect = lambda url: V2_SOURCE if url == MANIFEST else None
        canvas = self.manifest().json()["sequences"][0]["canvases"][0]
        source = V2_SOURCE["sequences"][0]["canvases"][0]

        self.assertEqual(canvas["images"], source["images"])
        self.assertEqual(canvas["label"], "f1")

    def test_v2_builds_a_canvas_from_a_v3_source(self):
        canvas = self.manifest().json()["sequences"][0]["canvases"][0]

        self.assertEqual(canvas["@id"], CANVAS)
        self.assertEqual(canvas["height"], 5000)
        self.assertEqual(canvas["images"], [])


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
                "oa:hasPurpose": {"@id": "oa:describing"},
            },
        )
        self.assertEqual(concept["@type"], "oa:SpecificResource")
        self.assertEqual(concept["oa:hasPurpose"], {"@id": "oa:classifying"})
        self.assertEqual(concept["full"]["@id"], "http://vocab.getty.edu/aat/300013526")
        self.assertEqual(
            concept["full"]["label"], [{"@value": "vermilion", "@language": "en"}]
        )
        self.assertEqual(link["oa:hasPurpose"], {"@id": "oa:linking"})
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
