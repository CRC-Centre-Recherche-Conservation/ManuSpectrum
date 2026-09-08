"""Characterisation tests for the analyze_invalid_relations command.

The command reads an export_relations_csv file, looks every affected tile up in
the database and writes a per-tile report next to a stdout summary. Nothing
here touches the database: the Tile manager is patched at the command-module
level and both CSVs live in a temporary directory. The assertions pin the
behaviour the code has today, including the places where it disagrees with its
own docstring.
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

from manuspectrum.management.commands import analyze_invalid_relations as cmd

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

REPORT_FIELDS = [
    "tile_id",
    "resource_id",
    "resource_name",
    "graph_name",
    "invalid_count",
    "recommendation",
    "invalid_uuids",
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


def _resource(name="Resource A", graph_name="Document"):
    resource = SimpleNamespace(
        resourceinstanceid=uuid.uuid4(),
        graph=SimpleNamespace(name=graph_name) if graph_name else None,
    )
    resource.displayname = lambda: name
    return resource


class FakeTile:
    def __init__(self, data=None, resource=None, tile_id=None):
        self.tileid = str(tile_id or uuid.uuid4())
        self.data = data
        self.resourceinstance = _resource() if resource is None else resource


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


def _run(rows=(), tiles=(), fields=CSV_FIELDS, raw=None):
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "relations.csv")
        output_path = os.path.join(tmpdir, "analysis.csv")
        if raw is None:
            _write_csv(input_path, rows, fields)
        else:
            with open(input_path, "w", encoding="utf-8") as handle:
                handle.write(raw)

        out = StringIO()
        with patch.object(cmd, "Tile") as tile_cls:
            tile_cls.DoesNotExist = TileMissing
            tile_cls.objects = _tile_manager(tiles)
            call_command(
                "analyze_invalid_relations",
                "--input",
                input_path,
                "--output",
                output_path,
                stdout=out,
            )

        with open(output_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            report_rows = list(reader)
            report_fields = reader.fieldnames

    return SimpleNamespace(
        output=out.getvalue(),
        rows=report_rows,
        report={row["tile_id"]: row for row in report_rows},
        fields=report_fields,
    )


class ArgumentTests(SimpleTestCase):
    def _parser(self):
        return cmd.Command().create_parser("manage.py", "analyze_invalid_relations")

    def test_input_is_required(self):
        with self.assertRaises(CommandError):
            call_command("analyze_invalid_relations", stdout=StringIO())

    def test_output_defaults_to_invalid_relations_analysis_csv(self):
        options = self._parser().parse_args(["--input", "relations.csv"])
        self.assertEqual(options.output, "invalid_relations_analysis.csv")

    def test_sample_option_promised_by_the_docstring_does_not_exist(self):
        self.assertIn("--sample", cmd.__doc__)
        with self.assertRaises(CommandError):
            self._parser().parse_args(["--input", "relations.csv", "--sample", "10"])


class CsvReadingTests(SimpleTestCase):
    def test_only_invalid_target_and_error_rows_are_selected(self):
        tile = FakeTile(data={})
        rows = [
            _row(tile.tileid, uuid.uuid4(), uuid.uuid4(), status="OK"),
            _row(tile.tileid, uuid.uuid4(), uuid.uuid4(), status="MISSING"),
            _row(tile.tileid, uuid.uuid4(), uuid.uuid4(), status="INVALID_TARGET"),
            _row(tile.tileid, uuid.uuid4(), uuid.uuid4(), status="ERROR"),
        ]

        result = _run(rows, [tile])

        self.assertIn("Relations invalides trouvées: 2", result.output)
        self.assertIn("UUIDs invalides uniques: 2", result.output)
        self.assertIn("Tiles affectés: 1", result.output)

    def test_empty_csv_reports_zero_and_writes_a_header_only_report(self):
        result = _run([], [])

        self.assertIn("Relations invalides trouvées: 0", result.output)
        self.assertIn("UUIDs invalides uniques: 0", result.output)
        self.assertIn("Tiles affectés: 0", result.output)
        self.assertEqual(result.rows, [])
        self.assertEqual(result.fields, REPORT_FIELDS)

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

        self.assertIn("Relations invalides trouvées: 0", result.output)

    def test_row_with_extra_fields_is_still_read(self):
        tile = FakeTile(data={})
        row = _row(tile.tileid, uuid.uuid4(), uuid.uuid4())
        header = ",".join(CSV_FIELDS)
        body = ",".join(str(row[field]) for field in CSV_FIELDS)
        result = _run(raw=f"{header}\n{body},extra-1,extra-2\n", tiles=[tile])

        self.assertIn("Relations invalides trouvées: 1", result.output)
        self.assertIn("Tiles affectés: 1", result.output)

    def test_duplicate_rows_count_occurrences_but_a_single_tile(self):
        tile = FakeTile(data={})
        target = uuid.uuid4()
        node = uuid.uuid4()
        rows = [_row(tile.tileid, node, target) for _ in range(3)]

        result = _run(rows, [tile])

        self.assertIn("Relations invalides trouvées: 3", result.output)
        self.assertIn("UUIDs invalides uniques: 1", result.output)
        self.assertIn("Tiles affectés: 1", result.output)
        self.assertIn(f"  {target}: 3 occurrences", result.output)


class UuidLocationTests(SimpleTestCase):
    def test_bare_string_value_is_located(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: target})

        result = _run([_row(tile.tileid, node, target)], [tile])

        entry = result.report[tile.tileid]
        self.assertEqual(entry["invalid_count"], "1")
        self.assertEqual(entry["invalid_uuids"], target)

    def test_uuid_string_inside_a_list_is_located(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: [str(uuid.uuid4()), target]})

        result = _run([_row(tile.tileid, node, target)], [tile])

        self.assertEqual(result.report[tile.tileid]["invalid_count"], "1")

    def test_resource_id_inside_a_dict_in_a_list_is_located(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(
            data={node: [{"resourceId": target, "ontologyProperty": "P1"}]},
        )

        result = _run([_row(tile.tileid, node, target)], [tile])

        self.assertEqual(result.report[tile.tileid]["invalid_count"], "1")
        self.assertEqual(result.report[tile.tileid]["invalid_uuids"], target)

    def test_bare_dict_value_is_never_located(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: {"resourceId": target}})

        result = _run([_row(tile.tileid, node, target)], [tile])

        self.assertEqual(result.report[tile.tileid]["invalid_count"], "0")
        self.assertEqual(result.report[tile.tileid]["invalid_uuids"], "")

    def test_uuid_absent_from_tile_data_is_reported_as_zero(self):
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: str(uuid.uuid4())})

        result = _run([_row(tile.tileid, node, target)], [tile])

        self.assertEqual(result.report[tile.tileid]["invalid_count"], "0")

    def test_target_that_is_not_a_uuid_can_never_be_located(self):
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: "not-a-uuid"})

        result = _run([_row(tile.tileid, node, "not-a-uuid")], [tile])

        self.assertEqual(result.report[tile.tileid]["invalid_count"], "0")

    def test_tile_without_data_is_reported_as_zero(self):
        target = str(uuid.uuid4())
        tile = FakeTile(data=None)

        result = _run([_row(tile.tileid, uuid.uuid4(), target)], [tile])

        self.assertEqual(result.report[tile.tileid]["invalid_count"], "0")

    def test_invalid_uuid_reported_for_another_tile_is_still_counted_here(self):
        first_target = str(uuid.uuid4())
        second_target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        first = FakeTile(data={node: [first_target, second_target]})
        second = FakeTile(data={node: second_target})
        rows = [
            _row(first.tileid, node, first_target),
            _row(second.tileid, node, second_target),
        ]

        result = _run(rows, [first, second])

        entry = result.report[first.tileid]
        self.assertEqual(entry["invalid_count"], "2")
        self.assertEqual(entry["invalid_uuids"], f"{first_target}, {second_target}")

    def test_the_node_holding_each_invalid_uuid_is_recorded(self):
        first_target = str(uuid.uuid4())
        second_target = str(uuid.uuid4())
        first_node = str(uuid.uuid4())
        second_node = str(uuid.uuid4())
        tile = FakeTile(data={first_node: first_target, second_node: second_target})
        rows = [
            _row(tile.tileid, first_node, first_target),
            _row(tile.tileid, second_node, second_target),
        ]

        result = _run(rows, [tile])

        self.assertEqual(
            result.report[tile.tileid]["invalid_uuids"],
            f"{first_target}, {second_target}",
        )


class RecommendationTests(SimpleTestCase):
    def _tile_with(self, count):
        node = str(uuid.uuid4())
        targets = [str(uuid.uuid4()) for _ in range(count)]
        tile = FakeTile(data={node: targets})
        rows = [_row(tile.tileid, node, target) for target in targets]
        return tile, rows

    def test_two_invalid_values_recommend_cleaning_the_node(self):
        tile, rows = self._tile_with(2)

        result = _run(rows, [tile])

        self.assertEqual(result.report[tile.tileid]["invalid_count"], "2")
        self.assertEqual(result.report[tile.tileid]["recommendation"], "CLEAN_NODE")
        self.assertIn(
            "Tiles à nettoyer (supprimer juste les valeurs invalides): 1",
            result.output,
        )
        self.assertIn(
            "Tiles à supprimer entièrement (trop corrompus): 0", result.output
        )

    def test_three_invalid_values_recommend_deleting_the_tile(self):
        tile, rows = self._tile_with(3)

        result = _run(rows, [tile])

        self.assertEqual(result.report[tile.tileid]["invalid_count"], "3")
        self.assertEqual(result.report[tile.tileid]["recommendation"], "DELETE_TILE")
        self.assertIn(
            "Tiles à nettoyer (supprimer juste les valeurs invalides): 0",
            result.output,
        )
        self.assertIn(
            "Tiles à supprimer entièrement (trop corrompus): 1", result.output
        )


class ReportTests(SimpleTestCase):
    def test_report_carries_the_resource_id_name_and_graph(self):
        resource = _resource(name="Manuscrit 42", graph_name="Document")
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: target}, resource=resource)

        result = _run([_row(tile.tileid, node, target)], [tile])

        entry = result.report[tile.tileid]
        self.assertEqual(entry["resource_id"], str(resource.resourceinstanceid))
        self.assertEqual(entry["resource_name"], "Manuscrit 42")
        self.assertEqual(entry["graph_name"], "Document")

    def test_resource_without_a_graph_is_reported_as_unknown(self):
        resource = _resource(graph_name=None)
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: target}, resource=resource)

        result = _run([_row(tile.tileid, node, target)], [tile])

        self.assertEqual(result.report[tile.tileid]["graph_name"], "Unknown")

    def test_non_callable_displayname_is_stringified(self):
        resource = SimpleNamespace(
            resourceinstanceid=uuid.uuid4(),
            graph=SimpleNamespace(name="Document"),
            displayname="Plain attribute",
        )
        target = str(uuid.uuid4())
        node = str(uuid.uuid4())
        tile = FakeTile(data={node: target}, resource=resource)

        result = _run([_row(tile.tileid, node, target)], [tile])

        self.assertEqual(result.report[tile.tileid]["resource_name"], "Plain attribute")

    def test_missing_tile_is_reported_and_left_out_of_the_report(self):
        missing_id = str(uuid.uuid4())

        result = _run([_row(missing_id, uuid.uuid4(), uuid.uuid4())], [])

        self.assertIn(f"Tile introuvable: {missing_id}", result.output)
        self.assertEqual(result.rows, [])
        self.assertIn("Tiles affectés: 1", result.output)

    def test_top_uuid_listing_is_sorted_by_frequency_and_capped_at_ten(self):
        tile = FakeTile(data={})
        targets = [str(uuid.uuid4()) for _ in range(11)]
        rows = []
        for index, target in enumerate(targets):
            rows.extend(
                _row(tile.tileid, uuid.uuid4(), target) for _ in range(11 - index)
            )

        result = _run(rows, [tile])

        listing = result.output.split("TOP 10 UUIDs INVALIDES LES PLUS FRÉQUENTS")[1]
        occurrences = [
            line for line in listing.splitlines() if line.endswith(" occurrences")
        ]
        self.assertEqual(len(occurrences), 10)
        self.assertEqual(occurrences[0], f"  {targets[0]}: 11 occurrences")
        self.assertEqual(occurrences[-1], f"  {targets[9]}: 2 occurrences")
        self.assertNotIn(targets[10], listing)
