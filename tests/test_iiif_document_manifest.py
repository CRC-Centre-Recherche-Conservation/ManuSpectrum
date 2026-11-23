"""The Presentation 3 manifest of a Document or Component, built from its annotation facts.

Usage:
    python manage.py test tests.test_iiif_document_manifest --settings=tests.test_settings
"""

import copy
import json
import time
import uuid
from unittest import mock
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.test import Client, override_settings

from arches.app.models.models import IIIFManifest, ResourceInstance

from manuspectrum.functions.resource_summary import bump_config_stamp
from manuspectrum.iiif import document_manifest, ids
from manuspectrum.iiif.facts import subject_of
from manuspectrum.iiif.manifest import ManifestTooLarge
from tests.explorer_fixtures import (
    CANVAS,
    CANVAS_2,
    CANVAS_3,
    DRAFT,
    ACTIVE,
    MANIFEST,
    POINT,
    SOURCE_MANIFEST,
    IIIFCase,
)
from tests.iiif_auth import bearer, signed_in, token_for
from tests.iiif_schema import assert_valid_manifest
from tests.test_iiif_memo import memo_keys
from tests.test_iiif_routes import UNKNOWN, RouteCase
from tests.test_iiif_v2 import V2_SOURCE

CONFIG = "manuspectrum.iiif.record.load_summary_config"
IMAGING = "https://example.org/iiif/maxrf/manifest"
ZONE = "0d0d0d0d-0000-4000-8000-000000000001"


class DocumentManifestTests(IIIFCase):
    def build(self, resource, user=None, **kwargs):
        user = user or self.anonymous
        subject = subject_of(resource.pk, user, None)
        return document_manifest.build(
            str(resource.pk), user, version=None, subject=subject, **kwargs
        )

    def doc(self):
        return str(self.documents["open"].pk)

    def test_canvases_are_the_pages_holding_analyses(self):
        built = self.build(self.documents["open"])
        self.assertEqual([c["id"] for c in built["items"]], [CANVAS, CANVAS_3])
        self.assertEqual(built["id"], ids.manifest(self.doc()))
        self.assertNotIn("structures", built)

    def test_canvas_references_canonical_pages(self):
        built = self.build(self.documents["open"])
        first = built["items"][0]["annotations"]
        self.assertEqual(first[0]["id"], ids.page(self.doc(), 1))
        self.assertNotIn("?only=", first[0]["id"])

    def test_materials_only_document(self):
        document = self.new_resource("document", "Ms 300")
        self.tile(document, "facsimiles", MANIFEST)
        component = self.new_resource("component", "f. 2r — ground")
        self.tile(component, "item_visual_is_part_of_document", self.refs(document))
        self.zone(component, [(ZONE, CANVAS_2, POINT)], alias="location_in_document")
        material = self.new_resource("characterization", "Lead white")
        self.tile(material, "object_observed", self.refs(component))
        self.tile(material, "evidence_analyses", self.refs(self.analyses["embargoed"]))
        built = self.build(document)
        self.assertEqual([c["id"] for c in built["items"]], [CANVAS_2])
        (reference,) = built["items"][0]["annotations"]
        self.assertEqual(
            reference["id"], ids.page(str(document.pk), 2, "characterization")
        )
        self.assertEqual(
            built["summary"]["en"], ["1 identified material on 1 page of Ms 300"]
        )

    def test_header_metadata_order(self):
        self.tile(self.analyses["open"], "chemical_imaging_manifest", IMAGING)
        self.tile_values(
            self.analyses["open"], "analysis", analysis_start_date="2024-03-05"
        )
        fields = [{"alias": "date_start_of_production_time", "style": "date"}]
        with mock.patch(CONFIG, return_value={"fields": fields}):
            built = self.build(self.documents["open"])
        labels = [entry["label"]["en"][0] for entry in built["metadata"]]
        self.assertEqual(labels[0], "Document")
        self.assertEqual(labels[2:], ["Projects", "Dates", "Chemical imaging"])
        self.assertIn(ids.report(self.doc()), built["metadata"][0]["value"]["en"][0])
        self.assertEqual(built["metadata"][1]["value"], {"none": ["1401-01"]})

    def test_component_metadata_starts_with_its_document_then_itself(self):
        component = self.components["open"]
        with mock.patch(CONFIG, return_value=None):
            built = self.build(component)
        first, second = built["metadata"][:2]
        self.assertEqual(first["label"]["en"], ["Document"])
        self.assertIn(ids.report(self.doc()), first["value"]["en"][0])
        self.assertEqual(second["label"]["en"], ["Component"])
        self.assertIn(ids.report(str(component.pk)), second["value"]["en"][0])

    def imaging_value(self, built):
        (entry,) = [
            m for m in built["metadata"] if m["label"]["en"] == ["Chemical imaging"]
        ]
        return entry["value"]

    def test_imaging_value_names_an_external_manifest_by_its_url(self):
        self.tile(self.analyses["open"], "chemical_imaging_manifest", IMAGING)
        value = self.imaging_value(self.build(self.documents["open"]))
        self.assertIn(f'<a href=\\"{IMAGING}\\">{IMAGING}</a>', json.dumps(value))
        self.assertTrue(all(value.values()))

    def test_imaging_value_names_a_stored_manifest_by_its_label(self):
        stored = IIIFManifest.objects.create(
            globalid=uuid.uuid4(), label="maXRF map", url="", manifest={}
        )
        stored.url = f"/manifest/{stored.globalid}"
        stored.save()
        self.tile(self.analyses["open"], "chemical_imaging_manifest", stored.url)
        self.tile(self.analyses["on_document"], "chemical_imaging_manifest", IMAGING)
        value = json.dumps(self.imaging_value(self.build(self.documents["open"])))
        self.assertIn("maXRF map", value)
        self.assertIn(ids.stored_manifest(stored.globalid), value)
        self.assertIn(IMAGING, value)

    def with_source(self, source):
        self.fetch.side_effect = lambda url: source if url == MANIFEST else None

    def painted(self, body):
        """The v3 source manifest whose canvases each carry one painting with *body*."""
        source = copy.deepcopy(SOURCE_MANIFEST)
        for canvas in source["items"]:
            canvas["items"] = [
                {
                    "id": f"{canvas['id']}/page",
                    "type": "AnnotationPage",
                    "items": [
                        {
                            "id": f"{canvas['id']}/painting",
                            "type": "Annotation",
                            "motivation": "painting",
                            "target": canvas["id"],
                            "body": body,
                        }
                    ],
                }
            ]
        return source

    def test_a_single_object_service_gives_the_thumbnail_and_a_v2_image_service(self):
        image = {"id": "https://img.example/i1/full/max/0/default.jpg", "type": "Image"}
        self.with_source(
            self.painted(
                {
                    **image,
                    "service": {
                        "id": "https://img.example/i1",
                        "type": "ImageService3",
                    },
                }
            )
        )
        thumbnail = self.build(self.documents["open"])["thumbnail"]
        self.assertEqual(
            thumbnail[0]["id"], "https://img.example/i1/full/!300,300/0/default.jpg"
        )
        v2 = self.build(self.documents["open"], api=2)
        resource = v2["sequences"][0]["canvases"][0]["images"][0]["resource"]
        self.assertEqual(resource["service"]["@id"], "https://img.example/i1")

    def test_a_painting_body_given_as_a_list_gives_the_thumbnail(self):
        self.with_source(
            self.painted(
                [
                    {
                        "id": "https://img.example/i2/full/max/0/default.jpg",
                        "type": "Image",
                        "service": [{"@id": "https://img.example/i2"}],
                    }
                ]
            )
        )
        built = self.build(self.documents["open"])
        self.assertEqual(
            built["thumbnail"][0]["id"],
            "https://img.example/i2/full/!300,300/0/default.jpg",
        )
        self.assertTrue(self.build(self.documents["open"], api=2))

    def test_v2_canvases_of_a_v3_source_carry_rights_and_attribution(self):
        source = self.painted({"id": "https://img.example/i/full/max/0/default.jpg"})
        source["rights"] = "http://creativecommons.org/licenses/by/4.0/"
        source["requiredStatement"] = {
            "label": {"en": ["Attribution"]},
            "value": {"en": ["Bibliothèque"]},
        }
        self.with_source(source)
        canvas = self.build(self.documents["open"], api=2)["sequences"][0]["canvases"][
            0
        ]
        self.assertEqual(canvas["license"], source["rights"])
        self.assertIn(
            {"@value": "Bibliothèque", "@language": "en"}, canvas["attribution"]
        )
        self.assertEqual(canvas["within"], MANIFEST)

    def test_v2_canvases_of_a_v2_source_carry_the_manifests_rights(self):
        source = copy.deepcopy(V2_SOURCE)
        source["license"] = "http://creativecommons.org/licenses/by/4.0/"
        source["attribution"] = "Bibliothèque"
        self.with_source(source)
        canvas = self.build(self.documents["open"], api=2)["sequences"][0]["canvases"][
            0
        ]
        self.assertEqual(canvas["license"], source["license"])
        self.assertEqual(canvas["attribution"][0]["@value"], "Bibliothèque")
        self.assertEqual(canvas["within"], MANIFEST)

    def test_a_document_without_a_name_is_named_by_its_id(self):
        document = ResourceInstance.objects.create(
            graph=self.graphs["document"], resource_instance_lifecycle_state_id=ACTIVE
        )
        self.tile(document, "facsimiles", MANIFEST)
        component = self.new_resource("component", "f. 2r — ground")
        self.tile(component, "item_visual_is_part_of_document", self.refs(document))
        self.zone(component, [(ZONE, CANVAS_2, POINT)], alias="location_in_document")
        material = self.new_resource("characterization", "Lead white")
        self.tile(material, "object_observed", self.refs(component))
        self.tile(material, "evidence_analyses", self.refs(self.analyses["embargoed"]))
        built = self.build(document)
        self.assertEqual(built["label"]["en"], [f"Analyses of {document.pk}"])
        self.assertEqual(built["homepage"][0]["label"], {"none": [str(document.pk)]})

    def test_a_draft_identified_material_adds_the_drafts_note(self):
        document = self.new_resource("document", "Ms 302")
        self.tile(document, "facsimiles", MANIFEST)
        component = self.new_resource("component", "f. 2r — ground")
        self.tile(component, "item_visual_is_part_of_document", self.refs(document))
        self.zone(component, [(ZONE, CANVAS_2, POINT)], alias="location_in_document")
        material = self.new_resource("characterization", "Lead white", state=DRAFT)
        self.tile(material, "object_observed", self.refs(component))
        self.tile(material, "evidence_analyses", self.refs(self.analyses["embargoed"]))
        built = self.build(document)
        self.assertIn("Contains drafts", built["summary"]["en"][0])

    def test_no_explorer_links_when_visitor_cannot_see_document(self):
        self.embargo(self.documents["open"])
        built = self.build(self.documents["open"], user=self.editor)
        self.assertEqual([h["id"] for h in built["homepage"]], [ids.report(self.doc())])
        self.assertNotIn("rendering", built)

    def test_visible_document_links_to_explorer_and_export(self):
        built = self.build(self.documents["open"])
        self.assertEqual(built["homepage"][0]["id"], ids.report(self.doc()))
        self.assertGreater(len(built["homepage"]), 1)
        query = urlencode({"document": self.doc()})
        (rendering,) = built["rendering"]
        self.assertEqual(rendering["id"], ids.explorer_export(query))
        self.assertEqual(rendering["format"], "application/zip")

    def test_drafts_are_named_in_the_summary(self):
        built = self.build(self.documents["open"])
        self.assertIn("Contains drafts", built["summary"]["en"][0])

    def test_component_manifest_has_no_explorer_links(self):
        component = self.components["open"]
        built = self.build(component)
        self.assertEqual(
            [h["id"] for h in built["homepage"]], [ids.report(str(component.pk))]
        )
        self.assertNotIn("rendering", built)
        self.assertEqual(built["label"]["en"], ["Analyses of f. 1v — initial"])

    def test_no_source_manifest_is_none(self):
        document = self.new_resource("document", "Ms 301")
        self.assertIsNone(self.build(document))

    @override_settings(EXPLORER_MANIFEST_MAX_CANVASES=1)
    def test_over_max_canvases_raises(self):
        with self.assertRaises(ManifestTooLarge):
            self.build(self.documents["open"])

    def test_source_manifest_read_once(self):
        self.build(self.documents["open"])
        self.assertEqual(self.fetch.call_count, 1)

    def test_embed_inlines_visitor_pages(self):
        built = self.build(self.documents["open"], embed=True)
        for canvas in built["items"]:
            for page in canvas["annotations"]:
                self.assertEqual(page["type"], "AnnotationPage")
                self.assertIn("items", page)
                self.assertNotIn("@context", page)

    def test_valid_presentation_3(self):
        assert_valid_manifest(self, self.build(self.documents["open"]))
        assert_valid_manifest(self, self.build(self.documents["open"], embed=True))


XRF = "https://example.org/concepts/xrf"


class ManifestRouteTests(RouteCase):
    def url(self, resource=None):
        return f"/iiif/v3/manifest/{resource or self.doc()}"

    def technique(self):
        self.tile(
            self.analyses["open"],
            "analysis_technique_used",
            self.reference_value(XRF, "XRF", "FRX"),
        )

    def test_visitor_gets_public_no_cache_with_etag_and_304(self):
        response = self.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, no-cache")
        self.assertIn("ld+json", response["Content-Type"])
        etag = response["ETag"]
        self.assertEqual(response.json()["id"], ids.manifest(self.doc()))
        again = self.get(self.url(), HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(again.status_code, 304)

    def test_header_differs_for_permitted_reader_and_is_private(self):
        self.technique()
        self.restrict_nodegroup(
            self.nodes[("analysis", "analysis_technique_used")].nodegroup_id,
            self.editor,
        )
        granted = Client()
        granted.force_login(self.editor)
        visitor = self.get(self.url())
        reader = granted.get(self.url())
        self.assertNotIn("Techniques", visitor.content.decode())
        self.assertIn("Techniques", reader.content.decode())
        self.assertEqual(reader["Cache-Control"], "private, no-store")

    def test_a_summary_configuration_save_changes_the_etag(self):
        before = self.get(self.url())["ETag"]
        self.assertEqual(self.get(self.url())["ETag"], before)
        bump_config_stamp()
        self.assertNotEqual(self.get(self.url())["ETag"], before)

    def test_a_component_manifest_answers_over_http(self):
        component = self.components["open"]
        response = self.get(self.url(component.pk))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["id"], ids.manifest(str(component.pk)))
        self.assertEqual(body["homepage"][0]["id"], ids.report(str(component.pk)))

    def test_token_reader_is_private(self):
        token = token_for(self.editor)
        response = self.get(self.url(), **bearer(token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertFalse(memo_keys())

    def test_embargoed_document_404_for_visitor(self):
        self.embargo(self.documents["open"])
        response = self.get(self.url())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")

    def test_unknown_id_404(self):
        response = self.get(self.url(UNKNOWN))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")

    def test_invalid_bearer_401(self):
        response = self.get(self.url(), HTTP_AUTHORIZATION="Bearer nope")
        self.assertEqual(response.status_code, 401)

    def test_unreadable_source_manifest_is_404_and_degraded(self):
        self.fetch.side_effect = lambda url: None
        response = self.get(self.url())
        self.assertEqual(response.status_code, 404)
        (key,) = memo_keys()
        remaining = cache._expire_info[key] - time.time()
        self.assertLessEqual(remaining, settings.IIIF_DEGRADED_TTL)
        self.assertGreater(remaining, settings.IIIF_DEGRADED_TTL - 5)

    @override_settings(EXPLORER_MANIFEST_MAX_CANVASES=1)
    def test_413_over_max_canvases(self):
        response = self.get(self.url())
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response.content, b"")
        self.assertFalse(memo_keys())

    def test_cors_headers(self):
        for url in (self.url(), self.url(UNKNOWN)):
            response = self.get(url, HTTP_ORIGIN="https://viewer.example")
            self.assertEqual(response["Access-Control-Allow-Origin"], "*")
            self.assertNotIn("Access-Control-Allow-Credentials", response)
