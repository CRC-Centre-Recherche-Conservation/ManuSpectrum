"""HTTP contract of the Explorer's Corpus APIs.

Usage:
    python manage.py test tests.test_explorer_api --settings="tests.test_settings"
"""

from unittest import mock

from django.contrib.auth.models import Group, User
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

    def test_a_draft_analysis_is_found_by_the_visitor_marked_unpublished_in_a_public_answer(
        self,
    ):
        visitor = self.get()
        guest = User.objects.create_user("guest_reader", password="pw")
        guest.groups.add(Group.objects.get(name="Guest"))
        self.client.force_login(guest)
        reader = self.get()

        marked = {r["id"]: r["unpublished"] for r in visitor.json()["results"]}
        self.assertIs(marked[str(self.analyses["draft"].pk)], True)
        self.assertIs(marked[str(self.analyses["open"].pk)], False)
        self.assertGreaterEqual(visitor.json()["unpublishedCount"], 1)
        self.assertEqual(visitor["Cache-Control"], "public, no-cache")
        self.assertEqual(reader.json(), visitor.json())

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

    def test_every_reader_sees_the_draft_annotation_marked_unpublished(self):
        visitor = self.get(self.documents["open"].pk)
        self.client.force_login(self.editor)
        editor = self.get(self.documents["open"].pk)

        for response in (visitor, editor):
            marked = {
                a["analysis"]: a["unpublished"] for a in response.json()["annotations"]
            }
            self.assertIs(marked[str(self.analyses["draft"].pk)], True)
            self.assertIs(marked[str(self.analyses["open"].pk)], False)
            self.assertGreater(response.json()["unpublishedCount"], 0)
        self.assertEqual(visitor["Cache-Control"], "public, no-cache")
        self.assertEqual(editor["Cache-Control"], "private, no-store")

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


class ItemsRouteTests(CorpusCase):
    CSV = "11111111-1111-4111-8111-111111111111"
    IMAGING_MANIFEST = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": "https://example.org/iiif/imaging/x",
        "items": [
            {
                "id": "https://example.org/iiif/imaging/x/canvas/pb",
                "type": "Canvas",
                "label": {"none": ["Pb"]},
            }
        ],
    }

    def get(self, keys):
        return self.client.get("/en/api/explorer/items", {"ids": ",".join(keys)})

    def test_a_readable_file_key_restores_its_item(self):
        key = f"af:{self.analyses['open'].pk}:{self.CSV}"

        payload = self.get([key]).json()

        assert_shape(self, payload, "ItemsResponse")
        self.assertEqual([i["key"] for i in payload["items"]], [key])
        assert_shape(self, payload["items"][0]["analysis"], "AnalysisHit")
        assert_shape(self, payload["items"][0]["file"], "FileEntry")

    def test_an_im_key_restores_its_layer_and_an_unknown_index_is_missing(self):
        self.tile(
            self.analyses["open"],
            "chemical_imaging_manifest",
            "https://example.org/iiif/imaging/x",
        )
        key = f"im:{self.analyses['open'].pk}:0"
        unknown = f"im:{self.analyses['open'].pk}:99"

        with mock.patch(
            "manuspectrum.views.explorer_service.manifest_json",
            return_value=self.IMAGING_MANIFEST,
        ):
            payload = self.get([key, unknown]).json()

        self.assertEqual(payload["missing"], [unknown])
        self.assertEqual([i["kind"] for i in payload["items"]], ["imaging"])
        assert_shape(self, payload["items"][0]["file"], "FileEntry")

    def test_malformed_and_hidden_keys_are_missing_alike(self):
        self.embargo(self.analyses["open"])
        hidden = f"af:{self.analyses['open'].pk}:{self.CSV}"

        payload = self.get(
            [hidden, "nonsense", f"ch:{self.characterization.pk}:-", hidden]
        ).json()

        self.assertEqual(payload["missing"], sorted([hidden, "nonsense"]))
        self.assertEqual([i["kind"] for i in payload["items"]], ["characterization"])

    def test_items_rejects_more_than_thirty_keys(self):
        keys = [f"ch:{i:08d}-0000-4000-8000-000000000000:-" for i in range(31)]

        response = self.get(keys)

        self.assertEqual((response.status_code, response.content), (400, b""))


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
