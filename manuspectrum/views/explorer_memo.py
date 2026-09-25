"""Memo of the Explorer's corpus bundle: one per reader scope, language and data version.

A bundle holds everything a request derives from the whole visible corpus
(rows, facet universe and labels, names, link maps); ``explorer_service``
builds it, this module keeps it. The key carries the ``explorer_scope`` of
the reader, the language, ``data_version()``, the permission epoch and the
digest of the reader's ``visible_set``; the data version and the visible set
are read once per request, before any memo is looked up.

Two layers. The default cache holds the pickled bundle: a miss is built by
one caller across processes while the others wait for it (``BUILD_WAIT``),
and only the last ``LIVE_ENTRIES`` keys per scope and language stay stored.
Each process keeps the last ``LOCAL_ENTRIES`` bundles it used, unpickled,
and builds or loads one bundle at a time: a bundle is large, and builds
are CPU-bound under one interpreter lock anyway. The cyclic garbage
collector is paused while a bundle is built or unpickled: both allocate
hundreds of thousands of containers, and the collections they trigger cost
about a third of a build. The cycles a build leaves behind (Django keeps the
traceback of the lookups it resolves by exception) are collected after it.

A bundle is shared between threads and requests: callers read it, never
change it.
"""

import gc
import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass

from django.core.cache import cache

from manuspectrum.utils.cache import get_or_build, stable_cache_key
from manuspectrum.utils.data_version import data_version
from manuspectrum.utils.public_visibility import (
    VisibleSet,
    explorer_scope,
    permission_epoch,
    visible_set,
)

BUNDLE_TTL = 6 * 60 * 60
BUILD_WAIT = 45
LOCK_TIMEOUT = 90
LIVE_ENTRIES = 2
LOCAL_ENTRIES = 2

_local = OrderedDict()
_local_lock = threading.Lock()
_build_lock = threading.Lock()


def bundle_key(scope, language, version, epoch, digest):
    return stable_cache_key("explorer-bundle", scope, language, version, epoch, digest)


@dataclass(frozen=True)
class Ticket:
    """What names the bundle of one reader in one language: its key, read before any memo."""

    key: str
    scope: str
    language: str
    visible: VisibleSet


def ticket(user, language):
    """The ``Ticket`` of *user* in *language*: data version and visible set read once."""
    version = data_version()
    visible = visible_set(user, version=version)
    scope = explorer_scope(user)
    key = bundle_key(scope, language, version, permission_epoch(), visible.digest)
    return Ticket(key=key, scope=scope, language=language, visible=visible)


def corpus_bundle(user, language, build, held=None):
    """The bundle of *user* in *language*; ``build(user, language, visible)`` makes a missing one.

    *held* is the ``ticket`` the caller already read for this request.
    """
    held = held or ticket(user, language)
    return remember(
        held.key,
        held.scope,
        language,
        lambda: build(user, language, held.visible),
    )


def remember(key, scope, language, build):
    """The bundle stored under *key*, from this process, else the cache, else ``build()``."""
    found = _local_get(key)
    if found is not None:
        return found
    with _build_lock:
        found = _local_get(key)
        if found is not None:
            return found
        with _collector_paused():
            found = cache.get(key)
        if found is None:
            found = get_or_build(
                key,
                _collector_paused()(build),
                BUNDLE_TTL,
                lock_timeout=LOCK_TIMEOUT,
                wait=BUILD_WAIT,
                kept=lambda _: _retire_previous(scope, language, key),
            )
        _local_put(key, found)
        return found


@contextmanager
def _collector_paused():
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()


def forget_local():
    """Drop every bundle this process holds."""
    with _local_lock:
        _local.clear()


def _local_get(key):
    with _local_lock:
        found = _local.get(key)
        if found is not None:
            _local.move_to_end(key)
        return found


def _local_put(key, value):
    with _local_lock:
        _local[key] = value
        _local.move_to_end(key)
        while len(_local) > LOCAL_ENTRIES:
            _local.popitem(last=False)


def _retire_previous(scope, language, key):
    """Keep the last ``LIVE_ENTRIES`` stored bundles of a scope and language, delete the older ones."""
    pointer = stable_cache_key("explorer-bundle-live", scope, language)
    live = [k for k in cache.get(pointer) or [] if k != key] + [key]
    for old in live[:-LIVE_ENTRIES]:
        cache.delete(old)
    cache.set(pointer, live[-LIVE_ENTRIES:], BUNDLE_TTL)
