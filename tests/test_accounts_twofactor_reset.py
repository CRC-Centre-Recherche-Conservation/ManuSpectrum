"""Forced two-factor enrolment and the re-enrolment link of a reset (PP-4 fix wave)."""

import re
from datetime import timedelta
from unittest import mock

import pyotp
from arches.app.models.models import UserProfile
from axes.models import AccessAttempt
from django.contrib.auth.models import User
from django.core import mail, signing
from django.core.cache import cache
from django.utils import timezone
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from manuspectrum.accounts import twofactor
from manuspectrum.accounts.terms import TERMS_VERSION
from manuspectrum.models import TermsAcceptance
from manuspectrum.accounts.twofactor import decrypt_secret, encrypt_secret
from tests.test_accounts_activation import browser_post
from tests.test_accounts_twofactor import PASSWORD, WRONG, enrol, stored

HTML = {"HTTP_ACCEPT": "text/html,application/xhtml+xml"}
IP = "203.0.113.30"


def post(client, path, **data):
    return client.post(path, data, HTTP_X_REAL_IP=IP, REMOTE_ADDR="10.0.0.1")


def token_path(user):
    return reverse(
        "account-two-factor-reset", kwargs={"token": twofactor.reset_token(user)}
    )


@override_settings(FORCE_TWO_FACTOR_AUTHENTICATION=True)
class RequireTwoFactorMiddlewareTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "a@manuspectrum.test", PASSWORD)
        TermsAcceptance.objects.create(user=cls.alice, version=TERMS_VERSION)

    def setUp(self):
        cache.clear()
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.alice)

    def test_a_navigation_without_a_secret_goes_to_the_enrolment_page(self):
        response = self.client.get("/en/about/team", **HTML)
        self.assertRedirects(
            response, "/en/account/two-factor", fetch_redirect_response=False
        )

    def test_other_requests_of_that_user_are_refused(self):
        for response in (
            self.client.get("/en/api/model-graph", HTTP_ACCEPT="application/json"),
            self.client.get("/en/about/team"),
            self.client.post("/en/about/team", **HTML),
            self.client.get(
                "/en/about/team",
                HTTP_ACCEPT="text/html",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            ),
            self.client.get("/iiif/v3/explorer-manifest?ids=x"),
        ):
            self.assertEqual(response.status_code, 403)

    def test_the_exempt_routes_stay_reachable(self):
        for path in (
            "/en/account/two-factor",
            "/en/account/terms",
            "/en/auth/?logout=true",
        ):
            response = self.client.get(path, **HTML)
            self.assertNotEqual(response.status_code, 403, path)
            self.assertFalse(
                response.status_code == 302
                and response["Location"] == "/en/account/two-factor",
                path,
            )

    def test_an_enrolled_user_and_a_visitor_are_untouched(self):
        enrol(self.alice)
        self.assertEqual(self.client.get("/en/about/team", **HTML).status_code, 200)
        self.assertEqual(Client().get("/en/about/team", **HTML).status_code, 200)

    def test_enrolment_through_the_page_then_lifts_the_gate(self):
        post(self.client, "/en/account/two-factor", action="start")
        secret = decrypt_secret(self.client.session["ms_pending_mfa_secret"])
        post(
            self.client,
            "/en/account/two-factor",
            action="confirm",
            code=pyotp.TOTP(secret).now(),
        )
        self.assertEqual(self.client.get("/en/about/team", **HTML).status_code, 200)

    def test_nothing_changes_when_the_setting_is_off(self):
        with override_settings(FORCE_TWO_FACTOR_AUTHENTICATION=False):
            self.assertEqual(self.client.get("/en/about/team", **HTML).status_code, 200)


class ResetTokenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "a@manuspectrum.test", PASSWORD)

    def test_a_token_is_valid_for_its_user_while_nothing_changes(self):
        token = twofactor.reset_token(self.alice)
        self.assertEqual(twofactor.user_for_reset(token), self.alice)

    def test_the_token_dies_with_an_enrolment(self):
        token = twofactor.reset_token(self.alice)
        enrol(self.alice)
        self.assertIsNone(twofactor.user_for_reset(token))

    def test_the_token_dies_with_a_password_change(self):
        token = twofactor.reset_token(self.alice)
        self.alice.set_password("Another!Passphrase-7")
        self.alice.save()
        self.assertIsNone(twofactor.user_for_reset(token))

    def test_the_token_dies_with_a_later_sign_in_even_if_the_secret_is_cleared_again(
        self,
    ):
        token = twofactor.reset_token(self.alice)
        User.objects.filter(pk=self.alice.pk).update(last_login=timezone.now())
        self.assertIsNone(twofactor.user_for_reset(token))
        newer = twofactor.reset_token(User.objects.get(pk=self.alice.pk))
        self.assertEqual(twofactor.user_for_reset(newer), self.alice)

    def test_the_token_dies_with_the_deactivation(self):
        token = twofactor.reset_token(self.alice)
        User.objects.filter(pk=self.alice.pk).update(is_active=False)
        self.assertIsNone(twofactor.user_for_reset(token))

    def test_the_token_expires_after_24_hours(self):
        token = twofactor.reset_token(self.alice)
        with mock.patch(
            "django.core.signing.time.time",
            return_value=__import__("time").time() + 25 * 3600,
        ):
            self.assertIsNone(twofactor.user_for_reset(token))

    def test_a_token_of_another_purpose_or_garbage_is_refused(self):
        other = signing.dumps({"u": self.alice.pk, "s": "x"}, salt="other")
        for token in (other, "garbage", ""):
            self.assertIsNone(twofactor.user_for_reset(token))


class ResetPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", "a@manuspectrum.test", PASSWORD)

    def setUp(self):
        cache.clear()
        AccessAttempt.objects.all().delete()
        self.client = Client(raise_request_exception=False)
        self.path = token_path(self.alice)
        self.page = "/en/account/two-factor/reset/enrol"

    def open(self):
        response = self.client.get(self.path)
        self.assertRedirects(response, self.page, fetch_redirect_response=False)
        return response

    def test_the_link_moves_its_token_to_the_session(self):
        response = self.open()
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertNotIn(self.path.rsplit("/", 1)[1], response["Location"])
        page = self.client.get(self.page)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page["Referrer-Policy"], "same-origin")
        self.assertNotContains(page, self.path.rsplit("/", 1)[1])
        self.assertContains(page, 'name="password"')

    def test_the_password_form_posts_from_the_browser_with_csrf_checks_on(self):
        client = Client(raise_request_exception=False, enforce_csrf_checks=True)
        client.get(self.path)
        page = client.get(self.page)
        response = browser_post(
            client, page, self.page, action="password", password=PASSWORD
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="code"')

    def test_a_user_with_stale_terms_is_not_sent_to_the_terms_with_the_token(self):
        self.client.force_login(self.alice)
        self.alice.refresh_from_db()
        response = self.client.get(token_path(self.alice), **HTML)
        self.assertRedirects(response, self.page, fetch_redirect_response=False)
        page = self.client.get(self.page, **HTML)
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("terms", page.get("Location", ""))

    def test_the_placeholder_without_a_session_token_is_refused(self):
        response = self.client.get(self.page)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(
            post(
                self.client, self.page, action="password", password=PASSWORD
            ).status_code,
            410,
        )

    def test_a_bad_token_is_refused(self):
        response = self.client.get("/en/account/two-factor/reset/not-a-token")
        self.assertEqual(response.status_code, 410)

    def test_a_wrong_password_is_refused_and_counted_by_axes(self):
        self.open()
        response = post(self.client, self.page, action="password", password=WRONG)
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, "qr_data", status_code=400)
        self.assertEqual(AccessAttempt.objects.filter(username="alice").count(), 1)
        self.assertIsNone(stored(self.alice))

    def test_an_older_link_stays_dead_after_an_enrolment_and_a_second_reset(self):
        self.open()
        post(self.client, self.page, action="password", password=PASSWORD)
        secret = decrypt_secret(self.client.session["ms_reset_pending_mfa_secret"])
        post(self.client, self.page, action="confirm", code=pyotp.TOTP(secret).now())
        UserProfile.objects.filter(user=self.alice).update(encrypted_mfa_hash=None)
        self.assertEqual(Client().get(self.path).status_code, 410)

    @override_settings(RATELIMIT_ENABLE=False)
    def test_the_account_is_locked_by_axes_after_the_failure_limit(self):
        self.open()
        statuses = [
            post(self.client, self.page, action="password", password=WRONG).status_code
            for _ in range(5)
        ]
        self.assertEqual(statuses, [400] * 4 + [429])
        response = post(self.client, self.page, action="password", password=PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertNotIn("ms_reset_pending_mfa_secret", self.client.session)
        self.assertIsNone(stored(self.alice))

    def test_the_manual_key_is_grouped_by_four_with_a_copy_button(self):
        self.open()
        response = post(self.client, self.page, action="password", password=PASSWORD)
        secret = decrypt_secret(self.client.session["ms_reset_pending_mfa_secret"])
        grouped = " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))
        self.assertContains(response, f">{grouped}</code>")
        self.assertContains(response, f'data-ms-copy-text="{secret}"')
        self.assertContains(response, "data-ms-copy-button")
        self.assertContains(response, "js/standalone/copy-text.js")
        self.assertNotIn("querySelector(", response.content.decode())

    def test_the_password_then_a_valid_code_enrols_and_signs_in(self):
        self.open()
        response = post(self.client, self.page, action="password", password=PASSWORD)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data:image/png;base64")
        secret = decrypt_secret(self.client.session["ms_reset_pending_mfa_secret"])
        bad = post(self.client, self.page, action="confirm", code="000000")
        if pyotp.TOTP(secret).now() != "000000":
            self.assertEqual(bad.status_code, 400)
        self.assertIsNone(stored(self.alice))
        done = post(
            self.client, self.page, action="confirm", code=pyotp.TOTP(secret).now()
        )
        self.assertRedirects(
            done, "/en/account/two-factor", fetch_redirect_response=False
        )
        self.assertEqual(decrypt_secret(stored(self.alice)), secret)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.alice.pk))
        self.assertEqual(Client().get(self.path).status_code, 410)
        self.assertEqual(self.client.get(self.page).status_code, 410)

    def test_a_code_without_the_password_step_enrols_nothing(self):
        self.open()
        secret = pyotp.random_base32()
        session = self.client.session
        session["ms_reset_pending_mfa_secret"] = encrypt_secret(secret)
        session.save()
        response = post(
            self.client, self.page, action="confirm", code=pyotp.TOTP(secret).now()
        )
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(stored(self.alice))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_post_is_rate_limited(self):
        self.open()
        with mock.patch("django_ratelimit.core._get_window", return_value=1_000_000):
            statuses = [
                post(self.client, self.page, action="cancel").status_code
                for _ in range(7)
            ]
        self.assertIn(429, statuses)


class AdminActionTests(TestCase):
    URL = "/en/admin/models/userprofile/"

    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser(
            "root", "r@manuspectrum.test", PASSWORD
        )
        cls.alice = User.objects.create_user(
            "alice", "alice@manuspectrum.test", PASSWORD
        )
        cls.bob = User.objects.create_user("bob", "bob@manuspectrum.test", PASSWORD)
        cls.nomail = User.objects.create_user("nomail", "", PASSWORD)

    def setUp(self):
        cache.clear()
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.root)

    def run_action(self, action, *users):
        pks = [UserProfile.objects.get_or_create(user=u)[0].pk for u in users]
        return self.client.post(
            self.URL, {"action": action, "_selected_action": pks}, follow=True
        )

    def test_the_reset_clears_the_secret_and_mails_a_working_link(self):
        enrol(self.alice)
        self.run_action("reset_two_factor", self.alice)
        self.assertIsNone(stored(self.alice))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["alice@manuspectrum.test"])
        self.assertTrue(message.subject.startswith("[ManuSpectrum][Account] "))
        body = message.body
        self.assertLess(
            body.index("Set up two-factor authentication"),
            (
                body.index("Configurer à nouveau")
                if "Configurer à nouveau" in body
                else len(body)
            ),
        )
        path = re.search(
            r"https?://[^\s]+/account/two-factor/reset/[^\s]+", body
        ).group(0)
        path = "/" + path.split("/", 3)[3]
        self.assertRedirects(
            Client().get(path),
            "/en/account/two-factor/reset/enrol",
            fetch_redirect_response=False,
        )

    def test_each_language_part_links_its_own_language_with_one_token(self):
        enrol(self.alice)
        self.run_action("reset_two_factor", self.alice)
        text_en, text_fr = mail.outbox[0].body.split("-" * 40)
        pattern = r"/(en|fr)/account/two-factor/reset/([^\s/]+)"
        en = re.search(pattern, text_en)
        fr = re.search(pattern, text_fr)
        self.assertEqual((en.group(1), fr.group(1)), ("en", "fr"))
        self.assertEqual(en.group(2), fr.group(2))

    def test_the_bulk_resend_reaches_only_accounts_without_a_secret(self):
        enrol(self.alice)
        self.run_action("send_enrolment_link", self.alice, self.bob, self.nomail)
        self.assertEqual([m.to for m in mail.outbox], [["bob@manuspectrum.test"]])
        self.assertIsNotNone(stored(self.alice))

    def test_a_staff_member_without_superuser_cannot_mail_or_reset(self):
        staff = User.objects.create_user(
            "staff", "s@manuspectrum.test", PASSWORD, is_staff=True
        )
        enrol(self.alice)
        self.client.force_login(staff)
        self.run_action("reset_two_factor", self.alice)
        self.run_action("send_enrolment_link", self.bob)
        self.assertIsNotNone(stored(self.alice))
        self.assertEqual(len(mail.outbox), 0)
