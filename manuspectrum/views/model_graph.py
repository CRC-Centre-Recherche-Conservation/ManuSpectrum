"""Public, cached JSON endpoint serving the graph-explorer payload.

The DB introspection (build_model_graph) is memoized by a publication
fingerprint so it is not re-run on every request. When any resource graph
is republished — or when resources/concepts are added or removed — the
fingerprint changes and the cache is bypassed automatically. A 24h TTL is
only a backstop in case the fingerprint never changes but the cache backend
still needs an eviction horizon.
"""

import hashlib
import logging

from django.core.cache import cache
from django.http import HttpResponseNotModified, JsonResponse
from django.utils import translation
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.gzip import gzip_page

from manuspectrum.views.model_graph_service import build_model_graph

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 60 * 24  # 24h backstop; fingerprint busts earlier on republish.

# Bump this whenever build_model_graph() changes the payload's shape or
# content: the version is part of the cache key, so a deploy immediately
# stops serving payloads built by the previous code — no manual redis flush,
# and no window where freshly deployed JS reads fields the cached payload
# doesn't have.
# v3: French graph content loaded via `i18n loadmessages` — an in-place graph
# edit the publication fingerprint cannot see.
PAYLOAD_VERSION = 3

# The fingerprint tracks (graphid, publication) plus the resource and concept
# table sizes, so it moves on republish AND when records/concepts are added or
# removed. The one blind spot left: correcting graph data in place without
# republishing (e.g. renaming a graph directly in the database) — flush by
# hand in that case, or just bump PAYLOAD_VERSION.


def graph_fingerprint():
    """Cheap fingerprint: graphs' (id, publication) + resource/concept counts.

    Changes on republish and on any resource or concept add/delete, which keeps
    the "live figures" (records, concepts, thesauri) honest without a rebuild
    on every request. Three cheap queries (2 COUNTs + 1 values_list).
    """
    from arches.app.models.models import Concept, GraphModel, ResourceInstance

    rows = GraphModel.objects.filter(isresource=True).values_list(
        "graphid", "publication_id"
    )
    payload = ";".join(sorted(f"{g}:{p}" for g, p in rows))
    payload += f"|ri:{ResourceInstance.objects.count()}"
    payload += f"|c:{Concept.objects.count()}"
    return hashlib.md5(
        payload.encode("utf-8")
    ).hexdigest()  # noqa: S324 (non-security fingerprint)


@method_decorator(gzip_page, name="dispatch")
class ModelGraphView(View):
    """Public, cached JSON introspection of the resource models for the Graph Explorer."""

    def get(self, request, *args, **kwargs):
        language = translation.get_language() or "en"
        try:
            fingerprint = graph_fingerprint()
            # Language and version belong in the ETag: the payload differs per
            # language, and a deploy that bumps PAYLOAD_VERSION must not 304
            # a client that cached the previous shape.
            etag = f'"{fingerprint}:{language}:v{PAYLOAD_VERSION}"'
            if_none_match = request.headers.get("If-None-Match", "")
            if etag in if_none_match or f"W/{etag}" in if_none_match:
                resp = HttpResponseNotModified()
                resp["ETag"] = etag
                return resp

            cache_key = f"ms:model-graph:v{PAYLOAD_VERSION}:{language}:{fingerprint}"
            payload = cache.get(cache_key)
            if payload is None:
                payload = build_model_graph(language)
                cache.set(cache_key, payload, CACHE_TTL)
            resp = JsonResponse(payload)
            resp["Cache-Control"] = "public, max-age=3600"
            resp["ETag"] = etag
            # No Vary: Cookie — since the route sits inside i18n_patterns the
            # language is carried by the URL itself (/api/… vs /fr/api/…), so
            # shared caches can key on the path alone.
            return resp
        except (
            Exception
        ):  # noqa: BLE001 — never 500 blank; return JSON error, frontend falls back
            logger.exception("model-graph introspection failed")
            return JsonResponse({"error": "introspection_failed"}, status=500)
