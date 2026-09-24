"""Techniques the homepage offers: the thesaurus references of the Explorer's
technique facet that have visible analyses, as the visitor sees them."""

from django.conf import settings
from django.http import QueryDict

from manuspectrum.utils.cache import get_or_build, stable_cache_key
from manuspectrum.utils.public_visibility import anonymous_user
from manuspectrum.views.explorer_service import search_payload


def homepage_techniques(language):
    """``[{"id": uri, "label": Label, "count": n}]``, techniques with at least
    one analysis visible to the anonymous visitor, in the facet's order.

    Always computed as the visitor, so the list is the same for every reader;
    memoised per language for ``EXPLORER_TECHNIQUES_TTL`` seconds.
    """

    def build():
        payload = search_payload(
            QueryDict("grain=analyses"), anonymous_user(), language
        )
        facet = next((f for f in payload["facets"] if f["key"] == "technique"), None)
        return [
            {"id": value["id"], "label": value["label"], "count": value["count"]}
            for value in (facet or {}).get("values", [])
            if value["count"] > 0
        ]

    key = stable_cache_key("explorer-home-techniques", language)
    return get_or_build(key, build, settings.EXPLORER_TECHNIQUES_TTL) or []
