"""DB-backed tests for the two triggers that stamp the XY configuration.

They pin the rule under the write paths no Python ``save()`` ever sees:
``bulk_create``, a queryset ``update()``, and with them the raw SQL an ETL
import issues. Every assertion reads the row back from the database, since a
``BEFORE`` trigger rewrites ``NEW`` without Django hearing about it.

The migrated test database provides ``renderer_config`` (``manuspectrum.0002``)
and the triggers (``manuspectrum.0003``). A test run never loads the package,
so the Analysis graph and its nodegroups are created below; nodes are not,
because ``tiles.nodegroupid`` carries no foreign key and the triggers read tile
data rather than the graph.
"""

import io
import uuid

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from arches.app.models.models import (
    GraphModel,
    NodeGroup,
    ResourceInstance,
    TileModel,
)

from manuspectrum.constants.xy_presets import (
    ANALYSIS_GRAPH_ID,
    CONFIG_SOURCE_AUTO,
    CONFIG_SOURCE_KEY,
    CONFIG_SOURCE_MANUAL,
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
    TECHNIQUE_LIST_ID,
    TECHNIQUE_NODE_ID,
    TECHNIQUE_NODEGROUP_ID,
    XY_PRESETS,
    XY_RENDERER_ID,
)
from manuspectrum.functions.xy_technique_config import XYTechniqueConfig
from manuspectrum.models import RendererConfig

# The real TAPAC item ids live with the tests that first needed them.
from tests.test_xy_technique_config import FORS, FTIR, MICRO_XRF, PXRF, UNMAPPED

FORS_CONFIG = XY_PRESETS["fors"]["config_id"]
FTIR_REFLECTION_CONFIG = XY_PRESETS["ftir_reflection"]["config_id"]
XRF_CONFIG = XY_PRESETS["xrf"]["config_id"]

CURATOR_CONFIG = "11111111-1111-4111-8111-111111111111"
OTHER_RENDERER = "22222222-2222-4222-8222-222222222222"

#: Seeded by ``models.11042_add_resource_instance_lifecycle``.
DEFAULT_LIFECYCLE_ID = "7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75"


class XYTriggerTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.graph = GraphModel.objects.create(
            graphid=ANALYSIS_GRAPH_ID,
            name="Analysis",
            isresource=True,
            is_active=True,
            slug="xy-config-trigger-tests",
            resource_instance_lifecycle_id=DEFAULT_LIFECYCLE_ID,
        )
        NodeGroup.objects.create(nodegroupid=TECHNIQUE_NODEGROUP_ID, cardinality="1")
        NodeGroup.objects.create(nodegroupid=DATA_FILE_NODEGROUP_ID, cardinality="n")

    def analysis(self, *technique_item_ids):
        """A resource, with its technique tile when any technique is given."""
        resource = ResourceInstance.objects.create(graph=self.graph)
        if technique_item_ids:
            self.write_technique(resource, *technique_item_ids)
        return resource

    def write_technique(self, resource, *technique_item_ids):
        return TileModel.objects.create(
            resourceinstance=resource,
            nodegroup_id=TECHNIQUE_NODEGROUP_ID,
            data={TECHNIQUE_NODE_ID: self.reference_value(technique_item_ids)},
        )

    @staticmethod
    def reference_value(technique_item_ids):
        """The shape the reference datatype stores, as read off the database."""
        return [
            {
                "uri": "61296",
                "list_id": TECHNIQUE_LIST_ID,
                "labels": [
                    {
                        "id": str(uuid.uuid4()),
                        "value": "technique",
                        "language_id": "fr",
                        "list_item_id": item_id,
                        "valuetype_id": "prefLabel",
                    }
                ],
            }
            for item_id in technique_item_ids
        ]

    def write_files(self, resource, *entries):
        return TileModel.objects.create(
            resourceinstance=resource,
            nodegroup_id=DATA_FILE_NODEGROUP_ID,
            data={DATA_FILE_NODE_ID: list(entries)},
        )

    def stored_entries(self, tile):
        return TileModel.objects.get(pk=tile.pk).data[DATA_FILE_NODE_ID]


class FileWriteTriggerTests(XYTriggerTestCase):
    def test_bulk_create_stamps_an_untouched_csv(self):
        resource = self.analysis(FORS)

        (tile,) = TileModel.objects.bulk_create(
            [
                TileModel(
                    tileid=uuid.uuid4(),
                    resourceinstance=resource,
                    nodegroup_id=DATA_FILE_NODEGROUP_ID,
                    data={DATA_FILE_NODE_ID: [{"name": "spectrum.csv"}]},
                )
            ]
        )

        (entry,) = self.stored_entries(tile)
        self.assertEqual(entry["rendererConfig"], FORS_CONFIG)
        self.assertEqual(entry[CONFIG_SOURCE_KEY], CONFIG_SOURCE_AUTO)
        self.assertEqual(entry["renderer"], XY_RENDERER_ID)

    def test_an_entry_already_carrying_a_configuration_is_never_rewritten(self):
        tile = self.write_files(
            self.analysis(FORS),
            {"name": "spectrum.csv", "rendererConfig": CURATOR_CONFIG},
        )

        (entry,) = self.stored_entries(tile)
        self.assertEqual(entry["rendererConfig"], CURATOR_CONFIG)
        self.assertNotIn(CONFIG_SOURCE_KEY, entry)

    def test_a_configuration_a_curator_cleared_stays_cleared(self):
        tile = self.write_files(
            self.analysis(FORS),
            {"name": "spectrum.csv", CONFIG_SOURCE_KEY: CONFIG_SOURCE_MANUAL},
        )

        (entry,) = self.stored_entries(tile)
        self.assertNotIn("rendererConfig", entry)
        self.assertEqual(entry[CONFIG_SOURCE_KEY], CONFIG_SOURCE_MANUAL)

    def test_which_technique_sets_resolve_to_a_configuration(self):
        for label, techniques, expected in (
            ("one preset, reached twice", (PXRF, MICRO_XRF), XRF_CONFIG),
            (
                "an unmapped technique beside a mapped one",
                (FORS, UNMAPPED),
                FORS_CONFIG,
            ),
            ("presets that disagree", (FTIR, FORS), None),
            ("no technique at all", (), None),
        ):
            with self.subTest(label):
                tile = self.write_files(
                    self.analysis(*techniques), {"name": "spectrum.csv"}
                )

                (entry,) = self.stored_entries(tile)
                self.assertEqual(entry.get("rendererConfig"), expected)

    def test_a_malformed_technique_id_does_not_abort_the_write(self):
        tile = self.write_files(self.analysis("not-a-uuid"), {"name": "spectrum.csv"})

        self.assertEqual(self.stored_entries(tile), [{"name": "spectrum.csv"}])

    def test_a_technique_stored_as_a_bare_object_still_resolves(self):
        resource = ResourceInstance.objects.create(graph=self.graph)
        TileModel.objects.create(
            resourceinstance=resource,
            nodegroup_id=TECHNIQUE_NODEGROUP_ID,
            data={TECHNIQUE_NODE_ID: self.reference_value([FORS])[0]},
        )

        tile = self.write_files(resource, {"name": "spectrum.csv"})

        self.assertEqual(self.stored_entries(tile)[0]["rendererConfig"], FORS_CONFIG)

    def test_junk_entries_inside_the_list_are_passed_through(self):
        tile = self.write_files(self.analysis(FORS), {"name": "s.csv"}, "junk", 3)

        stamped, *rest = self.stored_entries(tile)
        self.assertEqual(stamped["rendererConfig"], FORS_CONFIG)
        self.assertEqual(rest, ["junk", 3])

    def test_only_a_csv_extension_is_stamped(self):
        resource = self.analysis(FORS)
        for name, stamped in (
            ("s.csv", True),
            ("S.CSV", True),
            ("raw.asd", False),
            ("noext", False),
            ("..csv", False),
        ):
            with self.subTest(name=name):
                tile = self.write_files(resource, {"name": name})

                (entry,) = self.stored_entries(tile)
                self.assertEqual(
                    entry.get("rendererConfig"),
                    FORS_CONFIG if stamped else None,
                )

    def test_a_queryset_update_is_stamped_too(self):
        tile = self.write_files(
            self.analysis(FORS),
            {"name": "spectrum.csv", "rendererConfig": CURATOR_CONFIG},
        )

        TileModel.objects.filter(pk=tile.pk).update(
            data={DATA_FILE_NODE_ID: [{"name": "spectrum.csv"}]}
        )

        (entry,) = self.stored_entries(tile)
        self.assertEqual(entry["rendererConfig"], FORS_CONFIG)
        self.assertEqual(entry[CONFIG_SOURCE_KEY], CONFIG_SOURCE_AUTO)

    def test_the_renderer_is_read_from_the_configurations_own_row(self):
        RendererConfig.objects.filter(configid=FORS_CONFIG).update(
            rendererid=OTHER_RENDERER
        )

        tile = self.write_files(self.analysis(FORS), {"name": "spectrum.csv"})

        (entry,) = self.stored_entries(tile)
        self.assertEqual(entry["renderer"], OTHER_RENDERER)
        self.assertEqual(entry["rendererConfig"], FORS_CONFIG)

    def test_a_renderer_already_named_is_kept(self):
        tile = self.write_files(
            self.analysis(FORS),
            {"name": "spectrum.csv", "renderer": OTHER_RENDERER},
        )

        (entry,) = self.stored_entries(tile)
        self.assertEqual(entry["renderer"], OTHER_RENDERER)
        self.assertEqual(entry["rendererConfig"], FORS_CONFIG)

    def test_the_order_of_the_file_entries_survives_stamping(self):
        tile = self.write_files(
            self.analysis(FORS),
            {"name": "z.csv"},
            {"name": "m.asd"},
            {"name": "a.csv"},
            {"name": "b.txt"},
        )

        entries = self.stored_entries(tile)
        self.assertEqual(
            [entry["name"] for entry in entries],
            ["z.csv", "m.asd", "a.csv", "b.txt"],
        )
        self.assertEqual(entries[0]["rendererConfig"], FORS_CONFIG)
        self.assertEqual(entries[2]["rendererConfig"], FORS_CONFIG)
        self.assertNotIn("rendererConfig", entries[1])
        self.assertNotIn("rendererConfig", entries[3])

    def test_a_tile_with_no_usable_file_value_is_written_without_error(self):
        resource = self.analysis(FORS)
        for label, data, expected in (
            ("key absent", {}, None),
            ("value null", {DATA_FILE_NODE_ID: None}, None),
            ("value not a list", {DATA_FILE_NODE_ID: "not-a-list"}, "not-a-list"),
            ("value empty list", {DATA_FILE_NODE_ID: []}, []),
        ):
            with self.subTest(label):
                tile = TileModel.objects.create(
                    resourceinstance=resource,
                    nodegroup_id=DATA_FILE_NODEGROUP_ID,
                    data=dict(data),
                )

                stored = TileModel.objects.get(pk=tile.pk)
                self.assertEqual(stored.data.get(DATA_FILE_NODE_ID), expected)


class TechniqueWriteTriggerTests(XYTriggerTestCase):
    def test_a_file_written_before_the_technique_is_backfilled(self):
        resource = self.analysis()
        tile = self.write_files(resource, {"name": "spectrum.csv"})
        self.assertEqual(self.stored_entries(tile), [{"name": "spectrum.csv"}])

        self.write_technique(resource, FTIR)

        (entry,) = self.stored_entries(tile)
        self.assertEqual(entry["rendererConfig"], FTIR_REFLECTION_CONFIG)
        self.assertEqual(entry[CONFIG_SOURCE_KEY], CONFIG_SOURCE_AUTO)
        self.assertEqual(entry["renderer"], XY_RENDERER_ID)

    def test_changing_the_technique_leaves_an_automatic_configuration_alone(self):
        resource = self.analysis(FTIR)
        tile = self.write_files(resource, {"name": "spectrum.csv"})

        technique = TileModel.objects.get(
            resourceinstance=resource, nodegroup_id=TECHNIQUE_NODEGROUP_ID
        )
        technique.data = {TECHNIQUE_NODE_ID: self.reference_value([FORS])}
        technique.save()

        (entry,) = self.stored_entries(tile)
        self.assertEqual(entry["rendererConfig"], FTIR_REFLECTION_CONFIG)

    def test_the_technique_trigger_reaches_only_its_own_analysis(self):
        neighbour = self.analysis()
        untouched = self.write_files(neighbour, {"name": "spectrum.csv"})

        self.write_technique(self.analysis(), FORS)

        self.assertEqual(self.stored_entries(untouched), [{"name": "spectrum.csv"}])


class TriggerInstallationTests(TestCase):
    def test_both_triggers_are_installed_and_enabled(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT tgname, tgenabled
                FROM pg_trigger
                WHERE tgrelid = 'tiles'::regclass AND tgname LIKE 'ms_xy_%'
                ORDER BY tgname
                """)
            installed = cursor.fetchall()

        self.assertEqual(
            installed,
            [("ms_xy_reapply_on_technique", "O"), ("ms_xy_stamp_file_config", "O")],
        )


class FunctionReloadTests(XYTriggerTestCase):
    def test_post_save_reloads_the_entries_the_trigger_stamped(self):
        tile = self.write_files(self.analysis(FORS), {"name": "spectrum.csv"})
        stale = TileModel(
            tileid=tile.pk,
            nodegroup_id=DATA_FILE_NODEGROUP_ID,
            data={DATA_FILE_NODE_ID: [{"name": "spectrum.csv"}]},
        )

        XYTechniqueConfig().post_save(stale, request=None)

        (entry,) = stale.data[DATA_FILE_NODE_ID]
        self.assertEqual(entry["rendererConfig"], FORS_CONFIG)
        self.assertEqual(entry["renderer"], XY_RENDERER_ID)

    def test_post_save_leaves_other_nodegroups_alone(self):
        technique = self.write_technique(self.analysis(), FORS)
        stale = TileModel(
            tileid=technique.pk, nodegroup_id=TECHNIQUE_NODEGROUP_ID, data={}
        )

        XYTechniqueConfig().post_save(stale, request=None)

        self.assertEqual(stale.data, {})


class BackfillCommandTests(XYTriggerTestCase):
    def write_files_without_the_trigger(self, resource, *entries):
        """Stock written before the trigger existed."""
        with connection.cursor() as cursor:
            # Arches' spatial trigger on tiles is deferred; ALTER TABLE is
            # refused while its events are pending, so fire them now.
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("ALTER TABLE tiles DISABLE TRIGGER ms_xy_stamp_file_config")
        try:
            return self.write_files(resource, *entries)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE tiles ENABLE TRIGGER ms_xy_stamp_file_config"
                )

    def run_command(self, *args):
        out = io.StringIO()
        call_command("backfill_xy_technique_config", *args, stdout=out)
        return out.getvalue()

    def test_a_dry_run_reports_without_writing(self):
        tile = self.write_files_without_the_trigger(
            self.analysis(FORS), {"name": "spectrum.csv"}
        )

        report = self.run_command()

        self.assertIn("1 file(s) configured", report)
        self.assertIn("dry run", report)
        self.assertEqual(self.stored_entries(tile), [{"name": "spectrum.csv"}])

    def test_apply_stamps_the_stock_and_nothing_else(self):
        resource = self.analysis(FORS)
        stock = self.write_files_without_the_trigger(resource, {"name": "old.csv"})
        curated = self.write_files_without_the_trigger(
            resource, {"name": "mine.csv", "rendererConfig": CURATOR_CONFIG}
        )

        report = self.run_command("--apply")

        self.assertIn("1 file(s) configured", report)
        (entry,) = self.stored_entries(stock)
        self.assertEqual(entry["rendererConfig"], FORS_CONFIG)
        self.assertEqual(entry[CONFIG_SOURCE_KEY], CONFIG_SOURCE_AUTO)
        (entry,) = self.stored_entries(curated)
        self.assertEqual(entry["rendererConfig"], CURATOR_CONFIG)

    def test_the_resource_option_narrows_the_touch(self):
        stock = self.write_files_without_the_trigger(
            self.analysis(FORS), {"name": "old.csv"}
        )
        other = self.write_files_without_the_trigger(
            self.analysis(FORS), {"name": "other.csv"}
        )

        self.run_command("--apply", "--resource", str(stock.resourceinstance_id))

        self.assertIn("rendererConfig", self.stored_entries(stock)[0])
        self.assertNotIn("rendererConfig", self.stored_entries(other)[0])
