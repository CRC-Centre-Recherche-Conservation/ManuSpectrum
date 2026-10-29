"""Fetch Metadata guard of the Explorer's internal APIs.

The ``/{lang}/api/explorer/*`` payloads and the spectrum preview serve the
Analysis Explorer page; they are not a contract. A browser tells the server
what started a request (``Sec-Fetch-Site``, ``Sec-Fetch-Mode``, which a page
script cannot forge or drop): the page's own ``fetch()`` is ``same-origin`` +
``cors``. Anything else (a pasted URL, another site, a script without those
headers) is refused with a 403 that points to the documented products. A
browser that sends no Fetch Metadata at all is answered when its ``Referer`` is
a page of this site (reason ``referer``). Guarded responses vary on the two
headers.

``settings.EXPLORER_UI_ONLY`` is ``enforce`` (refuse), ``observe`` (answer, count
what would be refused) or ``off`` (no check, no count). The products meant
for reuse (data package, series CSV, events CSV/GeoJSON, IIIF routes, the
Explorer manifest) are not decorated.
"""

from functools import wraps
from urllib.parse import urlsplit

import orjson
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.urls import reverse
from django.utils import translation
from django.utils.cache import patch_vary_headers

from manuspectrum.observability import metrics

MODES = ("enforce", "observe", "off")
ACCEPTED_SITE = "same-origin"
ACCEPTED_MODES = ("cors", "same-origin")
REASON_ACCEPTED = "same_origin"
REASON_REFERER = "referer"
VARY = ("Sec-Fetch-Site", "Sec-Fetch-Mode")
REUSE_ANCHOR = "#reuse"
DETAIL = "This endpoint serves the Analysis Explorer page only."

# Route names of the guarded views; tests/test_explorer_ui_only.py checks that
# each resolves to a view whose dispatch carries ``ui_only``.
UI_ONLY_ROUTES = (
    "explorer-search",
    "explorer-document",
    "explorer-document-match",
    "explorer-facet",
    "explorer-home",
    "explorer-analysis",
    "explorer-items",
    "explorer-synthesis",
    "explorer-events",
    "explorer-share",
    "api-spectrum-preview",
)


def mode():
    """The configured mode; an unknown value is a configuration error."""
    value = getattr(settings, "EXPLORER_UI_ONLY", "enforce")
    if value not in MODES:
        raise ImproperlyConfigured(
            f"EXPLORER_UI_ONLY must be one of {', '.join(MODES)}, not {value!r}"
        )
    return value


def refusal_reason(request):
    """None when the request comes from the page's own script, else why not."""
    site = request.META.get("HTTP_SEC_FETCH_SITE")
    fetch_mode = request.META.get("HTTP_SEC_FETCH_MODE")
    if site == ACCEPTED_SITE and fetch_mode in ACCEPTED_MODES:
        return None
    if site is None and fetch_mode is None:
        return "absent"
    if site == "cross-site":
        return "cross_site"
    if site == "same-site":
        return "same_site"
    if fetch_mode == "navigate":
        return "navigate"
    return "other"


def _own_origin(request):
    """Scheme of ``PUBLIC_SERVER_ADDRESS`` (nginx ends TLS) and the validated host."""
    scheme = urlsplit(settings.PUBLIC_SERVER_ADDRESS).scheme or request.scheme
    return f"{scheme}://{request.get_host()}"


def _referer_is_own_page(request):
    """True when the ``Referer`` names this site's origin (legacy browsers, no Fetch Metadata)."""
    referer = request.META.get("HTTP_REFERER", "")
    parts = urlsplit(referer)
    if not parts.scheme or not parts.netloc:
        return False
    return f"{parts.scheme}://{parts.netloc}" == _own_origin(request)


def _reuse_url(request):
    code = translation.get_language_from_path(request.path_info)
    if code not in dict(settings.LANGUAGES):
        code = settings.LANGUAGE_CODE
    with translation.override(code):
        path = reverse("about-data")
    return f"{settings.PUBLIC_SERVER_ADDRESS.rstrip('/')}{path}{REUSE_ANCHOR}"


def _refusal(request):
    url = _reuse_url(request)
    response = HttpResponse(
        orjson.dumps({"detail": DETAIL, "reuse": url}),
        content_type="application/json",
        status=403,
    )
    response["Cache-Control"] = "no-store"
    response["Link"] = f'<{url}>; rel="help"'
    return response


def ui_only(view):
    """Answer *view* to the Explorer page's own requests only (see the module docstring)."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        current = mode()
        if current == "off":
            return view(request, *args, **kwargs)
        reason = refusal_reason(request)
        if reason == "absent" and _referer_is_own_page(request):
            outcome, label = "accepted", REASON_REFERER
        elif reason is None:
            outcome, label = "accepted", REASON_ACCEPTED
        else:
            outcome = "refused" if current == "enforce" else "observed"
            label = metrics.bounded(reason, metrics.EXPLORER_UI_REASONS)
        metrics.EXPLORER_UI_CHECKS.labels(outcome=outcome, reason=label).inc()
        response = (
            _refusal(request)
            if outcome == "refused"
            else view(request, *args, **kwargs)
        )
        patch_vary_headers(response, VARY)
        return response

    wrapper.ui_only = True
    return wrapper
