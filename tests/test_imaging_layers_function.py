"""The « Imaging layers proposal » Function and its migration.

Usage:
    python manage.py test tests.test_imaging_layers_function --settings="tests.test_settings"
"""

import importlib
import uuid
from unittest import mock

from django.apps import apps
from django.contrib.auth.models import Group, User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from arches.app.models.models import CardModel, Function, FunctionXGraph, TileModel
from arches.app.models.tile import Tile

from manuspectrum.constants.imaging_layers import (
    ANALYSIS_GRAPH_ID,
    IMAGING_MANIFEST_NODEGROUP_ID,
)
from manuspectrum.functions import imaging_layers_proposal as function_module
from manuspectrum.functions.imaging_layers_proposal import (
    ImagingLayersProposal,
    details,
)
from manuspectrum.utils import imaging_layers as rule
from tests import test_imaging_layers_rule as base
from tests.explorer_fixtures import ROLE_NODES

MIGRATION = "manuspectrum.migrations.0007_imaging_layers_proposal"
LOGGER = "manuspectrum.functions.imaging_layers_proposal"


def serialized_graph(nodes):
    """The nodes of the fixture; the manifest datatype is left out as its module reads the widget table on import."""
    return {
        "nodes": [
            {
                "nodeid": str(node.nodeid),
                "datatype": "string" if node.datatype == "manifest" else node.datatype,
            }
            for node in nodes.values()
        ]
    }


class FunctionCase(base.RuleCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.reviewer = User.objects.create_user("layers_reviewer", password="pw")
        cls.reviewer.groups.add(Group.objects.get(name="Resource Reviewer"))
        for key in (
            ("analysis", "chemical_imaging_manifest"),
            ("analysis", "imaging_layer_canvas"),
        ):
            CardModel.objects.create(
                graph=cls.graphs["analysis"],
                nodegroup_id=cls.nodes[key].nodegroup_id,
                name=key[1],
            )
        cls.nodegroup = cls.nodes[
            ("analysis", "chemical_imaging_manifest")
        ].nodegroup_id
        cls.manifest_node = str(
            cls.nodes[("analysis", "chemical_imaging_manifest")].nodeid
        )

    def setUp(self):
        migration = importlib.import_module(MIGRATION)
        migration.register_function(apps, None)
        FunctionXGraph.objects.filter(function_id=details["functionid"]).update(
            config={"triggering_nodegroups": [str(self.nodegroup)]}
        )
        graph = serialized_graph(self.nodes)
        patch = mock.patch.object(
            Tile,
            "load_serialized_graph",
            lambda tile: setattr(tile, "serialized_graph", graph),
        )
        patch.start()
        self.addCleanup(patch.stop)
        # The manifest datatype cannot be imported here: its module reads the widget table.
        validate = mock.patch.object(Tile, "validate")
        validate.start()
        self.addCleanup(validate.stop)
        self.resource = self.analyses["on_document"]

    def save_manifest(
        self, *labels, user=None, tile_id=None, context=None, url=base.MANIFEST_URL
    ):
        tile = Tile(
            tileid=tile_id or uuid.uuid4(),
            resourceinstance_id=self.resource.pk,
            nodegroup_id=self.nodegroup,
            data={self.manifest_node: {"url": url}},
        )
        with mock.patch.object(
            rule, "manifest_json", return_value=base.manifest(*labels)
        ):
            tile.save(user=user, index=False, context=context)
        return tile

    def children(self, tile):
        return TileModel.objects.filter(parenttile_id=tile.pk)


class SaveTests(FunctionCase):
    def test_a_reviewer_saving_a_manifest_tile_gets_a_layer_tile_per_proposal(self):
        tile = self.save_manifest("Pb", "650 nm", "foo", user=self.reviewer)
        canvases = [
            child.data[self.layer_node("canvas")] for child in self.children(tile)
        ]
        self.assertEqual(sorted(canvases), [f"{base.CANVAS_BASE}{n}" for n in (0, 1)])

    def test_a_save_without_user_proposes_too(self):
        tile = self.save_manifest("Pb")
        self.assertEqual(self.children(tile).count(), 1)

    def test_a_provisional_tile_proposes_nothing(self):
        tile = self.save_manifest("Pb", user=self.editor)
        self.assertIsNotNone(TileModel.objects.get(pk=tile.pk).provisionaledits)
        self.assertEqual(self.children(tile).count(), 0)

    def test_a_copy_proposes_nothing(self):
        tile = self.save_manifest("Pb", context="copy")
        self.assertEqual(self.children(tile).count(), 0)

    def test_saving_the_same_tile_again_adds_nothing(self):
        tile = self.save_manifest("Pb", "Cu", user=self.reviewer)
        again = self.save_manifest("Pb", "Cu", user=self.reviewer, tile_id=tile.pk)
        self.assertEqual(again.pk, tile.pk)
        self.assertEqual(self.children(tile).count(), 2)

    def test_a_tile_of_another_nodegroup_is_ignored(self):
        function = ImagingLayersProposal({}, uuid.uuid4())
        other = Tile(
            tileid=uuid.uuid4(),
            resourceinstance_id=self.resource.pk,
            nodegroup_id=self.nodes[("analysis", "imaging_layer_canvas")].nodegroup_id,
            data={self.manifest_node: {"url": base.MANIFEST_URL}},
        )
        with mock.patch.object(rule, "plan") as plan:
            function.post_save(other, None)
        plan.assert_not_called()

    def test_an_unreadable_manifest_logs_a_warning_and_the_save_succeeds(self):
        tile = Tile(
            tileid=uuid.uuid4(),
            resourceinstance_id=self.resource.pk,
            nodegroup_id=self.nodegroup,
            data={self.manifest_node: {"url": base.MANIFEST_URL}},
        )
        with mock.patch.object(rule, "manifest_json", return_value=None):
            with self.assertLogs(LOGGER, "WARNING"):
                tile.save(index=False)
        self.assertTrue(TileModel.objects.filter(pk=tile.pk).exists())
        self.assertEqual(self.children(tile).count(), 0)

    def test_a_failing_write_leaves_no_child_and_keeps_the_manifest(self):
        real = Tile.save
        calls = []

        def flaky(tile, **kwargs):
            if str(tile.nodegroup_id) == str(
                self.nodes[("analysis", "imaging_layer_canvas")].nodegroup_id
            ):
                calls.append(tile)
                if len(calls) == 2:
                    raise RuntimeError("boom")
            return real(tile, **kwargs)

        tile_id = uuid.uuid4()
        with mock.patch.object(Tile, "save", autospec=True, side_effect=flaky):
            with self.assertLogs(LOGGER, "WARNING") as logged:
                self.save_manifest("Pb", "Cu", tile_id=tile_id)
        self.assertEqual(len(calls), 2)
        self.assertTrue(TileModel.objects.filter(pk=tile_id).exists())
        self.assertFalse(TileModel.objects.filter(parenttile_id=tile_id).exists())
        self.assertIsNotNone(logged.records[0].exc_info)

    def test_a_provisional_edit_of_an_existing_tile_proposes_nothing(self):
        tile = self.save_manifest("Pb", user=self.reviewer)
        self.assertEqual(self.children(tile).count(), 1)
        self.save_manifest(
            "Pb",
            "Cu",
            user=self.editor,
            tile_id=tile.pk,
            url=f"{base.MANIFEST_URL}-edited",
        )
        stored = TileModel.objects.get(pk=tile.pk)
        self.assertIsNotNone(stored.provisionaledits)
        self.assertEqual(stored.data[self.manifest_node], {"url": base.MANIFEST_URL})
        self.assertEqual(self.children(tile).count(), 1)

    def test_a_layer_deleted_on_purpose_stays_deleted_when_the_manifest_is_saved_again(
        self,
    ):
        tile = self.save_manifest("Pb", "Cu", user=self.reviewer)
        self.children(tile).first().delete()
        self.save_manifest("Pb", "Cu", user=self.reviewer, tile_id=tile.pk)
        self.assertEqual(self.children(tile).count(), 1)

    def test_changing_the_manifest_url_proposes_for_the_new_canvases(self):
        tile = self.save_manifest("Pb", user=self.reviewer)
        self.save_manifest(
            "Pb",
            "Cu",
            user=self.reviewer,
            tile_id=tile.pk,
            url=f"{base.MANIFEST_URL}-other",
        )
        canvases = [
            child.data[self.layer_node("canvas")] for child in self.children(tile)
        ]
        self.assertEqual(sorted(canvases), [f"{base.CANVAS_BASE}{n}" for n in (0, 1)])

    def test_on_import_does_nothing(self):
        with self.assertRaises(NotImplementedError):
            ImagingLayersProposal({}, None).on_import({})


class DetailsTests(FunctionCase):
    def test_details(self):
        self.assertEqual(uuid.UUID(details["functionid"]).version, 4)
        self.assertEqual(details["type"], "node")
        self.assertEqual(
            details["defaultconfig"],
            {"triggering_nodegroups": [IMAGING_MANIFEST_NODEGROUP_ID]},
        )
        self.assertEqual(function_module.details, details)


class MigrationTests(FunctionCase):
    def rows(self):
        return (
            Function.objects.filter(functionid=details["functionid"]).count(),
            FunctionXGraph.objects.filter(function_id=details["functionid"]).count(),
        )

    def test_migration_registers_and_binds_the_function(self):
        self.assertEqual(self.rows(), (1, 1))
        row = FunctionXGraph.objects.get(function_id=details["functionid"])
        self.assertEqual(str(row.graph_id), ANALYSIS_GRAPH_ID)
        function = Function.objects.get(functionid=details["functionid"])
        self.assertEqual(function.classname, "ImagingLayersProposal")
        self.assertEqual(function.component, details["component"])

    def test_the_binding_is_skipped_without_the_analysis_graph(self):
        FunctionXGraph.objects.filter(function_id=details["functionid"]).delete()
        migration = importlib.import_module(MIGRATION)
        with mock.patch.object(
            apps.get_model("models", "GraphModel").objects,
            "filter",
            return_value=mock.Mock(exists=lambda: False),
        ):
            migration.register_function(apps, None)
        self.assertEqual(self.rows(), (1, 0))

    def test_migration_reverse_removes_them(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("manuspectrum", "0006_data_change_ledger")])
        self.assertEqual(self.rows(), (0, 0))
        executor = MigrationExecutor(connection)
        executor.migrate([("manuspectrum", "0007_imaging_layers_proposal")])
        self.assertEqual(self.rows()[0], 1)
