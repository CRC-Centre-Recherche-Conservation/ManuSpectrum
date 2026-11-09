"""The page a password-reset link opens.

Arches answers `reset/<uidb64>/<token>/` (`password_reset_confirm`) with its
own subclass of Django's `PasswordResetConfirmView`, which moves a valid token
into the session on the GET of the link and redirects to `.../set-password/`.
Clicked in a webmail or a mail client, that redirect reaches the form without
the `SameSite=Strict` session cookie, so the link was refused (#280, see
`mailed_links`).

`PasswordResetConfirmView` answers the link with a « Continue » page instead
and moves the token into the session on its post (`mailed_links.land`), under
the session key and to the URL Django's view reads back. Everything else is
Arches' view unchanged: the placeholder URL, the form (`ArchesSetPasswordForm`),
the templates and the invalid-link page.
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
