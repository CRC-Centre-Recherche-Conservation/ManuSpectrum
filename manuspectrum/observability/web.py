"""Signal receivers of the web process: requests in flight and login attempts.

``request_finished`` is sent when the response is closed, after the last byte of a
streamed body: an export counts as in flight until it is sent.
"""

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.signals import request_finished, request_started

from manuspectrum.observability import metrics


def request_started_handler(sender, **kwargs):
    metrics.INFLIGHT_REQUESTS.inc()


def request_finished_handler(sender, **kwargs):
    metrics.INFLIGHT_REQUESTS.dec()


def login_succeeded_handler(sender, **kwargs):
    metrics.AUTH_LOGINS.labels(outcome="success").inc()


def login_failed_handler(sender, **kwargs):
    metrics.AUTH_LOGINS.labels(outcome="failure").inc()


def connect():
    request_started.connect(request_started_handler, dispatch_uid="ms-inflight-start")
    request_finished.connect(request_finished_handler, dispatch_uid="ms-inflight-end")
    user_logged_in.connect(login_succeeded_handler, dispatch_uid="ms-login-ok")
    user_login_failed.connect(login_failed_handler, dispatch_uid="ms-login-failed")
