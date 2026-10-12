"""Account activation and acceptance of the terms of use.

An administrator creates an account with no password and sends the invitation
(`send_invitation`). The mail carries a link built like Django's password
reset: `urlsafe_base64_encode(pk)` and a `default_token_generator` token, valid
for `PASSWORD_RESET_TIMEOUT` and dead once the password is set. The link opens
`ActivateAccountView`: a valid token is moved into the session and the browser
is redirected to the same route with the placeholder `set-password`, so the
token is in no page URL, `Referer` or access-log line (Django's
`PasswordResetConfirmView` does the same). That page shows the terms, asks for
their acceptance and a password, signs the user in and sends them to the
two-factor enrolment page.

`TermsAcceptance` holds one row per user and version of the terms
(`accounts.terms.TERMS_VERSION`). `TermsAcceptanceMiddleware` sends a signed-in
user without a row for the current version to `AcceptTermsView` on their next
page navigation. The pages reuse the terms page (`views/pages/terms.htm`) as
their base template, so the text exists once.

Nothing here logs an address, a token or a link: log lines name the user id.
"""

import logging
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import redirect_to_login
from django.db import transaction
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes
from django.utils.http import (
    url_has_allowed_host_and_scheme,
    urlsafe_base64_decode,
    urlsafe_base64_encode,
)
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django_ratelimit.decorators import ratelimit

from manuspectrum.accounts import notices
from manuspectrum.accounts.terms import TERMS_VERSION
from manuspectrum.models import TermsAcceptance
from manuspectrum.views.legal_pages import LegalPageView

logger = logging.getLogger(__name__)

LOGIN_BACKEND = "django.contrib.auth.backends.ModelBackend"
SESSION_KEY = "ms_terms_accepted_version"
TOKEN_PLACEHOLDER = "set-password"
SESSION_TOKEN_KEY = "_ms_activation_token"


def can_be_invited(user):
    """True for an active account with an address and no usable password."""
    return (
        user.is_active
        and bool((user.email or "").strip())
        and not user.has_usable_password()
        and user.username != "anonymous"
    )


def activation_link(user):
    """The absolute, personal activation URL of *user* (never logged)."""
    with translation.override(settings.LANGUAGE_CODE):
        path = reverse(
            "account-activate",
            kwargs={
                "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
                "token": default_token_generator.make_token(user),
            },
        )
    return settings.PUBLIC_SERVER_ADDRESS.rstrip("/") + path


def send_invitation(user):
    """Mail the invitation to *user*; returns the mail outcome.

    Raises `ValueError` when *user* cannot be invited (see `can_be_invited`).
    """
    if not can_be_invited(user):
        raise ValueError("This account cannot be invited.")
    expires_on = (
        timezone.now() + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT)
    ).date()
    return notices.send_account_mail(
        user,
        "invitation",
        {"link": activation_link(user), "expires_on": expires_on},
    )


def user_for_link(uidb64, token):
    """The account an activation link is for, or None when it is not valid."""
    User = get_user_model()
    try:
        user = User.objects.get(pk=urlsafe_base64_decode(uidb64).decode())
    except (User.DoesNotExist, ValueError, TypeError, OverflowError, UnicodeError):
        return None
    if not user.is_active or user.has_usable_password() or user.username == "anonymous":
        return None
    if not default_token_generator.check_token(user, token):
        return None
    return user


def record_acceptance(user, request=None):
    """Store *user*'s acceptance of the current terms; idempotent."""
    TermsAcceptance.objects.get_or_create(user=user, version=TERMS_VERSION)
    if request is not None:
        request.session[SESSION_KEY] = TERMS_VERSION


def has_accepted(request):
    """True when the signed-in user accepted the current terms.

    The answer is kept in the session under the version it was read for, so a
    new version asks again.
    """
    if request.session.get(SESSION_KEY) == TERMS_VERSION:
        return True
    if TermsAcceptance.objects.filter(
        user_id=request.user.pk, version=TERMS_VERSION
    ).exists():
        request.session[SESSION_KEY] = TERMS_VERSION
        return True
    return False


def safe_next(request, value):
    """*value* when it is a local URL, else the site root."""
    if value and url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return value
    return reverse("root")


def is_real_user(user):
    return user.is_authenticated and user.username != "anonymous"


class _TermsPage(LegalPageView):
    """The terms page with a form under it."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["robots_noindex"] = True
        return context

    def refuse(self, request, **extra):
        status = extra.pop("status", 400)
        context = self.get_context_data(**extra)
        return self.render_to_response(context, status=status)


@method_decorator(never_cache, name="dispatch")
class ActivateAccountView(_TermsPage):
    """Terms, acceptance and first password, behind the personal link."""

    template_name = "accounts/activate.htm"

    def dispatch(self, request, *args, **kwargs):
        response = self._dispatch(request, *args, **kwargs)
        response["Referrer-Policy"] = "no-referrer"
        return response

    def _dispatch(self, request, *args, **kwargs):
        uidb64, token = kwargs["uidb64"], kwargs["token"]
        if token == TOKEN_PLACEHOLDER:
            token = request.session.get(SESSION_TOKEN_KEY, "")
        elif user_for_link(uidb64, token) is not None:
            request.session[SESSION_TOKEN_KEY] = token
            return redirect("account-activate", uidb64=uidb64, token=TOKEN_PLACEHOLDER)
        self.account = user_for_link(uidb64, token) if token else None
        if self.account is None:
            self.template_name = "accounts/activation_invalid.htm"
            return self.render_to_response(self.get_context_data(), status=410)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        return self.render_to_response(
            self.get_context_data(form=SetPasswordForm(self.account))
        )

    @method_decorator(
        ratelimit(key="ip", rate=settings.RATE_LIMIT, method="POST", block=False)
    )
    def post(self, request, *args, **kwargs):
        if getattr(request, "limited", False):
            return self.refuse(
                request,
                form=SetPasswordForm(self.account),
                error=_("Too many attempts. Wait a minute."),
                status=429,
            )
        form = SetPasswordForm(self.account, request.POST)
        accepted = request.POST.get("accept_terms") == "on"
        if not accepted:
            form.is_valid()
            return self.refuse(
                request,
                form=form,
                error=_("You must accept the terms of use to activate your account."),
            )
        if not form.is_valid():
            return self.refuse(request, form=form)
        with transaction.atomic():
            user = form.save()
            record_acceptance(user)
        # Arches' `user_logged_in` receiver reads `user.backend`, which only
        # `authenticate()` sets.
        user.backend = LOGIN_BACKEND
        login(request, user)
        request.session.pop(SESSION_TOKEN_KEY, None)
        request.session[SESSION_KEY] = TERMS_VERSION
        logger.info("Account activated for user %s", user.pk)
        return redirect("account-two-factor")


@method_decorator(never_cache, name="dispatch")
class AcceptTermsView(_TermsPage):
    """The terms of use and the box to accept them, for a signed-in user."""

    template_name = "accounts/terms_accept.htm"

    def dispatch(self, request, *args, **kwargs):
        if not is_real_user(request.user):
            return redirect_to_login(request.get_full_path())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["next"] = safe_next(
            self.request, self.request.POST.get("next") or self.request.GET.get("next")
        )
        return context

    def get(self, request, *args, **kwargs):
        if has_accepted(request):
            return HttpResponseRedirect(safe_next(request, request.GET.get("next")))
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if request.POST.get("accept_terms") != "on":
            return self.refuse(
                request,
                error=_("You must accept the terms of use to continue."),
            )
        record_acceptance(request.user, request)
        logger.info("Terms %s accepted by user %s", TERMS_VERSION, request.user.pk)
        return HttpResponseRedirect(safe_next(request, request.POST.get("next")))


class TermsAcceptanceMiddleware:
    """Send a signed-in user who has not accepted the current terms to the accept page.

    Placed after authentication. Only page navigations are redirected: a GET
    whose `Accept` header asks for HTML and that is not an XHR. Never touched:
    anonymous visitors, other methods, `/api/` and `/iiif/` paths, static and
    media files, the monitoring endpoints, and the routes in `EXEMPT_ROUTES`
    (sign-in, sign-out, password reset, the activation, acceptance, two-factor
    and two-factor re-enrolment pages). The answer is read from the session, then the database,
    for the request that needs it only.
    """

    EXEMPT_ROUTES = frozenset(
        {
            "account-terms",
            "account-activate",
            "account-two-factor",
            "account-two-factor-reset",
            "auth",
            "two-factor-authentication-login",
            "password_reset",
            "password_reset_confirm",
            "admin:logout",
        }
    )
    EXEMPT_PREFIXES = ("/iiif/", "/healthz", "/readyz", "/metrics")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not self.applies(request):
            return None
        match = request.resolver_match
        if match is not None and match.view_name in self.EXEMPT_ROUTES:
            return None
        if has_accepted(request):
            return None
        return HttpResponseRedirect(
            reverse("account-terms")
            + "?next="
            + quote(request.get_full_path(), safe="/")
        )

    def applies(self, request):
        if request.method != "GET" or not is_real_user(request.user):
            return False
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return False
        if "text/html" not in request.headers.get("accept", ""):
            return False
        path = request.path
        if "/api/" in path or path.startswith(self.EXEMPT_PREFIXES):
            return False
        for base in (settings.STATIC_URL, settings.MEDIA_URL):
            if base and path.startswith(base):
                return False
        return not path.startswith(("/files/", "/uploadedfiles/")) and (
            "/files/" not in path
        )
