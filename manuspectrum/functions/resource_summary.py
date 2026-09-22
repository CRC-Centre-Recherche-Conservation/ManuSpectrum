"""Per-graph configuration of the summary popup ("fiche essentielle").

The function carries configuration only. Its config never holds
``triggering_nodegroups``: Arches selects the functions to run on a tile save
with ``config__contains={"triggering_nodegroups": [...]}`` or
``config__triggering_nodegroups__exact=[]``
(arches/app/models/tile.py:826-844), and an absent key matches neither, so the
class stays out of that loop.
"""

import logging
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from arches.app.functions.base import BaseFunction

logger = logging.getLogger(__name__)

SUMMARY_FUNCTION_ID = "8e2b3f70-2b2c-4c45-9c2e-7a1d5f0c6b41"
CONFIG_VERSION = 1
STYLES = frozenset({"text", "date", "chip", "number", "link", "image"})
OPS = frozenset({"count", "distinct"})
DIRECTIONS = frozenset({"incoming", "outgoing"})
MAX_HOPS = 2

# Registered by migration 0004, which imports this dict: one source of identity.
details = {
    "functionid": SUMMARY_FUNCTION_ID,
    "name": "Resource Summary",
    "type": "summary",
    "description": "Fields and rollups shown in the map and IIIF summary popup",
    "defaultconfig": {"config_version": CONFIG_VERSION, "fields": [], "rollups": []},
    "classname": "ResourceSummary",
    "component": "views/components/functions/resource-summary",
}


def config_cache_key(graph_id):
    return f"summary-config:{graph_id}"


# One stamp for the whole deployment: the views key memos by resource id and
# do not know the graph without one more query per id.
SUMMARY_CONFIG_STAMP_KEY = "summary-config-stamp"


def config_stamp():
    """The token every memoised popup carries, stored without expiry.

    Minted on first read and kept until a configuration save deletes it.
    """
    return cache.get_or_set(SUMMARY_CONFIG_STAMP_KEY, lambda: uuid.uuid4().hex, None)


def bump_config_stamp():
    """Drop the stamp: the next reader mints another, orphaning every memo.

    Called by every path that writes a summary configuration. Only the server
    memos are affected: a copy a browser or a proxy holds under the response's
    ``max-age`` lives until it expires.
    """
    cache.delete(SUMMARY_CONFIG_STAMP_KEY)


def _clamp(value, ceiling, default):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, ceiling))


def _label(raw):
    if not isinstance(raw, dict):
        return None
    label = {
        k: v for k, v in raw.items() if k in ("en", "fr") and isinstance(v, str) and v
    }
    return label or None


def _normalize_field(raw, warnings, index):
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("alias"), str)
        or not raw["alias"]
    ):
        warnings.append(f"fields[{index}]: alias missing")
        return None
    style = raw.get("style", "text")
    if style not in STYLES:
        warnings.append(f"fields[{index}] ({raw['alias']}): unknown style {style!r}")
        return None
    field = {"alias": raw["alias"], "style": style}
    if "max_values" in raw:
        field["max_values"] = _clamp(raw["max_values"], settings.SUMMARY_MAX_VALUES, 3)
    label = _label(raw.get("label"))
    if label:
        field["label"] = label
    return field


def _normalize_hop(raw, warnings, where):
    if not isinstance(raw, dict):
        warnings.append(f"{where}: hop is not an object")
        return None
    slug, alias, direction = (
        raw.get("graph_slug"),
        raw.get("alias"),
        raw.get("direction"),
    )
    if not (isinstance(slug, str) and slug and isinstance(alias, str) and alias):
        warnings.append(f"{where}: graph_slug and alias are required")
        return None
    if direction not in DIRECTIONS:
        warnings.append(f"{where}: unknown direction {direction!r}")
        return None
    return {"graph_slug": slug, "alias": alias, "direction": direction}


def _normalize_aggregate(raw, warnings, where):
    op = raw.get("op") if isinstance(raw, dict) else None
    if op not in OPS:
        warnings.append(f"{where}: unknown op {op!r}")
        return None
    if op == "count":
        return {"op": "count"}
    if not isinstance(raw.get("alias"), str) or not raw["alias"]:
        warnings.append(f"{where}: distinct needs an alias")
        return None
    return {
        "op": "distinct",
        "alias": raw["alias"],
        "style": raw.get("style") if raw.get("style") in STYLES else "chip",
        "limit": _clamp(raw.get("limit"), settings.SUMMARY_MAX_LIMIT, 5),
    }


def _normalize_rollup(raw, warnings, index):
    """Return a cleaned rollup, or None when one of its hops is unusable.

    Hops and aggregates are both inspected before the verdict: a broken hop
    drops the whole rollup, but it does not hide the other problems of the
    same entry from the editor. An aggregate list without a ``count`` gets one,
    since the popup always shows the related count.
    """
    where = f"rollups[{index}]"
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("key"), str)
        or not raw["key"]
    ):
        warnings.append(f"{where}: key missing")
        return None
    path = raw.get("path")
    if not isinstance(path, list) or not 1 <= len(path) <= MAX_HOPS:
        warnings.append(f"{where}: path must hold 1 to {MAX_HOPS} hops")
        return None
    hops = [
        _normalize_hop(h, warnings, f"{where}.path[{i}]") for i, h in enumerate(path)
    ]
    aggregates = [
        _normalize_aggregate(a, warnings, f"{where}.aggregate[{i}]")
        for i, a in enumerate(raw.get("aggregate") or [])
    ]
    if any(hop is None for hop in hops):
        return None
    aggregates = [a for a in aggregates if a is not None]
    if not any(a["op"] == "count" for a in aggregates):
        aggregates.insert(0, {"op": "count"})
    rollup = {
        "key": raw["key"],
        "path": hops,
        "aggregate": aggregates,
        "max_related": _clamp(
            raw.get("max_related"),
            settings.SUMMARY_MAX_RELATED,
            settings.SUMMARY_MAX_RELATED,
        ),
    }
    label = _label(raw.get("label"))
    if label:
        rollup["label"] = label
    return rollup


def normalize_config(config):
    """Return (cleaned config, warnings).

    Invalid entries are dropped, never repaired; limits are clamped to the
    settings ceilings; a missing or foreign ``config_version`` yields an empty
    config. The result never contains ``triggering_nodegroups``.
    """
    warnings = []
    empty = {"config_version": CONFIG_VERSION, "fields": [], "rollups": []}
    if not isinstance(config, dict) or config.get("config_version") != CONFIG_VERSION:
        if config:
            warnings.append("config_version unsupported: configuration ignored")
        return empty, warnings
    fields = [
        _normalize_field(f, warnings, i)
        for i, f in enumerate(config.get("fields") or [])
    ]
    rollups = [
        _normalize_rollup(r, warnings, i)
        for i, r in enumerate(config.get("rollups") or [])
    ]
    return {
        "config_version": CONFIG_VERSION,
        "fields": [f for f in fields if f is not None],
        "rollups": [r for r in rollups if r is not None],
    }, warnings


class ResourceSummary(BaseFunction):
    """Configuration holder: no tile hook is implemented on purpose."""

    def after_function_save(self, functionxgraph, request):
        """Store the normalised config; drop the cached copy and the stamp on commit.

        The hook is the last write of the designer POST: the view
        (arches/app/views/graph.py:964-989) creates the row inside its
        transaction, calls the hook and returns, so the cleaned config reaches
        the database only through this ``save()``. Problems travel back to the
        editor under ``config["warnings"]``; nothing is raised, since the view
        catches ``NotImplementedError`` alone and any other exception would
        surface as an opaque 500.
        """
        cleaned, warnings = normalize_config(functionxgraph.config)
        if warnings:
            cleaned["warnings"] = warnings
            logger.warning(
                "summary config for graph %s: %s", functionxgraph.graph_id, warnings
            )
        functionxgraph.config = cleaned
        functionxgraph.save()
        # The designer's view calls this hook inside `transaction.atomic()`.
        transaction.on_commit(lambda: _forget_config(functionxgraph.graph_id))


def _forget_config(graph_id):
    cache.delete(config_cache_key(graph_id))
    bump_config_stamp()
