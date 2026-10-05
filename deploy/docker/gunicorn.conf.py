"""gunicorn settings of the `web` container.

`gthread` workers: GUNICORN_WORKERS processes (default 2) of GUNICORN_THREADS
request threads each (default 4); production runs 5 x 4, 20 concurrent
requests. Application code must be thread-safe (see CLAUDE.md, "Concurrency:
gunicorn gthread workers").

`timeout` only detects a worker whose main loop is stuck; it does not bound a
request, and a request thread blocked in a network call is never killed. The
guards are the application budgets: BIBLISSIMA_VIEW_DEADLINE, the SSRF_*
timeouts and SUMMARY_ES_TIMEOUT.

A worker that reaches `max_requests` stops accepting requests and waits at
most `graceful_timeout` for the requests its threads still serve before it
exits; a stop or a restart of the container waits the same. 300 s lets the
longest downloads (Explorer export, `series.csv`, full spectra) finish, and
the Compose `stop_grace_period` of `web` (310 s) stays above it.

No preload: Arches opens connections when it is imported, and `wsgi.py`
closes the import-time connections in each worker. Forwarded headers are
trusted from any address because the container publishes no port: only the
Compose network (nginx, from PP-3) reaches it. Logs go to stdout/stderr.
"""

import os

wsgi_app = "manuspectrum.wsgi:application"
chdir = "/app"
bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", 2))
threads = int(os.environ.get("GUNICORN_THREADS", 4))
worker_class = "gthread"
timeout = 90
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", 300))
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "*")
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
