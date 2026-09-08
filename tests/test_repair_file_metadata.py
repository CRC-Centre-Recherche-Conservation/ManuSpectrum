"""What `repair_file_metadata` reports, and what it writes.

The command walks every tile of every `file-list` nodegroup, completes the
localised metadata of each stored file entry, and writes with a plain UPDATE —
only for the tiles that actually needed it, and only when `--apply` is passed.

The Arches managers are patched as the command reaches them, so nothing here
needs a database.
"""

import copy
import uuid
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase

from manuspectrum.utils.file_entries import METADATA_FIELDS, build_file_entry

COMMAND = "repair_file_metadata"
MODULE = "manuspectrum.management.commands.repair_file_metadata"

BLANK = {"value": "", "direction": "ltr"}


def make_node(name, nodegroup_id=None):
    node = mock.Mock()
    node.nodeid = uuid.uuid4()
    node.name = name
    node.nodegroup_id = nodegroup_id or uuid.uuid4()
    return node


def make_tile(entries_by_node):
    tile = mock.Mock()
    tile.tileid = uuid.uuid4()
    tile.data = {str(node.nodeid): entries for node, entries in entries_by_node.items()}
    return tile


def broken_entry(name="spectrum.csv"):
    """A file entry as every writer that bypasses the upload widget leaves it."""
    entry = {"name": name, "file_id": str(uuid.uuid4())}
    entry.update({field: None for field in METADATA_FIELDS})
    return entry


def complete_entry(name="reference.csv"):
    return build_file_entry(
        file_id=uuid.uuid4(),
        name=name,
        path="uploadedfiles",
        size=12,
        content_type="text/csv",
    )


class FakeTileManager:
    """Stands in for `TileModel.objects`: yields the scan, records the writes."""

    def __init__(self, tiles):
        self.tiles = tiles
        self.scanned_nodegroups = None
        self.updates = []

    def filter(self, **kwargs):
        if "pk" in kwargs:
            return FakeUpdate(self, kwargs["pk"])
        self.scanned_nodegroups = kwargs["nodegroup_id__in"]
        return FakeScan(self.tiles)


class FakeScan:
    def __init__(self, tiles):
        self.tiles = tiles

    def iterator(self):
        return iter(self.tiles)


class FakeUpdate:
    def __init__(self, manager, pk):
        self.manager = manager
        self.pk = pk

    def update(self, **kwargs):
        self.manager.updates.append((self.pk, kwargs["data"]))
        return 1


class RepairFileMetadataTests(SimpleTestCase):
    def run_command(self, nodes, tiles, *arguments):
        manager = FakeTileManager(tiles)
        output = StringIO()
        with (
            mock.patch(f"{MODULE}.Node") as node_model,
            mock.patch(f"{MODULE}.TileModel") as tile_model,
        ):
            node_model.objects.filter.return_value = nodes
            tile_model.objects = manager
            call_command(COMMAND, *arguments, stdout=output, no_color=True)
            self.node_filter = node_model.objects.filter
        return output.getvalue(), manager

    def test_a_dry_run_writes_nothing_and_still_counts_what_it_would_fix(self):
        node = make_node("Fichier de mesure")
        tile = make_tile({node: [broken_entry()]})

        output, manager = self.run_command([node], [tile])

        self.assertEqual(manager.updates, [])
        tile.save.assert_not_called()
        self.assertIn("1 file(s) across 1 tile(s) would be repaired (dry run)", output)
        self.assertIn("Pass --apply to write.", output)

    def test_apply_updates_only_the_tile_that_needed_repair(self):
        node = make_node("Fichier de mesure")
        broken = make_tile({node: [broken_entry()]})
        healthy = make_tile({node: [complete_entry()]})
        untouched = copy.deepcopy(healthy.data)

        output, manager = self.run_command([node], [broken, healthy], "--apply")

        self.assertEqual(manager.updates, [(broken.tileid, broken.data)])
        self.assertEqual(healthy.data, untouched)
        healthy.save.assert_not_called()
        self.assertIn("1 file(s) across 1 tile(s) repaired", output)
        self.assertIn("Now run:  python manage.py es index_resources", output)

    def test_a_repaired_entry_carries_every_field_in_every_language(self):
        node = make_node("Fichier de mesure")
        tile = make_tile({node: [broken_entry()]})

        self.run_command([node], [tile], "--apply")

        entry = tile.data[str(node.nodeid)][0]
        for field in METADATA_FIELDS:
            self.assertEqual(entry[field], {"en": BLANK, "fr": BLANK})

    def test_the_field_count_covers_every_field_in_every_language(self):
        node = make_node("Fichier de mesure")
        tile = make_tile({node: [broken_entry()]})

        output, _manager = self.run_command([node], [tile])

        self.assertIn(
            "8 field(s) across altText, title, attribution, description", output
        )

    def test_each_node_is_reported_with_the_number_of_files_it_holds(self):
        measurement = make_node("Fichier de mesure")
        image = make_node("Image")
        tile = make_tile(
            {
                measurement: [broken_entry("a.csv"), broken_entry("b.csv")],
                image: [broken_entry("recto.jpg")],
            }
        )

        output, _manager = self.run_command([measurement, image], [tile])

        self.assertIn("  Fichier de mesure: 2 file(s)", output)
        self.assertIn("  Image: 1 file(s)", output)
        self.assertIn("3 file(s) across 1 tile(s) would be repaired", output)

    def test_only_the_nodegroups_holding_a_file_list_node_are_scanned(self):
        measurement = make_node("Fichier de mesure")
        image = make_node("Image")

        _output, manager = self.run_command([measurement, image], [])

        self.node_filter.assert_called_once_with(datatype="file-list")
        self.assertEqual(
            manager.scanned_nodegroups,
            {measurement.nodegroup_id, image.nodegroup_id},
        )

    def test_a_single_language_can_be_asked_for(self):
        node = make_node("Fichier de mesure")
        tile = make_tile({node: [broken_entry()]})

        output, _manager = self.run_command([node], [tile], "--apply", "--language=fr")

        entry = tile.data[str(node.nodeid)][0]
        self.assertEqual(entry["title"], {"fr": BLANK})
        self.assertIn(
            "4 field(s) across altText, title, attribution, description", output
        )

    def test_a_tile_holding_no_file_list_value_is_left_alone(self):
        node = make_node("Fichier de mesure")
        empty = make_tile({node: None})
        other_nodegroup = make_tile({make_node("Autre"): [broken_entry()]})

        output, manager = self.run_command([node], [empty, other_nodegroup], "--apply")

        self.assertEqual(manager.updates, [])
        self.assertIn("0 file(s) across 0 tile(s) repaired", output)

    def test_a_graph_with_no_file_list_node_never_scans_a_tile(self):
        output, manager = self.run_command([], [make_tile({})], "--apply")

        self.assertEqual(output, "No file-list node in this graph set.\n")
        self.assertIsNone(manager.scanned_nodegroups)
        self.assertEqual(manager.updates, [])

    def test_running_twice_repairs_nothing_the_second_time(self):
        node = make_node("Fichier de mesure")
        tile = make_tile({node: [broken_entry()]})

        self.run_command([node], [tile], "--apply")
        output, manager = self.run_command([node], [tile], "--apply")

        self.assertEqual(manager.updates, [])
        self.assertIn("0 file(s) across 0 tile(s) repaired", output)
