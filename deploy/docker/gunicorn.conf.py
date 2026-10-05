"""gunicorn settings of the `web` container.

`gthread` workers: GUNICORN_WORKERS processes (default 2) of GUNICORN_THREADS
request threads each (default 4); production runs 5 x 4, 20 concurrent
requests. Application code must be thread-safe (see CLAUDE.md, "Concurrency:
gunicorn gthread workers").

Under gthread `timeout` only watches the worker's main loop: it never bounds
a request, and a request thread blocked in a network call is never killed. The
guards are the application budgets: BIBLISSIMA_VIEW_DEADLINE, the SSRF_*
timeouts and SUMMARY_ES_TIMEOUT.

A worker that reaches `max_requests` stops accepting requests and finishes
the requests its threads still serve; a stop of the container waits the same.
`graceful_timeout` (300 s) bounds both, so the longest downloads (Explorer
export, `series.csv`, full spectra) finish. A recycling worker no longer
notifies the arbiter, which kills it once its last heartbeat is older than
`timeout` (gunicorn 26.2.0, `workers/gthread.py`, `arbiter.murder_workers`):
`timeout` must therefore be at least `graceful_timeout`, and loading this
file raises ValueError otherwise. The Compose `stop_grace_period` of `web`
(310 s) stays above `graceful_timeout`; raise it with that value.

No preload: Arches opens connections when it is imported, and `wsgi.py`
closes the import-time connections in each worker. Forwarded headers are
trusted from any address because the container publishes no port: only the
Compose network (nginx, from PP-3) reaches it.

nginx writes the access log (rotated on the host, 30 days); gunicorn writes only
its error log, to stderr. With `PROMETHEUS_MULTIPROC_DIR` set (Compose),
`child_exit` archives a dead worker's metric files
(`manuspectrum/observability/multiproc.py`) so the directory stays bounded; the
entrypoint empties the directory before gunicorn starts.
"""

import os

wsgi_app = "manuspectrum.wsgi:application"
chdir = "/app"
bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", 2))
threads = int(os.environ.get("GUNICORN_THREADS", 4))
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 330))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", 300))
if timeout < graceful_timeout:
    raise ValueError(
        f"GUNICORN_TIMEOUT ({timeout}) must be at least "
        f"GUNICORN_GRACEFUL_TIMEOUT ({graceful_timeout})"
    )
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "*")
accesslog = None
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")


def _multiproc():
    """``manuspectrum/observability/multiproc.py`` loaded by path: importing the
    ``manuspectrum`` package would build the Celery app in the arbiter."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ms_multiproc",
        os.path.join(chdir, "manuspectrum", "observability", "multiproc.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def child_exit(server, worker):
    """Archive the metric files of the dead worker. Never raises: gunicorn calls this
    from the arbiter's reaper, where an exception halts every worker."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        try:
            _multiproc().archive_dead_process(worker.pid)
        except Exception as error:
            server.log.error(
                "manuspectrum.observability.multiproc: metrics archive failed for pid %s: %s",
                worker.pid,
                type(error).__name__,
            )
