"""GET APIs of the Explorer's Corpus view (spec §5), above the language boundary.

Every answer goes through ``_answer``: the guard has already decided by
building the payload from ``visible_set``; a payload the visitor may read is
the same for every visitor, so it is sent ``public, no-cache`` with a strong
ETag computed from its bytes; a signed-in reader's is ``private, no-store``.
Unknown and refused alike answer a bodyless 404.
"""

import hashlib

import orjson
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseNotModified
from django.utils import translation
from django.views import View

from manuspectrum.utils.cache import etag_already_held, renews_csrf_cookie
from manuspectrum.utils.public_visibility import is_connected
from manuspectrum.views.explorer_service import (
    analysis_payload,
    document_payload,
    search_payload,
)


def _answer(request, payload):
    """The HTTP answer for *payload*; None is the not-found answer."""
    if payload is None:
        response = HttpResponseNotFound()
        response["Cache-Control"] = "private, no-store"
        return response
    body = orjson.dumps(payload)
    if is_connected(request.user) or renews_csrf_cookie(request):
        response = HttpResponse(body, content_type="application/json")
        response["Cache-Control"] = "private, no-store"
        return response
    etag = '"%s"' % hashlib.md5(body, usedforsecurity=False).hexdigest()
    if etag_already_held(request, etag):
        response = HttpResponseNotModified()
    else:
        response = HttpResponse(body, content_type="application/json")
    response["ETag"] = etag
    response["Cache-Control"] = "public, no-cache"
    return response


class ExplorerSearchView(View):
    """``GET /{lang}/api/explorer/search``: results, facets and counts for the reader."""

    def get(self, request):
        return _answer(
            request,
            search_payload(request.GET, request.user, translation.get_language()),
        )


class ExplorerDocumentView(View):
    """``GET /{lang}/api/explorer/document/<uuid>``: canvases, annotations and identified materials of one document."""

    def get(self, request, resourceid):
        return _answer(
            request,
            document_payload(resourceid, request.user, translation.get_language()),
        )


class ExplorerAnalysisView(View):
    """``GET /{lang}/api/explorer/analysis/<uuid>``: one analysis with its files, conditions, evidence and dataset."""

    def get(self, request, resourceid):
        return _answer(
            request,
            analysis_payload(resourceid, request.user, translation.get_language()),
        )
