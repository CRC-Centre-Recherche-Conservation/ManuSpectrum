"""Links between resources as the tiles hold them, resolved by (model slug, node alias).

A role names a node by the slug of its published resource model and its alias,
through ``GraphIndex``; no graph or node id is written in the code. Links are
read off ``TileModel``, never off ``resource_x_resource``.
"""

import logging
from collections import defaultdict

from django.contrib.postgres.fields import ArrayField
from django.db.models import BooleanField, TextField
from django.db.models.expressions import RawSQL
from django.db.models.functions import Cast

from arches.app.models.models import TileModel

from manuspectrum.views.summary_service import GraphIndex

logger = logging.getLogger(__name__)


def role_node(slug, alias):
    """The ``NodeInfo`` of a role, or None when the model or the alias is unknown."""
    index = GraphIndex.for_slug(slug)
    return index.nodes.get(alias) if index else None


def graph_id_of(slug):
    """Graph id of the published resource model carrying *slug*, or None."""
    index = GraphIndex.for_slug(slug)
    return index.graph_id if index else None


# Targets of one tile's value, in stored order: ``_resource_id`` of each item
# of a list, or of the value itself. Pinned equal to it by tests.test_role_links.
_TARGETS = """
    SELECT x.target
    FROM (SELECT tiles.tiledata -> %s AS v) AS n
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE jsonb_typeof(n.v) WHEN 'array' THEN n.v ELSE jsonb_build_array(n.v) END
    ) WITH ORDINALITY AS e(item, position)
    CROSS JOIN LATERAL (
        SELECT CASE jsonb_typeof(e.item)
            WHEN 'object' THEN coalesce(
                nullif(e.item ->> 'resourceId', ''), nullif(e.item ->> 'resourceid', '')
            )
            WHEN 'string' THEN nullif(e.item #>> '{}', '')
        END AS target
    ) AS x
    WHERE x.target IS NOT NULL{only}
"""


def node_links(node, targets=None):
    """``(source id, target id)`` of every resource-instance reference *node* holds, in one query.

    A list value yields one pair per target; an empty or malformed entry
    yields none. *targets* keeps the pairs whose target is one of them.
    """
    rows = TileModel.objects.filter(nodegroup_id=node.nodegroup_id)
    if targets is None:
        sql, params = _TARGETS.replace("{only}", ""), [str(node.nodeid)]
    else:
        targets = [str(target) for target in targets]
        if not targets:
            return []
        sql = _TARGETS.replace("{only}", " AND x.target = ANY(%s)")
        params = [str(node.nodeid), targets]
        rows = rows.filter(RawSQL(f"EXISTS ({sql})", params, BooleanField()))
    rows = rows.annotate(
        source=Cast("resourceinstance_id", TextField()),
        refs=RawSQL(
            f"ARRAY({sql} ORDER BY e.position)", params, ArrayField(TextField())
        ),
    )
    return [
        (source, target)
        for source, found in rows.values_list("source", "refs")
        for target in found
    ]


def role_links(slug, alias):
    """``(source id, target id)`` of every resource-instance value of the role (``node_links``).

    An unresolved role yields ``[]`` and logs a warning.
    """
    node = role_node(slug, alias)
    if node is None or not node.nodegroup_id:
        logger.warning("explorer: role %s.%s is not resolved", slug, alias)
        return []
    return node_links(node)


def readable_links(slug, alias, readable):
    """Links of a role, keyed by source resource id, gated by nodegroup readability.

    ``readable`` is a set of readable nodegroup ids: the role is skipped
    entirely when its nodegroup id is not in it. ``None`` ignores
    readability and reads the role unconditionally.
    """
    result = defaultdict(set)
    node = role_node(slug, alias)
    if readable is not None and (node is None or node.nodegroup_id not in readable):
        return result
    for source, target in role_links(slug, alias):
        result[source].add(target)
    return result
