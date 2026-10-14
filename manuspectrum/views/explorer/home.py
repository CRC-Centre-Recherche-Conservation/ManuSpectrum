"""Techniques the homepage offers: the thesaurus references the visible
analyses carry themselves (``home_techniques``), as the visitor sees them."""

import logging

from django.conf import settings

from manuspectrum.utils.cache import get_or_build, stable_cache_key
from manuspectrum.utils.public_visibility import anonymous_user
from manuspectrum.views.explorer.service import home_techniques

logger = logging.getLogger(__name__)


def homepage_techniques(language):
    """``[{"id": uri, "label": Label, "count": n, "depth": d}]``, techniques with
    at least one analysis visible to the anonymous visitor, in tree order.

    ``count`` includes the rows of the narrower techniques; ``depth`` is the
    number of carried ancestors along the first path (the page indents by it).

    Always computed as the visitor, so the list is the same for every reader;
    memoised per language for ``EXPLORER_TECHNIQUES_TTL`` seconds. A build
    that raises is logged and yields ``[]``, memoising nothing.
    """

    def build():
        try:
            values = [
                v for v in home_techniques(anonymous_user(), language) if v["count"] > 0
            ]
            by_id = {v["id"]: v for v in values}

            def depth(value):
                steps, seen = 0, {value["id"]}
                while value["parents"] and value["parents"][0] in by_id:
                    value = by_id[value["parents"][0]]
                    if value["id"] in seen:
                        break
                    seen.add(value["id"])
                    steps += 1
                return steps

            return [
                {
                    "id": v["id"],
                    "label": v["label"],
                    "count": v["count"],
                    "depth": depth(v),
                }
                for v in values
            ]
        except Exception:
            logger.exception("Homepage techniques: the explorer search failed")
            return None

    key = stable_cache_key("explorer-home-techniques", language)
    return get_or_build(key, build, settings.EXPLORER_TECHNIQUES_TTL) or []
