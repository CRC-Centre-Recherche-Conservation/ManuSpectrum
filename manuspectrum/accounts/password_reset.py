"""The page a password-reset link opens.

Overrides the core route `reset/<uidb64>/<token>/` (`password_reset_confirm`,
`arches/urls.py`, Arches 8.1.5), which Arches answers with
`arches.app.views.auth.PasswordResetConfirmView` (Django's view with
`ArchesSetPasswordForm`). Core moves a valid token into the session on the GET
of the link and redirects to `.../set-password/`; clicked from a webmail, that
redirect reaches the form without the `SameSite=Strict` session cookie
(see `mailed_links`).

The only difference: a valid token on a GET answers a « Continue » page, and
its post moves the token into the session (`mailed_links.land`), under the
session key and to the URL Django's view reads back. Every other behaviour is
core's: the placeholder URL, the form, the templates and the invalid-link page.
Re-check this module against `PasswordResetConfirmView` at each Arches upgrade.
"""

from arches.app.views.auth import (
    PasswordResetConfirmView as ArchesPasswordResetConfirmView,
)
from django.contrib.auth.views import INTERNAL_RESET_SESSION_TOKEN
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from manuspectrum.accounts.mailed_links import land


@method_decorator(never_cache, name="dispatch")
class PasswordResetConfirmView(ArchesPasswordResetConfirmView):
    """Arches' password-reset form, reached through a « Continue » page."""

    def dispatch(self, request, *args, **kwargs):
        response = self._dispatch(request, *args, **kwargs)
        response["Referrer-Policy"] = "same-origin"
        return response

    def _dispatch(self, request, *args, **kwargs):
        uidb64, token = kwargs.get("uidb64"), kwargs.get("token")
        if token != self.reset_url_token:
            user = self.get_user(uidb64)
            if user is not None and self.token_generator.check_token(user, token):
                return land(
                    request,
                    token=token,
                    session_key=INTERNAL_RESET_SESSION_TOKEN,
                    target=reverse(
                        "password_reset_confirm",
                        kwargs={"uidb64": uidb64, "token": self.reset_url_token},
                    ),
                    template_name="registration/password_reset_continue.html",
                )
        return super().dispatch(request, *args, **kwargs)
