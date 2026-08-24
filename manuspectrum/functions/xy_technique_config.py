"""Give every measurement file a sensible XY viewer configuration, once.

An analysis records the technique it used ("Fluorescence X portable", "IRTF",
"Spectrométrie de réflectance par fibre optique"…). That technique determines
the axes the resulting spectrum should be plotted against — energy in keV for
XRF, a *reversed* wavenumber axis for FTIR, m/z for MALDI. Asking every data
producer to pick that configuration by hand is both tedious and error-prone:
of the five configurations assigned manually before this function existed, two
were on the wrong kind of spectrum.

So the mapping fills the blank, and only the blank:

* it acts when a data file is saved, and when a technique is chosen — either
  order works, since producers upload files before and after tagging;
* it only ever writes to a file entry that has **no** configuration and no
  provenance marker. A curator's choice is never overwritten, never re-derived,
  and never restored after they clear it;
* when an analysis carries several techniques that map to different presets, it
  writes nothing. A wrong axis label is worse than a missing one.

The mapping itself lives in :mod:`manuspectrum.constants.xy_presets`.

Note that :meth:`save` runs *before* Arches writes the tile, so mutating
``tile.data`` in place costs no extra query — which is the common case here.
Only the technique-side trigger has to reach out and save sibling tiles.
"""

import logging
import os

from django.utils.translation import gettext as _
from django.conf import settings

from arches.app.functions.base import BaseFunction
from arches.app.models.models import TileModel
from arches.app.models.tile import Tile

from manuspectrum.constants.xy_presets import (
    ANALYSIS_GRAPH_ID,
    CONFIG_SOURCE_AUTO,
    CONFIG_SOURCE_KEY,
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
    TECHNIQUE_NODE_ID,
    TECHNIQUE_NODEGROUP_ID,
    XY_RENDERER_ID,
    config_id_for_techniques,
)

logger = logging.getLogger(__name__)


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
    "defaultconfig": {
        "triggering_nodegroups": [
            TECHNIQUE_NODEGROUP_ID,
            DATA_FILE_NODEGROUP_ID,
        ]
    },
    "classname": "XYTechniqueConfig",
    "component": "views/components/functions/xy-technique-config",
}


def technique_ids_from_tile_data(data):
    """Extract controlled-list item ids from a reference-datatype tile value."""
    value = data.get(TECHNIQUE_NODE_ID) if data else None
    if not value:
        return []
    if isinstance(value, dict):
        value = [value]
    ids = []
    for item in value:
        if isinstance(item, dict):
            for label in item.get("labels") or []:
                item_id = label.get("list_item_id")
                if item_id:
                    ids.append(str(item_id))
                    break
    return ids


def is_xy_text_file(entry):
    """True when the uploaded file is a text format the XY reader can parse."""
    name = entry.get("name") or ""
    extension = os.path.splitext(name)[1].lstrip(".").lower()
    return extension in settings.XY_TEXT_FILE_FORMATS


def apply_config_to_file_entries(entries, config_id):
    """Stamp renderer + config onto untouched file entries.

    Returns the number of entries changed, so callers can skip a write when
    there is nothing to do.
    """
    if not config_id:
        return 0

    changed = 0
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        # A curator has already spoken — about the config, or by clearing it.
        if entry.get("rendererConfig") or entry.get(CONFIG_SOURCE_KEY):
            continue
        if not is_xy_text_file(entry):
            continue

        entry["rendererConfig"] = config_id
        entry[CONFIG_SOURCE_KEY] = CONFIG_SOURCE_AUTO
        # Without a renderer the config pointer is inert: Arches only matches
        # renderers at upload time, and only on an exact extension match.
        if not entry.get("renderer"):
            entry["renderer"] = XY_RENDERER_ID
        changed += 1
    return changed


def resolve_config_id(resourceinstance_id):
    """Look up an analysis's technique tile and resolve it to a config id."""
    data = (
        TileModel.objects.filter(
            resourceinstance_id=resourceinstance_id,
            nodegroup_id=TECHNIQUE_NODEGROUP_ID,
        )
        .values_list("data", flat=True)
        .first()
    )
    return config_id_for_techniques(technique_ids_from_tile_data(data))


class XYTechniqueConfig(BaseFunction):
    def save(self, tile, request, context=None):
        nodegroup_id = str(tile.nodegroup_id)

        if nodegroup_id == DATA_FILE_NODEGROUP_ID:
            self._on_file_saved(tile)
        elif nodegroup_id == TECHNIQUE_NODEGROUP_ID:
            self._on_technique_saved(tile, request)

        return tile

    def _on_file_saved(self, tile):
        """Fill in the files being saved, in place — no extra write."""
        config_id = resolve_config_id(tile.resourceinstance_id)
        if not config_id:
            return
        apply_config_to_file_entries(tile.data.get(DATA_FILE_NODE_ID), config_id)

    def _on_technique_saved(self, tile, request):
        """Backfill files uploaded before the technique was known."""
        config_id = config_id_for_techniques(technique_ids_from_tile_data(tile.data))
        if not config_id:
            return

        siblings = TileModel.objects.filter(
            resourceinstance_id=tile.resourceinstance_id,
            nodegroup_id=DATA_FILE_NODEGROUP_ID,
        )
        for sibling in siblings:
            entries = sibling.data.get(DATA_FILE_NODE_ID)
            if not apply_config_to_file_entries(entries, config_id):
                continue
            try:
                # The proxy re-enters this function on the file nodegroup, where
                # every entry now carries a provenance marker and is skipped —
                # so it converges after one pass. index=False keeps the extra
                # Elasticsearch write out of the enclosing transaction.
                proxy = Tile.objects.get(pk=sibling.tileid)
                proxy.data = sibling.data
                proxy.save(request=request, index=False)
            except Exception:
                logger.exception(
                    _("Could not apply the XY configuration to tile %s")
                    % sibling.tileid
                )

    def post_save(self, tile, request, context=None):
        raise NotImplementedError

    def delete(self, tile, request):
        raise NotImplementedError

    def on_import(self, tile):
        raise NotImplementedError

    def after_function_save(self, functionxgraph, request):
        raise NotImplementedError
