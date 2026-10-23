"""Two-factor enrolment and the second-factor sign-in step (PP-4, T4)."""

from unittest import mock

import pyotp
from arches.app.models.models import UserProfile
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings

from manuspectrum.accounts.twofactor import decrypt_secret, encrypt_secret
from tests.observability_helpers import delta
from tests.totp import current_code

PASSWORD = "Str0ng!Passphrase-for-tests"
WRONG = "not-the-password-Zq81"
PAGE = "/en/account/two-factor"
LOGIN = "/en/two-factor-authentication-login"
IP = "203.0.113.10"


def post(client, path, **data):
    return client.post(path, data, HTTP_X_REAL_IP=IP, REMOTE_ADDR="10.0.0.1")


def enrol(user):
    secret = pyotp.random_base32()
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.encrypted_mfa_hash = encrypt_secret(secret)
    profile.save()
    return secret


def stored(user):
    return UserProfile.objects.get(user=user).encrypted_mfa_hash


def wrong_code(secret):
    right = current_code(secret)
    return "000000" if right != "000000" else "111111"


class SetupBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", "alice@manuspectrum.test", PASSWORD
        )
        cls.bob = User.objects.create_user("bob", "bob@manuspectrum.test", PASSWORD)

    def setUp(self):
        cache.clear()
        self.client = Client(raise_request_exception=False)
        self.client.force_login(self.alice)

    def start(self):
        response = post(self.client, PAGE, action="start")
        self.assertEqual(response.status_code, 200)
        return decrypt_secret(self.client.session["ms_pending_mfa_secret"])


class SettingsTests(TestCase):
    def test_two_factor_is_on_and_not_forced(self):
        self.assertIs(settings.ENABLE_TWO_FACTOR_AUTHENTICATION, True)
        self.assertIs(settings.FORCE_TWO_FACTOR_AUTHENTICATION, False)


class EnrolmentTests(SetupBase):
    def test_anonymous_visitor_is_sent_to_sign_in_and_nothing_changes(self):
        enrol(self.bob)
        before = stored(self.bob)
        User.objects.get_or_create(username="anonymous")
        anonymous = Client(raise_request_exception=False)
        response = anonymous.post(
            PAGE, {"action": "remove", "user-id": self.bob.pk, "code": "123456"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(stored(self.bob), before)
        self.assertEqual(anonymous.get(PAGE).status_code, 302)
        post_anonymous = anonymous.post(PAGE, {"action": "start"})
        self.assertEqual(post_anonymous.status_code, 302)
        self.assertFalse(
            UserProfile.objects.filter(user__username="anonymous")
            .exclude(encrypted_mfa_hash__isnull=True)
            .exists()
        )

    def test_start_shows_a_qr_code_and_stores_nothing_yet(self):
        response = post(self.client, PAGE, action="start")
        self.assertContains(response, "data:image/png;base64,")
        self.assertFalse(
            UserProfile.objects.filter(user=self.alice)
            .exclude(encrypted_mfa_hash__isnull=True)
            .exists()
        )

    def test_the_manual_key_is_grouped_by_four_and_copied_without_spaces(self):
        secret = self.start()
        html = self.client.get(PAGE).content.decode()
        grouped = " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))
        self.assertIn(f">{grouped}</code>", html)
        self.assertIn(f'data-ms-copy-text="{secret}"', html)
        self.assertIn("data-ms-copy-button", html)
        self.assertIn("js/standalone/copy-text.js", html)
        self.assertNotIn("querySelector(", html)

    def test_a_valid_code_stores_the_secret_the_way_arches_reads_it(self):
        secret = self.start()
        response = post(self.client, PAGE, action="confirm", code=current_code(secret))
        self.assertContains(response, "Two-factor authentication is on.")
        value = stored(self.alice)
        self.assertNotIn(secret, value)
        self.assertEqual(decrypt_secret(value), secret)
        self.assertNotIn("ms_pending_mfa_secret", self.client.session)

    def test_a_first_enrolment_offers_a_continue_button_to_the_home_page(self):
        secret = self.start()
        response = post(self.client, PAGE, action="confirm", code=current_code(secret))
        self.assertContains(response, 'href="/en/" class="btn btn-primary btn-block')
        self.assertContains(response, "Continue")

    def test_a_replacement_does_not_offer_the_continue_button(self):
        old = enrol(self.alice)
        post(self.client, PAGE, action="start", code=current_code(old))
        secret = decrypt_secret(self.client.session["ms_pending_mfa_secret"])
        response = post(self.client, PAGE, action="confirm", code=current_code(secret))
        self.assertContains(response, "Two-factor authentication is on.")
        self.assertNotContains(response, "btn-primary")

    def test_a_wrong_code_stores_nothing(self):
        secret = self.start()
        response = post(self.client, PAGE, action="confirm", code=wrong_code(secret))
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(stored(self.alice))

    def test_the_account_comes_from_the_session_never_from_the_request(self):
        secret = self.start()
        post(
            self.client,
            PAGE,
            action="confirm",
            code=current_code(secret),
            **{"user-id": self.bob.pk, "user": self.bob.pk},
        )
        self.assertIsNotNone(stored(self.alice))
        self.assertFalse(
            UserProfile.objects.filter(user=self.bob)
            .exclude(encrypted_mfa_hash__isnull=True)
            .exists()
        )

    def test_replacing_needs_the_current_code(self):
        secret = enrol(self.alice)
        before = stored(self.alice)
        refused = post(self.client, PAGE, action="start", code=wrong_code(secret))
        self.assertEqual(refused.status_code, 400)
        self.assertNotIn("ms_pending_mfa_secret", self.client.session)
        accepted = post(self.client, PAGE, action="start", code=current_code(secret))
        self.assertContains(accepted, "data:image/png;base64,")
        self.assertEqual(stored(self.alice), before)

    def test_removing_needs_the_current_code(self):
        secret = enrol(self.alice)
        refused = post(self.client, PAGE, action="remove", code=wrong_code(secret))
        self.assertEqual(refused.status_code, 400)
        self.assertIsNotNone(stored(self.alice))
        post(self.client, PAGE, action="remove", code=current_code(secret))
        self.assertIsNone(stored(self.alice))

    @override_settings(FORCE_TWO_FACTOR_AUTHENTICATION=True)
    def test_removing_is_refused_when_two_factor_is_compulsory(self):
        secret = enrol(self.alice)
        response = post(self.client, PAGE, action="remove", code=current_code(secret))
        self.assertEqual(response.status_code, 403)
        self.assertIsNotNone(stored(self.alice))
        self.assertNotContains(self.client.get(PAGE), 'value="remove"')

    @override_settings(ENABLE_TWO_FACTOR_AUTHENTICATION=False)
    def test_the_page_is_absent_when_two_factor_is_off(self):
        self.assertEqual(self.client.get(PAGE).status_code, 404)

    def test_the_page_needs_the_csrf_token(self):
        strict = Client(enforce_csrf_checks=True, raise_request_exception=False)
        strict.force_login(self.alice)
        self.assertEqual(strict.post(PAGE, {"action": "start"}).status_code, 403)

    def test_attempts_are_rate_limited_per_user(self):
        secret = self.start()
        with mock.patch("django_ratelimit.core._get_window", return_value=1_000_000):
            codes = [
                post(
                    self.client, PAGE, action="confirm", code=wrong_code(secret)
                ).status_code
                for _ in range(7)
            ]
        self.assertEqual(codes[-1], 429)
        self.assertIsNone(stored(self.alice))

    def test_the_french_page_is_translated(self):
        response = self.client.get("/fr/account/two-factor")
        self.assertContains(response, "Authentification à deux facteurs")


class SecondFactorSignInTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", "alice@manuspectrum.test", PASSWORD, is_staff=True
        )

    def setUp(self):
        cache.clear()
        self.client = Client(raise_request_exception=False)
        self.secret = enrol(self.alice)

    def second_step(self, code, password=PASSWORD):
        return post(
            self.client,
            LOGIN,
            **{
                "username": "alice",
                "password": password,
                "next": "/",
                "user-has-enabled-two-factor-authentication": "True",
                "two-factor-authentication": code,
            },
        )

    def signed_in(self):
        return "_auth_user_id" in self.client.session

    def test_the_password_step_asks_for_the_code(self):
        response = post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertContains(response, "name='two-factor-authentication'")
        self.assertFalse(self.signed_in())

    def test_the_code_page_loads_the_single_submission_script(self):
        response = post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertContains(response, "js/utils/two-factor-login.js")
        self.assertContains(response, "onkeyup")

    def test_a_valid_code_signs_in(self):
        response = self.second_step(current_code(self.secret))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.signed_in())

    def test_a_wrong_password_is_a_401_not_a_500(self):
        response = self.second_step(current_code(self.secret), password=WRONG)
        self.assertEqual(response.status_code, 401)
        self.assertNotContains(response, WRONG, status_code=401)
        self.assertFalse(self.signed_in())

    def test_a_wrong_code_is_a_401(self):
        response = self.second_step(wrong_code(self.secret))
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.signed_in())

    def test_five_wrong_codes_lock_the_account(self):
        for _ in range(5):
            self.second_step(wrong_code(self.secret))
        response = self.second_step(current_code(self.secret))
        self.assertEqual(response.status_code, 429)
        self.assertFalse(self.signed_in())

    def test_four_wrong_codes_do_not_lock(self):
        for _ in range(4):
            self.second_step(wrong_code(self.secret))
        self.assertEqual(self.second_step(current_code(self.secret)).status_code, 302)

    def test_wrong_codes_are_counted_as_mfa_failures_only(self):
        with delta("manuspectrum_auth_logins_total", outcome="mfa_failure") as mfa:
            with delta("manuspectrum_auth_logins_total", outcome="failure") as plain:
                self.second_step(wrong_code(self.secret))
                self.second_step(wrong_code(self.secret))
        self.assertEqual(mfa.value, 2)
        self.assertEqual(plain.value, 0)

    def test_a_wrong_password_is_counted_as_a_plain_failure(self):
        with delta("manuspectrum_auth_logins_total", outcome="failure") as plain:
            with delta("manuspectrum_auth_logins_total", outcome="mfa_failure") as mfa:
                self.second_step("123456", password=WRONG)
        self.assertEqual(plain.value, 1)
        self.assertEqual(mfa.value, 0)


class CsrfFailureTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            "alice", "alice@manuspectrum.test", PASSWORD, is_staff=True
        )

    def setUp(self):
        cache.clear()
        self.client = Client(raise_request_exception=False, enforce_csrf_checks=True)
        self.secret = enrol(self.alice)

    def token(self):
        return self.client.cookies["csrftoken"].value

    def code_step(self, token, next_url="/", code=None):
        return post(
            self.client,
            LOGIN,
            **{
                "csrfmiddlewaretoken": token,
                "username": "alice",
                "password": PASSWORD,
                "next": next_url,
                "user-has-enabled-two-factor-authentication": "True",
                "two-factor-authentication": code or current_code(self.secret),
            },
        )

    def signed_code_step(self, next_url="/"):
        self.client.get("/en/auth/")
        old = self.token()
        post(
            self.client,
            "/en/auth/",
            csrfmiddlewaretoken=old,
            username="alice",
            password=PASSWORD,
        )
        first = self.code_step(old, next_url)
        self.assertEqual(first.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
        return old

    def test_the_second_post_of_the_code_is_redirected_to_next(self):
        old = self.signed_code_step(next_url="/en/search")
        again = self.code_step(old, "/en/search")
        self.assertEqual(again.status_code, 302)
        self.assertEqual(again["Location"], "/en/search")

    def test_the_second_post_is_a_403_without_the_failure_view(self):
        with override_settings(CSRF_FAILURE_VIEW="django.views.csrf.csrf_failure"):
            old = self.signed_code_step()
            self.assertEqual(self.code_step(old).status_code, 403)

    def test_an_unsafe_next_falls_back_to_the_home_page(self):
        old = self.signed_code_step()
        again = self.code_step(old, "https://evil.example/steal")
        self.assertEqual(again.status_code, 302)
        self.assertEqual(again["Location"], "/en/")

    def test_a_next_that_is_a_bare_word_is_a_redirect_not_a_url_name_lookup(self):
        old = self.signed_code_step()
        again = self.code_step(old, "foo")
        self.assertEqual(again.status_code, 302)
        self.assertEqual(again["Location"], "foo")

    def test_a_bad_token_without_a_session_is_still_refused(self):
        response = self.code_step("x" * 64)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "This page is out of date", status_code=403)
        self.assertContains(response, "noindex", status_code=403)

    def test_another_failure_gets_the_site_page(self):
        self.client.force_login(self.alice)
        response = post(self.client, PAGE, action="start", csrfmiddlewaretoken="x" * 64)
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "This page is out of date", status_code=403)

    def test_an_api_path_gets_json(self):
        from manuspectrum.accounts.csrf_failure import csrf_failure

        request = RequestFactory().post("/en/api/anything")
        request.user = self.alice
        response = csrf_failure(request, "reason")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")


class AdminResetTests(TestCase):
    URL = "/en/admin/models/userprofile/"

    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser(
            "root", "r@manuspectrum.test", PASSWORD
        )
        cls.staff = User.objects.create_user(
            "staff", "s@manuspectrum.test", PASSWORD, is_staff=True
        )
        cls.alice = User.objects.create_user("alice", "a@manuspectrum.test", PASSWORD)

    def run_action(self, user):
        enrol(self.alice)
        client = Client(raise_request_exception=False)
        client.force_login(user)
        profile = UserProfile.objects.get(user=self.alice)
        return client.post(
            self.URL,
            {"action": "reset_two_factor", "_selected_action": [profile.pk]},
            follow=True,
        )

    def test_a_superuser_clears_the_secret(self):
        self.run_action(self.root)
        self.assertIsNone(stored(self.alice))

    def test_the_stored_secret_is_not_in_the_form(self):
        model_admin = admin.site._registry[UserProfile]
        self.assertIn("encrypted_mfa_hash", model_admin.exclude)

    def test_a_staff_member_without_the_permission_cannot(self):
        self.run_action(self.staff)
        self.assertIsNotNone(stored(self.alice))
