import json
import tempfile
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from manuspectrum.models import SiteNotice, site_now

START = "2026-11-03T20:00"
END = "2026-11-03T20:30"


class SiteNoticeCommandTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.snapshot = Path(self.directory.name, "notice.json")
        override = override_settings(SITE_NOTICE_SNAPSHOT_DIR=self.directory.name)
        override.enable()
        self.addCleanup(override.disable)

    def run_command(self, *args):
        out = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command("site_notice", *args, stdout=out)
        return out.getvalue().strip()

    def snapshot_notices(self):
        return json.loads(self.snapshot.read_text(encoding="utf-8"))["notices"]

    def plan(self, *extra):
        output = self.run_command("plan", "--start", START, "--end", END, *extra)
        self.assertRegex(output, r"^id=\d+$")
        return SiteNotice.objects.get(pk=int(output.split("=")[1]))

    def test_plan_creates_a_maintenance_event_and_prints_its_id(self):
        notice = self.plan()
        self.assertEqual(notice.kind, SiteNotice.MAINTENANCE)
        self.assertEqual(notice.display, SiteNotice.EVENT)
        self.assertEqual(
            notice.text_en,
            "Scheduled update of the site: brief interruption of service.",
        )
        self.assertEqual(
            notice.text_fr, "Mise à jour du site : brève interruption de service."
        )
        self.assertEqual(notice.starts_at, datetime(2026, 11, 3, 20, 0))
        self.assertEqual(notice.ends_at, datetime(2026, 11, 3, 20, 30))
        self.assertEqual(notice.reminders, "7d 1d 1h 10m")

    def test_plan_takes_the_reminders_given(self):
        self.assertEqual(self.plan("--reminders", "10m 1d 1h").reminders, "1d 1h 10m")

    def test_plan_refreshes_the_snapshot(self):
        notice = self.plan()
        self.assertEqual([n["id"] for n in self.snapshot_notices()], [notice.pk])

    def test_plan_refuses_bad_input_and_creates_nothing(self):
        bad = [
            ("--start", START, "--end", START),
            ("--start", START, "--end", "2026-11-03 20:30"),
            ("--start", "2026-13-03T20:00", "--end", END),
            ("--start", START, "--end", END, "--reminders", "soon"),
            ("--start", START, "--end", END, "--reminders", "100d"),
        ]
        for args in bad:
            with self.subTest(args=args):
                with self.assertRaises(CommandError):
                    call_command("site_notice", "plan", *args, stdout=StringIO())
        self.assertFalse(SiteNotice.objects.exists())

    def test_end_moves_the_end(self):
        notice = self.plan()
        self.run_command("end", str(notice.pk), "--at", "2026-11-03T20:10")
        notice.refresh_from_db()
        self.assertEqual(notice.ends_at, datetime(2026, 11, 3, 20, 10))
        self.assertEqual(len(self.snapshot_notices()), 1)

    def test_end_extends_by_a_relative_duration_from_now(self):
        notice = self.plan()
        SiteNotice.objects.filter(pk=notice.pk).update(
            starts_at=site_now() - timedelta(hours=1)
        )
        before = site_now()
        self.run_command("end", str(notice.pk), "--at", "+24h")
        notice.refresh_from_db()
        delta = notice.ends_at - before
        self.assertLess(abs(delta - timedelta(hours=24)), timedelta(minutes=1))

    def test_end_before_the_start_withdraws_the_notice(self):
        notice = self.plan()
        self.assertEqual(self.run_command("end", str(notice.pk), "--at", "now"), "")
        self.assertFalse(SiteNotice.objects.filter(pk=notice.pk).exists())
        self.assertEqual(self.snapshot_notices(), [])

    def test_end_of_an_unknown_id_is_absent(self):
        self.assertEqual(self.run_command("end", "999999"), "absent")

    def test_withdraw_deletes_and_is_idempotent(self):
        notice = self.plan()
        self.assertEqual(self.run_command("withdraw", str(notice.pk)), "")
        self.assertEqual(self.snapshot_notices(), [])
        self.assertEqual(self.run_command("withdraw", str(notice.pk)), "absent")

    def test_ids_and_times_are_parsed_strictly(self):
        for args in (
            ("withdraw", "1; drop"),
            ("withdraw", "-1"),
            ("end", "1", "--at", "tomorrow"),
            ("end", "1", "--at", "+24"),
        ):
            with self.subTest(args=args):
                with self.assertRaises(CommandError):
                    call_command("site_notice", *args, stdout=StringIO())
