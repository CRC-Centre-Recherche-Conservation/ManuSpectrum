"""The Presentation 3 manifest of a Document or Component, built from its annotation facts.

Usage:
    python manage.py test tests.test_iiif_document_manifest --settings=tests.test_settings
"""

import time
from unittest import mock
from urllib.parse import urlencode

from django.conf import settings
from django.core.cache import cache
from django.test import Client, override_settings

from manuspectrum.iiif import document_manifest, ids
from manuspectrum.iiif.facts import subject_of
from manuspectrum.iiif.manifest import ManifestTooLarge
from tests.explorer_fixtures import (
    CANVAS,
    CANVAS_2,
    CANVAS_3,
    MANIFEST,
    POINT,
    IIIFCase,
)
from tests.iiif_auth import bearer, signed_in, token_for
from tests.iiif_schema import assert_valid_manifest
from tests.test_iiif_memo import memo_keys
from tests.test_iiif_routes import UNKNOWN, RouteCase

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
        self.assertEqual(labels[1:], ["Projects", "Dates", "Chemical imaging"])
        self.assertEqual(built["metadata"][0]["value"], {"none": ["1401-01"]})

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
