"""HTTP contract of the Explorer's Corpus APIs.

Usage:
    python manage.py test tests.test_explorer_api --settings="tests.test_settings"
"""

import datetime
import json
import re
from pathlib import Path
from unittest import mock

import bibtexparser

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.db import connection
from django.http import QueryDict
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from arches.app.models.models import NodeGroup, TileModel
from arches.app.utils.permission_backend import assign_perm

from tests.explorer_contract import assert_shape
from tests.explorer_fixtures import (
    CANVAS,
    CANVAS_2,
    CANVAS_3,
    MANIFEST,
    POINT,
    RECT,
    TRIANGLE,
    XY_CONFIG_ID,
    IIIFCase,
)
from tests.test_explorer_service import AZURITE, FORS, XRF, ServiceCase

from manuspectrum.views.explorer import service as explorer_service
from manuspectrum.views.explorer.service import (
    PREVIEW_SIZE,
    imaging_entries,
    layer_of,
    search_payload,
)

DAY_VECTORS = Path(__file__).parent / "fixtures" / "explorer_day_index.json"


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
        for facet in response.json()["facets"]:
            assert_shape(self, facet, "Facet")
            for value in facet["values"]:
                assert_shape(self, value, "FacetValue")
        techniques = [r["technique"] for r in response.json()["results"]]
        self.assertTrue(any(techniques))
        for technique in filter(None, techniques):
            assert_shape(self, technique, "Technique")
        again = self.client.get(
            "/en/api/explorer/search", HTTP_IF_NONE_MATCH=response["ETag"]
        )
        self.assertEqual(again.status_code, 304)

    def test_a_document_thumbnail_is_a_path_on_the_site_that_serves_the_page(self):
        results = self.get("?grain=documents").json()["results"]

        self.assertTrue(results)
        for hit in results:
            assert_shape(self, hit, "DocumentHit")
            self.assertTrue(
                hit["thumbnail"].startswith("/en/thumbnail/"), hit["thumbnail"]
            )

    def test_facets_0_leaves_the_facets_out_and_keeps_the_results(self):
        full = self.get("?grain=analyses").json()
        bare = self.get("?grain=analyses&facets=0")

        assert_shape(self, bare.json(), "SearchResponse")
        self.assertIsNone(bare.json()["facets"])
        self.assertEqual(bare.json()["results"], full["results"])
        self.assertNotEqual(bare["ETag"], self.get("?grain=analyses")["ETag"])

    def test_the_part_facet_lists_its_first_values_and_the_selected_ones(self):
        parts = []
        for n in range(PREVIEW_SIZE + 2):
            part = self.new_resource("component", f"f. {n + 10}r — part {n:02d}")
            self.tile(
                part,
                "item_visual_is_part_of_document",
                self.refs(self.documents["open"]),
            )
            analysis = self.new_resource("analysis", f"P{n:02d}")
            self.tile(analysis, "component_observed", self.refs(part))
            parts.append(str(part.pk))

        full = self.client.get("/en/api/explorer/facet/part").json()
        search = self.get(f"?part={full['values'][-1]['id']}").json()

        facet = next(f for f in search["facets"] if f["key"] == "part")
        assert_shape(self, facet, "Facet")
        self.assertEqual(facet["total"], len(full["values"]))
        self.assertGreater(facet["total"], PREVIEW_SIZE + 1)
        self.assertEqual(
            [v["id"] for v in facet["values"]],
            [v["id"] for v in full["values"][:PREVIEW_SIZE]]
            + [full["values"][-1]["id"]],
        )
        self.assertTrue(set(parts) <= {v["id"] for v in full["values"]})

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

    def test_a_visitor_whose_csrf_cookie_is_renewed_gets_a_private_answer(self):
        self.client.cookies["csrftoken"] = "malformed"

        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotIn("ETag", response)

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


def feature_of(analysis):
    """The feature id of the one zone the fixture stored for *analysis*."""
    for data in TileModel.objects.filter(resourceinstance=analysis).values_list(
        "data", flat=True
    ):
        for value in (data or {}).values():
            if isinstance(value, dict) and value.get("type") == "FeatureCollection":
                return value["features"][0]["id"]
    return None


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


class ReadRightsCase(CorpusCase):
    def deny(self, *roles):
        """Take read access to the nodegroups of *roles* ``(slug, alias)`` away from the visitor."""
        for role in roles:
            nodegroup = NodeGroup.objects.get(pk=self.nodes[role].nodegroup_id)
            with self.captureOnCommitCallbacks(execute=True):
                assign_perm("no_access_to_nodegroup", self.anonymous, nodegroup)

    def document(self, resource):
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            return self.client.get(f"/en/api/explorer/document/{resource}").json()

    def analysis(self, resource):
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            return self.client.get(f"/en/api/explorer/analysis/{resource}")


class ReadRightsTests(ReadRightsCase):
    def test_a_value_nodegroup_the_visitor_cannot_read_leaves_its_values_out(self):
        self.deny(("analysis", "analysis_technique_used"))

        search = self.client.get("/en/api/explorer/search").json()
        payload = self.analysis(self.analyses["open"].pk).json()

        self.assertNotIn("technique", [f["key"] for f in search["facets"]])
        self.assertEqual({r["technique"] for r in search["results"]}, {None})
        self.assertIsNone(payload["technique"])
        self.assertNotIn("Portable XRF", str(payload))

    def test_a_part_nodegroup_the_visitor_cannot_read_leaves_its_facet_out(self):
        component = self.components["open"]
        self.tile(
            component,
            "type",
            self.reference_value("http://vocab/illum", "Illumination"),
        )
        self.tile(
            component,
            "color_features",
            self.reference_value("http://vocab/part-blue", "Blue"),
        )
        shown = self.client.get("/en/api/explorer/search").json()
        self.assertIn("partType", [f["key"] for f in shown["facets"]])

        self.deny(("component", "type"), ("component", "color_features"))
        search = self.client.get("/en/api/explorer/search").json()

        keys = [f["key"] for f in search["facets"]]
        self.assertNotIn("partType", keys)
        self.assertNotIn("partColour", keys)
        self.assertNotIn("Illumination", str(search))

    def test_a_zone_nodegroup_the_visitor_cannot_read_gives_no_zone(self):
        self.tile(
            self.components["open"],
            "location_in_document",
            self.annotation_value(CANVAS, {"type": "Point", "coordinates": [10, -20]}),
        )
        self.deny(("component", "location_in_document"))

        payload = self.document(self.documents["open"].pk)

        self.assertEqual([s["zone"] for s in payload["characterizations"]], [None])
        self.assertEqual([c["characterizationCount"] for c in payload["canvases"]], [0])

    def test_a_person_model_the_visitor_cannot_read_names_no_operator(self):
        self.deny(("person", "label_of_name"))

        search = self.client.get("/en/api/explorer/search").json()
        payload = self.analysis(self.analyses["open"].pk).json()

        self.assertNotIn("operator", [f["key"] for f in search["facets"]])
        self.assertEqual(payload["operators"], [])
        self.assertNotIn("Robinet", str(search) + str(payload))

    def test_an_unreadable_name_nodegroup_gives_the_placeholder_name(self):
        self.deny(("component", "label_of_name"))

        payload = self.analysis(self.analyses["open"].pk).json()

        self.assertEqual(payload["component"]["id"], str(self.components["open"].pk))
        self.assertNotIn("initial", payload["component"]["name"]["value"])

    def test_a_document_of_a_model_the_visitor_cannot_read_is_not_listed(self):
        self.deny(*(role for role in self.nodes if role[0] == "document"))

        search = self.client.get(
            "/en/api/explorer/search",
            {"grain": "documents", "empty": "1"},
        ).json()

        self.assertEqual(search["results"], [])
        self.assertNotIn("Ms 59", str(search))

    def test_an_identifier_nodegroup_the_visitor_cannot_read_gives_no_shelfmark(self):
        self.tile_values(
            self.documents["open"],
            "document",
            value_of_identifier=self.string_value("Latin 8055"),
        )
        self.tile(
            self.documents["open"],
            "content_of_statement",
            self.string_value("A psalter"),
        )
        self.deny(("document", "value_of_identifier"))

        search = self.client.get(
            "/en/api/explorer/search", {"grain": "documents"}
        ).json()

        hit = next(
            r for r in search["results"] if r["id"] == str(self.documents["open"].pk)
        )
        self.assertIsNone(hit["shelfmark"])
        self.assertEqual(hit["description"]["value"], "A psalter")
        self.assertNotIn("Latin 8055", str(search))


class DocumentRouteTests(CorpusCase):
    def get(self, resource, query=""):
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            return self.client.get(f"/en/api/explorer/document/{resource}{query}")

    def by_id(self, payload):
        return {a["id"]: a for a in payload["analyses"]}

    def test_the_document_payload_has_the_contract_shape(self):
        response = self.get(self.documents["open"].pk)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        assert_shape(self, payload, "DocumentPayload")
        self.assertEqual(
            payload["canvases"][0]["image"]["service"],
            "https://example.org/iiif/image/f1v",
        )
        for analysis in payload["analyses"]:
            assert_shape(self, analysis, "DocumentAnalysis")
            for zone in analysis["zones"]:
                assert_shape(self, zone, "AnalysisZone")
        for uri, technique in payload["techniques"].items():
            assert_shape(self, technique, "Technique")
            self.assertEqual(technique["uri"], uri)
        for summary in payload["characterizations"]:
            assert_shape(self, summary, "CharacterizationSummary")
            for evidence in summary["evidence"]:
                assert_shape(self, evidence, "NamedRef")

    def test_each_analysis_names_its_technique_and_its_zones_by_canvas_position(self):
        payload = self.get(self.documents["open"].pk).json()

        mine = self.by_id(payload)[str(self.analyses["open"].pk)]
        self.assertEqual(mine["technique"], XRF)
        self.assertEqual(payload["techniques"][XRF]["label"]["value"], "Portable XRF")
        self.assertEqual([z["canvas"] for z in mine["zones"]], [0])
        self.assertEqual(mine["zones"][0]["shape"]["type"], "point")

    def test_zones_carry_their_feature(self):
        payload = self.get(self.documents["open"].pk).json()

        mine = self.by_id(payload)[str(self.analyses["open"].pk)]
        self.assertEqual(
            [z["feature"] for z in mine["zones"]],
            [feature_of(self.analyses["open"])],
        )

    def test_the_payload_is_the_same_whatever_the_filters(self):
        plain = self.get(self.documents["open"].pk)
        filtered = self.get(self.documents["open"].pk, f"?technique={FORS}&q=x")

        self.assertEqual(filtered.content, plain.content)
        self.assertEqual(filtered["ETag"], plain["ETag"])

    def test_an_identified_material_names_its_evidence(self):
        payload = self.get(self.documents["open"].pk).json()

        summary = next(
            s
            for s in payload["characterizations"]
            if s["id"] == str(self.characterization.pk)
        )
        cited = sorted(str(self.analyses[k].pk) for k in ("open", "on_document"))
        named = {
            r["id"]: r["name"]
            for r in search_payload(QueryDict("size=50"), self.anonymous, "en")[
                "results"
            ]
        }
        self.assertEqual(
            summary["evidence"], [{"id": a, "name": named[a]} for a in cited]
        )

    def test_every_reader_sees_the_draft_analysis_marked_unpublished(self):
        visitor = self.get(self.documents["open"].pk)
        self.client.force_login(self.editor)
        editor = self.get(self.documents["open"].pk)

        for response in (visitor, editor):
            marked = {a["id"]: a["unpublished"] for a in response.json()["analyses"]}
            self.assertIs(marked[str(self.analyses["draft"].pk)], True)
            self.assertIs(marked[str(self.analyses["open"].pk)], False)
            self.assertGreater(response.json()["unpublishedCount"], 0)
        self.assertEqual(visitor["Cache-Control"], "public, no-cache")
        self.assertEqual(editor["Cache-Control"], "private, no-store")

    def test_an_annotation_naming_the_image_service_lands_on_its_canvas(self):
        placed = self.new_resource("analysis", "XRF_021 — f. 1v, by image service")
        self.tile(placed, "component_observed", self.refs(self.components["open"]))
        self.tile(placed, "analysis_by_project", self.refs(self.projects["main"]))
        self.tile(
            placed,
            "literal_location_of_analysis",
            self.annotation_value(
                "https://example.org/iiif/image/f1v",
                {"type": "Point", "coordinates": [10, -20]},
            ),
        )

        payload = self.get(self.documents["open"].pk).json()

        mine = self.by_id(payload)[str(placed.pk)]
        self.assertEqual([z["canvas"] for z in mine["zones"]], [0])
        self.assertEqual(
            payload["canvases"][0]["analysisCount"],
            sum(1 for a in payload["analyses"] if a["zones"]),
        )

    def test_an_analysis_without_a_position_is_listed_without_zones_not_dropped(self):
        unplaced = self.new_resource("analysis", "FORS_014 — f. 1v, no zone")
        self.tile(unplaced, "component_observed", self.refs(self.components["open"]))
        self.tile(unplaced, "analysis_by_project", self.refs(self.projects["main"]))

        payload = self.get(self.documents["open"].pk).json()

        self.assertEqual(self.by_id(payload)[str(unplaced.pk)]["zones"], [])
        self.assertEqual(
            sum(c["analysisCount"] for c in payload["canvases"]),
            sum(1 for a in payload["analyses"] if a["zones"]),
        )
        search_results = search_payload(QueryDict(""), self.anonymous, "en")["results"]
        self.assertIn(str(unplaced.pk), {r["id"] for r in search_results})

    def test_an_identified_material_on_another_component_of_the_document_is_shown(
        self,
    ):
        second = self.new_resource("component", "f. 2r — border")
        self.tile(
            second,
            "item_visual_is_part_of_document",
            self.refs(self.documents["open"]),
        )
        vermilion = self.new_resource("characterization", "Vermilion, red border")
        self.tile(vermilion, "object_observed", self.refs(second))
        self.tile(vermilion, "evidence_analyses", self.refs(self.analyses["open"]))

        payload = self.get(self.documents["open"].pk).json()

        self.assertIn(
            str(vermilion.pk), {s["id"] for s in payload["characterizations"]}
        )

    def test_a_sample_used_by_an_analysis_of_the_document_is_listed_with_its_zone(
        self,
    ):
        self.tile(
            self.samples["s1"],
            "location_in_object_of_sampling_taking",
            self.annotation_value(
                CANVAS,
                {
                    "type": "Polygon",
                    "coordinates": [[[10, -20], [30, -20], [30, -40], [10, -20]]],
                },
            ),
        )

        payload = self.get(self.documents["open"].pk).json()

        self.assertEqual(
            [s["id"] for s in payload["samples"]], [str(self.samples["s1"].pk)]
        )
        sample = payload["samples"][0]
        assert_shape(self, sample, "SampleSummary")
        self.assertEqual(sample["name"]["value"], "S1")
        self.assertEqual(sample["zone"]["canvas"], CANVAS)
        self.assertEqual(sample["zone"]["shape"]["type"], "polygon")
        self.assertEqual(sample["analyses"], [str(self.analyses["open"].pk)])
        self.assertIs(sample["unpublished"], False)

    def test_a_sample_of_a_hidden_analysis_is_not_listed(self):
        hidden = self.new_resource("analysis", "X04 — f. 1v, embargoed")
        self.tile(hidden, "component_observed", self.refs(self.components["open"]))
        s2 = self.new_resource("sample", "S2")
        self.tile(hidden, "sample_used", self.refs(s2))
        self.embargo(hidden)

        payload = self.get(self.documents["open"].pk).json()

        self.assertNotIn(str(s2.pk), {s["id"] for s in payload["samples"]})
        self.assertNotIn("S2", str(payload["samples"]))

    def test_a_sample_zone_naming_the_image_service_lands_on_its_canvas(self):
        self.tile(
            self.samples["s1"],
            "location_in_object_of_sampling_taking",
            self.annotation_value(
                "https://example.org/iiif/image/f1v",
                {"type": "Point", "coordinates": [10, -20]},
            ),
        )

        payload = self.get(self.documents["open"].pk).json()

        self.assertEqual([s["zone"]["canvas"] for s in payload["samples"]], [CANVAS])

    def test_a_zone_on_a_canvas_the_manifest_does_not_list_is_left_out(self):
        elsewhere = self.new_resource("analysis", "XRF_030 — another manifest")
        self.tile(elsewhere, "component_observed", self.refs(self.components["open"]))
        self.tile(
            elsewhere,
            "literal_location_of_analysis",
            self.annotation_value(
                "https://example.org/iiif/other/canvas/9",
                {"type": "Point", "coordinates": [10, -20]},
            ),
        )

        payload = self.get(self.documents["open"].pk).json()

        self.assertEqual(self.by_id(payload)[str(elsewhere.pk)]["zones"], [])

    def test_an_embargoed_document_answers_like_an_unknown_one(self):
        self.embargo(self.documents["embargoed"])

        for suffix in ("", "/match"):
            refused = self.get(self.documents["embargoed"].pk, suffix)
            unknown = self.get("00000000-0000-4000-8000-000000000009", suffix)

            self.assertEqual((refused.status_code, refused.content), (404, b""))
            self.assertEqual((unknown.status_code, unknown.content), (404, b""))
            self.assertEqual(refused["Cache-Control"], unknown["Cache-Control"])


class DocumentComponentsTests(IIIFCase):
    COMPONENT_ZONE = "location_in_document"

    def payload(self):
        return self.client.get(f"/en/api/explorer/document/{self.documents['open'].pk}")

    def component(self, name, zones, document=None):
        found = self.new_resource("component", name)
        self.tile(
            found,
            "item_visual_is_part_of_document",
            self.refs(document or self.documents["open"]),
        )
        if zones:
            self.zone(found, zones, alias=self.COMPONENT_ZONE)
        return found

    def test_components_list_their_own_zones_by_canvas_position(self):
        initial = "0b0b0b0b-0000-4000-8000-000000000001"
        initial_3 = "0b0b0b0b-0000-4000-8000-000000000002"
        self.zone(
            self.components["open"],
            [(initial_3, CANVAS_3, RECT), (initial, CANVAS, TRIANGLE)],
            alias=self.COMPONENT_ZONE,
        )
        border = self.component(
            "f. 2r — border",
            [("0b0b0b0b-0000-4000-8000-000000000003", CANVAS_2, POINT)],
        )

        response = self.payload()

        payload = response.json()
        assert_shape(self, payload, "DocumentPayload")
        for component in payload["components"]:
            assert_shape(self, component, "DocumentComponent")
            for zone in component["zones"]:
                assert_shape(self, zone, "AnalysisZone")
        self.assertEqual(
            [c["id"] for c in payload["components"]],
            [str(self.components["open"].pk), str(border.pk)],
        )
        first = payload["components"][0]
        self.assertEqual(first["name"]["value"], "f. 1v — initial")
        self.assertEqual(
            [(z["canvas"], z["feature"], z["shape"]["type"]) for z in first["zones"]],
            [(0, initial, "polygon"), (2, initial_3, "rect")],
        )
        self.assertEqual([z["canvas"] for z in payload["components"][1]["zones"]], [1])

    def test_components_on_the_same_first_page_are_ordered_by_name(self):
        later = self.component(
            "f. 2r — border",
            [("0b0b0b0b-0000-4000-8000-000000000004", CANVAS_2, POINT)],
        )
        sooner = self.component(
            "Band, f. 2r", [("0b0b0b0b-0000-4000-8000-000000000005", CANVAS_2, POINT)]
        )

        payload = self.payload().json()

        self.assertEqual(
            [c["id"] for c in payload["components"]], [str(sooner.pk), str(later.pk)]
        )

    def test_a_component_without_a_zone_on_the_pages_is_left_out(self):
        self.component("f. 5r — no zone", [])
        self.component(
            "Elsewhere",
            [
                (
                    "0b0b0b0b-0000-4000-8000-000000000006",
                    "https://example.org/iiif/other/canvas/9",
                    POINT,
                )
            ],
        )

        self.assertEqual(self.payload().json()["components"], [])

    def test_a_component_of_another_document_is_not_listed(self):
        self.zone(
            self.components["embargoed"],
            [("0b0b0b0b-0000-4000-8000-000000000007", CANVAS, POINT)],
            alias=self.COMPONENT_ZONE,
        )

        self.assertEqual(self.payload().json()["components"], [])

    def test_a_restricted_component_is_never_listed(self):
        self.zone(
            self.components["open"],
            [("0b0b0b0b-0000-4000-8000-000000000008", CANVAS, POINT)],
            alias=self.COMPONENT_ZONE,
        )
        self.embargo(self.components["open"])

        payload = self.payload().json()

        self.assertEqual(payload["components"], [])
        self.assertNotIn(str(self.components["open"].pk), json.dumps(payload))

    def test_a_zone_nodegroup_the_visitor_cannot_read_lists_no_component(self):
        self.zone(
            self.components["open"],
            [("0b0b0b0b-0000-4000-8000-000000000009", CANVAS, POINT)],
            alias=self.COMPONENT_ZONE,
        )
        nodegroup = NodeGroup.objects.get(
            pk=self.nodes[("component", self.COMPONENT_ZONE)].nodegroup_id
        )
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm("no_access_to_nodegroup", self.anonymous, nodegroup)

        self.assertEqual(self.payload().json()["components"], [])

    def test_the_query_count_does_not_grow_with_the_components(self):
        def queries():
            self.payload()
            with CaptureQueriesContext(connection) as captured:
                response = self.payload()
            self.assertEqual(response.status_code, 200)
            return len(
                [
                    q
                    for q in captured.captured_queries
                    if not re.search(r"silk_|SAVEPOINT|^EXPLAIN", q["sql"])
                ]
            )

        self.component(
            "Part 1", [("0b0b0b0b-0000-4000-8000-00000000000a", CANVAS, POINT)]
        )
        one = queries()
        for n in range(3):
            self.component(
                f"Part {n + 2}",
                [(f"0b0b0b0b-0000-4000-8000-00000000001{n}", CANVAS_2, POINT)],
            )
        many = queries()

        self.assertEqual(len(self.payload().json()["components"]), 4)
        self.assertEqual(many, one)


class DocumentMatchRouteTests(CorpusCase):
    def get(self, resource, query=""):
        return self.client.get(f"/en/api/explorer/document/{resource}/match{query}")

    def test_the_match_has_the_contract_shape(self):
        response = self.get(self.documents["open"].pk, f"?technique={XRF}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, no-cache")
        payload = response.json()
        assert_shape(self, payload, "DocumentMatch")
        for facet in payload["facets"]:
            assert_shape(self, facet, "Facet")
            for value in facet["values"]:
                assert_shape(self, value, "FacetValue")
        self.assertEqual(payload["kept"]["analyses"], [str(self.analyses["open"].pk)])

    def test_the_match_without_a_filter_keeps_every_analysis_as_null(self):
        response = self.get(self.documents["open"].pk)

        payload = response.json()
        assert_shape(self, payload, "DocumentMatch")
        assert_shape(self, payload["kept"], "MatchKept")
        self.assertIsNone(payload["kept"]["analyses"])
        self.assertGreater(payload["total"], 0)

    def test_the_match_and_the_search_keep_the_same_analyses(self):
        query = f"?technique={XRF}"
        search = self.client.get(
            f"/en/api/explorer/search{query}&grain=analyses&size=50"
        ).json()
        kept = self.get(self.documents["open"].pk, query).json()["kept"]["analyses"]

        found = {
            r["id"]
            for r in search["results"]
            if r["document"]["id"] == str(self.documents["open"].pk)
        }
        self.assertTrue(kept)
        self.assertEqual(set(kept), found)

    def test_grain_page_and_size_do_not_change_the_answer(self):
        plain = self.get(self.documents["open"].pk, f"?material={AZURITE}")
        paged = self.get(
            self.documents["open"].pk,
            f"?material={AZURITE}&grain=documents&page=4&size=50&empty=1",
        )

        self.assertEqual(paged.content, plain.content)
        self.assertEqual(paged["ETag"], plain["ETag"])

    def test_a_restricted_value_nodegroup_leaves_its_facet_out(self):
        nodegroup = NodeGroup.objects.get(
            pk=self.nodes[("analysis", "analysis_technique_used")].nodegroup_id
        )
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm("no_access_to_nodegroup", self.anonymous, nodegroup)

        payload = self.get(self.documents["open"].pk).json()

        self.assertNotIn("technique", [f["key"] for f in payload["facets"]])
        self.assertNotIn("Portable XRF", str(payload))


class AnalysisRouteTests(CorpusCase):
    def setUp(self):
        super().setUp()
        fetch = mock.patch(FETCH, return_value=MANIFEST_JSON)
        fetch.start()
        self.addCleanup(fetch.stop)

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
        viewers = {f["name"]: f["viewer"] for f in payload["files"]}
        self.assertEqual(viewers["X01_f1v.csv"]["presetKey"], "xrf")
        self.assertEqual(viewers["X01_f1v.csv"]["configName"], "XRF — energy / counts")
        self.assertIsNone(viewers["X01_f1v.mca"]["presetKey"])
        self.assertIsNone(viewers["X01_f1v.mca"]["configName"])
        self.assertEqual(
            payload["conditions"],
            [{"type": None, "html": "<p>260 µm / 100 ms</p>", "lang": "en"}],
        )
        self.assertEqual(
            payload["dataset"]["url"], "https://doi.org/10.48579/PRO/ZEEJTH"
        )
        self.assertEqual(
            payload["evidenceOf"],
            [
                {
                    "id": str(self.characterization.pk),
                    "name": {"value": "Azurite, blue ground", "lang": "en"},
                }
            ],
        )
        for entry in payload["evidenceOf"]:
            assert_shape(self, entry, "NamedRef")
        self.assertTrue(
            payload["permalink"].endswith(f"report/{self.analyses['open'].pk}")
        )
        assert_shape(self, payload["citation"], "Citation")

    def test_the_analysis_carries_its_citation(self):
        analysis = str(self.analyses["open"].pk)

        payload = self.get(analysis).json()

        permalink = f"{settings.PUBLIC_SERVER_ADDRESS}report/{analysis}"
        citation = payload["citation"]
        self.assertEqual(set(citation), {"text", "bibtex"})
        fields = bibtexparser.parse_string(citation["bibtex"]).entries[0].fields_dict
        self.assertTrue(citation["bibtex"].startswith("@dataset{robinetnd"))
        self.assertEqual(fields["doi"].value, "10.48579/pro/zeejth")
        self.assertEqual(fields["title"].value, "HEU, S. 2024")
        self.assertEqual(fields["author"].value, "Robinet, L.")
        self.assertIn("Project: EMMA", fields["note"].value)
        self.assertIn(f"({permalink})", fields["note"].value)
        for text in ("Robinet, L.", "HEU, S. 2024", "EMMA", "doi.org/10.48579"):
            self.assertIn(text, citation["text"])
        self.assertIn(permalink, payload["availability"])
        self.assertIn("https://doi.org/10.48579/PRO/ZEEJTH", payload["availability"])

    def test_an_analysis_without_dataset_is_cited_as_its_record(self):
        analysis = str(self.analyses["on_document"].pk)

        citation = self.get(analysis).json()["citation"]

        fields = bibtexparser.parse_string(citation["bibtex"]).entries[0].fields_dict
        self.assertEqual(fields["title"].value, r"FORS\_009 {\textemdash} f. 1v")
        self.assertEqual(fields["publisher"].value, settings.APP_TITLE)
        self.assertEqual(
            fields["url"].value, f"{settings.PUBLIC_SERVER_ADDRESS}report/{analysis}"
        )
        self.assertNotIn("doi", fields)
        self.assertTrue(citation["text"].startswith("FORS_009 — f. 1v [Dataset]"))

    def test_the_analysis_names_its_manifest_by_absolute_url(self):
        analysis = str(self.analyses["open"].pk)

        english = self.get(analysis).json()["manifest"]
        french = self.client.get(f"/fr/api/explorer/analysis/{analysis}").json()

        self.assertEqual(
            english,
            f"{settings.PUBLIC_SERVER_ADDRESS}iiif/v3/explorer-manifest"
            f"?ids=an:{analysis}:-",
        )
        self.assertEqual(french["manifest"], english)

    def test_the_analysis_lists_one_content_state_per_located_zone(self):
        analysis = str(self.analyses["open"].pk)

        payload = self.get(analysis).json()

        state = (
            f"{settings.PUBLIC_SERVER_ADDRESS}iiif/v3/content-state/"
            f"{analysis}/{feature_of(self.analyses['open'])}"
        )
        self.assertEqual(
            payload["contentStates"],
            [
                {
                    "feature": feature_of(self.analyses["open"]),
                    "url": state,
                }
            ],
        )
        for entry in payload["contentStates"]:
            assert_shape(self, entry, "ContentStateLink")

    def test_an_instrument_file_without_configuration_is_a_raw_file(self):
        self.tile(
            self.analyses["on_document"],
            "measurement_point_data",
            [
                {
                    "file_id": "33333333-3333-4333-8333-333333333333",
                    "name": "FORS_009.asd",
                    "size": 900,
                    "type": "",
                    "url": "/files/33333333-3333-4333-8333-333333333333",
                },
                {
                    "file_id": "44444444-4444-4444-8444-444444444444",
                    "name": "FORS_009.spa",
                    "size": 900,
                    "type": "",
                    "url": "/files/44444444-4444-4444-8444-444444444444",
                },
            ],
        )

        payload = self.get(self.analyses["on_document"].pk).json()

        files = {f["name"]: f for f in payload["files"]}
        self.assertEqual(
            (files["FORS_009.asd"]["role"], files["FORS_009.asd"]["dataKind"]),
            ("raw", "file"),
        )
        self.assertFalse(files["FORS_009.asd"]["previewUrl"])
        self.assertEqual(
            (files["FORS_009.spa"]["role"], files["FORS_009.spa"]["dataKind"]),
            ("raw", "file"),
        )

    def test_an_analysis_without_a_located_zone_lists_no_content_state(self):
        payload = self.get(self.analyses["embargoed"].pk).json()

        self.assertEqual(payload["contentStates"], [])

    def test_an_analysis_placing_no_canvas_names_no_manifest(self):
        payload = self.get(self.analyses["embargoed"].pk).json()

        assert_shape(self, payload, "AnalysisPayload")
        self.assertIsNone(payload["manifest"])

    def test_the_report_link_is_a_path_in_the_language_of_the_request(self):
        analysis = self.analyses["open"].pk

        english = self.get(analysis).json()
        french = self.client.get(f"/fr/api/explorer/analysis/{analysis}").json()

        self.assertEqual(english["reportUrl"], f"/en/report/{analysis}")
        self.assertEqual(french["reportUrl"], f"/fr/report/{analysis}")

    def test_a_local_file_link_is_a_path_on_the_site(self):
        files = self.get(self.analyses["open"].pk).json()["files"]

        for entry in files:
            self.assertTrue(entry["downloadUrl"].startswith("/files/"), entry)
            if entry["previewUrl"]:
                self.assertTrue(entry["previewUrl"].startswith("/"), entry)
                self.assertFalse(entry["previewUrl"].startswith("//"), entry)

    def test_an_operator_whose_resource_is_gone_is_left_out(self):
        gone = "00000000-0000-4000-8000-0000000000de"
        self.tile(self.analyses["open"], "performed_by_actor", [{"resourceId": gone}])

        response = self.get(self.analyses["open"].pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [o["id"] for o in response.json()["operators"]], [str(self.operator.pk)]
        )

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
            "manuspectrum.views.explorer.service.manifest_json",
            return_value=self.IMAGING_MANIFEST,
        ):
            payload = self.get([key, unknown]).json()

        self.assertEqual(payload["missing"], [unknown])
        self.assertEqual([i["kind"] for i in payload["items"]], ["imaging"])
        assert_shape(self, payload["items"][0]["file"], "FileEntry")

    def test_an_an_key_restores_the_whole_analysis_with_the_files_it_shows(self):
        key = f"an:{self.analyses['open'].pk}:-"

        payload = self.get([key]).json()

        self.assertEqual(payload["missing"], [])
        item = payload["items"][0]
        assert_shape(self, item, "AnalysisItem")
        self.assertEqual((item["key"], item["kind"]), (key, "analysis"))
        self.assertEqual(item["analysis"]["id"], str(self.analyses["open"].pk))
        self.assertEqual([f["id"] for f in item["files"]], [self.CSV])
        for entry in item["files"]:
            assert_shape(self, entry, "FileEntry")
        viewer = item["files"][0]["viewer"]
        self.assertEqual(
            (viewer["presetKey"], viewer["configName"]),
            ("xrf", "XRF — energy / counts"),
        )

    def statement(self, analysis, text):
        self.tile(analysis, "content_of_statement", self.string_value(text))

    def test_an_analysis_item_carries_the_excitation_read_from_its_statements(self):
        analysis = self.analyses["open"]
        self.statement(analysis, "<p>Tube Ag, 40 kV</p>")
        keys = [f"an:{analysis.pk}:-", f"af:{analysis.pk}:{self.CSV}"]

        items = self.get(keys).json()["items"]

        expected = {"anode": "Ag", "kV": 40, "source": "conditions"}
        self.assertEqual([i["excitation"] for i in items], [expected] * 2)

    def test_an_analysis_without_excitation_text_gives_null(self):
        key = f"an:{self.analyses['open'].pk}:-"

        item = self.get([key]).json()["items"][0]

        assert_shape(self, item, "AnalysisItem")
        self.assertIsNone(item["excitation"])

    def test_a_statement_nodegroup_the_visitor_cannot_read_gives_null_excitation(self):
        self.statement(self.analyses["open"], "<p>Tube Ag, 40 kV</p>")
        self.restrict_nodegroup(
            self.nodes[("analysis", "content_of_statement")].nodegroup_id,
            self.editor,
        )

        item = self.get([f"an:{self.analyses['open'].pk}:-"]).json()["items"][0]

        self.assertIsNone(item["excitation"])

    def test_reading_the_excitation_adds_no_query(self):
        analysis = self.analyses["open"]
        keys = [f"an:{analysis.pk}:-", f"af:{analysis.pk}:{self.CSV}"]

        def warm_queries():
            self.get(keys)
            with CaptureQueriesContext(connection) as captured:
                payload = self.get(keys).json()
            return payload, [q["sql"] for q in captured if "silk_" not in q["sql"]]

        _, without = warm_queries()
        self.statement(analysis, "<p>Tube Ag, 40 kV</p>")
        payload, with_excitation = warm_queries()

        self.assertEqual(payload["items"][0]["excitation"]["anode"], "Ag")
        self.assertEqual(len(with_excitation), len(without), "\n".join(with_excitation))

    def test_an_analysis_with_nothing_to_show_is_still_an_item(self):
        key = f"an:{self.analyses['on_document'].pk}:-"

        payload = self.get([key]).json()

        self.assertEqual(payload["missing"], [])
        self.assertEqual(payload["items"][0]["files"], [])

    def test_an_imaging_manifest_comes_with_its_layers_in_the_analysis_item(self):
        self.tile(
            self.analyses["open"],
            "chemical_imaging_manifest",
            "https://example.org/iiif/imaging/x",
        )

        with mock.patch(
            "manuspectrum.views.explorer.service.manifest_json",
            return_value=self.IMAGING_MANIFEST,
        ):
            payload = self.get([f"an:{self.analyses['open'].pk}:-"]).json()

        files = payload["items"][0]["files"]
        self.assertEqual([f["dataKind"] for f in files], ["xy", "chemical-imaging"])
        self.assertEqual([layer["label"] for layer in files[1]["layers"]], ["Pb"])
        for layer in files[1]["layers"]:
            assert_shape(self, layer, "FileLayer")

    LAYER_MANIFEST = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": "https://example.org/iiif/imaging/x",
        "items": [
            {
                "id": "https://example.org/iiif/imaging/x/canvas/pb",
                "type": "Canvas",
                "label": {"none": ["Pb map"]},
            },
            {
                "id": "https://example.org/iiif/imaging/x/canvas/650",
                "type": "Canvas",
                "label": {"none": ["650 nm"]},
            },
        ],
    }
    LAYER_CANVASES = {
        "pb": "https://example.org/iiif/imaging/x/canvas/pb",
        "650": "https://example.org/iiif/imaging/x/canvas/650",
    }

    def layer_files(self, manifest=None):
        node = self.nodes[("analysis", "chemical_imaging_manifest")]
        if not TileModel.objects.filter(
            resourceinstance=self.analyses["open"], nodegroup_id=node.nodegroup_id
        ).exists():
            self.tile(
                self.analyses["open"],
                "chemical_imaging_manifest",
                "https://example.org/iiif/imaging/x",
            )
        with mock.patch(
            "manuspectrum.views.explorer.service.manifest_json",
            return_value=manifest or self.LAYER_MANIFEST,
        ):
            payload = self.get([f"an:{self.analyses['open'].pk}:-"]).json()
        return payload["items"][0]["files"][-1]["layers"]

    def layer_tile(self, canvas, **values):
        return self.tile_values(
            self.analyses["open"],
            "analysis",
            imaging_layer_canvas=canvas,
            **values,
        )

    def ref(self, uri, en, fr=None, alt=None):
        return self.reference_value(uri, en, fr, alt=alt)

    def test_a_layer_tile_fills_content_elements_band_and_processing(self):
        lead = self.ref("https://example.org/el/lead", "Lead", "Plomb", alt="Pb")
        self.layer_tile(
            self.LAYER_CANVASES["pb"],
            imaging_layer_label="Pb map",
            imaging_layer_content=self.ref(
                "https://example.org/c/element", "Element distribution"
            ),
            imaging_layer_elements=lead,
            imaging_layer_emission_line=self.ref("https://example.org/l/la", "Lα"),
            imaging_layer_processing_method=self.ref(
                "https://example.org/m/pca",
                "Principal component analysis",
                alt="PCA",
            ),
            imaging_layer_component_index=2,
            imaging_layer_processing_inputs="  a, b ",
            imaging_layer_note=self.string_value("  A note  "),
        )
        self.layer_tile(
            self.LAYER_CANVASES["650"],
            imaging_layer_content=self.ref("https://example.org/c/band", "Band"),
            imaging_layer_band_value=650.0,
            imaging_layer_band_lower=640,
            imaging_layer_band_upper=660,
            imaging_layer_band_unit=self.ref(
                "https://example.org/u/nm", "Nanometre", alt="nm"
            ),
        )

        pb, band = self.layer_files()

        assert_shape(self, pb, "FileLayer")
        assert_shape(self, band, "FileLayer")
        self.assertEqual(
            (pb["index"], pb["id"], pb["label"]),
            (0, self.LAYER_CANVASES["pb"], "Pb map"),
        )
        self.assertEqual(pb["content"]["label"]["value"], "Element distribution")
        self.assertEqual(
            [(e["value"]["label"]["value"], e["symbol"]) for e in pb["elements"]],
            [("Lead", "Pb")],
        )
        assert_shape(self, pb["elements"][0], "LayerElement")
        self.assertEqual(pb["emissionLine"]["label"]["value"], "Lα")
        self.assertIsNone(pb["band"])
        assert_shape(self, pb["processing"], "LayerProcessing")
        self.assertEqual(
            (
                pb["processing"]["method"]["label"]["value"],
                pb["processing"]["index"],
                pb["processing"]["inputs"],
            ),
            ("Principal component analysis", 2, "a, b"),
        )
        assert_shape(self, pb["processing"]["method"], "LayerMethod")
        self.assertEqual(pb["processing"]["method"]["symbol"], "PCA")
        self.assertEqual(pb["note"], "A note")
        assert_shape(self, band["band"], "LayerBand")
        self.assertEqual(
            (band["band"]["value"], band["band"]["lower"], band["band"]["upper"]),
            (650, 640, 660),
        )
        assert_shape(self, band["band"]["unit"], "LayerUnit")
        self.assertEqual(band["band"]["unit"]["label"]["value"], "Nanometre")
        self.assertEqual(band["band"]["unit"]["symbol"], "nm")
        self.assertEqual(
            (band["elements"], band["emissionLine"], band["processing"], band["note"]),
            ([], None, None, None),
        )

    def test_a_band_unit_without_alternative_label_has_no_symbol(self):
        self.layer_tile(
            self.LAYER_CANVASES["650"],
            imaging_layer_content=self.ref("https://example.org/c/band", "Band"),
            imaging_layer_band_value=650,
            imaging_layer_band_unit=self.ref("https://example.org/u/nm", "Nanometre"),
        )

        _, band = self.layer_files()

        assert_shape(self, band["band"]["unit"], "LayerUnit")
        self.assertEqual(band["band"]["unit"]["label"]["value"], "Nanometre")
        self.assertIsNone(band["band"]["unit"]["symbol"])

    def test_a_processing_method_without_alternative_label_has_no_symbol(self):
        self.layer_tile(
            self.LAYER_CANVASES["pb"],
            imaging_layer_content=self.ref("https://example.org/c/comp", "Component"),
            imaging_layer_processing_method=self.ref(
                "https://example.org/m/deconv", "Deconvolution / fitting"
            ),
            imaging_layer_component_index=1,
        )

        pb, _ = self.layer_files()

        assert_shape(self, pb["processing"]["method"], "LayerMethod")
        self.assertEqual(
            pb["processing"]["method"]["label"]["value"], "Deconvolution / fitting"
        )
        self.assertIsNone(pb["processing"]["method"]["symbol"])

    def test_all_layers_unclassified_when_no_tile_exists(self):
        layers = self.layer_files()

        self.assertEqual([layer["index"] for layer in layers], [0, 1])
        self.assertEqual(
            [layer["id"] for layer in layers], list(self.LAYER_CANVASES.values())
        )
        for layer in layers:
            assert_shape(self, layer, "FileLayer")
            self.assertEqual(
                (
                    layer["content"],
                    layer["elements"],
                    layer["emissionLine"],
                    layer["band"],
                    layer["processing"],
                    layer["note"],
                ),
                (None, [], None, None, None, None),
            )
        self.assertEqual([layer["label"] for layer in layers], ["Pb map", "650 nm"])

    def test_some_layers_classified_and_a_content_only_tile(self):
        self.layer_tile(
            self.LAYER_CANVASES["650"],
            imaging_layer_content=self.ref("https://example.org/c/video", "Video"),
        )

        first, second = self.layer_files()

        self.assertEqual(
            (first["content"], first["elements"], first["band"]), (None, [], None)
        )
        self.assertEqual(second["content"]["label"]["value"], "Video")
        self.assertEqual(
            (second["elements"], second["band"], second["processing"]),
            ([], None, None),
        )
        self.assertEqual(second["label"], "650 nm")

    def test_layer_nodegroup_unreadable_reads_as_unclassified(self):
        self.layer_tile(
            self.LAYER_CANVASES["pb"],
            imaging_layer_content=self.ref("https://example.org/c/el", "Element"),
        )
        self.restrict_nodegroup(
            self.nodes[("analysis", "imaging_layer_canvas")].nodegroup_id,
            self.editor,
        )

        layers = self.layer_files()

        self.assertEqual([layer["content"] for layer in layers], [None, None])
        self.assertEqual([layer["label"] for layer in layers], ["Pb map", "650 nm"])

    def legacy_case(self, tile_host, manifest_host):
        canvas = "/iiif/manifest/canvas/pb.json"
        manifest = {
            **self.LAYER_MANIFEST,
            "items": [
                {"id": f"http://{manifest_host}{canvas}", "type": "Canvas"},
            ],
        }
        self.layer_tile(
            f"http://{tile_host}{canvas}",
            imaging_layer_content=self.ref("https://example.org/c/el", "Element"),
        )
        return self.layer_files(manifest)

    def test_imaging_entries_matches_a_layer_tile_stored_under_a_legacy_host(self):
        new_host = settings.PUBLIC_SERVER_ADDRESS.split("//", 1)[1].strip("/")
        group = self.nodes[("analysis", "imaging_layer_canvas")].nodegroup_id

        with self.settings(EXPLORER_LEGACY_HOSTS=["old-host"]):
            tile_old = self.legacy_case("old-host", new_host)
            TileModel.objects.filter(nodegroup_id=group).delete()
            tile_mirror = self.legacy_case(new_host, "old-host")

        for layers in (tile_old, tile_mirror):
            self.assertEqual(len(layers), 1)
            self.assertEqual(layers[0]["content"]["label"]["value"], "Element")
            self.assertTrue(layers[0]["id"].startswith(settings.PUBLIC_SERVER_ADDRESS))

    def test_layers_are_read_in_one_values_query(self):
        def tile_queries():
            with CaptureQueriesContext(connection) as queries:
                self.layer_files()
            return len([q for q in queries if 'FROM "tiles"' in q["sql"]])

        without = tile_queries()
        for canvas in self.LAYER_CANVASES.values():
            self.layer_tile(
                canvas,
                imaging_layer_content=self.ref("https://example.org/c/el", "Element"),
            )

        self.assertEqual(tile_queries(), without)

    def test_a_hidden_unknown_or_malformed_analysis_key_is_missing(self):
        self.embargo(self.analyses["open"])
        hidden = f"an:{self.analyses['open'].pk}:-"
        unknown = "an:00000000-0000-4000-8000-00000000000a:-"
        malformed = f"an:{self.analyses['on_document'].pk}:0"

        payload = self.get([hidden, unknown, malformed]).json()

        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["missing"], sorted([hidden, unknown, malformed]))

    def test_malformed_and_hidden_keys_are_missing_alike(self):
        self.embargo(self.analyses["open"])
        hidden = f"af:{self.analyses['open'].pk}:{self.CSV}"

        payload = self.get(
            [hidden, "nonsense", f"ch:{self.characterization.pk}:-", hidden]
        ).json()

        self.assertEqual(payload["missing"], sorted([hidden, "nonsense"]))
        self.assertEqual([i["kind"] for i in payload["items"]], ["characterization"])

    def test_a_ch_key_restores_a_characterization_summary(self):
        key = f"ch:{self.characterization.pk}:-"

        payload = self.get([key]).json()

        self.assertEqual(set(payload["items"][0]), {"key", "kind", "characterization"})
        self.assertEqual(payload["items"][0]["kind"], "characterization")
        assert_shape(
            self, payload["items"][0]["characterization"], "CharacterizationSummary"
        )

    def test_items_rejects_more_than_thirty_keys(self):
        keys = [f"ch:{i:08d}-0000-4000-8000-000000000000:-" for i in range(31)]

        response = self.get(keys)

        self.assertEqual((response.status_code, response.content), (400, b""))


class ZoneCoordinatesTests(ReadRightsCase):
    def test_a_material_zone_is_scaled_on_its_document_and_absent_from_items(self):
        self.tile(
            self.components["open"],
            "location_in_document",
            self.annotation_value(
                CANVAS, {"type": "Point", "coordinates": [78.125, -100]}
            ),
        )
        mine = str(self.characterization.pk)

        document = self.document(self.documents["open"].pk)
        items = self.client.get("/en/api/explorer/items", {"ids": f"ch:{mine}:-"})

        zone = next(s["zone"] for s in document["characterizations"] if s["id"] == mine)
        self.assertEqual(zone["shape"], {"type": "point", "x": 2500, "y": 3200})
        self.assertIsNone(items.json()["items"][0]["characterization"]["zone"])


class FacetRouteTests(CorpusCase):
    def get(self, key, query=""):
        return self.client.get(f"/en/api/explorer/facet/{key}{query}")

    def test_the_facet_lists_every_value_with_the_counts_of_the_search(self):
        search = self.client.get(f"/en/api/explorer/search?material={AZURITE}").json()
        response = self.get("technique", f"?material={AZURITE}")

        self.assertEqual(response.status_code, 200)
        facet = response.json()
        assert_shape(self, facet, "Facet")
        self.assertEqual(
            facet, next(f for f in search["facets"] if f["key"] == "technique")
        )

    def test_find_narrows_the_values_by_folded_label_and_keeps_the_selected_ones(self):
        both = self.get("technique").json()
        found = self.get("technique", "?find=REFLECTANCE").json()
        kept = self.get("technique", f"?find=reflectance&technique={XRF}").json()

        self.assertEqual({v["id"] for v in both["values"]}, {XRF, FORS})
        self.assertEqual([v["id"] for v in found["values"]], [FORS])
        self.assertEqual(found["total"], 2)
        self.assertEqual({v["id"] for v in kept["values"]}, {XRF, FORS})

    def test_an_unknown_key_or_a_facet_without_values_answers_a_bodyless_404(self):
        for key in ("nonsense", "layer"):
            response = self.get(key)
            self.assertEqual((response.status_code, response.content), (404, b""), key)

    def test_a_restricted_value_nodegroup_answers_like_an_absent_facet(self):
        nodegroup = NodeGroup.objects.get(
            pk=self.nodes[("analysis", "analysis_technique_used")].nodegroup_id
        )
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm("no_access_to_nodegroup", self.anonymous, nodegroup)

        response = self.get("technique")

        self.assertEqual((response.status_code, response.content), (404, b""))

    def test_a_document_scope_counts_only_the_rows_of_the_document(self):
        document = self.documents["open"].pk
        corpus = self.get("part").json()
        scoped = self.get("part", f"?document={document}").json()
        match = self.client.get(f"/en/api/explorer/document/{document}/match").json()

        self.assertEqual(
            {v["id"] for v in corpus["values"]},
            {str(self.components["open"].pk), str(self.components["embargoed"].pk)},
        )
        self.assertEqual(
            {v["id"] for v in scoped["values"]}, {str(self.components["open"].pk)}
        )
        self.assertEqual(scoped, next(f for f in match["facets"] if f["key"] == "part"))

    def test_find_narrows_a_document_scoped_facet(self):
        found = self.get(
            "technique", f"?document={self.documents['open'].pk}&find=reflectance"
        ).json()

        self.assertEqual([v["id"] for v in found["values"]], [FORS])
        self.assertEqual(found["total"], 2)

    def test_a_document_hidden_unknown_or_malformed_answers_a_bodyless_404(self):
        self.embargo(self.documents["embargoed"])

        for document in (
            self.documents["embargoed"].pk,
            "00000000-0000-4000-8000-000000000001",
            "not-a-uuid",
            "",
        ):
            response = self.get("part", f"?document={document}")
            self.assertEqual(
                (response.status_code, response.content), (404, b""), document
            )

    def test_a_facet_the_document_lacks_answers_a_bodyless_404(self):
        response = self.get("technique", f"?document={self.documents['embargoed'].pk}")

        self.assertEqual((response.status_code, response.content), (404, b""))

    def test_the_etag_of_the_whole_corpus_does_not_revalidate_a_document_scope(self):
        etag = self.get("part")["ETag"]

        scoped = self.client.get(
            f"/en/api/explorer/facet/part?document={self.documents['open'].pk}",
            HTTP_IF_NONE_MATCH=etag,
        )

        self.assertEqual(scoped.status_code, 200)


class HomeRouteTests(CorpusCase):
    def get(self, day=None, **headers):
        day = day or datetime.date.today().isoformat()
        return self.client.get("/en/api/explorer/home", {"day": day}, **headers)

    def test_the_home_has_the_contract_shape_and_the_overview_of_the_search(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, no-cache")
        home = response.json()
        assert_shape(self, home, "HomeResponse")
        overview = self.client.get("/en/api/explorer/search?grain=documents").json()
        facets = {f["key"]: f["values"] for f in overview["facets"]}
        self.assertEqual(home["documentCount"], overview["total"])
        self.assertEqual(home["unpublishedCount"], overview["unpublishedCount"])
        self.assertEqual(home["techniques"], facets["technique"])
        self.assertEqual(home["projects"], facets["project"])
        for value in home["techniques"] + home["projects"]:
            assert_shape(self, value, "FacetValue")

    def test_the_featured_document_is_the_one_at_the_position_of_the_day(self):
        day = datetime.date.today().isoformat()
        overview = self.client.get(
            "/en/api/explorer/search?grain=documents&size=50"
        ).json()

        featured = self.get(day).json()["featured"]

        assert_shape(self, featured, "DocumentHit")
        position = explorer_service.day_index(day, overview["total"])
        self.assertEqual(featured, overview["results"][position])

    def test_a_hidden_document_is_never_featured(self):
        self.embargo(self.documents["open"])
        self.embargo(self.documents["embargoed"])

        home = self.get().json()

        self.assertEqual((home["documentCount"], home["featured"]), (0, None))

    def test_a_day_that_is_malformed_missing_or_more_than_a_day_away_is_a_bad_request(
        self,
    ):
        today = datetime.date.today()
        for day in (
            "not-a-day",
            "2026-9-5",
            (today + datetime.timedelta(days=2)).isoformat(),
            (today - datetime.timedelta(days=2)).isoformat(),
        ):
            self.assertEqual(self.get(day).status_code, 400, day)
        self.assertEqual(self.client.get("/en/api/explorer/home").status_code, 400)
        for shift in (-1, 1):
            day = (today + datetime.timedelta(days=shift)).isoformat()
            self.assertEqual(self.get(day).status_code, 200, day)


class DayIndexTests(SimpleTestCase):
    def test_the_day_index_follows_the_vectors_the_front_end_shares(self):
        vectors = json.loads(DAY_VECTORS.read_text())

        self.assertTrue(vectors)
        for vector in vectors:
            self.assertEqual(
                explorer_service.day_index(vector["day"], vector["count"]),
                vector["index"],
                vector,
            )


class RevalidationTests(CorpusCase):
    ROUTES = (
        "/en/api/explorer/search?grain=analyses",
        "/en/api/explorer/facet/technique",
        "/en/api/explorer/facet/technique?document={document}",
        "/en/api/explorer/home?day={today}",
        "/en/api/explorer/document/{document}/match?technique=" + XRF,
    )

    def urls(self):
        return [
            route.format(
                today=datetime.date.today().isoformat(),
                document=self.documents["open"].pk,
            )
            for route in self.ROUTES
        ]

    def test_a_held_etag_answers_304_without_building_the_bundle(self):
        for url in self.urls():
            etag = self.client.get(url)["ETag"]
            with (
                mock.patch.object(
                    explorer_service, "build_bundle", side_effect=AssertionError
                ),
                mock.patch.object(
                    explorer_service.explorer_memo,
                    "remember",
                    side_effect=AssertionError,
                ),
            ):
                again = self.client.get(url, HTTP_IF_NONE_MATCH=etag)

            self.assertEqual(again.status_code, 304, url)
            self.assertEqual(again["ETag"], etag, url)

    def test_the_etag_changes_when_the_data_changes(self):
        for url in self.urls():
            before = self.client.get(url)["ETag"]
            self.tile(
                self.analyses["open"],
                "label_of_name",
                self.string_value(f"renamed for {url}"),
            )

            after = self.client.get(url, HTTP_IF_NONE_MATCH=before)

            self.assertEqual(after.status_code, 200, url)
            self.assertNotEqual(after["ETag"], before, url)

    def test_a_gzipped_answer_carries_a_weak_etag_that_revalidates(self):
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            for url in self.urls() + [
                f"/en/api/explorer/document/{self.documents['open'].pk}",
                f"/en/api/explorer/analysis/{self.analyses['open'].pk}",
            ]:
                response = self.client.get(url, HTTP_ACCEPT_ENCODING="gzip")
                self.assertEqual(response["Content-Encoding"], "gzip", url)
                self.assertTrue(response["ETag"].startswith('W/"'), url)
                self.assertIn("Accept-Encoding", response["Vary"], url)

                again = self.client.get(
                    url,
                    HTTP_ACCEPT_ENCODING="gzip",
                    HTTP_IF_NONE_MATCH=response["ETag"],
                )
                self.assertEqual(again.status_code, 304, url)


class LayerOfTests(SimpleTestCase):
    def test_a_layer_without_a_tile_is_unclassified(self):
        layer = layer_of(3, "  Pb  ", {"url": None}, "canvas-id")

        self.assertEqual(
            layer,
            {
                "index": 3,
                "id": "canvas-id",
                "label": "Pb",
                "image": {"url": None},
                "content": None,
                "elements": [],
                "emissionLine": None,
                "band": None,
                "processing": None,
                "note": None,
            },
        )

    def test_a_missing_label_is_an_empty_string(self):
        layer = layer_of(0, None, {"url": None})

        self.assertEqual(layer["label"], "")


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

    def test_layer_indices_continue_across_manifests_in_canvas_order(self):
        with mock.patch(
            "manuspectrum.views.explorer.service.manifest_json",
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
        self.assertEqual([layer["index"] for layer in entries[0]["layers"]], [0, 1])
        self.assertEqual(
            [layer["label"] for layer in entries[0]["layers"]], ["650 nm", "450 nm"]
        )
        self.assertEqual(entries[1]["layers"][0]["index"], 2)
        self.assertEqual(entries[1]["layers"][0]["label"], "Pb")
