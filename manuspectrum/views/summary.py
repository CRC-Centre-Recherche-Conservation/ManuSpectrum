"""Summary popup endpoints: one resource, and the batch a map load warms.

Both answer the payload of spec §4.2 and share one memo entry per resource,
language and permission scope, so a popup opened from the map and the same
popup reopened from the IIIF viewer are built once. The guard runs before the
memo is read: the entry is keyed by scope, not by reader, and only a
deployment where nothing is restricted keys it publicly.

The ETag is the digest of the payload, which makes a reopened popup a 304 as
long as the memo holds. A payload a shared cache may keep says so; anything
that depends on the reader is marked ``private, no-store``, as in
``iiif_annotation``.
"""

import hashlib
import logging
import uuid

import orjson
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotModified, JsonResponse
from django.utils import translation
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.gzip import gzip_page

from arches.app.utils.permission_backend import user_can_read_resource

from manuspectrum.utils.cache import get_or_build, stable_cache_key
from manuspectrum.views.summary_service import (
    DEGRADED_TTL,
    ResourceNotFound,
    build_summaries,
    build_summary,
    perm_scope,
)

logger = logging.getLogger(__name__)

# A lost builder costs one extra build, never a stalled popup: the lock is
# shorter than the 30 s a sick cluster could hold a worker for.
LOCK_TIMEOUT = 10
LOCK_WAIT = 2.0


def summary_cache_key(resourceid, language, scope):
    """The memo entry of one payload; both views read and write this one."""
    return stable_cache_key("summary", resourceid, language, scope)


def shorten_degraded(payload, key):
    """Expire a degraded payload in seconds: it states a symptom, not a fact."""
    if payload.get("degraded"):
        cache.set(key, payload, DEGRADED_TTL)


def _private(data, status=200):
    """An answer that depends on the reader, which no shared cache may keep."""
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _already_held(request, etag):
    """Whether the client's ``If-None-Match`` names this payload."""
    header = request.headers.get("If-None-Match", "")
    return etag in header or f"W/{etag}" in header


@method_decorator(gzip_page, name="dispatch")
class SummaryView(View):
    """The summary of one resource, for the map popup and the IIIF viewer."""

    def get(self, request, resourceid):
        if not user_can_read_resource(request.user, resourceid=resourceid):
            return _private({"error": "forbidden"}, 403)
        language = translation.get_language() or settings.LANGUAGE_CODE
        scope = perm_scope(request.user)
        key = summary_cache_key(resourceid, language, scope)
        try:
            payload = get_or_build(
                key,
                lambda: build_summary(resourceid, language, request.user),
                settings.SUMMARY_CACHE_TTL,
                lock_timeout=LOCK_TIMEOUT,
                wait=LOCK_WAIT,
            )
        except ResourceNotFound:
            return _private({"error": "not_found"}, 404)
        if payload is None:
            logger.error("summary: nothing built for %s", resourceid)
            return _private({"error": "unavailable"}, 503)
        shorten_degraded(payload, key)
        body = orjson.dumps(payload)
        etag = '"%s"' % hashlib.md5(body, usedforsecurity=False).hexdigest()
        if _already_held(request, etag):
            response = HttpResponseNotModified()
        else:
            response = HttpResponse(body, content_type="application/json")
        response["ETag"] = etag
        # No Vary: the language is in the path (the route sits inside
        # i18n_patterns) and a reader-dependent payload is never shared.
        response["Cache-Control"] = (
            f"public, max-age={settings.SUMMARY_CACHE_TTL}"
            if scope == "public"
            else "private, no-store"
        )
        return response


@method_decorator(gzip_page, name="dispatch")
class SummaryBatchView(View):
    """The summaries of the features a map load shows, warmed in one request.

    The answer is never cached by a proxy: it mixes as many resources as the
    map holds, each with its own guard. The payloads themselves are memoised
    one by one, under the keys the single endpoint reads, so a click that
    follows the warm-up costs nothing.
    """

    def get(self, request):
        asked = [
            part.strip()
            for part in request.GET.get("ids", "").split(",")
            if part.strip()
        ]
        if len(asked) > settings.SUMMARY_MAX_IDS:
            return _private({"error": "too_many_ids"}, 400)
        language = translation.get_language() or settings.LANGUAGE_CODE
        scope = perm_scope(request.user)
        summaries, missing = {}, []
        for resourceid in _well_formed(asked):
            if not user_can_read_resource(request.user, resourceid=resourceid):
                continue
            held = cache.get(summary_cache_key(resourceid, language, scope))
            if held is None:
                missing.append(resourceid)
            else:
                summaries[resourceid] = held
        built = build_summaries(missing, language, request.user)
        for resourceid, payload in built.items():
            key = summary_cache_key(resourceid, language, scope)
            cache.set(key, payload, settings.SUMMARY_CACHE_TTL)
            shorten_degraded(payload, key)
            summaries[resourceid] = payload
        return _private({"summaries": summaries})


def _well_formed(values):
    """The ids that are uuids, once each, in the order asked.

    A malformed id is dropped rather than refused: the map sends the features
    it holds, and one bad one must not cost the others their popup.
    """
    ids = []
    for value in values:
        try:
            uuid.UUID(value)
        except (AttributeError, TypeError, ValueError):
            continue
        if value not in ids:
            ids.append(value)
    return ids
