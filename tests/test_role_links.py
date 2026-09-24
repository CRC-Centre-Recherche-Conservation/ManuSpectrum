"""Links between resources as the tiles hold them, found by (model slug, node alias).

Usage:
    python manage.py test tests.test_role_links --settings="tests.test_settings"
"""

import uuid
from collections import defaultdict

from django.core.cache import cache
from django.test import TestCase

from arches.app.models.models import (
    GraphModel,
    Node,
    NodeGroup,
    ResourceInstance,
    TileModel,
)

from manuspectrum.utils.role_links import (
    graph_id_of,
    readable_links,
    role_links,
    role_node,
)

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
