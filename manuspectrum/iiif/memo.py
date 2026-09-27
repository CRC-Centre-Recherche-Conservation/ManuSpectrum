"""The memo and the HTTP answer of the memoised IIIF documents (pages, collections, annotations).

A document is stored under ``stable_cache_key("iiif", kind, *parts,
data_version, permission_epoch, visitor digest)``, language-free, and only
when the reader's ``visible_set`` digest equals the visitor's (same visible
resources, hidden resources, readable nodegroups and models) and the
response renews no CSRF cookie. That answer is ``public, no-cache`` with a
strong ETag derived from the key, and an ``If-None-Match`` naming it gets a
304 before anything is built. Any other reader, and any reader identified by a IIIF
token, gets a document built for them, ``private, no-store``, never stored.

The caller runs its read guard before ``answer``: no memo is read for a
reader refused the resource.
"""

import hashlib
from dataclasses import dataclass

import orjson
from django.conf import settings
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

PUBLIC = "public, no-cache"
PRIVATE = "private, no-store"


@dataclass(frozen=True)
class Gate:
    """Whether the reader's view is the visitor's, and the key parts naming that view."""

    shared: bool
    parts: tuple


def gate(reader, token=False):
    """The ``Gate`` of *reader*: data version, permission epoch and the visitor's visible digest.

    A reader identified by a IIIF token (*token*) never shares the visitor's view.
    """
    version = data_version()
    visitor = visible_set(anonymous_user(), version)
    mine = visible_set(reader, version)
    return Gate(
        shared=not token and mine.digest == visitor.digest,
        parts=(version, permission_epoch(), visitor.digest),
    )


def _response(body, content_type, cache_control, etag=None):
    response = HttpResponse(body, content_type=content_type)
    response["Cache-Control"] = cache_control
    if etag:
        response["ETag"] = etag
    return response


def answer(request, reader_gate, kind, parts, build, *, content_type):
    """The response of a memoised IIIF document; *build* returns its JSON-able dict.

    An exception raised by *build* propagates and nothing is stored.
    """
    if not reader_gate.shared or renews_csrf_cookie(request):
        return _response(orjson.dumps(build()), content_type, PRIVATE)
    key = stable_cache_key("iiif", kind, *parts, *reader_gate.parts)
    etag = '"' + hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest() + '"'
    if etag_already_held(request, etag):
        response = HttpResponseNotModified()
        response["ETag"] = etag
        response["Cache-Control"] = PUBLIC
        return response
    body = get_or_build(key, lambda: orjson.dumps(build()), settings.IIIF_MEMO_TTL)
    return _response(body, content_type, PUBLIC, etag)
