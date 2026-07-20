"""Public, cached JSON endpoint serving the graph-explorer payload.

The DB introspection (build_model_graph) is memoized by a publication
fingerprint so it is not re-run on every request. When any resource graph
is republished, the fingerprint changes and the cache is bypassed
automatically. A 24h TTL is only a backstop in case the fingerprint never
changes but the cache backend still needs an eviction horizon.
"""

import hashlib
import logging

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import translation
from django.utils.cache import patch_vary_headers
from django.views import View

from manuspectrum.views.model_graph_service import build_model_graph

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 60 * 24  # 24h backstop; fingerprint busts earlier on republish.


def graph_fingerprint():
    """Cheap fingerprint of all resource graphs' (id, publication). Changes on republish."""
    from arches.app.models.models import GraphModel

    rows = GraphModel.objects.filter(isresource=True).values_list(
        "graphid", "publication_id"
    )
    payload = ";".join(sorted(f"{g}:{p}" for g, p in rows))
    return hashlib.md5(
        payload.encode("utf-8")
    ).hexdigest()  # noqa: S324 (non-security fingerprint)


class ModelGraphView(View):
    """Public, cached JSON introspection of the resource models for the Graph Explorer."""

    def get(self, request, *args, **kwargs):
        language = translation.get_language() or "en"
        try:
            fingerprint = graph_fingerprint()
            cache_key = f"ms:model-graph:{language}:{fingerprint}"
            payload = cache.get(cache_key)
            if payload is None:
                payload = build_model_graph(language)
                cache.set(cache_key, payload, CACHE_TTL)
            resp = JsonResponse(payload)
            resp["Cache-Control"] = "public, max-age=3600"
            resp["ETag"] = f'"{fingerprint}"'
            # The payload is language-dependent and the active language can be
            # selected by the django_language cookie (LocaleMiddleware only adds
            # Vary: Accept-Language). Without Vary: Cookie a shared proxy/CDN
            # could serve an "fr" payload to an "en" visitor.
            patch_vary_headers(resp, ("Cookie",))
            return resp
        except (
            Exception
        ):  # noqa: BLE001 — never 500 blank; return JSON error, frontend falls back
            logger.exception("model-graph introspection failed")
            return JsonResponse({"error": "introspection_failed"}, status=500)
