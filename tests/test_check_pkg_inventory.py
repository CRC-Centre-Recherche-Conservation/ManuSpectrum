"""Guards for the check_pkg_inventory command.

Each test exports the inventory of the test database with `export_pkg`, then
changes the database in one way and expects the command to name the difference
and fail (exit 1). The unchanged database passes.
"""

import json
import tempfile
import uuid
from io import StringIO
from pathlib import Path
from unittest import mock

from arches.app.models import models
from arches.app.models.system_settings import settings
from django.core.management import call_command
from django.core.management.base import CommandError, OutputWrapper
from django.db import InternalError
from django.utils import timezone
from django.test import TestCase

from arches_controlled_lists.models import List, ListItem, ListItemValue

from manuspectrum.management.commands import check_pkg_inventory
from tests.test_export_pkg import ORIGIN, SETTINGS_NODES, make_list


class CheckPkgInventoryTests(TestCase):
    def setUp(self):
        for model in (List, ListItem, ListItemValue):
            for method in ("index", "delete_index"):
                if hasattr(model, method):
                    patcher = mock.patch.object(model, method)
                    patcher.start()
                    self.addCleanup(patcher.stop)
        for code in ("en", "fr"):
            models.Language.objects.get_or_create(
                code=code,
                defaults={"name": code, "default_direction": "ltr", "scope": "system"},
            )
        graph, _ = models.GraphModel.objects.get_or_create(
            graphid=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID,
            defaults={"name": "Arches System Settings", "isresource": True},
        )
        for alias, node_id in SETTINGS_NODES.items():
            group, _ = models.NodeGroup.objects.get_or_create(nodegroupid=node_id)
            models.Node.objects.get_or_create(
                nodeid=node_id,
                defaults={
                    "graph": graph,
                    "alias": alias,
                    "name": alias,
                    "datatype": "string",
                    "nodegroup": group,
                    "istopnode": False,
                },
            )
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.controlled_list, self.items = make_list(
            "Units",
            [
                (0, None, {"en": "Gram", "fr": "Gramme"}, "https://example.org/g"),
                (1, None, {"en": "Metre"}, "https://example.org/m"),
                (0, 0, {"en": "Milligram"}, "https://example.org/mg"),
            ],
            searchable=True,
        )
        namespace = mock.patch.object(
            settings, "ARCHES_NAMESPACE_FOR_DATA_EXPORT", ORIGIN
        )
        self.inventory_path = self.export_inventory()
        namespace.start()
        self.addCleanup(namespace.stop)

    def export_inventory(self):
        out = self.base / "pkg"
        call_command(
            "export_pkg",
            out=str(out),
            public_origin=ORIGIN,
            force=True,
            stdout=StringIO(),
        )
        return out / "expected-inventory.json"

    def check(self):
        stdout = StringIO()
        call_command("check_pkg_inventory", str(self.inventory_path), stdout=stdout)
        return stdout.getvalue()

    def failure(self):
        with self.assertRaises(CommandError) as raised:
            self.check()
        return str(raised.exception)

    def test_the_database_the_inventory_was_written_from_passes(self):
        output = self.check()
        self.assertIn("Inventory check passed", output)
        self.assertNotIn("WARNING", output)

    def test_a_missing_item_is_reported_with_its_list(self):
        ListItem.objects.filter(pk=self.items[1].pk).delete()
        message = self.failure()
        self.assertIn("controlled_lists.items", message)
        self.assertIn(f"list Units ({self.controlled_list.id}) items", message)

    def test_a_missing_value_is_reported(self):
        ListItemValue.objects.filter(list_item=self.items[0], language_id="fr").delete()
        self.assertIn("values: expected 4, found 3", self.failure())

    def test_a_changed_value_with_the_same_count_is_reported(self):
        ListItemValue.objects.filter(list_item=self.items[0], language_id="fr").update(
            value="Gramme!"
        )
        message = self.failure()
        self.assertIn("digest_values", message)
        self.assertNotIn(" values: expected", message)

    def test_a_changed_language_with_the_same_count_is_reported(self):
        ListItemValue.objects.filter(list_item=self.items[1]).update(language_id="fr")
        self.assertIn("digest_values", self.failure())

    def test_a_changed_sort_order_is_reported(self):
        ListItem.objects.filter(pk=self.items[0].pk).update(sortorder=5)
        ListItem.objects.filter(pk=self.items[1].pk).update(sortorder=-1)
        self.assertIn("digest_sibling_rank", self.failure())

    def test_a_moved_item_is_reported(self):
        ListItem.objects.filter(pk=self.items[2].pk).update(
            parent=self.items[1], sortorder=0
        )
        self.assertIn("digest_sibling_rank", self.failure())

    def test_a_list_that_is_not_searchable_is_reported(self):
        List.objects.filter(pk=self.controlled_list.pk).update(searchable=False)
        message = self.failure()
        self.assertIn("controlled_lists.searchable", message)
        self.assertIn("Units", message)

    def test_a_missing_list_and_a_ghost_list_are_reported(self):
        ghost, _ = make_list("Ghost")
        message = self.failure()
        self.assertIn("controlled_lists.lists", message)
        self.assertIn(str(ghost.id), message)

    def test_a_ghost_graph_is_reported(self):
        models.GraphModel.objects.create(
            name="Ghost model", isresource=True, slug="ghost-model"
        )
        message = self.failure()
        self.assertIn("graphs.resource_models", message)
        self.assertIn("Ghost model.json", message)

    def test_a_draft_graph_is_not_a_ghost(self):
        source = models.GraphModel.objects.create(
            name="Source", isresource=True, slug="source"
        )
        models.GraphModel.objects.create(
            name="Source draft", isresource=True, source_identifier=source
        )
        message = self.failure()
        self.assertIn("Source.json", message)
        self.assertNotIn("Source draft.json", message)

    def publish(self, graph, current=True):
        publication = models.GraphXPublishedGraph.objects.create(
            graph=graph, notes="test", published_time=timezone.now()
        )
        for code, _ in settings.LANGUAGES:
            models.PublishedGraph.objects.create(
                publication=publication, language_id=code, serialized_graph={}
            )
        if current:
            models.GraphModel.objects.filter(pk=graph.pk).update(
                publication=publication
            )
        return publication

    def inventory_with_graph(self, name):
        for code, _ in settings.LANGUAGES:
            models.Language.objects.get_or_create(
                code=code,
                defaults={"name": code, "default_direction": "ltr", "scope": "system"},
            )
        graph = models.GraphModel.objects.create(
            name=name, isresource=True, slug=name.lower()
        )
        self.publish(graph)
        inventory = json.loads(self.inventory_path.read_text("utf-8"))
        inventory["graphs"]["resource_models"] = [f"{name}.json"]
        inventory["graphs"]["published"] = [
            f"{name}|{code}" for code, _ in settings.LANGUAGES
        ]
        self.inventory_path.write_text(json.dumps(inventory), "utf-8")
        return graph

    def test_the_publication_history_of_a_graph_is_not_counted(self):
        graph = self.inventory_with_graph("Model")
        self.assertIn("Inventory check passed", self.check())
        self.publish(graph, current=False)
        self.publish(graph, current=False)
        self.assertIn("Inventory check passed", self.check())

    def test_a_missing_current_publication_is_reported(self):
        graph = self.inventory_with_graph("Model")
        models.PublishedGraph.objects.filter(
            publication_id=graph.publication_id
            or models.GraphModel.objects.get(pk=graph.pk).publication_id,
            language_id="fr",
        ).delete()
        message = self.failure()
        self.assertIn("graphs.published", message)
        self.assertIn("Model|fr", message)

    def test_a_moved_item_is_reported_even_when_the_origin_differs(self):
        ListItem.objects.filter(pk=self.items[2].pk).update(
            parent=self.items[1], sortorder=0
        )
        with mock.patch.object(
            settings, "ARCHES_NAMESPACE_FOR_DATA_EXPORT", "https://rehearsal.test/"
        ):
            with self.assertRaises(CommandError) as raised:
                self.check()
        self.assertIn("digest_items", str(raised.exception))
        self.assertNotIn("digest_sibling_rank", str(raised.exception))

    def test_a_non_empty_mapbox_key_is_reported(self):
        resource = models.ResourceInstance.objects.create(
            resourceinstanceid=settings.SYSTEM_SETTINGS_RESOURCE_ID,
            graph_id=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID,
        )
        models.TileModel.objects.create(
            tileid=uuid.uuid4(),
            resourceinstance=resource,
            nodegroup_id=SETTINGS_NODES["mapbox_api_key"],
            data={SETTINGS_NODES["mapbox_api_key"]: {"en": {"value": "secret"}}},
        )
        self.assertIn("the Mapbox key is not empty", self.failure())

    def test_an_empty_mapbox_key_passes(self):
        resource = models.ResourceInstance.objects.create(
            resourceinstanceid=settings.SYSTEM_SETTINGS_RESOURCE_ID,
            graph_id=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID,
        )
        models.TileModel.objects.create(
            tileid=uuid.uuid4(),
            resourceinstance=resource,
            nodegroup_id=SETTINGS_NODES["mapbox_api_key"],
            data={SETTINGS_NODES["mapbox_api_key"]: {"en": {"value": ""}}},
        )
        self.assertIn("Inventory check passed", self.check())

    def test_a_count_of_the_database_section_is_reported(self):
        models.Plugin.objects.create(
            name="extra",
            icon="x",
            component="views/x",
            componentname="extra",
            slug="extra",
        )
        self.assertIn("database.plugins", self.failure())

    def test_another_origin_warns_and_skips_only_the_order_digest(self):
        ListItem.objects.filter(pk=self.items[0].pk).update(sortorder=5)
        ListItem.objects.filter(pk=self.items[1].pk).update(sortorder=-1)
        with mock.patch.object(
            settings, "ARCHES_NAMESPACE_FOR_DATA_EXPORT", "https://rehearsal.test/"
        ):
            output = self.check()
        self.assertIn("WARNING: list sort orders were not loaded", output)
        self.assertIn("https://rehearsal.test/", output)
        self.assertIn("Inventory check passed", output)

    def test_another_origin_still_compares_everything_else(self):
        ListItemValue.objects.filter(list_item=self.items[0], language_id="fr").update(
            value="changed"
        )
        with mock.patch.object(
            settings, "ARCHES_NAMESPACE_FOR_DATA_EXPORT", "https://rehearsal.test/"
        ):
            with self.assertRaises(CommandError) as raised:
                self.check()
        self.assertIn("digest_values", str(raised.exception))

    def test_the_origin_is_compared_exactly_not_without_its_slash(self):
        with mock.patch.object(
            settings,
            "ARCHES_NAMESPACE_FOR_DATA_EXPORT",
            ORIGIN.rstrip("/"),
        ):
            output = self.check()
        self.assertIn("WARNING", output)

    def test_the_database_is_only_read(self):
        def write(expected, warnings):
            List.objects.create(id=uuid.uuid4(), name="written by the check")

        with mock.patch.object(check_pkg_inventory, "compare", write):
            with self.assertRaises(InternalError):
                self.check()
        self.assertFalse(List.objects.filter(name="written by the check").exists())

    def test_the_exit_status_is_1_on_a_difference_and_0_otherwise(self):
        command = check_pkg_inventory.Command()
        argv = ["manage.py", "check_pkg_inventory", str(self.inventory_path)]
        with mock.patch("django.core.management.base.connections"):
            with mock.patch.object(command, "stdout", OutputWrapper(StringIO())):
                command.run_from_argv(argv)  # no SystemExit: exit status 0
            ListItem.objects.filter(pk=self.items[1].pk).delete()
            with mock.patch.object(command, "stderr", OutputWrapper(StringIO())):
                with self.assertRaises(SystemExit) as raised:
                    command.run_from_argv(argv)
        self.assertEqual(raised.exception.code, 1)

    def test_an_unreadable_inventory_is_an_error(self):
        for content in (None, "{not json", "{}"):
            with self.subTest(content=content):
                path = self.base / "bad.json"
                if content is not None:
                    path.write_text(content)
                with self.assertRaises(CommandError):
                    call_command("check_pkg_inventory", str(path), stdout=StringIO())

    def test_the_inventory_names_every_digest_it_is_checked_with(self):
        entry = json.loads(self.inventory_path.read_text("utf-8"))["controlled_lists"][
            "per_list"
        ][str(self.controlled_list.id)]
        self.assertEqual(
            {
                "digest_sortorder",
                "digest_sibling_rank",
                "digest_items",
                "digest_values",
            },
            {k for k in entry if k.startswith("digest_")},
        )
