import io
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from manuspectrum.checks import check_oauth_password_grant

LOCKED = SimpleNamespace(locked=True)


class LockedPassTests(SimpleTestCase):
    def run_locked(self, command, module):
        out = io.StringIO()
        with mock.patch(
            f"manuspectrum.management.commands.{module}.run_pass", return_value=LOCKED
        ) as run_pass:
            call_command(command, "--apply", stdout=out)
        run_pass.assert_called_once()
        return out.getvalue()

    def test_the_embargo_command_stops_while_another_pass_runs(self):
        out = self.run_locked("release_expired_embargoes", "release_expired_embargoes")
        self.assertEqual(out, "Another embargo pass is running: nothing done.\n")

    def test_the_workflow_command_stops_while_another_pass_runs(self):
        out = self.run_locked("prune_workflow_history", "prune_workflow_history")
        self.assertEqual(out, "Another workflow pass is running: nothing done.\n")

    def test_the_retention_command_stops_while_another_pass_runs(self):
        out = self.run_locked(
            "anonymise_inactive_accounts", "anonymise_inactive_accounts"
        )
        self.assertEqual(out, "Another retention pass is running: nothing done.\n")


class EmbargoCommandFlagTests(SimpleTestCase):
    def test_apply_and_dry_run_together_run_nothing(self):
        err = io.StringIO()
        with mock.patch(
            "manuspectrum.management.commands.release_expired_embargoes.run_pass"
        ) as run_pass:
            call_command(
                "release_expired_embargoes", "--apply", "--dry-run", stderr=err
            )
        run_pass.assert_not_called()
        self.assertIn("exclude each other", err.getvalue())


@override_settings(ENABLE_TWO_FACTOR_AUTHENTICATION=True)
class OAuthPasswordGrantCheckTests(SimpleTestCase):
    def test_an_unreadable_application_table_is_silent(self):
        with mock.patch(
            "oauth2_provider.models.Application.objects.filter",
            side_effect=RuntimeError("relation does not exist"),
        ):
            self.assertEqual(
                check_oauth_password_grant(None, databases=["default"]), []
            )

    def test_without_the_default_database_nothing_is_checked(self):
        self.assertEqual(check_oauth_password_grant(None, databases=[]), [])
