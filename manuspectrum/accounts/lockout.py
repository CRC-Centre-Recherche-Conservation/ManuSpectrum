"""Sign-in lockout and login records, django-axes behind Arches' views.

Arches calls `django.contrib.auth.authenticate()` without a `request` in its
`LoginView`, `TwoFactorAuthenticationLoginView`, `UserProfileView`,
`GetClientIdView` and `ServerSettingView` (arches 8.1.5, `views/auth.py`).
django-axes needs the request: its backend raises `ValueError` without one and
its handler records nothing. `CurrentRequestMiddleware` keeps the request in a
`ContextVar` for the duration of the view, and the backend and the handler
below read it when `authenticate()` or the `user_login_failed` signal carry
none. A `ContextVar` is per thread (and per task), so concurrent gthread
requests never see each other's request.

The lock is keyed on the account and the client address (`AXES_LOCKOUT_PARAMETERS`);
the address is `manuspectrum.utils.client_ip.client_ip`. A user name or an e-mail
address typed at the form resolve to the same account (`lockout_username`).
Locked requests are answered by `axes.middleware.AxesMiddleware` with
`accounts/lockout.htm` (429).
"""

import logging
from contextvars import ContextVar
from datetime import timedelta

from axes.backends import AxesStandaloneBackend
from axes.handlers.database import AxesDatabaseHandler
from axes.handlers.proxy import AxesProxyHandler
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_login_failed
from django.shortcuts import render
from django.utils import timezone

from manuspectrum.observability import metrics

logger = logging.getLogger(__name__)

_current_request = ContextVar("manuspectrum_current_request", default=None)


def current_request():
    """The request of the view running in this thread, or None."""
    return _current_request.get()


class CurrentRequestMiddleware:
    """Expose the request being served to code that is called without it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_request.set(request)
        try:
            return self.get_response(request)
        finally:
            _current_request.reset(token)


class TwoFactorLoginMiddleware:
    """The lock and the error page around Arches' second-factor sign-in step.

    `TwoFactorAuthenticationLoginView` (arches 8.1.5, `views/auth.py`)
    re-checks the password with `authenticate()`, then the TOTP code, and
    answers 401 on a wrong code without telling the lockout. A 401 on that route
    after a correct password is therefore sent as a failed sign-in flagged
    `mfa`, which axes counts with the password failures and the metrics count
    as `mfa_failure`. When the password is wrong or the account is locked,
    `authenticate()` returns None and the view fails on `user.email`
    (`AttributeError`); that exception is answered here with the same 401 page,
    without the password field, and axes replaces it with the lockout page when
    the account is locked.
    """

    route = "two-factor-authentication-login"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            response.status_code == 401
            and self._is_second_factor_post(request)
            and not getattr(request, "_ms_mfa_error_page", False)
        ):
            username = lockout_username(request)
            if username:
                user_login_failed.send(
                    sender=__name__,
                    credentials={"username": username, "mfa": True},
                    request=request,
                )
        return response

    def process_exception(self, request, exception):
        if not (
            self._is_second_factor_post(request)
            and isinstance(exception, AttributeError)
        ):
            return None
        request._ms_mfa_error_page = True
        return render(
            request,
            "two_factor_authentication_login.htm",
            {
                "auth_failed": True,
                "next": request.POST.get("next", "/"),
                "username": request.POST.get("username", ""),
                "user_has_enabled_two_factor_authentication": request.POST.get(
                    "user-has-enabled-two-factor-authentication"
                ),
            },
            status=401,
        )

    def _is_second_factor_post(self, request):
        match = getattr(request, "resolver_match", None)
        return (
            request.method == "POST"
            and match is not None
            and match.url_name == self.route
        )


class ArchesAxesBackend(AxesStandaloneBackend):
    """The axes lock check, usable from calls that omit `request`.

    Without a request and outside a view (a shell, `Client.login()`) there is no
    client to lock and the backend steps aside, as it does for an attempt that
    names no account (Arches' `user_profile` calls `authenticate()` with no
    credentials for a signed-in session).
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        request = request or current_request()
        if request is None or not username:
            return None
        return super().authenticate(
            request, username=username, password=password, **kwargs
        )


class ArchesAxesHandler(AxesDatabaseHandler):
    """The database handler, fed with the current request and counting lockouts.

    `manuspectrum_auth_lockouts_total` counts the transition into the locked
    state; `user_locked_out` is also sent on every failure attempted while
    locked and is not used for counting.
    """

    def user_login_failed(self, sender, credentials, request=None, **kwargs):
        request = request or current_request()
        if request is None:
            logger.warning("A sign-in failure carried no request and was not recorded")
            return
        if not lockout_username(request, credentials):
            return
        AxesProxyHandler.update_request(request)
        was_locked = bool(request.axes_locked_out)
        super().user_login_failed(sender, credentials, request, **kwargs)
        if request.axes_locked_out and not was_locked:
            metrics.AUTH_LOCKOUTS.inc()


def lockout_username(request, credentials=None):
    """The account a sign-in attempt names, whether by user name or e-mail.

    A user name that exists wins; an e-mail address shared by one account only
    resolves to that account; anything else is the typed text, lower-cased.
    """
    typed = (credentials or {}).get("username")
    if typed is None and request is not None:
        typed = request.POST.get("username")
    if not typed:
        return None
    typed = str(typed).strip()
    users = get_user_model().objects
    match = users.filter(username__iexact=typed).values_list("username", flat=True)
    if match:
        return match[0]
    match = users.filter(email__iexact=typed).values_list("username", flat=True)[:2]
    if len(match) == 1:
        return match[0]
    return typed.lower()


def prune_login_records():
    """Delete login records older than `LOGIN_RECORDS_RETENTION_DAYS`.

    Covers the success log, the failure log (through the axes handler, as
    `axes_reset_logs` and `axes_reset_failure_logs` do) and the attempts left
    behind by an expired lock. Timestamps are `timezone.now()`, as axes writes
    them. Returns the number of rows deleted.
    """
    from axes.models import AccessAttempt

    days = settings.LOGIN_RECORDS_RETENTION_DAYS
    deleted = AxesProxyHandler.reset_logs(age_days=days)
    deleted += AxesProxyHandler.reset_failure_logs(age_days=days)
    limit = timezone.now() - timedelta(days=days)
    deleted += AccessAttempt.objects.filter(attempt_time__lte=limit).delete()[0]
    return deleted
