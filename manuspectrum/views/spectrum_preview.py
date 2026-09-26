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

The resource a file hangs from never changes, so its row is memoised under the
file id for as long as a summary payload lives (``SUMMARY_CACHE_TTL``). Two
gates are still checked on every request, before anything is read from disk or
from the series memo: whether the resource is in the reader's ``visible_set``,
then whether the nodegroup of the tile holding the file is one
``readable_nodegroups`` lets through — the rule the summary popup filters its
fields with. Either refusal answers the same bodyless 404 as an unknown file.
The renderer configuration id and the nodegroup id travel in the memo with the
join, and the configuration id keeps keying the series memo: a file restamped
with another preset is drawn with it once the join entry expires, within the
same lifetime a summary payload has for an edited resource. Deleting the file
row drops its entry on commit (``signals.py``). A request that read the row
while the delete was committing can put the entry back, for at most
``SUMMARY_CACHE_TTL``; during that time the guard still runs, but Arches
permits reading a resource that no longer exists.

``None`` (no row, no stored file, no tile) is not memoised, and no caller waits
on the join's lock: an unknown id costs one query per request, never a 2 s
poll for a value that will never be stored, and a file created later is found
at once. The primary-key read costs less than the stampede protection it would
buy.
"""

import hashlib
import logging
import os

import orjson
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotFound,
    HttpResponseNotModified,
)
from django.utils.cache import patch_cache_control
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.gzip import gzip_page

from arches.app.models.models import File

from manuspectrum.models import RendererConfig
from manuspectrum.utils.cache import etag_already_held, get_or_build
from manuspectrum.utils.public_visibility import visible_set
from manuspectrum.utils.spectrum_preview import build_preview, is_supported
from manuspectrum.views.summary_service import readable_nodegroups

logger = logging.getLogger(__name__)

CACHE_TTL = 86400

# Presets change by migration only, so an hour is short for what it saves.
CONFIG_TTL = 3600

# A lost builder costs one extra read, never a stalled popup.
LOCK_TIMEOUT = 10
LOCK_WAIT = 2.0


def file_record_key(file_id):
    return f"spectrum-preview-file:{str(file_id).lower()}"


def file_record(file_id):
    """``(path, resourceid, config_id, nodegroup_id)`` of a file, memoised.

    ``config_id`` is the renderer configuration the file entry carries, and
    ``nodegroup_id`` the nodegroup of the tile holding the file, as a string.

    ``None`` covers a row that is gone, a row whose file was never stored, and
    a file no tile holds: with no resource there is nothing to check a read
    permission against. Memoised under the file id for ``SUMMARY_CACHE_TTL``;
    ``None`` is never kept, and a miss never waits on another caller's build.
    """
    return get_or_build(
        file_record_key(file_id),
        lambda: _load_file_record(file_id),
        settings.SUMMARY_CACHE_TTL,
        lock_timeout=LOCK_TIMEOUT,
        wait=0,
    )


def _load_file_record(file_id):
    """The one database read behind ``file_record``.

    ``thumbnail_data`` is deferred — the column holds image bytes this route
    never looks at.
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
        str(row.tile.nodegroup_id),
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


def _not_found():
    """The answer for an unknown file and for one the reader may not see alike."""
    response = HttpResponseNotFound()
    response["Cache-Control"] = "private, no-store"
    return response


@method_decorator(gzip_page, name="dispatch")
class SpectrumPreviewView(View):
    """``GET /api/spectrum-preview/<file_id>``, at most one file read per day.

    204 means there is nothing to draw — an extension outside
    ``XY_TEXT_FILE_FORMATS``, a file over ``SPECTRUM_PREVIEW_MAX_BYTES``, or
    fewer than two points — and carries the same lifetime as a series, because
    the answer for a given file id cannot change either.
    """

    def get(self, request, file_id):
        """Serve the series of one file to a reader who may see its analysis.

        ``n`` picks a point budget among ``SPECTRUM_PREVIEW_TIERS`` (default the
        first). A file whose resource is outside ``visible_set`` (embargo,
        hidden chain or Project) or whose nodegroup is unreadable
        answers the same bodyless 404 as an unknown file.
        """
        raw_n = request.GET.get("n")
        tiers = settings.SPECTRUM_PREVIEW_TIERS
        try:
            n = int(raw_n) if raw_n is not None else tiers[0]
        except ValueError:
            return HttpResponseBadRequest()
        if n not in tiers:
            return HttpResponseBadRequest()
        record = file_record(file_id)
        if record is None:
            return _not_found()
        path, resourceid, config_id, nodegroup_id = record
        if resourceid not in visible_set(request.user).ids:
            return _not_found()
        nodegroups = readable_nodegroups(request.user)
        if nodegroups is not None and nodegroup_id not in nodegroups:
            return _not_found()

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
        if etag_already_held(request, etag):
            response = HttpResponseNotModified()
        else:
            response = HttpResponse(body, content_type="application/json")
        response["ETag"] = etag
        return self._with_lifetime(response)

    @staticmethod
    def _with_lifetime(response):
        patch_cache_control(response, private=True, max_age=CACHE_TTL)
        return response
