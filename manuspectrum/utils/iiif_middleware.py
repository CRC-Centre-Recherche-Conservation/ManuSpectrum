"""Keep the IIIF routes language-neutral in their HTTP headers.

``LocaleMiddleware`` adds ``Vary: Accept-Language`` and a ``Content-Language``
to every response of a path outside ``i18n_patterns``. A IIIF document under
``/iiif/`` carries every language in one body: this middleware, listed before
``LocaleMiddleware`` so it sees the response after it, removes both. The HTML
pages rendered in the negotiated language (``LOCALISED_PAGES``: the
documentation page and the IIIF Auth windows) keep them when they answer
HTML; any other answer under ``/iiif/``, error and redirect included, drops
them.
"""

from django.utils.cache import cc_delim_re

IIIF_PREFIX = "/iiif/"
LOCALISED_PAGES = frozenset(
    {
        "iiif-xy-reading-doc",
        "iiif-auth-login",
        "iiif-auth-token-1",
        "iiif-auth-token-2",
        "iiif-auth-logout",
    }
)


def _localised(request, response):
    match = getattr(request, "resolver_match", None)
    return (
        match is not None
        and match.url_name in LOCALISED_PAGES
        and response.get("Content-Type", "").startswith("text/html")
    )


class IIIFLanguageNeutralMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path_info.startswith(IIIF_PREFIX) or _localised(
            request, response
        ):
            return response
        if response.has_header("Vary"):
            kept = [
                field
                for field in cc_delim_re.split(response["Vary"])
                if field and field.lower() != "accept-language"
            ]
            if kept:
                response["Vary"] = ", ".join(kept)
            else:
                del response["Vary"]
        if response.has_header("Content-Language"):
            del response["Content-Language"]
        return response
