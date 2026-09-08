"""Characterisation tests for the import_relations_csv management command.

The command writes rows into ResourceXResource, so the tests below pin the
dry-run / write boundary first: every write goes through
``ResourceXResource.objects.get_or_create`` and each test asserts on the
recorded calls, never on stdout alone.

Nothing here touches a database — the Arches managers and ``transaction`` are
replaced at the command-module level and every CSV is written inside a
temporary directory. Several tests pin behaviour that looks like a defect;
their docstrings say so.
"""

import csv
import os
import tempfile
from io import StringIO
from types import SimpleNamespace
from unittest.mock import ANY, patch

from django.core.management import call_command
from django.test import SimpleTestCase

from manuspectrum.management.commands import import_relations_csv as cmd

ANALYSIS_GRAPH = "60c85aba-f079-45bc-997f-21cdd4f77b6d"
COMPONENT_GRAPH = "d47595b4-f8a6-419c-8f33-b388206280c4"

SOURCE_ID = "11111111-1111-4111-8111-111111111111"
TARGET_ID = "22222222-2222-4222-8222-222222222222"
OTHER_TARGET_ID = "66666666-6666-4666-8666-666666666666"
TILE_ID = "33333333-3333-4333-8333-333333333333"
NODEGROUP_ID = "44444444-4444-4444-8444-444444444444"
NODE_ID = "55555555-5555-4555-8555-555555555555"

DEFAULT_REL_UUID = "ac41d9be-79db-4256-b368-2f4559cfbe55"
OTHER_REL_UUID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
INVERSE_REL_UUID = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"

# Mirrors the header written by export_relations_csv; the shared format.
FIELDNAMES = [
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


class ResourceDoesNotExist(Exception):
    pass


class TileDoesNotExist(Exception):
    pass


class NodeDoesNotExist(Exception):
    pass


class ValueDoesNotExist(Exception):
    pass


class FakeResource:
    def __init__(self, resourceinstanceid, graph_id):
        self.resourceinstanceid = resourceinstanceid
        self.graph_id = graph_id


class FakeTile:
    def __init__(self, tileid):
        self.tileid = tileid


class FakeNode:
    def __init__(self, nodeid):
        self.nodeid = nodeid


class FakeValue:
    def __init__(self, valueid, value):
        self.valueid = valueid
        self.value = value


class _FilterResult:
    def __init__(self, rows):
        self.rows = list(rows)

    def values(self, *fields):
        return list(self.rows)


class RecordingRxrManager:
    def __init__(self, existing_types=(), already_present=()):
        self.existing_types = list(existing_types)
        self.already_present = {(str(a), str(b)) for a, b in already_present}
        self.get_or_create_calls = []

    def filter(self, **kwargs):
        return _FilterResult(self.existing_types)

    def get_or_create(self, **kwargs):
        self.get_or_create_calls.append(kwargs)
        pair = (str(kwargs["from_resource_id"]), str(kwargs["to_resource_id"]))
        return (object(), pair not in self.already_present)


class _LookupManager:
    def __init__(self, objects, key, exception):
        self.by_id = {str(getattr(o, key)): o for o in objects}
        self.key = key
        self.exception = exception
        self.get_calls = []

    def get(self, **kwargs):
        wanted = str(kwargs[self.key])
        self.get_calls.append(wanted)
        try:
            return self.by_id[wanted]
        except KeyError:
            raise self.exception(wanted)


class RecordingAtomic:
    """Stand-in for ``transaction.atomic`` recording how each block ended.

    ``blocks`` holds one entry per ``with`` block, in order: ``None`` for a
    clean exit (commit), the exception class for one that propagated out
    (rollback).
    """

    def __init__(self):
        self.blocks = []

    def __call__(self, *args, **kwargs):
        return _AtomicBlock(self)


class _AtomicBlock:
    def __init__(self, recorder):
        self.recorder = recorder
        self.index = None

    def __enter__(self):
        self.recorder.blocks.append(None)
        self.index = len(self.recorder.blocks) - 1
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.recorder.blocks[self.index] = exc_type
        return False


class Harness:
    def __init__(
        self,
        resources=None,
        tiles=None,
        nodes=None,
        values=(),
        existing_types=(),
        already_present=(),
    ):
        if resources is None:
            resources = [
                FakeResource(SOURCE_ID, ANALYSIS_GRAPH),
                FakeResource(TARGET_ID, COMPONENT_GRAPH),
                FakeResource(OTHER_TARGET_ID, COMPONENT_GRAPH),
            ]
        if tiles is None:
            tiles = [FakeTile(TILE_ID)]
        if nodes is None:
            nodes = [FakeNode(NODE_ID)]
        self.rxr = RecordingRxrManager(existing_types, already_present)
        self.resources = _LookupManager(
            resources, "resourceinstanceid", ResourceDoesNotExist
        )
        self.tiles = _LookupManager(tiles, "tileid", TileDoesNotExist)
        self.nodes = _LookupManager(nodes, "nodeid", NodeDoesNotExist)
        self.values = _LookupManager(values, "valueid", ValueDoesNotExist)
        self.atomic = RecordingAtomic()

    def run(self, input_file, **options):
        out = StringIO()
        with (
            patch.object(cmd, "ResourceXResource") as rxr_cls,
            patch.object(cmd, "Resource") as resource_cls,
            patch.object(cmd, "Tile") as tile_cls,
            patch.object(cmd, "Node") as node_cls,
            patch.object(cmd, "Value") as value_cls,
            patch.object(cmd, "transaction", SimpleNamespace(atomic=self.atomic)),
        ):
            rxr_cls.objects = self.rxr
            rxr_cls.DoesNotExist = LookupError
            resource_cls.objects = self.resources
            resource_cls.DoesNotExist = ResourceDoesNotExist
            tile_cls.objects = self.tiles
            tile_cls.DoesNotExist = TileDoesNotExist
            node_cls.objects = self.nodes
            node_cls.DoesNotExist = NodeDoesNotExist
            value_cls.objects = self.values
            value_cls.DoesNotExist = ValueDoesNotExist
            call_command(
                "import_relations_csv", input=input_file, stdout=out, **options
            )
        return out.getvalue()

    @property
    def written_pairs(self):
        return [
            (call["from_resource_id"], call["to_resource_id"])
            for call in self.rxr.get_or_create_calls
        ]


def _row(**overrides):
    row = {
        "relation_type": "Analysis→Component",
        "source_id": SOURCE_ID,
        "source_name": "Analysis 1",
        "source_graph": "Analysis",
        "target_id": TARGET_ID,
        "target_name": "Component 1",
        "target_graph": "Component",
        "tile_id": TILE_ID,
        "node_id": NODE_ID,
        "nodegroup_id": NODEGROUP_ID,
        "rxr_exists": "NON",
        "action": "CREATE",
        "status": "MISSING",
    }
    row.update(overrides)
    return row


class ImportCommandTestCase(SimpleTestCase):
    def run_rows(self, rows, harness=None, fieldnames=FIELDNAMES, **options):
        harness = harness or Harness()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "relations.csv")
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            output = harness.run(path, **options)
        return output, harness

    def run_text(self, text, harness=None, **options):
        harness = harness or Harness()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "relations.csv")
            with open(path, "w", newline="", encoding="utf-8") as handle:
                handle.write(text)
            output = harness.run(path, **options)
        return output, harness


class DryRunBoundaryTests(ImportCommandTestCase):
    def test_dry_run_writes_nothing(self):
        output, harness = self.run_rows(
            [_row(), _row(target_id=OTHER_TARGET_ID)], dry_run=True
        )
        self.assertEqual(harness.rxr.get_or_create_calls, [])
        self.assertEqual(harness.atomic.blocks, [])
        self.assertEqual(harness.resources.get_calls, [])
        self.assertIn("MODE DRY RUN - No modifications", output)
        self.assertIn("END OF DRY RUN", output)
        self.assertIn("Relations to create: 2", output)

    def test_dry_run_previews_the_first_twenty_relations_only(self):
        rows = [_row(source_name=f"Analysis {i:02d}") for i in range(25)]
        output, harness = self.run_rows(rows, dry_run=True)
        self.assertEqual(harness.rxr.get_or_create_calls, [])
        self.assertIn("  1. Analysis→Component: Analysis 00 → Component 1", output)
        self.assertIn("  20. Analysis→Component: Analysis 19 → Component 1", output)
        self.assertNotIn("  21. ", output)
        self.assertIn("... and 5 more", output)

    def test_write_run_creates_exactly_the_create_rows(self):
        harness = Harness()
        output, harness = self.run_rows(
            [
                _row(),
                _row(target_id=OTHER_TARGET_ID, action="SKIP", status="OK"),
                _row(
                    target_id=OTHER_TARGET_ID, action="ERROR", status="INVALID_TARGET"
                ),
            ],
            harness=harness,
        )
        self.assertEqual(
            harness.rxr.get_or_create_calls,
            [
                {
                    "from_resource_id": SOURCE_ID,
                    "to_resource_id": TARGET_ID,
                    "defaults": {
                        "from_resource_graph_id": ANALYSIS_GRAPH,
                        "to_resource_graph_id": COMPONENT_GRAPH,
                        "tile": harness.tiles.by_id[TILE_ID],
                        "node": harness.nodes.by_id[NODE_ID],
                        "relationshiptype": DEFAULT_REL_UUID,
                        "inverserelationshiptype": DEFAULT_REL_UUID,
                        "notes": ANY,
                    },
                }
            ],
        )
        self.assertIn("✓ Relations created: 1", output)


class RowSelectionTests(ImportCommandTestCase):
    def test_counters_report_created_skipped_and_error_lines(self):
        output, harness = self.run_rows(
            [
                _row(),
                _row(target_id=OTHER_TARGET_ID),
                _row(action="SKIP", status="OK"),
                _row(action="ERROR", status="INVALID_TARGET"),
            ]
        )
        self.assertIn("Relations to create: 2", output)
        self.assertIn("Relations skipped (SKIP): 1", output)
        self.assertIn("Error lines ignored: 1", output)
        self.assertIn("✓ Relations created: 2", output)
        self.assertIn("  Relations already existed: 0", output)

    def test_create_row_with_an_error_status_is_dropped_as_an_error_line(self):
        for status in ("INVALID_TARGET", "ERROR"):
            with self.subTest(status=status):
                output, harness = self.run_rows([_row(status=status)])
                self.assertEqual(harness.rxr.get_or_create_calls, [])
                self.assertIn("Error lines ignored: 1", output)
                self.assertIn("No relations to create!", output)

    def test_skip_wins_over_an_error_status(self):
        output, harness = self.run_rows([_row(action="SKIP", status="INVALID_TARGET")])
        self.assertIn("Relations skipped (SKIP): 1", output)
        self.assertIn("Error lines ignored: 0", output)

    def test_action_and_status_are_matched_case_insensitively_and_trimmed(self):
        output, harness = self.run_rows([_row(action=" create ", status=" missing ")])
        self.assertEqual(harness.written_pairs, [(SOURCE_ID, TARGET_ID)])

    def test_row_with_an_unrecognised_action_is_dropped_without_being_counted(self):
        """Characterisation, not endorsement.

        Only SKIP, ERROR and CREATE are recognised. Anything else — including an
        empty ``action`` cell — is dropped silently: it appears in none of the
        three counters the command reports, so a typo in a hand-edited CSV loses
        rows without a word.
        """
        output, harness = self.run_rows([_row(action="MAYBE"), _row(action="")])
        self.assertEqual(harness.rxr.get_or_create_calls, [])
        self.assertIn("Relations to create: 0", output)
        self.assertIn("Relations skipped (SKIP): 0", output)
        self.assertIn("Error lines ignored: 0", output)
        self.assertIn("No relations to create!", output)

    def test_ids_are_trimmed_before_being_written(self):
        output, harness = self.run_rows(
            [_row(source_id=f"  {SOURCE_ID} ", target_id=f"{TARGET_ID}  ")]
        )
        self.assertEqual(harness.written_pairs, [(SOURCE_ID, TARGET_ID)])


class MalformedInputTests(ImportCommandTestCase):
    def test_empty_file_reports_nothing_to_create(self):
        output, harness = self.run_text("")
        self.assertEqual(harness.rxr.get_or_create_calls, [])
        self.assertIn("Relations to create: 0", output)
        self.assertIn("No relations to create!", output)

    def test_header_only_file_reports_nothing_to_create(self):
        output, harness = self.run_rows([])
        self.assertEqual(harness.rxr.get_or_create_calls, [])
        self.assertIn("No relations to create!", output)

    def test_missing_source_id_column_raises_keyerror(self):
        """Characterisation, not endorsement.

        A CSV missing one of the two id columns dies on a bare ``KeyError``
        escaping ``handle`` — a traceback, not a ``CommandError`` naming the
        offending column.
        """
        fieldnames = [f for f in FIELDNAMES if f != "source_id"]
        rows = [{k: v for k, v in _row().items() if k != "source_id"}]
        with self.assertRaises(KeyError) as caught:
            self.run_rows(rows, fieldnames=fieldnames)
        self.assertEqual(caught.exception.args[0], "source_id")

    def test_truncated_row_raises_attributeerror(self):
        """Characterisation, not endorsement.

        ``csv.DictReader`` pads a short row with ``None``, and the command calls
        ``.strip()`` on the ``action`` cell unconditionally, so a row cut off
        before the last columns raises ``AttributeError`` rather than being
        reported as malformed.
        """
        text = ",".join(FIELDNAMES) + "\n" + f"Analysis→Component,{SOURCE_ID}\n"
        with self.assertRaises(AttributeError):
            self.run_text(text)

    def test_extra_columns_are_ignored(self):
        text = (
            ",".join(FIELDNAMES)
            + "\n"
            + ",".join(_row()[name] for name in FIELDNAMES)
            + ",surplus\n"
        )
        output, harness = self.run_text(text)
        self.assertEqual(harness.written_pairs, [(SOURCE_ID, TARGET_ID)])

    def test_unreadable_input_path_raises_filenotfounderror(self):
        """Characterisation, not endorsement.

        ``--input`` pointing at nothing raises a raw ``FileNotFoundError``
        instead of a ``CommandError``, so the CLI prints a traceback.
        """
        harness = Harness()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                harness.run(os.path.join(tmp, "absent.csv"))


class MissingReferenceTests(ImportCommandTestCase):
    def test_missing_source_resource_aborts_the_batch_and_the_import(self):
        harness = Harness(resources=[FakeResource(TARGET_ID, COMPONENT_GRAPH)])
        output, harness = self.run_rows([_row()], harness=harness)
        self.assertEqual(harness.rxr.get_or_create_calls, [])
        self.assertEqual(harness.atomic.blocks, [Exception])
        self.assertIn("✗ Fatal error in batch 1: Source resource not found:", output)
        self.assertIn("Import cancelled. Use --skip-errors to continue", output)
        self.assertNotIn("IMPORT SUMMARY", output)

    def test_missing_target_resource_aborts_the_batch_and_the_import(self):
        harness = Harness(resources=[FakeResource(SOURCE_ID, ANALYSIS_GRAPH)])
        output, harness = self.run_rows([_row()], harness=harness)
        self.assertEqual(harness.rxr.get_or_create_calls, [])
        self.assertIn("✗ Fatal error in batch 1: Target resource not found:", output)

    def test_skip_errors_reports_the_failing_row_and_writes_the_others(self):
        harness = Harness(
            resources=[
                FakeResource(SOURCE_ID, ANALYSIS_GRAPH),
                FakeResource(OTHER_TARGET_ID, COMPONENT_GRAPH),
            ]
        )
        output, harness = self.run_rows(
            [_row(), _row(target_id=OTHER_TARGET_ID)],
            harness=harness,
            skip_errors=True,
        )
        self.assertEqual(harness.written_pairs, [(SOURCE_ID, OTHER_TARGET_ID)])
        self.assertEqual(harness.atomic.blocks, [None])
        self.assertIn("✗ Row 2: Target resource not found: 22222222...", output)
        self.assertIn("✓ Relations created: 1", output)
        self.assertIn("✗ Errors: 1", output)
        self.assertIn("  - Row 2: Target resource not found: 22222222...", output)

    def test_missing_tile_is_written_without_a_tile_reference(self):
        harness = Harness(tiles=[])
        output, harness = self.run_rows([_row()], harness=harness)
        self.assertIsNone(harness.rxr.get_or_create_calls[0]["defaults"]["tile"])
        self.assertIn("⚠️  Some tiles not found, continuing without tile", output)

    def test_missing_node_is_written_without_a_node_reference(self):
        harness = Harness(nodes=[])
        output, harness = self.run_rows([_row()], harness=harness)
        self.assertIsNone(harness.rxr.get_or_create_calls[0]["defaults"]["node"])

    def test_empty_tile_and_node_cells_skip_the_lookups(self):
        output, harness = self.run_rows([_row(tile_id="", node_id="")])
        self.assertEqual(harness.tiles.get_calls, [])
        self.assertEqual(harness.nodes.get_calls, [])
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertIsNone(defaults["tile"])
        self.assertIsNone(defaults["node"])


class BatchAndTransactionTests(ImportCommandTestCase):
    def test_each_batch_runs_in_its_own_transaction(self):
        rows = [_row(), _row(target_id=OTHER_TARGET_ID), _row()]
        output, harness = self.run_rows(rows, batch_size=1)
        self.assertEqual(harness.atomic.blocks, [None, None, None])
        self.assertEqual(len(harness.rxr.get_or_create_calls), 3)
        self.assertIn("Batch 1/3...", output)
        self.assertIn("Batch 3/3...", output)

    def test_default_batch_size_puts_every_row_in_one_transaction(self):
        rows = [_row() for _ in range(3)]
        output, harness = self.run_rows(rows)
        self.assertEqual(harness.atomic.blocks, [None])
        self.assertIn("Batch 1/1...", output)
        self.assertIn("Progress: 3/3 (3 created)", output)

    def test_earlier_batches_are_not_undone_when_a_later_batch_aborts(self):
        """Characterisation, not endorsement.

        The transaction is per batch, so aborting on row 2 leaves row 1's write
        committed and never reaches row 3 — an import stopped halfway is a
        partially applied import, despite the "all or nothing" wording in the
        module docstring.
        """
        harness = Harness(
            resources=[
                FakeResource(SOURCE_ID, ANALYSIS_GRAPH),
                FakeResource(OTHER_TARGET_ID, COMPONENT_GRAPH),
            ]
        )
        output, harness = self.run_rows(
            [
                _row(target_id=OTHER_TARGET_ID),
                _row(),
                _row(target_id=OTHER_TARGET_ID),
            ],
            harness=harness,
            batch_size=1,
        )
        self.assertEqual(harness.written_pairs, [(SOURCE_ID, OTHER_TARGET_ID)])
        self.assertEqual(harness.atomic.blocks, [None, Exception])
        self.assertIn("✗ Fatal error in batch 2:", output)

    def test_existing_relation_is_counted_as_already_existed(self):
        harness = Harness(already_present=[(SOURCE_ID, TARGET_ID)])
        output, harness = self.run_rows(
            [_row(), _row(target_id=OTHER_TARGET_ID)], harness=harness
        )
        self.assertEqual(len(harness.rxr.get_or_create_calls), 2)
        self.assertIn("✓ Relations created: 1", output)
        self.assertIn("  Relations already existed: 1", output)


class FieldInclusionTests(ImportCommandTestCase):
    def test_notes_record_the_source_and_target_names(self):
        output, harness = self.run_rows([_row()])
        notes = harness.rxr.get_or_create_calls[0]["defaults"]["notes"]
        self.assertTrue(notes.startswith("Auto-imported from CSV on "))
        self.assertIn("Source: Analysis 1 → Target: Component 1", notes)

    def test_exclusion_flags_leave_tile_node_and_notes_unset(self):
        output, harness = self.run_rows(
            [_row()], exclude_tile=True, exclude_node=True, exclude_notes=True
        )
        self.assertEqual(harness.tiles.get_calls, [])
        self.assertEqual(harness.nodes.get_calls, [])
        self.assertEqual(
            harness.rxr.get_or_create_calls[0]["defaults"],
            {
                "from_resource_graph_id": ANALYSIS_GRAPH,
                "to_resource_graph_id": COMPONENT_GRAPH,
                "tile": None,
                "node": None,
                "relationshiptype": DEFAULT_REL_UUID,
                "inverserelationshiptype": DEFAULT_REL_UUID,
                "notes": None,
            },
        )
        self.assertIn("Tile reference: NO", output)
        self.assertIn("Node reference: NO", output)
        self.assertIn("Auto notes: NO", output)


class RelationshipTypeDetectionTests(ImportCommandTestCase):
    def test_no_existing_relation_falls_back_to_the_is_related_to_uuid(self):
        output, harness = self.run_rows([_row()])
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertEqual(defaults["relationshiptype"], DEFAULT_REL_UUID)
        self.assertEqual(defaults["inverserelationshiptype"], DEFAULT_REL_UUID)
        self.assertIn("No existing relations found, using default UUID", output)

    def test_most_common_uuid_is_reused_with_its_most_common_inverse(self):
        harness = Harness(
            existing_types=[
                {
                    "relationshiptype": OTHER_REL_UUID,
                    "inverserelationshiptype": INVERSE_REL_UUID,
                },
                {
                    "relationshiptype": OTHER_REL_UUID,
                    "inverserelationshiptype": INVERSE_REL_UUID,
                },
                {
                    "relationshiptype": DEFAULT_REL_UUID,
                    "inverserelationshiptype": None,
                },
            ]
        )
        output, harness = self.run_rows([_row()], harness=harness)
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertEqual(defaults["relationshiptype"], OTHER_REL_UUID)
        self.assertEqual(defaults["inverserelationshiptype"], INVERSE_REL_UUID)
        self.assertIn(f"✓ Using UUID format (most common): {OTHER_REL_UUID}", output)
        self.assertIn(f"✓ Asymmetric relation (inverse: {INVERSE_REL_UUID})", output)
        self.assertIn("Relation is: ASYMMETRIC (directional)", output)

    def test_inverse_equal_to_the_main_type_is_announced_as_symmetric(self):
        harness = Harness(
            existing_types=[
                {
                    "relationshiptype": OTHER_REL_UUID,
                    "inverserelationshiptype": OTHER_REL_UUID,
                }
            ]
        )
        output, harness = self.run_rows([_row()], harness=harness)
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertEqual(defaults["inverserelationshiptype"], OTHER_REL_UUID)
        self.assertIn("✓ Symmetric relation (inverse same as main)", output)
        self.assertIn("Relation is: SYMMETRIC (bidirectional)", output)

    def test_only_string_types_are_reused_and_related_is_treated_as_symmetric(self):
        harness = Harness(
            existing_types=[
                {"relationshiptype": "related", "inverserelationshiptype": None}
            ]
        )
        output, harness = self.run_rows([_row()], harness=harness)
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertEqual(defaults["relationshiptype"], "related")
        self.assertEqual(defaults["inverserelationshiptype"], "related")
        self.assertIn("⚠️  Only string format found: 'related'", output)

    def test_uuid_is_preferred_even_when_a_string_type_is_more_common(self):
        """Characterisation, not endorsement.

        With a legacy ``related`` string on most rows and a UUID on one, the
        command silently switches new relations to the minority UUID format.
        """
        harness = Harness(
            existing_types=[
                {"relationshiptype": "related", "inverserelationshiptype": None},
                {"relationshiptype": "related", "inverserelationshiptype": None},
                {"relationshiptype": OTHER_REL_UUID, "inverserelationshiptype": None},
            ]
        )
        output, harness = self.run_rows([_row()], harness=harness)
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertEqual(defaults["relationshiptype"], OTHER_REL_UUID)
        self.assertIn(
            f"⚠️  String format 'related' is most common, but using UUID: "
            f"{OTHER_REL_UUID}",
            output,
        )

    def test_force_uuid_labels_the_choice_as_forced(self):
        harness = Harness(
            existing_types=[
                {"relationshiptype": OTHER_REL_UUID, "inverserelationshiptype": None},
                {"relationshiptype": OTHER_REL_UUID, "inverserelationshiptype": None},
            ]
        )
        output, harness = self.run_rows([_row()], harness=harness, force_uuid=True)
        self.assertEqual(
            harness.rxr.get_or_create_calls[0]["defaults"]["relationshiptype"],
            OTHER_REL_UUID,
        )
        self.assertIn(f"✓ Using UUID format (forced): {OTHER_REL_UUID}", output)

    def test_symmetric_concept_label_sets_the_inverse_to_the_same_uuid(self):
        harness = Harness(
            values=[FakeValue(OTHER_REL_UUID, "Is Related To")],
            existing_types=[
                {"relationshiptype": OTHER_REL_UUID, "inverserelationshiptype": None}
            ],
        )
        output, harness = self.run_rows([_row()], harness=harness)
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertEqual(defaults["inverserelationshiptype"], OTHER_REL_UUID)
        self.assertIn('✓ Detected symmetric relation: "Is Related To"', output)

    def test_non_symmetric_concept_label_leaves_the_inverse_unset(self):
        harness = Harness(
            values=[FakeValue(OTHER_REL_UUID, "is part of")],
            existing_types=[
                {"relationshiptype": OTHER_REL_UUID, "inverserelationshiptype": None}
            ],
        )
        output, harness = self.run_rows([_row()], harness=harness)
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertIsNone(defaults["inverserelationshiptype"])
        self.assertIn('ℹ Detected non-symmetric relation: "is part of"', output)
        self.assertIn("Relation is: DIRECTIONAL (one-way)", output)

    def test_uuid_absent_from_the_rdm_leaves_the_inverse_unset(self):
        harness = Harness(
            existing_types=[
                {"relationshiptype": OTHER_REL_UUID, "inverserelationshiptype": None}
            ]
        )
        output, harness = self.run_rows([_row()], harness=harness)
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertIsNone(defaults["inverserelationshiptype"])
        self.assertIn("ℹ Cannot determine symmetry, inverse set to None", output)
        self.assertIn("⚠️  Concept not found in RDM", output)

    def test_manual_string_relationship_type_is_used_verbatim(self):
        output, harness = self.run_rows([_row()], relationship_type="related")
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertEqual(defaults["relationshiptype"], "related")
        self.assertEqual(defaults["inverserelationshiptype"], "related")
        self.assertNotIn("No existing relations found", output)

    def test_manual_non_uuid_non_related_type_gets_no_inverse(self):
        output, harness = self.run_rows([_row()], relationship_type="depicts")
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertEqual(defaults["relationshiptype"], "depicts")
        self.assertIsNone(defaults["inverserelationshiptype"])

    def test_manual_uuid_type_takes_its_inverse_from_the_concept_label(self):
        harness = Harness(values=[FakeValue(OTHER_REL_UUID, "is associated with")])
        output, harness = self.run_rows(
            [_row()], harness=harness, relationship_type=OTHER_REL_UUID
        )
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertEqual(defaults["inverserelationshiptype"], OTHER_REL_UUID)
        self.assertIn("Detected symmetric relation from concept label", output)

    def test_manual_uuid_type_absent_from_the_rdm_gets_no_inverse(self):
        output, harness = self.run_rows([_row()], relationship_type=OTHER_REL_UUID)
        defaults = harness.rxr.get_or_create_calls[0]["defaults"]
        self.assertEqual(defaults["relationshiptype"], OTHER_REL_UUID)
        self.assertIsNone(defaults["inverserelationshiptype"])


class IsUuidTests(SimpleTestCase):
    def test_accepts_uuid_strings_and_rejects_everything_else(self):
        is_uuid = cmd.Command()._is_uuid
        self.assertTrue(is_uuid(DEFAULT_REL_UUID))
        self.assertTrue(is_uuid(DEFAULT_REL_UUID.replace("-", "")))
        self.assertFalse(is_uuid("related"))
        self.assertFalse(is_uuid(""))
        self.assertFalse(is_uuid(None))
        self.assertFalse(is_uuid(12345))
