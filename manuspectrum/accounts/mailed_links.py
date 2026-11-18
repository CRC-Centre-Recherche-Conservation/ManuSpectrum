"""Personal links mailed to a user, and the cookie that carries their token.

Three mails carry a link with a token in its path: the invitation
(`activation.ActivateAccountView`), the two-factor re-enrolment
(`twofactor.TwoFactorResetView`) and the password reset
(`password_reset.PasswordResetConfirmView`). Each flow keeps the token out of
the URL of the page where a password is typed, so that URL and its `Referer`
carry none.

A GET of the link checks the token, sets a signed cookie holding it and
redirects at once to the same route with a placeholder in place of the token
(`MailedLink.land`). The page at the placeholder URL reads the token back from
the cookie (`MailedLink.token`) and checks it again, on GET and on POST.

The cookie is `HttpOnly`, `Secure` (as the session cookie), `SameSite=Lax`,
signed and timestamped, and valid for `COOKIE_MAX_AGE`: the server refuses an
older one whatever the browser kept, and every valid answer of the form renews
it. Its `Path` is the folder of the flow's routes, so the browser sends it to
no other page. There is one cookie per language, each on the path of its
language prefix, so the language switch of the header keeps the form working.
It is deleted when the form succeeds and when the token is refused.

`Lax` is what makes the flow work from a webmail or a mail client. The session
cookie is `SameSite=Strict` (`SESSION_COOKIE_SAMESITE`, set by Arches and
kept), and a browser sends no `Strict` cookie on any request of a redirect
chain that started on another site. A `Lax` cookie is sent on a top-level GET
navigation, and on the redirects that follow, even when the click came from
another site; it is never sent on a cross-site subrequest or POST. The form is
posted from a page of the site, so that POST is same-site: the CSRF check and
the `Strict` session work as on every other page.

A GET changes nothing and consumes nothing: a mail scanner that fetches the
link only gets a cookie and a redirect, and the link keeps working. The
password, the activation, the acceptance of the terms and the re-enrolment
change on the POST of the form only, and the token is single use (it is bound
to the password hash, or marked used). The views answer every step with
`Referrer-Policy: same-origin`.

A page of one of `ROUTES` repeats its own URL nowhere in its head
(`context_processors.personal_link`, read by `ms_base.htm`), and the log
formatters mask the path of these routes (`observability.logging`).
"""

from dataclasses import dataclass
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.urls import reverse
from django.utils import translation

# The names of the routes whose path holds the token of a mailed link.
ROUTES = frozenset(
    {"account-activate", "account-two-factor-reset", "password_reset_confirm"}
)

COOKIE_MAX_AGE = 15 * 60


@dataclass(frozen=True)
class MailedLink:
    """One mailed-link flow: its route, its placeholder and its cookie.

    *cookie* is the base name, also the signing salt; the cookie of a language
    is `<cookie>_<code>`. *route* is the URL name of the link and *placeholder*
    the value that stands for the token in the URL of the form.
    """

    cookie: str
    route: str
    placeholder: str

    def target(self, **kwargs):
        """The URL of the form, without the token, in the active language."""
        return reverse(self.route, kwargs={**kwargs, "token": self.placeholder})

    def land(self, request, token, **kwargs):
        """Answer a GET of the link whose *token* the caller has checked.

        Redirects to the form and sets the cookie. Stores nothing in the
        session. Any method but GET and HEAD gets a 405.
        """
        if request.method not in ("GET", "HEAD"):
            return HttpResponseNotAllowed(["GET", "HEAD"])
        response = HttpResponseRedirect(self.target(**kwargs))
        self.remember(response, token, **kwargs)
        return response

    def token(self, request):
        """The token in the cookie of the active language.

        Empty when the cookie is absent, tampered with or older than
        `COOKIE_MAX_AGE`.
        """
        return request.get_signed_cookie(
            self._name(translation.get_language()),
            default="",
            salt=self.cookie,
            max_age=COOKIE_MAX_AGE,
        )

    def remember(self, response, token, **kwargs):
        """Set the cookie of every language on *response*."""
        for code, path in self._paths(**kwargs):
            response.set_signed_cookie(
                self._name(code),
                token,
                salt=self.cookie,
                max_age=COOKIE_MAX_AGE,
                path=path,
                secure=settings.SESSION_COOKIE_SECURE,
                httponly=True,
                samesite="Lax",
            )

    def forget(self, response, **kwargs):
        """Delete the cookie of every language on *response*."""
        for code, path in self._paths(**kwargs):
            response.set_cookie(
                self._name(code),
                "",
                max_age=0,
                path=path,
                secure=settings.SESSION_COOKIE_SECURE,
                httponly=True,
                samesite="Lax",
            )

    def _name(self, code):
        return f"{self.cookie}_{code}"

    def _paths(self, **kwargs):
        """Each language code with the folder of the flow's URLs under its prefix.

        `reverse` leaves `;` and `,` unescaped in a path segment taken from the
        request; the folder is escaped again so no character of the URL can end
        the `Path` attribute of the `Set-Cookie` header.
        """
        for code, _name in settings.LANGUAGES:
            with translation.override(code):
                url = self.target(**kwargs)
            yield code, quote(url[: url.rstrip("/").rfind("/") + 1], safe="/%")
