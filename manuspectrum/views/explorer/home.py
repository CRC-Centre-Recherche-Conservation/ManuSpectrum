"""Techniques the homepage offers: the thesaurus references the visible
analyses carry themselves (``home_techniques``), as the visitor sees them,
nested under the carried techniques they are narrower than."""

import logging
from collections import defaultdict

from django.conf import settings

from manuspectrum.utils.cache import get_or_build, stable_cache_key
from manuspectrum.utils.public_visibility import anonymous_user
from manuspectrum.views.explorer.service import home_techniques

logger = logging.getLogger(__name__)


def technique_tree(values):
    """*values* (``FacetValue`` with ``count`` > 0, in tree order) as nested nodes ``{"id", "label", "count", "children"}``.

    A value sits under every one of its ``parents`` that is listed, in the
    order of *values*; a value with no listed parent, or reached only through
    a cycle, is a root. A path never repeats a value.
    """
    listed = {v["id"] for v in values}
    children = defaultdict(list)
    for value in values:
        for parent in value["parents"]:
            if parent in listed:
                children[parent].append(value)

    def node(value, path):
        path = path | {value["id"]}
        return {
            "id": value["id"],
            "label": value["label"],
            "count": value["count"],
            "children": [
                node(child, path)
                for child in children[value["id"]]
                if child["id"] not in path
            ],
        }

    roots, reached = [], set()
    starts = [v for v in values if not any(p in listed for p in v["parents"])]
    for value in starts + values:
        if value["id"] in reached:
            continue
        root = node(value, frozenset())
        roots.append(root)
        stack = [root]
        while stack:
            current = stack.pop()
            reached.add(current["id"])
            stack.extend(current["children"])
    return roots


def homepage_techniques(language):
    """The techniques with at least one analysis visible to the anonymous visitor, as ``technique_tree`` nodes.

    ``count`` includes the rows of the narrower techniques; a technique sits
    under each of its nearest carried ancestors, the rule of the Explorer home.

    Always computed as the visitor, so the list is the same for every reader;
    memoised per language for ``EXPLORER_TECHNIQUES_TTL`` seconds. A build
    that raises is logged and yields ``[]``, memoising nothing.
    """

    def build():
        try:
            return technique_tree(
                [
                    v
                    for v in home_techniques(anonymous_user(), language)
                    if v["count"] > 0
                ]
            )
        except Exception:
            logger.exception("Homepage techniques: the explorer search failed")
            return None

    key = stable_cache_key("explorer-home-techniques", language)
    return get_or_build(key, build, settings.EXPLORER_TECHNIQUES_TTL) or []
