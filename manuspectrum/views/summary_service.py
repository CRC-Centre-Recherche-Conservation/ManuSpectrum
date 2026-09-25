"""Summary popup: graph index and field extraction from the Elasticsearch document.

The popup reads the resource as Elasticsearch already holds it, never the ORM.
``_source`` carries ``graph_id``, ``displayname`` (``[{language, value}]``),
``geometries``, ``ids``, ``references``, ``permissions`` and the whole tile
list, ``tiles = [{tileid, nodegroup_id, sortorder, data: {nodeid: value}}]``.
A tile value keeps the shape its datatype stores:

- ``string`` → ``{language: {value, direction}}``;
- ``reference`` → ``[{uri, list_id, labels: [{value, language_id, valuetype_id}]}]``,
  so a controlled-list label costs no query;
- ``resource-instance(-list)`` → ``[{resourceId, …}]``; a single instance may
  also arrive as a bare object;
- ``file-list`` → ``[{file_id, name, url, …}]``;
- ``date`` → an ISO string; ``number`` → a JSON number.

Language fallback, for every localized text: the requested language, then
English, then any other language holding a value. A reference with no usable
label falls back to its uri, and a field with no widget label to its alias.

The graph index turns a configured alias into the node that carries it and
into its widget label. It holds tuples and dicts alone, so it survives a trip
through the cache, and it is built with three queries; a warm popup makes none.

A rollup follows the one or two hops its configuration declares (D4), one
Elasticsearch search each. The reader's permission filter rides in every one
of them, so a resource a click could not open is never counted, and the last
hop counts and aggregates in the same search.

Once any nodegroup carries a grant, the document is stripped of the tiles the
reader may not read before anything is extracted from it, and the payload is
memoised per reader.

Every search is produced by a plan, a generator yielding search keywords and
receiving the response: one resource drives its plans with ``search``, a batch
drives all of them together with one ``msearch`` per hop. A cluster that
refuses or times out yields the degraded payload, whose name and model come
from the database.
"""

import logging
import re
from collections import defaultdict, namedtuple
from typing import NamedTuple

from django.conf import settings

from elasticsearch import ApiError, NotFoundError, TransportError
from guardian.models import GroupObjectPermission, UserObjectPermission

from arches.app.models import models
from arches.app.models.models import ResourceInstance
from arches.app.search.mappings import RESOURCES_INDEX
from arches.app.search.search_engine_factory import SearchEngineFactory
from arches_controlled_lists.models import ListItemValue

from manuspectrum.functions.resource_summary import (
    SUMMARY_FUNCTION_ID,
    config_cache_key,
    normalize_config,
)
from manuspectrum.utils.cache import get_or_build
from manuspectrum.utils.public_visibility import (  # noqa: F401  (re-exported)
    PERM_SCOPE_TTL,
    RESTRICTED_CACHE_KEY,
    RESTRICTED_NODEGROUPS_CACHE_KEY,
    readable_nodegroup_ids,
    resource_grant_count,
)
from manuspectrum.utils.spectrum_preview import is_supported
from manuspectrum.views.graph_nodes import (
    RELATION_DATATYPES,
    localized,
    target_graphids,
)

logger = logging.getLogger(__name__)

CACHE_TTL = 3600
SLUG_CACHE_KEY = "summary-graph-slugs"


def graph_index_key(graph_id):
    """Cache key of the memoised ``GraphIndex`` of a graph."""
    return f"summary-graph:{graph_id}"


# A degraded payload states that the cluster answered nothing, which is a
# symptom and not a fact about the resource: it expires in seconds.
DEGRADED_TTL = 30


# What a linked resource is fetched for: its name, and whether the reader may
# open it at all.
LINK_SOURCE = ["displayname", "permissions"]

NodeInfo = namedtuple("NodeInfo", "nodeid nodegroup_id datatype alias")

# ``target_graphids`` reads ``node.config`` alone, and the index holds no model
# instance.
_ConfiguredNode = namedtuple("_ConfiguredNode", "config")

# Counts above this are reported as the bound itself; a popup shows an order of
# magnitude, not a census.
TRACK_TOTAL_HITS = 10000

# A date node is indexed as the midnight of its day in the local timezone,
# "2025-02-07 00:00:00+01:00", which is neither ISO nor what a popup shows.
_INDEXED_DATETIME = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]")


class GraphIndex(NamedTuple):
    """One resource model, reduced to what the popup resolves by alias.

    ``targets`` holds, per relation alias, the models its values may point at,
    and ``lists`` the controlled list of a reference alias: a rollup needs the
    first to follow an outgoing hop and the second to name its buckets. Both
    are read off the node configuration in the query that builds the nodes.
    """

    graph_id: str
    slug: str
    name: dict
    nodes: dict
    labels: dict
    targets: dict
    lists: dict

    def name_for(self, language):
        """Localized name of the model."""
        return localized(self.name, language)

    def label_for(self, node, language):
        """Localized widget label of a node, falling back to its alias."""
        return localized(self.labels.get(node.nodeid) or {}, language) or node.alias

    @classmethod
    def for_graph(cls, graph_id):
        """Index of a graph, memoised for an hour; None when the graph is unknown."""
        graph_id = str(graph_id)
        return get_or_build(
            graph_index_key(graph_id), lambda: cls._build(graph_id), CACHE_TTL
        )

    @classmethod
    def for_slug(cls, slug):
        """Index of the published resource model carrying that slug, or None."""
        graph_id = _graph_ids_by_slug().get(slug)
        return cls.for_graph(graph_id) if graph_id else None

    @classmethod
    def slug_of(cls, graph_id):
        """Slug of a graph, read off its index, or None."""
        index = cls.for_graph(graph_id)
        return index.slug if index else None

    @classmethod
    def _build(cls, graph_id):
        graph = (
            models.GraphModel.objects.filter(graphid=graph_id)
            .values("slug", "name")
            .first()
        )
        if graph is None:
            return None
        nodes, targets, lists = {}, {}, {}
        for nodeid, nodegroup_id, datatype, alias, config in models.Node.objects.filter(
            graph_id=graph_id
        ).values_list("nodeid", "nodegroup_id", "datatype", "alias", "config"):
            if not alias:
                continue
            nodes[alias] = NodeInfo(
                nodeid=str(nodeid),
                nodegroup_id=str(nodegroup_id) if nodegroup_id else None,
                datatype=datatype,
                alias=alias,
            )
            if datatype in RELATION_DATATYPES:
                reached = target_graphids(_ConfiguredNode(config=config))
                if reached:
                    targets[alias] = reached
            elif datatype == "reference":
                list_id = (config or {}).get("controlledList")
                if list_id:
                    lists[alias] = str(list_id)
        labels = {}
        for node_id, label in models.CardXNodeXWidget.objects.filter(
            node__graph_id=graph_id
        ).values_list("node_id", "label"):
            texts = _i18n_dict(label)
            if texts:
                labels[str(node_id)] = texts
        return cls(
            graph_id=str(graph_id),
            slug=graph["slug"],
            name=_i18n_dict(graph["name"]),
            nodes=nodes,
            labels=labels,
            targets=targets,
            lists=lists,
        )


def _i18n_dict(value):
    """Plain ``{language: text}`` of an ``I18n_String``, empty texts dropped."""
    raw = getattr(value, "raw_value", value)
    if isinstance(raw, str):
        return {settings.LANGUAGE_CODE: raw} if raw else {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, str) and v}


def _graph_ids_by_slug():
    """Slug → graph id for every published resource model, memoised for an hour.

    One entry for the whole deployment: a rollup names the models it crosses by
    slug, and resolving them per click would put a query back on the hot path.
    ``manuspectrum.signals`` drops it whenever a publication row is written or
    deleted.
    """

    def build():
        return {
            slug: str(graphid)
            for graphid, slug in models.GraphModel.objects.filter(
                isresource=True, source_identifier__isnull=True
            ).values_list("graphid", "slug")
            if slug
        }

    return get_or_build(SLUG_CACHE_KEY, build, CACHE_TTL) or {}


def load_summary_config(graph_id):
    """Cleaned summary configuration of a graph, or None when unconfigured.

    A graph the function is not attached to memoises an empty dict, so a model
    left on the core behaviour (D11) costs no query either. The entry is
    dropped by the designer form and by ``after_function_save`` on every write.
    """
    config = get_or_build(
        config_cache_key(graph_id), lambda: _read_config(graph_id), CACHE_TTL
    )
    return config or None


def _read_config(graph_id):
    stored = (
        models.FunctionXGraph.objects.filter(
            graph_id=graph_id, function_id=SUMMARY_FUNCTION_ID
        )
        .values_list("config", flat=True)
        .first()
    )
    if stored is None:
        return {}
    config, warnings = normalize_config(stored)
    if warnings:
        logger.warning("summary config for graph %s: %s", graph_id, warnings)
    return config


def _tile_values(doc, node):
    """Every non-empty value of a node, its tiles ordered by ``sortorder``.

    A list value (reference, resource-instance-list, file-list) is flattened
    into the result; anything else is kept whole, a localized string included.
    """
    tiles = [
        tile
        for tile in doc.get("tiles") or []
        if isinstance(tile, dict)
        and str(tile.get("nodegroup_id")) == node.nodegroup_id
        and isinstance(tile.get("data"), dict)
    ]
    tiles.sort(key=lambda tile: tile.get("sortorder") or 0)
    values = []
    for tile in tiles:
        raw = tile["data"].get(node.nodeid)
        if raw is None or raw == "" or raw == [] or raw == {}:
            continue
        if isinstance(raw, list):
            values.extend(value for value in raw if value not in (None, "", [], {}))
        else:
            values.append(raw)
    return values


def _localized_string(value, language):
    """Text of a string value; a non-localized string is returned as it stands."""
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    texts = {}
    for lang, entry in value.items():
        text = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(text, str) and text.strip():
            texts[lang] = text
    return localized(texts, language)


def _reference_label(value, language):
    """Label of one reference value: its ``prefLabel``, any other label, its uri.

    The labels travel in the tile in every language of the deployment
    (``ReferenceDataType`` indexes them), so this never reaches the database.
    """
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    preferred, other = {}, {}
    for label in value.get("labels") or []:
        if not isinstance(label, dict):
            continue
        text = label.get("value")
        if not isinstance(text, str) or not text:
            continue
        bucket = preferred if label.get("valuetype_id") == "prefLabel" else other
        bucket.setdefault(label.get("language_id"), text)
    return (
        localized(preferred, language)
        or localized(other, language)
        or str(value.get("uri") or "")
    )


def _date(value):
    """An indexed timestamp reduced to its day; any other string is untouched.

    An EDTF value (an interval, an open end) never matches, so it travels as
    the model holds it.
    """
    match = _INDEXED_DATETIME.match(value)
    return match.group(1) if match else value


def _resource_id(value):
    """Id a resource-instance value points at, as a string."""
    if isinstance(value, dict):
        resource_id = value.get("resourceId") or value.get("resourceid")
        return str(resource_id) if resource_id else ""
    return str(value) if isinstance(value, str) else ""


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _style_values(style, raw_values, language):
    """Displayable values of a field, in the shape its style expects."""
    if style == "text":
        return [
            text
            for text in (_localized_string(value, language) for value in raw_values)
            if text
        ]
    if style == "date":
        return [
            _date(value) for value in raw_values if isinstance(value, str) and value
        ]
    if style == "number":
        return [
            number
            for number in (_number(value) for value in raw_values)
            if number is not None
        ]
    if style == "chip":
        return [
            label
            for label in (_reference_label(value, language) for value in raw_values)
            if label
        ]
    if style == "link":
        return [
            {"id": resource_id}
            for resource_id in (_resource_id(value) for value in raw_values)
            if resource_id
        ]
    return []


def extract_fields(doc, config, index, language):
    """Return ``(fields, link ids, preview)`` for one resource document.

    A field is ``{key, label, style, values, more}``, in configuration order;
    an alias the model does not carry, and a field the resource holds no value
    for, are both left out. ``max_values`` bounds ``values``, the remainder is
    counted in ``more``. Values of the ``link`` style carry an id
    alone, and those ids come back once each, in order, for the caller to
    resolve in a single request. The ``image`` style holds no value: it yields
    the preview, and only the first such field does.
    """
    fields, link_ids, seen = [], [], set()
    preview = None
    for entry in (config or {}).get("fields") or []:
        node = index.nodes.get(entry.get("alias"))
        if node is None:
            continue
        style = entry.get("style", "text")
        if style == "image" and preview is None:
            preview = find_preview(doc, node)
        values = _style_values(style, _tile_values(doc, node), language)
        if not values:
            continue
        limit = entry.get("max_values") or settings.SUMMARY_MAX_VALUES
        more, values = max(0, len(values) - limit), values[:limit]
        if style == "link":
            for value in values:
                if value["id"] not in seen:
                    seen.add(value["id"])
                    link_ids.append(value["id"])
        fields.append(
            {
                "key": node.alias,
                "label": _field_label(entry, node, index, language),
                "style": style,
                "values": values,
                "more": more,
            }
        )
    return fields, link_ids, preview


def _field_label(entry, node, index, language):
    """The configured override if it holds any language, else the widget label."""
    override = entry.get("label")
    if isinstance(override, dict):
        text = localized(override, language)
        if text:
            return text
    return index.label_for(node, language)


def find_preview(doc, node):
    """First file of a file-list node the spectrum preview can plot, or None.

    Which extensions those are is ``settings.XY_TEXT_FILE_FORMATS``, read
    through the endpoint's own test so the popup never offers a file the
    preview answers 204 for.
    """
    for value in _tile_values(doc, node):
        if not isinstance(value, dict) or not value.get("file_id"):
            continue
        name = value.get("name") or ""
        if is_supported(name):
            return {"file_id": str(value["file_id"]), "name": name}
    return None


def localized_entries(doc, key, language):
    """Text of an indexed descriptor (``displayname``, ``map_popup``).

    Arches indexes one entry per language, ``[{value, language}]``, and wrote
    a bare string before it did.
    """
    raw = doc.get(key)
    if isinstance(raw, str):
        return raw
    texts = {}
    for entry in raw or []:
        if isinstance(entry, dict) and isinstance(entry.get("value"), str):
            if entry["value"]:
                texts.setdefault(entry.get("language"), entry["value"])
    return localized(texts, language)


def display_name(doc, language):
    """Localized display name of the indexed resource, or an empty string."""
    return localized_entries(doc, "displayname", language)


def es_client():
    """The Elasticsearch client of a popup, and the name of the resources index.

    The client carries ``SUMMARY_ES_TIMEOUT`` rather than the project's 30 s:
    a sick cluster has to fall into the degraded payload instead of holding a
    worker for half a minute.
    """
    engine = SearchEngineFactory().create()
    return (
        engine.es.options(request_timeout=settings.SUMMARY_ES_TIMEOUT),
        engine._add_prefix(RESOURCES_INDEX),
    )


def _no_access(user_id):
    """The clause Arches' own search applies to hide what a reader is denied."""
    return {
        "nested": {
            "path": "permissions",
            "query": {"terms": {"permissions.users_with_no_access": [str(user_id)]}},
        }
    }


def hop_query(source_ids, hop, target_index, user_id, size):
    """``es.search`` kwargs for one hop of a rollup path.

    ``incoming``: the model reached records the link, so its documents are
    those whose indexed ``ids`` hold a source id under the relation's
    nodegroup. ``outgoing``: the ids were read off the source documents, so
    the hop fetches them by id. Every hop excludes what the reader may not
    open (D6), so a count never names resources a click cannot reach.
    """
    source_ids = list(source_ids)
    filters = [{"term": {"graph_id": target_index.graph_id}}]
    if hop.get("direction") == "outgoing":
        filters.append({"ids": {"values": source_ids}})
    else:
        matches = [{"terms": {"ids.id": source_ids}}]
        node = target_index.nodes.get(hop.get("alias"))
        if node is not None and node.nodegroup_id:
            matches.append({"term": {"ids.nodegroup_id": node.nodegroup_id}})
        filters.append(
            {"nested": {"path": "ids", "query": {"bool": {"filter": matches}}}}
        )
    return {
        "query": {"bool": {"filter": filters, "must_not": [_no_access(user_id)]}},
        "size": size,
        "track_total_hits": TRACK_TOTAL_HITS,
        "source": False,
    }


def distinct_aggs(node, limit):
    """Aggregation counting the resources of a hop per value of a reference node.

    ``references`` holds one nested document per label, so its own
    ``doc_count`` is label-inflated and the count comes from a
    ``reverse_nested``. Buckets are keyed by uri, which is language-neutral,
    and filtered by nodegroup, which ``references`` carries instead of the
    nodeid.
    """
    size = min(limit or settings.SUMMARY_MAX_LIMIT, settings.SUMMARY_MAX_LIMIT)
    return {
        "distinct": {
            "nested": {"path": "references"},
            "aggs": {
                "ng": {
                    "filter": {"term": {"references.nodegroup_id": node.nodegroup_id}},
                    "aggs": {
                        "uris": {
                            "terms": {"field": "references.uri", "size": size},
                            "aggs": {"n": {"reverse_nested": {}}},
                        }
                    },
                }
            },
        }
    }


def outgoing_ids(doc, node):
    """Resource ids a relation node points at, once each, in the order stored.

    The tiles carry the node itself; a document fetched without them (an
    intermediate hop, ``_source: ["ids"]``) only has the indexed ``ids``,
    which are keyed by nodegroup.
    """
    if doc.get("tiles"):
        candidates = (_resource_id(value) for value in _tile_values(doc, node))
    else:
        candidates = (
            str(entry.get("id") or "")
            for entry in doc.get("ids") or []
            if isinstance(entry, dict)
            and str(entry.get("nodegroup_id")) == node.nodegroup_id
        )
    ids = []
    for resource_id in candidates:
        if resource_id and resource_id not in ids:
            ids.append(resource_id)
    return ids


def list_labels(list_id, language):
    """Uri → preferred label of one controlled list, memoised for an hour.

    Buckets come back as uris, which is what keeps them language-neutral, so
    a list is resolved once per language instead of once per resource. The
    entry lives by its TTL: a relabelled item shows its new label within the
    hour.
    """
    return (
        get_or_build(
            f"summary-list-labels:{list_id}:{language}",
            lambda: _read_list_labels(list_id, language),
            CACHE_TTL,
        )
        or {}
    )


def _read_list_labels(list_id, language):
    texts = defaultdict(dict)
    for uri, lang, value in ListItemValue.objects.filter(
        list_item__list_id=list_id, valuetype_id="prefLabel"
    ).values_list("list_item__uri", "language_id", "value"):
        if value:
            texts[str(uri)][lang] = value
    return {uri: localized(langs, language) for uri, langs in texts.items()}


def parse_rollup_response(response, rollup, aggregate, labels):
    """The last hop's response as a rollup: count, named buckets, ``more``.

    A bucket's own ``doc_count`` counts nested label documents, several per
    value; ``n``, the ``reverse_nested``, counts the resources. A uri the list
    does not label travels as its uri.
    """
    items, more = [], 0
    if aggregate is not None:
        uris = (
            ((response.get("aggregations") or {}).get("distinct") or {})
            .get("ng", {})
            .get("uris", {})
        )
        for bucket in uris.get("buckets") or []:
            uri = str(bucket.get("key"))
            items.append(
                {
                    "uri": uri,
                    "label": labels.get(uri) or uri,
                    "count": (bucket.get("n") or {}).get("doc_count", 0),
                }
            )
        more = uris.get("sum_other_doc_count") or 0
    return {
        "key": rollup.get("key"),
        "count": _total(response),
        "items": items,
        "more": more,
        "truncated": False,
    }


def run_rollup(
    es, index_name, doc, rollup, indexes, user_id, language, nodegroups=None
):
    """One configured rollup, driven one ``search`` at a time.

    The work is in ``rollup_plan``; this runs it against one resource, which
    is what a single popup needs. A batch runs the same plans together.
    """
    return drive(
        rollup_plan(doc, rollup, indexes, user_id, language, nodegroups),
        lambda kwargs: es.search(index=index_name, **kwargs),
    )


def drive(plan, run):
    """Exhaust a plan of searches against one runner, returning its result."""
    response = None
    while True:
        try:
            kwargs = next(plan) if response is None else plan.send(response)
        except StopIteration as stop:
            return stop.value
        response = run(kwargs)


def rollup_plan(doc, rollup, indexes, user_id, language, nodegroups=None):
    """One configured rollup, one search per hop.

    An intermediate hop hands the next one the ids of its hits, or, when that
    next hop is outgoing, the relation ids those hits carry
    (``_source: ["ids"]``). A hop reaching more than ``max_related``
    resources stops the path: the result is ``truncated`` and carries the
    count of the hop that overflowed, the end of the path never having been
    reached. The last hop counts and aggregates in the same search. None when
    the path names a model or an alias the deployment does not carry: a broken
    rollup is dropped rather than shown empty.

    ``indexes`` maps a slug to an index already in hand; a model missing from
    it is read (and memoised) by ``GraphIndex``. ``nodegroups`` is what
    ``readable_nodegroups`` returned: a rollup whose relation node or distinct
    node sits in a nodegroup the reader may not read is dropped, the same way
    Arches search filters on the reader's permitted nodegroups.
    """
    hops = rollup.get("path") or []
    aggregate = next(
        (a for a in rollup.get("aggregate") or [] if a.get("op") == "distinct"), None
    )
    steps = _resolve_path(hops, aggregate, indexes, rollup)
    if steps is None:
        return None
    if nodegroups is not None and _reads_hidden_nodegroup(steps, aggregate, nodegroups):
        logger.info("summary rollup %s: hidden from this reader", rollup.get("key"))
        return None
    target_index = steps[-1][1]
    label = (
        localized(rollup.get("label") or {}, language)
        or target_index.name_for(language)
        or rollup.get("key")
    )
    distinct_node = _distinct_node(aggregate, target_index, rollup)
    labels = {}
    if distinct_node is None:
        aggregate = None
    else:
        list_id = target_index.lists.get(distinct_node.alias)
        labels = list_labels(list_id, language) if list_id else {}
    max_related = min(
        rollup.get("max_related") or settings.SUMMARY_MAX_RELATED,
        settings.SUMMARY_MAX_RELATED,
    )
    sources = [doc]
    source_ids = [str(doc.get("resourceinstanceid") or "")]
    for position, (hop, reached, relation_node) in enumerate(steps):
        last = position == len(steps) - 1
        if hop.get("direction") == "outgoing":
            source_ids = _outgoing_from(sources, relation_node)
            if len(source_ids) > max_related:
                return _plain_rollup(rollup, label, len(source_ids), truncated=True)
        source_ids = [resource_id for resource_id in source_ids if resource_id]
        if not source_ids:
            return _plain_rollup(rollup, label, 0)
        kwargs = hop_query(
            source_ids, hop, reached, user_id, 0 if last else max_related
        )
        if last and aggregate is not None:
            kwargs["aggs"] = distinct_aggs(distinct_node, aggregate.get("limit"))
        elif not last and steps[position + 1][0].get("direction") == "outgoing":
            kwargs["source"] = ["ids"]
        response = yield kwargs
        if last:
            result = parse_rollup_response(response, rollup, aggregate, labels)
            result["label"] = label
            return result
        total = _total(response)
        if total > max_related:
            return _plain_rollup(rollup, label, total, truncated=True)
        hits = (response.get("hits") or {}).get("hits") or []
        source_ids = [str(hit.get("_id")) for hit in hits if hit.get("_id")]
        sources = [hit.get("_source") or {} for hit in hits]


def _reads_hidden_nodegroup(steps, aggregate, nodegroups):
    """Whether a step's relation node or the distinct node is outside the set."""
    nodes = [relation_node for _hop, _reached, relation_node in steps]
    if aggregate is not None:
        distinct = steps[-1][1].nodes.get(aggregate.get("alias"))
        if distinct is not None:
            nodes.append(distinct)
    return any(node.nodegroup_id not in nodegroups for node in nodes)


def _resolve_path(hops, aggregate, indexes, rollup):
    """Every hop resolved to its models and its relation node, or None."""
    steps = []
    for position, hop in enumerate(hops):
        last = position == len(hops) - 1
        step = _resolve_hop(
            hop, indexes, aggregate.get("alias") if aggregate and last else None
        )
        if step is None:
            logger.warning(
                "summary rollup %s: hop %s (%s/%s) does not resolve",
                rollup.get("key"),
                position,
                hop.get("graph_slug"),
                hop.get("alias"),
            )
            return None
        steps.append(step)
    if not steps:
        logger.warning("summary rollup %s: empty path", rollup.get("key"))
        return None
    return steps


def _resolve_hop(hop, indexes, prefer_alias=None):
    """(hop, index of the model reached, node recording the link), or None.

    A hop names the node that records the link and the model carrying it: for
    ``incoming`` that model is the one the hop reaches, for ``outgoing`` it is
    the one the hop leaves, and the models reached are read off the node
    configuration. A node allowing several models resolves to the one holding
    ``prefer_alias``, the alias the last hop aggregates on, else to the first
    configured.
    """
    carrier = _index_for_slug(hop.get("graph_slug"), indexes)
    if carrier is None:
        return None
    node = carrier.nodes.get(hop.get("alias"))
    if node is None:
        return None
    if hop.get("direction") != "outgoing":
        return hop, carrier, node
    reached = [
        index
        for index in (
            _index_for_graph(graph_id, indexes)
            for graph_id in carrier.targets.get(node.alias) or []
        )
        if index is not None
    ]
    for index in reached:
        if prefer_alias and prefer_alias in index.nodes:
            return hop, index, node
    return (hop, reached[0], node) if reached else None


def _index_for_slug(slug, indexes):
    if not slug:
        return None
    index = (indexes or {}).get(slug)
    return index if index is not None else GraphIndex.for_slug(slug)


def _index_for_graph(graph_id, indexes):
    for index in (indexes or {}).values():
        if index is not None and index.graph_id == graph_id:
            return index
    return GraphIndex.for_graph(graph_id)


def _distinct_node(aggregate, target_index, rollup):
    """The reference node a ``distinct`` aggregates on, or None and a warning.

    ``references`` is keyed by nodegroup and holds uris alone, so only a
    reference node can be aggregated this way; on anything else the rollup
    keeps its count and loses its buckets.
    """
    if aggregate is None:
        return None
    node = target_index.nodes.get(aggregate.get("alias"))
    if node is None or node.datatype != "reference":
        logger.warning(
            "summary rollup %s: %s is not a reference node of %s",
            rollup.get("key"),
            aggregate.get("alias"),
            target_index.slug,
        )
        return None
    return node


def _outgoing_from(sources, node):
    """Ids the relation node of every source document points at, once each."""
    ids = []
    for source in sources:
        for resource_id in outgoing_ids(source, node):
            if resource_id not in ids:
                ids.append(resource_id)
    return ids


def _plain_rollup(rollup, label, count, truncated=False):
    """A rollup with no bucket: nothing to start from, or a path cut short."""
    return {
        "key": rollup.get("key"),
        "label": label,
        "count": count,
        "items": [],
        "more": 0,
        "truncated": truncated,
    }


def _total(response):
    """``hits.total.value``, bounded by ``track_total_hits``."""
    total = ((response or {}).get("hits") or {}).get("total")
    if isinstance(total, dict):
        return total.get("value") or 0
    return total or 0


class ResourceNotFound(Exception):
    """The resources index holds no document under that id."""


def perm_scope(user):
    """The memo scope of a reader: shared when nothing is restricted.

    A deployment where no resource carries an object grant and no nodegroup
    carries any grant answers the same payload to everyone, so one entry per
    resource and language is enough and a shared HTTP cache may keep it. Both
    counts are read once a minute and dropped when a grant is written; the
    first restriction moves every reader onto their own entry.
    """
    if not _restricted_resources() and not _restricted_nodegroups():
        return "public"
    return str(getattr(user, "id", None) or "anonymous")


def _restricted_resources():
    """Whether any resource is hidden from someone, memoised for a minute."""
    return bool(get_or_build(RESTRICTED_CACHE_KEY, _count_restrictions, PERM_SCOPE_TTL))


def _count_restrictions():
    """Object grants on resource instances that may deny read access to someone.

    Every codename counts, as for nodegroups: a grant set that leaves
    ``view_resourceinstance`` out denies read to its holder
    (arches/app/permissions/arches_default_allow.py:325-330).
    """
    return resource_grant_count()


def _restricted_nodegroups():
    """Whether any nodegroup carries a grant, memoised for a minute."""
    return bool(
        get_or_build(
            RESTRICTED_NODEGROUPS_CACHE_KEY,
            _count_nodegroup_restrictions,
            PERM_SCOPE_TTL,
        )
    )


def _count_nodegroup_restrictions():
    """Object grants on a nodegroup, users and groups together.

    Arches reads a nodegroup that carries no grant as readable by everyone.
    Any grant can take it away from someone: ``no_access_to_nodegroup``, and
    equally a set of grants that leaves ``read_nodegroup`` out, so every
    codename counts.
    """
    on_nodegroup = {
        "content_type__app_label": "models",
        "content_type__model": "nodegroup",
    }
    return (
        UserObjectPermission.objects.filter(**on_nodegroup).count()
        + GroupObjectPermission.objects.filter(**on_nodegroup).count()
    )


def readable_nodegroups(user):
    """Nodegroup ids the reader may read, or None when no nodegroup is restricted.

    None costs one memoised count. Otherwise the set is
    ``readable_nodegroup_ids``, memoised per reader; a reader without a
    profile reads none.
    """
    if not _restricted_nodegroups():
        return None
    return set(readable_nodegroup_ids(user))


def readable_doc(doc, nodegroups):
    """The document stripped of what the reader may not read.

    ``nodegroups`` is what ``readable_nodegroups`` returned; None keeps the
    document as indexed. The indexed ``ids`` and ``geometries`` go with the
    tiles: an outgoing hop reads the ids when a document holds no tile, and
    ``has_geometry`` reads the geometries.
    """
    if nodegroups is None:
        return doc
    kept = dict(doc)
    for key in ("tiles", "ids", "geometries"):
        kept[key] = [
            entry
            for entry in doc.get(key) or []
            if isinstance(entry, dict) and str(entry.get("nodegroup_id")) in nodegroups
        ]
    return kept


_Draft = namedtuple("_Draft", "payload index config link_ids")


def build_summary(resourceid, language, user):
    """The popup payload of one resource (spec §4.2).

    Raises ``ResourceNotFound`` when the index holds no such document. A
    cluster that refuses, breaks or times out yields the degraded payload
    instead of an error: a popup says what it still knows rather than
    nothing.
    """
    resourceid = str(resourceid)
    user_id = getattr(user, "id", None)
    es, index_name = es_client()
    try:
        nodegroups = readable_nodegroups(user)
        doc = readable_doc(
            es.get(index=index_name, id=resourceid)["_source"] or {}, nodegroups
        )
        draft = _draft(doc, resourceid, language)
        if draft.config is None:
            return draft.payload
        if draft.link_ids:
            _name_links(
                draft.payload["fields"],
                fetch_link_labels(es, index_name, draft.link_ids, language, user_id),
            )
        indexes = {draft.index.slug: draft.index}
        for rollup in draft.config.get("rollups") or []:
            result = run_rollup(
                es, index_name, doc, rollup, indexes, user_id, language, nodegroups
            )
            if result is not None:
                draft.payload["rollups"].append(result)
        return draft.payload
    except NotFoundError:
        raise ResourceNotFound(resourceid) from None
    except (ApiError, TransportError) as error:
        logger.warning("summary: elasticsearch failed on %s: %s", resourceid, error)
        return degraded_summary(resourceid, language)


def build_summaries(ids, language, user):
    """Payloads of several resources: one ``mget``, then one ``msearch`` per hop.

    Every search of every resource travels in the same round, so the popups a
    map warms cost one round-trip per hop rather than one per resource. An id
    the index does not hold is left out of the result; a cluster that answers
    nothing degrades the whole batch.
    """
    ids = [str(resource_id) for resource_id in ids]
    if not ids:
        return {}
    user_id = getattr(user, "id", None)
    es, index_name = es_client()
    try:
        sources = _fetch_sources(es, index_name, ids)
        nodegroups = readable_nodegroups(user)
        drafts, plans = {}, []
        for resource_id in ids:
            doc = sources.get(resource_id)
            if doc is None:
                continue
            doc = readable_doc(doc, nodegroups)
            draft = _draft(doc, resource_id, language)
            drafts[resource_id] = draft
            if draft.config is None:
                continue
            if draft.link_ids:
                plans.append(
                    (
                        (resource_id, "links"),
                        link_plan(draft.link_ids, language, user_id),
                    )
                )
            indexes = {draft.index.slug: draft.index}
            for position, rollup in enumerate(draft.config.get("rollups") or []):
                plans.append(
                    (
                        (resource_id, position),
                        rollup_plan(
                            doc, rollup, indexes, user_id, language, nodegroups
                        ),
                    )
                )
        results = run_plans(es, index_name, plans)
    except (ApiError, TransportError) as error:
        logger.warning("summary: elasticsearch failed on a batch: %s", error)
        return {
            resource_id: degraded_summary(resource_id, language) for resource_id in ids
        }
    return {
        resource_id: _finish(draft, results, resource_id)
        for resource_id, draft in drafts.items()
    }


def _finish(draft, results, resource_id):
    """The payload of one resource of a batch, once its searches came back."""
    if draft.config is None:
        return draft.payload
    _name_links(draft.payload["fields"], results.get((resource_id, "links")) or {})
    for position in range(len(draft.config.get("rollups") or [])):
        result = results.get((resource_id, position))
        if result is not None:
            draft.payload["rollups"].append(result)
    return draft.payload


def _draft(doc, resourceid, language):
    """Everything a payload holds before Elasticsearch is asked again.

    A model the deployment does not carry, or one the function is not
    attached to, stops here on the core display (D11): its name and the
    ``map_popup`` the descriptors wrote.
    """
    index = GraphIndex.for_graph(doc["graph_id"]) if doc.get("graph_id") else None
    graph = {
        "slug": index.slug if index else None,
        "name": index.name_for(language) if index else "",
    }
    payload = {
        "id": resourceid,
        "configured": True,
        "graph": graph,
        "name": display_name(doc, language),
    }
    config = load_summary_config(index.graph_id) if index else None
    if config is None:
        payload["configured"] = False
        payload["map_popup"] = localized_entries(doc, "map_popup", language)
        return _Draft(payload, index, None, [])
    fields, link_ids, preview = extract_fields(doc, config, index, language)
    payload.update(
        fields=fields,
        rollups=[],
        preview=_preview(preview, fields),
        has_geometry=bool(doc.get("geometries")),
        degraded=False,
    )
    return _Draft(payload, index, config, link_ids)


def _preview(preview, fields):
    """The preview file, labelled with the technique it was measured with.

    The label is the first chip of a technique field; a model whose
    configuration names no technique yields a preview without one.
    """
    if preview is None:
        return None
    label = next(
        (
            field["values"][0]
            for field in fields
            if field["style"] == "chip"
            and "technique" in field["key"]
            and field["values"]
        ),
        None,
    )
    return {"file_id": preview["file_id"], "label": label}


def degraded_summary(resourceid, language):
    """Name and model of a resource, read from the database (spec §4.2).

    What a popup can still say when Elasticsearch answers nothing: the name
    the descriptors hold and the model the resource belongs to.
    """
    row = (
        ResourceInstance.objects.filter(resourceinstanceid=resourceid)
        .values("descriptors", "name", "graph_id")
        .first()
    ) or {}
    index = GraphIndex.for_graph(row["graph_id"]) if row.get("graph_id") else None
    return {
        "id": str(resourceid),
        "configured": bool(index and load_summary_config(index.graph_id)),
        "graph": {
            "slug": index.slug if index else None,
            "name": index.name_for(language) if index else "",
        },
        "name": _descriptor(row.get("descriptors"), "name", language)
        or localized(row.get("name"), language),
        "degraded": True,
    }


def _descriptor(descriptors, key, language):
    """One descriptor of ``resource_instances.descriptors``, in the language."""
    texts = {}
    for lang, entry in (descriptors or {}).items():
        text = entry.get(key) if isinstance(entry, dict) else None
        if isinstance(text, str) and text:
            texts[lang] = text
    return localized(texts, language)


def fetch_link_labels(es, index_name, ids, language, user_id):
    """Name of every linked resource, in one ``mget``."""
    response = es.mget(index=index_name, ids=list(ids), source_includes=LINK_SOURCE)
    return _link_labels(
        {
            str(doc.get("_id")): doc.get("_source") or {}
            for doc in response.get("docs") or []
            if doc.get("found")
        },
        language,
        user_id,
    )


def link_plan(ids, language, user_id):
    """The same names, asked as a search so a batch pays one round for all."""
    ids = list(ids)
    response = yield {
        "query": {"ids": {"values": ids}},
        "size": len(ids),
        "source": LINK_SOURCE,
    }
    hits = (response.get("hits") or {}).get("hits") or []
    return _link_labels(
        {str(hit.get("_id")): hit.get("_source") or {} for hit in hits},
        language,
        user_id,
    )


def _link_labels(sources, language, user_id):
    """Id → name, empty for a resource the reader may not open (D6)."""
    return {
        resource_id: "" if _denied(source, user_id) else display_name(source, language)
        for resource_id, source in sources.items()
    }


def _denied(source, user_id):
    denied = ((source or {}).get("permissions") or {}).get("users_with_no_access") or []
    return str(user_id) in {str(value) for value in denied}


def _name_links(fields, labels):
    """Name every ``link`` value; an id nothing resolved keeps an empty label."""
    for field in fields:
        if field["style"] != "link":
            continue
        for value in field["values"]:
            value["label"] = labels.get(value["id"], "")


def _fetch_sources(es, index_name, ids):
    """``_source`` of every id the index holds, keyed by id."""
    response = es.mget(index=index_name, ids=list(ids))
    return {
        str(doc.get("_id")): doc.get("_source") or {}
        for doc in response.get("docs") or []
        if doc.get("found")
    }


def run_plans(es, index_name, plans):
    """Drive plans of searches in lockstep, one ``msearch`` per round.

    Every plan still pending contributes one search to the round, so a batch
    of popups costs one round-trip per hop instead of one per search. A plan
    whose search comes back as an error, or with no response at all, is
    dropped: its key is missing from the result and the popup shows one
    rollup less rather than nothing.
    """
    results, pending = {}, {}
    for key, plan in plans:
        _advance(key, plan, None, pending, results)
    while pending:
        keys = list(pending)
        searches = []
        for key in keys:
            searches.append({"index": index_name})
            searches.append(_search_body(pending[key][1]))
        responses = (es.msearch(searches=searches) or {}).get("responses") or []
        for key, response in zip(keys, responses):
            plan, _ = pending.pop(key)
            if not isinstance(response, dict) or "error" in response:
                plan.close()
                continue
            _advance(key, plan, response, pending, results)
        for key in keys[len(responses) :]:
            pending.pop(key)[0].close()
    return results


def _advance(key, plan, response, pending, results):
    """Push one response into a plan, recording its result or its next search."""
    try:
        kwargs = next(plan) if response is None else plan.send(response)
    except StopIteration as stop:
        results[key] = stop.value
    else:
        pending[key] = (plan, kwargs)


def _search_body(kwargs):
    """``es.search`` keywords as an ``msearch`` body."""
    body = dict(kwargs)
    if "source" in body:
        body["_source"] = body.pop("source")
    return body
