"""Cache helpers for the views that memoise a build, their ETag and CSRF checks."""

import hashlib
import time

from django.core.cache import cache


def stable_cache_key(prefix, *parts):
    """A bounded key: fixed prefix plus the sha1 of the joined parts.

    Client-supplied strings (URLs, hash lists) never reach the key verbatim,
    and two part lists cannot collide through the join.
    """
    joined = "\x1f".join(str(p) for p in parts)
    return f"{prefix}:{hashlib.sha1(joined.encode('utf-8')).hexdigest()}"  # noqa: S324


def etag_already_held(request, etag):
    """Whether the client's ``If-None-Match`` names *etag*.

    ``*`` stands for any current representation (RFC 9110 §13.1.2); anything
    else is a list of tags the strong form and the weak form are looked up in.
    """
    header = request.headers.get("If-None-Match", "")
    return header.strip() == "*" or etag in header or f"W/{etag}" in header


def if_match_allows(request, etag):
    """Whether a write may proceed under the client's ``If-Match``.

    An absent header allows it; ``*`` allows it; otherwise one listed tag must
    name *etag*. A ``W/`` prefix is ignored, unlike the strong comparison of
    RFC 9110 §13.1.1: a compressing proxy weakens the ETag the client echoes
    back, and the tags compared here are digests of the stored state, so a
    weakened copy still names the same version.
    """
    header = request.headers.get("If-Match")
    if header is None:
        return True
    tags = [tag.strip() for tag in header.split(",")]
    return "*" in tags or any(tag.removeprefix("W/") == etag for tag in tags)


def renews_csrf_cookie(request):
    """Whether ``CsrfViewMiddleware`` will add a ``Set-Cookie`` to this response.

    The middleware sets ``CSRF_COOKIE_NEEDS_UPDATE`` before the view for a
    malformed ``csrftoken`` cookie, and ``get_token()`` sets it whenever a
    render reads the token. A response answered while it is set is never
    ``public`` and never stored.
    """
    return bool(request.META.get("CSRF_COOKIE_NEEDS_UPDATE"))


def get_or_build(
    key, build, timeout, *, lock_timeout=60, wait=2.0, poll=0.1, kept=None
):
    """Return the cached value for `key`, building it at most once per miss.

    A miss takes a lock (`cache.add`, atomic on Redis and locmem); the holder
    builds, stores a non-None result for `timeout` seconds and releases the
    lock even when `build` raises. Other callers poll the key for up to
    `wait` seconds, then build themselves rather than block: a lost holder
    costs one extra build, never a stalled request. `None` means "failed, do
    not memoise"; empty lists and dicts are stored.

    `kept` runs on a value this call has just stored, never on a memo hit: it
    is how a caller gives the answer it built a lifetime of its own.
    """

    def keep(value):
        if value is not None:
            cache.set(key, value, timeout)
            if kept is not None:
                kept(value)
        return value

    value = cache.get(key)
    if value is not None:
        return value
    lock_key = f"{key}:lock"
    if cache.add(lock_key, 1, lock_timeout):
        try:
            return keep(build())
        finally:
            cache.delete(lock_key)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        time.sleep(poll)
        value = cache.get(key)
        if value is not None:
            return value
    return keep(build())
