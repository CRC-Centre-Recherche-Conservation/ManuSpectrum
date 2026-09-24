"""Links between resources as the tiles hold them, resolved by (model slug, node alias).

A role names a node by the slug of its published resource model and its alias,
through ``GraphIndex``; no graph or node id is written in the code. Links are
read off ``TileModel``, never off ``resource_x_resource``.
"""

import logging
from collections import defaultdict

from arches.app.models.models import TileModel

from manuspectrum.views.summary_service import GraphIndex, _resource_id

logger = logging.getLogger(__name__)


def role_node(slug, alias):
    """The ``NodeInfo`` of a role, or None when the model or the alias is unknown."""
    index = GraphIndex.for_slug(slug)
    return index.nodes.get(alias) if index else None


def graph_id_of(slug):
    """Graph id of the published resource model carrying *slug*, or None."""
    index = GraphIndex.for_slug(slug)
    return index.graph_id if index else None


def role_links(slug, alias):
    """``(source id, target id)`` of every resource-instance value of the role.

    A list value yields one pair per target; an empty or malformed entry
    yields none. An unresolved role yields ``[]`` and logs a warning.
    """
    node = role_node(slug, alias)
    if node is None or not node.nodegroup_id:
        logger.warning("explorer: role %s.%s is not resolved", slug, alias)
        return []
    rows = TileModel.objects.filter(nodegroup_id=node.nodegroup_id).values_list(
        "resourceinstance_id", f"data__{node.nodeid}"
    )
    pairs = []
    for source, value in rows:
        for ref in value if isinstance(value, list) else [value]:
            target = _resource_id(ref)
            if target:
                pairs.append((str(source), target))
    return pairs


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
