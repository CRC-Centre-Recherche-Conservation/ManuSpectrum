"""GET APIs of the Explorer's Corpus view (spec §5), above the language boundary.

Every reader, signed in or not, is answered with the visitor's view (spec
D59): each payload is built from the ``visible_set`` of ``anonymous_user()``,
so an embargoed resource or a restricted nodegroup shows to nobody until it
is opened. Every answer goes through ``_answer``: the visitor's is sent
``public, no-cache`` with a strong ETag; a signed-in reader's, same content,
``private, no-store`` (its response may renew the CSRF cookie). Unknown and refused
alike answer a bodyless 404. Answers are gzipped; the compression turns the
ETag weak, which ``etag_already_held`` accepts.

The ETag of a payload built from the corpus bundle alone (search, facet,
match, home) is computed before building it, from the bundle key, the route
and the query as the payload reads it, so a revalidation answers 304 without
building anything. The document, analysis and items payloads embed IIIF
manifests fetched over HTTP, which the data version does not follow: their
ETag is the digest of the body.
"""

import datetime
import hashlib

import orjson
from django.conf import settings
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotFound,
    HttpResponseNotModified,
)
from django.utils import translation
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.gzip import gzip_page

from manuspectrum.utils.cache import etag_already_held, renews_csrf_cookie
from manuspectrum.utils.public_visibility import anonymous_user, is_connected
from manuspectrum.views.explorer import memo as explorer_memo
from manuspectrum.views.explorer.manifest import ManifestTooLarge, build_manifest
from manuspectrum.views.explorer.scopes import (
    ScopeError,
    export_language,
    resolve_scope,
    share_payload,
)
from manuspectrum.views.explorer.service import (
    FACET_KEYS,
    analysis_payload,
    document_payload,
    document_scope,
    facet_payload,
    home_payload,
    items_payload,
    match_payload,
    parse_filters,
    parse_keys,
    search_payload,
    wants_facets,
)

HOME_DAY_MARGIN = datetime.timedelta(days=1)
IIIF_MEDIA_TYPE = (
    'application/ld+json;profile="http://iiif.io/api/presentation/3/context.json"'
)


def _shared(request):
    """Whether the answer is the visitor's, which every visitor shares."""
    return not (is_connected(request.user) or renews_csrf_cookie(request))


def _not_found():
    response = HttpResponseNotFound()
    response["Cache-Control"] = "private, no-store"
    return response


def _answer(request, build, token=None, content_type="application/json"):
    """The HTTP answer for the payload ``build()`` returns; None is the not-found answer.

    *token* names the payload before it is built; without it the ETag is the
    digest of the body.
    """
    shared = _shared(request)
    etag = f'"{token}"' if token else None
    if shared and etag and etag_already_held(request, etag):
        return _not_modified(etag)
    payload = build()
    if payload is None:
        return _not_found()
    body = orjson.dumps(payload)
    if not shared:
        response = HttpResponse(body, content_type=content_type)
        response["Cache-Control"] = "private, no-store"
        return response
    etag = etag or '"%s"' % hashlib.md5(body, usedforsecurity=False).hexdigest()
    if etag_already_held(request, etag):
        return _not_modified(etag)
    response = HttpResponse(body, content_type=content_type)
    response["ETag"] = etag
    response["Cache-Control"] = "public, no-cache"
    return response


def _not_modified(etag):
    response = HttpResponseNotModified()
    response["ETag"] = etag
    response["Cache-Control"] = "public, no-cache"
    return response


def _token(route, ticket, *parts):
    """The ETag of a payload of *route* over the bundle of *ticket*, named by *parts*."""
    return hashlib.sha1(
        orjson.dumps(
            [settings.CACHE_CODE_VERSION, route, ticket.key, *parts],
            option=orjson.OPT_SORT_KEYS,
        ),
        usedforsecurity=False,
    ).hexdigest()


def _filters(query):
    """The filters of *query* as ``row_filter`` reads them, without grain, page and size."""
    filters, _ = parse_filters(query)
    return {key: filters[key] for key in (*FACET_KEYS, "q")}


def _ticket(reader):
    return explorer_memo.ticket(reader, translation.get_language())


@method_decorator(gzip_page, name="dispatch")
class ExplorerSearchView(View):
    """``GET /{lang}/api/explorer/search``: results, facets and counts for the reader.

    The visitor's ETag is computed before building, from the bundle key, the route and the filters, page and facet request: a revalidation answers 304 without building.
    """

    def get(self, request):
        reader = anonymous_user()
        ticket, language = _ticket(reader), translation.get_language()
        filters, page = parse_filters(request.GET)
        token = _token("search", ticket, filters, page, wants_facets(request.GET))
        return _answer(
            request,
            lambda: search_payload(request.GET, reader, language, ticket),
            token,
        )


@method_decorator(gzip_page, name="dispatch")
class ExplorerFacetView(View):
    """``GET /{lang}/api/explorer/facet/<key>``: every value of one facet under the filters, narrowed by ``find``.

    Over the whole corpus, or over one document with ``document=<uuid>``.
    The visitor's ETag is computed before building, from the bundle key, the route and the key, document, filters and ``find``: a revalidation answers 304 without building.
    """

    def get(self, request, key):
        document_id = document_scope(request.GET)
        if key not in FACET_KEYS or document_id is None:
            return _not_found()
        reader = anonymous_user()
        ticket, language = _ticket(reader), translation.get_language()
        token = _token(
            "facet",
            ticket,
            key,
            document_id,
            _filters(request.GET),
            request.GET.get("find", "").strip(),
        )
        return _answer(
            request,
            lambda: facet_payload(key, request.GET, reader, language, ticket),
            token,
        )


@method_decorator(gzip_page, name="dispatch")
class ExplorerHomeView(View):
    """``GET /{lang}/api/explorer/home?day=YYYY-MM-DD``: the explorer home of the reader's day.

    *day* is the reader's local date; one more than a day away from the
    server's date is a bad request. The visitor's ETag is computed before
    building, from the bundle key, the route and *day*: a revalidation
    answers 304 without building.
    """

    def get(self, request):
        day = request.GET.get("day", "")
        try:
            date = datetime.date.fromisoformat(day)
        except ValueError:
            return HttpResponseBadRequest()
        if day != date.isoformat() or (
            abs(date - datetime.date.today()) > HOME_DAY_MARGIN
        ):
            return HttpResponseBadRequest()
        reader = anonymous_user()
        ticket, language = _ticket(reader), translation.get_language()
        return _answer(
            request,
            lambda: home_payload(day, reader, language, ticket),
            _token("home", ticket, day),
        )


@method_decorator(gzip_page, name="dispatch")
class ExplorerDocumentView(View):
    """``GET /{lang}/api/explorer/document/<uuid>``: canvases, analyses and identified materials of one document.

    The visitor's ETag is the digest of the body: the payload embeds IIIF manifests the data version does not follow, so a revalidation builds it.
    """

    def get(self, request, resourceid):
        reader, language = anonymous_user(), translation.get_language()
        return _answer(
            request,
            lambda: document_payload(resourceid, reader, language),
        )


@method_decorator(gzip_page, name="dispatch")
class ExplorerDocumentMatchView(View):
    """``GET /{lang}/api/explorer/document/<uuid>/match``: what the Corpus filters keep in one document.

    The visitor's ETag is computed before building, from the bundle key, the route and the document and filters: a revalidation answers 304 without building.
    """

    def get(self, request, resourceid):
        reader = anonymous_user()
        ticket, language = _ticket(reader), translation.get_language()
        token = _token("match", ticket, str(resourceid), _filters(request.GET))
        return _answer(
            request,
            lambda: match_payload(resourceid, request.GET, reader, language, ticket),
            token,
        )


@method_decorator(gzip_page, name="dispatch")
class ExplorerAnalysisView(View):
    """``GET /{lang}/api/explorer/analysis/<uuid>``: one analysis with its files, conditions, evidence and dataset.

    The visitor's ETag is the digest of the body: the payload embeds IIIF manifests the data version does not follow, so a revalidation builds it.
    """

    def get(self, request, resourceid):
        reader, language = anonymous_user(), translation.get_language()
        return _answer(
            request,
            lambda: analysis_payload(resourceid, reader, language),
        )


@method_decorator(gzip_page, name="dispatch")
class ExplorerItemsView(View):
    """``GET /{lang}/api/explorer/items?ids=``: the Selection's items, at most ``EXPLORER_ITEMS_MAX`` keys.

    The visitor's ETag is the digest of the body: the payload embeds IIIF manifests the data version does not follow, so a revalidation builds it.
    """

    def get(self, request):
        keys = parse_keys(request.GET)
        if len(keys) > settings.EXPLORER_ITEMS_MAX:
            return HttpResponseBadRequest()
        reader, language = anonymous_user(), translation.get_language()
        return _answer(
            request,
            lambda: items_payload(keys, reader, language),
        )


@method_decorator(gzip_page, name="dispatch")
class ExplorerShareView(View):
    """``GET /{lang}/api/explorer/share?ids=|document=|project=``: citations and export estimate of a scope.

    Malformed scope parameters answer a bodyless 400; a scope with nothing
    visible the bodyless 404. The visitor's ETag is the digest of the body:
    the payload carries the day of consultation and counts files of imaging
    manifests the data version does not follow.
    """

    def get(self, request):
        language = translation.get_language()
        try:
            scope = resolve_scope(request.GET, language)
        except ScopeError:
            return HttpResponseBadRequest()
        if scope is None:
            return _not_found()
        return _answer(request, lambda: share_payload(scope, datetime.date.today()))


@method_decorator(gzip_page, name="dispatch")
class ExplorerManifestView(View):
    """``GET /iiif/v3/explorer-manifest?ids=|document=|project=[&canvases=all][&lang=]``: the IIIF v3 manifest of a scope.

    ``lang`` absent is ``LANGUAGE_CODE``; an unknown language or malformed
    scope parameters answer a bodyless 400, a scope with nothing visible the
    bodyless 404, a manifest over ``EXPLORER_MANIFEST_MAX_CANVASES``
    canvases a bodyless 413. The visitor's ETag is the digest of the body:
    the manifest embeds source manifests the data version does not follow.
    """

    def get(self, request):
        try:
            language = export_language(request.GET)
        except ScopeError:
            return HttpResponseBadRequest()
        with translation.override(language):
            try:
                scope = resolve_scope(request.GET, language)
            except ScopeError:
                return HttpResponseBadRequest()
            if scope is None:
                return _not_found()
            try:
                manifest = build_manifest(scope)
            except ManifestTooLarge:
                response = HttpResponse(status=413)
                response["Cache-Control"] = "private, no-store"
                return response
        return _answer(request, lambda: manifest, content_type=IIIF_MEDIA_TYPE)
