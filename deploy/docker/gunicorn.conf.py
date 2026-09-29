"""gunicorn settings of the `web` container.

GUNICORN_WORKERS sync workers (default 2 * CPU + 1), no preload: Arches opens
connections when it is imported. `timeout` covers the slowest Biblissima scrape
(a 45 s request plus retries); a worker past it is replaced. Forwarded headers
are trusted from any address because the container publishes no port: only
the Compose network (nginx, from PP-3) reaches it. Logs go to stdout/stderr.
"""

import multiprocessing
import os

wsgi_app = "manuspectrum.wsgi:application"
chdir = "/app"
bind = "0.0.0.0:8000"
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = "sync"
timeout = 90
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "*")
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
