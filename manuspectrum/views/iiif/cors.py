"""CORS of the IIIF routes: any origin, no credentials, on every status.

Every response carries ``Access-Control-Allow-Origin: *``, exposes ``ETag``
and ``WWW-Authenticate`` and varies on ``Authorization`` and ``Cookie``. An
``OPTIONS`` request is answered here, allowing ``GET, HEAD, OPTIONS`` with
``Authorization`` and ``Accept`` for ten minutes. ``django-cors-headers``,
when it covers the path, answers a preflight itself and keeps ``*``: never
``Access-Control-Allow-Credentials``.
"""

import functools

from django.http import HttpResponse
from django.utils.cache import patch_vary_headers


def iiif_cors(view):
    """Decorate a view function (or ``dispatch``) with the IIIF CORS headers."""

    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
            response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Authorization, Accept"
            response["Access-Control-Max-Age"] = "600"
        else:
            response = view(request, *args, **kwargs)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Expose-Headers"] = "ETag, WWW-Authenticate"
        patch_vary_headers(response, ("Authorization", "Cookie"))
        return response

    return wrapped
