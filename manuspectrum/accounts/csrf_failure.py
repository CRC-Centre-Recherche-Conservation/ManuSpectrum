"""The answer to a failed CSRF check (`CSRF_FAILURE_VIEW`).

A second post of the two-factor code, made after the first one signed the user
in, carries a token the new session has rotated. It is answered with the
redirect the first post already earned, so the user lands signed in. Every
other failure gets a page of the site (a JSON body for an API path, as
`arches.app.views.main.custom_403`), status 403. The request body is never
logged.
"""

from http import HTTPStatus

from arches.app.utils.response import JSONErrorResponse
from arches.app.utils.request import looks_like_api_call
from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _

SECOND_FACTOR_ROUTE = "two-factor-authentication-login"


def _is_repeated_second_factor_post(request):
    match = getattr(request, "resolver_match", None)
    return (
        request.method == "POST"
        and match is not None
        and match.url_name == SECOND_FACTOR_ROUTE
        and request.user.is_authenticated
        and request.user.username != "anonymous"
    )


def csrf_failure(request, reason=""):
    if _is_repeated_second_factor_post(request):
        target = request.POST.get("next") or ""
        if not url_has_allowed_host_and_scheme(
            target,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return HttpResponseRedirect(reverse("root"))
        return HttpResponseRedirect(target)
    if looks_like_api_call(request):
        return JSONErrorResponse(
            _("Request Failed"), _("Permission Denied"), status=HTTPStatus.FORBIDDEN
        )
    return render(request, "errors/csrf.htm", status=HTTPStatus.FORBIDDEN)
