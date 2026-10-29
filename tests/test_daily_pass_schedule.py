"""Beat never catches up a daily personal-data pass older than two hours.

python manage.py test tests.test_daily_pass_schedule --settings="tests.test_settings"
"""

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from celery.schedules import crontab
from django.conf import settings
from django.test import SimpleTestCase

from manuspectrum.celery import app

PARIS = ZoneInfo("Europe/Paris")
PASSES = {
    "workflow-cleanup-pass": (3, 30),
    "account-retention-pass": (4, 30),
    "embargo-pass": (6, 0),
}


def paris(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=PARIS)


def utc(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=dt_timezone.utc)


class SettingsTests(SimpleTestCase):
    def test_beat_refuses_a_crontab_run_older_than_two_hours(self):
        self.assertEqual(settings.CELERY_BEAT_CRON_STARTING_DEADLINE, 7200)
        self.assertEqual(app.conf.beat_cron_starting_deadline, 7200)

    def test_the_passes_are_crontabs_whose_message_expires_after_two_hours(self):
        for name, (hour, minute) in PASSES.items():
            with self.subTest(entry=name):
                entry = settings.CELERY_BEAT_SCHEDULE[name]
                self.assertIsInstance(entry["schedule"], crontab)
                self.assertEqual(
                    (entry["schedule"]._orig_hour, entry["schedule"]._orig_minute),
                    (hour, minute),
                )
                self.assertEqual(entry["options"], {"expires": 7200})


class CatchUpTests(SimpleTestCase):
    """The real ``crontab.is_due`` of Celery, with the settings' deadline."""

    def due(self, name, last_run_at, now):
        entry = settings.CELERY_BEAT_SCHEDULE[name]["schedule"]
        schedule = crontab(
            minute=entry._orig_minute,
            hour=entry._orig_hour,
            nowfun=lambda: now.astimezone(PARIS),
            app=app,
        )
        return schedule.is_due(last_run_at.astimezone(PARIS)).is_due

    def test_a_start_hours_after_a_missed_pass_does_not_catch_it_up(self):
        for name, (hour, minute) in PASSES.items():
            with self.subTest(entry=name):
                yesterday = paris(2026, 10, 12, hour, minute, 5)
                self.assertFalse(self.due(name, yesterday, paris(2026, 10, 13, 13, 46)))

    def test_the_pass_runs_at_its_time_and_up_to_two_hours_late(self):
        for name, (hour, minute) in PASSES.items():
            with self.subTest(entry=name):
                yesterday = paris(2026, 10, 12, hour, minute, 5)
                on_time = paris(2026, 10, 13, hour, minute, 10)
                self.assertTrue(self.due(name, yesterday, on_time))
                late = on_time + timedelta(minutes=119)
                self.assertTrue(self.due(name, yesterday, late))
                self.assertFalse(
                    self.due(name, yesterday, on_time + timedelta(minutes=121))
                )

    def test_after_a_refused_catch_up_the_next_night_runs(self):
        two_days_ago = paris(2026, 10, 11, 3, 30, 5)
        self.assertTrue(
            self.due(
                "workflow-cleanup-pass", two_days_ago, paris(2026, 10, 13, 3, 30, 10)
            )
        )

    def test_the_autumn_clock_change_counts_real_hours(self):
        # 2026-10-25: 03:00 CEST becomes 02:00 CET; 03:30 CET is 02:30 UTC.
        last = paris(2026, 10, 24, 3, 30, 5)
        self.assertTrue(
            self.due("workflow-cleanup-pass", last, utc(2026, 10, 25, 4, 20))
        )
        self.assertFalse(
            self.due("workflow-cleanup-pass", last, utc(2026, 10, 25, 4, 40))
        )

    def test_the_spring_clock_change_counts_real_hours(self):
        # 2027-03-28: 02:00 CET becomes 03:00 CEST; 03:30 CEST is 01:30 UTC.
        last = paris(2027, 3, 27, 3, 30, 5)
        self.assertTrue(
            self.due("workflow-cleanup-pass", last, utc(2027, 3, 28, 3, 20))
        )
        self.assertFalse(
            self.due("workflow-cleanup-pass", last, utc(2027, 3, 28, 3, 40))
        )
