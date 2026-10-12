"""Invitation, account activation and acceptance of the terms (PP-4, decision 13)."""

import re
from unittest import mock

from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from manuspectrum.accounts import activation
from manuspectrum.accounts.terms import TERMS_VERSION
from manuspectrum.models import TermsAcceptance

PASSWORD = "Str0ng!Passphrase-for-tests"
HTML = {"HTTP_ACCEPT": "text/html,application/xhtml+xml"}
IP = "203.0.113.20"


def invited(username="newbie", email="newbie@manuspectrum.test"):
    user = User(username=username, email=email)
    user.set_unusable_password()
    user.save()
    return user


def link_path(user):
    return (
        "/en/account/activate/"
        + urlsafe_base64_encode(force_bytes(user.pk))
        + "/"
        + default_token_generator.make_token(user)
    )


def activate(client, path, **data):
    return client.post(path, data, HTTP_X_REAL_IP=IP, REMOTE_ADDR="10.0.0.1")


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(raise_request_exception=False)


class InvitationTests(Base):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_superuser(
            "boss", "boss@manuspectrum.test", PASSWORD
        )
        self.client.force_login(self.staff)

    def run_action(self, *users):
        return self.client.post(
            reverse("admin:auth_user_changelist"),
            {
                "action": "send_invitation",
                "_selected_action": [u.pk for u in users],
            },
            follow=True,
        )

    def test_one_mail_english_then_french_with_a_working_link(self):
        user = invited()
        self.run_action(user)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertTrue(message.subject.startswith("[ManuSpectrum][Account] "))
        self.assertEqual(message.extra_headers["X-ManuSpectrum-Category"], "Account")
        self.assertEqual(message.to, ["newbie@manuspectrum.test"])
        body = message.body
        self.assertLess(
            body.index("Activate my account"), body.index("Activer mon compte")
        )
        path = re.search(r"https?://[^\s]+/account/activate/[^\s]+", body).group(0)
        path = "/" + path.split("/", 3)[3]
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)

    def test_refused_for_a_usable_password_or_no_address(self):
        has_password = User.objects.create_user("p", "p@manuspectrum.test", PASSWORD)
        no_mail = invited("nomail", "")
        self.run_action(has_password, no_mail)
        self.assertEqual(len(mail.outbox), 0)
        with self.assertRaises(ValueError):
            activation.send_invitation(has_password)

    def test_the_user_admin_keeps_its_own_class_and_gains_the_action(self):
        model_admin = admin.site._registry[User]
        self.assertIn("send_invitation", model_admin.actions)


class ActivationTests(Base):
    def setUp(self):
        super().setUp()
        self.user = invited()
        self.path = link_path(self.user)

    def good(self, **overrides):
        data = {
            "new_password1": PASSWORD,
            "new_password2": PASSWORD,
            "accept_terms": "on",
        }
        data.update(overrides)
        return {k: v for k, v in data.items() if v is not None}

    def test_a_bad_token_is_refused_without_a_form(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        response = self.client.get(f"/en/account/activate/{uid}/bad-token")
        self.assertEqual(response.status_code, 410)
        self.assertNotContains(response, "<form", status_code=410)

    def test_an_unknown_user_is_refused(self):
        response = self.client.get("/en/account/activate/zzzz/abc-def")
        self.assertEqual(response.status_code, 410)

    def test_an_expired_token_is_refused(self):
        with override_settings(PASSWORD_RESET_TIMEOUT=-1):
            response = self.client.get(self.path)
        self.assertEqual(response.status_code, 410)

    def test_the_terms_and_the_version_are_shown(self):
        response = self.client.get(self.path)
        self.assertContains(response, TERMS_VERSION)
        self.assertContains(response, 'name="accept_terms"')
        self.assertContains(response, "not a data repository")

    def test_no_checkbox_refuses_and_stores_nothing(self):
        response = activate(self.client, self.path, **self.good(accept_terms=None))
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(TermsAcceptance.objects.exists())

    def test_a_weak_password_is_refused(self):
        response = activate(
            self.client,
            self.path,
            **self.good(new_password1="1234", new_password2="1234"),
        )
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(TermsAcceptance.objects.exists())

    def test_success_sets_the_password_records_logs_in_and_kills_the_link(self):
        response = activate(self.client, self.path, **self.good())
        self.assertRedirects(
            response, "/en/account/two-factor", fetch_redirect_response=False
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertTrue(
            TermsAcceptance.objects.filter(
                user=self.user, version=TERMS_VERSION
            ).exists()
        )
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))
        self.assertEqual(Client().get(self.path).status_code, 410)

    def test_the_post_is_rate_limited(self):
        statuses = [
            activate(self.client, self.path, **self.good(accept_terms=None)).status_code
            for _ in range(7)
        ]
        self.assertIn(429, statuses)


class MiddlewareTests(Base):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("mia", "mia@manuspectrum.test", PASSWORD)
        self.client.force_login(self.user)

    def accept(self):
        TermsAcceptance.objects.create(user=self.user, version=TERMS_VERSION)

    def test_a_page_navigation_is_redirected_to_the_accept_page(self):
        response = self.client.get("/en/about/team", **HTML)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/en/account/terms?next=/en/about/team")

    def test_requests_that_are_not_navigations_are_left_alone(self):
        self.assertNotEqual(self.client.get("/en/about/team").status_code, 302)
        self.assertNotEqual(
            self.client.get(
                "/en/about/team",
                HTTP_ACCEPT="text/html",
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            ).status_code,
            302,
        )
        self.assertNotEqual(
            self.client.get(
                "/en/api/model-graph", HTTP_ACCEPT="application/json"
            ).status_code,
            302,
        )
        self.assertNotEqual(
            self.client.get("/en/api/model-graph", **HTML).status_code, 302
        )
        self.assertNotEqual(self.client.post("/en/about/team", **HTML).status_code, 302)
        self.assertNotEqual(self.client.get("/static/x.css", **HTML).status_code, 302)

    def test_the_exempt_pages_are_reachable(self):
        for path in (
            "/en/account/terms",
            "/en/account/two-factor",
            "/en/auth/?logout=true",
        ):
            response = self.client.get(path, **HTML)
            self.assertFalse(
                response.status_code == 302
                and response["Location"].startswith("/en/account/terms"),
                path,
            )

    def test_anonymous_visitors_are_untouched(self):
        response = Client().get("/en/about/team", **HTML)
        self.assertEqual(response.status_code, 200)

    def test_accepting_records_and_returns_to_next(self):
        response = self.client.post(
            "/en/account/terms", {"accept_terms": "on", "next": "/en/about/team"}
        )
        self.assertRedirects(response, "/en/about/team", fetch_redirect_response=False)
        self.assertTrue(
            TermsAcceptance.objects.filter(
                user=self.user, version=TERMS_VERSION
            ).exists()
        )
        self.assertEqual(self.client.get("/en/about/team", **HTML).status_code, 200)

    def test_accepting_without_the_box_is_refused(self):
        response = self.client.post("/en/account/terms", {"next": "/en/about/team"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(TermsAcceptance.objects.exists())

    def test_an_external_next_is_refused(self):
        for target in ("https://evil.example/x", "//evil.example/x"):
            response = self.client.post(
                "/en/account/terms", {"accept_terms": "on", "next": target}
            )
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response["Location"], reverse("root"))

    def test_a_new_version_asks_again(self):
        self.accept()
        self.assertEqual(self.client.get("/en/about/team", **HTML).status_code, 200)
        with mock.patch.object(activation, "TERMS_VERSION", "2099-01-01"):
            response = self.client.get("/en/about/team", **HTML)
        self.assertEqual(response.status_code, 302)

    def test_a_signed_out_visitor_is_sent_to_sign_in_from_the_accept_page(self):
        response = Client().get("/en/account/terms")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/en/auth/"))
