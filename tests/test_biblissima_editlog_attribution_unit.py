"""Edit-log attribution of the Biblissima writes that go through ``Tile.save()``.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_editlog_attribution_unit \\
        --settings="tests.test_settings" --noinput
"""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from arches.app.models.models import EditLog
from django.contrib.auth.models import User
from django.test import TestCase

from manuspectrum.views.biblissima_proxy import (
    PERSON_GRAPH_ID,
    PROJECT_STUDIED_OBJECTS_NODE,
    BiblissimaAddAltNameView,
    BiblissimaCreateResourceView,
    BiblissimaLinkToProjectView,
)

USER = SimpleNamespace(id=7, username="editor", first_name="", last_name="", email="")


class AttributeTileSaveTests(TestCase):
    def setUp(self):
        self.view = BiblissimaCreateResourceView()
        self.user = User.objects.create_user(
            "biblissima-importer",
            email="importer@example.org",
            first_name="Ada",
            last_name="Lovelace",
        )
        self.transaction_id = uuid.uuid4()
        self.tileid = uuid.uuid4()

    def _row(self, **overrides):
        fields = {
            "transactionid": self.transaction_id,
            "tileinstanceid": str(self.tileid),
            "edittype": "tile edit",
            "userid": "",
            "user_username": "",
            "user_firstname": "",
            "user_lastname": "",
            "user_email": "",
        }
        fields.update(overrides)
        return EditLog.objects.create(**fields)

    def test_names_the_user_on_the_unattributed_row_of_that_tile_and_transaction(self):
        row = self._row()

        self.view._attribute_tile_save(self.tileid, self.transaction_id, self.user)

        row.refresh_from_db()
        self.assertEqual(row.userid, str(self.user.id))
        self.assertEqual(row.user_username, "biblissima-importer")
        self.assertEqual(row.user_firstname, "Ada")
        self.assertEqual(row.user_lastname, "Lovelace")
        self.assertEqual(row.user_email, "importer@example.org")

    def test_leaves_other_tiles_other_transactions_and_attributed_rows_alone(self):
        other_tile = self._row(tileinstanceid=str(uuid.uuid4()))
        other_transaction = self._row(transactionid=uuid.uuid4())
        already_attributed = self._row(userid="42", user_username="someone")

        self.view._attribute_tile_save(self.tileid, self.transaction_id, self.user)

        for row in (other_tile, other_transaction):
            row.refresh_from_db()
            self.assertEqual(row.userid, "")
        already_attributed.refresh_from_db()
        self.assertEqual(already_attributed.userid, "42")
        self.assertEqual(already_attributed.user_username, "someone")


class ProjectLinkAttributionTests(TestCase):
    @patch.object(BiblissimaCreateResourceView, "_attribute_tile_save")
    @patch("manuspectrum.views.biblissima_proxy.ResourceInstance")
    @patch("manuspectrum.views.biblissima_proxy.Tile")
    def test_a_first_studied_objects_tile_is_saved_under_a_transaction_and_attributed(
        self, mock_tile, mock_ri, mock_attribute
    ):
        (
            mock_ri.objects.select_for_update.return_value.filter.return_value.first.return_value
        ) = MagicMock()
        mock_tile.objects.filter.return_value.first.return_value = None
        new_tile = mock_tile.return_value

        BiblissimaCreateResourceView()._link_to_project(
            str(uuid.uuid4()), str(uuid.uuid4()), None, USER
        )

        transaction_id = new_tile.save.call_args.kwargs["transaction_id"]
        self.assertIsInstance(transaction_id, uuid.UUID)
        mock_attribute.assert_called_once_with(new_tile.tileid, transaction_id, USER)

    @patch.object(BiblissimaCreateResourceView, "_attribute_tile_save")
    @patch("manuspectrum.views.biblissima_proxy.ResourceInstance")
    @patch("manuspectrum.views.biblissima_proxy.Tile")
    def test_the_batch_link_is_attributed_under_the_batch_transaction(
        self, mock_tile, mock_ri, mock_attribute
    ):
        (
            mock_ri.objects.select_for_update.return_value.filter.return_value.first.return_value
        ) = MagicMock()
        existing = MagicMock()
        existing.data = {PROJECT_STUDIED_OBJECTS_NODE: []}
        (
            mock_tile.objects.select_for_update.return_value.filter.return_value.first.return_value
        ) = existing
        batch_tx = uuid.uuid4()

        BiblissimaCreateResourceView()._link_to_project_batch(
            [str(uuid.uuid4())], str(uuid.uuid4()), batch_tx, USER
        )

        existing.save.assert_called_once_with(index=False, transaction_id=batch_tx)
        mock_attribute.assert_called_once_with(existing.tileid, batch_tx, USER)


class EndpointAttributionTests(TestCase):
    @patch.object(BiblissimaCreateResourceView, "_defer_indexing")
    @patch.object(BiblissimaCreateResourceView, "_concept_list", return_value=[])
    @patch.object(BiblissimaCreateResourceView, "_attribute_tile_save")
    @patch("manuspectrum.views.biblissima_proxy.Tile")
    def test_a_new_alternative_name_is_saved_under_a_transaction_and_attributed(
        self, mock_tile, mock_attribute, _concept_list, _defer_indexing
    ):
        mock_tile.objects.filter.return_value = []
        new_tile = mock_tile.return_value
        request = SimpleNamespace(
            body=json.dumps(
                {
                    "resourceId": str(uuid.uuid4()),
                    "graphId": PERSON_GRAPH_ID,
                    "label": "Jehan Fouquet",
                }
            ).encode("utf-8"),
            user=USER,
        )

        response = BiblissimaAddAltNameView().post(request)

        self.assertEqual(response.status_code, 200)
        transaction_id = new_tile.save.call_args.kwargs["transaction_id"]
        self.assertIsInstance(transaction_id, uuid.UUID)
        mock_attribute.assert_called_once_with(new_tile.tileid, transaction_id, USER)

    @patch.object(BiblissimaCreateResourceView, "_defer_indexing")
    @patch.object(BiblissimaCreateResourceView, "_link_to_project")
    def test_the_link_endpoint_passes_the_requesting_user(
        self, mock_link, _defer_indexing
    ):
        request = SimpleNamespace(
            body=json.dumps(
                {"resourceId": str(uuid.uuid4()), "projectId": str(uuid.uuid4())}
            ).encode("utf-8"),
            user=USER,
        )

        response = BiblissimaLinkToProjectView().post(request)

        self.assertEqual(response.status_code, 200)
        self.assertIs(mock_link.call_args.kwargs["user"], USER)
