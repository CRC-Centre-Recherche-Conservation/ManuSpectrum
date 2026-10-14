"""Replace the Mapbox basemaps of Arches with the OpenFreeMap Positron basemap.

Forward, each step only when the row still is a Mapbox one (a source equal to
Arches' own, a layer drawing from it), so a row replaced in the designer is left
alone and a second run changes nothing:
- `streets` takes the Positron layers drawn from the `openfreemap` source;
- the `satellite` basemap (Mapbox) and the `mapzen` basemap (a service shut down
  in 2018) are deleted;
- the `mapbox-streets`, `mapbox-satellite` and `mapzen` sources are deleted once
  no layer draws from them;
- the sprite and glyph System Settings values that equal the `mapbox://`
  defaults point to OpenFreeMap.

Reverse puts back the rows of Arches' `db_data.sql` and the `mapbox://`
defaults of the same two values.

A running process keeps the sprite and glyph values it read at start
(`update_from_db`): restart it after the migration.
"""

import json

from django.db import migrations

from manuspectrum import basemaps

# (layer, source) of the Arches basemaps with no OpenFreeMap counterpart.
DROPPED_BASEMAPS = (
    (basemaps.SATELLITE_LAYER_NAME, "mapbox-satellite"),
    ("mapzen", "mapzen"),
)


def _delete_source_if(MapSource, MapLayer, name, expected):
    """Delete the source when it still equals `expected` and no layer uses it."""
    source = MapSource.objects.filter(name=name).first()
    if source is None or source.source != expected:
        return
    if any(
        basemaps.references_source(layer.layerdefinitions, name)
        for layer in MapLayer.objects.all()
    ):
        return
    source.delete()


def _restore_source(MapSource, name, expected):
    MapSource.objects.get_or_create(name=name, defaults={"source": expected})


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
    _, core_sources = basemaps.core_map_rows()

    MapSource.objects.get_or_create(
        name=basemaps.OPENFREEMAP_SOURCE_NAME,
        defaults={"source": basemaps.OPENFREEMAP_SOURCE},
    )

    streets = MapLayer.objects.filter(name=basemaps.STREETS_LAYER_NAME).first()
    if streets and basemaps.references_source(
        streets.layerdefinitions, "mapbox-streets"
    ):
        streets.layerdefinitions = basemaps.positron_layers()
        streets.save()

    for layer_name, source_name in DROPPED_BASEMAPS:
        dropped = MapLayer.objects.filter(name=layer_name).first()
        if dropped and basemaps.references_source(
            dropped.layerdefinitions, source_name
        ):
            dropped.delete()

    for name in ("mapbox-streets", "mapbox-satellite", "mapzen"):
        if name in core_sources:
            _delete_source_if(MapSource, MapLayer, name, core_sources[name])

    _swap_tile_value(
        TileModel,
        basemaps.SPRITES_NODE_ID,
        basemaps.MAPBOX_SPRITES_URL,
        basemaps.SPRITES_URL,
    )
    _swap_tile_value(
        TileModel,
        basemaps.GLYPHS_NODE_ID,
        basemaps.MAPBOX_GLYPHS_URL,
        basemaps.GLYPHS_URL,
    )


def reverse(apps, schema_editor):
    MapSource = apps.get_model("models", "MapSource")
    MapLayer = apps.get_model("models", "MapLayer")
    TileModel = apps.get_model("models", "TileModel")
    core_layers, core_sources = basemaps.core_map_rows()

    for name in ("mapbox-streets", "mapbox-satellite", "mapzen"):
        if name in core_sources:
            _restore_source(MapSource, name, core_sources[name])

    for layer_name, _ in DROPPED_BASEMAPS:
        if layer_name in core_layers:
            MapLayer.objects.get_or_create(
                name=layer_name,
                defaults={
                    "layerdefinitions": core_layers[layer_name],
                    "isoverlay": False,
                    "icon": "",
                    "activated": True,
                    "addtomap": False,
                },
            )

    streets = MapLayer.objects.filter(name=basemaps.STREETS_LAYER_NAME).first()
    if (
        streets
        and basemaps.STREETS_LAYER_NAME in core_layers
        and basemaps.references_source(
            streets.layerdefinitions, basemaps.OPENFREEMAP_SOURCE_NAME
        )
    ):
        streets.layerdefinitions = core_layers[basemaps.STREETS_LAYER_NAME]
        streets.save()

    _delete_source_if(
        MapSource,
        MapLayer,
        basemaps.OPENFREEMAP_SOURCE_NAME,
        json.loads(json.dumps(basemaps.OPENFREEMAP_SOURCE)),
    )

    _swap_tile_value(
        TileModel,
        basemaps.SPRITES_NODE_ID,
        basemaps.SPRITES_URL,
        basemaps.MAPBOX_SPRITES_URL,
    )
    _swap_tile_value(
        TileModel,
        basemaps.GLYPHS_NODE_ID,
        basemaps.GLYPHS_URL,
        basemaps.MAPBOX_GLYPHS_URL,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("manuspectrum", "0012_restriction_verbose_names"),
        ("models", "12586_tile_cardinality_check"),
    ]

    operations = [migrations.RunPython(forward, reverse)]
