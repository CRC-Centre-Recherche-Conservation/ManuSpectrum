"""Techniques the homepage offers: the thesaurus references of the Explorer's
technique facet that have visible analyses, as the visitor sees them."""

import logging

from django.conf import settings
from django.http import QueryDict

from manuspectrum.utils.cache import get_or_build, stable_cache_key
from manuspectrum.utils.public_visibility import anonymous_user
from manuspectrum.views.explorer.service import search_payload

logger = logging.getLogger(__name__)


def homepage_techniques(language):
    """``[{"id": uri, "label": Label, "count": n}]``, techniques with at least
    one analysis visible to the anonymous visitor, in the facet's order.

    Always computed as the visitor, so the list is the same for every reader;
    memoised per language for ``EXPLORER_TECHNIQUES_TTL`` seconds. A search
    that raises is logged and yields ``[]``, memoising nothing.
    """

    def build():
        try:
            payload = search_payload(
                QueryDict("grain=analyses"), anonymous_user(), language
            )
            facet = next(
                (f for f in payload["facets"] if f["key"] == "technique"), None
            )
            return [
                {"id": value["id"], "label": value["label"], "count": value["count"]}
                for value in (facet or {}).get("values", [])
                if value["count"] > 0
            ]
        except Exception:
            logger.exception("Homepage techniques: the explorer search failed")
            return None

    key = stable_cache_key("explorer-home-techniques", language)
    return get_or_build(key, build, settings.EXPLORER_TECHNIQUES_TTL) or []
