"""Characterisation tests for the export_relations_csv management command.

The command is the source of truth for the relations CSV format that the three
sibling commands read back, so the header and the value vocabulary of every
column are pinned literally here.

Nothing in the file touches a database: the Arches managers are replaced at the
command-module level and every CSV is written inside a temporary directory.
Several tests pin behaviour that looks like a defect; their docstrings say so.
"""

import csv
import os
import tempfile
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from manuspectrum.management.commands import export_relations_csv as cmd

ANALYSIS_GRAPH = "60c85aba-f079-45bc-997f-21cdd4f77b6d"
COMPONENT_GRAPH = "d47595b4-f8a6-419c-8f33-b388206280c4"
UNKNOWN_GRAPH = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

SOURCE_ID = "11111111-1111-4111-8111-111111111111"
TARGET_ID = "22222222-2222-4222-8222-222222222222"
OTHER_TARGET_ID = "66666666-6666-4666-8666-666666666666"
TILE_ID = "33333333-3333-4333-8333-333333333333"
NODEGROUP_ID = "44444444-4444-4444-8444-444444444444"
RI_NODE = "55555555-5555-4555-8555-555555555555"
CONCEPT_NODE = "77777777-7777-4777-8777-777777777777"

HEADER = [
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


class FakeQuerySet(list):
    def count(self):
        return len(self)

    def exists(self):
        return bool(self)


class FakeNode:
    def __init__(self, nodeid, name, graph_id, datatype="resource-instance"):
        self.nodeid = nodeid
        self.name = name
        self.graph_id = graph_id
        self.datatype = datatype


class FakeTile:
    def __init__(self, data, tileid=TILE_ID, nodegroup_id=NODEGROUP_ID):
        self.tileid = tileid
        self.data = data
        self.nodegroup_id = nodegroup_id


class FakeResource:
    def __init__(self, resourceinstanceid, graph_id, displayname="unnamed"):
        self.resourceinstanceid = resourceinstanceid
        self.graph_id = graph_id
        self._displayname = displayname

    def displayname(self, context=None):
        if isinstance(self._displayname, BaseException):
            raise self._displayname
        return self._displayname


class FakeNodeManager:
    def __init__(self, nodes):
        self.nodes = list(nodes)

    def filter(self, **kwargs):
        found = self.nodes
        if "graph_id" in kwargs:
            found = [n for n in found if str(n.graph_id) == str(kwargs["graph_id"])]
        if "datatype" in kwargs:
            found = [n for n in found if n.datatype == kwargs["datatype"]]
        if "datatype__startswith" in kwargs:
            prefix = kwargs["datatype__startswith"]
            found = [n for n in found if n.datatype.startswith(prefix)]
        return FakeQuerySet(found)


class FakeResourceManager:
    def __init__(self, resources, lookup_errors=None):
        self.by_id = {str(r.resourceinstanceid): r for r in resources}
        self.lookup_errors = lookup_errors or {}

    def filter(self, graph_id=None, **kwargs):
        return FakeQuerySet(
            [r for r in self.by_id.values() if str(r.graph_id) == str(graph_id)]
        )

    def get(self, resourceinstanceid=None, **kwargs):
        key = str(resourceinstanceid)
        if key in self.lookup_errors:
            raise self.lookup_errors[key]
        try:
            return self.by_id[key]
        except KeyError:
            raise ResourceDoesNotExist(key)


class FakeTileManager:
    def __init__(self, tiles_by_resource):
        self.by_resource = {str(k): list(v) for k, v in tiles_by_resource.items()}

    def filter(self, resourceinstance_id=None, **kwargs):
        return FakeQuerySet(self.by_resource.get(str(resourceinstance_id), []))


class FakeRxrManager:
    def __init__(self, pairs):
        self.pairs = {(str(a), str(b)) for a, b in pairs}

    def filter(self, from_resource_id=None, to_resource_id=None, **kwargs):
        present = (str(from_resource_id), str(to_resource_id)) in self.pairs
        return FakeQuerySet([1] if present else [])


def _run(
    *,
    resources=(),
    tiles_by_resource=None,
    nodes=(),
    rxr_pairs=(),
    lookup_errors=None,
    **options,
):
    out = StringIO()
    with (
        patch.object(cmd, "Node") as node_cls,
        patch.object(cmd, "Resource") as resource_cls,
        patch.object(cmd, "Tile") as tile_cls,
        patch.object(cmd, "ResourceXResource") as rxr_cls,
    ):
        node_cls.objects = FakeNodeManager(nodes)
        resource_cls.objects = FakeResourceManager(resources, lookup_errors)
        resource_cls.DoesNotExist = ResourceDoesNotExist
        tile_cls.objects = FakeTileManager(tiles_by_resource or {})
        rxr_cls.objects = FakeRxrManager(rxr_pairs)
        call_command("export_relations_csv", stdout=out, **options)
    return out.getvalue()


def _run_in_tmp(**kwargs):
    """Run the command for its stdout only, writing the CSV somewhere disposable."""
    with tempfile.TemporaryDirectory() as tmp:
        return _run(output=os.path.join(tmp, "relations.csv"), **kwargs)


def _export(**kwargs):
    """Run the command into a throwaway CSV; return (rows, header, stdout)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "relations.csv")
        output = _run(output=path, **kwargs)
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            rows = [dict(zip(header, raw)) for raw in reader]
    return rows, header, output


def _scenario(value, *, targets=(), rxr_pairs=(), lookup_errors=None, source=None):
    source = source or FakeResource(SOURCE_ID, ANALYSIS_GRAPH, "Analysis 1")
    tile = FakeTile({RI_NODE: value})
    return {
        "resources": [source, *targets],
        "tiles_by_resource": {source.resourceinstanceid: [tile]},
        "nodes": [FakeNode(RI_NODE, "Component ref", ANALYSIS_GRAPH)],
        "rxr_pairs": rxr_pairs,
        "lookup_errors": lookup_errors,
    }


def _component(resource_id=TARGET_ID, name="Component 1"):
    return FakeResource(resource_id, COMPONENT_GRAPH, name)


class CsvContractTests(SimpleTestCase):
    def test_header_is_the_thirteen_columns_in_export_order(self):
        _, header, _ = _export(**_scenario(None))
        self.assertEqual(header, HEADER)

    def test_relation_already_in_resourcexresource_is_a_fully_populated_ok_row(self):
        rows, _, _ = _export(
            **_scenario(
                TARGET_ID,
                targets=[_component()],
                rxr_pairs=[(SOURCE_ID, TARGET_ID)],
            )
        )
        self.assertEqual(
            rows,
            [
                {
                    "relation_type": "Analysis→Component",
                    "source_id": SOURCE_ID,
                    "source_name": "Analysis 1",
                    "source_graph": "Analysis",
                    "target_id": TARGET_ID,
                    "target_name": "Component 1",
                    "target_graph": "Component",
                    "tile_id": TILE_ID,
                    "node_id": RI_NODE,
                    "nodegroup_id": NODEGROUP_ID,
                    "rxr_exists": "OUI",
                    "action": "SKIP",
                    "status": "OK",
                }
            ],
        )

    def test_relation_absent_from_resourcexresource_is_marked_create(self):
        rows, _, _ = _export(**_scenario(TARGET_ID, targets=[_component()]))
        self.assertEqual(rows[0]["rxr_exists"], "NON")
        self.assertEqual(rows[0]["action"], "CREATE")
        self.assertEqual(rows[0]["status"], "MISSING")

    def test_unknown_target_resource_is_marked_invalid_target(self):
        rows, _, _ = _export(**_scenario(TARGET_ID))
        self.assertEqual(
            {k: rows[0][k] for k in HEADER[4:]},
            {
                "target_id": TARGET_ID,
                "target_name": "⚠️ RESOURCE NOT FOUND",
                "target_graph": "???",
                "tile_id": TILE_ID,
                "node_id": RI_NODE,
                "nodegroup_id": NODEGROUP_ID,
                "rxr_exists": "N/A",
                "action": "ERROR",
                "status": "INVALID_TARGET",
            },
        )
        self.assertEqual(rows[0]["relation_type"], "Analysis→???")

    def test_unexpected_lookup_failure_is_marked_error_with_a_truncated_message(self):
        rows, _, _ = _export(
            **_scenario(
                TARGET_ID,
                lookup_errors={TARGET_ID: RuntimeError("connection reset")},
            )
        )
        self.assertEqual(rows[0]["status"], "ERROR")
        self.assertEqual(rows[0]["action"], "ERROR")
        self.assertEqual(rows[0]["rxr_exists"], "N/A")
        self.assertEqual(rows[0]["target_name"], "⚠️ ERROR: connection reset")
        self.assertEqual(rows[0]["relation_type"], "Analysis→???")

    def test_rows_are_sorted_by_relation_type_then_source_name(self):
        early = FakeResource(SOURCE_ID, ANALYSIS_GRAPH, "AAA source")
        late = FakeResource(OTHER_TARGET_ID, ANALYSIS_GRAPH, "ZZZ source")
        missing_target = "88888888-8888-4888-8888-888888888888"
        rows, _, _ = _export(
            resources=[late, early, _component()],
            tiles_by_resource={
                late.resourceinstanceid: [FakeTile({RI_NODE: TARGET_ID})],
                early.resourceinstanceid: [
                    FakeTile({RI_NODE: [TARGET_ID, missing_target]})
                ],
            },
            nodes=[FakeNode(RI_NODE, "Component ref", ANALYSIS_GRAPH)],
        )
        self.assertEqual(
            [(r["relation_type"], r["source_name"]) for r in rows],
            [
                ("Analysis→???", "AAA source"),
                ("Analysis→Component", "AAA source"),
                ("Analysis→Component", "ZZZ source"),
            ],
        )

    def test_export_without_any_relation_writes_only_the_header(self):
        rows, header, _ = _export(**_scenario(None))
        self.assertEqual(header, HEADER)
        self.assertEqual(rows, [])


class ExtractResourceIdsTests(SimpleTestCase):
    """``extract_resource_ids`` is a closure inside ``handle``; reached by running it."""

    def _target_ids(self, value, **kwargs):
        rows, _, _ = _export(**_scenario(value, **kwargs))
        return [row["target_id"] for row in rows]

    def test_bare_uuid_string_yields_one_target(self):
        self.assertEqual(self._target_ids(TARGET_ID), [TARGET_ID])

    def test_list_of_uuid_strings_yields_one_target_each(self):
        self.assertEqual(
            self._target_ids([TARGET_ID, OTHER_TARGET_ID]),
            [TARGET_ID, OTHER_TARGET_ID],
        )

    def test_list_of_dicts_carrying_resource_id_yields_one_target_each(self):
        value = [
            {
                "resourceId": TARGET_ID,
                "ontologyProperty": "",
                "resourceXresourceId": "",
            },
            {"resourceId": OTHER_TARGET_ID},
        ]
        self.assertEqual(self._target_ids(value), [TARGET_ID, OTHER_TARGET_ID])

    def test_mixed_list_keeps_uuids_and_resource_id_dicts_and_drops_the_rest(self):
        value = [
            TARGET_ID,
            {"resourceId": OTHER_TARGET_ID},
            {"resourceId": "not-a-uuid"},
            {"resourceId": None},
            {"noResourceIdHere": TARGET_ID},
            "plain text",
            [TARGET_ID],
            None,
            42,
        ]
        self.assertEqual(self._target_ids(value), [TARGET_ID, OTHER_TARGET_ID])

    def test_none_value_yields_no_target(self):
        self.assertEqual(self._target_ids(None), [])

    def test_non_uuid_string_yields_no_target(self):
        self.assertEqual(self._target_ids("Bibliothèque nationale"), [])

    def test_malformed_uuid_is_dropped_instead_of_being_reported_as_invalid(self):
        """Characterisation, not endorsement.

        A node value that is nearly a UUID never reaches the CSV at all, so the
        INVALID_TARGET status is unreachable for corrupt values: it only fires
        for well-formed UUIDs pointing at a deleted resource. A malformed
        reference is silently invisible to the audit the command exists for.
        """
        self.assertEqual(self._target_ids("22222222-2222-4222-8222-2222222222"), [])
        self.assertEqual(self._target_ids([TARGET_ID + "x"]), [])

    def test_top_level_dict_value_yields_no_target(self):
        """Characterisation, not endorsement.

        Only ``str`` and ``list`` values are inspected, so a resource-instance
        node whose tile value is a bare ``{"resourceId": ...}`` dict rather than
        a list of them exports nothing.
        """
        self.assertEqual(self._target_ids({"resourceId": TARGET_ID}), [])

    def test_nodes_outside_the_resource_instance_set_are_never_inspected(self):
        source = FakeResource(SOURCE_ID, ANALYSIS_GRAPH, "Analysis 1")
        rows, _, _ = _export(
            resources=[source, _component()],
            tiles_by_resource={
                SOURCE_ID: [FakeTile({CONCEPT_NODE: TARGET_ID, RI_NODE: TARGET_ID})]
            },
            nodes=[
                FakeNode(RI_NODE, "Component ref", ANALYSIS_GRAPH),
                FakeNode(CONCEPT_NODE, "Material", ANALYSIS_GRAPH, datatype="concept"),
            ],
        )
        self.assertEqual([row["node_id"] for row in rows], [RI_NODE])

    def test_tile_without_data_is_skipped(self):
        source = FakeResource(SOURCE_ID, ANALYSIS_GRAPH, "Analysis 1")
        rows, _, _ = _export(
            resources=[source, _component()],
            tiles_by_resource={
                SOURCE_ID: [
                    FakeTile(None),
                    FakeTile({}),
                    FakeTile({RI_NODE: TARGET_ID}, tileid=TILE_ID),
                ]
            },
            nodes=[FakeNode(RI_NODE, "Component ref", ANALYSIS_GRAPH)],
        )
        self.assertEqual([row["tile_id"] for row in rows], [TILE_ID])


class GraphNameTests(SimpleTestCase):
    def test_known_graph_uuid_resolves_to_its_name(self):
        rows, _, _ = _export(
            **_scenario(TARGET_ID, targets=[_component()]),
        )
        self.assertEqual(rows[0]["source_graph"], "Analysis")
        self.assertEqual(rows[0]["target_graph"], "Component")
        self.assertEqual(rows[0]["relation_type"], "Analysis→Component")

    def test_unknown_graph_uuid_resolves_to_its_first_eight_characters(self):
        source = FakeResource(SOURCE_ID, UNKNOWN_GRAPH, "Stray 1")
        target = FakeResource(TARGET_ID, UNKNOWN_GRAPH, "Stray 2")
        rows, _, output = _export(
            resources=[source, target],
            tiles_by_resource={SOURCE_ID: [FakeTile({RI_NODE: TARGET_ID})]},
            nodes=[FakeNode(RI_NODE, "Stray ref", UNKNOWN_GRAPH)],
            graph_id=UNKNOWN_GRAPH,
        )
        self.assertEqual(rows[0]["source_graph"], "Unknown(aaaaaaaa)")
        self.assertEqual(rows[0]["target_graph"], "Unknown(aaaaaaaa)")
        self.assertIn(f"Graph source filtré: {UNKNOWN_GRAPH}", output)

    def test_none_graph_id_resolves_to_unknown_none(self):
        rows, _, _ = _export(
            **_scenario(TARGET_ID, targets=[FakeResource(TARGET_ID, None, "Orphan")])
        )
        self.assertEqual(rows[0]["target_graph"], "Unknown(None)")
        self.assertEqual(rows[0]["relation_type"], "Analysis→Unknown(None)")


class DisplayNameTests(SimpleTestCase):
    def test_non_callable_displayname_is_stringified(self):
        source = FakeResource(SOURCE_ID, ANALYSIS_GRAPH)
        source.displayname = "Plain attribute"
        target = _component()
        target.displayname = "Target attribute"
        rows, _, _ = _export(**_scenario(TARGET_ID, targets=[target], source=source))
        self.assertEqual(rows[0]["source_name"], "Plain attribute")
        self.assertEqual(rows[0]["target_name"], "Target attribute")

    def test_failing_displayname_falls_back_to_the_first_eight_characters_of_the_id(
        self,
    ):
        source = FakeResource(
            SOURCE_ID, ANALYSIS_GRAPH, RuntimeError("no primary name")
        )
        target = FakeResource(TARGET_ID, COMPONENT_GRAPH, RuntimeError("boom"))
        rows, _, _ = _export(**_scenario(TARGET_ID, targets=[target], source=source))
        self.assertEqual(rows[0]["source_name"], SOURCE_ID[:8])
        self.assertEqual(rows[0]["target_name"], TARGET_ID[:8])


class CommandOptionTests(SimpleTestCase):
    def test_graph_id_option_scans_only_that_graph(self):
        analysis = FakeResource(SOURCE_ID, ANALYSIS_GRAPH, "Analysis 1")
        component = FakeResource(TARGET_ID, COMPONENT_GRAPH, "Component 1")
        shared = {
            "resources": [analysis, component],
            "tiles_by_resource": {
                SOURCE_ID: [FakeTile({RI_NODE: TARGET_ID})],
                TARGET_ID: [FakeTile({RI_NODE: SOURCE_ID}, tileid=NODEGROUP_ID)],
            },
            "nodes": [FakeNode(RI_NODE, "ref", ANALYSIS_GRAPH)],
        }
        both, _, output = _export(**shared)
        self.assertEqual(len(both), 2)
        self.assertIn("Tous les graphs seront analysés", output)

        filtered, _, _ = _export(graph_id=ANALYSIS_GRAPH, **shared)
        self.assertEqual([row["source_id"] for row in filtered], [SOURCE_ID])

    def test_output_option_names_the_written_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub-name.csv")
            output = _run(output=path, **_scenario(None))
            self.assertTrue(os.path.exists(path))
            self.assertIn(f"Fichier de sortie: {path}", output)
            self.assertIn(f"✓ Export terminé: {path}", output)

    def test_default_output_is_relations_export_csv_in_the_working_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = os.getcwd()
            os.chdir(tmp)
            try:
                _run(**_scenario(None))
            finally:
                os.chdir(previous)
            self.assertTrue(os.path.exists(os.path.join(tmp, "relations_export.csv")))


class SummaryOutputTests(SimpleTestCase):
    def test_totals_and_per_type_statistics_count_every_status(self):
        source = FakeResource(SOURCE_ID, ANALYSIS_GRAPH, "Analysis 1")
        known = _component()
        missing_target = "88888888-8888-4888-8888-888888888888"
        broken_target = "99999999-9999-4999-8999-999999999999"
        output = _run_in_tmp(
            resources=[source, known, _component(OTHER_TARGET_ID, "Component 2")],
            tiles_by_resource={
                SOURCE_ID: [
                    FakeTile(
                        {
                            RI_NODE: [
                                TARGET_ID,
                                OTHER_TARGET_ID,
                                missing_target,
                                broken_target,
                            ]
                        }
                    )
                ]
            },
            nodes=[FakeNode(RI_NODE, "Component ref", ANALYSIS_GRAPH)],
            rxr_pairs=[(SOURCE_ID, TARGET_ID)],
            lookup_errors={broken_target: RuntimeError("boom")},
        )
        self.assertIn("Total relations trouvées: 4", output)
        self.assertIn("✓ Déjà dans ResourceXResource: 1", output)
        self.assertIn("⚠️  Manquantes: 1", output)
        self.assertIn("✗ Cibles invalides: 1", output)
        self.assertIn("✗ Autres erreurs: 1", output)
        self.assertIn("Analysis→Component: 2 relations", output)
        self.assertIn("Analysis→???: 2 relations", output)

    def test_resource_instance_nodes_are_listed_per_graph_before_the_scan(self):
        output = _run_in_tmp(
            nodes=[
                FakeNode(RI_NODE, "Component ref", ANALYSIS_GRAPH),
                FakeNode(
                    CONCEPT_NODE,
                    "Samples",
                    COMPONENT_GRAPH,
                    datatype="resource-instance-list",
                ),
            ],
        )
        self.assertIn("  Analysis:", output)
        self.assertIn(f"    - Component ref ({RI_NODE})", output)
        self.assertIn("Nodes resource-instance à analyser: 2", output)

    def test_graph_with_no_resource_is_not_announced(self):
        output = _run_in_tmp(**_scenario(None))
        self.assertIn("Analysis: 1 ressources", output)
        self.assertNotIn("Sample:", output)
