"""Characterisation tests for the clean_invalid_relations command.

The command rewrites tile.data and, with --delete-tiles, drops whole tiles, so
the boundary that matters most is --dry-run: nothing may be saved or deleted
without an explicit write. Every test below drives the command through
call_command with the Tile and Node managers patched at the command-module
level, so no database is involved; save() and delete() are mocks and the
assertions are on their calls.
"""

import csv
import os
import tempfile
import uuid
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from manuspectrum.management.commands import clean_invalid_relations as cmd

CSV_FIELDS = [
    "relation_type",
    "source_id",
    "source_name",
    "source_graph",
    "target_id",
    "target_name",
    "target_graph",
    "tile_id",
    "node_id",
    "nodegroup_id",
    "rxr_exists",
    "action",
    "status",
]


class TileMissing(Exception):
    pass


def _row(tile_id, node_id, target_id, status="INVALID_TARGET"):
    return {
        "relation_type": "Document→???",
        "source_id": str(uuid.uuid4()),
        "source_name": "Source",
        "source_graph": "Document",
        "target_id": str(target_id),
        "target_name": "RESOURCE NOT FOUND",
        "target_graph": "???",
        "tile_id": str(tile_id),
        "node_id": str(node_id),
        "nodegroup_id": str(uuid.uuid4()),
        "rxr_exists": "N/A",
        "action": "ERROR",
        "status": status,
    }


class FakeTile:
    def __init__(self, data=None, tile_id=None, resource_name="Manuscrit 42"):
        self.tileid = str(tile_id or uuid.uuid4())
        self.data = data
        self.resourceinstance = SimpleNamespace(name=resource_name)
        self.save = MagicMock()
        self.delete = MagicMock()


def _tile_manager(tiles):
    by_id = {str(tile.tileid): tile for tile in tiles}

    def _get(tileid=None, **kwargs):
        try:
            return by_id[str(tileid)]
        except KeyError:
            raise TileMissing(str(tileid))

    manager = MagicMock()
    manager.get.side_effect = _get
    return manager


def _write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: v for k, v in row.items() if k in fields})


def _run(
    rows=(),
    tiles=(),
    dry_run=False,
    delete_tiles=False,
    node_ids=None,
    fields=CSV_FIELDS,
    raw=None,
):
    if node_ids is None:
        node_ids = [row["node_id"] for row in rows]

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "relations.csv")
        if raw is None:
            _write_csv(input_path, rows, fields)
        else:
            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write(raw)

        out = StringIO()
        transaction = MagicMock()
        with (
            patch.object(cmd, "Tile") as tile_cls,
            patch.object(cmd, "Node") as node_cls,
            patch.object(cmd, "transaction", transaction),
        ):
            tile_cls.DoesNotExist = TileMissing
            tile_cls.objects = _tile_manager(tiles)
            node_cls.objects.filter.return_value = [
                SimpleNamespace(nodeid=node_id) for node_id in node_ids
            ]
            args = ["--input", input_path]
            if dry_run:
                args.append("--dry-run")
            if delete_tiles:
                args.append("--delete-tiles")
            call_command("clean_invalid_relations", *args, stdout=out)

    return SimpleNamespace(output=out.getvalue(), transaction=transaction)


class ArgumentTests(SimpleTestCase):
    def _parser(self):
        return cmd.Command().create_parser("manage.py", "clean_invalid_relations")

    def test_input_is_required(self):
        with self.assertRaises(CommandError):
            call_command("clean_invalid_relations", stdout=StringIO())

    def test_dry_run_and_delete_tiles_both_default_to_false(self):
        options = self._parser().parse_args(["--input", "relations.csv"])
        self.assertFalse(options.dry_run)
        self.assertFalse(options.delete_tiles)

    def test_dry_run_is_announced_in_the_banner_and_the_summary(self):
        result = _run(dry_run=True)

        self.assertIn("MODE DRY RUN", result.output)
        self.assertIn("Aucune modification effectuée", result.output)

    def test_writing_run_says_nothing_about_dry_run(self):
        result = _run()

        self.assertNotIn("DRY RUN", result.output)


class DryRunBoundaryTests(SimpleTestCase):
    def _string_case(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: target})
        return tile, node, target, [_row(tile.tileid, node, target)]

    def test_dry_run_neither_saves_nor_mutates_tile_data(self):
        tile, node, target, rows = self._string_case()

        result = _run(rows, [tile], dry_run=True)

        tile.save.assert_not_called()
        tile.delete.assert_not_called()
        self.assertEqual(tile.data, {node: target})
        self.assertIn("Tile nettoyé", result.output)

    def test_dry_run_still_counts_the_tile_as_cleaned(self):
        tile, _, _, rows = self._string_case()

        result = _run(rows, [tile], dry_run=True)

        self.assertIn("Tiles nettoyés: 1", result.output)

    def test_dry_run_leaves_a_list_untouched(self):
        target = str(uuid.uuid4())
        keeper = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: [keeper, target]})

        _run([_row(tile.tileid, node, target)], [tile], dry_run=True)

        tile.save.assert_not_called()
        self.assertEqual(tile.data, {node: [keeper, target]})

    def test_delete_tiles_in_dry_run_deletes_nothing_but_reports_a_deletion(self):
        node = str(uuid.uuid4())
        targets = [str(uuid.uuid4()) for _ in range(3)]
        tile = FakeTile(data={node: list(targets)})
        rows = [_row(tile.tileid, node, target) for target in targets]

        result = _run(rows, [tile], dry_run=True, delete_tiles=True)

        tile.delete.assert_not_called()
        tile.save.assert_not_called()
        self.assertIn("TILE SUPPRIMÉ", result.output)
        self.assertIn("Tiles supprimés: 1", result.output)


class CleaningTests(SimpleTestCase):
    def test_string_value_has_its_node_removed_and_the_tile_saved(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        other = str(uuid.uuid4())
        tile = FakeTile(data={node: target, other: "kept"})

        result = _run([_row(tile.tileid, node, target)], [tile])

        self.assertEqual(tile.data, {other: "kept"})
        tile.save.assert_called_once_with()
        tile.delete.assert_not_called()
        self.assertIn("valeur simple", result.output)
        self.assertIn("Tiles nettoyés: 1", result.output)

    def test_matching_dict_is_dropped_from_the_list_and_the_rest_kept(self):
        target = str(uuid.uuid4())
        keeper = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(
            data={
                node: [
                    {"resourceId": keeper, "ontologyProperty": "P1"},
                    {"resourceId": target, "ontologyProperty": "P1"},
                ]
            }
        )

        _run([_row(tile.tileid, node, target)], [tile])

        self.assertEqual(
            tile.data,
            {node: [{"resourceId": keeper, "ontologyProperty": "P1"}]},
        )
        tile.save.assert_called_once_with()

    def test_matching_string_is_dropped_from_the_list(self):
        target = str(uuid.uuid4())
        keeper = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: [keeper, target]})

        _run([_row(tile.tileid, node, target)], [tile])

        self.assertEqual(tile.data, {node: [keeper]})
        tile.save.assert_called_once_with()

    def test_emptied_list_removes_the_node_key_entirely(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: [{"resourceId": target}]})

        _run([_row(tile.tileid, node, target)], [tile])

        self.assertEqual(tile.data, {})
        tile.save.assert_called_once_with()

    def test_save_runs_inside_an_atomic_block(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: target})

        result = _run([_row(tile.tileid, node, target)], [tile])

        result.transaction.atomic.assert_called_once_with()

    def test_target_that_is_not_a_uuid_is_deleted_all_the_same(self):
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: "not-a-uuid"})

        _run([_row(tile.tileid, node, "not-a-uuid")], [tile])

        self.assertEqual(tile.data, {})
        tile.save.assert_called_once_with()

    def test_two_rows_on_the_same_tile_are_cleaned_in_one_save(self):
        first_target = str(uuid.uuid4())
        second_target = str(uuid.uuid4())
        first_node = str(uuid.uuid4())
        second_node = str(uuid.uuid4())
        tile = FakeTile(
            data={first_node: first_target, second_node: [second_target, "keep"]}
        )
        rows = [
            _row(tile.tileid, first_node, first_target),
            _row(tile.tileid, second_node, second_target),
        ]

        result = _run(rows, [tile])

        self.assertEqual(tile.data, {second_node: ["keep"]})
        tile.save.assert_called_once_with()
        self.assertIn("Valeurs invalides: 2", result.output)
        self.assertIn("Tiles à nettoyer: 1", result.output)

    def test_a_list_with_no_match_is_rewritten_after_an_earlier_removal(self):
        target = str(uuid.uuid4())
        first_node = str(uuid.uuid4())
        second_node = str(uuid.uuid4())
        tile = FakeTile(data={first_node: target, second_node: ["untouched"]})
        rows = [
            _row(tile.tileid, first_node, target),
            _row(tile.tileid, second_node, str(uuid.uuid4())),
        ]

        _run(rows, [tile])

        self.assertEqual(tile.data, {second_node: ["untouched"]})
        tile.save.assert_called_once_with()


class NothingToDoTests(SimpleTestCase):
    def test_node_absent_from_tile_data_leaves_the_tile_alone(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={str(uuid.uuid4()): "other"})

        result = _run([_row(tile.tileid, node, target)], [tile])

        tile.save.assert_not_called()
        self.assertIn("Rien à nettoyer", result.output)
        self.assertIn("Tiles nettoyés: 0", result.output)

    def test_tile_without_data_is_skipped(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data=None)

        result = _run([_row(tile.tileid, node, target)], [tile])

        tile.save.assert_not_called()
        self.assertIn("Pas de données", result.output)
        self.assertIn("Tiles nettoyés: 0", result.output)

    def test_bare_dict_value_is_never_cleaned(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: {"resourceId": target}})

        result = _run([_row(tile.tileid, node, target)], [tile])

        tile.save.assert_not_called()
        self.assertEqual(tile.data, {node: {"resourceId": target}})
        self.assertIn("Rien à nettoyer", result.output)

    def test_string_value_that_does_not_match_is_kept(self):
        node = str(uuid.uuid4())
        present = str(uuid.uuid4())
        tile = FakeTile(data={node: present})

        _run([_row(tile.tileid, node, str(uuid.uuid4()))], [tile])

        tile.save.assert_not_called()
        self.assertEqual(tile.data, {node: present})


class ResourceInstanceGuardTests(SimpleTestCase):
    def test_node_that_is_not_resource_instance_is_skipped(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: target})

        result = _run([_row(tile.tileid, node, target)], [tile], node_ids=[])

        tile.save.assert_not_called()
        self.assertEqual(tile.data, {node: target})
        self.assertIn("pas resource-instance", result.output)
        self.assertIn("Tiles nettoyés: 0", result.output)

    def test_the_guard_reads_the_node_table_once(self):
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: "x"})

        with (
            patch.object(cmd, "Tile") as tile_cls,
            patch.object(cmd, "Node") as node_cls,
            patch.object(cmd, "transaction", MagicMock()),
            tempfile.TemporaryDirectory() as tmpdir,
        ):
            tile_cls.DoesNotExist = TileMissing
            tile_cls.objects = _tile_manager([tile])
            node_cls.objects.filter.return_value = []
            path = os.path.join(tmpdir, "relations.csv")
            _write_csv(path, [_row(tile.tileid, node, "x")], CSV_FIELDS)
            call_command("clean_invalid_relations", "--input", path, stdout=StringIO())

        node_cls.objects.filter.assert_called_once_with(
            datatype__startswith="resource-instance"
        )

    def test_delete_tiles_bypasses_the_resource_instance_guard(self):
        node = str(uuid.uuid4())
        targets = [str(uuid.uuid4()) for _ in range(3)]
        tile = FakeTile(data={node: list(targets)})
        rows = [_row(tile.tileid, node, target) for target in targets]

        result = _run(rows, [tile], delete_tiles=True, node_ids=[])

        tile.delete.assert_called_once_with()
        self.assertNotIn("pas resource-instance", result.output)
        self.assertIn("Tiles supprimés: 1", result.output)


class DeleteTilesTests(SimpleTestCase):
    def _corrupt_tile(self, invalid_values):
        node = str(uuid.uuid4())
        targets = [str(uuid.uuid4()) for _ in range(invalid_values)]
        tile = FakeTile(data={node: list(targets)})
        rows = [_row(tile.tileid, node, target) for target in targets]
        return tile, rows

    def test_three_invalid_values_delete_the_whole_tile(self):
        tile, rows = self._corrupt_tile(3)

        result = _run(rows, [tile], delete_tiles=True)

        tile.delete.assert_called_once_with()
        tile.save.assert_not_called()
        self.assertIn("TILE SUPPRIMÉ", result.output)
        self.assertIn("Tiles supprimés: 1", result.output)
        self.assertIn("Tiles nettoyés: 0", result.output)

    def test_two_invalid_values_are_cleaned_not_deleted(self):
        tile, rows = self._corrupt_tile(2)

        result = _run(rows, [tile], delete_tiles=True)

        tile.delete.assert_not_called()
        tile.save.assert_called_once_with()
        self.assertIn("Tiles supprimés: 0", result.output)
        self.assertIn("Tiles nettoyés: 1", result.output)

    def test_three_invalid_values_without_the_flag_are_cleaned(self):
        tile, rows = self._corrupt_tile(3)

        result = _run(rows, [tile])

        tile.delete.assert_not_called()
        tile.save.assert_called_once_with()
        self.assertEqual(tile.data, {})
        self.assertIn("Tiles supprimés: 0", result.output)
        self.assertIn("Tiles nettoyés: 1", result.output)

    def test_a_tile_without_data_is_never_deleted(self):
        tile, rows = self._corrupt_tile(3)
        tile.data = None

        result = _run(rows, [tile], delete_tiles=True)

        tile.delete.assert_not_called()
        self.assertIn("Pas de données", result.output)
        self.assertIn("Tiles supprimés: 0", result.output)


class CsvReadingTests(SimpleTestCase):
    def test_only_invalid_target_and_error_rows_are_selected(self):
        node = str(uuid.uuid4())
        target = str(uuid.uuid4())
        tile = FakeTile(data={node: target})
        rows = [
            _row(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), status="OK"),
            _row(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), status="MISSING"),
            _row(tile.tileid, node, target, status="ERROR"),
        ]

        result = _run(rows, [tile])

        self.assertIn("Tiles à nettoyer: 1", result.output)
        tile.save.assert_called_once_with()

    def test_empty_csv_reports_no_tiles(self):
        result = _run()

        self.assertIn("Tiles à nettoyer: 0", result.output)
        self.assertIn("Tiles nettoyés: 0", result.output)
        self.assertIn("Tiles supprimés: 0", result.output)

    def test_missing_node_id_column_raises_key_error(self):
        with self.assertRaises(KeyError):
            _run(
                [_row(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())],
                [],
                fields=[f for f in CSV_FIELDS if f != "node_id"],
            )

    def test_missing_status_column_raises_key_error(self):
        with self.assertRaises(KeyError):
            _run(
                [_row(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())],
                [],
                fields=[f for f in CSV_FIELDS if f != "status"],
            )

    def test_short_row_is_skipped_because_status_reads_as_none(self):
        header = ",".join(CSV_FIELDS)
        result = _run(raw=f"{header}\nDocument→???,{uuid.uuid4()}\n")

        self.assertIn("Tiles à nettoyer: 0", result.output)


class ErrorTests(SimpleTestCase):
    def test_missing_tile_is_counted_as_an_error(self):
        missing_id = str(uuid.uuid4())

        result = _run([_row(missing_id, uuid.uuid4(), uuid.uuid4())], [])

        self.assertIn(f"Tile introuvable: {missing_id}", result.output)
        self.assertIn("Erreurs: 1", result.output)
        self.assertIn("Tiles nettoyés: 0", result.output)

    def test_a_failing_save_is_swallowed_counted_and_not_reported_as_cleaned(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: target})
        tile.save.side_effect = RuntimeError("boom")

        result = _run([_row(tile.tileid, node, target)], [tile])

        self.assertIn("Erreur: boom", result.output)
        self.assertIn("Erreurs: 1", result.output)
        self.assertIn("Tiles nettoyés: 0", result.output)

    def test_no_error_line_when_everything_succeeds(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: target})

        result = _run([_row(tile.tileid, node, target)], [tile])

        self.assertNotIn("Erreurs:", result.output)
