"""Readiness probes behind ``/readyz``.

Each probe takes a timeout in seconds and returns, or raises. ``readiness()``
runs them concurrently, waits at most ``READYZ_TIMEOUT`` + 0.5 s in all, and
reports per component ``up`` (with its duration), ``down`` (with the exception
class, or the fixed reason of ``ProbeFailed``; never the message, which may
hold a URL with credentials) or ``timeout``. A probe still running after the
bound is left to finish on its own socket timeout; it holds no Django
connection. To add a component: write ``probe_<name>(timeout)``, add it to
``components()``, add its name to ``metrics.READYZ_COMPONENTS``.
"""

import concurrent.futures
import functools
import logging
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


def _timed(probe, timeout):
    started = time.monotonic()
    probe(timeout)
    return time.monotonic() - started


def readiness():
    timeout = float(settings.READYZ_TIMEOUT)
    checks = components()
    pool = concurrent.futures.ThreadPoolExecutor(
        max_workers=len(checks), thread_name_prefix="readyz"
    )
    futures = {name: pool.submit(_timed, probe, timeout) for name, probe in checks}
    concurrent.futures.wait(futures.values(), timeout=timeout + 0.5)
    pool.shutdown(wait=False, cancel_futures=True)
    report = {}
    for name, future in futures.items():
        if not future.done():
            entry = {"status": "timeout"}
        else:
            try:
                entry = {"status": "up", "seconds": round(future.result(), 3)}
            except ProbeFailed as failure:
                entry = {"status": "down", "error": str(failure)}
            except Exception as error:
                entry = {"status": "down", "error": type(error).__name__}
                logger.warning("readiness: %s is down: %s", name, error)
        metrics.READYZ_UP.labels(
            component=metrics.bounded(name, metrics.READYZ_COMPONENTS)
        ).set(1 if entry["status"] == "up" else 0)
        report[name] = entry
    ready = all(entry["status"] == "up" for entry in report.values())
    return {"status": "ready" if ready else "not ready", "components": report}


_real_probe_elasticsearch = probe_elasticsearch
_real_probe_broker = probe_broker
