"""The request id of the current context: a request thread, a Celery task, or a
thread that bound it explicitly (``bound_request_id``)."""

import contextvars
import re
import uuid
from contextlib import contextmanager

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{7,127}")

request_id_var = contextvars.ContextVar("ms_request_id", default="")


def new_request_id():
    return uuid.uuid4().hex


def safe_request_id(value):
    """*value* when it is 8 to 128 of ``[A-Za-z0-9._-]`` starting alphanumeric, else ``""``."""
    if isinstance(value, str) and _SAFE_ID.fullmatch(value):
        return value
    return ""


def current_request_id():
    return request_id_var.get()


@contextmanager
def bound_request_id(value):
    """Run the block under request id *value* (kept only when safe), then restore the previous one."""
    token = request_id_var.set(safe_request_id(value))
    try:
        yield
    finally:
        request_id_var.reset(token)
