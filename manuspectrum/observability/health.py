"""Readiness probes behind ``/readyz``.

Each probe takes a timeout in seconds and returns, or raises. ``readiness()``
runs them concurrently on daemon threads, waits at most ``READYZ_TIMEOUT`` + 0.5 s
in all, and reports per component ``up`` (with its duration), ``down`` (with the
exception class, or the fixed reason of ``ProbeFailed``; never the message, which
may hold a URL with credentials) or ``timeout`` (logged once, by component name).
A probe still running after the bound is left to finish on its own socket
timeout; its daemon thread never delays the exit of the worker and it holds no
Django connection. A process runs one evaluation at a time (see ``readiness``). To add a component: write ``probe_<name>(timeout)``, add it to
``components()``, add its name to ``metrics.READYZ_COMPONENTS``.
"""

import functools
import logging
import threading
import time

from django.conf import settings
from django.db import connections

from manuspectrum.observability import metrics

logger = logging.getLogger(__name__)


class ProbeFailed(Exception):
    """A component answered, but not ready; the message is a fixed reason."""


def probe_postgres(timeout):
    """``SELECT 1`` on a new connection with the settings of ``default``, bounded by *timeout*."""
    import psycopg2

    params = connections["default"].get_connection_params()
    params["connect_timeout"] = max(2, int(timeout))  # libpq: whole seconds, 2 at least
    params["options"] = (
        f"{params.get('options', '')} -c statement_timeout={int(timeout * 1000)}".strip()
    )
    connection = psycopg2.connect(**params)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    finally:
        connection.close()


def search_engine():
    from arches.app.search.search_engine_factory import SearchEngineInstance

    return SearchEngineInstance


def probe_elasticsearch(timeout):
    """Cluster health through Arches' search engine; red is down."""
    health = search_engine().es.options(request_timeout=timeout).cluster.health()
    if health["status"] == "red":
        raise ProbeFailed("status red")


def probe_broker(timeout):
    """A connection to ``CELERY_BROKER_URL``, the one Celery publishes on."""
    from kombu import Connection

    with Connection(
        settings.CELERY_BROKER_URL,
        connect_timeout=timeout,
        transport_options={
            "socket_timeout": timeout,
            "socket_connect_timeout": timeout,
        },
    ) as connection:
        connection.ensure_connection(
            max_retries=1, interval_start=0, interval_step=0, timeout=timeout
        )


def probe_redis(url, timeout):
    import redis

    client = redis.Redis.from_url(
        url, socket_connect_timeout=timeout, socket_timeout=timeout
    )
    try:
        if not client.ping():
            raise ProbeFailed("no pong")
    finally:
        client.close()


def probe_cantaloupe(timeout):
    import requests

    url = settings.CANTALOUPE_HTTP_ENDPOINT.rstrip("/") + "/iiif/3"
    response = requests.get(url, timeout=(timeout, timeout), allow_redirects=False)
    response.close()
    if response.status_code != 200:
        raise ProbeFailed(f"http {response.status_code}")


def components():
    """``[(name, probe)]`` of the components this deployment checks."""
    checks = [
        ("postgres", probe_postgres),
        ("elasticsearch", probe_elasticsearch),
        ("celery-broker", probe_broker),
    ]
    for name, url in getattr(settings, "READYZ_REDIS_URLS", {}).items():
        checks.append((name, functools.partial(probe_redis, url)))
    if getattr(settings, "READYZ_CANTALOUPE", False):
        checks.append(("cantaloupe", probe_cantaloupe))
    return checks


REUSE_WINDOW = 2.0
_gate = threading.Lock()
_last = None  # (monotonic time, report) of the last finished evaluation


def _run(probe, timeout, outcome):
    started = time.monotonic()
    try:
        probe(timeout)
        outcome["seconds"] = time.monotonic() - started
    except BaseException as error:  # noqa: BLE001 - reported by class, never raised
        outcome["error"] = error


def _evaluate():
    """Run every probe on its own daemon thread, wait at most ``READYZ_TIMEOUT`` + 0.5 s in all."""
    timeout = float(settings.READYZ_TIMEOUT)
    runs = []
    for name, probe in components():
        outcome = {}
        thread = threading.Thread(
            target=_run,
            args=(probe, timeout, outcome),
            name=f"readyz-{name}",
            daemon=True,
        )
        thread.start()
        runs.append((name, thread, outcome))
    deadline = time.monotonic() + timeout + 0.5
    report = {}
    for name, thread, outcome in runs:
        thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive():
            entry = {"status": "timeout"}
            logger.warning("readiness: %s timed out", name)
        elif "error" in outcome:
            error = outcome["error"]
            if isinstance(error, ProbeFailed):
                entry = {"status": "down", "error": str(error)}
            else:
                entry = {"status": "down", "error": type(error).__name__}
                logger.warning("readiness: %s is down: %s", name, error)
        else:
            entry = {"status": "up", "seconds": round(outcome["seconds"], 3)}
        metrics.READYZ_UP.labels(
            component=metrics.bounded(name, metrics.READYZ_COMPONENTS)
        ).set(1 if entry["status"] == "up" else 0)
        report[name] = entry
    ready = all(entry["status"] == "up" for entry in report.values())
    return {"status": "ready" if ready else "not ready", "components": report}


def _fresh():
    last = _last
    if last is not None and time.monotonic() - last[0] < REUSE_WINDOW:
        return last[1]
    return None


def readiness():
    """The readiness report. One evaluation runs per process at a time: a call that
    finds one running reuses its result when it ends within ``REUSE_WINDOW`` seconds, or
    after waiting at most ``READYZ_TIMEOUT`` reports every component ``timeout``."""
    global _last
    waited = False
    if not _gate.acquire(blocking=False):
        report = _fresh()
        if report is not None:
            return report
        if not _gate.acquire(timeout=float(settings.READYZ_TIMEOUT)):
            return {
                "status": "not ready",
                "components": {
                    name: {"status": "timeout"} for name, _probe in components()
                },
            }
        waited = True
    try:
        report = _fresh() if waited else None
        if report is None:
            report = _evaluate()
            _last = (time.monotonic(), report)
        return report
    finally:
        _gate.release()
