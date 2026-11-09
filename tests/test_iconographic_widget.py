"""The Biblissima concept widget on « Iconographic representation » (#289).

The Component graph is not in the test database, so `setUp` loads a reduced
copy of the package's Component model through the importer that
`packages -o load_package` uses (`import_graph`, with the package's
publication): the node « Iconographic representation » with the URL widget and
the package's config, and the node « Source » of the statements, which keeps
the URL widget. The project widget is registered the way `load_package`
registers it (`manage.py project update` → `widget register`).
"""

import copy
import json
import uuid
from io import StringIO
from pathlib import Path

from arches.app.models import models
from arches.app.models.graph import Graph
from arches.app.utils.data_management.resource_graphs.importer import import_graph
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.utils import translation

from manuspectrum.constants.biblissima import (
    COMP_ICONOGRAPHIC_NODE,
    COMP_STATEMENT_SOURCE,
    COMPONENT_GRAPH_ID,
)
from manuspectrum.management.commands.export_pkg import widget_usage

ROOT = Path(__file__).resolve().parent.parent
WIDGET_FILE = ROOT / "manuspectrum" / "widgets" / "biblissima-concept-widget.json"

URL_WIDGET = "ca0c43ff-af73-4349-bafd-53ff9f22eebd"
CONCEPT_WIDGET = "29905551-a4a5-428c-bf82-2eb0ec464bab"
PUBLICATION = "50443b2c-a212-4799-a6ff-a94fe4b267bc"
ROOT_NODE = "186801f4-7055-11ef-8753-0575b5bada34"
ICONOGRAPHIC_CARD = "2e2dbac4-e7c2-45cd-a387-f2861c53d177"
ICONOGRAPHIC_ROW = "3d45f30e-7792-4571-af07-497f48d9746b"

# The card-node-widget config of the node in the package (pkg ecc9161).
PACKAGE_CONFIG = {
    "i18n_properties": ["url_label_placeholder", "url_placeholder"],
    "label": "Concept URI",
    "link_color": "#0055a0",
    "url_label_placeholder": {"en": "Dragon", "fr": "Dragon"},
    "url_placeholder": {
        "en": "https://data.biblissima.fr/entity/Q291430",
        "fr": "https://data.biblissima.fr/entity/Q291430",
    },
}
EXPECTED_CONFIG = {
    "entityType": "descriptor",
    "placeholder": "",
    "link_color": "#0055a0",
    "label": "Concept URI",
}

# The acceptance check of the issue: no resource of a published graph on a
# publication other than the graph's current one.
ACCEPTANCE_SQL = """
    SELECT g.name->>'en', count(*)
    FROM resource_instances r JOIN graphs g ON g.graphid = r.graphid
    WHERE r.graphpublicationid IS DISTINCT FROM g.publicationid
    GROUP BY 1
"""


def url_node(node_id, name, alias, sortorder):
    return {
        "alias": alias,
        "config": {},
        "datatype": "url",
        "description": "",
        "exportable": True,
        "fieldname": None,
        "graph_id": COMPONENT_GRAPH_ID,
        "hascustomalias": False,
        "is_collector": True,
        "is_immutable": False,
        "isrequired": False,
        "issearchable": True,
        "istopnode": False,
        "name": name,
        "nodegroup_id": node_id,
        "nodeid": node_id,
        "ontologyclass": None,
        "parentproperty": None,
        "sortorder": sortorder,
        "source_identifier_id": None,
        "sourcebranchpublication_id": None,
    }


def card(card_id, node_id, name):
    return {
        "active": True,
        "cardid": card_id,
        "component_id": "f05e4d3a-53c1-11e8-b0ea-784f435179ea",
        "config": None,
        "constraints": [],
        "cssclass": None,
        "description": None,
        "graph_id": COMPONENT_GRAPH_ID,
        "helpenabled": False,
        "helptext": {"en": ""},
        "helptitle": {"en": ""},
        "instructions": {"en": ""},
        "name": name,
        "nodegroup_id": node_id,
        "sortorder": None,
        "source_identifier_id": None,
        "visible": True,
    }


def widget_row(row_id, card_id, node_id, label, config):
    return {
        "card_id": card_id,
        "config": config,
        "id": row_id,
        "label": label,
        "node_id": node_id,
        "sortorder": 0,
        "source_identifier_id": None,
        "visible": True,
        "widget_id": URL_WIDGET,
    }


def component_graph():
    """A reduced Component model, as the package carries it."""
    source_card = "b6dfa2e1-0000-4000-8000-000000000001"
    root = url_node(ROOT_NODE, "Component", "component", 0)
    root.update(datatype="semantic", istopnode=True, nodegroup_id=None, config={})
    return {
        "author": "",
        "cards": [
            card(
                ICONOGRAPHIC_CARD,
                COMP_ICONOGRAPHIC_NODE,
                {
                    "en": "Iconographic representation",
                    "fr": "Représentation iconographique",
                },
            ),
            card(source_card, COMP_STATEMENT_SOURCE, {"en": "Source", "fr": "Source"}),
        ],
        "cards_x_nodes_x_widgets": [
            widget_row(
                ICONOGRAPHIC_ROW,
                ICONOGRAPHIC_CARD,
                COMP_ICONOGRAPHIC_NODE,
                {"en": "Concept URI", "fr": "URI du concept"},
                copy.deepcopy(PACKAGE_CONFIG),
            ),
            widget_row(
                "b6dfa2eb-0000-4000-8000-000000000002",
                source_card,
                COMP_STATEMENT_SOURCE,
                {"en": "Source", "fr": "Source"},
                {"label": "Source", "link_color": "#0055a0"},
            ),
        ],
        "color": None,
        "config": {},
        "deploymentdate": None,
        "deploymentfile": None,
        "description": {"en": "Component", "fr": "Composant"},
        "edges": [
            {
                "description": None,
                "domainnode_id": ROOT_NODE,
                "edgeid": str(uuid.uuid5(uuid.NAMESPACE_URL, node_id)),
                "graph_id": COMPONENT_GRAPH_ID,
                "name": None,
                "ontologyproperty": None,
                "rangenode_id": node_id,
                "source_identifier_id": None,
            }
            for node_id in (COMP_ICONOGRAPHIC_NODE, COMP_STATEMENT_SOURCE)
        ],
        "functions_x_graphs": [],
        "graphid": COMPONENT_GRAPH_ID,
        "has_unpublished_changes": False,
        "iconclass": "fa fa-picture-o",
        "is_active": True,
        "is_copy_immutable": False,
        "isresource": True,
        "jsonldcontext": None,
        "name": {"en": "Component", "fr": "Composant"},
        "nodegroups": [
            {
                "cardinality": "n",
                "grouping_node_id": node_id,
                "legacygroupid": None,
                "nodegroupid": node_id,
                "parentnodegroup_id": None,
            }
            for node_id in (COMP_ICONOGRAPHIC_NODE, COMP_STATEMENT_SOURCE)
        ],
        "nodes": [
            root,
            url_node(
                COMP_ICONOGRAPHIC_NODE,
                "Iconographic representation",
                "iconographic_representation",
                1,
            ),
            url_node(COMP_STATEMENT_SOURCE, "Source", "statement_source", 2),
        ],
        "ontology_id": None,
        "publication": {
            "graph_id": COMPONENT_GRAPH_ID,
            "most_recent_edit_id": None,
            "notes": "Grouping cards reverted to Default Card",
            "publicationid": PUBLICATION,
            "published_time": "2026-09-15T15:34:53.593",
        },
        "relatable_resource_model_ids": [],
        "resource_2_resource_constraints": [],
        "root": root,
        "slug": "component",
        "subtitle": {"en": ""},
        "template_id": "50000000-0000-0000-0000-000000000001",
        "version": "",
    }


def published_entries(node_id=COMP_ICONOGRAPHIC_NODE):
    """{language: entry of the node} in the graph's current publication."""
    graph = models.GraphModel.objects.get(pk=COMPONENT_GRAPH_ID)
    return {
        published.language_id: next(
            entry
            for entry in published.serialized_graph["cards_x_nodes_x_widgets"]
            if entry["node_id"] == node_id
        )
        for published in models.PublishedGraph.objects.filter(
            publication_id=graph.publication_id
        )
    }


def source_row(node_id=COMP_ICONOGRAPHIC_NODE):
    return models.CardXNodeXWidget.objects.get(
        node_id=node_id, source_identifier__isnull=True
    )


def load_package_graph(graph):
    """What `packages -o load_package` does for this graph: the project's
    widgets registered (`project update`), then the graph imported with its
    publication, in every language of `settings.LANGUAGES`."""
    for code in ("en", "fr"):
        models.Language.objects.get_or_create(
            code=code,
            defaults={"name": code, "default_direction": "ltr", "scope": "system"},
        )
    models.Widget.objects.filter(pk=CONCEPT_WIDGET).delete()
    call_command("widget", "register", source=str(WIDGET_FILE))
    errors, _ = import_graph([graph], overwrite_graphs=True)
    return errors


def run_command(*args):
    stdout = StringIO()
    call_command("repair_iconographic_widget", *args, stdout=stdout)
    return stdout.getvalue()


def snapshot():
    """Everything the repair may write, to compare two states."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, widgetid, config::text, label::text "
            "FROM cards_x_nodes_x_widgets ORDER BY id"
        )
        rows = cursor.fetchall()
    return (
        rows,
        {
            (str(p.publication_id), p.language_id): p.serialized_graph
            for p in models.PublishedGraph.objects.all()
        },
        models.PublishedGraphEdit.objects.count(),
    )


class IconographicWidgetTests(TestCase):
    def setUp(self):
        self.assertEqual(load_package_graph(component_graph()), [])

    def test_the_package_load_gives_the_node_the_url_widget(self):
        """The bug, as `load_package` leaves it: the URL widget everywhere."""
        self.assertEqual(str(source_row().widget_id), URL_WIDGET)
        entries = published_entries()
        self.assertEqual(sorted(entries), ["en", "fr"])
        for entry in entries.values():
            self.assertEqual(entry["widget_id"], URL_WIDGET)

    def test_the_command_assigns_the_widget_in_the_database_and_every_language(self):
        labels = {code: entry["label"] for code, entry in published_entries().items()}
        output = run_command()

        row = source_row()
        self.assertEqual(str(row.widget_id), CONCEPT_WIDGET)
        self.assertEqual(row.config.raw_value, EXPECTED_CONFIG)
        self.assertEqual(
            row.label.raw_value, {"en": "Concept URI", "fr": "URI du concept"}
        )
        entries = published_entries()
        self.assertEqual(sorted(entries), ["en", "fr"])
        for code, entry in entries.items():
            self.assertEqual(entry["widget_id"], CONCEPT_WIDGET, code)
            self.assertEqual(entry["config"], EXPECTED_CONFIG, code)
            # The strings of a publication are per language: kept as they were.
            self.assertEqual(entry["label"], labels[code], code)
        self.assertIn("biblissima-concept-widget", output)
        self.assertIn("en, fr", output)

    def test_the_other_url_widgets_are_left_alone(self):
        config = source_row(COMP_STATEMENT_SOURCE).config.raw_value
        entries = published_entries(COMP_STATEMENT_SOURCE)
        run_command()
        row = source_row(COMP_STATEMENT_SOURCE)
        self.assertEqual(str(row.widget_id), URL_WIDGET)
        self.assertEqual(row.config.raw_value, config)
        self.assertEqual(published_entries(COMP_STATEMENT_SOURCE), entries)

    def test_no_new_publication_and_resources_keep_theirs(self):
        resource = models.ResourceInstance(graph_id=COMPONENT_GRAPH_ID)
        resource.save()
        self.assertEqual(str(resource.graph_publication_id), PUBLICATION)
        publications = models.GraphXPublishedGraph.objects.count()
        published = models.PublishedGraph.objects.count()

        run_command()

        graph = models.GraphModel.objects.get(pk=COMPONENT_GRAPH_ID)
        self.assertEqual(str(graph.publication_id), PUBLICATION)
        self.assertEqual(models.GraphXPublishedGraph.objects.count(), publications)
        self.assertEqual(models.PublishedGraph.objects.count(), published)
        resource.refresh_from_db()
        self.assertEqual(str(resource.graph_publication_id), PUBLICATION)
        with connection.cursor() as cursor:
            cursor.execute(ACCEPTANCE_SQL)
            self.assertEqual(cursor.fetchall(), [])
        # Arches records an in-place edit of a publication, as
        # Graph.update_published_graphs() does.
        edit = models.PublishedGraphEdit.objects.get()
        self.assertEqual(str(edit.publication_id), PUBLICATION)
        self.assertIn("#289", edit.notes)

    def test_the_resource_editor_reads_the_concept_widget_in_every_language(self):
        """What ResourceEditorView builds from the publication of the active language."""
        run_command()
        for code in ("en", "fr"):
            with translation.override(code):
                graph = Graph.objects.get(pk=COMPONENT_GRAPH_ID)
                serialized = graph.get_published_graph().serialized_graph
                widgets = [
                    models.CardXNodeXWidget(**entry)
                    for entry in serialized["cards_x_nodes_x_widgets"]
                ]
            widget = next(
                w for w in widgets if str(w.node_id) == COMP_ICONOGRAPHIC_NODE
            )
            self.assertEqual(str(widget.widget_id), CONCEPT_WIDGET, code)
            self.assertEqual(widget.widget.name, "biblissima-concept-widget")

    def test_a_second_run_changes_nothing(self):
        run_command()
        after_first = snapshot()
        output = run_command()
        self.assertEqual(snapshot(), after_first)
        self.assertIn("nothing to do", output)

    def test_the_draft_the_graph_designer_publishes_from_is_repaired_too(self):
        draft = Graph.objects.get(pk=COMPONENT_GRAPH_ID).create_draft_graph()
        draft_rows = models.CardXNodeXWidget.objects.filter(
            node__graph_id=draft.pk, node__source_identifier_id=COMP_ICONOGRAPHIC_NODE
        )
        self.assertEqual([str(r.widget_id) for r in draft_rows], [URL_WIDGET])

        run_command()

        self.assertEqual([str(r.widget_id) for r in draft_rows.all()], [CONCEPT_WIDGET])
        self.assertEqual(draft_rows.get().config.raw_value, EXPECTED_CONFIG)

    def test_a_publication_behind_the_database_catches_up(self):
        """The row already holds the widget (changed by hand), the publication not."""
        models.CardXNodeXWidget.objects.filter(pk=ICONOGRAPHIC_ROW).update(
            widget_id=CONCEPT_WIDGET
        )
        output = run_command()
        for code, entry in published_entries().items():
            self.assertEqual(entry["widget_id"], CONCEPT_WIDGET, code)
        self.assertIn("0 card-node-widget row(s)", output)
        self.assertIn("en, fr", output)

    def test_a_dry_run_writes_nothing(self):
        before = snapshot()
        output = run_command("--dry-run")
        self.assertEqual(snapshot(), before)
        self.assertIn("Dry run", output)

    def test_a_widget_chosen_in_the_designer_is_left_alone(self):
        other = models.Widget.objects.create(
            name="another-url-widget",
            component="views/components/widgets/another-url-widget",
            datatype="url",
            defaultconfig={},
        )
        models.CardXNodeXWidget.objects.filter(pk=ICONOGRAPHIC_ROW).update(widget=other)
        before = snapshot()
        output = run_command()
        self.assertEqual(snapshot(), before)
        self.assertIn("left unchanged", output)

    def test_an_unregistered_widget_stops_the_command_and_writes_nothing(self):
        models.Widget.objects.filter(pk=CONCEPT_WIDGET).delete()
        before = snapshot()
        with self.assertRaises(CommandError) as raised:
            run_command()
        self.assertIn("project update", str(raised.exception))
        self.assertEqual(snapshot(), before)

    def test_the_inventory_gains_the_widget_and_keeps_its_row_count(self):
        """What `check_pkg_inventory` compares: the widgets the graphs reference
        and the card-node-widget rows per graph. The URL widget stays in use
        (the node « Source »), so the package's inventory gains one widget."""
        widgets, rows = widget_usage()
        self.assertNotIn(CONCEPT_WIDGET, widgets)
        run_command()
        widgets_after, rows_after = widget_usage()
        self.assertEqual(widgets_after, sorted(widgets + [CONCEPT_WIDGET]))
        self.assertEqual(rows_after, rows)


class FixedPackageTests(TestCase):
    """`init` with a package that already assigns the widget to the node."""

    def test_the_repair_has_nothing_to_do(self):
        graph = component_graph()
        graph["cards_x_nodes_x_widgets"][0].update(
            widget_id=CONCEPT_WIDGET, config=copy.deepcopy(EXPECTED_CONFIG)
        )
        self.assertEqual(load_package_graph(graph), [])
        self.assertEqual(str(source_row().widget_id), CONCEPT_WIDGET)
        self.assertEqual(source_row().config.raw_value, EXPECTED_CONFIG)
        before = snapshot()
        output = run_command()
        self.assertEqual(snapshot(), before)
        self.assertIn("nothing to do", output)


class IconographicWidgetMigrationTests(TestCase):
    """`migrate` runs migration 0017 on an existing database and on a fresh one."""

    def migrate(self):
        """Back to 0016, then forward to 0017, as an update from 0016 does.

        The forward step targets 0017, not the leaf, so the migrations added
        after it do not run here. The backward step still unapplies every
        manuspectrum migration after 0016: each one needs a reverse (as in
        test_imaging_layers_function), or this setup fails for a reason
        unrelated to #289.
        """
        executor = MigrationExecutor(connection)
        executor.migrate([("manuspectrum", "0016_workflow_plugin_access")])
        executor.loader.build_graph()
        executor.migrate([("manuspectrum", "0017_iconographic_widget")])

    def test_an_existing_database_gets_the_widget_without_a_new_publication(self):
        self.assertEqual(load_package_graph(component_graph()), [])
        resource = models.ResourceInstance(graph_id=COMPONENT_GRAPH_ID)
        resource.save()

        self.migrate()

        self.assertEqual(str(source_row().widget_id), CONCEPT_WIDGET)
        entries = published_entries()
        self.assertEqual(sorted(entries), ["en", "fr"])
        for code, entry in entries.items():
            self.assertEqual(entry["widget_id"], CONCEPT_WIDGET, code)
        graph = models.GraphModel.objects.get(pk=COMPONENT_GRAPH_ID)
        self.assertEqual(str(graph.publication_id), PUBLICATION)
        resource.refresh_from_db()
        self.assertEqual(str(resource.graph_publication_id), PUBLICATION)
        with connection.cursor() as cursor:
            cursor.execute(ACCEPTANCE_SQL)
            self.assertEqual(cursor.fetchall(), [])

    def test_a_database_without_the_package_is_left_as_it_is(self):
        """`setup_db` runs the migrations before `load_package`."""
        self.assertFalse(models.Node.objects.filter(pk=COMP_ICONOGRAPHIC_NODE).exists())
        rows = models.CardXNodeXWidget.objects.count()
        published = models.PublishedGraph.objects.count()
        self.migrate()
        self.assertEqual(models.CardXNodeXWidget.objects.count(), rows)
        self.assertEqual(models.PublishedGraph.objects.count(), published)
        self.assertEqual(models.PublishedGraphEdit.objects.count(), 0)
        self.assertIn("not in the database", run_command())


class FrozenValuesTests(TestCase):
    """The values frozen for migration 0017 are the project's."""

    def test_they_match_the_widget_and_the_node(self):
        from manuspectrum.utils import iconographic_widget

        widget = json.loads(WIDGET_FILE.read_text("utf-8"))
        self.assertEqual(iconographic_widget.CONCEPT_WIDGET_ID, widget["widgetid"])
        self.assertEqual(
            iconographic_widget.CONCEPT_WIDGET_CONFIG, widget["defaultconfig"]
        )
        self.assertEqual(iconographic_widget.NODE_ID, COMP_ICONOGRAPHIC_NODE)
        self.assertTrue(
            models.Widget.objects.filter(
                pk=iconographic_widget.URL_WIDGET_ID, name="urldatatype"
            ).exists()
        )
