"""The User admin as the one place for accounts: list, account section, add form, rubrics.

Usage:
    python manage.py test tests.test_admin_accounts --settings="tests.test_settings" --noinput
"""

from datetime import datetime, time, timedelta

from arches.app.models.models import UserProfile
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth.models import Group, Permission, User
from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from unittest import mock

from manuspectrum.accounts import notices, retention
from manuspectrum.accounts.embargo import LOCAL_TZ, local_today
from manuspectrum.admin import InvitingUserAdmin
from manuspectrum.models import AccountRetention, TermsAcceptance

PASSWORD = "Str0ng!Passphrase-for-tests"
LIST = "admin:auth_user_changelist"


def stored(moment):
    if settings.USE_TZ:
        return moment
    return moment.replace(tzinfo=None)


def enrol(user):
    UserProfile.objects.update_or_create(
        user=user, defaults={"encrypted_mfa_hash": "secret"}
    )


class AdminCase(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox.clear()
        self.client = Client(raise_request_exception=False)
        self.boss = User.objects.create_superuser(
            "boss", "boss@manuspectrum.test", PASSWORD
        )
        self.client.force_login(self.boss)


class ListTests(AdminCase):
    def rows(self, **params):
        response = self.client.get(reverse(LIST), params)
        self.assertEqual(response.status_code, 200)
        return response

    def test_columns_are_the_account_overview(self):
        response = self.rows()
        self.assertEqual(
            list(response.context["cl"].list_display),
            [
                "action_checkbox",
                "username",
                "full_name",
                "email",
                "is_active",
                "two_factor",
                "last_login",
                "planned_anonymisation",
                "is_staff",
                "is_superuser",
            ],
        )

    def test_two_factor_filter_splits_enrolled_from_the_rest(self):
        done = User.objects.create_user("done", "done@manuspectrum.test", PASSWORD)
        User.objects.create_user("todo", "todo@manuspectrum.test", PASSWORD)
        enrol(done)
        yes = self.rows(two_factor="yes").context["cl"].result_list
        no = self.rows(two_factor="no").context["cl"].result_list
        self.assertEqual({u.username for u in yes}, {"done"})
        self.assertIn("todo", {u.username for u in no})
        self.assertNotIn("done", {u.username for u in no})

    def test_filters_offered(self):
        response = self.rows()
        titles = {str(spec.title) for spec in response.context["cl"].filter_specs}
        self.assertTrue(
            {"active", "two-factor authentication", "staff status", "superuser status"}
            <= titles
        )
        self.assertTrue(any("group" in t for t in titles))

    def count_queries(self, users, prefix):
        for i in range(users):
            u = User.objects.create_user(
                f"{prefix}{i}", f"{prefix}{i}@manuspectrum.test", PASSWORD
            )
            if i % 2:
                enrol(u)
            AccountRetention.objects.create(
                user_id=u.pk, noticed_on=local_today(datetime.now(LOCAL_TZ))
            )
        self.rows()
        with CaptureQueriesContext(connection) as queries:
            self.rows()
        return len(
            [
                q
                for q in queries.captured_queries
                if "silk_" not in q["sql"]
                and not q["sql"].startswith(("EXPLAIN", "SAVEPOINT", "RELEASE"))
            ]
        )

    def test_query_count_does_not_grow_with_the_page(self):
        few = self.count_queries(1, "a")
        many = self.count_queries(9, "b")
        self.assertEqual(few, many)


class PlannedAnonymisationTests(AdminCase):
    def setUp(self):
        super().setUp()
        self.today = local_today(datetime.now(LOCAL_TZ))

    def user(self, name, *, idle_months=30, **extra):
        user = User.objects.create_user(name, f"{name}@manuspectrum.test", "x", **extra)
        moment = datetime.now(LOCAL_TZ) - relativedelta(months=idle_months)
        User.objects.filter(pk=user.pk).update(last_login=stored(moment))
        user.refresh_from_db()
        return user

    def test_planned_date_writes_nothing_even_inside_the_notice_period(self):
        user = self.user("late")
        planned = retention.planned_anonymisation(user, None, self.today)
        self.assertEqual(planned, self.today + timedelta(days=30))
        self.assertFalse(AccountRetention.objects.exists())
        self.assertEqual(mail.outbox, [])

    def test_before_the_notice_period_it_is_the_end_of_retention(self):
        user = self.user("early", idle_months=1)
        activity = retention.last_activity_day(user)
        self.assertEqual(
            retention.planned_anonymisation(user, None, self.today),
            retention.due_on(activity),
        )

    def test_a_valid_notice_fixes_the_date_and_a_void_one_does_not(self):
        user = self.user("noticed")
        activity = retention.last_activity_day(user)
        noticed = self.today - timedelta(days=10)
        row = AccountRetention(
            user_id=user.pk, noticed_on=noticed, noticed_for=activity
        )
        self.assertEqual(
            retention.planned_anonymisation(user, row, self.today),
            retention.anonymise_on(activity, noticed),
        )
        row.noticed_for = activity - timedelta(days=5)
        self.assertEqual(
            retention.planned_anonymisation(user, row, self.today),
            retention.anonymise_on(activity, self.today),
        )

    def test_never_for_superusers_anonymous_and_anonymised_accounts(self):
        boss = self.user("chief", is_superuser=True)
        self.assertIsNone(retention.planned_anonymisation(boss, None, self.today))
        anon = User.objects.get(username="anonymous")
        self.assertIsNone(retention.planned_anonymisation(anon, None, self.today))
        gone = self.user("gone")
        row = AccountRetention(user_id=gone.pk, anonymised_on=self.today)
        self.assertIsNone(retention.planned_anonymisation(gone, row, self.today))

    def test_inactive_accounts_follow_the_same_rule(self):
        user = self.user("off", is_active=False)
        self.assertEqual(
            retention.planned_anonymisation(user, None, self.today),
            self.today + timedelta(days=30),
        )

    def test_the_list_shows_the_dates_without_touching_the_ledger(self):
        self.user("late")
        self.user("chief", is_superuser=True)
        response = self.client.get(reverse(LIST))
        self.assertContains(response, "Never (superuser)")
        self.assertFalse(AccountRetention.objects.exists())
        self.assertEqual(mail.outbox, [])

    def run_days(self, user, planned, start):
        """Run the pass each day from *start*; return the first day *user* is anonymised."""
        day = start
        while day <= planned + timedelta(days=2):
            retention.run_pass(
                datetime.combine(day, time(12), LOCAL_TZ), send_mail=False
            )
            if retention.AccountRetention.objects.filter(
                user_id=user.pk, anonymised_on__isnull=False
            ).exists():
                return day
            day += timedelta(days=1)
        return None

    def test_the_pass_anonymises_on_the_date_the_admin_shows(self):
        user = self.user("normal", idle_months=settings.ACCOUNT_RETENTION_MONTHS)
        activity = retention.last_activity_day(user)
        start = retention.notice_on(activity) - timedelta(days=3)
        planned = retention.planned_anonymisation(user, None, start)
        self.assertEqual(self.run_days(user, planned, start), planned)

    def test_the_pass_anonymises_a_noticed_account_on_the_date_shown(self):
        user = self.user("warned", idle_months=settings.ACCOUNT_RETENTION_MONTHS)
        activity = retention.last_activity_day(user)
        noticed = retention.notice_on(activity) + timedelta(days=4)
        AccountRetention.objects.create(
            user_id=user.pk, noticed_on=noticed, noticed_for=activity
        )
        row = AccountRetention.objects.get(user_id=user.pk)
        planned = retention.planned_anonymisation(user, row, noticed)
        self.assertEqual(self.run_days(user, planned, noticed), planned)

    def test_an_anonymised_account_shows_its_date(self):
        user = self.user("done")
        AccountRetention.objects.create(user_id=user.pk, anonymised_on=self.today)
        response = self.client.get(reverse(LIST))
        self.assertContains(response, "Anonymised on")


class ChangePageTests(AdminCase):
    def test_account_section_is_read_only_and_complete(self):
        user = User.objects.create_user(
            "inv", "inv@manuspectrum.test", None, first_name="In", last_name="Vited"
        )
        TermsAcceptance.objects.create(user=user, version="2026-10")
        response = self.client.get(reverse("admin:auth_user_change", args=[user.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Can be invited: no password yet.")
        self.assertContains(response, "2026-10")
        profile = UserProfile.objects.get(user=user)
        self.assertContains(
            response,
            reverse("admin:models_userprofile_change", args=[profile.pk]),
        )
        self.assertContains(response, "Planned anonymisation")

    def test_anonymous_gets_a_reason_of_its_own(self):
        anon = User.objects.get(username="anonymous")
        response = self.client.get(reverse("admin:auth_user_change", args=[anon.pk]))
        self.assertContains(response, "system account for visitors")

    def test_a_superuser_can_be_made_from_the_admin(self):
        self.client.post(
            reverse("admin:auth_user_add"),
            {"username": "chief", "email": "chief@manuspectrum.test"},
        )
        user = User.objects.get(username="chief")
        response = self.client.post(
            reverse("admin:auth_user_change", args=[user.pk]),
            {
                "username": "chief",
                "email": "chief@manuspectrum.test",
                "first_name": "",
                "last_name": "",
                "is_active": "on",
                "is_staff": "on",
                "is_superuser": "on",
                "date_joined_0": "2026-01-01",
                "date_joined_1": "10:00:00",
            },
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_superuser and user.is_staff)


class TwoFactorActionTests(AdminCase):
    def run_action(self, action, *users):
        return self.client.post(
            reverse(LIST),
            {"action": action, "_selected_action": [u.pk for u in users]},
            follow=True,
        )

    def test_reset_from_the_user_list_clears_the_secret_and_mails_the_link(self):
        alice = User.objects.create_user("alice", "alice@manuspectrum.test", PASSWORD)
        enrol(alice)
        self.run_action("reset_two_factor", alice)
        self.assertIsNone(UserProfile.objects.get(user=alice).encrypted_mfa_hash)
        self.assertEqual(len(mail.outbox), 1)

    def test_an_account_without_a_profile_is_skipped_and_none_is_created(self):
        bob = User.objects.create_user("bob", "bob@manuspectrum.test", PASSWORD)
        UserProfile.objects.filter(user=bob).delete()
        self.run_action("send_enrolment_link", bob)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(UserProfile.objects.filter(user=bob).exists())

    def test_actions_are_superuser_only(self):
        staff = User.objects.create_user(
            "staffer", "s@manuspectrum.test", PASSWORD, is_staff=True
        )
        staff.user_permissions.add(
            *Permission.objects.filter(
                codename__in=("change_user", "view_user", "delete_user")
            )
        )
        alice = User.objects.create_user("alice", "alice@manuspectrum.test", PASSWORD)
        enrol(alice)
        self.client.force_login(staff)
        response = self.client.get(reverse(LIST))
        names = [
            name for name, _ in response.context["action_form"].fields["action"].choices
        ]
        self.assertNotIn("reset_two_factor", names)
        self.assertNotIn("send_enrolment_link", names)
        self.run_action("reset_two_factor", alice)
        self.assertEqual(
            UserProfile.objects.get(user=alice).encrypted_mfa_hash, "secret"
        )
        self.assertEqual(mail.outbox, [])


class RubricTests(AdminCase):
    def test_user_profile_is_off_the_index_but_reachable(self):
        index = self.client.get(reverse("admin:index"))
        self.assertNotContains(index, "User profiles")
        self.assertNotContains(index, reverse("admin:models_userprofile_changelist"))
        self.assertEqual(
            self.client.get(reverse("admin:models_userprofile_changelist")).status_code,
            200,
        )

    def test_terms_acceptance_is_named_in_french(self):
        from django.utils import translation

        with translation.override("fr"):
            self.assertEqual(
                str(TermsAcceptance._meta.verbose_name_plural),
                "acceptations des conditions",
            )


class AddFormTests(AdminCase):
    URL_NAME = "admin:auth_user_add"

    def post(self, **extra):
        data = {
            "username": "newbie",
            "email": "newbie@manuspectrum.test",
            "first_name": "New",
            "last_name": "Bie",
            "invite_now": "on",
        }
        data.update(extra)
        data = {k: v for k, v in data.items() if v is not None}
        return self.client.post(reverse(self.URL_NAME), data)

    def test_form_has_no_password_fields(self):
        response = self.client.get(reverse(self.URL_NAME))
        fields = list(response.context["adminform"].form.fields)
        self.assertEqual(
            fields,
            ["username", "email", "first_name", "last_name", "groups", "invite_now"],
        )
        self.assertTrue(response.context["adminform"].form.fields["invite_now"].initial)

    def test_creates_an_unusable_password_account_and_invites_after_commit(self):
        group = Group.objects.create(name="Editors")
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.post(groups=[group.pk])
        user = User.objects.get(username="newbie")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(list(user.groups.all()), [group])
        self.assertRedirects(
            response,
            reverse("admin:auth_user_change", args=[user.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(mail.outbox, [])
        for callback in callbacks:
            callback()
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertEqual(mail.outbox[0].to, ["newbie@manuspectrum.test"])
        self.assertLess(
            body.index("Activate my account"), body.index("Activer mon compte")
        )

    def test_no_invitation_when_unticked(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post(invite_now=None)
        self.assertTrue(User.objects.filter(username="newbie").exists())
        self.assertEqual(mail.outbox, [])

    def test_duplicate_email_is_refused_whatever_its_case(self):
        User.objects.create_user("old", "Newbie@Manuspectrum.test", PASSWORD)
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="newbie").exists())
        self.assertIn("email", response.context["adminform"].form.errors)

    def test_email_is_required(self):
        response = self.post(email="")
        self.assertIn("email", response.context["adminform"].form.errors)

    def test_resend_action_still_works(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post(invite_now=None)
        user = User.objects.get(username="newbie")
        self.client.post(
            reverse(LIST),
            {"action": "send_invitation", "_selected_action": [user.pk]},
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_a_failed_invitation_mail_leaves_the_account_and_reports_it(self):
        with (
            mock.patch(
                "manuspectrum.admin.activation.send_invitation",
                return_value=notices.FAILED,
            ),
            mock.patch(
                "manuspectrum.admin.transaction.on_commit", side_effect=lambda f: f()
            ),
        ):
            response = self.post()
        self.assertEqual(response.status_code, 302)
        follow = self.client.get(response["Location"])
        self.assertEqual(follow.status_code, 200)
        self.assertTrue(User.objects.filter(username="newbie").exists())
        self.assertContains(follow, "could not be sent")
