"""Memo of the Explorer's corpus bundle: one per reader scope, language and data version.

A bundle holds everything a request derives from the whole visible corpus
(rows, facet universe and labels, names, link maps); ``explorer.service``
builds it, this module keeps it. The key carries the ``explorer_scope`` of
the reader, the language, ``data_version()``, the permission epoch and the
digest of the reader's ``visible_set``; the data version and the visible set
are read once per request, before any memo is looked up.

Two layers. The default cache holds the bundle pickled and compressed with
zlib level 1 (``pack``): a miss is built by one caller across processes while
the others wait for it (``BUILD_WAIT``), and only the last ``LIVE_ENTRIES``
keys per scope and language stay stored. That retirement works within one
cache key prefix: the entries of a previous ``CACHE_CODE_VERSION`` are never
read again and expire by ``settings.EXPLORER_BUNDLE_TTL``.
Each process keeps the last ``LOCAL_ENTRIES`` bundles it used, unpickled,
and builds or loads one bundle at a time in its requests: a bundle is large,
and builds are CPU-bound under one interpreter lock anyway. The cyclic
garbage collector is paused while a bundle is built or unpickled: both
allocate hundreds of thousands of containers, and the collections they
trigger cost about a third of a build. The cycles a build leaves behind
(Django keeps the traceback of the lookups it resolves by exception) are
collected after it.

Stale while rebuilding. When the current key holds no bundle but a live
bundle of the same scope and language was built under the same permission
gates (epoch, hidden resources, readable nodegroups and models: everything
but the data), ``ticket`` names that bundle and the reader is answered from
it at once, while one rebuild of the current key runs in the background:
the caller that takes the key's build lock starts it through ``spawn``, the
others keep reading the previous bundle until the new one is stored. A
change of permission gates, or no previous bundle, builds in the request.

One ``INFO`` line per build on the ``manuspectrum.explorer`` logger, its
fields in ``extra``: ``duration_s``, ``rows``, ``stored_bytes``,
``language``, ``scope_kind`` (``public`` for the shared scope, else
``reader``), ``reason`` (``data``, ``permissions``, ``cold``),
``background`` and ``stale_served`` (answers given from the previous bundle
while it ran).

A bundle is shared between threads and requests: callers read it, never
change it.
"""

import gc
import logging
import pickle
import threading
import time
import zlib
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, replace

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.utils import translation

from manuspectrum.utils.cache import get_or_build, stable_cache_key
from manuspectrum.utils.data_version import data_version
from manuspectrum.utils.public_visibility import (
    VisibleSet,
    explorer_scope,
    permission_epoch,
    visible_set,
)

logger = logging.getLogger("manuspectrum.explorer")

BUILD_WAIT = 45
LOCK_TIMEOUT = 90
LIVE_ENTRIES = 2
LOCAL_ENTRIES = 2

_local = OrderedDict()
_local_lock = threading.Lock()
_build_lock = threading.Lock()
_collector_lock = threading.Lock()
_collector_pauses = 0
_collector_was_enabled = False


def bundle_key(scope, language, version, epoch, digest):
    return stable_cache_key("explorer-bundle", scope, language, version, epoch, digest)


@dataclass(frozen=True)
class Ticket:
    """What names the bundle a reader is answered from in one language, read before any memo.

    ``key`` is the bundle served; ``current`` the bundle of the current data
    and permissions. They differ while a rebuild of ``current`` runs and the
    reader is answered from the previous bundle (``stale``). ``permissions``
    names the permission gates of the reader; ``reason`` why ``current``
    would be built: ``data``, ``permissions`` or ``cold``.
    """

    key: str
    scope: str
    language: str
    visible: VisibleSet
    current: str = ""
    permissions: str = ""
    reason: str = "cold"

    @property
    def stale(self):
        return bool(self.current) and self.key != self.current


def ticket(user, language, build=None):
    """The ``Ticket`` of *user* in *language*: data version and visible set read once.

    When the current bundle is missing and a previous one may stand in for
    it, starts its rebuild with *build* (``build(user, language, visible)``,
    ``explorer.service.build_bundle`` by default) and names the previous one.
    """
    version = data_version()
    visible = visible_set(user, version=version)
    scope = explorer_scope(user)
    epoch = permission_epoch()
    key = bundle_key(scope, language, version, epoch, visible.digest)
    held = Ticket(
        key=key,
        scope=scope,
        language=language,
        visible=visible,
        current=key,
        permissions=stable_cache_key("explorer-gates", epoch, visible.gates),
    )
    if _stored(key):
        return held
    previous, reason = _previous(held)
    held = replace(held, reason=reason)
    if previous is None:
        return held
    _rebuild_in_background(held, user, build or _service_build)
    if _stored(key):
        return held
    _count_stale(held)
    return replace(held, key=previous)


def corpus_bundle(user, language, build, held=None):
    """The bundle of *user* in *language*; ``build(user, language, visible)`` makes a missing one.

    *held* is the ``ticket`` the caller already read for this request. A
    stale ticket whose previous bundle is gone builds the current one.
    """
    held = held or ticket(user, language, build)
    if held.stale:
        found = _load(held.key)
        if found is not None:
            return found
        held = replace(held, key=held.current)
    return remember(
        held.key,
        held.scope,
        language,
        lambda: build(user, language, held.visible),
        permissions=held.permissions,
        reason=held.reason,
    )


def remember(key, scope, language, build, permissions="", reason="cold"):
    """The bundle stored under *key*, from this process, else the cache, else ``build()``."""
    found = _local_get(key)
    if found is not None:
        return found
    with _build_lock:
        found = _local_get(key)
        if found is not None:
            return found
        built = []

        def build_packed():
            started = time.monotonic()
            with _collector_paused():
                built.append(build())
            if built[0] is None:
                return None
            packed = pack(built[0])
            _log_build(key, scope, language, reason, started, built[0], packed, False)
            return packed

        stored = get_or_build(
            key,
            build_packed,
            settings.EXPLORER_BUNDLE_TTL,
            lock_timeout=LOCK_TIMEOUT,
            wait=BUILD_WAIT,
            kept=lambda _: _retire_previous(scope, language, key, permissions),
        )
        found = built[0] if built else unpack(stored)
        _local_put(key, found)
        return found


def spawn(target):
    """Run *target* in a daemon thread that closes its database connections at the end.

    Runs it in the calling thread when ``settings.EXPLORER_BACKGROUND_REBUILD``
    is False.
    """
    if not getattr(settings, "EXPLORER_BACKGROUND_REBUILD", True):
        target()
        return None

    def run():
        try:
            target()
        finally:
            connections.close_all()

    thread = threading.Thread(target=run, name="explorer-rebuild", daemon=True)
    thread.start()
    return thread


def pack(bundle):
    """*bundle* as stored in the default cache: pickled, then zlib level 1."""
    return zlib.compress(pickle.dumps(bundle, pickle.HIGHEST_PROTOCOL), 1)


def unpack(stored):
    """The bundle ``pack`` turned into *stored*."""
    with _collector_paused():
        return pickle.loads(zlib.decompress(stored))


@contextmanager
def _collector_paused():
    """Pause the cyclic collector until the last of the overlapping pauses ends."""
    global _collector_pauses, _collector_was_enabled
    with _collector_lock:
        if _collector_pauses == 0:
            _collector_was_enabled = gc.isenabled()
            gc.disable()
        _collector_pauses += 1
    try:
        yield
    finally:
        with _collector_lock:
            _collector_pauses -= 1
            if _collector_pauses == 0 and _collector_was_enabled:
                gc.enable()


def forget_local():
    """Drop every bundle this process holds."""
    with _local_lock:
        _local.clear()


def _service_build(user, language, visible):
    from manuspectrum.views.explorer import service

    return service.build_bundle(user, language, visible)


def _stored(key):
    return key in _local or cache.has_key(key)


def _load(key):
    """The bundle stored under *key*, from this process or the cache; never builds."""
    found = _local_get(key)
    if found is not None:
        return found
    with _build_lock:
        found = _local_get(key)
        if found is None:
            stored = cache.get(key)
            if stored is None:
                return None
            found = unpack(stored)
            _local_put(key, found)
        return found


def _previous(held):
    """The newest stored live key built under the gates of *held*, and why *held* is missing.

    ``data`` when there is one; else ``permissions`` when the scope and
    language have live keys built under other gates, ``cold`` when not.
    """
    other_gates = False
    for key, permissions in reversed(_live(held.scope, held.language)):
        if permissions != held.permissions:
            other_gates = True
        elif _stored(key):
            return key, "data"
    return None, "permissions" if other_gates else "cold"


def _rebuild_in_background(held, user, build):
    """Start the one rebuild of ``held.current``, unless a caller holds its build lock."""
    lock = f"{held.current}:lock"
    if not cache.add(lock, 1, LOCK_TIMEOUT):
        return
    if cache.has_key(held.current):
        cache.delete(lock)
        return

    def rebuild():
        try:
            with translation.override(held.language):
                _build_and_keep(held, lambda: build(user, held.language, held.visible))
        except Exception:
            logger.exception(
                "explorer bundle rebuild failed",
                extra={"language": held.language, "scope_kind": _kind(held.scope)},
            )
        finally:
            cache.delete(lock)

    try:
        spawn(rebuild)
    except Exception:
        cache.delete(lock)
        logger.exception("explorer bundle rebuild could not start")


def _build_and_keep(held, build):
    started = time.monotonic()
    with _collector_paused():
        bundle = build()
    if bundle is None:
        logger.warning(
            "explorer bundle rebuild returned nothing",
            extra={"language": held.language, "scope_kind": _kind(held.scope)},
        )
        return
    packed = pack(bundle)
    cache.set(held.current, packed, settings.EXPLORER_BUNDLE_TTL)
    _retire_previous(held.scope, held.language, held.current, held.permissions)
    _local_put(held.current, bundle)
    _log_build(
        held.current,
        held.scope,
        held.language,
        held.reason,
        started,
        bundle,
        packed,
        True,
    )


def _stale_key(key):
    return f"{key}:stale"


def _count_stale(held):
    counter = _stale_key(held.current)
    try:
        cache.incr(counter)
    except ValueError:
        cache.add(counter, 1, LOCK_TIMEOUT)
    logger.debug(
        "explorer bundle served stale",
        extra={"language": held.language, "scope_kind": _kind(held.scope)},
    )


def _kind(scope):
    return "public" if scope == "public" else "reader"


def _log_build(key, scope, language, reason, started, bundle, packed, background):
    stale_served = cache.get(_stale_key(key)) or 0
    cache.delete(_stale_key(key))
    fields = {
        "duration_s": round(time.monotonic() - started, 3),
        "rows": len(getattr(bundle, "rows", ())),
        "stored_bytes": len(packed),
        "language": language,
        "scope_kind": _kind(scope),
        "reason": reason,
        "background": background,
        "stale_served": stale_served,
    }
    logger.info(
        "explorer bundle built: %(duration_s)ss, %(rows)s rows, %(stored_bytes)s bytes, "
        "language=%(language)s scope=%(scope_kind)s reason=%(reason)s "
        "background=%(background)s stale_served=%(stale_served)s",
        fields,
        extra=fields,
    )


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


def _live_pointer(scope, language):
    return stable_cache_key("explorer-bundle-live", scope, language)


def _live(scope, language):
    """The live ``(key, permissions)`` of a scope and language, oldest first."""
    return [
        tuple(entry) if isinstance(entry, (list, tuple)) else (entry, None)
        for entry in cache.get(_live_pointer(scope, language)) or []
    ]


def _retire_previous(scope, language, key, permissions=""):
    """Keep the last ``LIVE_ENTRIES`` stored bundles of a scope and language, delete the older ones."""
    live = [e for e in _live(scope, language) if e[0] != key] + [(key, permissions)]
    for old, _ in live[:-LIVE_ENTRIES]:
        cache.delete(old)
    cache.set(
        _live_pointer(scope, language),
        live[-LIVE_ENTRIES:],
        settings.EXPLORER_BUNDLE_TTL,
    )
