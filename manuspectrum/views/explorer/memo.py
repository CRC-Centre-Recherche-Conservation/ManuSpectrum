"""Memo of the Explorer's corpus bundle: one per language, data version and visible set.

A bundle holds everything a request derives from the whole visible corpus
(rows, facet universe and labels, names, link maps); ``explorer.service``
builds it, this module keeps it. The Explorer answers every reader with
the visitor's view (spec D59), so one bundle per language serves everyone.
The key carries the language, ``data_version()``, the permission epoch and
the digest of the ``visible_set`` it was built from, which names every
permission-relevant input of the build; the data version and the visible
set are read once per request, before any memo is looked up.

Two layers. The default cache holds the bundle pickled and compressed with
zlib level 1 (``pack``): a miss is built by one caller across processes while
the others wait for it (``BUILD_WAIT``), and only the last ``LIVE_ENTRIES``
keys per language stay stored. That retirement works within one
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
bundle of the same language was built under the same permission gates
(epoch, hidden resources, readable nodegroups and models: everything but
the data) and shows no resource the reader can no longer see, ``ticket``
names that bundle and the reader is answered from it at once, while one
rebuild runs in the background: one at a time in a process, whatever its
language, and one per language across processes, started through
``spawn`` by the caller that takes the language's rebuild lock. The others
keep reading the previous bundle until the new one is stored; a data
change during a rebuild is rebuilt by the first request after it ends.
Meanwhile a resource made visible by the new data is still absent from the
bundle served: its document or analysis answers 404 for those few seconds,
and the new analyses of a document read as not matching the filters. A
change of permission gates, a resource the previous bundle shows that the
current visible set leaves out (a link to a hidden Project, a deletion), or
no previous bundle, builds in the request.

One ``INFO`` line per build on the ``manuspectrum.explorer`` logger, its
fields in ``extra``: ``duration_s``, ``rows``, ``stored_bytes``,
``language``, ``reason`` (``data``, ``permissions``, ``visibility``,
``cold``), ``background`` and ``stale_served`` (answers given from the
previous bundle while it ran).

A bundle is shared between threads and requests: callers read it, never
change it.
"""

import gc
import logging
import pickle
import threading
import time
import uuid
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
    permission_epoch,
    visible_set,
)

logger = logging.getLogger("manuspectrum.explorer")

BUILD_WAIT = 45
LOCK_TIMEOUT = 90
LIVE_ENTRIES = 2
LOCAL_ENTRIES = 2
POINTER_LOCK_WAIT = 5

_local = OrderedDict()
_local_lock = threading.Lock()
_build_lock = threading.Lock()
_rebuilding = set()
_rebuilding_lock = threading.Lock()
_collector_lock = threading.Lock()
_collector_pauses = 0
_collector_was_enabled = False


def _clock():
    """Wall-clock seconds, shared by every process: when a background rebuild ended."""
    return time.time()


def bundle_key(language, version, epoch, digest):
    return stable_cache_key("explorer-bundle", language, version, epoch, digest)


@dataclass(frozen=True)
class Ticket:
    """What names the bundle a reader is answered from in one language, read before any memo.

    ``key`` is the bundle served; ``current`` the bundle of the current data
    (``data_version`` ``version``) and permissions. They differ while a
    rebuild of ``current`` runs and the reader is answered from the previous
    bundle (``stale``). ``permissions`` names the permission gates of the
    reader; ``reason`` why ``current`` would be built: ``data``,
    ``permissions``, ``visibility`` (the previous bundle shows a resource the
    reader can no longer see) or ``cold`` (no previous bundle to answer from).
    """

    key: str
    language: str
    visible: VisibleSet
    current: str = ""
    permissions: str = ""
    reason: str = "cold"
    version: str = ""

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
    epoch = permission_epoch()
    key = bundle_key(language, version, epoch, visible.digest)
    held = Ticket(
        key=key,
        language=language,
        visible=visible,
        current=key,
        permissions=stable_cache_key("explorer-gates", epoch, visible.gates),
        version=version,
    )
    if _stored(key):
        return held
    previous, reason = _previous(held)
    held = replace(held, reason=reason)
    if previous is None:
        return held
    shown = _load(previous)
    if shown is None:
        return replace(held, reason="cold")
    if _shows_hidden(shown, visible):
        return replace(held, reason="visibility")
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
        language,
        lambda: build(user, language, held.visible),
        permissions=held.permissions,
        reason=held.reason,
        version=held.version,
    )


def remember(key, language, build, permissions="", reason="cold", version=""):
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
            _log_build(key, language, reason, started, built[0], packed, False)
            return packed

        stored = get_or_build(
            key,
            build_packed,
            settings.EXPLORER_BUNDLE_TTL,
            lock_timeout=LOCK_TIMEOUT,
            wait=BUILD_WAIT,
            kept=lambda _: _retire_previous(language, key, permissions, version),
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


def _shows_hidden(bundle, visible):
    """Whether *bundle* shows a resource outside *visible*, lifecycle aside."""
    shown = getattr(bundle, "visible", None)
    return shown is None or bool(shown.ids - visible.ids)


def _previous(held):
    """The live key with the newest data stored under *held*'s gates, and why *held* is missing.

    ``data`` when there is one; else ``permissions`` when the language has
    live keys built under other gates, ``cold`` when not.
    """
    live = _live(held.language)
    same = [e for e in live if e[1] == held.permissions]
    for key, _, _ in sorted(same, key=lambda e: _order(e[2]), reverse=True):
        if _stored(key):
            return key, "data"
    return None, "permissions" if len(same) < len(live) else "cold"


def _order(version):
    """Where a ``data_version()`` stands in time: ``(last sequence, count)``, ``(-1, -1)`` when unknown.

    Two commits can share a last sequence (a transaction whose last write is
    older commits later); the row count, which grows with each committed
    transaction under one last sequence, orders them. A prune lowers the
    count but writes a higher sequence.
    """
    count, _, last = str(version).partition(".")
    try:
        return int(last), int(count)
    except ValueError:
        return -1, -1


def _rebuild_lock(language):
    return f"{stable_cache_key('explorer-rebuild', language)}:lock"


def _rebuild_failed(language):
    return f"{stable_cache_key('explorer-rebuild', language)}:failed"


def _rebuild_ended(language):
    return f"{stable_cache_key('explorer-rebuild', language)}:ended"


def _deferred(language):
    """Whether the last background rebuild of *language* ended less than ``EXPLORER_REBUILD_MIN_INTERVAL`` seconds ago."""
    interval = getattr(settings, "EXPLORER_REBUILD_MIN_INTERVAL", 0)
    if interval <= 0:
        return False
    ended = cache.get(_rebuild_ended(language))
    return ended is not None and _clock() - ended < interval


def _rebuild_in_background(held, user, build):
    """Start the rebuild of ``held.current`` unless this process or its language runs one.

    One background rebuild at a time in this process, whatever its
    language (a guard set), and one per language across processes (a cache
    lock). A caller that finds either taken starts
    nothing and is answered from the previous bundle. The lock holds its owner's token and only that
    owner deletes it: a rebuild that outlived ``LOCK_TIMEOUT`` leaves the
    lock a later one took. The next request after the running one ends
    starts the rebuild of the data current then. A rebuild that raised or
    returned nothing starts none for ``settings.EXPLORER_REBUILD_RETRY_AFTER``
    seconds, readers answered from the previous bundle meanwhile. Once a
    rebuild ends with a bundle (stored, or superseded by newer data), none
    starts for its language during
    ``settings.EXPLORER_REBUILD_MIN_INTERVAL`` seconds (0: no floor): readers
    of newer data are answered from the previous bundle and the first
    request after the interval starts the rebuild; a ``DEBUG`` line with
    ``deferred`` says so. A cache error while taking or releasing the lock
    or recording a failure is logged and never leaves the guard set.
    """
    failed = _rebuild_failed(held.language)
    if cache.get(failed):
        return
    if _deferred(held.language):
        logger.debug(
            "explorer bundle rebuild deferred",
            extra={"language": held.language, "deferred": True},
        )
        return
    slot = held.language
    with _rebuilding_lock:
        if _rebuilding:
            return
        _rebuilding.add(slot)
    lock, token = _rebuild_lock(held.language), uuid.uuid4().hex
    extra = {"language": held.language}

    def release():
        try:
            if cache.get(lock) == token:
                cache.delete(lock)
        except Exception:
            logger.exception("explorer bundle rebuild lock not released", extra=extra)
        finally:
            _free(slot)

    def rebuild():
        kept = False
        try:
            with translation.override(held.language):
                kept = _build_and_keep(
                    held, lambda: build(user, held.language, held.visible)
                )
        except Exception:
            logger.exception("explorer bundle rebuild failed", extra=extra)
        finally:
            try:
                if not kept:
                    cache.set(
                        failed,
                        1,
                        getattr(settings, "EXPLORER_REBUILD_RETRY_AFTER", 60),
                    )
                elif getattr(settings, "EXPLORER_REBUILD_MIN_INTERVAL", 0) > 0:
                    cache.set(
                        _rebuild_ended(held.language),
                        _clock(),
                        settings.EXPLORER_REBUILD_MIN_INTERVAL,
                    )
            except Exception:
                logger.exception(
                    "explorer bundle rebuild failure not recorded", extra=extra
                )
            finally:
                release()

    try:
        if cache.add(lock, token, LOCK_TIMEOUT) and not cache.has_key(held.current):
            spawn(rebuild)
            return
    except Exception:
        logger.exception("explorer bundle rebuild could not start", extra=extra)
    release()


def _free(slot):
    with _rebuilding_lock:
        _rebuilding.discard(slot)


def _build_and_keep(held, build):
    """Build and store ``held.current`` unless newer data is live; False when it gave nothing."""
    started = time.monotonic()
    with _collector_paused():
        bundle = build()
    if bundle is None:
        logger.warning(
            "explorer bundle rebuild returned nothing",
            extra={"language": held.language},
        )
        return False
    if _superseded(held):
        logger.info(
            "explorer bundle rebuild superseded by newer data",
            extra={"language": held.language},
        )
        return True
    packed = pack(bundle)
    cache.set(held.current, packed, settings.EXPLORER_BUNDLE_TTL)
    _retire_previous(held.language, held.current, held.permissions, held.version)
    _local_put(held.current, bundle)
    _log_build(
        held.current,
        held.language,
        held.reason,
        started,
        bundle,
        packed,
        True,
    )
    return True


def _stale_key(key):
    return f"{key}:stale"


def _count_stale(held):
    counter = _stale_key(held.current)
    try:
        cache.incr(counter)
    except ValueError:
        cache.add(counter, 1, LOCK_TIMEOUT)
    logger.debug("explorer bundle served stale", extra={"language": held.language})


def _log_build(key, language, reason, started, bundle, packed, background):
    stale_served = cache.get(_stale_key(key)) or 0
    cache.delete(_stale_key(key))
    fields = {
        "duration_s": round(time.monotonic() - started, 3),
        "rows": len(getattr(bundle, "rows", ())),
        "stored_bytes": len(packed),
        "language": language,
        "reason": reason,
        "background": background,
        "stale_served": stale_served,
    }
    logger.info(
        "explorer bundle built: %(duration_s)ss, %(rows)s rows, %(stored_bytes)s bytes, "
        "language=%(language)s reason=%(reason)s "
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


def _live_pointer(language):
    return stable_cache_key("explorer-bundle-live", language)


def _live(language):
    """The live ``(key, permissions, version)`` of a language, oldest data first."""
    return [tuple(e) for e in cache.get(_live_pointer(language)) or []]


def _superseded(held):
    """Whether a live bundle of *held*'s gates holds newer data than ``held.current``."""
    return any(
        permissions == held.permissions and _order(version) > _order(held.version)
        for _, permissions, version in _live(held.language)
    )


def _retire_previous(language, key, permissions="", version=""):
    """Keep the ``LIVE_ENTRIES`` bundles of a language with the newest data.

    The live pointer is read, changed and written under a cache lock held by
    one caller across processes, so two builds ending together both land in
    it. A caller that waits ``POINTER_LOCK_WAIT`` seconds without the lock
    updates the pointer anyway and logs it.
    """
    lock, token = f"{_live_pointer(language)}:lock", uuid.uuid4().hex
    deadline = time.monotonic() + POINTER_LOCK_WAIT
    while not cache.add(lock, token, POINTER_LOCK_WAIT):
        if time.monotonic() > deadline:
            logger.warning(
                "explorer bundle live pointer updated without its lock",
                extra={"language": language},
            )
            break
        time.sleep(0.01)
    try:
        live = sorted(
            [e for e in _live(language) if e[0] != key] + [(key, permissions, version)],
            key=lambda e: _order(e[2]),
        )
        for old, _, _ in live[:-LIVE_ENTRIES]:
            cache.delete(old)
        cache.set(
            _live_pointer(language),
            live[-LIVE_ENTRIES:],
            settings.EXPLORER_BUNDLE_TTL,
        )
    finally:
        if cache.get(lock) == token:
            cache.delete(lock)
