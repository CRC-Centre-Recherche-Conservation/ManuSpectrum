"""Tests for the relatable-nodes endpoint of the summary configuration form.

Two suites. ``RelatableNodesFixtureTests`` builds four throw-away resource
graphs so the payload is exercised on any database, including the empty one CI
creates. ``RelatableNodesProjectGraphTests`` runs the same contract against the
real models when they are present, and skips otherwise.

Fixture graphs are slugged ``rn_*`` so they never collide with the project
models on a database that carries the package.
"""

import uuid

from django.contrib.auth.models import Group, User
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from arches.app.models import models

from manuspectrum.views.graph_nodes import CONFIG_GROUPS, RelatableNodesView


def _graph(slug, name):
    return models.GraphModel.objects.create(
        name={"en": name, "fr": name},
        slug=slug,
        isresource=True,
    )


def _resource_instance_config(*graphs):
    return {
        "graphs": [
            {"graphid": str(graph.graphid), "name": str(graph.name)} for graph in graphs
        ],
        "searchDsl": "",
        "searchString": "",
    }


def _node(graph, nodegroup, alias, datatype, config=None):
    return models.Node.objects.create(
        name=alias,
        alias=alias,
        datatype=datatype,
        graph=graph,
        nodegroup=nodegroup,
        istopnode=False,
        config=config if config is not None else {},
    )


class RelatableNodesFixtureTests(TestCase):
    """The payload, on graphs built here rather than loaded from a package."""

    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_user("rn_editor", password="pw")
        cls.editor.groups.add(Group.objects.get_or_create(name="Graph Editor")[0])
        cls.admin = User.objects.create_user("rn_admin", password="pw")
        cls.admin.groups.add(
            Group.objects.get_or_create(name="Application Administrator")[0]
        )
        cls.outsider = User.objects.create_user("rn_outsider", password="pw")
        cls.outsider.groups.add(Group.objects.get_or_create(name="Guest")[0])

        cls.document = _graph("rn_document", "Document")
        cls.component = _graph("rn_component", "Component")
        cls.analysis = _graph("rn_analysis", "Analysis")
        cls.place = _graph("rn_place", "Place")

        nodegroups = {
            graph.slug: models.NodeGroup.objects.create(cardinality="1")
            for graph in (cls.document, cls.component, cls.analysis, cls.place)
        }

        cls.name_node = _node(
            cls.document, nodegroups["rn_document"], "label_of_name", "string"
        )
        _node(cls.document, nodegroups["rn_document"], "name_statement", "semantic")
        _node(cls.document, nodegroups["rn_document"], "type_of_document", "reference")
        _node(
            cls.document,
            nodegroups["rn_document"],
            "current_location",
            "resource-instance",
            config=_resource_instance_config(cls.place),
        )
        _node(
            cls.component,
            nodegroups["rn_component"],
            "item_visual_is_part_of_document",
            "resource-instance",
            config=_resource_instance_config(cls.document),
        )
        _node(
            cls.analysis,
            nodegroups["rn_analysis"],
            "component_observed",
            "resource-instance-list",
            config=_resource_instance_config(cls.document, cls.component),
        )
        _node(
            cls.analysis,
            nodegroups["rn_analysis"],
            "analysis_technique_used",
            "reference",
        )
        _node(cls.place, nodegroups["rn_place"], "type_of_place", "reference")

        card = models.CardModel.objects.create(
            name={"en": "Name"},
            nodegroup=nodegroups["rn_document"],
            graph=cls.document,
        )
        widget = models.Widget.objects.create(
            name="rn-test-widget", component="widgets/rn-test", datatype="string"
        )
        models.CardXNodeXWidget.objects.create(
            node=cls.name_node,
            card=card,
            widget=widget,
            label={"en": "Title", "fr": "Titre"},
            config={},
        )

    def setUp(self):
        self.client.force_login(self.editor)
        self.url = reverse("relatable-nodes", args=[self.document.graphid])

    def _payload(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_identifies_the_graph(self):
        data = self._payload()
        self.assertEqual(
            data["graph"],
            {
                "graphid": str(self.document.graphid),
                "slug": "rn_document",
                "name": "Document",
            },
        )

    def test_fields_list_the_non_semantic_nodes_of_the_graph(self):
        data = self._payload()
        aliases = [field["alias"] for field in data["fields"]]
        self.assertIn("label_of_name", aliases)
        self.assertIn("current_location", aliases)
        self.assertNotIn("name_statement", aliases)
        self.assertNotIn("item_visual_is_part_of_document", aliases)
        self.assertEqual(
            [f["datatype"] for f in data["fields"] if f["alias"] == "label_of_name"],
            ["string"],
        )

    def test_a_field_label_comes_from_the_widget_label_of_the_language(self):
        data = self._payload()
        labels = {field["alias"]: field["label"] for field in data["fields"]}
        self.assertEqual(labels["label_of_name"], "Title")
        self.assertEqual(labels["type_of_document"], "type_of_document")

    def test_outgoing_relations_carry_their_target_graphs(self):
        data = self._payload()
        outgoing = {hop["alias"]: hop for hop in data["outgoing"]}
        self.assertIn("current_location", outgoing)
        self.assertEqual(
            outgoing["current_location"]["targets"],
            [
                {
                    "graphid": str(self.place.graphid),
                    "slug": "rn_place",
                    "name": "Place",
                }
            ],
        )

    def test_incoming_relations_are_nodes_of_other_graphs_pointing_here(self):
        data = self._payload()
        incoming = {(hop["graph_slug"], hop["alias"]) for hop in data["incoming"]}
        self.assertIn(("rn_component", "item_visual_is_part_of_document"), incoming)
        self.assertIn(("rn_analysis", "component_observed"), incoming)
        self.assertNotIn(("rn_document", "current_location"), incoming)

    def test_aggregatable_covers_every_involved_graph(self):
        data = self._payload()
        self.assertEqual(
            set(data["aggregatable"]),
            {"rn_document", "rn_component", "rn_analysis", "rn_place"},
        )
        self.assertIn(
            "analysis_technique_used",
            [a["alias"] for a in data["aggregatable"]["rn_analysis"]],
        )
        self.assertIn(
            "type_of_document",
            [a["alias"] for a in data["aggregatable"]["rn_document"]],
        )
        self.assertEqual(data["aggregatable"]["rn_component"], [])

    def test_aggregatable_only_lists_reference_nodes(self):
        data = self._payload()
        self.assertEqual(
            [a["alias"] for a in data["aggregatable"]["rn_document"]],
            ["type_of_document"],
        )

    def test_the_payload_takes_four_queries(self):
        request = RequestFactory().get(self.url)
        request.user = self.editor
        with CaptureQueriesContext(connection) as queries:
            RelatableNodesView().get(request, graphid=str(self.document.graphid))
        # django-silk analyses every statement with its own EXPLAIN; those are
        # not queries the view issues.
        statements = [
            q["sql"]
            for q in queries.captured_queries
            if not q["sql"].startswith("EXPLAIN")
        ]
        self.assertLessEqual(len(statements), 4, "\n".join(statements))

    def test_an_unknown_graph_is_not_found(self):
        response = self.client.get(reverse("relatable-nodes", args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, 404)

    def test_administrators_may_read_it_too(self):
        self.client.logout()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_rejects_a_member_of_no_configuration_group(self):
        self.client.logout()
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_the_configuration_groups_never_include_an_anonymous_group(self):
        self.assertNotIn("Guest", CONFIG_GROUPS)
        self.assertNotIn("Resource Exporter", CONFIG_GROUPS)

    def test_rejects_anonymous_callers(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 403)


class RelatableNodesProjectGraphTests(TestCase):
    """The same contract against the project models, when the package is loaded."""

    def setUp(self):
        self.user = User.objects.create_user("editor", password="x")
        self.user.groups.add(Group.objects.get_or_create(name="Graph Editor")[0])
        self.client.force_login(self.user)
        self.graph = models.GraphModel.objects.filter(
            slug="document", source_identifier__isnull=True
        ).first()
        if self.graph is None:
            self.skipTest("document graph absent")

    def test_lists_fields_outgoing_incoming_and_aggregatable_nodes(self):
        resp = self.client.get(reverse("relatable-nodes", args=[self.graph.graphid]))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("label_of_name", [f["alias"] for f in data["fields"]])
        self.assertTrue(
            any(
                h["alias"] == "item_visual_is_part_of_document"
                and h["graph_slug"] == "component"
                for h in data["incoming"]
            )
        )
        self.assertIn(
            "analysis_technique_used",
            [a["alias"] for a in data["aggregatable"].get("analysis", [])],
        )

    def test_requires_a_configuration_group(self):
        self.client.logout()
        other = User.objects.create_user("reader", password="x")
        other.groups.add(Group.objects.get_or_create(name="Guest")[0])
        self.client.force_login(other)
        resp = self.client.get(reverse("relatable-nodes", args=[self.graph.graphid]))
        self.assertEqual(resp.status_code, 403)
