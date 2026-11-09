"""``/iiif/manifest/<uuid>``: a manifest stored in Arches, as the IIIF output names it (``ids.stored_manifest``).

Arches serves the same JSON at ``/manifest/<uuid>``, a route under the
language prefix (a bare request is a 302) that sends no CORS header: a viewer
on another origin cannot load it. This route is language-neutral and carries
the IIIF CORS headers on every answer (``IIIFView``).

The guard is ``iiif.stored_manifests.readable_manifest``: a manifest no
resource the reader may see names, and an unknown id, are a bodyless 404; a
Bearer credential that is not a valid IIIF token is a 401. The body is
``sources.published_manifest`` of the stored JSON, with the media type of its
Presentation version. A reader whose view is the visitor's (never a token
reader) gets ``public, no-cache`` and a strong ETag (the digest of the body)
that an ``If-None-Match`` answers with a 304; any other reader ``private,
no-store``. Nothing is memoised: the manifest is one row.
"""

import hashlib

import orjson
from django.http import HttpResponse, HttpResponseNotModified

from manuspectrum.iiif import memo, stored_manifests
from manuspectrum.iiif.constants import IIIF_MEDIA_TYPE, IIIF_V2_MEDIA_TYPE
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
        stored = stored_manifests.readable_manifest(
            globalid, reader_of(request), version
        )
        if stored is None:
            raise Missing()
        body = orjson.dumps(published_manifest(stored, globalid))
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
