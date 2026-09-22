"""Vector tiles of the geometry nodes, with an empty tile a browser may keep.

Subclass of ``arches.app.views.api.geo.MVT`` (Arches 8.1.5, geo.py:196-204).
``get`` is rewritten rather than wrapped: the core view raises the same
``Http404`` for a node the reader cannot see and for a tile with no feature,
and only the second is an answer worth keeping. The tile is still built by
Arches' ``MVTTiler``, with its per-reader server cache.
"""

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotFound

from arches.app.utils.mvt_tiler import MVTTiler
from arches.app.views.api.geo import MVT

from manuspectrum.utils.cache import renews_csrf_cookie
from manuspectrum.views.summary_service import perm_scope

# A zoom deeper than any map requests, whose tile indices fit the int4
# arguments of TileBBox.
MAX_ZOOM = 30


def tile_coordinates(zoom, x, y):
    """``(zoom, x, y)`` as integers when they name a tile, else ``None``.

    Each part is ASCII digits with at most ten significant ones, checked
    before ``int()`` sees it. The route also admits the literal ``{z}``,
    ``{x}`` and ``{y}`` of the URL template Arches reverses for the map.
    """
    parts = (zoom, x, y)
    if not all(
        part.isascii() and part.isdigit() and len(part.lstrip("0")) <= 10
        for part in parts
    ):
        return None
    zoom, x, y = map(int, parts)
    if zoom > MAX_ZOOM or x >= 2**zoom or y >= 2**zoom:
        return None
    return zoom, x, y


class EmptyTileMVTView(MVT):
    """``MVT`` answering 204 for a tile with no feature.

    ``MVTTiler.createTile`` returns ``None`` for an unknown node or one outside
    the reader's viewable nodegroups: a bodyless 404 with no lifetime. An empty
    tile comes back as ``""`` up to the clustering zoom and as ``b""`` beyond
    it: a 204, ``public, max-age=MVT_EMPTY_TILE_MAX_AGE`` while ``perm_scope``
    finds nothing restricted, ``private, no-store`` within ``PERM_SCOPE_TTL``
    (a minute) of the first restriction, since one reader's empty tile then
    says nothing of another's. It is ``private, no-store`` too while the CSRF
    middleware renews the reader's cookie: a public answer never carries a
    ``Set-Cookie``. A tile with features is served as Arches serves it; what
    the tiler raises propagates.
    """

    def get(self, request, nodeid, zoom, x, y):
        coordinates = tile_coordinates(zoom, x, y)
        if coordinates is None:
            return HttpResponseNotFound()
        tile = MVTTiler().createTile(
            nodeid,
            request.user.userprofile.viewable_nodegroups,
            request.user,
            *coordinates,
        )
        if tile is None:
            return HttpResponseNotFound()
        if tile:
            return HttpResponse(tile, content_type="application/x-protobuf")
        response = HttpResponse(status=204)
        response["Cache-Control"] = (
            f"public, max-age={settings.MVT_EMPTY_TILE_MAX_AGE}"
            if perm_scope(request.user) == "public" and not renews_csrf_cookie(request)
            else "private, no-store"
        )
        return response
