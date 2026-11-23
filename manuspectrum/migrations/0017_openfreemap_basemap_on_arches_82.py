"""Give an Arches 8.2 database the OpenFreeMap Bright basemap.

Arches 8.2 draws its `streets` basemap from the Maptoolkit `mtk` source and no
longer has Mapbox rows, so `0013_openfreemap_basemap`, which only replaces a
`streets` row drawing from `mapbox-streets`, leaves a fresh database on
Maptoolkit. Both paths end in the same state:

- a fresh 8.2 database: `streets` drawing from `mtk` takes the Bright layers;
- a database migrated from 8.1 (`0013` already installed Bright): `streets` is
  left alone;
- the `openfreemap` source exists (created when missing);
- the six sources Arches' `12913_migrate_to_maplibre` adds (`mtk`,
  `naturalearth`, `bathymetry_vector`, `rgb-tiles-blur-min|med|max`) are deleted
  once no layer draws from them; a source a project layer still uses is kept;
- sprite and glyph System Settings values equal to the Maptoolkit defaults of
  8.2 point to OpenFreeMap; any other value is left alone.

The values come from `0013_openfreemap_basemap.json`, the snapshot of the style
and of the `openfreemap` source. A later change of the style is a new migration.

Reverse changes nothing: the state this migration leaves is the state `0013`
leaves on an 8.1 database, and the Maptoolkit rows are Arches' to restore
(its own reverse of `12913` deletes them by name).
"""

import json
from pathlib import Path

from django.db import migrations

FROZEN = json.loads(
    (Path(__file__).with_name("0013_openfreemap_basemap.json")).read_text(
        encoding="utf-8"
    )
)

SPRITES_NODE_ID = "0e900254-4148-11e7-9902-c4b301baab9f"
GLYPHS_NODE_ID = "0e90031e-4148-11e7-a176-c4b301baab9f"
OPENFREEMAP_SOURCE_NAME = "openfreemap"
STREETS_LAYER_NAME = "streets"
MAPTOOLKIT_SOURCES = (
    "mtk",
    "naturalearth",
    "bathymetry_vector",
    "rgb-tiles-blur-min",
    "rgb-tiles-blur-med",
    "rgb-tiles-blur-max",
)
MAPTOOLKIT_SPRITES = "https://icons.maptoolkit.org/sprite"
MAPTOOLKIT_GLYPHS = "https://fonts.maptoolkit.org/{fontstack}/{range}.pbf"


def _references_source(layerdefinitions, source_name):
    if not isinstance(layerdefinitions, list):
        return False
    return any(
        isinstance(layer, dict) and layer.get("source") == source_name
        for layer in layerdefinitions
    )


def _swap_tile_value(TileModel, node_id, old, new):
    for tile in TileModel.objects.filter(data__has_key=node_id):
        node_data = tile.data.get(node_id)
        if not isinstance(node_data, dict):
            continue
        changed = False
        for localized in node_data.values():
            if isinstance(localized, dict) and localized.get("value") == old:
                localized["value"] = new
                changed = True
        if changed:
            tile.save(update_fields=["data"])


def forward(apps, schema_editor):
    MapSource = apps.get_model("models", "MapSource")
    MapLayer = apps.get_model("models", "MapLayer")
    TileModel = apps.get_model("models", "TileModel")

    MapSource.objects.get_or_create(
        name=OPENFREEMAP_SOURCE_NAME,
        defaults={"source": FROZEN["openfreemap_source"]},
    )

    streets = MapLayer.objects.filter(name=STREETS_LAYER_NAME).first()
    if streets and _references_source(streets.layerdefinitions, "mtk"):
        streets.layerdefinitions = FROZEN["bright_layers"]
        streets.save()

    layers = list(MapLayer.objects.all())
    for name in MAPTOOLKIT_SOURCES:
        if not any(
            _references_source(layer.layerdefinitions, name) for layer in layers
        ):
            MapSource.objects.filter(name=name).delete()

    _swap_tile_value(TileModel, SPRITES_NODE_ID, MAPTOOLKIT_SPRITES, FROZEN["sprites"])
    _swap_tile_value(TileModel, GLYPHS_NODE_ID, MAPTOOLKIT_GLYPHS, FROZEN["glyphs"])


class Migration(migrations.Migration):

    dependencies = [
        ("manuspectrum", "0016_workflow_plugin_access"),
        ("models", "12913_migrate_to_maplibre"),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
