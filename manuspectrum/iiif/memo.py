"""The memo and the HTTP answer of the memoised IIIF documents (pages, collections, annotations).

A document is stored under ``stable_cache_key("iiif", kind, *parts,
data_version, permission_epoch, visitor digest, locale stamp, code
version)``, language-free, and only
when the reader's ``visible_set`` digest equals the visitor's (same visible
resources, hidden resources, readable nodegroups and models) and the
response renews no CSRF cookie. That answer is ``public, no-cache`` with a
strong ETag derived from the key, and an ``If-None-Match`` naming it gets a
304 before anything is built; ``If-None-Match: *`` gets a 304 only once the
document is known to exist (RFC 9110 §13.1.2). A build raising ``Absent``
stores a marker for ``IIIF_ABSENT_TTL`` seconds: the same missing document
is answered from it, not rebuilt. A build that read a degraded source
(``mark_degraded``: a source manifest named but unreadable) is stored, body
or marker, for ``IIIF_DEGRADED_TTL`` seconds only, and its answer carries no
ETag. Any other reader, and any reader identified by a IIIF token, gets a
document built for them, ``private, no-store``, never stored.
A derived document (``answer_derived``, a filtered page) is computed from
its source's entry and never stored itself.

The caller runs its read guard before ``answer``: no memo is read for a
reader refused the resource.
"""

import contextvars
import hashlib
from dataclasses import dataclass

import orjson
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotModified

from manuspectrum.observability import metrics
from manuspectrum.utils.cache import (
    etag_already_held,
    get_or_build,
    renews_csrf_cookie,
    stable_cache_key,
)
from manuspectrum.utils.data_version import data_version
from manuspectrum.utils.public_visibility import (
    anonymous_user,
    permission_epoch,
    visible_set,
)
from manuspectrum.utils.stamps import locale_stamp

PUBLIC = "public, no-cache"
PRIVATE = "private, no-store"
ABSENT = b""
DEGRADED = b"\x00"


class Absent(Exception):
    """The document asked for does not exist for this reader."""


_degraded = contextvars.ContextVar("iiif_memo_degraded", default=None)


def mark_degraded():
    """Note that the document being built read a source it could not read; outside a memo build, nothing."""
    marks = _degraded.get()
    if marks is not None:
        marks.append(True)


@dataclass(frozen=True)
class Gate:
    """Whether the reader's view is the visitor's, and the key parts naming that view."""

    shared: bool
    parts: tuple


def gate(reader, token=False, version=None):
    """The ``Gate`` of *reader*: data version, permission epoch, the visitor's visible digest,
    the translations' ``locale_stamp`` and ``CACHE_CODE_VERSION``.

    *version* is the ``data_version()`` the request read for its guard, else
    read here. A reader identified by a IIIF token (*token*) never shares the
    visitor's view.
    """
    version = data_version() if version is None else version
    visitor = visible_set(anonymous_user(), version)
    mine = visible_set(reader, version)
    return Gate(
        shared=not token and mine.digest == visitor.digest,
        parts=(
            version,
            permission_epoch(),
            visitor.digest,
            locale_stamp(),
            settings.CACHE_CODE_VERSION,
        ),
    )


def _response(body, content_type, cache_control, etag=None):
    response = HttpResponse(body, content_type=content_type)
    response["Cache-Control"] = cache_control
    if etag:
        response["ETag"] = etag
    return response


def _key(kind, parts, reader_gate):
    return stable_cache_key("iiif", kind, *parts, *reader_gate.parts)


def _etag(text):
    return '"' + hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest() + '"'


def _stored(key, build):
    """``(body, degraded)`` stored under *key*, built by *build* on a miss; ``Absent`` when the document does not exist."""

    marks = []

    def stored():
        token = _degraded.set(marks)
        try:
            body = orjson.dumps(build())
        except Absent:
            return ABSENT
        finally:
            _degraded.reset(token)
        return DEGRADED + body if marks else body

    def expire_early(value):
        if marks:
            cache.set(key, value, settings.IIIF_DEGRADED_TTL)
        elif value == ABSENT:
            cache.set(key, value, settings.IIIF_ABSENT_TTL)

    body = get_or_build(
        key,
        stored,
        settings.IIIF_MEMO_TTL,
        wait=settings.IIIF_BUILD_WAIT,
        kept=expire_early,
    )
    if body == ABSENT:
        raise Absent()
    if body.startswith(DEGRADED):
        return body[len(DEGRADED) :], True
    return body, False


def _shares(request, reader_gate):
    return reader_gate.shared and not renews_csrf_cookie(request)


def answer(request, reader_gate, kind, parts, build, *, content_type):
    """The response of a memoised IIIF document; *build* returns its JSON-able dict.

    ``Absent`` raised by *build*, or read from its marker, propagates; any
    other exception propagates and nothing is stored.
    """
    if not _shares(request, reader_gate):
        metrics.IIIF_ANSWERS.labels(mode="private").inc()
        return _response(orjson.dumps(build()), content_type, PRIVATE)
    key = _key(kind, parts, reader_gate)
    etag = _etag(key)
    any_tag = request.headers.get("If-None-Match", "").strip() == "*"
    if not any_tag and etag_already_held(request, etag):
        return _not_modified(etag)
    body, degraded = _stored(key, build)
    if any_tag:
        return _not_modified(etag)
    metrics.IIIF_ANSWERS.labels(mode="shared").inc()
    return _response(body, content_type, PUBLIC, None if degraded else etag)


def answer_derived(request, reader_gate, kind, parts, build, derive, *, content_type):
    """The response of a document derived from the memoised document *kind*, *parts* (built by *build*).

    *derive* takes the source document's dict and returns ``(document,
    variant)``, *variant* a string naming what the derivation kept, or raises
    ``Absent``. The source is read, or built and stored, as ``answer`` does;
    nothing is stored for the derived document. Its ETag is the sha1 of the
    source's key and *variant*; a private reader's source is built for them
    and never stored.
    """
    if not _shares(request, reader_gate):
        document, _ = derive(build())
        metrics.IIIF_ANSWERS.labels(mode="private").inc()
        return _response(orjson.dumps(document), content_type, PRIVATE)
    key = _key(kind, parts, reader_gate)
    source, degraded = _stored(key, build)
    document, variant = derive(orjson.loads(source))
    etag = None if degraded else _etag(f"{key}\n{variant}")
    if etag and etag_already_held(request, etag):
        return _not_modified(etag)
    metrics.IIIF_ANSWERS.labels(mode="shared").inc()
    return _response(orjson.dumps(document), content_type, PUBLIC, etag)


def _not_modified(etag):
    metrics.IIIF_ANSWERS.labels(mode="not_modified").inc()
    response = HttpResponseNotModified()
    response["ETag"] = etag
    response["Cache-Control"] = PUBLIC
    return response
