"""Account mail (PP-4, T6): category, sender, one message per recipient, counted outcomes."""

import logging
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings

from manuspectrum.accounts import notices
from tests.observability_helpers import delta

FROM = "noreply@manuspectrum.test"
PREFIX = "[ManuSpectrum][Account] "
RESOURCES = [{"name": "Codex <b>Alpha</b>", "url": "https://manuspectrum.test/r/1"}]
CONTEXTS = {
    "embargo_notice": {"resources": RESOURCES, "ends_on": date(2027, 3, 1), "days": 30},
    "embargo_lifted": {"resources": RESOURCES},
    "workflow_notice": {
        "workflow": "Import",
        "cleanup_on": date(2027, 3, 1),
        "days": 7,
        "resources": RESOURCES,
    },
    "workflow_cleaned": {"workflow": "Import", "deleted": RESOURCES, "kept": RESOURCES},
    "invitation": {
        "link": "https://manuspectrum.test/en/activate/abc-token",
        "expires_on": date.today() + timedelta(days=7),
    },
}


@override_settings(
    DEFAULT_FROM_EMAIL=FROM,
    CONTACT_EMAIL="contact@manuspectrum.test",
    ACCOUNT_SUMMARY_RECIPIENTS=["ops1@manuspectrum.test", "ops2@manuspectrum.test"],
)
class AccountMailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "alice", "alice@manuspectrum.test", "x", first_name="Alice"
        )

    def send(self, kind="embargo_notice", **kwargs):
        user = kwargs.get("user", self.user)
        return notices.send_account_mail(user, kind, CONTEXTS[kind])

    def test_subject_header_and_sender(self):
        for kind in CONTEXTS:
            with self.subTest(kind=kind):
                mail.outbox.clear()
                self.assertEqual(self.send(kind), "sent")
                message = mail.outbox[0]
                self.assertTrue(message.subject.startswith(PREFIX))
                self.assertNotIn("\n", message.subject)
                self.assertEqual(
                    message.extra_headers["X-ManuSpectrum-Category"], "Account"
                )
                self.assertEqual(message.from_email, FROM)
                self.assertNotIn("contact@manuspectrum.test", message.from_email)

    def test_one_message_to_one_recipient_without_copies(self):
        self.send()
        (message,) = mail.outbox
        self.assertEqual(message.to, ["alice@manuspectrum.test"])
        self.assertEqual((message.cc, message.bcc), ([], []))

    def test_text_and_html_hold_english_then_french(self):
        self.send("embargo_notice")
        message = mail.outbox[0]
        html = message.alternatives[0][0]
        for body in (message.body, html):
            self.assertIn("Hello Alice", body)
            self.assertIn("Bonjour Alice", body)
            self.assertLess(body.index("Hello Alice"), body.index("Bonjour Alice"))
            self.assertIn("1 mars 2027", body)
            self.assertIn("March 1, 2027", body)
        self.assertEqual(message.alternatives[0][1], "text/html")
        self.assertNotIn("<html", message.body)
        self.assertNotIn("font-family", message.body)
        self.assertIn("https://manuspectrum.test/r/1", message.body)

    def test_the_footer_says_there_is_no_unsubscribe(self):
        self.send()
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("no unsubscribe link", html)
        self.assertIn("pas de lien de désabonnement", html)
        self.assertIn("contact@manuspectrum.test", html)

    def test_names_are_escaped_in_html_and_not_in_text(self):
        self.send()
        message = mail.outbox[0]
        html = message.alternatives[0][0]
        self.assertNotIn("<b>Alpha</b>", html)
        self.assertIn("&lt;b&gt;Alpha&lt;/b&gt;", html)
        self.assertIn("Codex <b>Alpha</b>", message.body)

    def test_the_invitation_carries_its_link_and_button(self):
        self.send("invitation")
        message = mail.outbox[0]
        self.assertIn("activate/abc-token", message.body)
        self.assertIn("activate/abc-token", message.alternatives[0][0])
        self.assertIn("Activate my account", message.body)
        self.assertIn("Activer mon compte", message.body)

    def test_inactive_or_address_less_users_are_skipped(self):
        inactive = User.objects.create_user(
            "bob", "bob@manuspectrum.test", "x", is_active=False
        )
        silent = User.objects.create_user("carol", "", "x")
        for user in (inactive, silent, None):
            with self.subTest(user=user):
                with delta(
                    "manuspectrum_account_mails_total",
                    kind="embargo_notice",
                    outcome="skipped",
                ) as skipped:
                    outcome = self.send(user=user)
                self.assertEqual(outcome, "skipped")
                self.assertEqual(skipped.value, 1)
        self.assertEqual(mail.outbox, [])

    def test_sent_is_counted(self):
        with delta(
            "manuspectrum_account_mails_total", kind="embargo_lifted", outcome="sent"
        ) as sent:
            self.send("embargo_lifted")
        self.assertEqual(sent.value, 1)

    def test_a_failing_backend_is_counted_and_logs_no_address(self):
        error = OSError("relay refused alice@manuspectrum.test")
        with (
            patch("django.core.mail.message.EmailMessage.send", side_effect=error),
            delta(
                "manuspectrum_account_mails_total", kind="invitation", outcome="failed"
            ) as failed,
            self.assertLogs("manuspectrum.accounts.notices", logging.WARNING) as logs,
        ):
            outcome = self.send("invitation")
        self.assertEqual(outcome, "failed")
        self.assertEqual(failed.value, 1)
        logged = "\n".join(logs.output)
        self.assertNotIn("alice", logged)
        self.assertNotIn("abc-token", logged)
        self.assertIn("invitation", logged)

    def test_the_pass_continues_after_a_failure(self):
        other = User.objects.create_user("dan", "dan@manuspectrum.test", "x")
        calls = []

        def flaky(message, *args, **kwargs):
            calls.append(message.to)
            if len(calls) == 1:
                raise OSError("down")
            return 1

        with patch("django.core.mail.message.EmailMessage.send", flaky):
            outcomes = [self.send(user=u) for u in (self.user, other)]
        self.assertEqual(outcomes, ["failed", "sent"])

    def test_the_summary_goes_one_message_per_administrator(self):
        self.assertEqual(
            notices.send_summary_mail("embargo_notice", CONTEXTS["embargo_notice"]),
            ["sent", "sent"],
        )
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            ["ops1@manuspectrum.test", "ops2@manuspectrum.test"],
        )
        for message in mail.outbox:
            self.assertEqual(len(message.to), 1)
            self.assertEqual(message.bcc, [])
            self.assertTrue(message.subject.startswith(PREFIX))
            self.assertEqual(
                message.extra_headers["X-ManuSpectrum-Category"], "Account"
            )
            self.assertIn("Copy for the administrators", message.body)

    @override_settings(ACCOUNT_SUMMARY_RECIPIENTS=[])
    def test_no_summary_recipient_sends_nothing(self):
        self.assertEqual(
            notices.send_summary_mail("stale_report", {"count": 3, "months": 12}), []
        )
        self.assertEqual(mail.outbox, [])

    def test_the_closed_vocabulary_refuses_other_kinds(self):
        with self.assertRaises(ValueError):
            notices.send_account_mail(self.user, "newsletter", {})
        with self.assertRaises(ValueError):
            notices.send_account_mail(self.user, "stale_report", {})
        with self.assertRaises(ValueError):
            notices.send_summary_mail("invitation", CONTEXTS["invitation"])

    def test_every_metric_kind_is_a_known_kind(self):
        from manuspectrum.observability import metrics

        self.assertEqual(set(notices.KINDS), set(metrics.ACCOUNT_MAIL_KINDS))


@override_settings(DEFAULT_FROM_EMAIL=FROM, CONTACT_EMAIL="contact@manuspectrum.test")
class PasswordResetMailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user("alice", "alice@manuspectrum.test", "x")

    def reset(self):
        return self.client.post(
            "/en/password_reset/", {"email": "alice@manuspectrum.test"}
        )

    def test_the_reset_mail_carries_the_prefix_header_and_sender(self):
        with delta(
            "manuspectrum_account_mails_total", kind="password_reset", outcome="sent"
        ) as sent:
            response = self.reset()
        self.assertEqual(response.status_code, 302)
        (message,) = mail.outbox
        self.assertTrue(message.subject.startswith(PREFIX + "Password reset"))
        self.assertEqual(message.extra_headers["X-ManuSpectrum-Category"], "Account")
        self.assertEqual(message.from_email, FROM)
        self.assertEqual(message.alternatives[0][1], "text/html")
        self.assertEqual(sent.value, 1)

    def test_a_failed_reset_mail_is_counted_and_the_answer_is_unchanged(self):
        with (
            patch(
                "django.core.mail.message.EmailMessage.send",
                side_effect=OSError("down"),
            ),
            delta(
                "manuspectrum_account_mails_total",
                kind="password_reset",
                outcome="failed",
            ) as failed,
        ):
            response = self.reset()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(failed.value, 1)
