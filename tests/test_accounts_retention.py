"""The retention pass: notice 30 days before, then anonymise accounts idle for 24 months.

The pass is driven by an explicit clock; mail goes to the locmem outbox.

Usage:
    python manage.py test tests.test_accounts_retention --settings="tests.test_settings" --noinput
"""

import io
import uuid
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from arches.app.models.models import EditLog, UserProfile
from axes.models import AccessAttempt, AccessLog
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import Group, User
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from manuspectrum.accounts import retention
from manuspectrum.accounts.embargo import LOCAL_TZ
from manuspectrum.accounts.retention import run_pass
from manuspectrum.models import AccountRetention, TermsAcceptance
from tests.observability_helpers import delta, sample

NOW = datetime(2026, 10, 12, 4, 30, tzinfo=LOCAL_TZ)
SUMMARY = ["ops@manuspectrum.test"]


def stored(moment):
    """*moment* as the user columns hold it (naive local when USE_TZ is off)."""
    if settings.USE_TZ:
        return moment
    return moment.astimezone(ZoneInfo(settings.TIME_ZONE)).replace(tzinfo=None)


def months_ago(months, extra_days=0):
    return NOW - relativedelta(months=months) - timedelta(days=extra_days)


@override_settings(ACCOUNT_SUMMARY_RECIPIENTS=SUMMARY)
class RetentionCase(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        User.objects.update(last_login=None, date_joined=stored(NOW))

    def user(self, name="alice", *, last_login=None, joined=None, **extra):
        joined = joined or months_ago(30)
        user = User.objects.create_user(
            name, f"{name}@manuspectrum.test", "x", first_name=name.title(), **extra
        )
        User.objects.filter(pk=user.pk).update(
            last_login=stored(last_login) if last_login else None,
            date_joined=stored(joined),
        )
        user.refresh_from_db()
        return user

    def go(self, now=NOW, **kwargs):
        return run_pass(now, **kwargs)

    def anonymised(self, user):
        return AccountRetention.objects.filter(
            user_id=user.pk, anonymised_on__isnull=False
        ).exists()

    def notices(self):
        return [m for m in mail.outbox if m.to != SUMMARY]


class SelectionTests(RetentionCase):
    def test_idle_for_23_months_is_left_alone_and_for_25_is_noticed(self):
        young = self.user("young", last_login=months_ago(23))
        old = self.user("old", last_login=months_ago(25))
        report = self.go()
        self.assertEqual(report.noticed, [old.pk])
        self.assertNotIn(young.pk, report.noticed)

    def test_a_never_signed_in_account_ages_from_its_creation(self):
        recent = self.user("recent", joined=months_ago(23))
        stale = self.user("stale", joined=months_ago(25))
        self.assertEqual(self.go().noticed, [stale.pk])
        self.assertNotIn(recent.pk, self.go().noticed)

    def test_the_visitor_and_an_anonymised_account_are_never_looked_at(self):
        anonymous = User.objects.get_or_create(username="anonymous")[0]
        User.objects.filter(pk=anonymous.pk).update(
            last_login=None, date_joined=stored(months_ago(40))
        )
        done = self.user("done", last_login=months_ago(40))
        retention.anonymise(done.pk)
        report = self.go()
        self.assertEqual(report.noticed + report.anonymised, [])

    def test_a_deactivated_account_is_still_selected(self):
        quiet = self.user("quiet", last_login=months_ago(25), is_active=False)
        self.assertEqual(self.go().noticed, [quiet.pk])
        self.assertEqual(len(self.notices()), 1)


class NoticeTests(RetentionCase):
    def test_the_notice_goes_once_thirty_days_before(self):
        user = self.user(last_login=months_ago(24) + timedelta(days=30))
        self.assertEqual(self.go().noticed, [user.pk])
        (message,) = self.notices()
        self.assertEqual(message.to, ["alice@manuspectrum.test"])
        self.assertIn("[ManuSpectrum][Account]", message.subject)
        self.assertIn("anonymised", message.body)
        self.assertIn("anonymisé", message.body)
        self.assertEqual(self.go(NOW + timedelta(days=5)).noticed, [])
        self.assertEqual(len(self.notices()), 1)

    def test_nothing_is_sent_29_days_before(self):
        self.user(last_login=months_ago(24) + timedelta(days=31))
        self.assertEqual(self.go().noticed, [])
        self.assertEqual(mail.outbox, [])

    def test_an_overdue_account_is_noticed_first_and_anonymised_30_days_later(self):
        user = self.user(last_login=months_ago(30))
        report = self.go()
        self.assertEqual((report.noticed, report.anonymised), ([user.pk], []))
        self.assertFalse(self.anonymised(user))
        self.assertEqual(self.go(NOW + timedelta(days=29)).anonymised, [])
        self.assertEqual(self.go(NOW + timedelta(days=30)).anonymised, [user.pk])

    def test_signing_in_after_the_notice_voids_it_and_restarts_the_clock(self):
        user = self.user(last_login=months_ago(25))
        self.go()
        User.objects.filter(pk=user.pk).update(last_login=stored(NOW))
        later = NOW + timedelta(days=40)
        report = self.go(later)
        self.assertEqual((report.reset, report.anonymised), ([user.pk], []))
        row = AccountRetention.objects.get(user_id=user.pk)
        self.assertIsNone(row.noticed_on)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.username, "alice")

    def test_an_account_without_address_is_skipped_but_still_recorded(self):
        user = self.user(last_login=months_ago(25))
        User.objects.filter(pk=user.pk).update(email="")
        self.assertEqual(self.go().noticed, [user.pk])
        self.assertEqual(self.notices(), [])
        self.assertEqual(self.go(NOW + timedelta(days=30)).anonymised, [user.pk])

    def test_the_administrators_get_a_summary_without_names(self):
        self.user(last_login=months_ago(25))
        self.go()
        (summary,) = [m for m in mail.outbox if m.to == SUMMARY]
        self.assertNotIn("alice", summary.body.lower())
        self.assertIn("1 newly warned", summary.body)


class AnonymiseTests(RetentionCase):
    def setUp(self):
        super().setUp()
        self.user_ = self.user(last_login=months_ago(25))
        UserProfile.objects.update_or_create(
            user=self.user_,
            defaults={"encrypted_mfa_hash": "secret", "phone": "0102030405"},
        )
        self.profile = UserProfile.objects.get(user=self.user_)
        self.group = Group.objects.create(name="Editors")
        self.user_.groups.add(self.group)
        TermsAcceptance.objects.create(user=self.user_, version="1")

    def anonymise(self):
        self.go()
        return self.go(NOW + timedelta(days=30))

    def test_the_account_fields_are_cleared_and_nothing_is_deleted(self):
        sessions = SessionStore()
        sessions["_auth_user_id"] = str(self.user_.pk)
        sessions.create()
        other = SessionStore()
        other["_auth_user_id"] = "999999"
        other.create()
        AccessAttempt.objects.create(
            username="alice",
            ip_address="1.2.3.4",
            user_agent="",
            get_data="",
            post_data="",
            http_accept="",
            path_info="",
            failures_since_start=1,
        )
        AccessLog.objects.create(
            username="alice",
            ip_address="1.2.3.4",
            user_agent="",
            http_accept="",
            path_info="",
        )
        report = self.anonymise()
        self.assertEqual(report.anonymised, [self.user_.pk])
        user = User.objects.get(pk=self.user_.pk)
        self.assertEqual(user.username, f"former-user-{user.pk}")
        self.assertEqual((user.first_name, user.last_name, user.email), ("", "", ""))
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(list(user.groups.all()), [self.group])
        self.assertEqual(user.terms_acceptances.count(), 1)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.encrypted_mfa_hash)
        self.assertEqual(self.profile.phone, "")
        self.assertFalse(
            SessionStore(session_key=sessions.session_key).exists(sessions.session_key)
        )
        self.assertTrue(other.exists(other.session_key))
        self.assertFalse(AccessAttempt.objects.filter(username="alice").exists())
        self.assertFalse(AccessLog.objects.filter(username="alice").exists())
        row = AccountRetention.objects.get(user_id=user.pk)
        self.assertEqual(row.anonymised_on, NOW.date() + timedelta(days=30))

    def test_a_second_run_changes_nothing_and_counts_nothing(self):
        self.anonymise()
        before = list(AccountRetention.objects.values())
        count = len(mail.outbox)
        with delta(
            "manuspectrum_account_anonymisations_total", outcome="anonymised"
        ) as d:
            report = self.go(NOW + timedelta(days=60))
        self.assertEqual((report.noticed, report.anonymised), ([], []))
        self.assertEqual(d.value, 0)
        self.assertEqual(list(AccountRetention.objects.values()), before)
        self.assertEqual(len(mail.outbox), count)
        self.assertFalse(retention.anonymise(self.user_.pk))

    def edit(self, user_id, **extra):
        return EditLog.objects.create(
            transactionid=uuid.uuid4(),
            userid=str(user_id),
            user_email=extra.pop("user_email", "x@manuspectrum.test"),
            user_username=extra.pop("user_username", "name"),
            user_firstname="First",
            user_lastname="Last",
            **extra,
        )

    def test_the_edit_log_loses_the_email_and_username_but_keeps_the_names(self):
        mine = self.edit(
            self.user_.pk, user_email="alice@manuspectrum.test", user_username="alice"
        )
        theirs = self.edit(
            4242, user_email="bob@manuspectrum.test", user_username="bob"
        )
        self.anonymise()
        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertEqual(mine.user_email, "")
        self.assertEqual(mine.user_username, f"former-user-{self.user_.pk}")
        self.assertEqual((mine.user_firstname, mine.user_lastname), ("First", "Last"))
        self.assertEqual(theirs.user_email, "bob@manuspectrum.test")
        self.assertEqual(theirs.user_username, "bob")

    def test_a_failure_rolls_the_account_back_and_is_counted(self):
        self.go()
        with (
            mock.patch.object(retention, "_end_sessions", side_effect=RuntimeError),
            delta("manuspectrum_account_anonymisations_total", outcome="failed") as d,
        ):
            report = self.go(NOW + timedelta(days=30))
        self.assertEqual(report.failed, [self.user_.pk])
        self.assertEqual(d.value, 1)
        user = User.objects.get(pk=self.user_.pk)
        self.assertEqual(user.username, "alice")
        self.assertTrue(user.is_active)
        self.assertFalse(self.anonymised(user))


class SuperuserTests(RetentionCase):
    def test_a_superuser_is_noticed_and_listed_once_but_never_anonymised(self):
        root = self.user("root", last_login=months_ago(25), is_superuser=True)
        self.go()
        self.assertEqual(len(self.notices()), 1)
        report = self.go(NOW + timedelta(days=30))
        self.assertEqual((report.superusers_due, report.anonymised), ([root.pk], []))
        summaries = [m for m in mail.outbox if m.to == SUMMARY]
        self.assertIn("root", summaries[-1].body)
        again = self.go(NOW + timedelta(days=31))
        self.assertEqual(again.superusers_due, [])
        root.refresh_from_db()
        self.assertEqual(root.username, "root")
        self.assertTrue(root.is_active)
        self.assertFalse(retention.anonymise(root.pk))


class DryRunTests(RetentionCase):
    def test_a_dry_run_changes_and_sends_nothing(self):
        self.user("old", last_login=months_ago(25))
        report = self.go(apply=False)
        self.assertEqual(len(report.noticed), 1)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(AccountRetention.objects.exists())

    def test_the_command_defaults_to_a_dry_run_and_applies_on_request(self):
        user = self.user("old", last_login=months_ago(25))
        out = io.StringIO()
        with mock.patch(
            "manuspectrum.accounts.retention.timezone.now", return_value=NOW
        ):
            call_command("anonymise_inactive_accounts", stdout=out)
            self.assertIn("1 would be notice sent", out.getvalue())
            self.assertIn(f"user {user.pk}", out.getvalue())
            self.assertIn("Dry run", out.getvalue())
            self.assertFalse(AccountRetention.objects.exists())
            call_command("anonymise_inactive_accounts", "--apply", stdout=out)
        self.assertTrue(AccountRetention.objects.filter(noticed_on__isnull=False))

    def test_the_command_refuses_both_flags(self):
        with self.assertRaises(CommandError):
            call_command("anonymise_inactive_accounts", "--apply", "--dry-run")


class MetricsAndScheduleTests(RetentionCase):
    def test_the_counter_and_the_timestamp_follow_the_pass(self):
        self.user(last_login=months_ago(25))
        self.go()
        before = sample("manuspectrum_account_retention_timestamp_seconds")
        with delta(
            "manuspectrum_account_anonymisations_total", outcome="anonymised"
        ) as d:
            self.go(NOW + timedelta(days=30))
        self.assertEqual(d.value, 1)
        self.assertGreater(
            sample("manuspectrum_account_retention_timestamp_seconds"), before
        )

    def test_a_dry_run_leaves_the_gauge_alone(self):
        before = sample("manuspectrum_account_retention_timestamp_seconds")
        self.go(apply=False)
        self.assertEqual(
            sample("manuspectrum_account_retention_timestamp_seconds"), before
        )

    def test_the_pass_is_scheduled_daily_at_0430_europe_paris(self):
        entry = settings.CELERY_BEAT_SCHEDULE["account-retention-pass"]
        self.assertEqual(entry["task"], "manuspectrum.account_retention_pass")
        self.assertEqual(
            (entry["schedule"]._orig_hour, entry["schedule"]._orig_minute), (4, 30)
        )

    def test_the_task_runs_the_pass(self):
        from manuspectrum.tasks import account_retention_pass_task

        self.assertEqual(account_retention_pass_task()["failed"], 0)

    def test_the_settings_are_the_po_decision(self):
        self.assertEqual(settings.ACCOUNT_RETENTION_MONTHS, 24)
        self.assertEqual(settings.ACCOUNT_RETENTION_NOTICE_DAYS, 30)
