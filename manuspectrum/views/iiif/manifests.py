"""``/iiif/manifest/<uuid>``: a manifest stored in Arches, as the IIIF output names it (``ids.stored_manifest``).

Arches serves the same JSON at ``/manifest/<uuid>``, a route under the
language prefix (a bare request is a 302) that sends no CORS header: a viewer
on another origin cannot load it. This route is language-neutral and carries
the IIIF CORS headers on every answer (``IIIFView``).

The guard is ``iiif.stored_manifests.readable_manifest``: a manifest no
resource the reader may see names, and an unknown id, are a bodyless 404; a
Bearer credential that is not a valid IIIF token is a 401. The body is
``sources.published_manifest`` of the stored JSON (our id, and the publisher's
URL in ``seeAlso`` for an imported manifest), with the media type of its
Presentation version. A reader whose view is the visitor's (never a token
reader) gets ``public, no-cache`` and a strong ETag (the digest of the body)
that an ``If-None-Match`` answers with a 304; any other reader ``private,
no-store``. Nothing is memoised: the manifest is one row.
"""

import hashlib
import logging

from urllib.parse import urlsplit

import orjson
from django.conf import settings
from django.http import HttpResponse, HttpResponseNotModified, HttpResponseRedirect
from django.urls import reverse
from django.utils import translation
from django.utils.cache import patch_vary_headers
from django.utils.decorators import method_decorator
from django.views import View

from manuspectrum.iiif import ids, memo, stored_manifests
from manuspectrum.iiif.constants import IIIF_MEDIA_TYPE, IIIF_V2_MEDIA_TYPE
from manuspectrum.iiif.sources import published_manifest
from manuspectrum.observability import metrics
from manuspectrum.utils.cache import etag_already_held, renews_csrf_cookie
from manuspectrum.utils.data_version import data_version
from manuspectrum.utils.iiif_tools import CanvasIIIF
from manuspectrum.utils.public_visibility import request_memo
from manuspectrum.views.iiif.annotations import IIIFView, Missing, gate_of, reader_of
from manuspectrum.views.iiif.cors import iiif_cors

logger = logging.getLogger(__name__)


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


def _origin(url):
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.netloc else None


def is_same_origin(request):
    """Whether a browser sends *request* from a page of this site: ``Sec-Fetch-Site: same-origin``, or an ``Origin`` equal to the site's own.

    No ``Sec-Fetch-Site`` (curl, harvesters) and ``none`` (a typed URL, a
    bookmark) are not same-origin.
    """
    if request.headers.get("Sec-Fetch-Site") == "same-origin":
        return True
    origin = request.headers.get("Origin")
    if not origin:
        return False
    return origin.lower() in {
        _origin(settings.PUBLIC_SERVER_ADDRESS),
        _origin(request.build_absolute_uri("/")),
    }


@method_decorator(iiif_cors, name="dispatch")
class LegacyManifestView(View):
    """``/manifest/<uuid>``, the bare path every manifest tile stores: a 302 to where the requester reads the manifest.

    A same-origin browser request (``is_same_origin``: the Arches IIIF viewer,
    the annotation tools, the manifest widget) always goes to Arches' route
    under the language of the request, ``/<lang>/manifest/<uuid>``, as a bare
    request did before this route. Any other request goes to
    ``ids.stored_manifest`` when the manifest is named for the reader
    (``stored_manifests.named_for``), else to Arches' route too (a manifest no
    tile names yet, just created, is still read by the Arches viewer). The
    answer depends on the reader, the data and the fetch headers: 302,
    ``private, no-store``, varying on ``Authorization``, ``Cookie``,
    ``Sec-Fetch-Site`` and ``Origin``. A Bearer credential that is not valid
    is ignored (the reader is the visitor); the target answers 401 to it. The
    query string is dropped. A preflight is answered 204 by ``iiif_cors``,
    never redirected. ``iiif_cors`` owns the CORS headers of this path:
    ``CORS_URLS_REGEX`` keeps ``django-cors-headers`` off it.
    """

    http_method_names = ["get", "head", "options"]

    def get(self, request, globalid):
        named = False
        if not is_same_origin(request):
            try:
                with request_memo(getattr(request, "user", None)):
                    named = stored_manifests.named_for(globalid, reader_of(request))
            except Exception:
                logger.exception("Legacy manifest lookup failed: %s", request.path)
        if named:
            target = ids.stored_manifest(globalid)
        else:
            with translation.override(translation.get_language_from_request(request)):
                target = reverse("manifest", kwargs={"id": str(globalid)})
        response = HttpResponseRedirect(target)
        response["Cache-Control"] = memo.PRIVATE
        patch_vary_headers(response, ("Sec-Fetch-Site", "Origin"))
        return response
