"""The normalize_frollo_uris command (issue #294).

The Frollo TAPAC items stored their bare Opentheso id ("61296") as URI, and the
report linked it relative to the report page. The command must give the item
and every tile copy the same Frollo address, and touch nothing else.

Usage:
    python manage.py test tests.test_normalize_frollo_uris --settings="tests.test_settings"
"""

import uuid
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.validators import URLValidator
from django.test import TestCase

from arches.app.models.models import (
    GraphModel,
    NodeGroup,
    ResourceInstance,
    TileModel,
)
from arches_controlled_lists.models import List, ListItem

from manuspectrum.constants.frollo import FROLLO_LIST_IDS, frollo_concept_url
from manuspectrum.management.commands.normalize_frollo_uris import Command

TAPAC, SAMPLING = FROLLO_LIST_IDS
FORS = "https://frollo.notre-dame.science/opentheso/?idc=61296&idt=th12"
AAT = "http://vocab.getty.edu/aat/300053228"
INDEX = "manuspectrum.management.commands.normalize_frollo_uris.Command.index_resources"


def run(*args):
    out, err = StringIO(), StringIO()
    call_command("normalize_frollo_uris", *args, stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


def reference(uri, list_id=TAPAC, label="FORS"):
    return {
        "uri": uri,
        "labels": [
            {
                "id": str(uuid.uuid4()),
                "value": label,
                "language_id": "en",
                "valuetype_id": "prefLabel",
                "list_item_id": str(uuid.uuid4()),
            }
        ],
        "list_id": list_id,
    }


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.tapac = List.objects.create(id=TAPAC, name="Frollo - TAPAC")
        cls.sampling = List.objects.create(id=SAMPLING, name="Frollo - Sampling")
        cls.other = List.objects.create(name="Another list")
        cls.graph = GraphModel.objects.create(
            graphid=uuid.uuid4(),
            name="Frollo",
            isresource=True,
            is_active=True,
            slug="normalize-frollo-uris-tests",
            resource_instance_lifecycle_id="7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75",
        )
        cls.group = NodeGroup.objects.create(nodegroupid=uuid.uuid4(), cardinality="n")

    def setUp(self):
        patcher = patch(INDEX)
        self.index = patcher.start()
        self.addCleanup(patcher.stop)

    def item(self, uri, vocab=None):
        vocab = vocab or self.tapac
        return ListItem.objects.create(
            list=vocab, uri=uri, sortorder=ListItem.objects.count()
        )

    def tile(self, data):
        resource = ResourceInstance.objects.create(graph=self.graph)
        return TileModel.objects.create(
            resourceinstance=resource, nodegroup_id=self.group.pk, data=data
        )

    @staticmethod
    def uri(item):
        return ListItem.objects.get(pk=item.pk).uri

    @staticmethod
    def stored(tile, field="data"):
        return getattr(TileModel.objects.get(pk=tile.pk), field)


class AddressTests(TestCase):
    def test_the_address_is_the_frollo_concept_page(self):
        self.assertEqual(frollo_concept_url("61296"), FORS)

    def test_the_address_is_a_url_where_the_bare_id_is_not(self):
        # ListItem.uri is a URLField: the stored bare id never was a valid value.
        URLValidator()(FORS)
        with self.assertRaises(ValidationError):
            URLValidator()("61296")


class ListTests(Base):
    def test_bare_ids_of_both_frollo_lists_become_frollo_addresses(self):
        fors = self.item("61296")
        sampling = self.item("61042", self.sampling)
        run()
        self.assertEqual(self.uri(fors), FORS)
        self.assertEqual(self.uri(sampling), frollo_concept_url("61042"))

    def test_absolute_uris_of_a_frollo_list_are_untouched(self):
        aat = self.item(AAT)
        done = self.item(FORS)
        run()
        self.assertEqual(self.uri(aat), AAT)
        self.assertEqual(self.uri(done), FORS)

    def test_bare_ids_of_another_list_are_untouched(self):
        item = self.item("61149", self.other)
        run()
        self.assertEqual(self.uri(item), "61149")


class TileTests(Base):
    def test_the_tile_copy_follows_the_item(self):
        self.item("61296")
        tile = self.tile({"technique": [reference("61296")], "note": "61296"})
        run()
        data = self.stored(tile)
        self.assertEqual(data["technique"][0]["uri"], FORS)
        self.assertEqual(data["technique"][0]["labels"][0]["value"], "FORS")
        self.assertEqual(data["note"], "61296")

    def test_every_reference_of_a_multivalue_node_is_rewritten(self):
        tile = self.tile(
            {"n": [reference("61296"), reference(AAT), reference("61042", SAMPLING)]}
        )
        run()
        uris = [ref["uri"] for ref in self.stored(tile)["n"]]
        self.assertEqual(uris, [FORS, AAT, frollo_concept_url("61042")])

    def test_a_list_id_in_upper_case_is_recognised(self):
        tile = self.tile({"n": [reference("61296", TAPAC.upper())]})
        run()
        self.assertEqual(self.stored(tile)["n"][0]["uri"], FORS)

    def test_references_to_another_list_are_untouched(self):
        other = str(self.other.pk)
        tile = self.tile({"n": [reference("61296", other)], "m": TAPAC})
        run()
        self.assertEqual(self.stored(tile)["n"][0]["uri"], "61296")

    def test_pending_edit_copies_are_rewritten(self):
        tile = self.tile({"n": [reference(FORS)]})
        pending = {"user-1": {"action": "update", "value": {"n": [reference("61296")]}}}
        TileModel.objects.filter(pk=tile.pk).update(provisionaledits=pending)
        run()
        stored = self.stored(tile, "provisionaledits")
        self.assertEqual(stored["user-1"]["value"]["n"][0]["uri"], FORS)
        self.assertEqual(stored["user-1"]["action"], "update")

    def test_tiles_are_written_without_save(self):
        tile = self.tile({"n": [reference("61296")]})
        with patch.object(TileModel, "save", side_effect=AssertionError("save")):
            run()
        self.assertEqual(self.stored(tile)["n"][0]["uri"], FORS)


class CommandTests(Base):
    def seed(self):
        return self.item("61296"), self.tile({"n": [reference("61296")]})

    def test_dry_run_counts_and_writes_nothing(self):
        item, tile = self.seed()
        output = run("--dry-run")
        self.assertEqual(self.uri(item), "61296")
        self.assertEqual(self.stored(tile)["n"][0]["uri"], "61296")
        self.assertIn("lists: would rewrite 1 item URI(s)", output)
        self.assertIn("tiles: would rewrite 1 reference(s) in 1 row(s)", output)
        self.index.assert_not_called()

    def test_second_run_changes_nothing(self):
        self.seed()
        first = run()
        self.index.reset_mock()
        second = run()
        self.assertIn("lists: rewrote 1 item URI(s)", first)
        self.assertIn("lists: rewrote 0 item URI(s)", second)
        self.assertIn("tiles: rewrote 0 reference(s) in 0 row(s)", second)
        self.index.assert_not_called()

    def test_the_rewritten_resources_and_their_searchable_lists_are_reindexed(self):
        _, tile = self.seed()
        self.tile({"n": [reference(FORS)]})
        List.objects.filter(pk=SAMPLING).update(searchable=True)
        with patch.object(List, "index", autospec=True) as list_index:
            output = run()
        self.index.assert_called_once_with([tile.resourceinstance_id])
        list_index.assert_not_called()
        self.assertIn("index: reindexed 1 resource(s) and 0 list(s)", output)

        self.item("61042", self.sampling)
        with patch.object(List, "index", autospec=True) as list_index:
            output = run()
        self.assertEqual(
            [str(call.args[0].pk) for call in list_index.call_args_list], [SAMPLING]
        )
        self.assertIn("index: reindexed 0 resource(s) and 1 list(s)", output)

    def test_a_reindex_failure_keeps_the_rewrite_and_names_the_follow_up(self):
        item, tile = self.seed()
        self.index.side_effect = ConnectionError("elasticsearch down")
        output = run()
        self.assertEqual(self.uri(item), FORS)
        self.assertEqual(self.stored(tile)["n"][0]["uri"], FORS)
        self.assertIn(
            "Reindexing the resources failed (ConnectionError: elasticsearch down)",
            output,
        )
        self.assertIn("finish with: python manage.py es reindex_database", output)
        self.assertNotIn("index: reindexed", output)

    def test_a_failed_list_reindex_still_reindexes_the_resources(self):
        _, tile = self.seed()
        List.objects.filter(pk=TAPAC).update(searchable=True)
        with patch.object(List, "index", side_effect=ConnectionError("down")):
            output = run()
        self.index.assert_called_once_with([tile.resourceinstance_id])
        self.assertIn("Reindexing the lists failed", output)
        self.assertNotIn("Reindexing the resources failed", output)


class IndexResourcesTests(Base):
    def setUp(self):
        # The real index_resources, with Arches' indexer stubbed out.
        patcher = patch(
            "manuspectrum.management.commands.normalize_frollo_uris."
            "index_resources_using_singleprocessing"
        )
        self.indexer = patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_given_resources_are_indexed_in_one_pass(self):
        tile = self.tile({"n": [reference("61296")]})
        self.tile({"n": [reference(FORS)]})
        Command().index_resources([tile.resourceinstance_id])
        self.indexer.assert_called_once()
        resources = self.indexer.call_args.args[0]
        self.assertEqual(
            list(resources.values_list("pk", flat=True)), [tile.resourceinstance_id]
        )

    def test_nothing_is_indexed_without_resources(self):
        Command().index_resources([])
        self.indexer.assert_not_called()
