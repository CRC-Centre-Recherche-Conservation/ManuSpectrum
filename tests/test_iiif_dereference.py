"""Every id the IIIF output names on this site dereferences cross-origin (issue #293).

The output of a corpus whose manifests are stored in Arches, as every
manifest tile stores them, is walked from its entry points: the annotation
and characterization collections of a Document and of a Component in both API
versions, a content state and the Explorer manifest of the Document. Every
``id`` and ``@id`` on ``PUBLIC_SERVER_ADDRESS``, every ``@context`` entry on
it and every v2 ``otherContent`` is fetched as a viewer on another origin
fetches it (no cookie, an ``Origin``) and must answer a 200 with
``Access-Control-Allow-Origin: *``, never a redirect; each JSON answer is
walked in turn.

A viewer never fetches some of them, each left out for its reason
(``exempt``):

- an id the Explorer manifest mints for what it embeds (``ids.explorer_part``:
  painting pages, ranges) and a canvas, embedded in its manifest: IIIF
  requires no dereference of an embedded resource;
- the image server (``/iiifserver/``), served by the edge, not by Django
  (``deploy/compose/nginx/tests/test_edge.sh`` checks its CORS);
- a page for people (``format`` ``text/html``: the report, the Explorer page)
  and the xyReading documentation (``conformsTo``): a browser navigates to
  them, and the report sits under the language prefix;
- the IIIF Auth interaction services (login, token, logout): a viewer opens
  them in a window or an iframe, never with ``fetch``.

A stored manifest is checked and not walked: it is served as stored, and the
ids in it are its publisher's (Arches' image server, for one the Image
Service Manager made).

Usage:
    python manage.py test tests.test_iiif_dereference --settings=tests.test_settings
"""

import copy
import json
import uuid
from urllib.parse import urldefrag

from django.conf import settings
from django.core.cache import cache
from django.test import Client
from django.urls import Resolver404, resolve

from arches.app.models.models import TileModel

from manuspectrum.iiif import ids, services
from tests.explorer_fixtures import CANVAS, FEATURES, POINT, SOURCE_MANIFEST
from tests.iiif_auth import DEMO
from tests.test_iiif_manifests import StoredManifestCase

BASE = settings.PUBLIC_SERVER_ADDRESS
AUTH_INTERACTION_TYPES = {
    "AuthAccessService2",
    "AuthAccessTokenService2",
    "AuthLogoutService2",
}
AUTH_INTERACTION_PROFILES = {
    services.LOGIN_PROFILE,
    services.TOKEN_PROFILE,
    services.LOGOUT_PROFILE,
}


def path_of(url):
    return "/" + urldefrag(url)[0][len(BASE) :]


def links(node):
    """``(url, holder, key)`` of every reference of a JSON document: ids, ``@context`` entries, ``otherContent``, ``conformsTo``."""
    if isinstance(node, list):
        for item in node:
            yield from links(item)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key in ("id", "@id", "conformsTo") and isinstance(value, str):
            yield value, node, key
        elif key in ("@context", "otherContent"):
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, str):
                    yield item, node, key
                else:
                    yield from links(item)
        else:
            yield from links(value)


def exempt(url, holder, key):
    """Why a viewer never fetches *url*, None when it does."""
    if url.startswith(ids.explorer_manifest() + "/"):
        return "an embedded resource of the Explorer manifest"
    if holder.get("type") == "Canvas" or holder.get("@type") == "sc:Canvas":
        return "a canvas, embedded in its manifest"
    if url.startswith(f"{BASE}iiifserver/"):
        return "the image server, behind the edge"
    if key == "conformsTo":
        return "documentation for people"
    if holder.get("format") == "text/html":
        return "a page for people"
    if (
        holder.get("type") in AUTH_INTERACTION_TYPES
        or holder.get("profile") in AUTH_INTERACTION_PROFILES
    ):
        return "an IIIF Auth interaction service, opened in a window"
    return None


class DereferenceTests(StoredManifestCase):
    """The corpus of ``StoredManifestCase`` with its source manifest stored too, a data file and a located identified material."""

    def setUp(self):
        super().setUp()
        self.source = self.stored("Ms 59", copy.deepcopy(SOURCE_MANIFEST))
        node = self.nodes[("document", "facsimiles")]
        TileModel.objects.filter(
            resourceinstance=self.documents["open"], nodegroup_id=node.nodegroup_id
        ).update(data={str(node.nodeid): f"/manifest/{self.source.globalid}"})
        self.stored_file(self.analyses["open"], "x01.csv", b"1,2\n3,4\n5,6\n")
        self.zone(
            self.characterization,
            [(str(uuid.uuid4()), CANVAS, POINT)],
            alias="location_of_characterization",
        )
        cache.clear()

    def entry_points(self):
        document, component = self.documents["open"].pk, self.components["open"].pk
        found = [
            ids.collection(subject, kind, version)
            for subject in (document, component)
            for kind in ("analysis", "characterization")
            for version in (3, 2)
        ]
        found.append(ids.content_state(self.analyses["open"].pk, FEATURES["open"]))
        found.append(ids.explorer_manifest(f"document={document}"))
        return found

    def walk(self):
        """``({url: route name}, [failure])`` of every id the output names on this site, from ``entry_points``."""
        checked, failures, exempted = {}, [], {}
        queue = self.entry_points()
        while queue:
            url = queue.pop(0)
            if url in checked:
                continue
            path = path_of(url)
            try:
                checked[url] = resolve(path.split("?")[0]).url_name
            except Resolver404:
                checked[url] = None
            response = Client().get(path, HTTP_ORIGIN=DEMO)
            if (
                response.status_code != 200
                or response.get("Access-Control-Allow-Origin") != "*"
            ):
                failures.append(
                    f"{url}: {response.status_code}"
                    f" {response.get('Location', '')}"
                    f" CORS={response.get('Access-Control-Allow-Origin')}"
                )
                continue
            if (
                "json" not in response["Content-Type"]
                or checked[url] == "iiif-manifest"
            ):
                continue
            for found, holder, key in links(json.loads(response.content)):
                if not found.startswith(BASE):
                    continue
                reason = exempt(found, holder, key)
                if reason:
                    exempted[found] = reason
                elif found not in checked:
                    queue.append(found)
        self.exempted = exempted
        return checked, failures

    def test_every_id_meant_to_be_fetched_answers_200_with_cors(self):
        checked, failures = self.walk()

        self.assertEqual(failures, [], "\n".join(failures))
        reached = set(checked.values())
        for name in (
            "iiif-v3-annotation-collection",
            "iiif-v3-annotation-page",
            "iiif-v3-annotation-zone",
            "iiif-v2-annotation-collection",
            "iiif-v2-annotation-page",
            "iiif-v2-annotation-zone",
            "iiif-v3-characterization-collection",
            "iiif-v3-characterization-page",
            "iiif-v2-characterization-page",
            "iiif-v3-content-state",
            "iiif-v3-explorer-manifest",
            "iiif-manifest",
            "iiif-data-series",
            "iiif-auth-probe",
            "iiif-xy-reading-context",
        ):
            self.assertIn(name, reached)
        self.assertIn(ids.stored_manifest(self.source.globalid), checked)
        self.assertIn(ids.stored_manifest(self.imaging.globalid), checked)

    def test_what_a_viewer_never_fetches_is_left_out_for_a_reason(self):
        self.walk()

        reasons = set(self.exempted.values())
        self.assertIn("a page for people", reasons)
        self.assertIn("an IIIF Auth interaction service, opened in a window", reasons)
        self.assertIn(ids.auth_login(), self.exempted)
        self.assertIn(ids.report(self.analyses["open"].pk), self.exempted)
