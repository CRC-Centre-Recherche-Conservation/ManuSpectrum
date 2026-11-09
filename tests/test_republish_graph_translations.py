"""republish_graph_translations and the W006 check.

The graphs are built and published through Arches, then ``i18n synclanguages``
runs as in ``entrypoint.sh init``: Arches' ``Graph.update_published_graphs()``
then writes the English strings into the ``fr`` rows of the current
publication. The command must put the French back into those same rows,
without a new publication, so that the resources stay on theirs.
"""

from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from arches.app.models import models
from arches.app.models.graph import Graph

from manuspectrum.checks import check_published_graph_translations

TEXT_WIDGET_ID = "10000000-0000-0000-0000-000000000001"

# The acceptance query of the issue: a resource pinned to another publication
# than its graph's current one opens read-only in the resource editor.
RESOURCES_OFF_THEIR_PUBLICATION = """
    SELECT count(*) FROM resource_instances r JOIN graphs g ON g.graphid = r.graphid
    WHERE r.graphpublicationid IS DISTINCT FROM g.publicationid
"""


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
    """A published branch with a child card named in en and fr.

    Its root card is published under the graph's name (``Graph.get_cards``),
    which is read from the ``graphs`` row and so stays right in every language.
    """
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


def card_names(graph_id, language):
    """{card name} of the graph's current publication in ``language``."""
    return {card["name"] for card in rows(graph_id)[language]["cards"]}


def publication_of(graph_id):
    return models.GraphModel.objects.get(pk=graph_id).publication_id


def rows(graph_id):
    """{language: serialised graph} of the graph's current publication."""
    return dict(
        models.PublishedGraph.objects.filter(
            publication_id=publication_of(graph_id)
        ).values_list("language_id", "serialized_graph")
    )


def strings(serialized):
    """(card names, card help texts, widget labels) of a serialised graph."""
    cards = serialized["cards"]
    return (
        sorted(card["name"] for card in cards),
        sorted(card["helptext"] or "" for card in cards),
        sorted(widget["label"] for widget in serialized["cards_x_nodes_x_widgets"]),
    )


def edits_of(graph_id):
    """Notes of the publication history entries of the graph's current publication."""
    return list(
        models.PublishedGraphEdit.objects.filter(
            publication_id=publication_of(graph_id)
        ).values_list("notes", flat=True)
    )


def republish(*args):
    out = StringIO()
    call_command("republish_graph_translations", *args, stdout=out)
    return out.getvalue()


@override_settings(LANGUAGES=[("en", "English"), ("fr", "French")])
class RepublishGraphTranslationsTests(TestCase):
    def setUp(self):
        self.model_id = build_resource_model()
        self.branch_id = build_branch()

    def break_translations(self):
        call_command("i18n", "synclanguages")

    def break_translations_of_the_branch_only(self):
        Graph.objects.get(pk=self.branch_id).update_published_graphs()

    def test_synclanguages_writes_english_under_fr(self):
        """The Arches behaviour the command repairs; fails if Arches fixes it."""
        self.assertEqual(
            strings(rows(self.model_id)["fr"]),
            (["Nom de l'analyse"], ["Donnez le nom."], ["Libellé"]),
        )

        self.break_translations()

        self.assertEqual(
            strings(rows(self.model_id)["fr"]),
            (["Name of Analysis"], ["Give the name."], ["Label"]),
        )
        self.assertEqual(card_names(self.branch_id, "fr"), {"Dimension (fr)", "Width"})

    def test_each_language_gets_its_strings_back_in_the_same_publication(self):
        self.break_translations()
        model_publication = publication_of(self.model_id)
        branch_publication = publication_of(self.branch_id)
        publications = models.GraphXPublishedGraph.objects.count()
        language_rows = models.PublishedGraph.objects.count()
        model_edits = edits_of(self.model_id)

        output = republish()

        self.assertEqual(
            strings(rows(self.model_id)["fr"]),
            (["Nom de l'analyse"], ["Donnez le nom."], ["Libellé"]),
        )
        self.assertEqual(
            strings(rows(self.model_id)["en"]),
            (["Name of Analysis"], ["Give the name."], ["Label"]),
        )
        self.assertEqual(
            card_names(self.branch_id, "fr"), {"Dimension (fr)", "Largeur"}
        )
        self.assertEqual(card_names(self.branch_id, "en"), {"Dimension", "Width"})
        self.assertEqual(publication_of(self.model_id), model_publication)
        self.assertEqual(publication_of(self.branch_id), branch_publication)
        self.assertEqual(models.GraphXPublishedGraph.objects.count(), publications)
        self.assertEqual(models.PublishedGraph.objects.count(), language_rows)
        self.assertIn(f"Rewrote: fr of Translated model ({self.model_id})", output)
        self.assertIn("cards, cards_x_nodes_x_widgets", output)
        self.assertNotIn("Rewrote: en of Translated model", output)
        self.assertIn("No publication was created", output)
        self.assertCountEqual(
            edits_of(self.model_id),
            model_edits
            + ["republish_graph_translations: fr rebuilt from the graph tables"],
        )

    def test_resources_stay_on_the_current_publication(self):
        publication = publication_of(self.model_id)
        resource = models.ResourceInstance.objects.create(
            graph_id=self.model_id, graph_publication_id=publication
        )
        self.break_translations()

        republish()

        resource.refresh_from_db()
        self.assertEqual(resource.graph_publication_id, publication)
        self.assertEqual(publication_of(self.model_id), publication)
        with connection.cursor() as cursor:
            cursor.execute(RESOURCES_OFF_THEIR_PUBLICATION)
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_dry_run_lists_the_differences_and_writes_nothing(self):
        self.break_translations()
        before = rows(self.model_id), rows(self.branch_id)
        edits = models.PublishedGraphEdit.objects.count()

        output = republish("--dry-run")

        self.assertEqual((rows(self.model_id), rows(self.branch_id)), before)
        self.assertEqual(models.PublishedGraphEdit.objects.count(), edits)
        self.assertIn(f"Differs: fr of Translated model ({self.model_id})", output)
        self.assertIn(f"Differs: fr of Dimension ({self.branch_id})", output)
        self.assertNotIn("Differs: en of", output)
        self.assertIn("Nothing was written", output)

    def test_a_write_locks_the_graph_rows_and_a_dry_run_does_not(self):
        self.break_translations()

        with CaptureQueriesContext(connection) as dry:
            republish("--dry-run")
        with CaptureQueriesContext(connection) as write:
            republish()

        self.assertFalse([q for q in dry if "FOR UPDATE" in q["sql"]])
        self.assertEqual(
            len(
                [
                    q
                    for q in write
                    if 'FROM "graphs"' in q["sql"] and "FOR UPDATE" in q["sql"]
                ]
            ),
            2,
        )

    def test_a_second_run_writes_nothing(self):
        self.break_translations()
        republish()
        after_first = rows(self.model_id), rows(self.branch_id)
        edits = models.PublishedGraphEdit.objects.count()

        output = republish()

        self.assertEqual((rows(self.model_id), rows(self.branch_id)), after_first)
        self.assertEqual(models.PublishedGraphEdit.objects.count(), edits)
        self.assertNotIn("Rewrote:", output)
        self.assertIn("0 publication row(s) rewritten", output)

    def test_a_publication_made_by_publish_is_already_up_to_date(self):
        """Graph.publish() and the command serialise alike: nothing is rewritten for nothing."""
        output = republish("--dry-run")

        self.assertNotIn("Differs:", output)
        self.assertIn("0 publication row(s) differ", output)

    def test_a_missing_language_row_is_added_to_the_same_publication(self):
        publication = publication_of(self.model_id)
        models.PublishedGraph.objects.filter(
            publication_id=publication, language_id="fr"
        ).delete()

        output = republish()

        self.assertEqual(publication_of(self.model_id), publication)
        self.assertEqual(
            strings(rows(self.model_id)["fr"]),
            (["Nom de l'analyse"], ["Donnez le nom."], ["Libellé"]),
        )
        self.assertIn(
            f"Rewrote: fr of Translated model ({self.model_id}): no row", output
        )

    def test_a_graph_with_unpublished_changes_is_left_alone(self):
        self.break_translations()
        models.GraphModel.objects.filter(pk=self.model_id).update(
            has_unpublished_changes=True
        )
        before = rows(self.model_id)

        output = republish()

        self.assertEqual(rows(self.model_id), before)
        self.assertIn(
            f"Skipped Translated model ({self.model_id}): it has unpublished changes",
            output,
        )
        self.assertEqual(
            card_names(self.branch_id, "fr"), {"Dimension (fr)", "Largeur"}
        )

    def test_a_publication_without_any_language_row_is_reported(self):
        """Loading such a graph raises in Arches; the command names it and goes on."""
        models.PublishedGraph.objects.filter(
            publication_id=publication_of(self.model_id)
        ).delete()
        self.break_translations_of_the_branch_only()

        output = republish()

        self.assertIn(
            f"Skipped Translated model ({self.model_id}): its publication", output
        )
        self.assertIn("i18n synclanguages", output)
        self.assertEqual(
            card_names(self.branch_id, "fr"), {"Dimension (fr)", "Largeur"}
        )

    def test_drafts_are_not_republished(self):
        Graph.objects.get(pk=self.model_id).create_draft_graph()
        draft = models.GraphModel.objects.get(source_identifier_id=self.model_id)
        self.break_translations()

        output = republish()

        self.assertNotIn(str(draft.graphid), output)
        self.assertEqual(strings(rows(self.model_id)["fr"])[0], ["Nom de l'analyse"])


@override_settings(LANGUAGES=[("en", "English"), ("fr", "French")])
class PublishedGraphTranslationsCheckTests(TestCase):
    def setUp(self):
        self.model_id = build_resource_model()
        self.branch_id = build_branch()

    def test_fresh_publications_are_silent(self):
        self.assertEqual(check_published_graph_translations(None, ["default"]), [])

    def test_english_under_fr_is_reported_until_republished(self):
        call_command("i18n", "synclanguages")

        messages = check_published_graph_translations(None, ["default"])

        self.assertEqual([m.id for m in messages], ["manuspectrum.W006"])
        self.assertIn("'fr' publication", messages[0].msg)
        self.assertIn("Translated model", messages[0].msg)
        self.assertIn("Dimension", messages[0].msg)
        self.assertIn("republish_graph_translations", messages[0].msg)

        republish()

        self.assertEqual(check_published_graph_translations(None, ["default"]), [])

    def show_english_in_fr(self, part, key):
        """Put the English text of one item into the model's fr row, nothing else."""
        row = models.PublishedGraph.objects.get(
            publication_id=publication_of(self.model_id), language_id="fr"
        )
        english = rows(self.model_id)["en"][part][0][key]
        row.serialized_graph[part][0][key] = english
        row.save()

    def test_a_help_text_alone_is_reported(self):
        self.show_english_in_fr("cards", "helptext")

        messages = check_published_graph_translations(None, ["default"])

        self.assertEqual([m.id for m in messages], ["manuspectrum.W006"])
        self.assertIn("(Translated model)", messages[0].msg)

    def test_a_widget_label_alone_is_reported(self):
        """Some package branches differ only there (Dimension, Identifier, Name)."""
        self.show_english_in_fr("cards_x_nodes_x_widgets", "label")

        messages = check_published_graph_translations(None, ["default"])

        self.assertEqual([m.id for m in messages], ["manuspectrum.W006"])
        self.assertIn("(Translated model)", messages[0].msg)

    def test_a_card_description_alone_is_reported(self):
        self.show_english_in_fr("cards", "description")

        messages = check_published_graph_translations(None, ["default"])

        self.assertEqual([m.id for m in messages], ["manuspectrum.W006"])
        self.assertIn("(Translated model)", messages[0].msg)

    def test_card_instructions_alone_are_reported(self):
        self.show_english_in_fr("cards", "instructions")

        messages = check_published_graph_translations(None, ["default"])

        self.assertEqual([m.id for m in messages], ["manuspectrum.W006"])

    def test_a_widget_placeholder_alone_is_reported(self):
        row = models.PublishedGraph.objects.get(
            publication_id=publication_of(self.model_id), language_id="fr"
        )
        row.serialized_graph["cards_x_nodes_x_widgets"][0]["config"][
            "placeholder"
        ] = "Enter a name"
        row.save()

        messages = check_published_graph_translations(None, ["default"])

        self.assertEqual([m.id for m in messages], ["manuspectrum.W006"])
        self.assertIn("(Translated model)", messages[0].msg)

    def test_the_command_repairs_description_instructions_and_placeholder(self):
        call_command("i18n", "synclanguages")
        fr = rows(self.model_id)["fr"]
        self.assertEqual(fr["cards"][0]["description"], "About the name.")
        self.assertEqual(
            fr["cards_x_nodes_x_widgets"][0]["config"]["placeholder"], "Enter a name"
        )

        republish()

        fr = rows(self.model_id)["fr"]
        self.assertEqual(fr["cards"][0]["description"], "A propos du nom.")
        self.assertEqual(fr["cards"][0]["instructions"], "Saisissez-le.")
        self.assertEqual(
            fr["cards_x_nodes_x_widgets"][0]["config"]["placeholder"], "Saisir un nom"
        )
        self.assertEqual(check_published_graph_translations(None, ["default"]), [])

    def test_a_graph_with_unpublished_changes_is_not_compared(self):
        """Its tables may hold edits its publication does not have yet."""
        call_command("i18n", "synclanguages")
        models.GraphModel.objects.filter(pk__in=[self.model_id, self.branch_id]).update(
            has_unpublished_changes=True
        )

        self.assertEqual(check_published_graph_translations(None, ["default"]), [])

    def test_only_runs_with_the_database(self):
        call_command("i18n", "synclanguages")

        self.assertEqual(check_published_graph_translations(None, None), [])

    def test_a_half_migrated_database_does_not_block_migrate(self):
        from unittest import mock

        with mock.patch(
            "manuspectrum.utils.graph_translations.translation_drift",
            side_effect=RuntimeError("relation does not exist"),
        ):
            self.assertEqual(check_published_graph_translations(None, ["default"]), [])
