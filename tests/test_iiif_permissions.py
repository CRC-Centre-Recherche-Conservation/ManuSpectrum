"""Reader rules of the ``/iiif/v3|v2/annotation…`` routes, on real fixtures.

Usage:
    python manage.py test tests.test_iiif_permissions --settings=tests.test_settings
"""

import uuid
from unittest import mock

from django.test import Client

from tests.explorer_fixtures import CANVAS, MANIFEST, ExplorerCase

MANIFEST_JSON = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": MANIFEST,
    "type": "Manifest",
    "items": [{"id": CANVAS, "type": "Canvas", "width": 4000, "height": 5000}],
}
FETCH = "manuspectrum.utils.iiif_tools.CanvasIIIF.fetch_manifest"
DIMENSIONS = "manuspectrum.utils.iiif_tools.CanvasIIIF.get_image_service_dimensions"
POINT = {"type": "Point", "coordinates": [10, -20]}


class IIIFPermissionCase(ExplorerCase):
    """The ExplorerCase corpus with a zone on three analyses of the open Document."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for key in ("open", "on_document", "draft"):
            cls.tile(
                cls.analyses[key],
                "literal_location_of_analysis",
                cls.annotation_value(CANVAS, POINT),
            )

    def setUp(self):
        super().setUp()
        for target, value in ((FETCH, MANIFEST_JSON), (DIMENSIONS, (4000, 5000))):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.visitor = Client()
        self.reader = Client()
        self.reader.force_login(self.editor)

    def document_urls(self):
        document = self.documents["open"].pk
        return [
            f"/iiif/v3/annotation-collection/{document}",
            f"/iiif/v3/annotation-collection/{document}/page-1",
            f"/iiif/v2/annotation-collection/{document}/page-1",
        ]

    def single_urls(self, analysis):
        return [
            f"/iiif/v3/annotation/{analysis.pk}",
            f"/iiif/v2/annotation/{analysis.pk}",
        ]


class NodegroupFilterTests(IIIFPermissionCase):
    def test_a_restricted_file_nodegroup_never_reaches_the_public_page(self):
        file_id = self.stored_file(self.analyses["open"], "X01_f1v.csv", b"x,y\n1,2\n")
        self.restrict_nodegroup(
            self.nodes[("analysis", "measurement_point_data")].nodegroup_id,
            self.editor,
        )
        urls = [*self.document_urls(), *self.single_urls(self.analyses["open"])]

        for url in urls:
            with self.subTest(url=url, reader="visitor, first"):
                response = self.visitor.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(file_id, response.content.decode())
        for url in urls:
            with self.subTest(url=url, reader="granted"):
                response = self.reader.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(file_id, response.content.decode())
                self.assertEqual(response["Cache-Control"], "private, no-store")
        for url in urls:
            with self.subTest(url=url, reader="visitor, after the granted reader"):
                response = self.visitor.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(file_id, response.content.decode())

    def test_a_restricted_zone_nodegroup_hides_the_annotation(self):
        self.restrict_nodegroup(
            self.nodes[("analysis", "literal_location_of_analysis")].nodegroup_id,
            self.editor,
        )
        analysis = str(self.analyses["open"].pk)
        urls = [*self.document_urls(), *self.single_urls(self.analyses["open"])]

        for url in urls:
            with self.subTest(url=url, reader="visitor"):
                self.assertNotIn(analysis, self.visitor.get(url).content.decode())
        for url in urls:
            with self.subTest(url=url, reader="granted"):
                response = self.reader.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(analysis, response.content.decode())
                self.assertEqual(response["Cache-Control"], "private, no-store")


class ProjectCascadeTests(IIIFPermissionCase):
    def test_an_analysis_of_a_hidden_project_is_refused_on_every_single_route(self):
        self.hide_project(self.projects["main"])
        hidden = self.analyses["open"]
        unknown = type("Unknown", (), {"pk": uuid.uuid4()})

        for url, unknown_url in zip(
            self.single_urls(hidden), self.single_urls(unknown)
        ):
            with self.subTest(url=url):
                refused = self.visitor.get(url)
                answer = self.visitor.get(unknown_url)
                self.assertEqual(refused.status_code, 404)
                self.assertEqual(refused.content, answer.content)
                self.assertEqual(refused["Cache-Control"], "private, no-store")
        collection = self.visitor.get(self.document_urls()[0])
        self.assertEqual(collection.status_code, 200)
        self.assertNotIn(str(hidden.pk), collection.content.decode())
        self.assertIn(str(self.analyses["on_document"].pk), collection.content.decode())

    def test_a_draft_project_hides_nothing(self):
        self.make_draft(self.projects["main"])
        analysis = str(self.analyses["open"].pk)

        for url in [*self.single_urls(self.analyses["open"]), self.document_urls()[0]]:
            with self.subTest(url=url):
                response = self.visitor.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(analysis, response.content.decode())
