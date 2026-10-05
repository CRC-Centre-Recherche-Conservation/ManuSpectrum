"""Bounded ``PROMETHEUS_MULTIPROC_DIR`` for processes that come and go.

prometheus_client keeps one file per process and type (``counter_<pid>.db``,
``histogram_<pid>.db``, ``summary_<pid>.db``, ``gauge_<mode>_<pid>.db``) and
``MultiProcessCollector`` sums every ``*.db`` of the directory, the type being
the filename's first ``_`` part. ``mark_process_dead`` only removes the
``gauge_live*`` files of a dead pid; its counters and histograms must stay or the
summed totals would fall. A recycled worker would then leave its files for the
life of the container.

``archive_dead_process(pid, path)`` folds the files of a dead pid into one
archive file per type (``counter_archive.db``, ``histogram_archive.db``,
``summary_archive.db``, ``gauge_mostrecent_archive.db``), in the library's own
file format, then deletes them:

- counter, histogram, summary: the raw values are added key by key (histogram
  buckets, ``_sum`` and ``_count`` are stored un-accumulated, so adding the raw
  values is exact);
- ``gauge_mostrecent``: the value with the newest timestamp per key is kept;
- ``gauge_live*``: removed by ``mark_process_dead``, as the library does;
- any other gauge mode (``all``, ``min``, ``max``, ``sum``; the project's
  ``metrics.gauge()`` allows neither) is left as the library leaves it.

An ``flock`` on ``.archive.lock`` serialises concurrent archivers. The archive's
pid label for a gauge reads ``archive``. The gauge
``manuspectrum_metrics_dir_bytes`` (mostrecent), written into the gauge archive
on each call, reports the bytes the directory occupies.

This module imports only the standard library and prometheus_client: gunicorn's
arbiter loads it without Django.
"""

import fcntl
import glob
import json
import os
import time

from prometheus_client import multiprocess
from prometheus_client.mmap_dict import MmapedDict, mmap_key

SUMMED_TYPES = ("counter", "histogram", "summary")
DIR_BYTES_NAME = "manuspectrum_metrics_dir_bytes"
DIR_BYTES_HELP = "Bytes the Prometheus multiprocess directory occupies."
_LOCK = ".archive.lock"


def directory_bytes(path):
    """Bytes allocated by the ``*.db`` files of *path* (sparse files count their touched pages)."""
    total = 0
    for name in glob.glob(os.path.join(path, "*.db")):
        try:
            total += os.stat(name).st_blocks * 512
        except FileNotFoundError:
            pass
    return total


def _read(filename):
    try:
        return list(MmapedDict.read_all_values_from_file(filename))
    except FileNotFoundError:
        return []


def _sum_into(archive, rows):
    store = MmapedDict(archive)
    try:
        for key, value, timestamp, _ in rows:
            current, _stamp = store.read_value(key)
            store.write_value(key, current + value, timestamp)
    finally:
        store.close()


def _newest_into(archive, rows):
    store = MmapedDict(archive)
    try:
        for key, value, timestamp, _ in rows:
            _current, stamp = store.read_value(key)
            if timestamp >= stamp:
                store.write_value(key, value, timestamp)
    finally:
        store.close()


def _write_dir_bytes(path):
    key = mmap_key(DIR_BYTES_NAME, DIR_BYTES_NAME, [], [], DIR_BYTES_HELP)
    store = MmapedDict(os.path.join(path, "gauge_mostrecent_archive.db"))
    try:
        store.write_value(key, float(directory_bytes(path)), time.time())
    finally:
        store.close()


def archive_dead_process(pid, path=None):
    """Fold the files of the dead process *pid* into the archives of *path*, then delete them."""
    path = path or os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if not path:
        return
    with open(os.path.join(path, _LOCK), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            multiprocess.mark_process_dead(pid, path)
            for typ in SUMMED_TYPES:
                source = os.path.join(path, f"{typ}_{pid}.db")
                if os.path.exists(source):
                    _sum_into(os.path.join(path, f"{typ}_archive.db"), _read(source))
                    os.remove(source)
            source = os.path.join(path, f"gauge_mostrecent_{pid}.db")
            if os.path.exists(source):
                _newest_into(
                    os.path.join(path, "gauge_mostrecent_archive.db"), _read(source)
                )
                os.remove(source)
            _write_dir_bytes(path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
