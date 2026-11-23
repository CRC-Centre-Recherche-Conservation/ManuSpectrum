"""The page a password-reset link opens.

Overrides the core route `reset/<uidb64>/<token>/` (`password_reset_confirm`,
`arches/urls.py`), which Arches 8.2.0 answers with
`arches.app.views.auth.PasswordResetConfirmView` (Django's view with
`ArchesSetPasswordForm`). Core moves a valid token into the session on the GET
of the link and redirects to `.../set-password/`; clicked from a webmail, that
redirect reaches the form without the `SameSite=Strict` session cookie.

The difference is where the token waits (`mailed_links` describes the flow). A
valid token on a GET sets a short-lived `SameSite=Lax` cookie and redirects to
the placeholder URL. There, the token of the cookie is placed in the session
under the key Django's view reads, for this request only, and the session
never keeps it. The answer renews the cookie while the form is shown and
deletes it on success and on an invalid link. Every other behaviour is core's:
the form, the templates and the invalid-link page.

This depends on Django 5.2's `django.contrib.auth.views.PasswordResetConfirmView`:
`INTERNAL_RESET_SESSION_TOKEN` read in `dispatch`, deleted in `form_valid`,
and the `validlink` and `reset_url_token` attributes. Re-check this module
against it at each Django or Arches upgrade.
"""

from arches.app.views.auth import (
    PasswordResetConfirmView as ArchesPasswordResetConfirmView,
)
from django.contrib.auth.views import INTERNAL_RESET_SESSION_TOKEN
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from manuspectrum.accounts.mailed_links import MailedLink

LINK = MailedLink(
    cookie="ms_reset_link", route="password_reset_confirm", placeholder="set-password"
)


@method_decorator(never_cache, name="dispatch")
class PasswordResetConfirmView(ArchesPasswordResetConfirmView):
    """Arches' password-reset form, its token carried by a cookie."""

    def dispatch(self, request, *args, **kwargs):
        response = self._dispatch(request, *args, **kwargs)
        response["Referrer-Policy"] = "same-origin"
        return response

    def form_valid(self, form):
        self.done = True
        return super().form_valid(form)

    def _dispatch(self, request, *args, **kwargs):
        """Answer the link, or the form its cookie opens.

        The session key core reads is lent for this request only: set from
        the cookie (removed when the cookie gives nothing) before core's
        `dispatch`, removed after it.
        """
        uidb64, token = kwargs.get("uidb64"), kwargs.get("token")
        if token != self.reset_url_token:
            user = self.get_user(uidb64)
            if user is not None and self.token_generator.check_token(user, token):
                return LINK.land(request, token, uidb64=uidb64)
            response = super().dispatch(request, *args, **kwargs)
            LINK.forget(response, uidb64=uidb64)
            return response
        token = LINK.token(request)
        session = request.session
        if token:
            session[INTERNAL_RESET_SESSION_TOKEN] = token
        else:
            session.pop(INTERNAL_RESET_SESSION_TOKEN, None)
        self.done = False
        try:
            response = super().dispatch(request, *args, **kwargs)
        finally:
            session.pop(INTERNAL_RESET_SESSION_TOKEN, None)
        if self.done or not self.validlink:
            LINK.forget(response, uidb64=uidb64)
        else:
            LINK.remember(response, token, uidb64=uidb64)
        return response
