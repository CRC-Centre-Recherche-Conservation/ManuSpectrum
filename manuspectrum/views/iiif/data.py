"""``/iiif/data/<file>/raw`` (the stored file) and ``/iiif/data/<file>/series.csv`` (its clean CSV).

The reader is ``iiif.tokens.iiif_reader`` (session, else Bearer IIIF token);
the guard is ``iiif.data.readable_file``. An unknown file is a bodyless 404;
a file the reader may not read is a 401 to the visitor (the requested URL
described as a ``Dataset`` with the Auth 1.0 and 2.0 services) and a bodyless
403 to a signed-in or token reader; a Bearer credential that is not a valid
IIIF token is a 401. A reader whose view is the visitor's (never a token
reader) gets ``public,
no-cache`` and a strong ETag (the file id, size and modification time; for the
clean CSV also the renderer configuration and the code version) that an
``If-None-Match`` answers with a 304; any other reader ``private, no-store``.
Nothing is memoised. Every answer carries ``nosniff`` and the IIIF CORS
headers.

``raw`` streams the file as an attachment with its true media type and a name
stripped of path separators and control characters. ``series.csv`` is a 404
when the file has no clean CSV (``clean_series_available``) or holds fewer
than two points.
"""

import hashlib
import logging
import os
import re

import orjson
from django.conf import settings
from django.http import (
    FileResponse,
    HttpResponse,
    HttpResponseNotModified,
    StreamingHttpResponse,
)
from django.utils.decorators import method_decorator
from django.views import View

from manuspectrum.iiif import data, memo, tokens, xy_reading
from manuspectrum.utils.cache import etag_already_held, renews_csrf_cookie
from manuspectrum.utils.data_version import data_version
from manuspectrum.utils.public_visibility import request_memo
from manuspectrum.views.iiif.annotations import (
    gate_of,
    not_found,
    reader_of,
    refused,
    unauthorized,
)
from manuspectrum.views.iiif.cors import iiif_cors
from manuspectrum.views.spectrum_preview import renderer_config

logger = logging.getLogger(__name__)

CSV_MEDIA_TYPE = "text/csv; charset=utf-8; header=present"
_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]+")


def safe_name(name):
    """*name* without path separators or control characters; ``file`` when nothing is left."""
    cleaned = _UNSAFE_NAME.sub("_", str(name or "")).strip(" .")
    return cleaned or "file"


def _nosniff(response):
    response["X-Content-Type-Options"] = "nosniff"
    return response


def _etag(*parts):
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(orjson.dumps([str(p) for p in parts]))
    return f'"{digest.hexdigest()}"'


@method_decorator(iiif_cors, name="dispatch")
class DataView(View):
    """GET, HEAD and OPTIONS of one stored file's representation."""

    http_method_names = ["get", "head", "options"]

    def get(self, request, file_id):
        try:
            with request_memo(getattr(request, "user", None)):
                return _nosniff(self.answer(request, file_id))
        except Exception:
            logger.exception("IIIF data failed: %s", request.path)
            response = HttpResponse(status=500)
            response["Cache-Control"] = memo.PRIVATE
            return _nosniff(response)

    def answer(self, request, file_id):
        if tokens.bearer_state(request) == tokens.INVALID:
            return unauthorized(request, "Dataset", file_id)
        version = data_version()
        try:
            record = data.readable_file(file_id, reader_of(request), version)
        except data.Refused:
            return refused(request, "Dataset", file_id)
        if record is None:
            return not_found()
        try:
            stat = os.stat(record.path)
        except OSError:
            return not_found()
        prepared = self.prepare(record)
        if prepared is None:
            return not_found()
        shared = gate_of(request, version).shared and not renews_csrf_cookie(request)
        etag = _etag(record.id, stat.st_size, stat.st_mtime_ns, *self.version(prepared))
        if shared and etag_already_held(request, etag):
            response = HttpResponseNotModified()
        else:
            response = self.respond(record, prepared)
            if response is None:
                return not_found()
        response["Cache-Control"] = memo.PUBLIC if shared else memo.PRIVATE
        if shared:
            response["ETag"] = etag
        return response

    def prepare(self, record):
        """What ``respond`` needs; None when this representation does not exist."""
        return ()

    def version(self, prepared):
        """What, besides the stored file, names the bytes of this representation."""
        return ()

    def respond(self, record, prepared):
        raise NotImplementedError


class RawDataView(DataView):
    """The stored file as an attachment, with its true media type."""

    def respond(self, record, prepared):
        return FileResponse(
            open(record.path, "rb"),
            content_type=record.media_type,
            as_attachment=True,
            filename=safe_name(record.name),
        )


class SeriesDataView(DataView):
    """The clean CSV of a file (``xy_reading.csv_lines``)."""

    def prepare(self, record):
        if not data.clean_series_available(record):
            return None
        return record.config_id, renderer_config(record.config_id)

    def version(self, prepared):
        config_id, config = prepared
        return (
            config_id or "",
            hashlib.sha1(
                orjson.dumps(config, option=orjson.OPT_SORT_KEYS),
                usedforsecurity=False,
            ).hexdigest(),
            settings.CACHE_CODE_VERSION,
        )

    def respond(self, record, prepared):
        _, config = prepared
        lines = xy_reading.csv_lines(record, config)
        if lines is None:
            return None
        return StreamingHttpResponse(lines, content_type=CSV_MEDIA_TYPE)
