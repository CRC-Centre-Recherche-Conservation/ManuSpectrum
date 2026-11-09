"""Reference values completed from their list items (issue #290).

The reference-select widget renders the prefLabel stored in a value for the
active language, with no fallback, so a value holding only the English label
shows "Unlabeled Item" under /fr/. These tests pin:

- the rule (`manuspectrum.utils.reference_labels`): only a reference lacking a
  site language is replaced, by its list item's labels in the shape of
  `ListItem.build_tile_value()`; a complete one, or one whose item is gone, is
  left as stored;
- `repair_reference_defaults` (command and migration 0017): the widget
  defaults in `cards_x_nodes_x_widgets` and in the current publication's
  serialized graphs, in place, without a new publication and without flagging
  the graph as changed;
- `refresh_reference_labels`: the values stored in tiles, then the
  descriptors of their resources, without moving them to another publication;
- the `manuspectrum.W007` system check.
"""

import importlib
import json
import uuid
from io import StringIO
from types import SimpleNamespace
from unittest import mock

from arches.app.models import models
from arches_controlled_lists.models import List, ListItem, ListItemValue
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from manuspectrum.checks import check_reference_default_labels
from manuspectrum.utils import reference_labels
from manuspectrum.utils.reference_labels import (
    complete_value,
    incomplete_defaults,
    list_item_id,
    missing_languages,
    repair_reference_defaults,
    tile_values,
)
from tests.explorer_fixtures import ACTIVE

LIFECYCLE = "7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75"
REFERENCE_SELECT_WIDGET = "19e56148-82b8-47eb-b66e-f6243639a1a8"
# The project's primary descriptors function (manuspectrum.functions.multi_descriptor).
MULTI_DESCRIPTOR = "3969e977-9ee9-4b86-a4e4-2b7bb2b642bc"
LANGUAGES = [("en", "English"), ("fr", "French")]
# Default of `ReferenceCase.reference_widget`: the package's English-only value.
ENGLISH_ONLY = object()

migration = importlib.import_module(
    "manuspectrum.migrations.0017_reference_default_labels"
)


def label(item_id, language, value, valuetype="prefLabel", label_id=None):
    return {
        "id": label_id or str(uuid.uuid4()),
        "valuetype_id": valuetype,
        "language_id": language,
        "value": value,
        "list_item_id": str(item_id),
    }


def reference(*labels, list_id=None, uri="http://vocab.getty.edu/aat/1"):
    return {
        "uri": uri,
        "labels": list(labels),
        "list_id": str(list_id or uuid.uuid4()),
    }


class RuleTests(SimpleTestCase):
    """The rule alone, on plain values: no database."""

    ITEM = "5f400d39-3b6b-4b8a-939b-4e49787c7444"

    def english_only(self):
        return reference(label(self.ITEM, "en", "preferred terms"))

    def full(self):
        return reference(
            label(self.ITEM, "en", "preferred terms"),
            label(self.ITEM, "fr", "termes préférentiels"),
        )

    def test_a_language_without_a_preflabel_is_missing(self):
        self.assertEqual(missing_languages(self.english_only(), ["en", "fr"]), ["fr"])
        self.assertEqual(missing_languages(self.full(), ["en", "fr"]), [])

    def test_an_altlabel_or_an_empty_label_does_not_count(self):
        value = reference(
            label(self.ITEM, "en", "preferred terms"),
            label(self.ITEM, "fr", "termes", valuetype="altLabel"),
            label(self.ITEM, "de", ""),
        )
        self.assertEqual(missing_languages(value, ["en", "fr", "de"]), ["fr", "de"])

    def test_the_item_is_named_by_the_labels(self):
        self.assertEqual(list_item_id(self.english_only()), self.ITEM)
        self.assertIsNone(list_item_id({"uri": "x", "labels": []}))

    def test_an_incomplete_reference_is_replaced_by_its_item(self):
        fresh = self.full()
        complete = reference(
            label("other", "en", "PeriodO"), label("other", "fr", "PeriodO")
        )
        stored = [self.english_only(), complete]

        result = complete_value(stored, ["en", "fr"], {self.ITEM: fresh})

        self.assertTrue(result.changed)
        self.assertEqual(result.value, [fresh, complete])
        self.assertIsNot(result.value[0], fresh, "the lookup's value is copied")
        self.assertEqual(len(stored[0]["labels"]), 1, "the input is not mutated")

    def test_a_complete_value_is_returned_as_is(self):
        stored = [self.full()]
        result = complete_value(stored, ["en", "fr"], {})
        self.assertFalse(result.changed)
        self.assertIs(result.value, stored)

    def test_a_reference_whose_item_is_gone_is_left_and_reported(self):
        stored = [self.english_only()]
        result = complete_value(stored, ["en", "fr"], {})
        self.assertFalse(result.changed)
        self.assertIs(result.value, stored)
        self.assertEqual(result.unresolved, [self.ITEM])

    def test_an_item_lacking_the_language_itself_is_reported(self):
        fresh = reference(
            label(self.ITEM, "en", "preferred terms"),
            label(self.ITEM, "en", "preferred", valuetype="altLabel"),
        )
        result = complete_value([self.english_only()], ["en", "fr"], {self.ITEM: fresh})
        self.assertTrue(result.changed)
        self.assertEqual(result.still_missing, {self.ITEM: ["fr"]})

        again = complete_value(result.value, ["en", "fr"], {self.ITEM: fresh})
        self.assertFalse(again.changed, "the second pass finds the value it wrote")

    def test_a_graph_published_before_arches_7_6_keeps_its_widgets_key(self):
        # `GraphModel.get_card_x_node_x_widgets` still reads "widgets" there.
        serialized = {
            "nodes": [{"nodeid": "n1", "datatype": "reference"}],
            "widgets": [
                "not a widget",
                {"node_id": "n1", "config": None},
                {"node_id": "n1", "config": {"defaultValue": [self.english_only()]}},
            ],
        }
        report = reference_labels.DefaultsReport()
        fresh = self.full()

        changed = reference_labels._complete_serialized_graph(
            serialized, ["en", "fr"], {self.ITEM: fresh}, report
        )

        self.assertTrue(changed)
        self.assertEqual(serialized["widgets"][2]["config"]["defaultValue"], [fresh])
        self.assertFalse(
            reference_labels._complete_serialized_graph(None, ["en"], {}, report)
        )

    def test_values_that_are_not_reference_lists_are_ignored(self):
        for value in (None, "", "a string", {"en": "x"}, ["a string"]):
            result = complete_value(value, ["en", "fr"], {})
            self.assertFalse(result.changed)
            self.assertIs(result.value, value)


class ReferenceCase(TestCase):
    """A list item labelled in en and fr, and a model whose reference widget
    defaults to it with the English prefLabel only, as the package shipped."""

    def setUp(self):
        for model in (List, ListItem, ListItemValue):
            for method in ("index", "delete_index"):
                if hasattr(model, method):
                    patcher = mock.patch.object(model, method)
                    patcher.start()
                    self.addCleanup(patcher.stop)
        for code, name in LANGUAGES:
            models.Language.objects.get_or_create(
                code=code,
                defaults={"name": name, "default_direction": "ltr", "scope": "system"},
            )
        self.controlled_list = List.objects.create(id=uuid.uuid4(), name="Names")
        self.item = ListItem.objects.create(
            id=uuid.uuid4(),
            uri="http://vocab.getty.edu/aat/300404670",
            list=self.controlled_list,
            sortorder=0,
        )
        self.en = self.value(self.item, "en", "preferred terms")
        self.fr = self.value(self.item, "fr", "termes préférentiels")
        self.alt = self.value(self.item, "en", "preferred names", "altLabel")

        self.graph = models.GraphModel.objects.create(
            name="Analysis",
            slug="analysis",
            isresource=True,
            is_active=True,
            resource_instance_lifecycle_id=LIFECYCLE,
        )
        self.node, self.widget_row = self.reference_widget(self.graph)
        self.string_node, self.string_row = self.widget_row_of(
            self.graph, "string", {"defaultValue": ""}
        )

    def value(self, item, language, text, valuetype="prefLabel"):
        return ListItemValue.objects.create(
            id=uuid.uuid4(),
            list_item=item,
            valuetype_id=valuetype,
            language_id=language,
            value=text,
        )

    def english_only(self, item=None):
        item = item or self.item
        return [
            {
                "uri": item.uri,
                "labels": [
                    label(item.pk, "en", "preferred terms", label_id=str(self.en.pk))
                ],
                "list_id": str(item.list_id),
            }
        ]

    def widget_row_of(self, graph, datatype, config):
        group = models.NodeGroup.objects.create(nodegroupid=uuid.uuid4())
        node = models.Node.objects.create(
            nodeid=group.pk,
            graph=graph,
            alias=f"n{uuid.uuid4().hex[:8]}",
            name=f"Type of name ({datatype})",
            datatype=datatype,
            nodegroup=group,
            istopnode=False,
            config=(
                {"controlledList": str(self.controlled_list.pk), "multiValue": True}
                if datatype == "reference"
                else {}
            ),
        )
        card = models.CardModel.objects.create(
            graph=graph, nodegroup=group, name="Name", active=True
        )
        widget = (
            models.Widget.objects.filter(pk=REFERENCE_SELECT_WIDGET).first()
            or models.Widget.objects.first()
        )
        row = models.CardXNodeXWidget.objects.create(
            card=card,
            node=node,
            widget=widget,
            config={
                "label": "Type",
                "i18n_properties": ["placeholder"],
                "placeholder": {"en": "Select an option", "fr": "Sélectionner"},
                **config,
            },
            label={"en": "Type", "fr": "Type"},
        )
        return node, row

    def reference_widget(self, graph, default=ENGLISH_ONLY):
        return self.widget_row_of(
            graph,
            "reference",
            {
                "defaultValue": (
                    self.english_only() if default is ENGLISH_ONLY else default
                )
            },
        )

    def stored_config(self, row):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT config FROM cards_x_nodes_x_widgets WHERE id = %s", [row.pk]
            )
            # Django loads jsonb as text and decodes it in the field.
            return json.loads(cursor.fetchone()[0])

    def serialized(self, language):
        """A published graph as Arches serialises it: the nodes and the card
        widgets of the graph, the i18n config flattened to that language."""
        widgets = []
        for row, node in (
            (self.widget_row, self.node),
            (self.string_row, self.string_node),
        ):
            config = dict(self.stored_config(row))
            config["placeholder"] = config["placeholder"][language]
            widgets.append(
                {"id": str(row.pk), "node_id": str(node.pk), "config": config}
            )
        return {
            "graphid": str(self.graph.pk),
            "nodes": [
                {"nodeid": str(self.node.pk), "datatype": "reference"},
                {"nodeid": str(self.string_node.pk), "datatype": "string"},
            ],
            "cards_x_nodes_x_widgets": widgets,
        }

    def publish(self, current=True):
        publication = models.GraphXPublishedGraph.objects.create(graph=self.graph)
        for code, _name in LANGUAGES:
            models.PublishedGraph.objects.create(
                publication=publication,
                language_id=code,
                serialized_graph=self.serialized(code),
            )
        if current:
            models.GraphModel.objects.filter(pk=self.graph.pk).update(
                publication=publication
            )
        # Publishing leaves the graph clean; the repair must keep it so.
        models.GraphModel.objects.filter(pk=self.graph.pk).update(
            has_unpublished_changes=False
        )
        return publication

    def published_default(self, publication, language):
        serialized = models.PublishedGraph.objects.get(
            publication=publication, language_id=language
        ).serialized_graph
        for widget in serialized["cards_x_nodes_x_widgets"]:
            if widget["node_id"] == str(self.node.pk):
                return widget["config"]["defaultValue"]

    def assert_full_labels(self, value):
        self.assertEqual(len(value), 1)
        labels = {
            (entry["valuetype_id"], entry["language_id"]): entry["value"]
            for entry in value[0]["labels"]
        }
        self.assertEqual(
            labels,
            {
                ("prefLabel", "en"): "preferred terms",
                ("prefLabel", "fr"): "termes préférentiels",
                ("altLabel", "en"): "preferred names",
            },
        )
        self.assertEqual(value[0]["list_id"], str(self.controlled_list.pk))
        self.assertEqual(value[0]["uri"], self.item.uri)


@override_settings(LANGUAGES=LANGUAGES)
class TileValuesTests(ReferenceCase):
    def test_the_shape_is_the_one_build_tile_value_gives(self):
        built = self.item.build_tile_value()
        ours = tile_values([self.item.pk])[str(self.item.pk)]

        self.assertEqual(ours.keys(), built.keys())
        self.assertEqual(ours["uri"], built["uri"])
        self.assertEqual(ours["list_id"], built["list_id"])
        key = lambda entry: entry["id"]  # noqa: E731
        self.assertEqual(
            sorted(ours["labels"], key=key), sorted(built["labels"], key=key)
        )

    def test_preflabels_come_first_in_a_fixed_order(self):
        labels = tile_values([self.item.pk])[str(self.item.pk)]["labels"]
        self.assertEqual(
            [(entry["valuetype_id"], entry["language_id"]) for entry in labels],
            [("prefLabel", "en"), ("prefLabel", "fr"), ("altLabel", "en")],
        )

    def test_unknown_and_malformed_ids_are_absent(self):
        self.assertEqual(tile_values([uuid.uuid4(), "not-a-uuid", None]), {})
        self.assertEqual(tile_values([]), {})

    def test_the_cache_resolves_another_spelling_of_the_item_id(self):
        # A label may hold the id in upper case or without hyphens;
        # tile_values() keys its result by the canonical form.
        lookup = reference_labels.TileValueCache()
        expected = tile_values([self.item.pk])[str(self.item.pk)]

        self.assertEqual(lookup.get(str(self.item.pk).upper()), expected)
        self.assertEqual(lookup.get(self.item.pk.hex), expected)
        self.assertIsNone(lookup.get("not-a-uuid"))
        self.assertIsNone(lookup.get(None))

    def test_an_item_without_labels_is_absent(self):
        bare = ListItem.objects.create(
            id=uuid.uuid4(), uri="", list=self.controlled_list, sortorder=1
        )
        self.assertEqual(tile_values([bare.pk]), {})


@override_settings(LANGUAGES=LANGUAGES)
class RepairReferenceDefaultsTests(ReferenceCase):
    def test_the_widget_default_gets_every_label_of_its_item(self):
        report = repair_reference_defaults()

        config = self.stored_config(self.widget_row)
        self.assert_full_labels(config["defaultValue"])
        self.assertEqual(report.widget_rows, 1)

    def test_only_the_default_of_the_row_changes(self):
        repair_reference_defaults()

        config = self.stored_config(self.widget_row)
        self.assertEqual(
            config["placeholder"], {"en": "Select an option", "fr": "Sélectionner"}
        )
        self.assertEqual(config["label"], "Type")
        self.assertEqual(self.stored_config(self.string_row)["defaultValue"], "")

    def test_the_current_publication_is_repaired_in_every_language(self):
        publication = self.publish()

        report = repair_reference_defaults()

        for code, _name in LANGUAGES:
            self.assert_full_labels(self.published_default(publication, code))
        self.assertEqual(report.published_graphs, 2)
        # The placeholder stays flattened to the language of the row.
        serialized = models.PublishedGraph.objects.get(
            publication=publication, language_id="fr"
        ).serialized_graph
        configs = {
            w["node_id"]: w["config"] for w in serialized["cards_x_nodes_x_widgets"]
        }
        self.assertEqual(configs[str(self.node.pk)]["placeholder"], "Sélectionner")

    def test_no_publication_is_made_and_the_graph_stays_published(self):
        publication = self.publish()
        publications = models.GraphXPublishedGraph.objects.count()

        repair_reference_defaults()

        graph = models.GraphModel.objects.get(pk=self.graph.pk)
        self.assertEqual(graph.publication_id, publication.pk)
        self.assertFalse(graph.has_unpublished_changes)
        self.assertEqual(models.GraphXPublishedGraph.objects.count(), publications)

    def test_an_older_publication_is_history_and_left_alone(self):
        older = self.publish(current=False)
        current = self.publish()

        repair_reference_defaults()

        self.assertEqual(self.published_default(older, "fr"), self.english_only())
        self.assert_full_labels(self.published_default(current, "fr"))

    def test_a_complete_default_is_not_rewritten(self):
        repair_reference_defaults()
        self.publish()

        report = repair_reference_defaults()

        self.assertEqual((report.widget_rows, report.published_graphs), (0, 0))

    def test_a_dry_run_changes_nothing(self):
        publication = self.publish()

        report = repair_reference_defaults(dry_run=True)

        self.assertEqual((report.widget_rows, report.published_graphs), (1, 2))
        self.assertEqual(
            self.stored_config(self.widget_row)["defaultValue"], self.english_only()
        )
        self.assertEqual(self.published_default(publication, "fr"), self.english_only())

    def test_a_default_whose_item_is_gone_is_reported_and_left(self):
        gone = str(uuid.uuid4())
        default = self.english_only()
        for entry in default[0]["labels"]:
            entry["list_item_id"] = gone
        other = models.GraphModel.objects.create(
            name="Other", slug="other", isresource=False
        )
        _node, row = self.reference_widget(other, default=default)

        report = repair_reference_defaults()

        self.assertEqual(self.stored_config(row)["defaultValue"], default)
        self.assertEqual(report.unresolved, {gone})

    def test_a_reference_widget_without_a_list_default_is_skipped(self):
        # The package has reference widgets defaulting to "" or null: the
        # query must not try to measure them as arrays.
        rows = [
            self.reference_widget(self.graph, default=default)[1]
            for default in ("", None, {}, [])
        ]

        report = repair_reference_defaults()

        self.assertEqual(report.widget_rows, 1)
        self.assertEqual(
            [self.stored_config(row)["defaultValue"] for row in rows],
            ["", None, {}, []],
        )
        self.assertEqual(incomplete_defaults(), [])

    def test_the_migration_runs_the_repair(self):
        publication = self.publish()

        migration.complete_defaults(None, SimpleNamespace(connection=connection))

        self.assert_full_labels(self.stored_config(self.widget_row)["defaultValue"])
        self.assert_full_labels(self.published_default(publication, "fr"))

    def test_the_command_reports_and_repairs(self):
        self.publish()

        out = StringIO()
        call_command("repair_reference_defaults", "--dry-run", stdout=out)
        self.assertIn("widget default rows would be repaired: 1", out.getvalue())
        self.assertIn("would be repaired: 2", out.getvalue())
        self.assertIn("Dry run", out.getvalue())
        self.assertEqual(
            self.stored_config(self.widget_row)["defaultValue"], self.english_only()
        )

        call_command("repair_reference_defaults", stdout=StringIO())
        out = StringIO()
        call_command("repair_reference_defaults", stdout=out)
        self.assertIn("Nothing to do", out.getvalue())

    def test_the_command_names_an_item_lacking_a_language(self):
        self.fr.delete()

        out = StringIO()
        call_command("repair_reference_defaults", stdout=out)

        self.assertIn(
            f"[list item] {self.item.pk} has no prefLabel in fr", out.getvalue()
        )


@override_settings(LANGUAGES=LANGUAGES)
class ReferenceDefaultCheckTests(ReferenceCase):
    def test_an_incomplete_default_is_a_warning(self):
        messages = check_reference_default_labels(None, databases=["default"])

        self.assertEqual([m.id for m in messages], ["manuspectrum.W007"])
        self.assertIn("analysis / Type of name (reference) (no fr)", messages[0].msg)
        self.assertIn("repair_reference_defaults", messages[0].msg)

    def test_the_check_is_silent_once_repaired(self):
        repair_reference_defaults()
        self.assertEqual(
            check_reference_default_labels(None, databases=["default"]), []
        )

    def test_the_check_only_runs_against_the_database(self):
        self.assertEqual(check_reference_default_labels(None, databases=None), [])

    def test_a_half_migrated_database_does_not_block_migrate(self):
        with mock.patch.object(
            reference_labels,
            "incomplete_defaults",
            side_effect=RuntimeError("no table"),
        ):
            self.assertEqual(
                check_reference_default_labels(None, databases=["default"]), []
            )

    def test_the_defaults_listed_name_their_missing_languages(self):
        self.assertEqual(
            incomplete_defaults(["en", "fr"]),
            [("analysis", "Type of name (reference)", ["fr"])],
        )
        self.assertEqual(incomplete_defaults(["en"]), [])


@override_settings(LANGUAGES=LANGUAGES)
class RefreshReferenceLabelsTests(ReferenceCase):
    def setUp(self):
        super().setUp()
        self.resource = models.ResourceInstance.objects.create(
            graph=self.graph,
            resource_instance_lifecycle_state_id=ACTIVE,
            descriptors={"en": {"name": "Analysis 1"}},
        )
        index = mock.patch("arches.app.models.resource.Resource.index")
        self.index = index.start()
        self.addCleanup(index.stop)

    def tile(self, value):
        return models.TileModel.objects.create(
            resourceinstance=self.resource,
            nodegroup_id=self.node.nodegroup_id,
            data={str(self.node.pk): value},
        )

    def stored(self, tile):
        return models.TileModel.objects.get(pk=tile.pk).data[str(self.node.pk)]

    def run_command(self, *arguments):
        out = StringIO()
        call_command("refresh_reference_labels", *arguments, stdout=out)
        return out.getvalue()

    def test_a_value_saved_with_the_english_only_default_is_completed(self):
        tile = self.tile(self.english_only())

        output = self.run_command()

        self.assert_full_labels(self.stored(tile))
        self.assertIn("Completed 1 reference value(s).", output)
        self.index.assert_called_once()
        self.assertIn("Reindexed 1 resource(s).", output)

    def test_a_complete_value_is_left_as_stored(self):
        complete = [tile_values([self.item.pk])[str(self.item.pk)]]
        complete[0]["labels"].reverse()
        tile = self.tile(complete)

        output = self.run_command()

        self.assertEqual(self.stored(tile), complete)
        self.assertIn("Nothing to do", output)
        self.index.assert_not_called()

    def test_a_dry_run_changes_nothing(self):
        tile = self.tile(self.english_only())

        output = self.run_command("--dry-run")

        self.assertEqual(self.stored(tile), self.english_only())
        self.assertIn(
            "reference values to complete: 1 in 1 tile(s) of 1 resource(s)", output
        )
        self.assertIn("Dry run", output)
        self.index.assert_not_called()

    def test_it_is_idempotent(self):
        self.tile(self.english_only())

        self.run_command()
        output = self.run_command()

        self.assertIn("Nothing to do", output)
        self.index.assert_called_once()

    def test_a_value_edited_since_it_was_read_is_left_alone(self):
        tile = self.tile(self.english_only())
        edited = [tile_values([self.item.pk])[str(self.item.pk)]]
        real_execute = connection.cursor().__class__.execute

        def edit_first(cursor, sql, params=None):
            # A user saves the tile between the read and the write.
            if "jsonb_set(tiledata" in sql:
                models.TileModel.objects.filter(pk=tile.pk).update(
                    data={str(self.node.pk): edited}
                )
            return real_execute(cursor, sql, params)

        with mock.patch.object(connection.cursor().__class__, "execute", edit_first):
            output = self.run_command()

        self.assertEqual(self.stored(tile), edited)
        self.assertIn("1 value(s) changed since they were read", output)
        self.index.assert_not_called()

    def test_a_value_naming_its_item_in_upper_case_is_completed(self):
        value = self.english_only()
        value[0]["labels"][0]["list_item_id"] = str(self.item.pk).upper()
        tile = self.tile(value)

        output = self.run_command()

        self.assert_full_labels(self.stored(tile))
        self.assertNotIn("[unresolved]", output)

    def describe_by_the_reference(self):
        """Give the graph the project's descriptor function, with the name made
        of the reference node, and the resource the descriptors Arches
        computed from the English-only value: the English label in fr too."""
        models.FunctionXGraph.objects.create(
            function_id=MULTI_DESCRIPTOR,
            graph=self.graph,
            config={
                "descriptor_types": {
                    "name": {
                        "nodegroup_id": str(self.node.nodegroup_id),
                        "string_template": f"<{self.node.alias}>",
                    },
                    "description": {"nodegroup_id": "", "string_template": "Analysis"},
                    "map_popup": {"nodegroup_id": "", "string_template": "Analysis"},
                }
            },
        )
        stale = {
            "name": "preferred terms",
            "description": "Analysis",
            "map_popup": "Analysis",
        }
        models.ResourceInstance.objects.filter(pk=self.resource.pk).update(
            descriptors={"en": dict(stale), "fr": dict(stale)},
            name={"en": "preferred terms", "fr": "preferred terms"},
        )

    def test_the_descriptors_fed_by_a_reference_are_recomputed(self):
        self.describe_by_the_reference()
        self.tile(self.english_only())
        indexed = []

        def index(resource, *args, **kwargs):
            indexed.append(json.loads(json.dumps(resource.descriptors)))

        # A plain function, so it is bound and sees the resource indexed.
        with mock.patch("arches.app.models.resource.Resource.index", index):
            output = self.run_command()

        resource = models.ResourceInstance.objects.get(pk=self.resource.pk)
        self.assertEqual(resource.descriptors["fr"]["name"], "termes préférentiels")
        self.assertEqual(resource.descriptors["en"]["name"], "preferred terms")
        self.assertEqual(resource.descriptors["fr"]["description"], "Analysis")
        self.assertEqual(resource.name.raw_value["fr"], "termes préférentiels")
        self.assertEqual(resource.name.raw_value["en"], "preferred terms")
        self.assertIn("Descriptors updated for 1 resource(s).", output)
        # The search document is built from the recomputed descriptors.
        self.assertEqual(indexed[0]["fr"]["name"], "termes préférentiels")

    def test_recomputing_the_descriptors_keeps_the_publication(self):
        # ResourceInstance.save() would move the resource onto the graph's
        # current publication without migrating its data (#289).
        self.describe_by_the_reference()
        older = self.publish(current=False)
        self.publish(current=True)
        models.ResourceInstance.objects.filter(pk=self.resource.pk).update(
            graph_publication=older
        )
        self.tile(self.english_only())

        self.run_command()

        resource = models.ResourceInstance.objects.get(pk=self.resource.pk)
        self.assertEqual(resource.descriptors["fr"]["name"], "termes préférentiels")
        self.assertEqual(resource.graph_publication_id, older.pk)

    def test_descriptors_the_reference_does_not_feed_are_left_as_stored(self):
        # A template without a node keeps the stored descriptor; a descriptor
        # type the configuration lacks is not computed.
        models.FunctionXGraph.objects.create(
            function_id=MULTI_DESCRIPTOR,
            graph=self.graph,
            config={
                "descriptor_types": {
                    "name": {"nodegroup_id": "", "string_template": "Analysis"}
                }
            },
        )
        stored = {"en": {"name": "Analysis 1"}, "fr": {"name": "Analyse 1"}}
        models.ResourceInstance.objects.filter(pk=self.resource.pk).update(
            descriptors=stored, name={"en": "Analysis 1", "fr": "Analyse 1"}
        )
        self.tile(self.english_only())

        output = self.run_command()

        resource = models.ResourceInstance.objects.get(pk=self.resource.pk)
        self.assertEqual(resource.descriptors, stored)
        self.assertIn("Descriptors updated for 0 resource(s).", output)
        self.assertIn("Reindexed 1 resource(s).", output)

    def test_a_graph_without_a_descriptor_function_keeps_its_descriptors(self):
        self.tile(self.english_only())

        output = self.run_command()

        resource = models.ResourceInstance.objects.get(pk=self.resource.pk)
        self.assertEqual(resource.descriptors, {"en": {"name": "Analysis 1"}})
        self.assertIn("Descriptors updated for 0 resource(s).", output)

    def test_a_value_whose_item_is_gone_is_reported_and_left(self):
        gone = str(uuid.uuid4())
        value = self.english_only()
        for entry in value[0]["labels"]:
            entry["list_item_id"] = gone
        tile = self.tile(value)

        output = self.run_command()

        self.assertEqual(self.stored(tile), value)
        self.assertIn(f"[unresolved] list item {gone} not found", output)

    def test_a_failed_reindex_is_reported_with_the_way_out(self):
        self.tile(self.english_only())
        self.index.side_effect = RuntimeError("search is down")

        output = self.run_command()

        self.assertIn("[not reindexed]", output)
        self.assertIn("es index_resources", output)
