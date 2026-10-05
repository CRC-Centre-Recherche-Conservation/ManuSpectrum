"""``/iiif/auth/…``: the IIIF Auth 1.0 login, token and logout services, the Auth 2.0 token and probe services.

``login`` (Auth 1.0 login service, Auth 2.0 access service ``active``): a
request without a signed-in Arches session is redirected to the Arches login
page with ``next`` set to this route, a relative path built here; nothing of
the query (``origin`` included) is read. A signed-in session gets the access
cookie and a page that closes itself. It cannot be framed.

``token`` (``1`` and ``2``) answers ``GET ?messageId=&origin=`` with HTTP
200 always: an HTML page posting the message to *origin* (never ``*``) when
``messageId`` is given, the same message as JSON otherwise. The origin must
be an http(s) origin (else ``invalidRequest``) and a trusted one (else
``invalidOrigin``, and no token); without a valid access cookie the answer is
``missingCredentials`` at once; over ``IIIF_AUTH_TOKEN_RATE`` per IP,
``unavailable``. Version 2 speaks the Auth 2.0 message format (errors mapped
to its profiles, heading and note as language maps). The page may be framed
by the trusted origins only (``frame-ancestors``).

``probe`` (Auth 2.0) answers HTTP 200 with the status the reader would get on
the stored file: 200, 401 (no credentials, or a Bearer credential that is not
a valid IIIF token), 403, 404 (unknown), with the IIIF CORS headers.

``logout`` ends the IIIF tokens of the session named by the access cookie and
deletes the cookie; the Arches session is kept.

Every answer is ``private, no-store``; the auth pages carry no CORS header.
"""

from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_noop
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt
from django_ratelimit.core import is_ratelimited

from manuspectrum.iiif import data, services, tokens
from manuspectrum.iiif import language as lang
from manuspectrum.iiif.services import AUTH2_CONTEXT
from manuspectrum.observability import metrics
from manuspectrum.utils.public_visibility import is_connected
from manuspectrum.views.iiif.cors import iiif_cors

PRIVATE = "private, no-store"
MAX_MESSAGE_ID = 2048

DESCRIPTIONS = {
    "invalidRequest": gettext_noop("The request to the token service is malformed."),
    "missingCredentials": gettext_noop(
        "Not signed in to ManuSpectrum in this browser."
    ),
    "invalidCredentials": gettext_noop("The ManuSpectrum sign-in is no longer valid."),
    "invalidOrigin": gettext_noop("This viewer is not allowed to receive a token."),
    "unavailable": gettext_noop("The token service is unavailable, try again later."),
}
HEADINGS = {
    "invalidRequest": gettext_noop("Invalid request"),
    "missingCredentials": gettext_noop("Not signed in"),
    "invalidCredentials": gettext_noop("Sign-in no longer valid"),
    "invalidOrigin": gettext_noop("Viewer not allowed"),
    "unavailable": gettext_noop("Not available"),
}
AUTH2_PROFILES = {
    "invalidRequest": "invalidRequest",
    "missingCredentials": "missingAspect",
    "invalidCredentials": "invalidAspect",
    "invalidOrigin": "invalidOrigin",
    "unavailable": "unavailable",
}
PROBE_HEADINGS = {
    401: (services.HEADER, services.NOTE),
    403: (services.FAILURE_HEADER, services.FAILURE_DESCRIPTION),
}


def _private(response):
    response["Cache-Control"] = PRIVATE
    return response


def _unframable(response):
    response["X-Frame-Options"] = "DENY"
    response["Content-Security-Policy"] = "frame-ancestors 'none'"
    return _private(response)


class LoginView(View):
    """The access cookie service: sends a visitor to the Arches login, gives a signed-in session the cookie."""

    http_method_names = ["get", "head"]

    def get(self, request):
        user = tokens.session_user(request)
        if user is None:
            query = urlencode({"next": reverse("iiif-auth-login")})
            return _unframable(HttpResponseRedirect(f"{reverse('auth')}?{query}"))
        response = render(request, "iiif/auth_login.htm")
        tokens.set_access_cookie(response, request, user)
        return _unframable(response)


def _message(version, message_id, token=None, error=None):
    """The token service message of Auth *version*: the token, or the IIIF Auth 1.0 *error*."""
    if version == 2:
        message = {"@context": AUTH2_CONTEXT}
        if error:
            message.update(type="AuthAccessTokenError2", profile=AUTH2_PROFILES[error])
        else:
            message["type"] = "AuthAccessToken2"
    else:
        message = {}
    if message_id is not None:
        message["messageId"] = message_id
    if error is None:
        message.update(accessToken=token[0], expiresIn=token[1])
    elif version == 2:
        message.update(
            heading=lang.gettext_map(HEADINGS[error]),
            note=lang.gettext_map(DESCRIPTIONS[error]),
        )
    else:
        message.update(error=error, description=services.plain(DESCRIPTIONS[error]))
    return message


@method_decorator(xframe_options_exempt, name="dispatch")
class TokenView(View):
    """The access token service of IIIF Auth ``version`` 1 or 2."""

    http_method_names = ["get", "head"]
    version = 1

    def get(self, request):
        message_id = request.GET.get("messageId")
        raw_origin = request.GET.get("origin")
        origin = tokens.normalized_origin(raw_origin)
        token = error = None
        if message_id is not None and len(message_id) > MAX_MESSAGE_ID:
            message_id, error = None, "invalidRequest"
        elif origin is None:
            error = "invalidRequest"
        elif not tokens.is_trusted(origin):
            error = "invalidOrigin"
        elif is_ratelimited(
            request,
            group="manuspectrum.iiif-auth.token",
            key="ip",
            rate=settings.IIIF_AUTH_TOKEN_RATE,
            increment=True,
        ):
            error = "unavailable"
        else:
            try:
                token = tokens.issue(request, origin)
            except tokens.TokenError as refused:
                error = refused.code
        metrics.IIIF_AUTH_TOKENS.labels(
            outcome=metrics.bounded(error or "issued", metrics.IIIF_TOKEN_OUTCOMES)
        ).inc()
        message = _message(self.version, message_id, token, error)
        if message_id is None:
            return _private(JsonResponse(message))
        response = render(
            request,
            "iiif/auth_token.htm",
            {
                "message": message,
                "target": origin if error != "invalidRequest" else None,
            },
        )
        response["Content-Security-Policy"] = "frame-ancestors 'self' " + " ".join(
            tokens.trusted_origins()
        )
        response["Referrer-Policy"] = "no-referrer"
        return _private(response)


class TokenViewV2(TokenView):
    version = 2


@method_decorator(iiif_cors, name="dispatch")
class ProbeView(View):
    """The Auth 2.0 probe service of one stored file."""

    http_method_names = ["get", "head", "options"]

    def get(self, request, file_id):
        status = self.status(request, file_id)
        body = {"@context": AUTH2_CONTEXT, "type": "AuthProbeResult2", "status": status}
        if status in PROBE_HEADINGS:
            heading, note = PROBE_HEADINGS[status]
            body.update(heading=lang.gettext_map(heading), note=lang.gettext_map(note))
        return _private(JsonResponse(body, content_type="application/ld+json"))

    def status(self, request, file_id):
        if tokens.bearer_state(request) == tokens.INVALID:
            return 401
        reader = tokens.iiif_reader(request)
        try:
            record = data.readable_file(file_id, reader)
        except data.Refused:
            return 403 if is_connected(reader) else 401
        return 404 if record is None else 200


class LogoutView(View):
    """The logout service: ends the IIIF tokens of the cookie's session and deletes the cookie."""

    http_method_names = ["get", "head"]

    def get(self, request):
        tokens.revoke_cookie(request)
        response = render(request, "iiif/auth_logout.htm")
        tokens.clear_access_cookie(response)
        return _unframable(response)
