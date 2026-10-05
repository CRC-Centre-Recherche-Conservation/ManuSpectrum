"""Arches function proposing « Imaging layers » tiles when a manifest tile is saved.

The rule lives in :mod:`manuspectrum.utils.imaging_layers`; this function only
decides when to run it. It is registered and bound to the Analysis graph by
migration ``0007_imaging_layers_proposal``.
"""

import logging

from django.db import transaction
from django.utils.translation import gettext as _

from arches.app.functions.base import BaseFunction
from arches.app.models.resource import Resource

from manuspectrum.constants.imaging_layers import IMAGING_MANIFEST_NODEGROUP_ID
from manuspectrum.utils import imaging_layers as rule
from manuspectrum.utils.role_links import role_node
from manuspectrum.utils.roles import ROLES

logger = logging.getLogger(__name__)

details = {
    "functionid": "6bd45d4b-3902-4ba7-bb46-8ac3ec830f9b",
    "name": "Imaging layers proposal",
    # Never "primarydescriptors": Arches skips that type in the tile hooks.
    "type": "node",
    "description": (
        "Proposes an Imaging layers tile for every canvas of a chemical imaging "
        "manifest, read from the canvas label. A tile that exists is never modified."
    ),
    "defaultconfig": {"triggering_nodegroups": [IMAGING_MANIFEST_NODEGROUP_ID]},
    "classname": "ImagingLayersProposal",
    "component": "views/components/functions/imaging-layers-proposal",
}


class ImagingLayersProposal(BaseFunction):
    def post_save(self, tile, request, context=None):
        """Create the layer tiles the manifest of *tile* implies.

        Runs inside the atomic block of ``Tile.save``, so the children commit or
        roll back with the manifest tile; the parent indexes the resource
        afterwards. Does nothing for a copy, for a tile whose data holds no
        manifest (a provisional edit empties it), or for a tile that is not in
        the manifest nodegroup. A manifest that cannot be read, or a model
        missing a node or list item, logs a warning and writes nothing.
        """
        if context == "copy":
            return
        manifest_node = role_node(*ROLES[rule.MANIFEST_ROLE])
        if manifest_node is None or str(tile.nodegroup_id) != str(
            manifest_node.nodegroup_id
        ):
            return
        if not (tile.data or {}).get(str(manifest_node.nodeid)):
            return
        try:
            with transaction.atomic():
                resource = Resource.objects.select_related("graph__publication").get(
                    pk=tile.resourceinstance_id
                )
                rule.write(rule.plan(resource.pk, tile), resource=resource)
        except rule.ImagingLayersError as error:
            logger.warning(
                _("Imaging layers not proposed for tile %(tile)s: %(error)s"),
                {"tile": tile.pk, "error": error},
            )

    def save(self, tile, request, context=None):
        raise NotImplementedError

    def delete(self, tile, request):
        raise NotImplementedError

    def on_import(self, tile):
        """Not implemented: the import reader calls it on a raw dict before any resource exists."""
        raise NotImplementedError

    def after_function_save(self, functionxgraph, request):
        raise NotImplementedError
