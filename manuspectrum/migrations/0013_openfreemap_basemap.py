"""Replace the Mapbox basemaps of Arches with the OpenFreeMap Positron basemap.

Forward, each step only when the row still is a Mapbox one (a source equal to
Arches' own, a layer drawing from it), so a row replaced in the designer is left
alone and a second run changes nothing:
- `streets` takes the Positron layers drawn from the `openfreemap` source;
- the `satellite` basemap (Mapbox) is deleted;
- the `mapbox-streets` and `mapbox-satellite` sources are deleted once no layer
  draws from them;
- the sprite and glyph System Settings values that equal the `mapbox://`
  defaults point to OpenFreeMap.

Arches' own `0010_4_1_0` already deleted the `mapzen` source and layer: they are
neither handled nor recreated. Reverse gives back the rows of an Arches 8.1
database before this migration: `satellite`, `streets` with its core
definitions, the `mapbox-streets` and `mapbox-satellite` sources, and the
`mapbox://` defaults of the sprite and glyph values.

Every value comes from `0013_openfreemap_basemap.json`, frozen next to this
file: Arches' core rows as `db_data.sql` installs them, and the Positron layers
and `openfreemap` source as of 2026-10-13. Nothing is read from `basemaps.py` or
Arches at run time, so a later change of the style is a new migration
(`tests/test_basemap.py` fails until the snapshot is revisited on purpose).

The sprite and glyph tiles are rewritten here for EXISTING databases. A fresh
`setup_db` takes them from the System Settings overlay
(`manuspectrum/system_settings/System_Settings.json` in dev, the package under
`make init`), which already carries the OpenFreeMap values.

A running process keeps the sprite and glyph values it read at start
(`update_from_db`): restart it after the migration.
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
SATELLITE_LAYER_NAME = "satellite"
MAPBOX_SOURCES = ("mapbox-streets", "mapbox-satellite")


def _references_source(layerdefinitions, source_name):
    if not isinstance(layerdefinitions, list):
        return False
    return any(
        isinstance(layer, dict) and layer.get("source") == source_name
        for layer in layerdefinitions
    )


def _delete_source_if(MapSource, MapLayer, name, expected):
    """Delete the source when it still equals `expected` and no layer uses it."""
    source = MapSource.objects.filter(name=name).first()
    if source is None or source.source != expected:
        return
    if any(
        _references_source(layer.layerdefinitions, name)
        for layer in MapLayer.objects.all()
    ):
        return
    source.delete()


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
    if streets and _references_source(streets.layerdefinitions, "mapbox-streets"):
        streets.layerdefinitions = FROZEN["positron_layers"]
        streets.save()

    satellite = MapLayer.objects.filter(name=SATELLITE_LAYER_NAME).first()
    if satellite and _references_source(satellite.layerdefinitions, "mapbox-satellite"):
        satellite.delete()

    for name in MAPBOX_SOURCES:
        _delete_source_if(MapSource, MapLayer, name, FROZEN["mapbox_sources"][name])

    _swap_tile_value(
        TileModel, SPRITES_NODE_ID, FROZEN["mapbox_sprites"], FROZEN["sprites"]
    )
    _swap_tile_value(
        TileModel, GLYPHS_NODE_ID, FROZEN["mapbox_glyphs"], FROZEN["glyphs"]
    )


def reverse(apps, schema_editor):
    MapSource = apps.get_model("models", "MapSource")
    MapLayer = apps.get_model("models", "MapLayer")
    TileModel = apps.get_model("models", "TileModel")

    for name in MAPBOX_SOURCES:
        MapSource.objects.get_or_create(
            name=name, defaults={"source": FROZEN["mapbox_sources"][name]}
        )

    MapLayer.objects.get_or_create(
        name=SATELLITE_LAYER_NAME,
        defaults={
            "layerdefinitions": FROZEN["core_layers"][SATELLITE_LAYER_NAME],
            "isoverlay": False,
            "icon": "",
            "activated": True,
            "addtomap": False,
        },
    )

    streets = MapLayer.objects.filter(name=STREETS_LAYER_NAME).first()
    if streets and _references_source(
        streets.layerdefinitions, OPENFREEMAP_SOURCE_NAME
    ):
        streets.layerdefinitions = FROZEN["core_layers"][STREETS_LAYER_NAME]
        streets.save()

    _delete_source_if(
        MapSource,
        MapLayer,
        OPENFREEMAP_SOURCE_NAME,
        FROZEN["openfreemap_source"],
    )

    _swap_tile_value(
        TileModel, SPRITES_NODE_ID, FROZEN["sprites"], FROZEN["mapbox_sprites"]
    )
    _swap_tile_value(
        TileModel, GLYPHS_NODE_ID, FROZEN["glyphs"], FROZEN["mapbox_glyphs"]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("manuspectrum", "0012_restriction_verbose_names"),
        ("models", "0010_4_1_0"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
