"""Celery side of observability: the request id follows a task from its publisher
to the worker that runs it (message header ``ms_request_id``)."""

from celery.signals import before_task_publish, task_postrun, task_prerun

from manuspectrum.observability.context import (
    current_request_id,
    request_id_var,
    safe_request_id,
)

HEADER = "ms_request_id"
_running = {}


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
    _running[task_id] = token


@task_postrun.connect(weak=False, dispatch_uid="ms-task-postrun")
def unbind_task(task_id=None, task=None, state=None, **kwargs):
    token = _running.pop(task_id, None)
    if token is not None:
        request_id_var.reset(token)
