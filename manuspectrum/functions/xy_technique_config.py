"""Arches function on the measurement-file nodegroup of the Analysis graph.

The XY viewer configuration a file receives from its analysis technique is
applied by two PostgreSQL triggers on the ``tiles`` table (declared in
:mod:`manuspectrum.sql_config`, bodies in ``manuspectrum/sql/triggers/``), so
that every write path is covered: card UI, workflows, ``bulk_create``, ETL.
The mapping itself lives in :mod:`manuspectrum.constants.xy_presets`.

This function does what a trigger cannot:

* complete each file entry's localised metadata before the write, a shape
  invariant the upload widget expects (see :func:`normalize_metadata`);
* after the write, reload the row the trigger just stamped into ``tile.data``,
  so the response Arches serialises back to the browser carries the
  configuration and the XY reader mounts without a page reload.
"""

from arches.app.functions.base import BaseFunction
from arches.app.models.models import TileModel

from manuspectrum.utils.file_entries import normalize_metadata
from manuspectrum.constants.xy_presets import (
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
)

details = {
    "functionid": "0f5a9c74-8e21-4c3d-b6f7-91d2ae4c5b08",
    "name": "XY Technique Configuration",
    # Deliberately NOT "primarydescriptors": Arches excludes that type from the
    # tile save/delete hooks entirely (see Tile._getFunctionClassInstances).
    "type": "node",
    "description": (
        "Applies a default XY viewer configuration to measurement files, "
        "derived from the analysis technique, without ever overwriting a "
        "configuration chosen by a curator."
    ),
    "defaultconfig": {"triggering_nodegroups": [DATA_FILE_NODEGROUP_ID]},
    "classname": "XYTechniqueConfig",
    "component": "views/components/functions/xy-technique-config",
}


class XYTechniqueConfig(BaseFunction):
    def save(self, tile, request, context=None):
        """Give every file entry the localised metadata the widget expects.

        Unconditional: the widget hydrates every missing language when it
        renders, mutating tile.data in place, and `tile.dirty` then reports
        unsaved edits on a card nobody touched.
        """
        if str(tile.nodegroup_id) == DATA_FILE_NODEGROUP_ID:
            for entry in tile.data.get(DATA_FILE_NODE_ID) or []:
                normalize_metadata(entry)
        return tile

    def post_save(self, tile, request, context=None):
        """Reload ``tile.data`` from the row the trigger has just rewritten.

        A BEFORE trigger changes the stored row without Django hearing about
        it; the in-memory tile is stale until read back.
        """
        if str(tile.nodegroup_id) != DATA_FILE_NODEGROUP_ID:
            return
        stored = (
            TileModel.objects.filter(pk=tile.pk).values_list("data", flat=True).first()
        )
        if stored is not None:
            tile.data = stored

    def delete(self, tile, request):
        raise NotImplementedError

    def on_import(self, tile):
        raise NotImplementedError

    def after_function_save(self, functionxgraph, request):
        raise NotImplementedError
