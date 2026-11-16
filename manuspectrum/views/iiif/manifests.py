"""The manifest routes: ``/iiif/manifest/<uuid>`` (stored manifest) and ``/iiif/v3|v2/manifest/<uuid>`` (document manifest).

``/iiif/manifest/<uuid>`` is a manifest stored in Arches, as the IIIF output
names it (``ids.stored_manifest``). Arches serves the same JSON at
``/manifest/<uuid>``, a route under the language prefix (a bare request is a
302) that sends no CORS header: a viewer on another origin cannot load it. The
route is language-neutral and carries the IIIF CORS headers on every answer
(``IIIFView``).

Its guard is ``iiif.stored_manifests.readable_manifest``: a manifest no
resource the reader may see names, and an unknown id, are a bodyless 404; a
Bearer credential that is not a valid IIIF token is a 401. The body is
``sources.published_manifest`` of the stored JSON (our id, and the publisher's
URL in ``seeAlso`` for an imported manifest), with the media type of its
Presentation version. A reader whose view is the visitor's (never a token
reader) gets ``public, no-cache`` and a strong ETag (the digest of the body)
that an ``If-None-Match`` answers with a 304; any other reader ``private,
no-store``. Nothing is memoised: the manifest is one row.

``/iiif/v3/manifest/<uuid>`` is the manifest of a Document or Component built
by ``iiif.document_manifest`` (it differs from the stored manifest above). It
is memoised like the annotation collection (``iiif.memo``): a Document or
Component the reader may not read, an unknown id, and one without a readable
source manifest or placed zone, are a bodyless 404; more canvases than
``EXPLORER_MANIFEST_MAX_CANVASES`` is a bodyless 413, ``private, no-store``,
never stored.
"""

import hashlib

import orjson
from django.http import HttpResponse, HttpResponseNotModified

from manuspectrum.iiif import document_manifest, facts, memo, stored_manifests
from manuspectrum.iiif.constants import IIIF_MEDIA_TYPE, IIIF_V2_MEDIA_TYPE
from manuspectrum.iiif.manifest import ManifestTooLarge
from manuspectrum.iiif.sources import published_manifest
from manuspectrum.observability import metrics
from manuspectrum.utils.cache import etag_already_held, renews_csrf_cookie
from manuspectrum.utils.data_version import data_version
from manuspectrum.utils.iiif_tools import CanvasIIIF
from manuspectrum.views.iiif.annotations import IIIFView, Missing, gate_of, reader_of


class StoredManifestView(IIIFView):
    """One stored manifest, in the Presentation version it was stored in."""

    described_as = "Manifest"

    def answer(self, request, globalid):
        version = data_version()
        found = stored_manifests.readable_manifest(
            globalid, reader_of(request), version
        )
        if found is None:
            raise Missing()
        stored, original = found
        body = orjson.dumps(published_manifest(stored, globalid, original))
        shared = gate_of(request, version).shared and not renews_csrf_cookie(request)
        etag = f'"{hashlib.sha1(body, usedforsecurity=False).hexdigest()}"'
        if shared and etag_already_held(request, etag):
            metrics.IIIF_ANSWERS.labels(mode="not_modified").inc()
            response = HttpResponseNotModified()
        else:
            metrics.IIIF_ANSWERS.labels(mode="shared" if shared else "private").inc()
            response = HttpResponse(
                body,
                content_type=(
                    IIIF_MEDIA_TYPE
                    if CanvasIIIF.detect_version(stored) == 3
                    else IIIF_V2_MEDIA_TYPE
                ),
            )
        response["Cache-Control"] = memo.PUBLIC if shared else memo.PRIVATE
        if shared:
            response["ETag"] = etag
        return response


class DocumentManifestView(IIIFView):
    """The Presentation 3 manifest of a Document or Component."""

    described_as = "Manifest"

    def answer(self, request, resource_id):
        reader = reader_of(request)
        version = data_version()
        subject = facts.subject_of(resource_id, reader, version)
        if subject is None:
            raise Missing()

        def build():
            built = document_manifest.build(
                str(resource_id),
                reader,
                version=version,
                subject=subject,
                api=self.version,
            )
            if built is None:
                raise Missing()
            return built

        try:
            return memo.answer(
                request,
                gate_of(request, version),
                f"manifest-v{self.version}",
                (resource_id,),
                build,
                content_type=self.content_type,
            )
        except ManifestTooLarge:
            response = HttpResponse(status=413)
            response["Cache-Control"] = memo.PRIVATE
            return response


class DocumentManifestViewV2(DocumentManifestView):
    """The Presentation 2.1 manifest of a Document or Component."""

    version = 2
