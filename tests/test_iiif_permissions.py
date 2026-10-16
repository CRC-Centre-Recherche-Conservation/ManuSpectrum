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


class CharacterizationMatrixTests(IIIFPermissionCase):
    """The characterization routes × visitor, granted session, ungranted session, unknown id."""

    OWN_ZONE = "0c0c0c0c-0000-4000-8000-0000000000aa"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from tests.explorer_fixtures import CANVAS_2, POINT

        cls.zone(
            cls.characterization,
            [(cls.OWN_ZONE, CANVAS_2, POINT)],
            alias="location_of_characterization",
        )

    def setUp(self):
        super().setUp()
        stranger = User.objects.create_user("iiif_ch_stranger", password="pw")
        stranger.groups.add(Group.objects.get(name="Resource Editor"))
        assign_perm("no_access_to_resourceinstance", stranger, self.characterization)
        self.stranger = Client()
        self.stranger.force_login(stranger)
        document = self.documents["open"].pk
        self.collections = [
            f"/iiif/v3/characterization-collection/{document}",
            f"/iiif/v2/characterization-collection/{document}",
        ]
        self.pages = [f"{url}/page-2" for url in self.collections]
        self.singles = [
            f"/iiif/v{v}/annotation/{self.characterization.pk}{suffix}"
            for v in (3, 2)
            for suffix in ("", f"/{self.OWN_ZONE}")
        ]

    def assert_answer(self, response, status, cache_control):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response["Cache-Control"], cache_control)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_the_visitor_reads_the_public_layer(self):
        for url in [*self.collections, *self.pages, *self.singles]:
            with self.subTest(url=url):
                response = self.visitor.get(url)
                self.assert_answer(response, 200, PUBLIC)
        for url in self.pages:
            with self.subTest(url=url):
                self.assertIn(
                    str(self.characterization.pk),
                    self.visitor.get(url).content.decode(),
                )

    def test_an_embargoed_characterization(self):
        self.embargo(self.characterization)
        for url in self.pages:
            with self.subTest(url=url, reader="visitor"):
                response = self.visitor.get(url)
                self.assert_answer(response, 200, PUBLIC)
                self.assertNotIn(
                    str(self.characterization.pk), response.content.decode()
                )
            with self.subTest(url=url, reader="granted"):
                response = self.reader.get(url)
                self.assert_answer(response, 200, PRIVATE)
                self.assertIn(str(self.characterization.pk), response.content.decode())
        for url in self.singles:
            with self.subTest(url=url):
                self.assert_answer(self.visitor.get(url), 401, PRIVATE)
                self.assert_answer(self.reader.get(url), 200, PRIVATE)

    def test_an_ungranted_session(self):
        for url in self.singles:
            with self.subTest(url=url):
                response = self.stranger.get(url)
                self.assert_answer(response, 403, PRIVATE)
                self.assertEqual(response.content, b"")

    def test_an_unknown_id(self):
        unknown = uuid.uuid4()
        for url in (
            f"/iiif/v3/characterization-collection/{unknown}",
            f"/iiif/v3/characterization-collection/{unknown}/page-1",
            f"/iiif/v2/characterization-collection/{unknown}",
            f"/iiif/v2/characterization-collection/{unknown}/page-1",
            f"/iiif/v3/annotation/{self.characterization.pk}/{unknown}",
        ):
            with self.subTest(url=url):
                self.assert_answer(self.visitor.get(url), 404, PRIVATE)


class RestrictedCase(IIIFPermissionCase):
    """``open`` embargoed for the visitor and refused to ``stranger``, with a stored file."""

    def setUp(self):
        super().setUp()
        self.file_id = self.stored_file(
            self.analyses["open"], "X01.csv", b"x,y\n1,2\n3,4\n"
        )
        self.embargo(self.analyses["open"])
        self.stranger_user = User.objects.create_user(
            "iiif_token_stranger", password="pw"
        )
        self.stranger_user.groups.add(Group.objects.get(name="Resource Editor"))
        assign_perm(
            "no_access_to_resourceinstance", self.stranger_user, self.analyses["open"]
        )
        analysis = self.analyses["open"].pk
        self.singles = [
            *self.single_urls(self.analyses["open"]),
            f"/iiif/v3/content-state/{analysis}/{FEATURES['open']}",
            f"/iiif/data/{self.file_id}/raw",
            f"/iiif/data/{self.file_id}/series.csv",
        ]

    def get(self, url, token=None, raw=None):
        from tests.iiif_auth import bearer

        headers = bearer(token) if token else {}
        if raw:
            headers = {"HTTP_AUTHORIZATION": raw}
        return Client().get(url, **headers)

    def body(self, response):
        if response.streaming:
            return b"".join(response.streaming_content).decode()
        return response.content.decode()

    def assert_private(self, response, status):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response["Cache-Control"], PRIVATE)
        self.assertNotIn("ETag", response)
        self.assertIn("authorization", response["Vary"].lower())
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def assert_401_with_services(self, response):
        self.assert_private(response, 401)
        self.assertIn("Bearer", response["WWW-Authenticate"])
        body = response.json()
        login = body["service"][0]
        self.assertEqual(login["profile"], "http://iiif.io/api/auth/1/login")
        self.assertEqual(
            login["service"][0]["profile"], "http://iiif.io/api/auth/1/token"
        )
        self.assertNotIn("X01", response.content.decode())
        return body

    def test_the_visitor_is_401_with_the_services_on_restricted_single_and_data(self):
        for url in self.singles:
            with self.subTest(url=url):
                body = self.assert_401_with_services(self.get(url))
                if "/iiif/data/" in url:
                    self.assertEqual(body["type"], "Dataset")
                    self.assertEqual(body["service"][1]["type"], "AuthProbeService2")
                    self.assertTrue(
                        body["service"][1]["id"].endswith(
                            f"/iiif/auth/2/probe/{self.file_id}"
                        )
                    )
                else:
                    self.assertEqual(body["type"], "Annotation")
                    self.assertEqual(len(body["service"]), 1)

    def test_an_oauth2_bearer_does_not_unlock_iiif_reads(self):
        import datetime

        from django.utils import timezone
        from oauth2_provider.models import get_access_token_model, get_application_model

        application = get_application_model().objects.create(
            name="iiif-test",
            user=self.editor,
            client_type="confidential",
            authorization_grant_type="password",
        )
        get_access_token_model().objects.create(
            user=self.editor,
            application=application,
            token="oauth2-iiif-test-token",
            expires=timezone.now() + datetime.timedelta(hours=1),
            scope="read write",
        )

        for url in self.singles:
            with self.subTest(url=url):
                response = self.get(url, raw="Bearer oauth2-iiif-test-token")
                self.assertEqual(response.status_code, 401)
                self.assertNotIn("X01", self.body(response))


class TokenMatrixTests(RestrictedCase):
    """Every IIIF read route × granted token, ungranted token, invalid token."""

    def setUp(self):
        super().setUp()
        from tests.iiif_auth import token_for

        self.granted = token_for(self.editor)
        self.ungranted = token_for(self.stranger_user)

    def test_a_granted_token_reads_the_restricted_data_privately(self):
        for url in [*self.document_urls(), *self.collection_urls(), *self.singles]:
            with self.subTest(url=url):
                response = self.get(url, self.granted)
                self.assert_private(response, 200)
        for url in [*self.document_urls(), *self.single_urls(self.analyses["open"])]:
            with self.subTest(url=url):
                self.assertIn(
                    str(self.analyses["open"].pk),
                    self.body(self.get(url, self.granted)),
                )

    def test_an_ungranted_token_gets_filtered_pages_and_403_on_single_and_data(self):
        for url in self.document_urls():
            with self.subTest(url=url):
                response = self.get(url, self.ungranted)
                self.assert_private(response, 200)
                self.assertNotIn(str(self.analyses["open"].pk), self.body(response))
        for url in self.singles:
            with self.subTest(url=url):
                response = self.get(url, self.ungranted)
                self.assert_private(response, 403)
                self.assertEqual(self.body(response), "")

    def test_an_invalid_token_is_401_with_the_services(self):
        for url in [*self.document_urls(), *self.collection_urls(), *self.singles]:
            for token in (self.granted + "x", "msiiif1.forged", "opaque"):
                with self.subTest(url=url, token=token[:12]):
                    self.assert_401_with_services(self.get(url, token))

    def test_a_token_reader_never_fills_the_public_memo(self):
        from manuspectrum.iiif import memo
        from tests.iiif_auth import token_for

        plain = User.objects.create_user("iiif_token_plain", password="pw")
        plain.groups.add(Group.objects.get(name="Guest"))
        assign_perm("no_access_to_resourceinstance", plain, self.analyses["open"])
        self.assertTrue(memo.gate(plain).shared)
        token = token_for(plain)
        url = self.document_urls()[0]

        from unittest import mock

        with mock.patch.object(
            memo, "get_or_build", wraps=memo.get_or_build
        ) as memo_call:
            response = self.get(url, token)
        visitor = self.get(url)

        self.assert_private(response, 200)
        memo_call.assert_not_called()
        self.assertEqual(visitor["Cache-Control"], PUBLIC)
        self.assertEqual(self.body(visitor), self.body(response))


class ServiceDeclarationTests(IIIFPermissionCase):
    def setUp(self):
        super().setUp()
        self.file_id = self.stored_file(
            self.analyses["on_document"], "FORS.csv", b"x,y\n1,2\n3,4\n"
        )

    def page(self, client, version=3):
        document = self.documents["open"].pk
        return client.get(
            f"/iiif/v{version}/annotation-collection/{document}/page-1"
        ).json()

    def test_every_dataset_body_declares_both_auth_services(self):
        from manuspectrum.iiif import services

        page = self.page(self.visitor)
        bodies = [
            body
            for annotation in page["items"]
            for body in annotation.get("body", [])
            if body["type"] == "Dataset"
        ]

        self.assertTrue(bodies)
        for body in bodies:
            with self.subTest(body=body["id"]):
                file_id = body["id"].split("/iiif/data/")[1].split("/")[0]
                self.assertEqual(
                    body["service"],
                    [services.auth1_block(), services.auth2_probe(file_id)],
                )
        self.assertEqual(
            page["@context"][-1], "http://iiif.io/api/presentation/3/context.json"
        )
        self.assertIn("http://iiif.io/api/auth/2/context.json", page["@context"])
        v2 = self.page(self.visitor, 2)
        resources = [
            r
            for annotation in v2["resources"]
            for r in annotation.get("resource", [])
            if r["@type"] == "dctypes:Dataset"
        ]
        self.assertTrue(resources)
        for resource in resources:
            self.assertEqual(resource["service"], services.v2_auth1_block())

    def test_every_page_and_collection_declares_the_auth1_service(self):
        from manuspectrum.iiif import services

        document = self.documents["open"].pk
        for kind in ("annotation", "characterization"):
            for url in (
                f"/iiif/v3/{kind}-collection/{document}",
                f"/iiif/v3/{kind}-collection/{document}/page-2",
                f"/iiif/v2/{kind}-collection/{document}",
                f"/iiif/v2/{kind}-collection/{document}/page-2",
            ):
                with self.subTest(url=url):
                    seen = [
                        c.get(url).json()["service"]
                        for c in (self.visitor, self.reader)
                    ]
                    expected = (
                        [services.auth1_block()]
                        if "/v3/" in url
                        else services.v2_auth1_block()
                    )
                    self.assertEqual(seen, [expected, expected])
