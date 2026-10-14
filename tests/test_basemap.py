"""The OpenFreeMap basemap: vendored style, settings, and data migration 0013.

The test database has already been through 0013, so each migration test first
runs `reverse` to get the rows Arches installs, then `forward` on them.
"""

import importlib
import json
import uuid
from pathlib import Path

from arches.app.models import models
from arches.app.models.system_settings import settings
from django.apps import apps
from django.conf import settings as django_settings
from django.test import SimpleTestCase, TestCase

from manuspectrum import basemaps

migration = importlib.import_module("manuspectrum.migrations.0013_openfreemap_basemap")

MAPBOX_SOURCES = ("mapbox-streets", "mapbox-satellite")
CORE_SOURCES = {*MAPBOX_SOURCES, "geocode-point", "search-query"}


def layer_names():
    return set(models.MapLayer.objects.values_list("name", flat=True))


def source_names():
    return set(models.MapSource.objects.values_list("name", flat=True))


class VendoredStyleTests(SimpleTestCase):
    def test_every_layer_draws_from_the_openfreemap_source_or_none(self):
        layers = basemaps.positron_layers()
        self.assertGreater(len(layers), 40)
        self.assertEqual(
            {layer.get("source") for layer in layers} - {None},
            {basemaps.OPENFREEMAP_SOURCE_NAME},
        )

    def test_layer_ids_are_unique_and_no_layer_needs_mapbox(self):
        layers = basemaps.positron_layers()
        ids = [layer["id"] for layer in layers]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("mapbox://", json.dumps(layers))

    def test_the_source_carries_the_attribution_openmaptiles_asks_for(self):
        attribution = basemaps.OPENFREEMAP_SOURCE["attribution"]
        for credit in ("OpenFreeMap", "OpenMapTiles", "OpenStreetMap"):
            self.assertIn(credit, attribution)

    def test_settings_point_at_the_openfreemap_sprite_and_glyphs(self):
        self.assertEqual(django_settings.MAPBOX_SPRITES, basemaps.SPRITES_URL)
        self.assertEqual(django_settings.MAPBOX_GLYPHS, basemaps.GLYPHS_URL)

    def test_core_map_rows_are_the_mapbox_ones(self):
        layers, sources = basemaps.core_map_rows()
        self.assertEqual(set(layers), {"satellite", "streets"})
        self.assertEqual(set(sources), CORE_SOURCES)


class FrozenSnapshotTests(SimpleTestCase):
    """Migration 0013 carries its own copy of every value it writes or expects."""

    frozen = migration.FROZEN

    def test_it_equals_the_live_openfreemap_values(self):
        self.assertEqual(self.frozen["positron_layers"], basemaps.positron_layers())
        self.assertEqual(self.frozen["openfreemap_source"], basemaps.OPENFREEMAP_SOURCE)
        self.assertEqual(self.frozen["sprites"], basemaps.SPRITES_URL)
        self.assertEqual(self.frozen["glyphs"], basemaps.GLYPHS_URL)

    def test_it_equals_the_core_rows_of_arches(self):
        layers, sources = basemaps.core_map_rows()
        self.assertEqual(self.frozen["core_layers"], layers)
        self.assertEqual(
            self.frozen["mapbox_sources"],
            {name: sources[name] for name in MAPBOX_SOURCES},
        )
        self.assertEqual(self.frozen["mapbox_sprites"], basemaps.MAPBOX_SPRITES_URL)
        self.assertEqual(self.frozen["mapbox_glyphs"], basemaps.MAPBOX_GLYPHS_URL)

    def test_the_migration_reads_nothing_else_at_run_time(self):
        source = Path(migration.__file__).read_text(encoding="utf-8")
        self.assertNotIn("basemaps", source.split('"""', 2)[2])
        self.assertNotIn("db_data", source.split('"""', 2)[2])


class SystemSettingsOverlayTests(SimpleTestCase):
    def test_the_overlay_carries_the_openfreemap_sprite_and_glyphs(self):
        text = (
            Path(django_settings.APP_ROOT) / "system_settings" / "System_Settings.json"
        ).read_text(encoding="utf-8")
        self.assertNotIn("mapbox://", text)
        data = json.loads(text)
        nodes = {}
        for resource in data["business_data"]["resources"]:
            for tile in resource["tiles"]:
                nodes.update(tile["data"])
        self.assertEqual(
            nodes[basemaps.SPRITES_NODE_ID]["en"]["value"], basemaps.SPRITES_URL
        )
        self.assertEqual(
            nodes[basemaps.GLYPHS_NODE_ID]["en"]["value"], basemaps.GLYPHS_URL
        )


class MigrationTests(TestCase):
    def forward(self):
        migration.forward(apps, None)

    def reverse(self):
        migration.reverse(apps, None)

    def tile(self, node_id, value, resource_id=None):
        graph, _ = models.GraphModel.objects.get_or_create(
            graphid=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID,
            defaults={"name": "Arches System Settings", "isresource": True},
        )
        resource, _ = models.ResourceInstance.objects.get_or_create(
            resourceinstanceid=resource_id or settings.SYSTEM_SETTINGS_RESOURCE_ID,
            defaults={"graph": graph},
        )
        group, _ = models.NodeGroup.objects.get_or_create(nodegroupid=node_id)
        return models.TileModel.objects.create(
            tileid=uuid.uuid4(),
            resourceinstance=resource,
            nodegroup=group,
            data={node_id: {"en": {"direction": "ltr", "value": value}}},
        )

    def value(self, tile):
        tile.refresh_from_db()
        (node_id,) = tile.data
        return tile.data[node_id]["en"]["value"]

    def test_the_migrated_database_has_only_the_openfreemap_basemap(self):
        self.assertEqual(layer_names(), {"streets"})
        self.assertEqual(
            source_names(), {"openfreemap", "geocode-point", "search-query"}
        )
        self.assertNotIn("mapzen", layer_names() | source_names())

    def test_forward_replaces_the_mapbox_rows_of_arches(self):
        self.reverse()
        self.assertEqual(layer_names(), {"satellite", "streets"})
        self.forward()
        self.assertEqual(layer_names(), {"streets"})
        self.assertEqual(
            models.MapLayer.objects.get(name="streets").layerdefinitions,
            basemaps.positron_layers(),
        )
        openfreemap = models.MapSource.objects.get(name="openfreemap")
        self.assertEqual(openfreemap.source, basemaps.OPENFREEMAP_SOURCE)
        self.assertFalse(source_names() & set(MAPBOX_SOURCES))

    def test_forward_twice_changes_nothing(self):
        self.reverse()
        self.forward()
        before = (
            list(models.MapLayer.objects.values_list("name", "layerdefinitions")),
            sorted(models.MapSource.objects.values_list("name", "source")),
        )
        self.forward()
        after = (
            list(models.MapLayer.objects.values_list("name", "layerdefinitions")),
            sorted(models.MapSource.objects.values_list("name", "source")),
        )
        self.assertEqual(before, after)

    def test_reverse_restores_the_rows_of_arches(self):
        self.reverse()
        core_layers, core_sources = basemaps.core_map_rows()
        self.assertEqual(
            {
                layer.name: layer.layerdefinitions
                for layer in models.MapLayer.objects.all()
            },
            core_layers,
        )
        self.assertEqual(
            {source.name: source.source for source in models.MapSource.objects.all()},
            core_sources,
        )

    def test_reverse_never_recreates_the_mapzen_rows_arches_deleted(self):
        self.reverse()
        self.assertNotIn("mapzen", layer_names() | source_names())

    def test_reverse_then_forward_then_reverse_is_stable(self):
        self.reverse()
        self.forward()
        self.reverse()
        self.assertEqual(layer_names(), {"satellite", "streets"})
        self.assertIn("mapbox-streets", source_names())
        self.assertNotIn("openfreemap", source_names())

    def test_a_streets_layer_the_project_replaced_is_left_alone(self):
        self.reverse()
        mine = [{"id": "mine", "type": "background"}]
        models.MapLayer.objects.filter(name="streets").update(layerdefinitions=mine)
        self.forward()
        self.assertEqual(
            models.MapLayer.objects.get(name="streets").layerdefinitions, mine
        )

    def test_a_source_a_project_layer_still_draws_from_is_kept(self):
        self.reverse()
        models.MapLayer.objects.create(
            name="mine",
            layerdefinitions=[
                {"id": "m", "type": "raster", "source": "mapbox-satellite"}
            ],
            icon="",
        )
        self.forward()
        self.assertIn("mapbox-satellite", source_names())
        self.assertNotIn("mapbox-streets", source_names())

    def test_a_changed_mapbox_source_is_kept(self):
        self.reverse()
        changed = {"type": "vector", "url": "mapbox://mine.tiles"}
        models.MapSource.objects.filter(name="mapbox-satellite").update(source=changed)
        self.forward()
        self.assertEqual(
            models.MapSource.objects.get(name="mapbox-satellite").source, changed
        )

    def test_sprites_and_glyphs_move_only_from_the_mapbox_defaults(self):
        sprites = self.tile(basemaps.SPRITES_NODE_ID, basemaps.MAPBOX_SPRITES_URL)
        glyphs = self.tile(basemaps.GLYPHS_NODE_ID, basemaps.MAPBOX_GLYPHS_URL)
        custom = self.tile(
            basemaps.SPRITES_NODE_ID, "https://sprites.example/s", uuid.uuid4()
        )
        self.forward()
        self.assertEqual(self.value(sprites), basemaps.SPRITES_URL)
        self.assertEqual(self.value(glyphs), basemaps.GLYPHS_URL)
        self.assertEqual(self.value(custom), "https://sprites.example/s")

    def test_reverse_puts_the_mapbox_defaults_back_on_the_openfreemap_values(self):
        sprites = self.tile(basemaps.SPRITES_NODE_ID, basemaps.SPRITES_URL)
        glyphs = self.tile(basemaps.GLYPHS_NODE_ID, basemaps.GLYPHS_URL)
        custom = self.tile(
            basemaps.GLYPHS_NODE_ID, "https://fonts.example/{range}", uuid.uuid4()
        )
        self.reverse()
        self.assertEqual(self.value(sprites), basemaps.MAPBOX_SPRITES_URL)
        self.assertEqual(self.value(glyphs), basemaps.MAPBOX_GLYPHS_URL)
        self.assertEqual(self.value(custom), "https://fonts.example/{range}")


class MigrationOrderTests(SimpleTestCase):
    def test_the_migration_runs_after_arches_removed_the_mapzen_rows(self):
        from importlib import import_module

        migration = import_module("manuspectrum.migrations.0013_openfreemap_basemap")
        self.assertIn(("models", "0010_4_1_0"), migration.Migration.dependencies)
