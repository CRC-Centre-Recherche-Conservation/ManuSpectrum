"""``GET /iiif/v3/explorer-manifest``: the IIIF v3 manifest of a Selection, a document or a project.

Usage:
    python manage.py test tests.test_explorer_manifest --settings="tests.test_settings"
"""

import copy
import json
from unittest import mock

from django.conf import settings
from django.test import override_settings

from arches.app.models.models import IIIFManifest, TileModel

from tests.explorer_fixtures import CANVAS, MANIFEST
from tests.iiif_schema import assert_valid_manifest
from tests.test_explorer_api import FETCH, CorpusCase

CANVAS_2 = "https://example.org/iiif/ms59/canvas/f2r"
IMAGING = "https://example.org/iiif/maxrf/manifest"
LAYERS = (
    "https://example.org/iiif/maxrf/canvas/pb",
    "https://example.org/iiif/maxrf/canvas/cu",
)
UNKNOWN = "00000000-0000-4000-8000-00000000000b"
PROFILE = 'application/ld+json;profile="http://iiif.io/api/presentation/3/context.json"'


def v3_canvas(canvas_id, label, service):
    return {
        "id": canvas_id,
        "type": "Canvas",
        "label": {"none": [label]},
        "width": 4000,
        "height": 5000,
        "items": [
            {
                "id": f"{canvas_id}/page",
                "type": "AnnotationPage",
                "items": [
                    {
                        "id": f"{canvas_id}/page/image",
                        "type": "Annotation",
                        "motivation": "painting",
                        "target": canvas_id,
                        "body": {
                            "id": f"{service}/full/max/0/default.jpg",
                            "type": "Image",
                            "format": "image/jpeg",
                            "service": [
                                {
                                    "id": service,
                                    "type": "ImageService3",
                                    "profile": "level1",
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


SOURCE = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": MANIFEST,
    "type": "Manifest",
    "label": {"none": ["Ms 59"]},
    "items": [
        v3_canvas(CANVAS, "f. 1v", "https://example.org/iiif/image/f1v"),
        v3_canvas(CANVAS_2, "f. 2r", "https://example.org/iiif/image/f2r"),
    ],
}
IMAGING_SOURCE = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": IMAGING,
    "type": "Manifest",
    "label": {"none": ["maXRF X01"]},
    "items": [
        v3_canvas(LAYERS[0], "Pb", "https://example.org/iiif/image/pb"),
        v3_canvas(LAYERS[1], "Cu", "https://example.org/iiif/image/cu"),
    ],
}


def fetched(url):
    return {MANIFEST: SOURCE, IMAGING: IMAGING_SOURCE}.get(url)


class ManifestRouteTests(CorpusCase):
    def get(self, query, **headers):
        with mock.patch(FETCH, side_effect=fetched):
            return self.client.get(f"/iiif/v3/explorer-manifest?{query}", **headers)

    def manifest(self, query):
        response = self.get(query)
        self.assertEqual(response.status_code, 200, query)
        return json.loads(response.content)

    def pk(self, key):
        return str(self.analyses[key].pk)

    def document_query(self):
        return f"document={self.documents['open'].pk}"

    def annotations(self, manifest):
        return [
            item
            for canvas in manifest["items"]
            for page in canvas.get("annotations", ())
            for item in page["items"]
        ]

    def test_the_manifest_of_each_scope_is_valid_iiif(self):
        self.tile(
            self.characterization,
            "location_of_characterization",
            self.annotation_value(CANVAS, {"type": "Point", "coordinates": [5, -5]}),
        )
        for query in (
            f"ids=an:{self.pk('open')}:-",
            self.document_query(),
            f"{self.document_query()}&canvases=all",
            f"project={self.projects['main'].pk}",
            f"ids=an:{self.pk('embargoed')}:-",
        ):
            with self.subTest(query=query):
                assert_valid_manifest(self, self.manifest(query))

    def test_only_canvases_carrying_an_element_by_default(self):
        manifest = self.manifest(self.document_query())

        self.assertEqual([c["id"] for c in manifest["items"]], [CANVAS])

    def test_canvases_all_includes_every_canvas_of_the_document(self):
        manifest = self.manifest(f"{self.document_query()}&canvases=all")

        self.assertEqual([c["id"] for c in manifest["items"]], [CANVAS, CANVAS_2])
        self.assertNotIn("annotations", manifest["items"][1])

    def test_canvas_ids_are_the_source_ids_and_part_of_the_source_manifest(self):
        canvas = self.manifest(self.document_query())["items"][0]

        self.assertEqual(canvas["id"], CANVAS)
        self.assertEqual(canvas["partOf"], [{"id": MANIFEST, "type": "Manifest"}])
        self.assertEqual(canvas["items"], SOURCE["items"][0]["items"])

    def test_every_analysis_zone_is_a_data_annotation_on_its_canvas(self):
        manifest = self.manifest(self.document_query())

        annotations = self.annotations(manifest)
        self.assertEqual(
            sorted(a["label"]["en"][0] for a in annotations),
            sorted(["X01 — f. 1v", "FORS_009 — f. 1v", "X03 — draft"]),
        )
        opened = next(a for a in annotations if a["label"]["en"] == ["X01 — f. 1v"])
        self.assertEqual(opened["motivation"], "supplementing")
        self.assertEqual(opened["target"]["source"]["id"], CANVAS)
        self.assertEqual(opened["target"]["selector"]["type"], "PointSelector")
        self.assertEqual(
            [b["id"] for b in opened["body"]],
            [
                f"{settings.PUBLIC_SERVER_ADDRESS}files/11111111-1111-4111-8111-111111111111",
                f"{settings.PUBLIC_SERVER_ADDRESS}files/22222222-2222-4222-8222-222222222222",
            ],
        )

    def test_a_material_zone_is_a_describing_annotation(self):
        self.tile(
            self.characterization,
            "location_of_characterization",
            self.annotation_value(CANVAS, {"type": "Point", "coordinates": [5, -5]}),
        )

        manifest = self.manifest(f"ids=ch:{self.characterization.pk}:-")

        self.assertEqual([c["id"] for c in manifest["items"]], [CANVAS])
        (describing,) = self.annotations(manifest)
        self.assertEqual(describing["motivation"], "describing")
        self.assertEqual(
            describing["body"],
            {
                "type": "TextualBody",
                "value": "Azurite",
                "format": "text/plain",
                "language": "en",
            },
        )

    def test_a_local_manifest_is_read_from_the_database_not_over_http(self):
        stored = IIIFManifest.objects.create(
            label="Ms 59", url="", manifest=copy.deepcopy(SOURCE)
        )
        node = self.nodes[("document", "facsimiles")]
        TileModel.objects.filter(
            resourceinstance=self.documents["open"], nodegroup_id=node.nodegroup_id
        ).update(
            data={
                str(
                    node.nodeid
                ): f"{settings.PUBLIC_SERVER_ADDRESS}manifest/{stored.globalid}"
            }
        )

        with mock.patch(FETCH, side_effect=fetched) as fetch:
            response = self.client.get(
                f"/iiif/v3/explorer-manifest?{self.document_query()}"
            )

        fetch.assert_not_called()
        self.assertEqual([c["id"] for c in response.json()["items"]], [CANVAS])

    def test_an_unlocated_analysis_is_in_metadata_without_annotation(self):
        manifest = self.manifest(
            f"ids=an:{self.pk('open')}:-,an:{self.pk('embargoed')}:-"
        )

        (unlocated,) = manifest["metadata"]
        self.assertEqual(
            unlocated["value"]["en"],
            [
                f"X02 — f. 3r — {settings.PUBLIC_SERVER_ADDRESS}report/{self.pk('embargoed')}"
            ],
        )
        self.assertEqual(
            [a["label"]["en"][0] for a in self.annotations(manifest)], ["X01 — f. 1v"]
        )

    def test_imaging_layers_are_canvases_with_one_range_per_analysis(self):
        self.tile(self.analyses["open"], "chemical_imaging_manifest", IMAGING)

        manifest = self.manifest(self.document_query())

        self.assertEqual([c["id"] for c in manifest["items"]], [CANVAS, *LAYERS])
        self.assertEqual(
            [c["label"] for c in manifest["items"][1:]],
            [{"none": ["f. 1v — Pb"]}, {"none": ["f. 1v — Cu"]}],
        )
        for layer in manifest["items"][1:]:
            self.assertEqual(layer["partOf"], [{"id": IMAGING, "type": "Manifest"}])
        ranges = {r["label"]["en"][0]: r for r in manifest["structures"]}
        self.assertEqual(
            [i["id"] for i in ranges["X01 — f. 1v"]["items"]], list(LAYERS)
        )
        assert_valid_manifest(self, manifest)

    def test_one_range_per_document(self):
        manifest = self.manifest(self.document_query())

        self.assertEqual(
            manifest["structures"],
            [
                {
                    "id": manifest["structures"][0]["id"],
                    "type": "Range",
                    "label": {"en": ["Ms 59"]},
                    "items": [{"id": CANVAS, "type": "Canvas"}],
                }
            ],
        )
        self.assertTrue(
            manifest["structures"][0]["id"].startswith(
                f"{settings.PUBLIC_SERVER_ADDRESS}iiif/v3/explorer-manifest/"
            )
        )

    def test_the_manifest_id_is_its_own_absolute_url(self):
        manifest = self.manifest(self.document_query())

        self.assertEqual(
            manifest["id"],
            f"{settings.PUBLIC_SERVER_ADDRESS}iiif/v3/explorer-manifest"
            f"?{self.document_query()}&lang=en",
        )
        self.assertEqual(
            manifest["homepage"][0]["id"],
            f"{settings.PUBLIC_SERVER_ADDRESS}en/discover?doc={self.documents['open'].pk}",
        )

    def test_labels_follow_lang(self):
        query = f"ids=an:{self.pk('open')}:-"

        english = self.manifest(query)
        french = self.manifest(f"{query}&lang=fr")

        self.assertEqual(english["label"], {"en": ["Selection of 1 page of Ms 59"]})
        self.assertEqual(french["label"], {"fr": ["Sélection de 1 folio de Ms 59"]})
        self.assertTrue(french["id"].endswith("&lang=fr"))
        (annotation,) = self.annotations(french)
        self.assertIn(
            "Technique", [m["label"]["fr"][0] for m in annotation["metadata"]]
        )
        self.assertIn(
            "Opérateurs", [m["label"]["fr"][0] for m in annotation["metadata"]]
        )

    def test_several_documents_are_named_by_their_count(self):
        manifest = self.manifest(
            f"ids=an:{self.pk('open')}:-,an:{self.pk('embargoed')}:-"
        )

        self.assertEqual(
            manifest["label"], {"en": ["Selection of 1 page of 2 documents"]}
        )

    def test_a_project_manifest_is_named_by_its_project(self):
        manifest = self.manifest(f"project={self.projects['main'].pk}")

        self.assertEqual(manifest["label"], {"en": ["EMMA"]})

    def test_an_unknown_lang_is_a_bad_request_without_body(self):
        for query in (f"{self.document_query()}&lang=xx", "lang=en", "ids="):
            with self.subTest(query=query):
                response = self.get(query)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.content, b"")

    def test_unknown_and_embargoed_scopes_answer_the_same_404(self):
        self.embargo(self.documents["embargoed"])

        responses = (
            self.get(f"document={UNKNOWN}"),
            self.get(f"document={self.documents['embargoed'].pk}"),
            self.get(f"ids=an:{self.pk('embargoed')}:-"),
        )

        for response in responses:
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.content, b"")
            self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_an_embargoed_analysis_leaves_no_trace(self):
        self.embargo(self.analyses["open"])

        for query in (
            self.document_query(),
            f"project={self.projects['main'].pk}",
            f"ids=an:{self.pk('open')}:-,an:{self.pk('on_document')}:-",
        ):
            with self.subTest(query=query):
                body = self.get(query).content.decode()

                self.assertNotIn(self.pk("open"), body)
                self.assertNotIn("X01", body)
                self.assertNotIn("11111111-1111-4111-8111-111111111111", body)

    def test_a_visitor_gets_public_no_cache_and_a_304_on_revalidation(self):
        response = self.get(self.document_query())

        self.assertEqual(response["Cache-Control"], "public, no-cache")
        again = self.get(self.document_query(), HTTP_IF_NONE_MATCH=response["ETag"])
        self.assertEqual(again.status_code, 304)

    def test_a_connected_readers_manifest_is_private(self):
        self.client.force_login(self.editor)

        response = self.get(self.document_query())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotIn("ETag", response)

    def test_drafts_and_restricted_inclusion_are_marked_in_the_summary(self):
        self.embargo(self.analyses["open"])
        self.client.force_login(self.editor)

        default = self.manifest(self.document_query())
        restricted = self.manifest(f"{self.document_query()}&restricted=1")
        open_only = self.manifest(f"ids=an:{self.pk('on_document')}:-")

        self.assertEqual(default["summary"], {"en": ["Contains drafts"]})
        self.assertEqual(
            restricted["summary"],
            {"en": ["Contains drafts", "Contains restricted-access data"]},
        )
        self.assertIn("X01 — f. 1v", json.dumps(restricted, ensure_ascii=False))
        self.assertTrue(restricted["id"].endswith("&restricted=1&lang=en"))
        self.assertNotIn("summary", open_only)

    @override_settings(EXPLORER_MANIFEST_MAX_CANVASES=0)
    def test_over_the_canvas_bound_answers_413_without_body(self):
        for query in (self.document_query(), f"{self.document_query()}&canvases=all"):
            with self.subTest(query=query):
                response = self.get(query)

                self.assertEqual(response.status_code, 413)
                self.assertEqual(response.content, b"")
                self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_the_media_type_is_the_iiif_presentation_3_profile(self):
        response = self.get(self.document_query())

        self.assertEqual(response["Content-Type"], PROFILE)
