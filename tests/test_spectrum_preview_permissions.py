"""The spectrum preview under a nodegroup grant, on real rows and real grants.

Like ``tests.test_spectrum_preview_deletion``, this module needs the migrated
test database, for the ``files`` row, its tile, the guardian grant and Arches'
own read checks. The Analysis graph and its two nodegroups come from the
trigger tests' case; each nodegroup gets its node here, since Arches reads a
resource whose model has no node in a readable nodegroup as unreadable. The
series is patched, so no file is written to disk.

Usage:
    python manage.py test tests.test_spectrum_preview_permissions --settings="tests.test_settings"
"""

import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache, caches
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from arches.app.models.models import File, Node, NodeGroup
from arches.app.utils.permission_backend import assign_perm, user_can_read_resource

from manuspectrum.constants.xy_presets import (
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
    TECHNIQUE_NODE_ID,
    TECHNIQUE_NODEGROUP_ID,
)
from manuspectrum.views.summary_service import readable_nodegroups
from tests.test_xy_config_trigger import XYTriggerTestCase

FILE_ID = "9e4a2d6b-3c71-4f58-b0e9-7a2c5d8f1b36"
SERIES = {"x": [0.0, 1.0], "y": [0.0, 1.0]}


def application_queries(captured):
    """The statements of the request itself, without django-silk's profiling."""
    return [
        query["sql"]
        for query in captured
        if "silk_" not in query["sql"] and not query["sql"].startswith("EXPLAIN")
    ]


class NodegroupGrantPreviewTests(XYTriggerTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for node_id, nodegroup_id, datatype in (
            (TECHNIQUE_NODE_ID, TECHNIQUE_NODEGROUP_ID, "reference"),
            (DATA_FILE_NODE_ID, DATA_FILE_NODEGROUP_ID, "file-list"),
        ):
            Node.objects.create(
                nodeid=node_id,
                graph=cls.graph,
                nodegroup_id=nodegroup_id,
                name=datatype,
                alias=datatype.replace("-", "_"),
                datatype=datatype,
                istopnode=False,
            )
        cls.reader = User.objects.create_user("preview_reader", password="pw")
        cls.other = User.objects.create_user("preview_other", password="pw")

    def setUp(self):
        cache.clear()
        caches["user_permission"].clear()
        self.addCleanup(cache.clear)
        self.addCleanup(caches["user_permission"].clear)
        self.resource = self.analysis()
        tile = self.write_files(self.resource, {"file_id": FILE_ID, "name": "a.csv"})
        File.objects.create(
            fileid=FILE_ID, path="uploadedfiles/preview-permissions.csv", tile=tile
        )
        series = mock.patch(
            "manuspectrum.views.spectrum_preview._series", return_value=SERIES
        )
        self.series = series.start()
        self.addCleanup(series.stop)

    def deny_files_to_reader(self):
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm(
                "no_access_to_nodegroup",
                self.reader,
                NodeGroup.objects.get(pk=DATA_FILE_NODEGROUP_ID),
            )

    def fetch(self):
        return self.client.get(reverse("api-spectrum-preview", args=[FILE_ID]))

    def preview(self, user):
        self.client.force_login(user)
        return self.fetch()

    def test_a_reader_denied_the_file_nodegroup_gets_no_preview(self):
        self.deny_files_to_reader()
        self.assertTrue(
            user_can_read_resource(self.reader, resourceid=str(self.resource.pk))
        )

        refused = self.preview(self.reader)
        served = self.preview(self.other)

        self.assertEqual(refused.status_code, 403)
        self.assertEqual(json.loads(refused.content), {"error": "forbidden"})
        self.assertEqual(served.status_code, 200)
        self.assertEqual(json.loads(served.content), SERIES)
        self.series.assert_called_once()

    def test_the_popup_and_the_endpoint_agree_on_the_nodegroup(self):
        self.deny_files_to_reader()

        for user, allowed in ((self.reader, False), (self.other, True)):
            with self.subTest(user=user.username):
                self.assertEqual(
                    DATA_FILE_NODEGROUP_ID in readable_nodegroups(user), allowed
                )
                self.assertEqual(self.preview(user).status_code != 403, allowed)

    def test_without_a_nodegroup_grant_the_warm_preview_adds_no_query(self):
        self.assertIsNone(readable_nodegroups(self.reader))
        self.assertEqual(self.preview(self.reader).status_code, 200)

        with CaptureQueriesContext(connection) as checked:
            self.assertEqual(self.fetch().status_code, 200)
        with (
            mock.patch(
                "manuspectrum.views.spectrum_preview.readable_nodegroups",
                return_value=None,
            ),
            CaptureQueriesContext(connection) as unchecked,
        ):
            self.assertEqual(self.fetch().status_code, 200)

        self.assertEqual(
            len(application_queries(checked)),
            len(application_queries(unchecked)),
            "\n".join(application_queries(checked)),
        )
