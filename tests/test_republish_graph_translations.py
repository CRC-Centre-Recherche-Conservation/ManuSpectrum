"""republish_graph_translations restores what ``i18n synclanguages`` overwrites."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from arches.app.models import models
from arches.app.models.graph import Graph

TEXT_WIDGET_ID = "10000000-0000-0000-0000-000000000001"


def _new_graph(name, is_resource):
    graph = Graph.objects.create_graph(name=name, is_resource=is_resource)
    # create_graph leaves a draft, and Graph.save() refuses a graph with one.
    graph.delete_draft_graph()
    return Graph.objects.get(pk=graph.pk)


def build_resource_model():
    """A published resource model with one card named, helped and labelled in en and fr."""
    graph = _new_graph("Translated model", is_resource=True)
    node = graph.append_node()["node"]
    node.datatype = "string"
    node.name = "label"
    graph.save()
    card = models.CardModel.objects.get(nodegroup_id=node.nodegroup_id)
    card.name = {"en": "Name of Analysis", "fr": "Nom de l'analyse"}
    card.helptext = {"en": "Give the name.", "fr": "Donnez le nom."}
    card.description = {"en": "About the name.", "fr": "A propos du nom."}
    card.instructions = {"en": "Type it.", "fr": "Saisissez-le."}
    card.save()
    models.CardXNodeXWidget.objects.create(
        card=card,
        node_id=node.nodeid,
        widget_id=TEXT_WIDGET_ID,
        label={"en": "Label", "fr": "Libellé"},
        config={
            "placeholder": {"en": "Enter a name", "fr": "Saisir un nom"},
            "i18n_properties": ["placeholder"],
        },
        sortorder=0,
    )
    Graph.objects.get(pk=graph.pk).publish()
    return graph.pk


def build_branch():
    """A published branch with a child card named in en and fr."""
    graph = _new_graph("Translated branch", is_resource=False)
    graph.name = {"en": "Dimension", "fr": "Dimension (fr)"}
    node = graph.append_node()["node"]
    node.datatype = "string"
    node.name = "width"
    graph.save()
    # The appended node shares the root's nodegroup; a nodegroup of its own
    # makes it a collector with its own card, as the Graph Designer does.
    nodegroup = models.NodeGroup.objects.create(
        pk=node.nodeid,
        parentnodegroup_id=graph.root.nodegroup_id,
        grouping_node_id=node.nodeid,
    )
    models.Node.objects.filter(pk=node.nodeid).update(nodegroup=nodegroup)
    models.CardModel.objects.create(
        nodegroup=nodegroup, graph_id=graph.pk, name={"en": "Width", "fr": "Largeur"}
    )
    Graph.objects.get(pk=graph.pk).publish()
    return graph.pk


def rows(graph_id):
    """{language: serialised graph} of the graph's current publication."""
    return dict(
        models.PublishedGraph.objects.filter(
            publication_id=publication_of(graph_id)
        ).values_list("language_id", "serialized_graph")
    )


def publication_of(graph_id):
    return models.GraphModel.objects.get(pk=graph_id).publication_id


def fr_strings(graph_id):
    serialized = rows(graph_id)["fr"]
    return {card["name"] for card in serialized["cards"]}, {
        widget["label"] for widget in serialized["cards_x_nodes_x_widgets"]
    }


@override_settings(LANGUAGES=[("en", "English"), ("fr", "French")])
class RepublishGraphTranslationsTests(TestCase):
    def setUp(self):
        self.model_id = build_resource_model()
        self.branch_id = build_branch()

    def test_fr_rows_are_restored_in_the_same_publications(self):
        publication = publication_of(self.model_id)
        resource = models.ResourceInstance.objects.create(
            graph_id=self.model_id, graph_publication_id=publication
        )
        call_command("i18n", "synclanguages")
        self.assertEqual(fr_strings(self.model_id), ({"Name of Analysis"}, {"Label"}))
        publications = models.GraphXPublishedGraph.objects.count()
        branch_publication = publication_of(self.branch_id)

        call_command("republish_graph_translations", stdout=StringIO())

        self.assertEqual(fr_strings(self.model_id), ({"Nom de l'analyse"}, {"Libellé"}))
        self.assertEqual(fr_strings(self.branch_id)[0], {"Dimension (fr)", "Largeur"})
        self.assertEqual(publication_of(self.model_id), publication)
        self.assertEqual(publication_of(self.branch_id), branch_publication)
        self.assertEqual(models.GraphXPublishedGraph.objects.count(), publications)
        resource.refresh_from_db()
        self.assertEqual(resource.graph_publication_id, publication)

    def test_a_graph_with_unpublished_changes_is_skipped(self):
        call_command("i18n", "synclanguages")
        models.GraphModel.objects.filter(pk=self.model_id).update(
            has_unpublished_changes=True
        )
        before = rows(self.model_id)
        out = StringIO()

        call_command("republish_graph_translations", stdout=out)

        self.assertEqual(rows(self.model_id), before)
        self.assertTrue(
            models.GraphModel.objects.get(pk=self.model_id).has_unpublished_changes
        )
        self.assertIn("Skipped Translated model", out.getvalue())
