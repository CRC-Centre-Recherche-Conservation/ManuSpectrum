"""Where the Biblissima write paths run relative to the DB transaction.

``transaction.atomic`` is replaced by a context manager that records when it is
open; the primitives record whether they ran inside it. No DB, no network.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_write_transaction_unit \\
        --settings="tests.test_settings" --noinput
"""

import json
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from django.test import TestCase

from manuspectrum.views.biblissima_proxy import (
    BiblissimaCreateAllView,
    BiblissimaCreateResourceView,
)

PATCH_ATOMIC = "django.db.transaction.atomic"
PATCH_RESOURCE = "arches.app.models.resource.Resource"
PATCH_FACTORY = "arches.app.datatypes.datatypes.DataTypeFactory"
PATCH_TILEMODEL = "manuspectrum.views.biblissima_proxy.TileModel"
PATCH_RI = "manuspectrum.views.biblissima_proxy.ResourceInstance"


def _fake_tile(rid):
    return SimpleNamespace(
        tileid=uuid.uuid4(),
        nodegroup_id="ng-fake",
        resourceinstance_id=rid,
        data={},
        parenttile=None,
        sortorder=0,
        _mspectrum_transaction_id=None,
    )


class WriteTransactionHarness(TestCase):
    def setUp(self):
        self.events = []
        self.in_transaction = False
        self.editlog_users = []
        self.user = SimpleNamespace(
            id=7, username="editor", first_name="", last_name="", email=""
        )

        @contextmanager
        def recording_atomic(*args, **kwargs):
            self.events.append("atomic:enter")
            self.in_transaction = True
            try:
                yield
            finally:
                self.in_transaction = False
                self.events.append("atomic:exit")

        self._start(patch(PATCH_ATOMIC, new=recording_atomic))
        self._start(patch(PATCH_FACTORY))
        self._start(patch(PATCH_TILEMODEL))

        self.mock_resource_cls = self._start(patch(PATCH_RESOURCE))
        self.mock_resource_cls.return_value.get_serialized_graph.return_value = {
            "nodes": []
        }
        self.resource = MagicMock()
        self.resource.get_serialized_graph.return_value = {"nodes": []}
        (
            self.mock_resource_cls.objects.select_related.return_value.get.return_value
        ) = self.resource

        self.mock_ri = self._start(patch(PATCH_RI))
        self.rid = uuid.uuid4()
        self.mock_ri.return_value.resourceinstanceid = self.rid
        self.mock_ri.return_value.save.side_effect = lambda *a, **k: (
            self.events.append(("resource row", self.in_transaction))
        )
        self.mock_ri.objects.filter.return_value.values_list.return_value = []

        def validate(tiles, nodes_by_id, factory):
            self.events.append(("validate", self.in_transaction))

        def run_hook(tiles, nodes_by_id, factory, method_name):
            self.events.append((method_name, self.in_transaction))

        def write_editlog(tiles, resource, user, tx_id):
            self.events.append(("editlog", self.in_transaction))
            self.editlog_users.append(user)

        self._start(
            patch.object(
                BiblissimaCreateResourceView, "_validate_tiles", side_effect=validate
            )
        )
        self.mock_run_hook = self._start(
            patch.object(
                BiblissimaCreateResourceView, "_run_hook", side_effect=run_hook
            )
        )
        self._start(
            patch.object(
                BiblissimaCreateResourceView,
                "_write_editlog",
                side_effect=write_editlog,
            )
        )
        self._start(patch.object(BiblissimaCreateResourceView, "_defer_indexing"))
        self._start(patch.object(BiblissimaCreateResourceView, "_link_to_project"))

        self.view = BiblissimaCreateResourceView()
        self.view._create_document_tiles = lambda rid, *args: (
            self.view._tile_buffer.append(_fake_tile(rid))
        )
        self.view._concept_list = lambda concept_ids: []

    def _start(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _request(self, body):
        return SimpleNamespace(body=json.dumps(body).encode("utf-8"), user=self.user)

    def _create_document(self):
        return self.view._create_resource(
            graph_id="graph-fake",
            resource_type="Document",
            transaction_id=None,
            bbma_data={"label": "Latin 40"},
            dependencies={},
            concept_mappings={},
            user=self.user,
        )

    def _fail_pre_tile_save(self):
        def run_hook(tiles, nodes_by_id, factory, method_name):
            self.events.append((method_name, self.in_transaction))
            if method_name == "pre_tile_save":
                raise requests.HTTPError("403 Client Error: Forbidden")

        self.mock_run_hook.side_effect = run_hook


class UnitaryCreateStagesBeforeTheTransactionTests(WriteTransactionHarness):
    def test_validation_and_pre_tile_save_run_before_the_transaction_opens(self):
        self._create_document()

        self.assertEqual(
            self.events[:3],
            [("validate", False), ("pre_tile_save", False), "atomic:enter"],
        )

    def test_the_resource_row_tiles_and_edit_log_are_written_inside_it(self):
        self._create_document()

        self.assertIn(("resource row", True), self.events)
        self.assertIn(("post_tile_save", True), self.events)
        self.assertIn(("editlog", True), self.events)

    def test_a_failing_manifest_fetch_opens_no_transaction_and_writes_no_row(self):
        self._fail_pre_tile_save()

        with self.assertRaises(requests.HTTPError):
            self._create_document()

        self.assertNotIn("atomic:enter", self.events)
        self.mock_ri.return_value.save.assert_not_called()

    def test_the_flush_reuses_the_graph_read_for_staging(self):
        self._create_document()

        self.resource.set_serialized_graph.assert_called_once_with({"nodes": []})


class DependencyCreateStagesBeforeTheTransactionTests(WriteTransactionHarness):
    def _create_person(self):
        return self.view.post(
            self._request(
                {"resourceType": "Person", "biblissimaData": {"label": "Jean Fouquet"}}
            )
        )

    def test_validation_and_pre_tile_save_run_before_the_transaction_opens(self):
        response = self._create_person()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.events[:3],
            [("validate", False), ("pre_tile_save", False), "atomic:enter"],
        )

    def test_a_failing_hook_opens_no_transaction_and_writes_no_row(self):
        self._fail_pre_tile_save()

        response = self._create_person()

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("atomic:enter", self.events)
        self.mock_ri.return_value.save.assert_not_called()


class CreateAllStagesBeforeTheTransactionTests(WriteTransactionHarness):
    def test_pre_tile_save_runs_before_pass_two_opens_the_transaction(self):
        self._start(
            patch.object(
                BiblissimaCreateResourceView,
                "_bulk_create_resources",
                side_effect=lambda graph_id, n, user, ids=None: list(ids),
            )
        )
        self._start(
            patch.object(BiblissimaCreateResourceView, "_batch_save_descriptors")
        )
        self._start(
            patch.object(BiblissimaCreateResourceView, "_link_to_project_batch")
        )
        (
            self.mock_resource_cls.objects.select_related.return_value.filter.side_effect
        ) = lambda **kwargs: [SimpleNamespace(pk=rid) for rid in kwargs["pk__in"]]
        view = BiblissimaCreateAllView()
        view._create_document_tiles = lambda rid, *args: view._tile_buffer.append(
            _fake_tile(rid)
        )

        response = view.post(
            self._request(
                {
                    "resourceType": "Document",
                    "items": [{"clientId": "a", "biblissimaData": {}}],
                }
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            self.events.index(("pre_tile_save", False)),
            self.events.index("atomic:enter"),
        )
        self.assertIn(("post_tile_save", True), self.events)


class DependencyCreateRecordsItsCreatorTests(WriteTransactionHarness):
    def test_the_edit_log_names_the_requesting_user(self):
        response = self.view.post(
            self._request({"resourceType": "Group", "biblissimaData": {"label": "BnF"}})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.editlog_users, [self.user])


class UnitaryCreateAttributesTheProjectLinkTests(WriteTransactionHarness):
    def test_the_project_link_receives_the_requesting_user(self):
        project_id = str(uuid.uuid4())
        self.mock_ri.objects.filter.return_value.values_list.return_value = [project_id]

        self.view._create_resource(
            graph_id="graph-fake",
            resource_type="Document",
            transaction_id=None,
            bbma_data={"label": "Latin 40"},
            dependencies={"project": project_id},
            concept_mappings={},
            user=self.user,
        )

        BiblissimaCreateResourceView._link_to_project.assert_called_once_with(
            self.rid, project_id, None, self.user
        )
