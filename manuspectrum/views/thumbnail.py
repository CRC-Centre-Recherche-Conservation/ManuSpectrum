"""Search thumbnails, cached at the edge of the request.

Subclass of ``arches.app.views.thumbnail.ThumbnailView`` (Arches 8.0.x): same
resolution and same body, plus the validators a browser needs to stop asking.
Every miss on this route costs the fetchers a IIIF manifest fetch and an image
fetch from a library server, and search results request one per row.

It reaches requests through the route registered in ``urls.py``, not by file
position: unlike a ``media/js`` shadow, deleting this module breaks the import
there rather than falling back to the core view.

The manifest fetch itself is cached in ``CanvasIIIF.fetch_manifest``; this is
the other half — the answer a client already holds is not re-sent, and is not
re-requested at all for ``settings.SEARCH_THUMBNAIL_MAX_AGE``.
"""

import hashlib

from django.conf import settings
from django.http import HttpResponseNotModified
from django.utils.cache import patch_cache_control

from arches.app.views.thumbnail import ThumbnailView


class CachedThumbnailView(ThumbnailView):
    """``ThumbnailView`` with an ETag and a Cache-Control lifetime.

    ``private`` rather than ``public``: nothing restricts a resource today, but
    a shared cache holding thumbnails would have to be purged the day one does
    (decision D1 in the remediation plan), and a per-browser cache already
    absorbs the repeat requests this route was answering.
    """

    def head(self, request, resource_id):
        return self._with_lifetime(super().head(request, resource_id))

    def get(self, request, resource_id):
        response = super().get(request, resource_id)
        if response.status_code != 200:
            return response

        digest = hashlib.md5(response.content, usedforsecurity=False).hexdigest()
        etag = f'"{digest}"'
        if request.headers.get("If-None-Match") == etag:
            response = HttpResponseNotModified()
        response.headers["ETag"] = etag
        return self._with_lifetime(response)

    @staticmethod
    def _with_lifetime(response):
        if response.status_code in (200, 304):
            patch_cache_control(
                response,
                private=True,
                max_age=getattr(settings, "SEARCH_THUMBNAIL_MAX_AGE", 86400),
            )
        return response
