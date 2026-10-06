"""Arches function proposing « Imaging layers » tiles when a manifest tile is saved.

The rule lives in :mod:`manuspectrum.utils.imaging_layers`; this function only
decides when to run it. It is registered and bound to the Analysis graph by
migration ``0007_imaging_layers_proposal``.
"""

import logging

from django.db import transaction

from arches.app.functions.base import BaseFunction
from arches.app.models.models import TileModel
from arches.app.models.resource import Resource

from manuspectrum.constants.imaging_layers import IMAGING_MANIFEST_NODEGROUP_ID
from manuspectrum.utils import imaging_layers as rule
from manuspectrum.utils.role_links import role_node
from manuspectrum.utils.roles import ROLES

logger = logging.getLogger(__name__)

PROPOSE_FOR = "_imaging_layers_propose_for"

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
    """Proposes layer tiles when a manifest tile is created or its manifest URL changes.

    ``save`` (Arches' pre-save hook, called before the tile is written) reads
    the stored ``TileModel`` and stashes on the tile instance the manifest URL
    being saved when the tile is new or that URL differs from the stored one.
    ``post_save`` proposes only for a stashed URL, so a layer a curator deleted
    on purpose is not proposed again when the same manifest is saved again.

    ``Tile.save`` replaces ``tile.data`` before ``post_save`` when the save is
    provisional (a non-reviewer: ``{}`` for a new tile, the stored data for an
    existing one). ``post_save`` therefore proposes only when the manifest URL
    in ``tile.data`` is still the stashed one; this holds for a save without
    ``request`` too, where the user cannot be read back. A reviewer approving
    an edit re-saves the tile with the edited URL and proposes then.

    Known limit: a resource imported from Arches JSON with its layer tiles
    receives duplicates. ``Resource.save`` saves the manifest tile before its
    children, and Arches passes the functions neither the resource nor its
    pending tiles (``Tile.save`` keeps ``resource`` for itself and the imported
    parent's ``tile.tiles`` is empty), so ``post_save`` cannot tell that the
    layers are coming.
    """

    def _manifest_node(self, tile):
        node = role_node(*ROLES[rule.MANIFEST_ROLE])
        if node is None or str(tile.nodegroup_id) != str(node.nodegroup_id):
            return None
        return str(node.nodeid)

    def save(self, tile, request, context=None):
        """Stash the manifest URL to propose for, when *tile* is new or its URL changes."""
        setattr(tile, PROPOSE_FOR, None)
        nodeid = self._manifest_node(tile)
        if nodeid is None:
            return
        url = rule.manifest_url((tile.data or {}).get(nodeid))
        if not url:
            return
        stored = (
            TileModel.objects.filter(pk=tile.pk).values_list("data", flat=True).first()
        )
        if stored is None or rule.manifest_url((stored or {}).get(nodeid)) != url:
            setattr(tile, PROPOSE_FOR, url)

    def post_save(self, tile, request, context=None):
        """Create the layer tiles the manifest of *tile* implies.

        Runs inside the atomic block of ``Tile.save``, so the children commit or
        roll back with the manifest tile; the parent indexes the resource
        afterwards. Does nothing for a copy, for a tile that is not in the
        manifest nodegroup, or when ``save`` stashed no URL (unchanged
        manifest) or the saved data no longer holds it (provisional edit). The
        proposal runs in a savepoint: any failure rolls the children back, logs
        a warning and keeps the manifest save.
        """
        if context == "copy":
            return
        url = getattr(tile, PROPOSE_FOR, None)
        nodeid = self._manifest_node(tile)
        if not url or nodeid is None:
            return
        if rule.manifest_url((tile.data or {}).get(nodeid)) != url:
            return
        try:
            with transaction.atomic():
                resource = Resource.objects.select_related("graph__publication").get(
                    pk=tile.resourceinstance_id
                )
                rule.write(rule.plan(resource.pk, tile), resource=resource)
        except rule.ImagingLayersError as error:
            logger.warning(
                "Imaging layers not proposed for tile %s: %s", tile.pk, error
            )
        except Exception:
            logger.warning(
                "Imaging layers not proposed for tile %s", tile.pk, exc_info=True
            )

    def delete(self, tile, request):
        raise NotImplementedError

    def on_import(self, tile):
        """Not implemented: the import reader calls it on a raw dict before any resource exists."""
        raise NotImplementedError

    def after_function_save(self, functionxgraph, request):
        raise NotImplementedError
