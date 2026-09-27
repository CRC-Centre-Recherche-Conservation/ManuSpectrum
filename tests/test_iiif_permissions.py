"""Reader rules of the ``/iiif/v3|v2/annotation…`` routes, on real fixtures.

Collections and pages answer 404 for a Document the reader may not see and
200 filtered otherwise; a single or per-zone annotation the reader may not
read answers 401 to the visitor and 403 to a signed-in reader (Planner ruling
R3); an unknown id answers 404.

Usage:
    python manage.py test tests.test_iiif_permissions --settings=tests.test_settings
"""

import uuid

from django.contrib.auth.models import Group, User
from django.test import Client

from arches.app.utils.permission_backend import assign_perm

from tests.explorer_fixtures import FEATURES, IIIFCase

PUBLIC = "public, no-cache"
PRIVATE = "private, no-store"


class IIIFPermissionCase(IIIFCase):
    """The IIIFCase corpus read by a visitor and by a Resource Editor."""

    def setUp(self):
        super().setUp()
        self.visitor = Client()
        self.reader = Client()
        self.reader.force_login(self.editor)

    def document_urls(self):
        """The pages holding the analyses of f. 1v (the collection lists no annotation)."""
        document = self.documents["open"].pk
        return [
            f"/iiif/v3/annotation-collection/{document}/page-1",
            f"/iiif/v2/annotation-collection/{document}/page-1",
        ]

    def collection_urls(self):
        document = self.documents["open"].pk
        return [
            f"/iiif/v3/annotation-collection/{document}",
            f"/iiif/v2/annotation-collection/{document}",
        ]

    def single_urls(self, analysis, feature=None):
        feature = feature or FEATURES.get(
            next((k for k, a in self.analyses.items() if a.pk == analysis.pk), ""), ""
        )
        urls = [
            f"/iiif/v3/annotation/{analysis.pk}",
            f"/iiif/v2/annotation/{analysis.pk}",
        ]
        if feature:
            urls += [
                f"/iiif/v3/annotation/{analysis.pk}/{feature}",
                f"/iiif/v2/annotation/{analysis.pk}/{feature}",
            ]
        return urls


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
                self.assertEqual(response["Cache-Control"], PRIVATE)
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

        for url in self.document_urls():
            with self.subTest(url=url, reader="visitor"):
                self.assertNotIn(analysis, self.visitor.get(url).content.decode())
        for url in self.single_urls(self.analyses["open"]):
            with self.subTest(url=url, reader="visitor"):
                self.assertEqual(self.visitor.get(url).status_code, 404)
        for url in [*self.document_urls(), *self.single_urls(self.analyses["open"])]:
            with self.subTest(url=url, reader="granted"):
                response = self.reader.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertIn(analysis, response.content.decode())
                self.assertEqual(response["Cache-Control"], PRIVATE)


class ProjectCascadeTests(IIIFPermissionCase):
    def test_an_analysis_of_a_hidden_project_is_refused_on_every_single_route(self):
        self.hide_project(self.projects["main"])
        hidden = self.analyses["open"]

        for url in self.single_urls(hidden):
            with self.subTest(url=url):
                refused = self.visitor.get(url)
                self.assertEqual(refused.status_code, 401)
                self.assertEqual(refused["Cache-Control"], PRIVATE)
                body = refused.json()
                self.assertEqual(body["type"], "Annotation")
                self.assertTrue(body["id"].endswith(url))
                self.assertNotIn("X01", refused.content.decode())
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


class MatrixTests(IIIFPermissionCase):
    """Every annotation route × visitor, granted session, ungranted session, unknown id, draft."""

    def setUp(self):
        super().setUp()
        self.embargo(self.analyses["open"])
        stranger = User.objects.create_user("iiif_stranger", password="pw")
        stranger.groups.add(Group.objects.get(name="Resource Editor"))
        assign_perm("no_access_to_resourceinstance", stranger, self.analyses["open"])
        self.stranger = Client()
        self.stranger.force_login(stranger)

    def assert_answer(self, response, status, cache_control=None):
        self.assertEqual(response.status_code, status)
        if cache_control:
            self.assertEqual(response["Cache-Control"], cache_control)
        vary = response.get("Vary", "").lower()
        self.assertIn("authorization", vary)
        self.assertIn("cookie", vary)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_the_visitor(self):
        for url in self.collection_urls():
            with self.subTest(url=url):
                self.assert_answer(self.visitor.get(url), 200, PUBLIC)
        for url in self.document_urls():
            with self.subTest(url=url):
                response = self.visitor.get(url)
                self.assert_answer(response, 200, PUBLIC)
                self.assertNotIn(
                    str(self.analyses["open"].pk), response.content.decode()
                )
        for url in self.single_urls(self.analyses["open"]):
            with self.subTest(url=url):
                self.assert_answer(self.visitor.get(url), 401, PRIVATE)
        for url in self.single_urls(
            self.analyses["on_document"], FEATURES["on_document_3"]
        ):
            with self.subTest(url=url):
                self.assert_answer(self.visitor.get(url), 200, PUBLIC)

    def test_a_granted_session(self):
        for url in self.collection_urls():
            with self.subTest(url=url):
                self.assert_answer(self.reader.get(url), 200, PRIVATE)
        for url in [*self.document_urls(), *self.single_urls(self.analyses["open"])]:
            with self.subTest(url=url):
                response = self.reader.get(url)
                self.assert_answer(response, 200, PRIVATE)
                self.assertIn(str(self.analyses["open"].pk), response.content.decode())

    def test_an_ungranted_session(self):
        for url in self.document_urls():
            with self.subTest(url=url):
                response = self.stranger.get(url)
                self.assert_answer(response, 200)
                self.assertNotIn(
                    str(self.analyses["open"].pk), response.content.decode()
                )
        for url in self.single_urls(self.analyses["open"]):
            with self.subTest(url=url):
                response = self.stranger.get(url)
                self.assert_answer(response, 403, PRIVATE)
                self.assertEqual(response.content, b"")

    def test_an_unknown_id(self):
        unknown = uuid.uuid4()
        for url in (
            f"/iiif/v3/annotation-collection/{unknown}",
            f"/iiif/v3/annotation-collection/{unknown}/page-1",
            f"/iiif/v2/annotation-collection/{unknown}",
            f"/iiif/v2/annotation-collection/{unknown}/page-1",
            f"/iiif/v3/annotation/{unknown}",
            f"/iiif/v2/annotation/{unknown}",
            f"/iiif/v3/annotation/{unknown}/{uuid.uuid4()}",
            f"/iiif/v2/annotation/{unknown}/{uuid.uuid4()}",
        ):
            for client in (self.visitor, self.reader):
                with self.subTest(url=url):
                    response = client.get(url)
                    self.assert_answer(response, 404, PRIVATE)
                    self.assertEqual(response.content, b"")

    def test_a_draft_analysis(self):
        for client in (self.visitor, self.reader, self.stranger):
            for url in self.single_urls(self.analyses["draft"]):
                with self.subTest(url=url):
                    self.assert_answer(client.get(url), 200)

    def test_an_embargoed_document(self):
        self.embargo(self.documents["open"])
        for url in [*self.collection_urls(), *self.document_urls()]:
            with self.subTest(url=url):
                self.assert_answer(self.visitor.get(url), 404, PRIVATE)
                self.assert_answer(self.reader.get(url), 200, PRIVATE)
