"""The Biblissima import writes under the workflow's transaction (PP-4, T8).

Arches' convention is workflow id = transaction id. The client sends it as
``transactionId``; the server validates it and uses it for the resource, its
dependencies and the project link, so a Quit reverses them.

Usage:
    python manage.py test tests.test_biblissima_workflow_transaction --settings="tests.test_settings" --noinput
"""

import json
import uuid
from types import SimpleNamespace
from unittest import mock

from arches.app.models.models import (
    EditLog,
    GraphModel,
    GraphXPublishedGraph,
    ResourceInstance,
    WorkflowHistory,
)
from arches.app.utils.transaction import reverse_edit_log_entries
from django.contrib.auth.models import User
from django.test import TestCase

from manuspectrum.accounts.workflows import (
    WorkflowTransactionError,
    workflow_transaction,
)
from manuspectrum.views.biblissima_proxy import (
    BiblissimaCreateAllView,
    BiblissimaCreateResourceView,
)
from tests.explorer_fixtures import ACTIVE
from tests.test_biblissima_createall_unit import CreateAllBase

LIFECYCLE = "7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75"


def request_of(user, body):
    return SimpleNamespace(body=json.dumps(body).encode("utf-8"), user=user)


class UserCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", "o@manuspectrum.test", "pw")
        self.other = User.objects.create_user("other", "x@manuspectrum.test", "pw")
        self.workflow = uuid.uuid4()

    def history(self, user, **kwargs):
        return WorkflowHistory.objects.create(
            workflowid=self.workflow,
            workflowname="import-biblissima-workflow",
            user=user,
            **kwargs,
        )

    def edit(self, user, workflow=None, edittype="tile create"):
        return EditLog.objects.create(
            transactionid=workflow or self.workflow,
            resourceinstanceid=str(uuid.uuid4()),
            edittype=edittype,
            userid=str(user.pk),
        )


class WorkflowTransactionRuleTests(UserCase):
    def code(self, raw, user):
        with self.assertRaises(WorkflowTransactionError) as caught:
            workflow_transaction(raw, user)
        return caught.exception.status

    def test_no_id_gives_none(self):
        self.assertIsNone(workflow_transaction(None, self.owner))
        self.assertIsNone(workflow_transaction("", self.owner))

    def test_a_malformed_id_is_a_400(self):
        for raw in ("not-a-uuid", 12, {"a": 1}, ["x"]):
            self.assertEqual(self.code(raw, self.owner), 400, raw)

    def test_an_unknown_id_is_accepted(self):
        self.assertEqual(
            workflow_transaction(str(self.workflow), self.owner), self.workflow
        )

    def test_the_owner_of_the_history_row_is_accepted(self):
        self.history(self.owner)
        self.assertEqual(
            workflow_transaction(str(self.workflow), self.owner), self.workflow
        )

    def test_another_users_history_row_is_a_403(self):
        self.history(self.other)
        self.assertEqual(self.code(str(self.workflow), self.owner), 403)

    def test_a_completed_run_is_a_403(self):
        self.history(self.owner, completed=True)
        self.assertEqual(self.code(str(self.workflow), self.owner), 403)

    def test_an_id_already_written_by_others_only_is_a_403(self):
        self.edit(self.other)
        self.assertEqual(self.code(str(self.workflow), self.owner), 403)

    def test_an_id_the_user_already_wrote_under_is_accepted(self):
        self.edit(self.owner)
        self.edit(self.other)
        self.assertEqual(
            workflow_transaction(str(self.workflow), self.owner), self.workflow
        )


class CreateResourceViewTests(UserCase):
    def post(self, user, **body):
        view = BiblissimaCreateResourceView()
        return view.post(request_of(user, {"resourceType": "Document", **body}))

    def test_the_workflow_id_reaches_the_resource_write(self):
        with mock.patch.object(
            BiblissimaCreateResourceView,
            "_create_resource",
            return_value=(uuid.uuid4(), {}),
        ) as create:
            response = self.post(self.owner, transactionId=str(self.workflow))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(create.call_args.kwargs["transaction_id"], self.workflow)

    def test_the_workflow_id_reaches_a_dependency_write(self):
        with mock.patch.object(
            BiblissimaCreateResourceView,
            "_create_dependency_resource",
        ) as create:
            create.return_value = SimpleNamespace(status_code=200)
            self.post(
                self.owner,
                resourceType="Place",
                transactionId=str(self.workflow),
                biblissimaData={"label": "Paris"},
            )
        self.assertEqual(create.call_args.args[-1], self.workflow)

    def test_the_dependency_flush_uses_the_workflow_id(self):
        graph = GraphModel.objects.create(name="place", isresource=True)
        flushed = []
        with (
            mock.patch.dict(
                "manuspectrum.views.biblissima_proxy.DEP_NAME_CONFIG",
                {
                    str(graph.pk): {
                        "ng": str(uuid.uuid4()),
                        "label": str(uuid.uuid4()),
                        "language": str(uuid.uuid4()),
                        "type": str(uuid.uuid4()),
                    }
                },
            ),
            mock.patch("arches.app.models.resource.Resource") as resource_class,
            mock.patch.object(BiblissimaCreateResourceView, "_stage_tiles"),
            mock.patch.object(
                BiblissimaCreateResourceView, "_concept_list", return_value=[]
            ),
            mock.patch.object(BiblissimaCreateResourceView, "_defer_indexing"),
            mock.patch.object(
                BiblissimaCreateResourceView,
                "_flush_tile_buffer",
                side_effect=lambda resource, user, default_transaction_id: flushed.append(
                    default_transaction_id
                ),
            ),
            mock.patch("manuspectrum.views.biblissima_proxy.ResourceInstance"),
        ):
            resource_class.return_value.get_serialized_graph.return_value = {}
            view = BiblissimaCreateResourceView()
            view._create_dependency_resource(
                str(graph.pk), "Place", {"label": "Paris"}, self.owner, self.workflow
            )
        self.assertEqual(flushed, [self.workflow])

    def test_a_malformed_id_is_a_400_and_writes_nothing(self):
        with mock.patch.object(
            BiblissimaCreateResourceView, "_create_resource"
        ) as create:
            response = self.post(self.owner, transactionId="nope")
        self.assertEqual(response.status_code, 400)
        create.assert_not_called()

    def test_a_foreign_workflow_id_is_a_403_and_writes_nothing(self):
        self.history(self.other)
        with mock.patch.object(
            BiblissimaCreateResourceView, "_create_resource"
        ) as create:
            response = self.post(self.owner, transactionId=str(self.workflow))
        self.assertEqual(response.status_code, 403)
        create.assert_not_called()

    def test_a_foreign_id_on_a_dependency_is_a_403(self):
        self.history(self.other)
        response = self.post(
            self.owner,
            resourceType="Place",
            transactionId=str(self.workflow),
            biblissimaData={"label": "Paris"},
        )
        self.assertEqual(response.status_code, 403)

    def test_without_an_id_the_write_mints_its_own(self):
        with mock.patch.object(
            BiblissimaCreateResourceView,
            "_create_resource",
            return_value=(uuid.uuid4(), {}),
        ) as create:
            self.post(self.owner)
        self.assertIsNone(create.call_args.kwargs["transaction_id"])


class CreateAllViewTests(CreateAllBase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("owner", "o@manuspectrum.test", "pw")
        self.workflow = uuid.uuid4()

    def post_as_user(self, body):
        response = self.view.post(request_of(self.user, body))
        return response, json.loads(response.content)

    def items(self, n=2, project=None):
        return [
            {
                "clientId": f"c{i}",
                "biblissimaData": {"label": f"Item {i}"},
                "dependencies": {"project": project} if project else {},
                "conceptMappings": {},
            }
            for i in range(n)
        ]

    def test_every_row_of_the_chunk_carries_the_workflow_id(self):
        with self.captureOnCommitCallbacks(execute=True):
            response, _ = self.post_as_user(
                {
                    "resourceType": "Document",
                    "transactionId": str(self.workflow),
                    "items": self.items(),
                }
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {c.args[3] for c in self.mock_write_editlog.call_args_list},
            {self.workflow},
        )
        self.assertEqual(
            {c.args[2] for c in self.mock_write_creation.call_args_list},
            {self.workflow},
        )

    def test_the_project_link_uses_the_workflow_id_and_the_chunk_is_indexed_by_ids(
        self,
    ):
        project = str(uuid.uuid4())
        self.mock_ri.objects.filter.return_value.values_list.return_value = [project]
        with self.captureOnCommitCallbacks(execute=True):
            self.post_as_user(
                {
                    "resourceType": "Document",
                    "transactionId": str(self.workflow),
                    "items": self.items(project=project),
                }
            )
        self.assertEqual(self.mock_link.call_args.args[2], self.workflow)
        self.mock_index.assert_not_called()
        indexed = {
            c.kwargs["pk"] for c in self.mock_resource_cls.objects.get.call_args_list
        }
        self.assertEqual(indexed & {project}, {project})
        self.assertEqual(len(indexed), 3)

    def test_without_an_id_the_batch_keeps_its_own_transaction(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post_as_user({"resourceType": "Document", "items": self.items()})
        (batch,) = {c.args[3] for c in self.mock_write_editlog.call_args_list}
        self.assertNotEqual(batch, self.workflow)
        self.mock_index.assert_called_once_with(
            str(batch), recalculate_descriptors=True
        )

    def test_a_malformed_id_is_a_400_and_writes_nothing(self):
        response, _ = self.post_as_user(
            {"resourceType": "Document", "transactionId": "x", "items": self.items()}
        )
        self.assertEqual(response.status_code, 400)
        self.mock_tilemodel.objects.bulk_create.assert_not_called()

    def test_a_foreign_workflow_id_is_a_403_and_writes_nothing(self):
        other = User.objects.create_user("other", "x@manuspectrum.test", "pw")
        WorkflowHistory.objects.create(
            workflowid=self.workflow,
            workflowname="import-biblissima-workflow",
            user=other,
        )
        response, _ = self.post_as_user(
            {
                "resourceType": "Document",
                "transactionId": str(self.workflow),
                "items": self.items(),
            }
        )
        self.assertEqual(response.status_code, 403)
        self.mock_tilemodel.objects.bulk_create.assert_not_called()


class ReversalTests(UserCase):
    """Arches' Quit (``reverse_edit_log_entries``) on rows the bulk path writes."""

    def setUp(self):
        super().setUp()
        self.graph = GraphModel.objects.create(
            name="document",
            isresource=True,
            is_active=True,
            slug="document",
            resource_instance_lifecycle_id=LIFECYCLE,
        )
        publication = GraphXPublishedGraph.objects.create(graph=self.graph)
        self.graph.publication = publication
        self.graph.save()
        self.publication = publication

    def resource(self, name):
        return ResourceInstance.objects.create(
            graph=self.graph,
            graph_publication=self.publication,
            resource_instance_lifecycle_state_id=ACTIVE,
            descriptors={"en": {"name": name}},
        )

    def test_a_quit_deletes_the_created_document_and_leaves_a_linked_existing_one(
        self,
    ):
        existing = self.resource("Existing Codex")
        created = self.resource("New Codex")
        view = BiblissimaCreateResourceView()
        from arches.app.models.resource import Resource

        resource = Resource.objects.get(pk=created.pk)
        with mock.patch.object(Resource, "displayname", return_value="New Codex"):
            view._write_creation_edit(resource, self.owner, self.workflow)
        EditLog.objects.create(
            transactionid=self.workflow,
            resourceinstanceid=str(created.pk),
            edittype="tile create",
            note="resource creation",
            tileinstanceid=str(uuid.uuid4()),
            userid=str(self.owner.pk),
        )
        EditLog.objects.create(
            transactionid=self.workflow,
            resourceinstanceid=str(existing.pk),
            edittype="tile edit",
            tileinstanceid=str(uuid.uuid4()),
            userid=str(self.owner.pk),
        )
        with mock.patch.object(Resource, "delete_index"):
            reverse_edit_log_entries(self.workflow)
        self.assertFalse(ResourceInstance.objects.filter(pk=created.pk).exists())
        self.assertTrue(ResourceInstance.objects.filter(pk=existing.pk).exists())

    def test_the_creation_row_names_the_user_and_the_transaction(self):
        created = self.resource("New Codex")
        from arches.app.models.resource import Resource

        resource = Resource.objects.get(pk=created.pk)
        with mock.patch.object(Resource, "displayname", return_value="New Codex"):
            BiblissimaCreateResourceView()._write_creation_edit(
                resource, self.owner, self.workflow
            )
        row = EditLog.objects.get(edittype="create")
        self.assertEqual(row.transactionid, self.workflow)
        self.assertEqual(row.userid, str(self.owner.pk))
        self.assertEqual(row.resourceinstanceid, str(created.pk))
        self.assertEqual(row.resourcedisplayname, "New Codex")
