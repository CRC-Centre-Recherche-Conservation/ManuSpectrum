"""Public, cached JSON endpoint serving the graph-explorer payload.

The DB introspection (build_model_graph) is memoized by a content
fingerprint so it is not re-run on every request. The fingerprint moves when
a resource graph is republished, when a card or widget is edited in place
(designer, ``i18n loadmessages``: the widget labels the payload reads), and when resources or concepts are added
or removed. The cache key prefix carries the code version of the serializer
(``settings.CACHE_CODE_VERSION``), so a deploy that changes the payload shape
starts cold. A 24h TTL is only a backstop in case the fingerprint never
changes but the cache backend still needs an eviction horizon. Only the
latest entry per language is kept; a miss is built by one worker while other
callers wait briefly for it.
"""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponseNotModified, JsonResponse
from django.utils import translation
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.gzip import gzip_page

from manuspectrum.utils.cache import get_or_build
from manuspectrum.views.model_graph_service import build_model_graph

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 60 * 24  # 24h backstop; fingerprint busts earlier on republish.

_CARDS_HASH_SQL = """
    SELECT md5(string_agg(
        w.id::text || ':' || coalesce(w.label::text, ''),
        '' ORDER BY w.id))
    FROM cards_x_nodes_x_widgets w
"""


def _cards_hash():
    """md5 of every widget label, in one query over the whole table.

    The payload reads one card/widget text: the widget label
    (``build_model_graph`` falls back to it for the node name). The designer
    and ``i18n loadmessages`` rewrite it in place, without a republication.
    Cost grows with the total widget count, not per graph.
    """
    with connection.cursor() as cursor:
        cursor.execute(_CARDS_HASH_SQL)
        return cursor.fetchone()[0] or ""


def graph_fingerprint():
    """Content fingerprint: publications, card/widget texts, record counts.

    Moves on republish, on any in-place widget label edit, and on any
    resource or concept add/delete, which keeps the "live figures" (records,
    concepts, thesauri) honest without a rebuild on every request. Four cheap
    queries (1 values_list, 1 md5 aggregate, 2 COUNTs).
    """
    from arches.app.models.models import Concept, GraphModel, ResourceInstance

    rows = GraphModel.objects.filter(isresource=True).values_list(
        "graphid", "publication_id"
    )
    payload = ";".join(sorted(f"{g}:{p}" for g, p in rows))
    payload += f"|labels:{_cards_hash()}"
    payload += f"|ri:{ResourceInstance.objects.count()}"
    payload += f"|c:{Concept.objects.count()}"
    return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


def _retire_previous_entry(language, cache_key):
    """Keep one live payload per language.

    The fingerprint moves on every record or concept change; a pointer key
    names the current entry and the one it replaces is deleted.
    """
    pointer = f"model-graph:{language}:current"
    previous = cache.get(pointer)
    if previous != cache_key:
        if previous:
            cache.delete(previous)
        cache.set(pointer, cache_key, CACHE_TTL)


@method_decorator(gzip_page, name="dispatch")
class ModelGraphView(View):
    """Public, cached JSON introspection of the resource models for the Graph Explorer."""

    def get(self, request, *args, **kwargs):
        language = translation.get_language() or "en"
        try:
            fingerprint = graph_fingerprint()
            # Language and code version belong in the ETag: the payload differs
            # per language, and a deploy that changes its shape must not 304 a
            # client that cached the previous one.
            etag = f'"{fingerprint}:{language}:{settings.CACHE_CODE_VERSION}"'
            if_none_match = request.headers.get("If-None-Match", "")
            if etag in if_none_match or f"W/{etag}" in if_none_match:
                resp = HttpResponseNotModified()
                resp["ETag"] = etag
                return resp

            cache_key = f"model-graph:{language}:{fingerprint}"
            payload = get_or_build(
                cache_key, lambda: build_model_graph(language), CACHE_TTL
            )
            if payload is not None:
                _retire_previous_entry(language, cache_key)
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
