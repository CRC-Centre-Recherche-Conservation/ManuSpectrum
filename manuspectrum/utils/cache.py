"""Cache helpers for the views that memoise a build, and their ETag check."""

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
