"""The decimated series behind the sparkline of a summary popup.

One file per request, kept out of the summary payload: the popup stays small,
the browser caches spectra across popups, and a file that cannot be drawn fails
on its own. A file id names one uploaded file for good — replacing a file
writes a new row — so both the memo and the browser may hold the answer for a
day without any invalidation.

The curve is the one the XY reader draws: the file entry names a renderer
configuration, and that configuration decides the columns and the reference
normalisation the series goes through. It is part of the memo key, so restamping
a file with another preset is another entry rather than a stale drawing.

The guard is the resource the file hangs from, checked before anything is read
from disk.
"""

import hashlib
import logging
import os

import orjson
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseNotModified, JsonResponse
from django.utils.cache import patch_cache_control
from django.views import View

from arches.app.models.models import File
from arches.app.utils.permission_backend import user_can_read_resource

from manuspectrum.models import RendererConfig
from manuspectrum.utils.cache import get_or_build
from manuspectrum.utils.spectrum_preview import build_preview, is_supported

logger = logging.getLogger(__name__)

CACHE_TTL = 86400

# Presets change by migration only, so an hour is short for what it saves.
CONFIG_TTL = 3600

# A lost builder costs one extra read, never a stalled popup.
LOCK_TIMEOUT = 10
LOCK_WAIT = 2.0


def file_record(file_id):
    """Path, owning resource and renderer configuration id of a file.

    ``None`` covers a row that is gone, a row whose file was never stored, and
    a file no tile holds: with no resource there is nothing to check a read
    permission against. ``thumbnail_data`` is deferred — the column holds
    image bytes this route never looks at.
    """
    row = (
        File.objects.filter(pk=file_id)
        .defer("thumbnail_data")
        .select_related("tile")
        .first()
    )
    if row is None or not row.path.name or row.tile is None:
        return None
    return (
        row.path.path,
        str(row.tile.resourceinstance_id),
        stamped_config_id(row.tile.data, file_id),
    )


def stamped_config_id(data, file_id):
    """The renderer configuration id the file entry carries, or ``None``.

    The entry is looked up by file id across the file-list nodes of the tile:
    one tile may hold several of them, and their node ids are not known here.
    """
    wanted = str(file_id).lower()
    for values in (data or {}).values():
        if not isinstance(values, list):
            continue
        for entry in values:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("file_id", "")).lower() == wanted:
                return entry.get("rendererConfig") or None
    return None


def renderer_config(config_id):
    """The stored configuration of a renderer, memoised; ``{}`` when unknown.

    An id naming no row is a stamp left behind by a preset that was removed;
    the file is then drawn on its first two columns rather than not at all.
    """
    if not config_id:
        return {}
    return (
        get_or_build(
            f"spectrum-preview-config:{config_id}",
            lambda: _load_config(config_id),
            CONFIG_TTL,
        )
        or {}
    )


def _load_config(config_id):
    try:
        config = RendererConfig.objects.values_list("config", flat=True).get(
            configid=config_id
        )
    except (RendererConfig.DoesNotExist, ValidationError, ValueError):
        logger.warning("spectrum preview: no renderer configuration %s", config_id)
        return {}
    return config if isinstance(config, dict) else {}


def _series(path, n, config):
    """The series of a supported, small enough file; ``{}`` when there is none.

    An empty dict is memoised: a format outside ``XY_TEXT_FILE_FORMATS`` or a
    file over the ceiling is measured once and answers 204 from the memo
    afterwards. A file that cannot be opened returns ``None`` instead, which
    ``get_or_build`` keeps out of the cache — it may be there on the next
    request.
    """
    if not is_supported(path):
        return {}
    try:
        if os.path.getsize(path) > settings.SPECTRUM_PREVIEW_MAX_BYTES:
            return {}
        return build_preview(path, n, config) or {}
    except OSError:
        return None


def _private(data, status):
    """A refusal that depends on the reader, which no cache may keep."""
    response = JsonResponse(data, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _already_held(request, etag):
    """Whether the client's ``If-None-Match`` names this payload."""
    header = request.headers.get("If-None-Match", "")
    return etag in header or f"W/{etag}" in header


class SpectrumPreviewView(View):
    """``GET /api/spectrum-preview/<file_id>``, at most one file read per day.

    204 means there is nothing to draw — an extension outside
    ``XY_TEXT_FILE_FORMATS``, a file over ``SPECTRUM_PREVIEW_MAX_BYTES``, or
    fewer than two points — and carries the same lifetime as a series, because
    the answer for a given file id cannot change either.
    """

    def get(self, request, file_id):
        record = file_record(file_id)
        if record is None:
            return _private({"error": "not_found"}, 404)
        path, resourceid, config_id = record
        if not user_can_read_resource(request.user, resourceid=resourceid):
            return _private({"error": "forbidden"}, 403)

        n = settings.SPECTRUM_PREVIEW_POINTS
        payload = get_or_build(
            f"spectrum-preview:{file_id}:{n}:{config_id}",
            lambda: _series(path, n, renderer_config(config_id)),
            CACHE_TTL,
            lock_timeout=LOCK_TIMEOUT,
            wait=LOCK_WAIT,
        )
        if not payload:
            return self._with_lifetime(HttpResponse(status=204))

        body = orjson.dumps(payload)
        etag = '"%s"' % hashlib.md5(body, usedforsecurity=False).hexdigest()
        if _already_held(request, etag):
            response = HttpResponseNotModified()
        else:
            response = HttpResponse(body, content_type="application/json")
        response["ETag"] = etag
        return self._with_lifetime(response)

    @staticmethod
    def _with_lifetime(response):
        patch_cache_control(response, private=True, max_age=CACHE_TTL)
        return response
