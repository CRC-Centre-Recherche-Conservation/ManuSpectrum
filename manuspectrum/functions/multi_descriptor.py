import logging
import re
from contextlib import nullcontext
from arches.app.functions.primary_descriptors import AbstractPrimaryDescriptorsFunction
from arches.app.models import models
from arches.app.models.system_settings import settings
from arches.app.datatypes.datatypes import DataTypeFactory

from django.utils.translation import get_language, gettext as _, override

logger = logging.getLogger(__name__)


# This duplicates the configuration declared in migration 0004,
# but on first package load, the function will be re-registered, because
# the .py file has not yet been placed in the destination folder.
# Re-registration will overwrite whatever the migration inserted.
details = {
    "functionid": "3969e977-9ee9-4b86-a4e4-2b7bb2b642bc",
    "name": "Multi Resource Descriptor Manuspectrum",
    "type": "primarydescriptors",
    "description": "Configure the name, description, and map popup of a resource",
    "defaultconfig": {
        "descriptor_types": {
            "name": {
                "nodegroup_id": "",
                "string_template": "",
            },
            "map_popup": {
                "nodegroup_id": "",
                "string_template": "",
            },
            "description": {
                "nodegroup_id": "",
                "string_template": "",
            },
        }
    },
    "classname": "MultiDescriptor",
    "component": "views/components/functions/multi_descriptor",
}


class MultiDescriptor(AbstractPrimaryDescriptorsFunction):
    """
    Function for processing multi-card resource descriptors by extracting node values
    based on node aliases rather than node names.

    The "Undefined" fallback is translated in ``context["language"]``, the
    language the descriptor is stored under.
    """

    def _graph_nodes(self, resource, context):
        """Nodes of the resource's graph, read once per graph and ``context``.

        When ``context`` is a dict the list is kept in
        ``context["_prefetched_graph_nodes_by_graph"][<graph_id>]``, so a
        context shared across resources of several graphs serves each its own
        nodes. ``context["_prefetched_graph_nodes"]`` is a list a caller
        supplies for the one resource it saves; it is honoured as that
        resource's graph when the keyed entry is absent. Deferred fields are
        never used here: datatypes read node fields this class does not know
        about.
        """
        if not isinstance(context, dict):
            return list(models.Node.objects.filter(graph=resource.graph))
        by_graph = context.setdefault("_prefetched_graph_nodes_by_graph", {})
        graph_key = str(resource.graph_id)
        if graph_key not in by_graph:
            supplied = context.get("_prefetched_graph_nodes")
            by_graph[graph_key] = (
                supplied
                if supplied is not None
                else list(models.Node.objects.filter(graph=resource.graph))
            )
        return by_graph[graph_key]

    def _tiles_by_nodegroup(self, resource, context, nodegroup_ids):
        """Tiles of ``resource`` for each nodegroup, sorted by ``sortorder``.

        Missing nodegroups are read in one query and kept in
        ``context["_prefetched_tiles"][<resourceinstanceid>]`` when ``context``
        is a dict; the cache is keyed by resource so a context shared across
        resources never serves another resource's tiles. A nodegroup without
        tiles is cached as an empty list.
        """
        resource_key = str(resource.resourceinstanceid)
        cacheable = isinstance(context, dict)
        cached = (
            context.setdefault("_prefetched_tiles", {}).setdefault(resource_key, {})
            if cacheable
            else {}
        )
        missing = [ng for ng in nodegroup_ids if ng not in cached]
        if missing:
            for nodegroup_id in missing:
                cached[nodegroup_id] = []
            tiles = models.TileModel.objects.filter(
                nodegroup_id__in=missing,
                resourceinstance_id=resource.resourceinstanceid,
            ).order_by("sortorder")
            for tile in tiles:
                cached[tile.nodegroup_id].append(tile)
        return {ng: cached[ng] for ng in nodegroup_ids}

    def get_primary_descriptor_from_nodes(
        self, resource, config, context=None, descriptor=None
    ):
        datatype_factory = None
        language = context.get("language") if context else None
        string_template = config.get("string_template", "")
        result = string_template
        updated = False

        try:
            node_aliases = []
            matches = re.findall(r"<([^>]+)>", string_template)
            if matches:
                node_aliases = matches

            graph_nodes = self._graph_nodes(resource, context)
            nodes_by_alias = {}
            for node in graph_nodes:
                if node.alias in node_aliases:
                    nodes_by_alias[node.alias] = node

            processed_tiles = set()
            nodegroup_ids = []
            for node in nodes_by_alias.values():
                if node.nodegroup_id not in nodegroup_ids:
                    nodegroup_ids.append(node.nodegroup_id)
            tiles_by_nodegroup = self._tiles_by_nodegroup(
                resource, context, nodegroup_ids
            )
            for alias, node in nodes_by_alias.items():
                nodeid = str(node.nodeid)
                tiles = tiles_by_nodegroup[node.nodegroup_id]

                for tile in tiles:
                    if tile.tileid in processed_tiles:
                        continue

                    if nodeid in tile.data and tile.data[nodeid] is not None:
                        if not datatype_factory:
                            datatype_factory = DataTypeFactory()

                        datatype = datatype_factory.get_instance(node.datatype)
                        value = datatype.get_display_value(
                            tile, node, language=language
                        )

                        if value is None:
                            value = ""

                        result = result.replace(f"<{alias}>", str(value))
                        updated = True

                        processed_tiles.add(tile.tileid)
        except Exception as e:
            logger.error(
                f"Error in MulticardResourceDescriptor Function: {e} -- {config['nodegroup_id']}"
            )

        if result.strip() == "":
            with override(language) if language else nullcontext():
                result = _("Undefined")

        if not updated:
            try:
                lookup_language = language or get_language() or settings.LANGUAGE_CODE
                result = resource.descriptors[lookup_language][descriptor]
            except (KeyError, TypeError):
                pass

        return result
