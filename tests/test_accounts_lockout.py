"""Sign-in lockout and login records (PP-4, T3).

Arches calls ``authenticate()`` without a request in most of its views; these
tests go through the real routes, not through the backend.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from manuspectrum import tasks
from manuspectrum.accounts import lockout
from tests.observability_helpers import delta, sample

PASSWORD = "Str0ng!Passphrase-for-tests"
WRONG = "not-the-password-Zq81"
IP_A = "203.0.113.10"
IP_B = "203.0.113.20"


def post(client, path, ip=IP_A, **data):
    return client.post(path, data, HTTP_X_REAL_IP=ip, REMOTE_ADDR="10.0.0.1")


@override_settings(RATELIMIT_ENABLE=False)
class LockoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            "alice", "alice@manuspectrum.test", PASSWORD, is_staff=True
        )

    def setUp(self):
        self.client = Client(raise_request_exception=False)

    def fail(self, times, path="/en/auth/", username="alice", ip=IP_A):
        for _ in range(times):
            post(self.client, path, ip=ip, username=username, password=WRONG)

    def signed_in(self):
        return "_auth_user_id" in self.client.session

    def test_the_sixth_attempt_is_locked_even_with_the_right_password(self):
        self.fail(5)
        response = post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many failed attempts", status_code=429)
        self.assertFalse(self.signed_in())

    def test_the_lockout_page_is_translated(self):
        self.fail(5, path="/fr/auth/")
        response = post(self.client, "/fr/auth/", username="alice", password=PASSWORD)
        self.assertContains(response, "Erreur 429", status_code=429)

    def test_the_lockout_page_gives_the_duration(self):
        self.fail(5)
        response = post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertContains(response, "locked for 15 minutes", status_code=429)

    def test_the_lockout_page_gives_the_duration_in_french(self):
        self.fail(5, path="/fr/auth/")
        response = post(self.client, "/fr/auth/", username="alice", password=PASSWORD)
        self.assertContains(response, "pendant 15 minutes", status_code=429)

    def test_without_a_cool_off_the_lockout_page_gives_no_duration(self):
        with override_settings(AXES_COOLOFF_TIME=None):
            self.fail(5)
            response = post(
                self.client, "/en/auth/", username="alice", password=PASSWORD
            )
        self.assertContains(response, "Too many failed attempts", status_code=429)
        self.assertContains(response, "Contact the team to unlock it", status_code=429)
        self.assertNotContains(response, "locked for", status_code=429)

    def test_whole_minutes_is_none_for_anything_but_a_timedelta(self):
        from manuspectrum.templatetags.account_tags import whole_minutes

        self.assertIsNone(whole_minutes(""))
        self.assertIsNone(whole_minutes(None))
        self.assertEqual(whole_minutes(timedelta(seconds=10)), 1)
        self.assertEqual(whole_minutes(timedelta(minutes=15)), 15)

    def test_four_failures_do_not_lock(self):
        self.fail(4)
        response = post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.signed_in())

    def test_the_same_account_from_another_address_is_not_locked(self):
        self.fail(5)
        response = post(
            self.client, "/en/auth/", ip=IP_B, username="alice", password=PASSWORD
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.signed_in())

    def test_another_account_from_the_same_address_is_not_locked(self):
        User.objects.create_user("bob", "bob@manuspectrum.test", PASSWORD)
        self.fail(5)
        response = post(self.client, "/en/auth/", username="bob", password=PASSWORD)
        self.assertEqual(response.status_code, 302)

    def test_the_lock_ends_after_the_cool_off(self):
        self.fail(5)
        AccessAttempt.objects.update(
            attempt_time=timezone.now() - timedelta(minutes=16)
        )
        response = post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertEqual(response.status_code, 302)

    def test_attempts_made_while_locked_do_not_extend_the_lock(self):
        self.fail(5)
        started = timezone.now() - timedelta(minutes=10)
        AccessAttempt.objects.update(attempt_time=started)
        self.fail(3)
        post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertEqual(AccessAttempt.objects.get().attempt_time, started)
        AccessAttempt.objects.update(
            attempt_time=timezone.now() - timedelta(minutes=16)
        )
        response = post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertEqual(response.status_code, 302)

    def test_the_client_address_is_the_one_nginx_forwards(self):
        self.fail(1)
        attempt = AccessAttempt.objects.get()
        self.assertEqual(attempt.ip_address, IP_A)

    def test_the_admin_login_counts(self):
        self.fail(5, path="/en/admin/login/")
        response = post(
            self.client, "/en/admin/login/", username="alice", password=PASSWORD
        )
        self.assertEqual(response.status_code, 429)

    def test_the_other_arches_credential_routes_count(self):
        for path in (
            "/en/auth/user_profile",
            "/en/auth/server_settings",
            "/en/two-factor-authentication-login",
        ):
            with self.subTest(path=path):
                AccessAttempt.objects.all().delete()
                self.fail(5, path=path)
                response = post(self.client, path, username="alice", password=PASSWORD)
                self.assertEqual(response.status_code, 429)
                self.assertFalse(self.signed_in())

    def test_lock_taken_on_one_route_holds_on_another(self):
        self.fail(5, path="/en/auth/user_profile")
        response = post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertEqual(response.status_code, 429)

    def test_user_profile_without_a_username_is_not_counted(self):
        self.client.force_login(self.user)
        for _ in range(7):
            response = post(self.client, "/en/auth/user_profile")
            self.assertEqual(response.status_code, 200)
        self.assertEqual(AccessAttempt.objects.count(), 0)

    def test_valid_credentials_still_work_on_every_route(self):
        for path in (
            "/en/auth/user_profile",
            "/en/auth/server_settings",
        ):
            with self.subTest(path=path):
                response = post(self.client, path, username="alice", password=PASSWORD)
                self.assertEqual(response.status_code, 200)

    def test_changing_the_password_still_works(self):
        self.client.force_login(self.user)
        new = "An0ther!Passphrase-123"
        response = self.client.post(
            "/en/auth/password",
            {"old_password": PASSWORD, "new_password": new, "new_password2": new},
            HTTP_X_REAL_IP=IP_A,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["success"])

    def test_username_and_email_share_one_counter(self):
        self.fail(3, username="alice")
        self.fail(2, username="Alice@Manuspectrum.test")
        response = post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            list(AccessAttempt.objects.values_list("username", flat=True)),
            ["alice"],
        )

    def test_the_lock_by_email_holds_for_the_user_name(self):
        self.fail(5, username="alice@manuspectrum.test")
        response = post(
            self.client,
            "/en/auth/",
            username="alice@manuspectrum.test",
            password=PASSWORD,
        )
        self.assertEqual(response.status_code, 429)

    def test_a_success_resets_the_counter(self):
        self.fail(4)
        post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.client.logout()
        self.fail(4)
        response = post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        self.assertEqual(response.status_code, 302)

    def test_an_unknown_account_is_limited_too(self):
        self.fail(5, username="nobody")
        response = post(self.client, "/en/auth/", username="nobody", password=WRONG)
        self.assertEqual(response.status_code, 429)

    def test_the_login_record_has_the_address_and_no_password(self):
        post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        record = AccessLog.objects.get()
        self.assertEqual((record.username, record.ip_address), ("alice", IP_A))
        self.fail(1)
        failure = AccessFailureLog.objects.get()
        self.assertEqual((failure.username, failure.ip_address), ("alice", IP_A))
        for row in AccessAttempt.objects.all():
            self.assertNotIn(WRONG, row.post_data)
        for text in (
            *AccessLog.objects.values_list("user_agent", "http_accept", "path_info"),
            *AccessFailureLog.objects.values_list(
                "user_agent", "http_accept", "path_info"
            ),
        ):
            self.assertNotIn(PASSWORD, "".join(map(str, text)))

    def test_no_log_record_contains_the_password(self):
        with self.assertLogs(level="DEBUG") as captured:
            self.fail(5)
            post(self.client, "/en/auth/", username="alice", password=PASSWORD)
        text = "\n".join(record.getMessage() for record in captured.records)
        self.assertNotIn(WRONG, text)
        self.assertNotIn(PASSWORD, text)


@override_settings(RATELIMIT_ENABLE=False)
class LockoutMetricTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user("carol", "carol@manuspectrum.test", PASSWORD)

    def setUp(self):
        self.client = Client(raise_request_exception=False)

    def test_a_lockout_is_counted_once_at_the_transition(self):
        with delta("manuspectrum_auth_lockouts_total") as locks:
            for _ in range(4):
                post(self.client, "/en/auth/", username="carol", password=WRONG)
            post(self.client, "/en/auth/", username="carol", password=WRONG)
            for _ in range(3):
                post(self.client, "/en/auth/", username="carol", password=WRONG)
                post(self.client, "/en/auth/", username="carol", password=PASSWORD)
        self.assertEqual(locks.value, 1)

    def test_four_failures_are_not_a_lockout(self):
        with delta("manuspectrum_auth_lockouts_total") as locks:
            for _ in range(4):
                post(self.client, "/en/auth/", username="carol", password=WRONG)
        self.assertEqual(locks.value, 0)

    def test_failures_still_count_as_login_failures(self):
        with delta("manuspectrum_auth_logins_total", outcome="failure") as failed:
            post(self.client, "/en/auth/", username="carol", password=WRONG)
        self.assertEqual(failed.value, 1)


class OutsideAViewTests(TestCase):
    def test_authenticate_without_a_request_outside_a_view_still_works(self):
        User.objects.create_user("dave", "dave@manuspectrum.test", PASSWORD)
        user = authenticate(username="dave", password=PASSWORD)
        self.assertEqual(user.username, "dave")
        self.assertIsNone(authenticate(username="dave", password=WRONG))
        self.assertEqual(AccessAttempt.objects.count(), 0)

    def test_the_client_login_helper_still_works(self):
        User.objects.create_user("erin", "erin@manuspectrum.test", PASSWORD)
        self.assertTrue(Client().login(username="erin", password=PASSWORD))


class CurrentRequestTests(TestCase):
    def test_eight_threads_each_see_their_own_request(self):
        factory = RequestFactory()
        barrier = threading.Barrier(8)
        seen = {}

        def serve(number):
            request = factory.get(f"/r/{number}")

            def view(request):
                barrier.wait(timeout=10)
                seen[number] = lockout.current_request()
                barrier.wait(timeout=10)
                return HttpResponse("ok")

            lockout.CurrentRequestMiddleware(view)(request)
            return request

        with ThreadPoolExecutor(8) as pool:
            requests = list(pool.map(serve, range(8)))
        for number, request in enumerate(requests):
            self.assertIs(seen[number], request)
        self.assertIsNone(lockout.current_request())

    def test_the_request_is_released_when_the_view_raises(self):
        def view(request):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            lockout.CurrentRequestMiddleware(view)(RequestFactory().get("/"))
        self.assertIsNone(lockout.current_request())


class PruneTests(TestCase):
    NOW = timezone.datetime(2026, 10, 12, 12, 0, 0)

    def make(self, age_days):
        when = self.NOW - timedelta(days=age_days)
        common = dict(
            username=f"u{age_days}",
            ip_address=IP_A,
            user_agent="ua",
            http_accept="*/*",
            path_info="/en/auth/",
            attempt_time=when,
        )
        AccessLog.objects.create(**common)
        AccessFailureLog.objects.create(**common, locked_out=False)
        AccessAttempt.objects.create(
            **common, get_data="", post_data="", failures_since_start=1
        )
        for model in (AccessLog, AccessFailureLog, AccessAttempt):
            model.objects.filter(username=common["username"]).update(attempt_time=when)

    def test_rows_older_than_six_months_go_and_younger_stay(self):
        self.assertEqual(settings.LOGIN_RECORDS_RETENTION_DAYS, 183)
        self.make(184)
        self.make(182)
        with patch.object(timezone, "now", return_value=self.NOW):
            deleted = lockout.prune_login_records()
        self.assertEqual(deleted, 3)
        for model in (AccessLog, AccessFailureLog, AccessAttempt):
            self.assertEqual(
                list(model.objects.values_list("username", flat=True)), ["u182"]
            )

    def test_the_task_stamps_its_success_time(self):
        before = sample("manuspectrum_login_records_prune_timestamp_seconds")
        tasks.prune_login_records_task()
        self.assertGreater(
            sample("manuspectrum_login_records_prune_timestamp_seconds"), before
        )

    def test_the_beat_runs_it_daily(self):
        entry = settings.CELERY_BEAT_SCHEDULE["prune-login-records"]
        self.assertEqual(entry["task"], "manuspectrum.prune_login_records")
        self.assertEqual(entry["schedule"], 24 * 3600)
