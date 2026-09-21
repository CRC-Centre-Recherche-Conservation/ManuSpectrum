"""Cache helpers shared by the views that memoise an expensive build."""

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


def get_or_build(key, build, timeout, *, lock_timeout=60, wait=2.0, poll=0.1):
    """Return the cached value for `key`, building it at most once per miss.

    A miss takes a lock (`cache.add`, atomic on Redis and locmem); the holder
    builds, stores a non-None result for `timeout` seconds and releases the
    lock even when `build` raises. Other callers poll the key for up to
    `wait` seconds, then build themselves rather than block: a lost holder
    costs one extra build, never a stalled request. `None` means "failed, do
    not memoise"; empty lists and dicts are stored.
    """
    value = cache.get(key)
    if value is not None:
        return value
    lock_key = f"{key}:lock"
    if cache.add(lock_key, 1, lock_timeout):
        try:
            value = build()
            if value is not None:
                cache.set(key, value, timeout)
            return value
        finally:
            cache.delete(lock_key)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        time.sleep(poll)
        value = cache.get(key)
        if value is not None:
            return value
    value = build()
    if value is not None:
        cache.set(key, value, timeout)
    return value
