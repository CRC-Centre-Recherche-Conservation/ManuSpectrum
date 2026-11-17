"""The stored manifests the IIIF output names, at ``/iiif/manifest/<uuid>`` (issue #293).

A local manifest (``/manifest/<uuid>``, the value every manifest tile
stores) is Arches' route: it sits under the language prefix (a bare request
is a 302 to ``/en/``) and answers no CORS, so a viewer on another origin
could not load the imaging manifest of an annotation, nor the source
manifest its target is part of. The IIIF output names it at the
language-neutral ``/iiif/manifest/<uuid>`` instead.

Usage:
    python manage.py test tests.test_iiif_manifests --settings=tests.test_settings
"""

import copy
import uuid
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse

from arches.app.models.models import IIIFManifest, TileModel

from manuspectrum.iiif import ids
from manuspectrum.iiif.sources import ManifestSource, manifest_source, manifest_sources
from manuspectrum.iiif.constants import IIIF_MEDIA_TYPE, IIIF_V2_MEDIA_TYPE
from tests.explorer_fixtures import FEATURES, SOURCE_MANIFEST, IIIFCase
from tests.iiif_auth import DEMO, bearer, token_for
from tests.observability_helpers import delta

BASE = settings.PUBLIC_SERVER_ADDRESS


def path_of(url):
    return "/" + url[len(BASE) :]


def arches_manifest(globalid, host="http://localhost:8000"):
    """A Presentation 2.1 manifest as Arches' Image Service Manager writes it: its ``@id`` is Arches' route."""
    service = f"{host}/iiifserver/iiif/2/maxrf-pb.tif"
    return {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@id": f"{host}/manifest/{globalid}",
        "@type": "sc:Manifest",
        "label": "maXRF_map1 - illumination - f1v",
        "sequences": [
            {
                "@id": f"{host}/iiifserver/iiif/manifest/sequence/TBD.json",
                "@type": "sc:Sequence",
                "canvases": [
                    {
                        "@id": f"{host}/iiifserver/iiif/manifest/canvas/pb.json",
                        "@type": "sc:Canvas",
                        "label": "Pb",
                        "width": 400,
                        "height": 500,
                        "images": [
                            {
                                "@type": "oa:Annotation",
                                "motivation": "sc:painting",
                                "on": f"{host}/iiifserver/iiif/manifest/canvas/pb.json",
                                "resource": {
                                    "@id": f"{service}/full/full/0/default.jpg",
                                    "@type": "dctypes:Image",
                                    "service": {
                                        "@context": "http://iiif.io/api/image/2/context.json",
                                        "@id": service,
                                        "profile": "http://iiif.io/api/image/2/level2.json",
                                    },
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }


class StoredManifestCase(IIIFCase):
    """The IIIFCase corpus whose ``open`` analysis names a stored imaging manifest, as every manifest tile does."""

    def setUp(self):
        super().setUp()
        self.visitor = Client()
        self.imaging = self.stored("maXRF_map1 - illumination - f1v")
        self.tile(
            self.analyses["open"],
            "chemical_imaging_manifest",
            f"/manifest/{self.imaging.globalid}",
        )
        cache.clear()

    def stored(self, label, manifest=None):
        globalid = uuid.uuid4()
        return IIIFManifest.objects.create(
            globalid=globalid,
            label=label,
            url=f"/manifest/{globalid}",
            manifest=manifest or arches_manifest(globalid),
        )

    def annotation(self, version=3):
        analysis, feature = self.analyses["open"].pk, FEATURES["open"]
        response = self.visitor.get(f"/iiif/v{version}/annotation/{analysis}/{feature}")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def cross_origin(self, url, **headers):
        """*url* as a viewer on another origin fetches it: no cookie, an ``Origin``."""
        return Client().get(path_of(url), HTTP_ORIGIN=DEMO, **headers)

    def assert_dereferences(self, url):
        """*url* answers a viewer on another origin with a 200, ``*`` and no redirect."""
        response = self.cross_origin(url)
        self.assertEqual(response.status_code, 200, f"{url}: {response.status_code}")
        self.assertEqual(response.get("Access-Control-Allow-Origin"), "*", url)
        return response


class ImagingBodyTests(StoredManifestCase):
    def manifest_body(self, annotation, key="body", id_key="id"):
        (body,) = [
            b
            for b in annotation[key]
            if b.get("type") == "Manifest" or b.get("@type") == "sc:Manifest"
        ]
        return body[id_key]

    def test_the_imaging_body_dereferences_cross_origin(self):
        url = self.manifest_body(self.annotation())

        response = self.assert_dereferences(url)

        self.assertEqual(
            response.json()["sequences"], self.imaging.manifest["sequences"]
        )
        self.assertEqual(response.json()["@id"], url)

    def test_the_v2_imaging_resource_dereferences_cross_origin(self):
        url = self.manifest_body(self.annotation(2), "resource", "@id")

        self.assertEqual(url, ids.stored_manifest(self.imaging.globalid))
        self.assert_dereferences(url)

    def test_the_imaging_body_is_the_language_neutral_iiif_route(self):
        url = self.manifest_body(self.annotation())

        self.assertEqual(url, ids.stored_manifest(self.imaging.globalid))
        self.assertEqual(resolve(path_of(url)).url_name, "iiif-manifest")
        self.assertFalse(
            reverse("iiif-manifest", args=[self.imaging.globalid]).startswith(
                ("/en/", "/fr/")
            )
        )

    def test_a_presentation_2_manifest_is_served_with_its_profile(self):
        response = self.assert_dereferences(ids.stored_manifest(self.imaging.globalid))

        self.assertEqual(response["Content-Type"], IIIF_V2_MEDIA_TYPE)

    def test_an_external_imaging_manifest_keeps_its_url(self):
        external = "https://example.org/iiif/maxrf/manifest"
        node = self.nodes[("analysis", "chemical_imaging_manifest")]
        TileModel.objects.filter(
            resourceinstance=self.analyses["open"], nodegroup_id=node.nodegroup_id
        ).update(data={str(node.nodeid): external})
        cache.clear()

        self.assertEqual(self.manifest_body(self.annotation()), external)


class SourceManifestTests(StoredManifestCase):
    """The Document's source manifest, which the target of every annotation is part of."""

    def setUp(self):
        super().setUp()
        self.source = self.stored("Ms 59", copy.deepcopy(SOURCE_MANIFEST))
        node = self.nodes[("document", "facsimiles")]
        TileModel.objects.filter(
            resourceinstance=self.documents["open"], nodegroup_id=node.nodegroup_id
        ).update(data={str(node.nodeid): f"/manifest/{self.source.globalid}"})
        cache.clear()

    def test_the_target_is_part_of_a_manifest_that_dereferences_cross_origin(self):
        (part_of,) = self.annotation()["target"]["source"]["partOf"]

        self.assertEqual(part_of["id"], ids.stored_manifest(self.source.globalid))
        response = self.assert_dereferences(part_of["id"])
        self.assertEqual(response["Content-Type"], IIIF_MEDIA_TYPE)
        self.assertEqual(response.json()["items"], SOURCE_MANIFEST["items"])

    def test_the_v2_target_is_within_the_same_manifest(self):
        within = self.annotation(2)["on"]["within"]

        self.assertEqual(within["@id"], ids.stored_manifest(self.source.globalid))
        self.assertEqual(
            self.assert_dereferences(within["@id"])["Content-Type"], IIIF_MEDIA_TYPE
        )

    def test_an_imported_manifest_is_served_under_our_id(self):
        url = ids.stored_manifest(self.source.globalid)

        self.assertEqual(self.assert_dereferences(url).json()["id"], url)


class AccessTests(StoredManifestCase):
    """Only a manifest the IIIF output names for the reader is served."""

    def url(self, stored=None):
        return path_of(ids.stored_manifest((stored or self.imaging).globalid))

    def assert_bodyless_404(self, response):
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_an_unknown_id_is_a_bodyless_404(self):
        self.assert_bodyless_404(
            self.visitor.get(f"/iiif/manifest/{uuid.uuid4()}", HTTP_ORIGIN=DEMO)
        )

    def test_a_manifest_no_resource_names_is_404(self):
        orphan = self.stored("Not linked")

        self.assert_bodyless_404(self.visitor.get(self.url(orphan), HTTP_ORIGIN=DEMO))

    def test_the_manifest_of_an_embargoed_analysis_is_404_to_the_visitor(self):
        self.embargo(self.analyses["open"])

        self.assert_bodyless_404(self.visitor.get(self.url(), HTTP_ORIGIN=DEMO))

    def test_a_signed_in_reader_of_the_embargoed_analysis_gets_it_privately(self):
        self.embargo(self.analyses["open"])
        reader = Client()
        reader.force_login(self.editor)

        response = reader.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotIn("ETag", response)

    def test_a_token_reader_of_the_embargoed_analysis_gets_it_privately(self):
        self.embargo(self.analyses["open"])

        response = Client().get(self.url(), **bearer(token_for(self.editor)))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_a_manifest_named_in_a_nodegroup_the_reader_may_not_read_is_404(self):
        node = self.nodes[("analysis", "chemical_imaging_manifest")]
        self.restrict_nodegroup(node.nodegroup_id, self.editor)
        reader = Client()
        reader.force_login(self.editor)

        self.assert_bodyless_404(self.visitor.get(self.url(), HTTP_ORIGIN=DEMO))
        self.assertEqual(reader.get(self.url()).status_code, 200)

    def test_a_manifest_also_named_by_a_visible_analysis_is_served(self):
        self.tile(
            self.analyses["on_document"],
            "chemical_imaging_manifest",
            [{"url": f"/manifest/{str(self.imaging.globalid).upper()}"}],
        )
        self.embargo(self.analyses["open"])

        self.assertEqual(self.visitor.get(self.url()).status_code, 200)

    def test_the_manifest_of_a_draft_analysis_is_served_as_its_annotation_is(self):
        self.make_draft(self.analyses["open"])

        self.assertEqual(self.visitor.get(self.url()).status_code, 200)

    def test_a_document_source_manifest_follows_the_document(self):
        source = self.stored("Ms 211", copy.deepcopy(SOURCE_MANIFEST))
        self.tile(
            self.documents["embargoed"],
            "facsimiles",
            f"{BASE}manifest/{source.globalid}",
        )
        self.assertEqual(self.visitor.get(self.url(source)).status_code, 200)

        self.embargo(self.documents["embargoed"])

        self.assert_bodyless_404(self.visitor.get(self.url(source)))

    def test_an_id_only_written_in_another_url_names_nothing(self):
        node = self.nodes[("analysis", "chemical_imaging_manifest")]
        TileModel.objects.filter(
            resourceinstance=self.analyses["open"], nodegroup_id=node.nodegroup_id
        ).update(
            data={
                str(
                    node.nodeid
                ): f"https://elsewhere.example/manifest/{self.imaging.globalid}"
            }
        )

        self.assert_bodyless_404(self.visitor.get(self.url()))

    def test_an_invalid_bearer_is_a_401_with_cors(self):
        response = Client().get(self.url(), **bearer("msiiif1.forged"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertEqual(response.json()["type"], "Manifest")


class HttpTests(StoredManifestCase):
    def url(self):
        return path_of(ids.stored_manifest(self.imaging.globalid))

    def test_the_visitor_answer_is_public_with_a_strong_etag(self):
        first = self.visitor.get(self.url())

        self.assertEqual(first["Cache-Control"], "public, no-cache")
        self.assertRegex(first["ETag"], r'^"[0-9a-f]{40}"$')
        again = self.visitor.get(self.url(), HTTP_IF_NONE_MATCH=first["ETag"])
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again["ETag"], first["ETag"])
        self.assertEqual(again["Access-Control-Allow-Origin"], "*")

    def test_a_shared_answer_counts_as_shared(self):
        with delta("manuspectrum_iiif_answers_total", mode="shared") as shared:
            self.visitor.get(self.url())

        self.assertEqual(shared.value, 1)

    def test_a_not_modified_answer_counts_as_not_modified(self):
        etag = self.visitor.get(self.url())["ETag"]

        with delta("manuspectrum_iiif_answers_total", mode="not_modified") as held:
            self.visitor.get(self.url(), HTTP_IF_NONE_MATCH=etag)

        self.assertEqual(held.value, 1)

    def test_a_private_answer_counts_as_private(self):
        reader = Client()
        reader.force_login(self.editor)
        self.embargo(self.analyses["open"])

        with delta("manuspectrum_iiif_answers_total", mode="private") as private:
            self.assertEqual(reader.get(self.url()).status_code, 200)

        self.assertEqual(private.value, 1)

    def test_a_changed_manifest_changes_the_etag(self):
        first = self.visitor.get(self.url())
        manifest = copy.deepcopy(self.imaging.manifest)
        manifest["label"] = "maXRF_map1 - renamed"
        IIIFManifest.objects.filter(pk=self.imaging.pk).update(manifest=manifest)

        again = self.visitor.get(self.url(), HTTP_IF_NONE_MATCH=first["ETag"])

        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["label"], "maXRF_map1 - renamed")

    def test_a_preflight_allows_authorization(self):
        response = Client().options(
            self.url(),
            HTTP_ORIGIN=DEMO,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization",
        )

        self.assertLess(response.status_code, 300)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("authorization", response["Access-Control-Allow-Headers"].lower())

    def test_head_answers_without_a_body(self):
        response = self.visitor.head(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")

    def test_a_write_is_not_allowed(self):
        self.assertEqual(self.visitor.post(self.url()).status_code, 405)

    def test_the_answer_is_language_neutral(self):
        response = self.visitor.get(self.url(), HTTP_ACCEPT_LANGUAGE="fr")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("accept-language", response.get("Vary", "").lower())
        self.assertNotIn("Content-Language", response)
        for code, _ in settings.LANGUAGES:
            self.assertEqual(self.visitor.get(f"/{code}{self.url()}").status_code, 404)


class PublishedJsonTests(StoredManifestCase):
    def published(self, stored):
        response = self.visitor.get(path_of(ids.stored_manifest(stored.globalid)))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_the_arches_id_written_on_another_host_becomes_the_route(self):
        globalid = self.imaging.globalid
        IIIFManifest.objects.filter(pk=self.imaging.pk).update(
            manifest=arches_manifest(globalid, host="http://dev.example:8000")
        )

        self.assertEqual(
            self.published(self.imaging)["@id"], ids.stored_manifest(globalid)
        )

    def test_legacy_hosts_are_rewritten_in_every_id(self):
        globalid = self.imaging.globalid
        IIIFManifest.objects.filter(pk=self.imaging.pk).update(
            manifest=arches_manifest(globalid, host="https://old.example")
        )

        with self.settings(EXPLORER_LEGACY_HOSTS=("old.example",)):
            canvas = self.published(self.imaging)["sequences"][0]["canvases"][0]

        self.assertEqual(
            canvas["@id"], f"{BASE}iiifserver/iiif/manifest/canvas/pb.json"
        )

    def test_the_stored_row_is_left_unchanged(self):
        before = copy.deepcopy(self.imaging.manifest)

        self.published(self.imaging)

        self.imaging.refresh_from_db()
        self.assertEqual(self.imaging.manifest, before)


ORIGINAL = "https://emmsm.unicaen.fr/manifests/Avranches_BM_59.json"
V3_PROFILE = "http://iiif.io/api/presentation/3/context.json"
V2_PROFILE = "http://iiif.io/api/presentation/2/context.json"


class OriginalLinkTests(StoredManifestCase):
    """An imported manifest is served under our id and links to its publisher's URL."""

    def imported(self, manifest):
        row = self.stored("Ms 59", manifest)
        IIIFManifest.objects.filter(pk=row.pk).update(url=ORIGINAL)
        self.tile(
            self.analyses["on_document"],
            "chemical_imaging_manifest",
            f"/manifest/{row.globalid}",
        )
        cache.clear()
        return row

    def served(self, row):
        with (
            patch(
                "manuspectrum.utils.iiif_tools.CanvasIIIF.fetch_manifest",
                side_effect=AssertionError("network"),
            ),
            patch(
                "manuspectrum.utils.http.get_iiif_session",
                side_effect=AssertionError("network"),
            ),
        ):
            response = self.visitor.get(path_of(ids.stored_manifest(row.globalid)))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_a_v3_imported_manifest_links_its_original(self):
        row = self.imported(copy.deepcopy(SOURCE_MANIFEST))

        body = self.served(row)

        self.assertEqual(body["id"], ids.stored_manifest(row.globalid))
        self.assertEqual(
            body["seeAlso"],
            [
                {
                    "id": ORIGINAL,
                    "type": "Dataset",
                    "format": "application/ld+json",
                    "profile": V3_PROFILE,
                }
            ],
        )
        self.assertEqual(body["items"], SOURCE_MANIFEST["items"])

    def test_a_v2_imported_manifest_links_its_original(self):
        row = self.imported(arches_manifest(uuid.uuid4(), host="https://emmsm.example"))

        body = self.served(row)

        self.assertEqual(body["@id"], ids.stored_manifest(row.globalid))
        self.assertEqual(
            body["seeAlso"],
            [{"@id": ORIGINAL, "format": "application/ld+json", "profile": V2_PROFILE}],
        )

    def test_an_existing_see_also_is_kept(self):
        manifest = copy.deepcopy(SOURCE_MANIFEST)
        manifest["seeAlso"] = {"id": "https://example.org/other", "type": "Text"}
        row = self.imported(manifest)

        ids_seen = [entry["id"] for entry in self.served(row)["seeAlso"]]

        self.assertEqual(ids_seen, ["https://example.org/other", ORIGINAL])

    def test_a_string_see_also_is_kept_and_not_duplicated(self):
        manifest = arches_manifest(uuid.uuid4())
        manifest["seeAlso"] = ORIGINAL
        row = self.imported(manifest)

        self.assertEqual(self.served(row)["seeAlso"], [ORIGINAL])

    def test_a_manifest_created_here_has_no_see_also(self):
        body = self.served(self.imaging)

        self.assertNotIn("seeAlso", body)
        self.assertEqual(body["@id"], ids.stored_manifest(self.imaging.globalid))

    def test_the_legacy_host_rewrite_still_applies(self):
        row = self.imported(arches_manifest(uuid.uuid4(), host="https://old.example"))

        with self.settings(EXPLORER_LEGACY_HOSTS=("old.example",)):
            canvas = self.served(row)["sequences"][0]["canvases"][0]

        self.assertEqual(
            canvas["@id"], f"{BASE}iiifserver/iiif/manifest/canvas/pb.json"
        )


class ManifestSourceTests(StoredManifestCase):
    def test_the_four_kinds_of_reference(self):
        imported = self.stored("Imported")
        IIIFManifest.objects.filter(pk=imported.pk).update(url=ORIGINAL)
        legacy = "https://example.org/iiif/legacy.json"
        IIIFManifest.objects.create(
            globalid=uuid.uuid4(), label="Legacy", url=legacy, manifest={}
        )
        refs = [
            f"/manifest/{imported.globalid}",
            f"/manifest/{self.imaging.globalid}",
            legacy,
            "https://example.org/never-stored.json",
            f"/manifest/{uuid.uuid4()}",
            "",
        ]

        with CaptureQueriesContext(connection) as queries:
            found = manifest_sources(refs)
        selects = [q for q in queries if q["sql"].startswith("SELECT")]
        self.assertEqual(len(selects), 1)

        self.assertEqual(
            found,
            {
                refs[0]: ManifestSource(ORIGINAL, "Imported"),
                refs[1]: ManifestSource(None, "maXRF_map1 - illumination - f1v"),
                legacy: ManifestSource(legacy, "Legacy"),
                refs[3]: ManifestSource(refs[3], None),
            },
        )

    def test_the_wrapper_returns_one_source_or_none(self):
        self.assertEqual(
            manifest_source(f"/manifest/{self.imaging.globalid}"),
            ManifestSource(None, "maXRF_map1 - illumination - f1v"),
        )
        self.assertIsNone(manifest_source(f"/manifest/{uuid.uuid4()}"))
        self.assertIsNone(manifest_source(""))
