"""Two-factor enrolment: a TOTP authenticator, set up by the signed-in user.

Arches stores a user's TOTP secret in `UserProfile.encrypted_mfa_hash`, AES
encrypted with `SECRET_KEY`, and checks it at its two-factor sign-in step
(`TwoFactorAuthenticationLoginView`, arches 8.1.5). Its own settings and reset
pages are refused at the edge, so enrolment lives here: the page acts on
`request.user` only.

A secret is generated, shown as a QR code and a manual key, and written to the
profile only once the user has typed one valid code from it; until then it
waits, encrypted, in the session. An enrolled user must give a current code to
replace or remove the secret. Removing is refused when
`FORCE_TWO_FACTOR_AUTHENTICATION` is on.

The page that confirms a first enrolment (the end of the account activation)
offers a « Continue » button to the home page.

With `FORCE_TWO_FACTOR_AUTHENTICATION` on, `RequireTwoFactorMiddleware` keeps a
signed-in user without a secret on the enrolment page. A user whose secret was
cleared by an administrator (lost device, new `SECRET_KEY`) cannot sign in to
get there, so the reset mails a personal link (`TwoFactorResetView`): a signed
token bound to the password hash and to the empty secret, so it dies with the
first enrolment or any password change. The token moves to the session and the
browser is redirected to the same route with the placeholder `enrol`, as in
`ActivateAccountView`. The user types the password (counted by django-axes like
a sign-in), enrols with a valid code and is signed in.
"""

import base64
import hmac
import io
import logging
from datetime import timedelta

import pyotp
import qrcode
from arches.app.models.models import UserProfile
from arches.app.utils.arches_crypto import AESCipher
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.views import redirect_to_login
from django.core import signing
from django.http import Http404, HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.crypto import salted_hmac
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.cache import never_cache
from django_ratelimit.decorators import ratelimit

from manuspectrum.accounts import notices
from manuspectrum.accounts.activation import (
    LOGIN_BACKEND,
    is_real_user,
)

logger = logging.getLogger(__name__)

PENDING_KEY = "ms_pending_mfa_secret"

RESET_SALT = "manuspectrum.two-factor-reset"
RESET_MAX_AGE = 24 * 3600
RESET_PLACEHOLDER = "enrol"
RESET_TOKEN_KEY = "_ms_two_factor_reset_token"
RESET_VERIFIED_KEY = "_ms_two_factor_reset_verified"
RESET_PENDING_KEY = "ms_reset_pending_mfa_secret"


def encrypt_secret(secret):
    """The stored form of *secret*, as Arches writes it.

    Arches assigns the AES output (bytes) to the character field, which keeps
    its `repr`; its reader drops the leading `b`. Both are reproduced so the
    Arches sign-in step reads what is stored here.
    """
    return str(AESCipher(settings.SECRET_KEY).encrypt(secret))


def decrypt_secret(stored):
    """The TOTP secret held in *stored*, or None when nothing is stored."""
    if not stored:
        return None
    return AESCipher(settings.SECRET_KEY).decrypt(stored[1:])


def code_matches(secret, code):
    """True when *code* is the current code of *secret*."""
    code = (code or "").strip().replace(" ", "")
    return bool(secret) and code.isdigit() and pyotp.TOTP(secret).verify(code)


def qr_data_uri(secret, account):
    """A PNG data URI of the provisioning QR code of *secret*."""
    uri = pyotp.TOTP(secret).provisioning_uri(account, issuer_name=settings.APP_TITLE)
    buffer = io.BytesIO()
    qrcode.make(uri).save(buffer)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


@method_decorator(never_cache, name="dispatch")
class TwoFactorSetupView(View):
    """Enrol, replace or remove the signed-in user's authenticator.

    Arches' `SetAnonymousUser` gives every visitor the real `anonymous` account,
    which is authenticated for Django: it is turned away like a signed-out
    visitor.
    """

    def dispatch(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated or user.username == "anonymous":
            return redirect_to_login(request.get_full_path())
        if not settings.ENABLE_TWO_FACTOR_AUTHENTICATION:
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        return self.render(request)

    @method_decorator(
        ratelimit(key="user", rate=settings.RATE_LIMIT, method="POST", block=False)
    )
    def post(self, request):
        if getattr(request, "limited", False):
            return self.render(
                request, error=_("Too many attempts. Wait a minute."), status=429
            )
        profile, _created = UserProfile.objects.get_or_create(user=request.user)
        enrolled = bool(profile.encrypted_mfa_hash)
        action = request.POST.get("action")
        code = request.POST.get("code")

        if action == "confirm":
            return self.confirm(request, profile, code)
        if action in ("start", "remove"):
            if enrolled and not code_matches(
                decrypt_secret(profile.encrypted_mfa_hash), code
            ):
                return self.render(
                    request,
                    error=_(
                        "The code is not valid. Enter the current code of your authenticator."
                    ),
                    status=400,
                )
            if action == "start":
                return self.start(request)
            return self.remove(request, profile)
        if action == "cancel":
            request.session.pop(PENDING_KEY, None)
        return redirect(request.path)

    def start(self, request):
        secret = pyotp.random_base32()
        request.session[PENDING_KEY] = encrypt_secret(secret)
        return self.render(request)

    def confirm(self, request, profile, code):
        secret = decrypt_secret(request.session.get(PENDING_KEY))
        if not secret:
            return redirect(request.path)
        if not code_matches(secret, code):
            return self.render(
                request,
                error=_("The code is not valid. Check the code and try again."),
                status=400,
            )
        first = not profile.encrypted_mfa_hash
        profile.encrypted_mfa_hash = encrypt_secret(secret)
        profile.save(update_fields=["encrypted_mfa_hash"])
        request.session.pop(PENDING_KEY, None)
        logger.info("Two-factor authenticator enrolled for user %s", request.user.pk)
        return self.render(
            request, done=_("Two-factor authentication is on."), first=first
        )

    def remove(self, request, profile):
        if settings.FORCE_TWO_FACTOR_AUTHENTICATION:
            return self.render(
                request,
                error=_(
                    "Two-factor authentication is compulsory and cannot be removed."
                ),
                status=403,
            )
        profile.encrypted_mfa_hash = None
        profile.save(update_fields=["encrypted_mfa_hash"])
        request.session.pop(PENDING_KEY, None)
        logger.info("Two-factor authenticator removed for user %s", request.user.pk)
        return self.render(request, done=_("Two-factor authentication is off."))

    def render(self, request, error=None, done=None, status=200, first=False):
        profile = UserProfile.objects.filter(user=request.user).first()
        pending = decrypt_secret(request.session.get(PENDING_KEY))
        context = {
            "enrolled": bool(profile and profile.encrypted_mfa_hash),
            "forced": settings.FORCE_TWO_FACTOR_AUTHENTICATION,
            "pending_secret": pending,
            "qr_data_uri": (
                qr_data_uri(pending, request.user.email or request.user.username)
                if pending
                else None
            ),
            "app_title": settings.APP_TITLE,
            "error": error,
            "done": done,
            "first_enrolment": first,
        }
        return render(request, "accounts/two_factor.htm", context, status=status)


def _reset_state(user, stored_secret):
    last_login = user.last_login.isoformat() if user.last_login else ""
    return salted_hmac(
        RESET_SALT,
        f"{user.pk}|{user.password}|{stored_secret or ''}|{last_login}",
    ).hexdigest()


def reset_token(user):
    """A signed enrolment token for *user*.

    Valid while the password, the empty secret and the last sign-in stay as
    they were: a link mailed before the account signed in again (a completed
    re-enrolment signs it in) is dead even if the secret is cleared again.
    """
    user = get_user_model().objects.get(pk=user.pk)
    profile = UserProfile.objects.filter(user=user).first()
    return signing.dumps(
        {
            "u": user.pk,
            "s": _reset_state(user, profile.encrypted_mfa_hash if profile else None),
        },
        salt=RESET_SALT,
    )


def user_for_reset(token):
    """The account a re-enrolment token is for, or None when it is not valid."""
    try:
        data = signing.loads(token, salt=RESET_SALT, max_age=RESET_MAX_AGE)
        user = (
            get_user_model()
            .objects.filter(pk=data["u"], is_active=True)
            .exclude(username="anonymous")
            .first()
        )
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None
    if user is None:
        return None
    profile = UserProfile.objects.filter(user=user).first()
    stored = profile.encrypted_mfa_hash if profile else None
    if stored or not hmac.compare_digest(data.get("s", ""), _reset_state(user, stored)):
        return None
    return user


def reset_link(user, language=None, token=None):
    """The absolute, personal re-enrolment URL of *user* in *language* (never logged).

    *language* defaults to `LANGUAGE_CODE`; *token* to a fresh `reset_token`.
    """
    token = token or reset_token(user)
    with translation.override(language or settings.LANGUAGE_CODE):
        path = reverse("account-two-factor-reset", kwargs={"token": token})
    return settings.PUBLIC_SERVER_ADDRESS.rstrip("/") + path


def send_reset_link(user):
    """Mail *user* the re-enrolment link; returns the mail outcome."""
    expires_on = (timezone.now() + timedelta(seconds=RESET_MAX_AGE)).date()
    token = reset_token(user)
    return notices.send_account_mail(
        user,
        "two_factor_reset",
        {
            "link": {code: reset_link(user, code, token) for code in notices.LANGUAGES},
            "expires_on": expires_on,
        },
    )


@method_decorator(never_cache, name="dispatch")
class TwoFactorResetView(View):
    """Password, then a new authenticator, behind the personal link of a reset."""

    def dispatch(self, request, *args, **kwargs):
        response = self._dispatch(request, *args, **kwargs)
        response["Referrer-Policy"] = "same-origin"
        return response

    def _dispatch(self, request, *args, **kwargs):
        if not settings.ENABLE_TWO_FACTOR_AUTHENTICATION:
            raise Http404
        token = kwargs["token"]
        if token == RESET_PLACEHOLDER:
            token = request.session.get(RESET_TOKEN_KEY, "")
        elif user_for_reset(token) is not None:
            request.session[RESET_TOKEN_KEY] = token
            return redirect("account-two-factor-reset", token=RESET_PLACEHOLDER)
        self.account = user_for_reset(token) if token else None
        if self.account is None:
            return render(request, "accounts/two_factor_reset_invalid.htm", status=410)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, token):
        return self.render(request)

    @method_decorator(
        ratelimit(key="ip", rate=settings.RATE_LIMIT, method="POST", block=False)
    )
    def post(self, request, token):
        if getattr(request, "limited", False):
            return self.render(
                request, error=_("Too many attempts. Wait a minute."), status=429
            )
        action = request.POST.get("action")
        if action == "password":
            return self.check_password(request)
        if action == "confirm":
            return self.confirm(request)
        if action == "cancel":
            self.forget(request)
        return redirect(request.path)

    def verified(self, request):
        return request.session.get(RESET_VERIFIED_KEY) == self.account.pk

    def forget(self, request):
        for key in (RESET_VERIFIED_KEY, RESET_PENDING_KEY):
            request.session.pop(key, None)

    def check_password(self, request):
        user = authenticate(
            request=request,
            username=self.account.get_username(),
            password=request.POST.get("password") or "",
        )
        if user is None or user.pk != self.account.pk:
            return self.render(
                request, error=_("The password is not valid."), status=400
            )
        request.session[RESET_VERIFIED_KEY] = user.pk
        request.session[RESET_PENDING_KEY] = encrypt_secret(pyotp.random_base32())
        return self.render(request)

    def confirm(self, request):
        secret = decrypt_secret(request.session.get(RESET_PENDING_KEY))
        if not self.verified(request) or not secret:
            return redirect(request.path)
        if not code_matches(secret, request.POST.get("code")):
            return self.render(
                request,
                error=_("The code is not valid. Check the code and try again."),
                status=400,
            )
        profile, _created = UserProfile.objects.get_or_create(user=self.account)
        profile.encrypted_mfa_hash = encrypt_secret(secret)
        profile.save(update_fields=["encrypted_mfa_hash"])
        self.forget(request)
        request.session.pop(RESET_TOKEN_KEY, None)
        self.account.backend = LOGIN_BACKEND
        login(request, self.account)
        logger.info("Two-factor authenticator re-enrolled for user %s", self.account.pk)
        return redirect("account-two-factor")

    def render(self, request, error=None, status=200):
        pending = (
            decrypt_secret(request.session.get(RESET_PENDING_KEY))
            if self.verified(request)
            else None
        )
        context = {
            "pending_secret": pending,
            "qr_data_uri": (
                qr_data_uri(pending, self.account.email or self.account.username)
                if pending
                else None
            ),
            "error": error,
        }
        return render(request, "accounts/two_factor_reset.htm", context, status=status)


class RequireTwoFactorMiddleware:
    """Keep a signed-in user without an authenticator on the enrolment page.

    Active only when `FORCE_TWO_FACTOR_AUTHENTICATION` is on. Placed after
    authentication. A signed-in user (the `anonymous` visitor excepted) whose
    profile holds no secret is redirected to `account/two-factor` on a page
    navigation (a GET asking for HTML, not an XHR) and gets a 403 on any other
    request. Never touched: static and media files, the monitoring endpoints and
    the routes in `EXEMPT_ROUTES` (enrolment and its re-enrolment link, the
    terms, sign-in and sign-out, password reset, activation). The secret is read
    from the database on every request of such a user, so a reset by an
    administrator applies to the sessions that are open.
    """

    EXEMPT_ROUTES = frozenset(
        {
            "account-two-factor",
            "account-two-factor-reset",
            "account-terms",
            "account-activate",
            "auth",
            "two-factor-authentication-login",
            "password_reset",
            "password_reset_confirm",
            "admin:logout",
        }
    )
    EXEMPT_PREFIXES = ("/healthz", "/readyz", "/metrics")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not settings.FORCE_TWO_FACTOR_AUTHENTICATION:
            return None
        if not is_real_user(request.user) or self.exempt(request):
            return None
        if (
            UserProfile.objects.filter(user_id=request.user.pk)
            .exclude(encrypted_mfa_hash__isnull=True)
            .exclude(encrypted_mfa_hash="")
            .exists()
        ):
            return None
        if self.is_navigation(request):
            return HttpResponseRedirect(reverse("account-two-factor"))
        return HttpResponseForbidden("Two-factor authentication is required.")

    def exempt(self, request):
        match = request.resolver_match
        if match is not None and match.view_name in self.EXEMPT_ROUTES:
            return True
        path = request.path
        if path.startswith(self.EXEMPT_PREFIXES):
            return True
        return any(
            base and path.startswith(base)
            for base in (settings.STATIC_URL, settings.MEDIA_URL)
        )

    def is_navigation(self, request):
        return (
            request.method == "GET"
            and request.headers.get("x-requested-with") != "XMLHttpRequest"
            and "text/html" in request.headers.get("accept", "")
            and "/api/" not in request.path
        )
