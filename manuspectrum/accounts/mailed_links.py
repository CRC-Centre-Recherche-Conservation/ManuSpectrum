"""The page a personal link mailed to a user opens first.

Three mails carry a link with a token in its path: the invitation
(`activation.ActivateAccountView`), the two-factor re-enrolment
(`twofactor.TwoFactorResetView`) and the password reset
(`password_reset.PasswordResetConfirmView`). Each flow moves the token into the
session and goes on at a URL without it, so the pages where a password is
typed carry no token in their URL or `Referer`.

The session cookie is `SameSite=Strict` (`SESSION_COOKIE_SAMESITE`, set by
Arches and kept). A link clicked in a webmail or a mail client is a cross-site
navigation, and a browser sends no `Strict` cookie on any request of a redirect
chain that started on another site, not even one that the chain set itself.
A flow that stores the token on that first GET and redirects loses it: the next
page has no session and refuses the link.

`land` therefore stores nothing on a GET. It answers a page of the site whose
« Continue » button posts back to the same URL. That post starts on a page of
the site, so it is same-site: the browser sends the session cookie with it and
with the redirect that follows. The post, checked by the CSRF middleware like
any other, moves the token into the session and redirects to the URL without
it. A GET neither stores nor consumes anything, so a mail scanner that fetches
the link leaves it working. The views answer every step with
`Referrer-Policy: same-origin`: the « Continue » page has the token in its URL,
and none of its requests to another site carries it in a `Referer`.
"""

from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.shortcuts import render


def land(request, *, token, session_key, target, template_name, context=None):
    """Answer *request* on a mailed link whose *token* the caller has checked.

    GET and HEAD render *template_name* with *context*: a page whose form posts
    back to the same URL. POST stores *token* under *session_key* and
    redirects to *target*, the URL without the token. Any other method gets
    a 405.
    """
    if request.method == "POST":
        request.session[session_key] = token
        return HttpResponseRedirect(target)
    if request.method in ("GET", "HEAD"):
        return render(request, template_name, context or {})
    return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
