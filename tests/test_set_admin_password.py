import io
import os
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

PASSWORD = "correct-horse-battery-staple-42"


class SetAdminPasswordTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.user, _ = self.User.objects.get_or_create(username="admin")
        self.user.set_password("admin")
        self.user.save()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, content, name="admin_password"):
        path = Path(self.dir.name) / name
        path.write_text(content, encoding="utf-8")
        return str(path)

    def run_command(self, *args):
        out, err = io.StringIO(), io.StringIO()
        try:
            call_command("set_admin_password", *args, stdout=out, stderr=err)
        finally:
            self.output = out.getvalue() + err.getvalue()

    def test_sets_the_password_of_admin(self):
        self.run_command("--password-file", self.write(PASSWORD))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertFalse(self.user.check_password("admin"))

    def test_trailing_newline_is_stripped(self):
        self.run_command("--password-file", self.write(PASSWORD + "\n"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_reads_the_path_from_the_environment_by_default(self):
        old = os.environ.get("ADMIN_PASSWORD_FILE")
        os.environ["ADMIN_PASSWORD_FILE"] = self.write(PASSWORD)
        self.addCleanup(
            lambda: (
                os.environ.pop("ADMIN_PASSWORD_FILE", None)
                if old is None
                else os.environ.__setitem__("ADMIN_PASSWORD_FILE", old)
            )
        )
        self.run_command()
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_refuses_an_empty_file(self):
        with self.assertRaises(CommandError):
            self.run_command("--password-file", self.write("\n"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("admin"))

    def test_refuses_a_short_password(self):
        with self.assertRaises(CommandError):
            self.run_command("--password-file", self.write("short"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("admin"))

    def test_refuses_a_missing_file(self):
        with self.assertRaises(CommandError):
            self.run_command("--password-file", str(Path(self.dir.name) / "nope"))

    def test_refuses_when_no_path_is_given(self):
        old = os.environ.pop("ADMIN_PASSWORD_FILE", None)
        if old is not None:
            self.addCleanup(os.environ.__setitem__, "ADMIN_PASSWORD_FILE", old)
        with self.assertRaises(CommandError):
            self.run_command()

    def test_refuses_a_missing_user(self):
        with self.assertRaises(CommandError):
            self.run_command(
                "--password-file", self.write(PASSWORD), "--username", "nobody"
            )

    def test_check_default_exits_3_on_the_default_password(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_command("--check-default")
        self.assertEqual(raised.exception.code, 3)
        self.assertNotIn("admin'", self.output.replace("'admin'", ""))

    def test_check_default_passes_once_changed(self):
        self.user.set_password(PASSWORD)
        self.user.save()
        self.run_command("--check-default")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_check_default_passes_without_the_user(self):
        self.User.objects.filter(username="admin").delete()
        self.run_command("--check-default")

    def test_never_echoes_the_password(self):
        self.run_command("--password-file", self.write(PASSWORD))
        self.assertNotIn(PASSWORD, self.output)
        secret = "tooshort-secret"
        with self.assertRaises(CommandError) as raised:
            self.run_command("--password-file", self.write(secret))
        self.assertNotIn(secret, str(raised.exception))
