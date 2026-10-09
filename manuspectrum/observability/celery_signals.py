"""Celery side of observability.

The request id follows a task from its publisher to the worker (message header
``ms_request_id``). Each task run is counted by name and outcome and timed
(``manuspectrum_celery_tasks_total``, ``manuspectrum_celery_task_seconds``). A
worker whose environment sets ``MS_CELERY_METRICS_PORT`` and
``PROMETHEUS_MULTIPROC_DIR`` serves the metrics of all its processes on that port
from its main process; a child that exits has its metric files archived (``multiproc``).
"""

import logging
import os
import time

from celery.signals import (
    before_task_publish,
    task_postrun,
    task_prerun,
    worker_process_shutdown,
    worker_ready,
)

from manuspectrum.observability import metrics
from manuspectrum.observability.context import (
    current_request_id,
    request_id_var,
    safe_request_id,
)

HEADER = "ms_request_id"
_STATES = {"SUCCESS": "success", "FAILURE": "failure", "RETRY": "retry"}
_running = {}
logger = logging.getLogger(__name__)


def _header(task):
    request = getattr(task, "request", None)
    value = getattr(request, HEADER, None)
    if value is None:
        value = (getattr(request, "headers", None) or {}).get(HEADER)
    return safe_request_id(value)


@before_task_publish.connect(weak=False, dispatch_uid="ms-request-id-publish")
def add_request_id(sender=None, headers=None, **kwargs):
    request_id = current_request_id()
    if request_id and headers is not None:
        headers[HEADER] = request_id


@task_prerun.connect(weak=False, dispatch_uid="ms-task-prerun")
def bind_task(task_id=None, task=None, **kwargs):
    request_id = _header(task)
    token = request_id_var.set(request_id) if request_id else None
    _running[task_id] = (token, time.monotonic())


@task_postrun.connect(weak=False, dispatch_uid="ms-task-postrun")
def unbind_task(task_id=None, task=None, state=None, **kwargs):
    token, started = _running.pop(task_id, (None, None))
    if token is not None:
        request_id_var.reset(token)
    name = metrics.task_label(getattr(task, "name", None))
    metrics.CELERY_TASKS.labels(
        task=name, outcome=_STATES.get(state, metrics.OTHER)
    ).inc()
    if started is not None:
        metrics.CELERY_TASK_SECONDS.labels(task=name).observe(
            time.monotonic() - started
        )


@worker_ready.connect(weak=False, dispatch_uid="ms-worker-metrics")
def serve_worker_metrics(**kwargs):
    port = os.environ.get("MS_CELERY_METRICS_PORT")
    if not port or not os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        return
    from prometheus_client import CollectorRegistry, start_http_server

    from manuspectrum.observability.multiproc import ArchiveSafeCollector

    registry = CollectorRegistry()
    ArchiveSafeCollector(registry)
    start_http_server(int(port), addr="0.0.0.0", registry=registry)


@worker_ready.connect(weak=False, dispatch_uid="ms-ledger-gauges")
def record_ledger_gauges(**kwargs):
    """Set the ``manuspectrum_data_change_*`` gauges when the worker starts.

    The row count is read from the ledger; the prune time is the start time, the
    reference the 26 h staleness alert counts from until the daily prune
    records its own. A database error is logged and never stops the worker.
    """
    from django.db import connection, connections

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM ms_data_change")
            metrics.DATA_CHANGE_ROWS.set(cursor.fetchone()[0])
        metrics.DATA_CHANGE_PRUNED.set(time.time())
    except Exception:
        logger.warning("ledger gauges not set at worker start", exc_info=True)
    finally:
        connections.close_all()


@worker_ready.connect(weak=False, dispatch_uid="ms-active-accounts-gauge")
def record_active_accounts_gauge(**kwargs):
    """Set ``manuspectrum_active_accounts`` when the worker starts.

    A database error is logged and never stops the worker.
    """
    from django.db import connections

    from manuspectrum.tasks import publish_active_accounts

    try:
        publish_active_accounts()
    except Exception:
        logger.warning("active accounts gauge not set at worker start", exc_info=True)
    finally:
        connections.close_all()


@worker_process_shutdown.connect(weak=False, dispatch_uid="ms-worker-child-exit")
def forget_child(pid=None, **kwargs):
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from manuspectrum.observability import multiproc

        try:
            multiproc.archive_dead_process(pid or os.getpid())
        except Exception as error:
            logger.error(
                "metrics archive failed for pid %s: %s",
                pid or os.getpid(),
                type(error).__name__,
            )
