"""Links between resources as the tiles hold them, found by (model slug, node alias).

Usage:
    python manage.py test tests.test_role_links --settings="tests.test_settings"
"""

import uuid
from collections import defaultdict
from unittest import mock

from django.core.cache import cache
from django.db.models.sql.compiler import SQLCompiler
from django.test import TestCase

from arches.app.models.models import (
    GraphModel,
    Node,
    NodeGroup,
    ResourceInstance,
    TileModel,
)

from manuspectrum.iiif.facts import _referencing
from manuspectrum.utils.role_links import (
    graph_id_of,
    node_links,
    readable_links,
    role_links,
    role_node,
)
from manuspectrum.views.summary_service import _resource_id

LIFECYCLE = "7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75"
ACTIVE = "f75bb034-36e3-4ab4-8167-f520cf0b4c58"


class RoleLinksTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.graph = GraphModel.objects.create(
            graphid=uuid.uuid4(),
            name="analysis",
            slug="analysis",
            isresource=True,
            is_active=True,
            resource_instance_lifecycle_id=LIFECYCLE,
        )
        target_graph = GraphModel.objects.create(
            graphid=uuid.uuid4(),
            name="component",
            slug="component",
            isresource=True,
            is_active=True,
            resource_instance_lifecycle_id=LIFECYCLE,
        )
        cls.nodegroup = NodeGroup.objects.create(
            nodegroupid=uuid.uuid4(), cardinality="n"
        )
        cls.node = Node.objects.create(
            nodeid=uuid.uuid4(),
            graph=cls.graph,
            nodegroup=cls.nodegroup,
            name="component_observed",
            alias="component_observed",
            datatype="resource-instance-list",
            istopnode=False,
        )
        make = lambda g: ResourceInstance.objects.create(
            graph=g, resource_instance_lifecycle_state_id=ACTIVE
        )
        cls.analysis, cls.first, cls.second = (
            make(cls.graph),
            make(target_graph),
            make(target_graph),
        )
        TileModel.objects.create(
            resourceinstance=cls.analysis,
            nodegroup=cls.nodegroup,
            data={
                str(cls.node.nodeid): [
                    {"resourceId": str(cls.first.pk), "ontologyProperty": ""},
                    {"resourceId": str(cls.second.pk), "ontologyProperty": ""},
                ]
            },
        )

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_a_list_value_yields_one_pair_per_target(self):
        pairs = sorted(role_links("analysis", "component_observed"))

        self.assertEqual(
            pairs,
            sorted(
                [
                    (str(self.analysis.pk), str(self.first.pk)),
                    (str(self.analysis.pk), str(self.second.pk)),
                ]
            ),
        )

    def test_role_node_and_graph_id_resolve_by_slug_and_alias(self):
        self.assertEqual(
            role_node("analysis", "component_observed").nodeid, str(self.node.nodeid)
        )
        self.assertEqual(graph_id_of("analysis"), str(self.graph.graphid))

    def test_an_unresolved_role_yields_nothing_and_warns(self):
        with self.assertLogs("manuspectrum.utils.role_links", level="WARNING"):
            self.assertEqual(role_links("analysis", "no_such_alias"), [])
        self.assertIsNone(graph_id_of("no_such_model"))

    def test_readable_links_gates_by_nodegroup_readability(self):
        expected = defaultdict(
            set, {str(self.analysis.pk): {str(self.first.pk), str(self.second.pk)}}
        )

        self.assertEqual(
            readable_links("analysis", "component_observed", {str(self.nodegroup.pk)}),
            expected,
        )
        self.assertEqual(
            readable_links("analysis", "component_observed", {str(uuid.uuid4())}),
            defaultdict(set),
        )
        self.assertEqual(
            readable_links("analysis", "component_observed", None),
            expected,
        )


class PairRuleTests(TestCase):
    """The SQL of ``node_links`` against ``summary_service._resource_id`` over every value shape."""

    @classmethod
    def setUpTestData(cls):
        graph = GraphModel.objects.create(
            graphid=uuid.uuid4(),
            name="analysis",
            slug="analysis",
            isresource=True,
            is_active=True,
            resource_instance_lifecycle_id=LIFECYCLE,
        )
        cls.nodegroup = NodeGroup.objects.create(
            nodegroupid=uuid.uuid4(), cardinality="n"
        )
        cls.node = Node.objects.create(
            nodeid=uuid.uuid4(),
            graph=graph,
            nodegroup=cls.nodegroup,
            name="component_observed",
            alias="component_observed",
            datatype="resource-instance-list",
            istopnode=False,
        )
        ids = [str(uuid.uuid4()) for _ in range(7)]
        cls.values = [
            [
                {"resourceId": ids[0], "ontologyProperty": ""},
                {"resourceid": ids[1]},
                ids[2],
                {"resourceId": ""},
                {"resourceId": "", "resourceid": ids[3]},
                {"resourceId": None, "resourceid": ids[3]},
                None,
                [],
                5,
                "",
            ],
            {"resourceId": ids[4]},
            {"resourceid": ids[5]},
            ids[6],
            None,
            [],
            "",
            {},
            [{"resourceId": ids[0]}, {"resourceId": ids[0]}],
        ]
        cls.targets = ids
        cls.sources = []
        for value in [*cls.values, "missing"]:
            source = ResourceInstance.objects.create(
                graph=graph, resource_instance_lifecycle_state_id=ACTIVE
            )
            data = {} if value == "missing" else {str(cls.node.nodeid): value}
            TileModel.objects.create(
                resourceinstance=source, nodegroup=cls.nodegroup, data=data
            )
            cls.sources.append(str(source.pk))

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def expected(self, targets=None):
        pairs = []
        for source, value in zip(self.sources, self.values):
            for item in value if isinstance(value, list) else [value]:
                target = _resource_id(item)
                if target and (targets is None or target in targets):
                    pairs.append((source, target))
        return sorted(pairs)

    def test_the_sql_rule_equals_resource_id_on_every_value_shape(self):
        self.assertEqual(
            sorted(role_links("analysis", "component_observed")), self.expected()
        )

    def test_targets_keep_the_pairs_naming_one_of_them(self):
        wanted = set(self.targets[1:4] + self.targets[5:])

        self.assertEqual(sorted(node_links(self.node, wanted)), self.expected(wanted))
        self.assertEqual(node_links(self.node, set()), [])

    def test_referencing_finds_lower_case_string_and_single_object_references(self):
        found = _referencing(
            "component_observed", set(self.targets), {str(self.nodegroup.pk)}
        )

        self.assertEqual(sorted(found), self.expected(set(self.targets)))

    def test_pairs_are_one_query_through_the_orm_compiler(self):
        compiled = mock.patch.object(
            SQLCompiler,
            "execute_sql",
            autospec=True,
            side_effect=SQLCompiler.execute_sql,
        )
        with compiled as execute:
            node_links(self.node)
            node_links(self.node, self.targets)

        self.assertEqual(execute.call_count, 2)
