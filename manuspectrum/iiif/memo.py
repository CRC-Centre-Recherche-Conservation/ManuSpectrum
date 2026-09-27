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
is answered from it, not rebuilt. Any other reader, and any reader identified by a IIIF
token, gets a document built for them, ``private, no-store``, never stored.

The caller runs its read guard before ``answer``: no memo is read for a
reader refused the resource.
"""

import hashlib
from dataclasses import dataclass

import orjson
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotModified

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


class Absent(Exception):
    """The document asked for does not exist for this reader."""


@dataclass(frozen=True)
class Gate:
    """Whether the reader's view is the visitor's, and the key parts naming that view."""

    shared: bool
    parts: tuple


def gate(reader, token=False):
    """The ``Gate`` of *reader*: data version, permission epoch, the visitor's visible digest,
    the translations' ``locale_stamp`` and ``CACHE_CODE_VERSION``.

    A reader identified by a IIIF token (*token*) never shares the visitor's view.
    """
    version = data_version()
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


def answer(request, reader_gate, kind, parts, build, *, content_type):
    """The response of a memoised IIIF document; *build* returns its JSON-able dict.

    ``Absent`` raised by *build*, or read from its marker, propagates; any
    other exception propagates and nothing is stored.
    """
    if not reader_gate.shared or renews_csrf_cookie(request):
        return _response(orjson.dumps(build()), content_type, PRIVATE)
    key = stable_cache_key("iiif", kind, *parts, *reader_gate.parts)
    etag = '"' + hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest() + '"'
    any_tag = request.headers.get("If-None-Match", "").strip() == "*"
    if not any_tag and etag_already_held(request, etag):
        return _not_modified(etag)

    def stored():
        try:
            return orjson.dumps(build())
        except Absent:
            return ABSENT

    def expire_absent(value):
        if value == ABSENT:
            cache.set(key, value, settings.IIIF_ABSENT_TTL)

    body = get_or_build(key, stored, settings.IIIF_MEMO_TTL, kept=expire_absent)
    if body == ABSENT:
        raise Absent()
    if any_tag:
        return _not_modified(etag)
    return _response(body, content_type, PUBLIC, etag)


def _not_modified(etag):
    response = HttpResponseNotModified()
    response["ETag"] = etag
    response["Cache-Control"] = PUBLIC
    return response
