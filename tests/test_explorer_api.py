"""HTTP contract of the Explorer's Corpus APIs.

Usage:
    python manage.py test tests.test_explorer_api --settings="tests.test_settings"
"""

from unittest import mock

from django.http import QueryDict
from django.test import SimpleTestCase

from tests.explorer_contract import assert_shape
from tests.explorer_fixtures import CANVAS, MANIFEST, XY_CONFIG_ID
from tests.test_explorer_service import FORS, XRF, ServiceCase

from manuspectrum.views.explorer_service import (
    imaging_entries,
    layer_of,
    search_payload,
)


class SearchRouteTests(ServiceCase):
    def get(self, query=""):
        return self.client.get(f"/en/api/explorer/search{query}")

    def test_the_visitor_gets_a_public_revalidated_answer_with_an_etag(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, no-cache")
        assert_shape(self, response.json(), "SearchResponse")
        for hit in response.json()["results"]:
            assert_shape(self, hit, "AnalysisHit")
        again = self.client.get(
            "/en/api/explorer/search", HTTP_IF_NONE_MATCH=response["ETag"]
        )
        self.assertEqual(again.status_code, 304)

    def test_a_signed_in_reader_gets_a_private_answer(self):
        self.client.force_login(self.editor)

        response = self.get()

        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotIn("ETag", response)
        self.assertIn("Cookie", response.get("Vary", ""))

    def test_a_filter_on_a_hidden_project_is_ignored_without_leaking_its_name(self):
        self.embargo(self.projects["side"])
        hidden = str(self.projects["side"].pk)

        filtered = self.get(f"?project={hidden}").json()
        unfiltered = self.get().json()

        self.assertEqual(filtered, unfiltered)
        self.assertNotIn("Side project", str(filtered))


MANIFEST_JSON = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": MANIFEST,
    "items": [
        {
            "id": CANVAS,
            "type": "Canvas",
            "label": {"none": ["f. 1v"]},
            "width": 4000,
            "height": 5000,
            "items": [
                {
                    "items": [
                        {
                            "body": {
                                "service": [
                                    {
                                        "id": "https://example.org/iiif/image/f1v",
                                        "type": "ImageService2",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ],
        }
    ],
}
FETCH = "manuspectrum.utils.iiif_tools.CanvasIIIF.fetch_manifest"


class CorpusCase(ServiceCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        point = {"type": "Point", "coordinates": [10, -20]}
        cls.tile(cls.documents["open"], "facsimiles", MANIFEST)
        for key in ("open", "on_document", "draft"):
            cls.tile(
                cls.analyses[key],
                "literal_location_of_analysis",
                cls.annotation_value(CANVAS, point),
            )
        cls.tile(
            cls.analyses["open"],
            "measurement_point_data",
            [
                {
                    "file_id": "11111111-1111-4111-8111-111111111111",
                    "name": "X01_f1v.csv",
                    "size": 4200,
                    "type": "text/csv",
                    "url": "/files/11111111-1111-4111-8111-111111111111",
                    "rendererConfig": XY_CONFIG_ID,
                },
                {
                    "file_id": "22222222-2222-4222-8222-222222222222",
                    "name": "X01_f1v.mca",
                    "size": 900,
                    "type": "",
                    "url": "/files/22222222-2222-4222-8222-222222222222",
                },
            ],
        )
        cls.tile(
            cls.analyses["open"],
            "content_of_statement",
            cls.string_value("<p>260 µm / 100 ms</p>"),
        )
        cls.tile(
            cls.analyses["open"],
            "dataset_url",
            {
                "url": "https://doi.org/10.48579/PRO/ZEEJTH,",
                "url_label": "HEU, S. 2024",
            },
        )


class DocumentRouteTests(CorpusCase):
    def get(self, resource):
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            return self.client.get(f"/en/api/explorer/document/{resource}")

    def test_the_document_payload_has_the_contract_shape(self):
        response = self.get(self.documents["open"].pk)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        assert_shape(self, payload, "DocumentPayload")
        self.assertEqual(
            payload["canvases"][0]["image"]["service"],
            "https://example.org/iiif/image/f1v",
        )
        for annotation in payload["annotations"]:
            assert_shape(self, annotation, "Annotation")
        for summary in payload["characterizations"]:
            assert_shape(self, summary, "CharacterizationSummary")

    def test_the_visitor_sees_no_draft_annotation_and_the_editor_sees_it_marked(self):
        visitor = {
            a["analysis"]
            for a in self.get(self.documents["open"].pk).json()["annotations"]
        }
        self.client.force_login(self.editor)
        editor = self.get(self.documents["open"].pk)

        self.assertNotIn(str(self.analyses["draft"].pk), visitor)
        marked = {a["analysis"]: a["unpublished"] for a in editor.json()["annotations"]}
        self.assertTrue(marked[str(self.analyses["draft"].pk)])
        self.assertEqual(editor["Cache-Control"], "private, no-store")
        self.assertGreater(editor.json()["unpublishedCount"], 0)

    def test_an_analysis_without_a_position_is_listed_as_unlocated_not_dropped(self):
        unplaced = self.new_resource("analysis", "FORS_014 — f. 1v, no zone")
        self.tile(unplaced, "component_observed", self.refs(self.components["open"]))
        self.tile(unplaced, "analysis_by_project", self.refs(self.projects["main"]))

        payload = self.get(self.documents["open"].pk).json()

        self.assertNotIn(
            str(unplaced.pk), {a["analysis"] for a in payload["annotations"]}
        )
        self.assertIn(str(unplaced.pk), {u["analysis"] for u in payload["unlocated"]})
        for item in payload["unlocated"]:
            assert_shape(self, item, "UnlocatedAnalysis")
        self.assertEqual(
            sum(c["analysisCount"] for c in payload["canvases"]),
            len({a["analysis"] for a in payload["annotations"]}),
        )
        search_results = search_payload(QueryDict(""), self.anonymous, "en")["results"]
        self.assertIn(str(unplaced.pk), {r["id"] for r in search_results})

    def test_an_embargoed_document_answers_like_an_unknown_one(self):
        self.embargo(self.documents["embargoed"])

        refused = self.get(self.documents["embargoed"].pk)
        unknown = self.get("00000000-0000-4000-8000-000000000009")

        self.assertEqual((refused.status_code, refused.content), (404, b""))
        self.assertEqual((unknown.status_code, unknown.content), (404, b""))
        self.assertEqual(refused["Cache-Control"], unknown["Cache-Control"])


class AnalysisRouteTests(CorpusCase):
    def get(self, resource):
        return self.client.get(f"/en/api/explorer/analysis/{resource}")

    def test_the_analysis_payload_has_the_contract_shape_and_its_files(self):
        payload = self.get(self.analyses["open"].pk).json()

        assert_shape(self, payload, "AnalysisPayload")
        for entry in payload["files"]:
            assert_shape(self, entry, "FileEntry")
        roles = {f["name"]: (f["role"], f["pairedWith"]) for f in payload["files"]}
        self.assertEqual(
            roles["X01_f1v.csv"],
            ("readable", "22222222-2222-4222-8222-222222222222"),
        )
        self.assertEqual(roles["X01_f1v.mca"][0], "raw")
        self.assertEqual(
            payload["conditions"],
            [{"type": None, "html": "<p>260 µm / 100 ms</p>", "lang": "en"}],
        )
        self.assertEqual(
            payload["dataset"]["url"], "https://doi.org/10.48579/PRO/ZEEJTH"
        )
        self.assertEqual(
            [c["id"] for c in payload["evidenceOf"]], [str(self.characterization.pk)]
        )
        self.assertTrue(
            payload["permalink"].endswith(f"report/{self.analyses['open'].pk}")
        )
        self.assertIsNone(payload["citation"])

    def test_an_analysis_of_an_embargoed_project_answers_like_an_unknown_one(self):
        self.embargo(self.projects["side"])

        refused = self.get(self.analyses["on_document"].pk)
        unknown = self.get("00000000-0000-4000-8000-00000000000a")

        self.assertEqual(
            (refused.status_code, refused.content),
            (unknown.status_code, unknown.content),
        )
        self.assertEqual(refused.status_code, 404)


class LayerOfTests(SimpleTestCase):
    def test_an_element_symbol_gives_an_element_layer(self):
        layer = layer_of(0, "Pb", {"url": None})

        self.assertEqual(layer["kind"], "element")
        self.assertEqual(layer["element"], "Pb")
        self.assertIsNone(layer["band"])

    def test_a_value_and_a_unit_gives_a_band_layer(self):
        nanometres = layer_of(1, "450 nm", {"url": None})
        wavenumber = layer_of(2, "1650 cm-1", {"url": None})

        self.assertEqual(nanometres["kind"], "band")
        self.assertEqual(nanometres["band"], {"value": 450.0, "unit": "nm"})
        self.assertEqual(wavenumber["kind"], "band")
        self.assertEqual(wavenumber["band"], {"value": 1650.0, "unit": "cm⁻¹"})

    def test_anything_else_gives_another_layer_without_an_element(self):
        layer = layer_of(3, "deconv_Pb", {"url": None})

        self.assertEqual(layer["kind"], "other")
        self.assertIsNone(layer["element"])


class ImagingEntriesTests(SimpleTestCase):
    MANIFEST_A = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": "https://example.org/iiif/imaging/a",
        "items": [
            {
                "id": "https://example.org/iiif/imaging/a/canvas/650",
                "type": "Canvas",
                "label": {"none": ["650 nm"]},
            },
            {
                "id": "https://example.org/iiif/imaging/a/canvas/450",
                "type": "Canvas",
                "label": {"none": ["450 nm"]},
            },
        ],
    }
    MANIFEST_B = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": "https://example.org/iiif/imaging/b",
        "items": [
            {
                "id": "https://example.org/iiif/imaging/b/canvas/pb",
                "type": "Canvas",
                "label": {"none": ["Pb"]},
            },
        ],
    }

    def test_layer_indices_continue_across_manifests_and_bands_sort_by_value(self):
        with mock.patch(
            "manuspectrum.views.explorer_service.manifest_json",
            side_effect=[self.MANIFEST_A, self.MANIFEST_B],
        ):
            entries = imaging_entries(
                "00000000-0000-4000-8000-000000000099",
                [
                    "https://example.org/manifest/a",
                    "https://example.org/manifest/b",
                ],
                "en",
            )

        self.assertEqual([len(entry["layers"]) for entry in entries], [2, 1])
        self.assertEqual([layer["index"] for layer in entries[0]["layers"]], [1, 0])
        self.assertEqual(
            [layer["band"]["value"] for layer in entries[0]["layers"]], [450.0, 650.0]
        )
        self.assertEqual(entries[1]["layers"][0]["index"], 2)
        self.assertEqual(entries[1]["layers"][0]["kind"], "element")
