import json
import os
import stat
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.core.checks import Warning as CheckWarning
from django.test import SimpleTestCase, TestCase, override_settings

from manuspectrum import checks
from manuspectrum.models import SiteNotice, site_now
from manuspectrum.views import site_notice
from manuspectrum.views.site_notice import build_payload, write_snapshot


def make(**overrides):
    start = site_now() + timedelta(days=1)
    fields = {
        "text_en": "Down for maintenance.",
        "text_fr": "En maintenance.",
        "starts_at": start,
        "ends_at": start + timedelta(hours=1),
    }
    fields.update(overrides)
    return SiteNotice.objects.create(**fields)


class SnapshotTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name, "notice.json")

    def test_without_a_directory_nothing_is_written(self):
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=""):
            make()
            self.assertIsNone(write_snapshot(build_payload()))
        self.assertEqual(os.listdir(self.directory.name), [])

    def test_the_file_equals_the_payload(self):
        make()
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=self.directory.name):
            self.assertEqual(write_snapshot(build_payload()), str(self.path))
        self.assertEqual(
            json.loads(self.path.read_text(encoding="utf-8")), build_payload()
        )
        self.assertEqual(os.listdir(self.directory.name), ["notice.json"])

    def test_the_file_replaces_the_previous_one_atomically(self):
        self.path.write_text("old", encoding="utf-8")
        calls = []
        real = os.replace

        def replace(source, target):
            calls.append((source, target, Path(source).read_text(encoding="utf-8")))
            real(source, target)

        make()
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=self.directory.name):
            with mock.patch.object(site_notice.os, "replace", replace):
                write_snapshot(build_payload())
        ((source, target, content),) = calls
        self.assertEqual(Path(source).parent, self.path.parent)
        self.assertTrue(Path(source).name.startswith("notice."))
        self.assertEqual(target, str(self.path))
        self.assertEqual(json.loads(content), build_payload())
        self.assertNotEqual(self.path.read_text(encoding="utf-8"), "old")

    def test_temporary_names_are_unique_and_the_file_is_world_readable(self):
        make()
        names = []
        real = os.replace

        def replace(source, target):
            names.append(source)
            real(source, target)

        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=self.directory.name):
            with mock.patch.object(site_notice.os, "replace", replace):
                write_snapshot(build_payload())
                write_snapshot(build_payload())
        self.assertEqual(len(set(names)), 2)
        self.assertEqual(os.listdir(self.directory.name), ["notice.json"])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o644)

    def test_a_failed_write_removes_its_temporary_file(self):
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=self.directory.name):
            with mock.patch.object(site_notice.os, "replace", side_effect=OSError):
                with self.assertLogs(site_notice.logger, "ERROR"):
                    write_snapshot(build_payload())
        self.assertEqual(os.listdir(self.directory.name), [])

    def test_a_failed_write_keeps_the_previous_file(self):
        self.path.write_text("old", encoding="utf-8")
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=self.directory.name):
            with mock.patch.object(site_notice.os, "replace", side_effect=OSError):
                with self.assertLogs(site_notice.logger, "ERROR"):
                    self.assertIsNone(write_snapshot(build_payload()))
        self.assertEqual(self.path.read_text(encoding="utf-8"), "old")

    def test_an_unwritable_directory_is_logged_and_not_raised(self):
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR="/nonexistent/dir"):
            with self.assertLogs(site_notice.logger, "ERROR"):
                self.assertIsNone(write_snapshot(build_payload()))

    def test_saving_rewrites_the_snapshot_on_commit(self):
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=self.directory.name):
            with self.captureOnCommitCallbacks(execute=True):
                make(text_en="first")
            first = json.loads(self.path.read_text(encoding="utf-8"))
            with self.captureOnCommitCallbacks(execute=True):
                SiteNotice.objects.get().delete()
            second = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(first["notices"][0]["text"]["en"], "first")
        self.assertEqual(second["notices"], [])

    def test_nothing_is_written_before_the_commit(self):
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=self.directory.name):
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                make()
        self.assertFalse(self.path.exists())
        self.assertTrue(callbacks)

    def test_command_reports_the_path(self):
        make()
        out = StringIO()
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=self.directory.name):
            call_command("site_notice_snapshot", stdout=out)
        self.assertEqual(out.getvalue().strip(), str(self.path))
        self.assertTrue(self.path.exists())

    def test_command_says_disabled_without_a_directory(self):
        out = StringIO()
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=""):
            call_command("site_notice_snapshot", stdout=out)
        self.assertEqual(out.getvalue().strip(), "disabled")


class SnapshotCheckTests(SimpleTestCase):
    def run_check(self, directory):
        with override_settings(SITE_NOTICE_SNAPSHOT_DIR=directory):
            return checks.check_site_notice_snapshot_dir(None, None)

    def test_disabled_and_writable_directories_pass(self):
        self.assertEqual(self.run_check(""), [])
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.run_check(directory), [])

    def test_a_missing_directory_warns(self):
        (message,) = self.run_check("/nonexistent/dir")
        self.assertIsInstance(message, CheckWarning)
        self.assertEqual(message.id, "manuspectrum.W005")

    def test_a_read_only_directory_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            os.chmod(directory, stat.S_IRUSR | stat.S_IXUSR)
            try:
                if os.access(directory, os.W_OK):
                    self.skipTest("running as a user that ignores permissions")
                self.assertEqual(self.run_check(directory)[0].id, "manuspectrum.W005")
            finally:
                os.chmod(directory, stat.S_IRWXU)

    def test_the_container_profile_reads_the_directory_from_the_environment(self):
        source = Path(settings.APP_ROOT, "settings_docker.py").read_text()
        self.assertIn(
            'SITE_NOTICE_SNAPSHOT_DIR = get_optional_env_variable("SITE_NOTICE_SNAPSHOT_DIR", "")',
            source,
        )
