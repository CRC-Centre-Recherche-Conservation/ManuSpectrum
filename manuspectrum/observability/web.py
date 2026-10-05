"""Signal receivers of the web process: requests in flight (and logins, Task 7).

``request_finished`` is sent when the response is closed, after the last byte of a
streamed body: an export counts as in flight until it is sent.
"""

from django.core.signals import request_finished, request_started

from manuspectrum.observability import metrics


def request_started_handler(sender, **kwargs):
    metrics.INFLIGHT_REQUESTS.inc()


def request_finished_handler(sender, **kwargs):
    metrics.INFLIGHT_REQUESTS.dec()


def connect():
    request_started.connect(request_started_handler, dispatch_uid="ms-inflight-start")
    request_finished.connect(request_finished_handler, dispatch_uid="ms-inflight-end")
