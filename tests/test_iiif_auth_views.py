"""The IIIF Auth 1.0 / 2.0 service pages: login, token, probe, logout (C7).

Usage:
    python manage.py test tests.test_iiif_auth_views --settings=tests.test_settings
"""

import json
import re
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from manuspectrum.iiif import tokens
from tests.explorer_fixtures import IIIFCase
from tests.iiif_auth import DEMO, bearer, own_origin, signed_in, token_for

AUTH2 = "http://iiif.io/api/auth/2/context.json"


def script_data(response, element_id):
    """The value ``json_script`` wrote under *element_id*."""
    match = re.search(
        rf'<script id="{element_id}" type="application/json">(.*?)</script>',
        response.content.decode(),
        re.S,
    )
    return json.loads(match.group(1)) if match else None


class AuthCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("iiif_auth_user", password="pw")


class LoginTests(AuthCase):
    def test_login_sends_a_visitor_to_the_arches_login_with_a_relative_next(self):
        response = Client().get("/iiif/auth/login")

        self.assertEqual(response.status_code, 302)
        location = urlsplit(response["Location"])
        self.assertEqual(location.scheme + location.netloc, "")
        self.assertRegex(location.path, r"^/(en|fr)/auth/$")
        self.assertEqual(parse_qs(location.query), {"next": ["/iiif/auth/login"]})
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_login_ignores_origin_for_redirects(self):
        for origin in ("https://evil.example", "//evil.example", DEMO):
            with self.subTest(origin=origin):
                response = Client().get("/iiif/auth/login", {"origin": origin})
                self.assertEqual(
                    parse_qs(urlsplit(response["Location"]).query),
                    {"next": ["/iiif/auth/login"]},
                )
                self.assertNotIn("evil", response["Location"])

    def test_login_sets_the_access_cookie_secure_httponly_samesite_none_on_the_auth_path(
        self,
    ):
        client = Client()
        client.force_login(self.user)

        response = client.get("/iiif/auth/login", {"origin": "https://evil.example"})

        self.assertEqual(response.status_code, 200)
        cookie = response.cookies[tokens.COOKIE_NAME]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "None")
        self.assertEqual(cookie["path"], "/iiif/auth/")
        self.assertLessEqual(int(cookie["max-age"]), 8 * 3600)
        self.assertIn("window.close()", response.content.decode())
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_login_cannot_be_framed(self):
        client = Client()
        client.force_login(self.user)

        response = client.get("/iiif/auth/login")

        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])


class TokenTests(AuthCase):
    def token_page(self, client, version=1, **params):
        params.setdefault("messageId", "m-1")
        return client.get(f"/iiif/auth/{version}/token", params)

    def test_token_without_cookie_posts_missing_credentials_at_once(self):
        for client in (Client(), self._session_only()):
            with self.subTest(session=bool(client.session.session_key)):
                response = self.token_page(client, origin=DEMO)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    script_data(response, "iiif-auth-message"),
                    {
                        "messageId": "m-1",
                        "error": "missingCredentials",
                        "description": "Not signed in to ManuSpectrum in this browser.",
                    },
                )
                self.assertEqual(script_data(response, "iiif-auth-origin"), DEMO)
                self.assertNotIn("<form", response.content.decode())

    def _session_only(self):
        client = Client()
        client.force_login(self.user)
        return client

    def test_a_revoked_cookie_answers_missing_credentials(self):
        client = signed_in(self.user)
        kept = client.cookies[tokens.COOKIE_NAME].value
        client.get("/iiif/auth/logout")
        client.cookies[tokens.COOKIE_NAME] = kept

        message = script_data(self.token_page(client, origin=DEMO), "iiif-auth-message")

        self.assertEqual(message["error"], "missingCredentials")

    def test_token_to_a_foreign_origin_posts_invalid_origin_without_a_token(self):
        client = signed_in(self.user)

        for origin in (
            "https://evil.example",
            f"{DEMO}.evil.example",
            "http://crc-centre-recherche-conservation.github.io",
        ):
            with self.subTest(origin=origin):
                response = self.token_page(client, origin=origin)
                message = script_data(response, "iiif-auth-message")
                self.assertEqual(message["error"], "invalidOrigin")
                body = response.content.decode()
                self.assertNotIn("accessToken", body)
                self.assertNotIn(tokens.PREFIX, body)

    def test_token_without_origin_is_an_invalid_request(self):
        client = signed_in(self.user)

        for params in (
            {},
            {"origin": "null"},
            {"origin": "javascript:alert(1)"},
            {"origin": f"{DEMO}/x"},
            {"origin": f"https://user@{DEMO[8:]}"},
        ):
            with self.subTest(params=params):
                response = client.get("/iiif/auth/1/token", params)
                self.assertEqual(response.json()["error"], "invalidRequest")
                self.assertNotIn(tokens.PREFIX, response.content.decode())

    def test_token_posts_to_the_given_origin_never_star(self):
        client = signed_in(self.user)

        for origin in (DEMO, own_origin()):
            with self.subTest(origin=origin):
                response = self.token_page(client, origin=origin)
                message = script_data(response, "iiif-auth-message")
                self.assertEqual(message["messageId"], "m-1")
                self.assertEqual(
                    tokens.verify(message["accessToken"], origin), self.user
                )
                self.assertEqual(message["expiresIn"], 3600)
                self.assertEqual(script_data(response, "iiif-auth-origin"), origin)
                body = response.content.decode()
                self.assertIn("postMessage(message, origin)", body)
                self.assertNotRegex(body, r"postMessage\([^)]*['\"]\*['\"]")

    def test_the_message_id_is_escaped(self):
        client = signed_in(self.user)
        hostile = "</script><script>alert(1)</script>"

        response = self.token_page(client, origin=DEMO, messageId=hostile)

        self.assertNotIn(hostile, response.content.decode())
        self.assertEqual(
            script_data(response, "iiif-auth-message")["messageId"], hostile
        )

    def test_token_frame_ancestors_is_the_allowlist(self):
        response = self.token_page(signed_in(self.user), origin=DEMO)

        self.assertNotIn("X-Frame-Options", response)
        policy = response["Content-Security-Policy"]
        self.assertEqual(policy, f"frame-ancestors 'self' {own_origin()} {DEMO}")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_token_json_without_message_id(self):
        response = signed_in(self.user).get("/iiif/auth/1/token", {"origin": DEMO})

        self.assertEqual(response["Content-Type"], "application/json")
        message = response.json()
        self.assertEqual(set(message), {"accessToken", "expiresIn"})
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotIn("Access-Control-Allow-Origin", response)

    def test_token_2_speaks_the_auth_2_message_format(self):
        client = signed_in(self.user)

        granted = script_data(
            self.token_page(client, version=2, origin=DEMO), "iiif-auth-message"
        )
        refused = script_data(
            self.token_page(Client(), version=2, origin=DEMO), "iiif-auth-message"
        )
        foreign = self.token_page(client, version=2, origin="https://evil.example")

        self.assertEqual(granted["@context"], AUTH2)
        self.assertEqual(granted["type"], "AuthAccessToken2")
        self.assertEqual(granted["messageId"], "m-1")
        self.assertEqual(tokens.verify(granted["accessToken"], DEMO), self.user)
        self.assertEqual(granted["expiresIn"], 3600)
        self.assertEqual(refused["type"], "AuthAccessTokenError2")
        self.assertEqual(refused["profile"], "missingAspect")
        self.assertEqual(set(refused["heading"]), {"en", "fr"})
        self.assertEqual(set(refused["note"]), {"en", "fr"})
        self.assertEqual(
            script_data(foreign, "iiif-auth-message")["profile"], "invalidOrigin"
        )

    @override_settings(IIIF_AUTH_TOKEN_RATE="2/m")
    def test_token_over_the_rate_answers_unavailable(self):
        client = signed_in(self.user)

        answers = [
            self.token_page(client, origin=DEMO, messageId=str(n)) for n in range(3)
        ]

        self.assertIn("accessToken", script_data(answers[1], "iiif-auth-message"))
        last = script_data(answers[2], "iiif-auth-message")
        self.assertEqual(last["error"], "unavailable")
        self.assertNotIn("accessToken", last)


class ProbeTests(IIIFCase):
    def setUp(self):
        super().setUp()
        self.file_id = self.stored_file(self.analyses["open"], "a.csv", b"1,2\n3,4\n")

    def probe(self, client=None, file_id=None, **headers):
        response = (client or Client()).get(
            f"/iiif/auth/2/probe/{file_id or self.file_id}", **headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        body = response.json()
        self.assertEqual(body["@context"], AUTH2)
        self.assertEqual(body["type"], "AuthProbeResult2")
        return body

    def test_probe_answers_200_with_the_reader_status(self):
        self.assertEqual(self.probe()["status"], 200)
        self.embargo(self.analyses["open"])
        refused = self.probe()
        self.assertEqual(refused["status"], 401)
        self.assertEqual(set(refused["heading"]), {"en", "fr"})
        token = token_for(self.editor)
        self.assertEqual(self.probe(**bearer(token))["status"], 200)
        self.assertEqual(self.probe(**bearer(token + "x"))["status"], 401)
        stranger = User.objects.create_user("probe_stranger", password="pw")
        from arches.app.utils.permission_backend import assign_perm
        from django.contrib.auth.models import Group

        stranger.groups.add(Group.objects.get(name="Resource Editor"))
        assign_perm("no_access_to_resourceinstance", stranger, self.analyses["open"])
        self.assertEqual(self.probe(**bearer(token_for(stranger)))["status"], 403)
        self.assertEqual(
            self.probe(file_id="00000000-0000-4000-8000-00000000abcd")["status"], 404
        )


class LogoutTests(AuthCase):
    def test_logout_clears_the_cookie(self):
        client = signed_in(self.user)
        token = token_for(self.user, client=client)

        response = client.get("/iiif/auth/logout")

        self.assertEqual(response.status_code, 200)
        cookie = response.cookies[tokens.COOKIE_NAME]
        self.assertEqual(cookie.value, "")
        self.assertEqual(cookie["path"], "/iiif/auth/")
        self.assertEqual(cookie["samesite"], "None")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertIsNone(tokens.verify(token, DEMO))
        self.assertTrue(client.session.session_key)
