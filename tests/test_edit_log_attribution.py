"""Edit-log attribution of tiles saved or deleted without a user.

Run:
    flock /tmp/claude-1000/ms-django.lock ~/venv-82/bin/python manage.py test \\
        tests.test_edit_log_attribution --settings=ms82_test_settings --noinput
"""

import uuid
from types import SimpleNamespace

from arches.app.models.models import CardModel, EditLog
from arches.app.models.tile import Tile

from manuspectrum.utils import edit_log
from tests.explorer_fixtures import ExplorerCase


class UserFieldsTests(ExplorerCase):
    def test_names_a_user(self):
        user = SimpleNamespace(
            id=7, username="ada", first_name="Ada", last_name="L", email="a@x.test"
        )
        self.assertEqual(
            edit_log.user_fields(user),
            {
                "userid": "7",
                "user_username": "ada",
                "user_firstname": "Ada",
                "user_lastname": "L",
                "user_email": "a@x.test",
            },
        )

    def test_none_gives_a_null_id_and_empty_names(self):
        fields = edit_log.user_fields(None)
        self.assertIsNone(fields["userid"])
        self.assertEqual(fields["user_username"], "")


class AttributeTests(ExplorerCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        node = cls.nodes[("document", "label_of_name")]
        CardModel.objects.create(
            cardid=uuid.uuid4(),
            graph=cls.graphs["document"],
            nodegroup_id=node.nodegroup_id,
            name="name",
        )

    def _tile(self, transaction_id):
        node = self.nodes[("document", "label_of_name")]
        tile = Tile(
            resourceinstance_id=str(self.documents["open"].pk),
            nodegroup_id=str(node.nodegroup_id),
            data={str(node.nodeid): self.string_value("Added")},
        )
        tile.serialized_graph = {
            "nodes": [{"nodeid": str(node.nodeid), "datatype": "string"}],
            "cards": [],
            "widgets": [],
        }
        tile.save(index=False, transaction_id=transaction_id)
        return tile

    def _rows(self, transaction_id, tile, edittype):
        return EditLog.objects.filter(
            transactionid=transaction_id,
            tileinstanceid=str(tile.tileid),
            edittype=edittype,
        )

    def test_names_the_author_on_a_user_less_create(self):
        tx = uuid.uuid4()
        tile = self._tile(tx)
        self.assertEqual({r.userid for r in self._rows(tx, tile, "tile create")}, {""})

        count = edit_log.attribute(tx, tile.tileid, self.editor, "tile create")

        rows = self._rows(tx, tile, "tile create")
        self.assertEqual(count, rows.count())
        self.assertGreaterEqual(count, 1)
        for row in rows:
            self.assertEqual(row.userid, str(self.editor.id))
            self.assertEqual(row.user_username, "explorer_editor")

    def test_leaves_another_transaction_untouched(self):
        tx, other = uuid.uuid4(), uuid.uuid4()
        tile = self._tile(tx)
        other_tile = self._tile(other)

        edit_log.attribute(tx, tile.tileid, self.editor, "tile create")

        self.assertEqual(
            {r.userid for r in self._rows(other, other_tile, "tile create")}, {""}
        )

    def test_names_the_author_on_a_user_less_delete(self):
        tx, delete_tx = uuid.uuid4(), uuid.uuid4()
        tile = self._tile(tx)
        tileid = tile.tileid
        tile.delete(index=False, transaction_id=delete_tx)
        tile.tileid = tileid
        self.assertTrue(self._rows(delete_tx, tile, "tile delete").exists())

        count = edit_log.attribute(delete_tx, tileid, self.editor, "tile delete")

        self.assertGreaterEqual(count, 1)
        self.assertEqual(
            {r.userid for r in self._rows(delete_tx, tile, "tile delete")},
            {str(self.editor.id)},
        )

    def test_only_the_asked_edit_type_changes(self):
        tx = uuid.uuid4()
        tile = self._tile(tx)

        edit_log.attribute(tx, tile.tileid, self.editor, "tile delete")

        self.assertEqual({r.userid for r in self._rows(tx, tile, "tile create")}, {""})

    def test_an_already_attributed_row_is_kept(self):
        tx = uuid.uuid4()
        tile = self._tile(tx)
        edit_log.attribute(tx, tile.tileid, self.editor, "tile create")

        count = edit_log.attribute(tx, tile.tileid, self.anonymous, "tile create")

        self.assertEqual(count, 0)

    def test_matches_a_null_user_id(self):
        tx = uuid.uuid4()
        tile = self._tile(tx)
        self._rows(tx, tile, "tile create").update(userid=None)

        count = edit_log.attribute(tx, tile.tileid, self.editor, "tile create")

        self.assertGreaterEqual(count, 1)
