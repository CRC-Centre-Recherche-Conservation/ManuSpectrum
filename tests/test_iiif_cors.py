"""CORS of the IIIF routes under the committed settings: the views own it, ``django-cors-headers`` stays off ``/iiif/`` (C9).

Usage:
    python manage.py test tests.test_iiif_cors --settings=tests.test_settings
"""

import uuid

from django.test import Client, override_settings

from tests.explorer_fixtures import FEATURES, IIIFCase
from tests.iiif_auth import DEMO, signed_in

VIEWER = "https://viewer.example"


class CorsCase(IIIFCase):
    def setUp(self):
        super().setUp()
        self.file_id = self.stored_file(self.analyses["open"], "a.csv", b"1,2\n3,4\n")
        analysis = self.analyses["open"].pk
        self.read_urls = [
            f"/iiif/v3/annotation-collection/{self.documents['open'].pk}/page-1",
            f"/iiif/v3/annotation/{analysis}",
            f"/iiif/v3/content-state/{analysis}/{FEATURES['open']}",
            f"/iiif/data/{self.file_id}/raw",
            f"/iiif/data/{self.file_id}/series.csv",
            f"/iiif/auth/2/probe/{self.file_id}",
            f"/iiif/v3/explorer-manifest?document={self.documents['open'].pk}",
        ]

    def assert_cors(self, response):
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("WWW-Authenticate", response["Access-Control-Expose-Headers"])
        self.assertIn("ETag", response["Access-Control-Expose-Headers"])
        self.assertNotIn("Access-Control-Allow-Credentials", response)


@override_settings(CORS_ALLOW_ALL_ORIGINS=False, CORS_ALLOWED_ORIGINS=[])
class PreflightTests(CorsCase):
    def test_a_preflight_with_authorization_is_allowed_without_credentials(self):
        for url in self.read_urls:
            with self.subTest(url=url):
                response = Client().options(
                    url,
                    HTTP_ORIGIN=VIEWER,
                    HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
                    HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization",
                )
                self.assertLess(response.status_code, 300)
                self.assert_cors(response)
                self.assertIn(
                    "authorization", response["Access-Control-Allow-Headers"].lower()
                )
                self.assertIn("GET", response["Access-Control-Allow-Methods"])

    def test_a_401_carries_cors_headers(self):
        self.embargo(self.analyses["open"])

        for url in (
            f"/iiif/data/{self.file_id}/raw",
            f"/iiif/v3/annotation/{self.analyses['open'].pk}",
        ):
            with self.subTest(url=url):
                response = Client().get(url, HTTP_ORIGIN=VIEWER)
                self.assertEqual(response.status_code, 401)
                self.assert_cors(response)
        invalid = Client().get(
            f"/iiif/data/{self.file_id}/raw",
            HTTP_ORIGIN=VIEWER,
            HTTP_AUTHORIZATION="Bearer msiiif1.forged",
        )
        self.assertEqual(invalid.status_code, 401)
        self.assert_cors(invalid)

    def test_a_404_carries_cors_headers(self):
        for url in (
            f"/iiif/data/{uuid.uuid4()}/raw",
            f"/iiif/v3/annotation/{uuid.uuid4()}",
            f"/iiif/v3/annotation-collection/{uuid.uuid4()}/page-1",
        ):
            with self.subTest(url=url):
                response = Client().get(url, HTTP_ORIGIN=VIEWER)
                self.assertEqual(response.status_code, 404)
                self.assert_cors(response)

    def test_vary_holds_authorization_and_cookie(self):
        for url in self.read_urls:
            with self.subTest(url=url):
                vary = Client().get(url, HTTP_ORIGIN=VIEWER)["Vary"].lower()
                self.assertIn("authorization", vary)
                self.assertIn("cookie", vary)


@override_settings(CORS_ALLOW_ALL_ORIGINS=True)
class AuthPageTests(CorsCase):
    def test_auth_html_pages_send_no_cors(self):
        client = signed_in(self.editor)
        for url in (
            "/iiif/auth/login",
            f"/iiif/auth/1/token?origin={DEMO}&messageId=m",
            f"/iiif/auth/2/token?origin={DEMO}&messageId=m",
            f"/iiif/auth/1/token?origin={DEMO}",
            "/iiif/auth/logout",
        ):
            with self.subTest(url=url):
                response = client.get(url, HTTP_ORIGIN=VIEWER)
                self.assertLess(response.status_code, 400)
                self.assertNotIn("Access-Control-Allow-Origin", response)
