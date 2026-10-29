"""The project runs on Paris time, with naive datetimes (Arches' ``USE_TZ = False``).

Usage:
    python manage.py test tests.test_time_zone --settings="tests.test_settings"
"""

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.test import TestCase
from django.utils import timezone


class TimeZoneTests(TestCase):
    def test_the_project_zone_is_paris_and_datetimes_are_naive(self):
        self.assertEqual(settings.TIME_ZONE, "Europe/Paris")
        self.assertFalse(settings.USE_TZ)

    def test_the_project_zone_is_the_one_of_the_scheduler_and_the_notices(self):
        self.assertEqual(settings.CELERY_TIMEZONE, settings.TIME_ZONE)
        self.assertEqual(settings.SITE_NOTICE_TIME_ZONE, settings.TIME_ZONE)

    def test_the_process_and_the_database_session_follow_it(self):
        self.assertEqual(os.environ["TZ"], "Europe/Paris")
        self.assertIn(time.tzname[0], ("CET", "CEST"))
        with connection.cursor() as cursor:
            cursor.execute("SHOW TIME ZONE")
            self.assertEqual(cursor.fetchone()[0], "Europe/Paris")

    def test_now_is_the_paris_wall_clock_without_an_offset(self):
        now = timezone.now()
        self.assertIsNone(now.tzinfo)
        paris = datetime.now(ZoneInfo("Europe/Paris")).replace(tzinfo=None)
        self.assertLess(abs((paris - now).total_seconds()), 5)
