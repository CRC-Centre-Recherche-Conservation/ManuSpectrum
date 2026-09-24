"""The spectrum preview under a nodegroup grant, on real rows and real grants.

Like ``tests.test_spectrum_preview_deletion``, this module needs the migrated
test database, for the ``files`` row, its tile, the guardian grant and Arches'
own read checks on the nodegroup. The Analysis graph and its two nodegroups
come from the trigger tests' case; each nodegroup gets its node here, since
Arches reads a resource whose model has no node in a readable nodegroup as
unreadable. The series is patched, so no file is written to disk, and
``visible_set`` is patched open on the resource: the trigger tests' graph
carries no slug the Explorer's role lookups resolve, so resource-level
visibility is not what this module exercises — the nodegroup gate is.
``PreviewRulesTests`` below covers the real ``visible_set`` decision.

Usage:
    python manage.py test tests.test_spectrum_preview_permissions --settings="tests.test_settings"
"""

import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache, caches
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from arches.app.models.models import File, Node, NodeGroup
from arches.app.utils.permission_backend import (
    assign_perm,
    remove_perm,
    user_can_read_resource,
)

from manuspectrum.constants.xy_presets import (
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
    TECHNIQUE_NODE_ID,
    TECHNIQUE_NODEGROUP_ID,
)
from manuspectrum.utils.public_visibility import VisibleSet
from manuspectrum.views.spectrum_preview import SpectrumPreviewView
from manuspectrum.views.summary_service import readable_nodegroups
from tests.explorer_fixtures import ExplorerCase
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
        visible = mock.patch(
            "manuspectrum.views.spectrum_preview.visible_set",
            return_value=VisibleSet(analyses=frozenset({str(self.resource.pk)})),
        )
        visible.start()
        self.addCleanup(visible.stop)

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

        self.assertEqual(refused.status_code, 404)
        self.assertEqual(refused.content, b"")
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
                self.assertEqual(self.preview(user).status_code != 404, allowed)

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


class PreviewRulesTests(TestCase):
    FILE_ID = "4f0e2a55-1c5e-4a8e-9f7b-3d2c1b0a9e88"
    RESOURCE = "7d6c5b4a-3928-4716-a5b4-c3d2e1f0a9b8"

    def get(self, query=""):
        request = RequestFactory().get(f"/api/spectrum-preview/{self.FILE_ID}{query}")
        request.user = User.objects.get(username="anonymous")
        return SpectrumPreviewView.as_view()(request, file_id=self.FILE_ID)

    def patched(self, visible):
        record = ("/tmp/x.csv", self.RESOURCE, None, "ng")
        return (
            mock.patch(
                "manuspectrum.views.spectrum_preview.file_record", return_value=record
            ),
            mock.patch(
                "manuspectrum.views.spectrum_preview.readable_nodegroups",
                return_value=None,
            ),
            mock.patch(
                "manuspectrum.views.spectrum_preview.visible_set",
                return_value=VisibleSet(
                    analyses=frozenset({self.RESOURCE} if visible else set())
                ),
            ),
            mock.patch(
                "manuspectrum.views.spectrum_preview.get_or_build",
                return_value={"x": [1, 2], "y": [3, 4]},
            ),
        )

    def test_a_file_of_an_invisible_analysis_answers_the_same_404_as_an_unknown_one(
        self,
    ):
        a, b, c, d = self.patched(visible=False)
        with a, b, c, d:
            refused = self.get()
        with mock.patch(
            "manuspectrum.views.spectrum_preview.file_record", return_value=None
        ):
            unknown = self.get()

        self.assertEqual((refused.status_code, refused.content), (404, b""))
        self.assertEqual((unknown.status_code, unknown.content), (404, b""))
        self.assertEqual(refused["Cache-Control"], "private, no-store")

    def test_n_outside_the_tiers_is_a_bodyless_400(self):
        a, b, c, d = self.patched(visible=True)
        with a, b, c, d:
            response = self.get("?n=1000")

        self.assertEqual((response.status_code, response.content), (400, b""))

    def test_n_4096_is_served_and_keys_its_own_memo(self):
        a, b, c, d = self.patched(visible=True)
        with a, b, c as _, d as built:
            response = self.get("?n=4096")

        self.assertEqual(response.status_code, 200)
        self.assertIn(":4096:", built.call_args.args[0])


class RealVisibleSetPreviewTests(ExplorerCase):
    """The 404 an embargoed analysis gets, and only that, is decided by the real ``visible_set``.

    No mock of ``visible_set`` here: the fixture's analyses observe a visible
    component, so a read restriction alone is what hides one from the
    anonymous visitor (spec cascade, C11); a Draft state hides nothing.
    """

    FILE_ID = "6a1b2c3d-4e5f-4071-8a9b-0c1d2e3f4a5b"

    def get(self, analysis):
        request = RequestFactory().get(f"/api/spectrum-preview/{self.FILE_ID}")
        request.user = User.objects.get(pk=self.anonymous.pk)
        record = ("/tmp/nowhere.csv", str(analysis.pk), None, "ng")
        with (
            mock.patch(
                "manuspectrum.views.spectrum_preview.file_record",
                return_value=record,
            ),
            mock.patch(
                "manuspectrum.views.spectrum_preview.readable_nodegroups",
                return_value=None,
            ),
        ):
            return SpectrumPreviewView.as_view()(request, file_id=self.FILE_ID)

    def test_an_embargoed_analysis_is_refused_then_served_once_lifted(self):
        self.embargo(self.analyses["open"])
        refused = self.get(self.analyses["open"])

        self.assertEqual(refused.status_code, 404)

        with self.captureOnCommitCallbacks(execute=True):
            remove_perm(
                "no_access_to_resourceinstance", self.anonymous, self.analyses["open"]
            )
        served = self.get(self.analyses["open"])

        self.assertNotEqual(served.status_code, 404)

    def test_a_draft_analysis_is_served_to_the_visitor(self):
        served = self.get(self.analyses["draft"])

        self.assertNotEqual(served.status_code, 404)
