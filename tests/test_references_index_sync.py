"""The references index is updated in the tile transaction, never through Celery."""

import uuid
from unittest import mock

from arches.app.models.resource import Resource
from django.conf import settings
from django.test import TestCase

from manuspectrum.settings import REFERENCES_INDEX_NAME

RESOURCE = "arches.app.models.resource"


class ReferencesIndexSynchronousTests(TestCase):
    def index(self):
        resource = Resource(resourceinstanceid=uuid.uuid4(), graph_id=uuid.uuid4())
        document = {"tiles": []}
        with (
            mock.patch(f"{RESOURCE}.index_resource") as task,
            mock.patch(
                f"{RESOURCE}.task_management.check_if_celery_available",
                return_value=True,
            ),
            mock.patch.object(
                Resource, "get_serialized_graph", return_value={"nodes": []}
            ),
            mock.patch.object(
                Resource, "get_documents_to_index", return_value=(document, [])
            ),
            mock.patch.object(Resource, "get_root_ontology", return_value=None),
            mock.patch(f"{RESOURCE}.se"),
            mock.patch(
                "arches_controlled_lists.search_indexes.reference_index."
                "ReferenceIndex.index_document"
            ) as sync_index,
        ):
            resource.index()
        return task, sync_index

    def test_the_references_index_is_configured_and_not_asynchronous(self):
        entries = [
            index
            for index in settings.ELASTICSEARCH_CUSTOM_INDEXES
            if index["name"] == REFERENCES_INDEX_NAME
        ]
        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].get("should_update_asynchronously"))

    def test_saving_a_resource_queues_no_celery_task_for_the_references_index(self):
        task, sync_index = self.index()
        task.apply_async.assert_not_called()
        sync_index.assert_called_once()
