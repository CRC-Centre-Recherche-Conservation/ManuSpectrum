"""Keep the IIIF routes language-neutral in their HTTP headers.

``LocaleMiddleware`` adds ``Vary: Accept-Language`` and a ``Content-Language``
to every response of a path outside ``i18n_patterns``. A IIIF document under
``/iiif/`` carries every language in one body: this middleware, listed before
``LocaleMiddleware`` so it sees the response after it, removes both. An HTML
page under ``/iiif/`` (a documentation page) is rendered in the negotiated
language and keeps them.
"""

from django.utils.cache import cc_delim_re

IIIF_PREFIX = "/iiif/"


class IIIFLanguageNeutralMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not request.path_info.startswith(IIIF_PREFIX) or response.get(
            "Content-Type", ""
        ).startswith("text/html"):
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
