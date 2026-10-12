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
"""

import base64
import io
import logging

import pyotp
import qrcode
from arches.app.models.models import UserProfile
from arches.app.utils.arches_crypto import AESCipher
from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.cache import never_cache
from django_ratelimit.decorators import ratelimit

logger = logging.getLogger(__name__)

PENDING_KEY = "ms_pending_mfa_secret"


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
        profile.encrypted_mfa_hash = encrypt_secret(secret)
        profile.save(update_fields=["encrypted_mfa_hash"])
        request.session.pop(PENDING_KEY, None)
        logger.info("Two-factor authenticator enrolled for user %s", request.user.pk)
        return self.render(request, done=_("Two-factor authentication is on."))

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

    def render(self, request, error=None, done=None, status=200):
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
        }
        return render(request, "accounts/two_factor.htm", context, status=status)
