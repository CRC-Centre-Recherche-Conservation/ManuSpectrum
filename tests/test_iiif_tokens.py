"""The IIIF token: signed, read-only, bound to one Arches session and one viewer origin (C7).

Usage:
    python manage.py test tests.test_iiif_tokens --settings=tests.test_settings
"""

import datetime
import time
import uuid
from unittest import mock

from django.contrib.auth.models import AnonymousUser, Group, User
from django.contrib.sessions.models import Session
from django.core import signing
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from manuspectrum.iiif import tokens
from tests.iiif_auth import DEMO, bearer, signed_in, token_for


class TokenCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("iiif_token_user", password="pw")
        self.client = signed_in(self.user)
        self.token = token_for(self.user, client=self.client)


class VerifyTests(TokenCase):
    def test_a_token_verifies_for_its_user_session_and_origin(self):
        self.assertTrue(self.token.startswith("msiiif1."))
        self.assertEqual(tokens.verify(self.token, DEMO), self.user)
        self.assertEqual(tokens.verify(self.token, None), self.user)

    def test_an_expired_token_is_refused(self):
        later = time.time() + tokens.token_ttl() + 1
        with mock.patch("django.core.signing.time.time", return_value=later):
            self.assertIsNone(tokens.verify(self.token, DEMO))

    def test_a_tampered_or_other_salt_token_is_refused(self):
        payload = signing.TimestampSigner(salt=tokens.TOKEN_SALT).unsign_object(
            self.token[len(tokens.PREFIX) :]
        )
        other_salt = tokens.PREFIX + signing.TimestampSigner(
            salt="another.salt"
        ).sign_object(payload)
        forged = tokens.PREFIX + signing.TimestampSigner(
            salt=tokens.TOKEN_SALT, key="not-the-secret-key-" * 3
        ).sign_object(payload)
        flipped = self.token[:-1] + ("A" if self.token[-1] != "A" else "B")
        other_user = dict(payload, u=payload["u"] + 1)
        swapped = (
            tokens.PREFIX
            + signing.TimestampSigner(salt=tokens.TOKEN_SALT)
            .sign_object(other_user)
            .rsplit(":", 1)[0]
            + ":"
            + self.token.rsplit(":", 1)[1]
        )
        for token in (
            other_salt,
            forged,
            flipped,
            swapped,
            self.token[len(tokens.PREFIX) :],
            "msiiif1.",
            "msiiif1.garbage",
            "",
        ):
            with self.subTest(token=token[:40]):
                self.assertIsNone(tokens.verify(token, DEMO))

    def test_another_origin_is_refused(self):
        self.assertIsNone(tokens.verify(self.token, "https://evil.example"))
        self.assertIsNone(tokens.verify(self.token, f"{DEMO}.evil.example"))

    def test_an_origin_taken_off_the_allowlist_kills_its_tokens(self):
        with override_settings(IIIF_AUTH_TRUSTED_ORIGINS=[]):
            self.assertIsNone(tokens.verify(self.token, DEMO))

    def test_a_token_outlives_nothing_session_deleted(self):
        Session.objects.all().delete()

        self.assertIsNone(tokens.verify(self.token, DEMO))

    def test_an_expired_session_kills_the_token(self):
        Session.objects.update(expire_date=timezone.now() - datetime.timedelta(1))

        self.assertIsNone(tokens.verify(self.token, DEMO))

    def test_a_password_change_kills_the_token(self):
        self.user.set_password("another")
        self.user.save()

        self.assertIsNone(tokens.verify(self.token, DEMO))

    def test_a_deactivated_account_kills_the_token(self):
        User.objects.filter(pk=self.user.pk).update(is_active=False)

        self.assertIsNone(tokens.verify(self.token, DEMO))

    def test_iiif_logout_revokes_it(self):
        self.client.get("/iiif/auth/logout")

        self.assertIsNone(tokens.verify(self.token, DEMO))

    def test_signing_in_again_does_not_revive_a_revoked_token(self):
        self.client.get("/iiif/auth/logout")
        self.client.get("/iiif/auth/login")

        self.assertIsNone(tokens.verify(self.token, DEMO))
        self.assertEqual(
            tokens.verify(token_for(self.user, client=self.client), DEMO), self.user
        )

    def test_arches_logout_revokes_it(self):
        self.client.logout()

        self.assertIsNone(tokens.verify(self.token, DEMO))

    def test_the_token_carries_no_session_key(self):
        payload = signing.TimestampSigner(salt=tokens.TOKEN_SALT).unsign_object(
            self.token[len(tokens.PREFIX) :]
        )
        session_key = Session.objects.get().session_key

        self.assertEqual(set(payload), {"u", "s", "n", "o"})
        self.assertEqual(payload["o"], DEMO)
        self.assertNotIn(session_key, self.token)
        self.assertNotIn(session_key, str(payload))

    def test_the_access_cookie_carries_no_session_key(self):
        value = self.client.cookies[tokens.COOKIE_NAME].value
        session_key = Session.objects.get().session_key

        self.assertNotIn(session_key, value)
        self.assertEqual(
            set(signing.loads(value, salt=tokens.COOKIE_SALT)), {"u", "s", "n"}
        )


class ReaderTests(TokenCase):
    def request(self, **headers):
        request = RequestFactory().get("/iiif/v3/annotation/x", **headers)
        request.user = AnonymousUser()
        request.session = {}
        return request

    def test_the_token_never_becomes_request_user(self):
        request = self.request(**bearer(self.token))

        self.assertEqual(tokens.iiif_reader(request), self.user)
        self.assertTrue(tokens.by_token(request))
        self.assertIsInstance(request.user, AnonymousUser)

    def test_a_bearer_state_is_none_valid_or_invalid(self):
        self.assertEqual(tokens.bearer_state(self.request()), "none")
        self.assertEqual(
            tokens.bearer_state(self.request(HTTP_AUTHORIZATION="Basic abc")), "none"
        )
        self.assertEqual(
            tokens.bearer_state(self.request(**bearer(self.token))), "valid"
        )
        self.assertEqual(
            tokens.bearer_state(self.request(**bearer(self.token + "x"))), "invalid"
        )
        self.assertEqual(
            tokens.bearer_state(self.request(HTTP_AUTHORIZATION="Bearer ")), "invalid"
        )

    def test_a_request_without_credentials_reads_as_the_visitor(self):
        request = self.request()

        self.assertFalse(tokens.by_token(request))
        self.assertNotEqual(tokens.iiif_reader(request), self.user)

    def test_a_write_route_with_the_bearer_stays_anonymous(self):
        self.user.groups.add(Group.objects.get(name="Graph Editor"))
        url = f"/en/api/summary-config/{uuid.uuid4()}"

        by_session = self.client.get(url)
        by_token = Client().get(url, **bearer(self.token))

        self.assertNotEqual(by_session.status_code, 403)
        self.assertEqual(by_token.status_code, 403)

    def test_the_oauth2_middleware_ignores_it(self):
        from oauth2_provider.middleware import OAuth2TokenMiddleware

        seen = {}

        def view(request):
            seen["user"] = request.user
            from django.http import HttpResponse

            return HttpResponse()

        request = RequestFactory().get("/iiif/data/x/raw", **bearer(self.token))
        request.user = AnonymousUser()
        OAuth2TokenMiddleware(view)(request)

        self.assertTrue(seen["user"].is_anonymous)
