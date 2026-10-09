"""Logging of the container image: one line per record on stdout, JSON by default.

``build_logging()`` returns the ``LOGGING`` dict ``settings_docker`` uses. Every
record carries the request id (``RequestIdFilter``). The formatters redact
secrets and personal data whatever the logger: values of keys that name a
password, token, cookie, session, CSRF value, API key or credential; in text,
``Authorization`` values, IIIF tokens (``msiiif1.``), ``password=``-style query
values, URL credentials and e-mail addresses. ``LogRecordCounter`` counts
records at WARNING and above into ``manuspectrum_log_records_total``.
"""

import datetime
import logging
import re
import socket

from pythonjsonlogger.core import RESERVED_ATTRS
from pythonjsonlogger.json import JsonFormatter as _JsonFormatter

from manuspectrum.observability.context import current_request_id

REDACTED = "[redacted]"
FORMATS = ("json", "text")

_SENSITIVE_KEY = re.compile(
    r"(?i)password|passwd|pwd|secret|token|authori[sz]ation|cookie|session|csrf"
    r"|api[_-]?key|credential"
)
_TEXT_RULES = (
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]{0,31}://)[^/\s:@]{0,256}:[^/\s@]{0,256}@"),
        r"\1" + REDACTED + "@",
    ),
    (
        re.compile(
            r"(?i)\b(authorization\s*[:=]\s*)(?:(?:bearer|basic|token)\s+)?[^\s,;]+"
        ),
        r"\1" + REDACTED,
    ),
    (re.compile(r"msiiif1\.[A-Za-z0-9._~+/=-]+"), REDACTED),
    (re.compile(r"(?i)\b(bearer\s+)[^\s,;\"']+"), r"\1" + REDACTED),
    (
        re.compile(
            r"(?i)([\"'](?:access_token|refresh_token|id_token|client_secret)[\"']\s*:\s*)"
            r"([\"'])[^\"']*\2"
        ),
        r"\1\2" + REDACTED + r"\2",
    ),
    (
        re.compile(
            r"(?i)\b((?:password|passwd|pwd|token|access_token|refresh_token|secret"
            r"|client_secret|api_?key|sessionid|csrftoken|csrfmiddlewaretoken"
            r"|code|key|sig|signature)=)[^&\s;,]+"
        ),
        r"\1" + REDACTED,
    ),
    (
        re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,255}\.[A-Za-z]{2,24}"),
        "[email]",
    ),
)
# Fields the formatter writes itself: their values are redacted as text, their keys never.
_OWN_FIELDS = frozenset(
    {
        "timestamp",
        "level",
        "logger",
        "message",
        "service",
        "environment",
        "version",
        "hostname",
        "request_id",
        "trace_id",
        "exc_info",
        "stack_info",
    }
)


def redact_text(text):
    for pattern, replacement in _TEXT_RULES:
        text = pattern.sub(replacement, text)
    return text


def redact(value, key=None):
    """*value* with secrets and e-mail addresses masked; everything under a sensitive *key* masked."""
    if key is not None and _SENSITIVE_KEY.search(str(key)):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if value is None or isinstance(
        value, (bool, int, float, datetime.date, datetime.time)
    ):
        return value
    if isinstance(value, BaseException):
        return redact_text(f"{type(value).__name__}: {value}")
    return redact_text(str(value))


def _request_id_of(record):
    request = getattr(record, "request", None)
    return current_request_id() or getattr(request, "request_id", "") or ""


class RequestIdFilter(logging.Filter):
    """Sets ``record.request_id``: the context's id, else the one of ``record.request``
    (``django.request`` logs after the middleware chain has returned)."""

    def filter(self, record):
        record.request_id = getattr(record, "request_id", "") or _request_id_of(record)
        return True


class JsonFormatter(_JsonFormatter):
    """One JSON object per record: ``timestamp`` (UTC, ISO 8601), ``level``, ``service``,
    ``message``, ``logger``, ``request_id``, ``trace_id`` (empty until tracing exists),
    ``environment``, ``version``, ``hostname``, then the record's extra fields, redacted.
    ``record.request`` (an ``HttpRequest``) is never written."""

    def __init__(self, *, environment="", version="", **kwargs):
        super().__init__(
            "%(levelname)s %(name)s %(message)s",
            rename_fields={"levelname": "level", "name": "logger"},
            static_fields={
                "service": "manuspectrum",
                "environment": environment,
                "version": version,
                "hostname": socket.gethostname(),
            },
            reserved_attrs=[*RESERVED_ATTRS, "request", "request_id", "trace_id"],
            timestamp=True,
            **kwargs,
        )

    def add_fields(self, log_data, record, message_dict):
        super().add_fields(log_data, record, message_dict)
        log_data["request_id"] = getattr(record, "request_id", "") or _request_id_of(
            record
        )
        log_data["trace_id"] = ""

    def process_log_record(self, log_data):
        return {
            key: redact(value, None if key in _OWN_FIELDS else key)
            for key, value in log_data.items()
        }


class TextFormatter(logging.Formatter):
    """``time level logger [request_id] message``, redacted."""

    def __init__(self, **kwargs):
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
        )

    def format(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = _request_id_of(record)
        return redact_text(super().format(record))


class LogRecordCounter(logging.Handler):
    """Counts records at its level and above into ``manuspectrum_log_records_total``."""

    def emit(self, record):
        try:
            from manuspectrum.observability import metrics

            metrics.LOG_RECORDS.labels(
                level=metrics.bounded(record.levelname.lower(), metrics.LOG_LEVELS),
                source=metrics.log_source(record.name),
            ).inc()
        except Exception:
            self.handleError(record)


def build_logging(fmt, *, environment, version):
    """The ``LOGGING`` dict of the image: *fmt* is ``json`` or ``text``.

    Root at WARNING; ``django``, ``arches``, ``manuspectrum`` and ``celery`` at
    INFO, ``django.request`` at WARNING, none propagating; no ``mail_admins``,
    no file.
    """
    if fmt not in FORMATS:
        raise ValueError(f"log format {fmt!r} is not one of {FORMATS}")
    formatter = (
        {
            "()": "manuspectrum.observability.logging.JsonFormatter",
            "environment": environment,
            "version": version,
        }
        if fmt == "json"
        else {"()": "manuspectrum.observability.logging.TextFormatter"}
    )
    both = ["console", "metrics"]
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "manuspectrum.observability.logging.RequestIdFilter"}
        },
        "formatters": {"main": formatter},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "main",
                "filters": ["request_id"],
                "stream": "ext://sys.stdout",
            },
            "metrics": {
                "class": "manuspectrum.observability.logging.LogRecordCounter",
                "level": "WARNING",
            },
        },
        "root": {"handlers": both, "level": "WARNING"},
        "loggers": {
            "django": {"handlers": both, "level": "INFO", "propagate": False},
            "django.request": {
                "handlers": both,
                "level": "WARNING",
                "propagate": False,
            },
            "arches": {"handlers": both, "level": "INFO", "propagate": False},
            "manuspectrum": {"handlers": both, "level": "INFO", "propagate": False},
            "celery": {"handlers": both, "level": "INFO", "propagate": False},
        },
    }
