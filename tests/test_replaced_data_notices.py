"""After `restore` or `load-snapshot`, the first daily passes only send notices.

Runs the voiding statements of `deploy/scripts/lib-replace-data.sh`
(`void_pending_notices`), read from the script itself, on ledgers whose notices
were sent long ago, then each pass with ``apply``.

    python manage.py test tests.test_replaced_data_notices --settings="tests.test_settings"
"""

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings

from manuspectrum.accounts import embargo, retention, workflows
from manuspectrum.accounts.embargo import LOCAL_TZ
from manuspectrum.models import AccountRetention, Embargo, WorkflowCleanup
from tests.test_accounts_workflows import WorkflowFixtures

SCRIPT = Path(settings.APP_ROOT).parent / "deploy" / "scripts" / "lib-replace-data.sh"
NOW = datetime(2026, 10, 12, 6, 0, tzinfo=LOCAL_TZ)
LONG_AGO = date(2026, 6, 1)


def voiding_statements():
    """The SQL statements of ``void_pending_notices`` in the shell library."""
    text = SCRIPT.read_text(encoding="utf-8")
    body = re.search(
        r'void_pending_notices\(\) \{\n\s*psql_admin -d "\$PGDBNAME" -c "(.*?)"\n\}',
        text,
        re.DOTALL,
    ).group(1)
    return [s.strip() for s in body.split(";") if s.strip()]


@override_settings(ACCOUNT_SUMMARY_RECIPIENTS=["ops@manuspectrum.test"])
class ReplacedDataTests(WorkflowFixtures, TestCase):
    def setUp(self):
        self.build()
        self.workflow = self.begin(idle=200)
        self.made_resource = self.made(self.workflow, self.creator, idle=200)
        WorkflowCleanup.objects.create(
            workflowid=self.workflow,
            workflowname="import-biblissima-workflow",
            last_activity=NOW - timedelta(days=200),
            notices_sent=[f"21@{LONG_AGO.isoformat()}", f"7@{LONG_AGO.isoformat()}"],
        )
        self.idle_user = User.objects.create_user("idle", "idle@manuspectrum.test", "x")
        login = NOW - timedelta(days=30 * 31)
        User.objects.filter(pk=self.idle_user.pk).update(
            last_login=login.replace(tzinfo=None),
            date_joined=login.replace(tzinfo=None),
        )
        self.idle_user.refresh_from_db()
        AccountRetention.objects.create(
            user_id=self.idle_user.pk,
            noticed_on=LONG_AGO,
            noticed_for=retention.last_activity_day(self.idle_user),
        )
        self.restricted = self.resource(creator=self.creator, name="Restricted")
        row = self.restrict(self.restricted, date(2026, 10, 1))
        Embargo.objects.filter(pk=row.pk).update(notices_sent=["30", "7"])

    def passes(self, apply):
        with mock.patch("arches.app.models.resource.Resource.delete_index"):
            with mock.patch("arches.app.models.resource.Resource.index"):
                with self.captureOnCommitCallbacks(execute=True):
                    return (
                        workflows.run_pass(NOW, apply=apply),
                        retention.run_pass(NOW, apply=apply),
                        embargo.run_pass(NOW, apply=apply),
                    )

    def test_the_script_holds_one_statement_per_ledger(self):
        tables = [re.match(r"UPDATE (\w+)", s).group(1) for s in voiding_statements()]
        self.assertEqual(
            tables, ["ms_workflow_cleanup", "ms_account_retention", "ms_embargo"]
        )

    def test_without_the_voiding_the_old_notices_would_let_every_pass_act(self):
        cleanup, account, restriction = self.passes(apply=False)
        self.assertIn(str(self.workflow), cleanup.plans)
        self.assertIn(self.idle_user.pk, account.anonymised)
        self.assertEqual(restriction.due, [str(self.restricted.pk)])

    def test_after_the_voiding_the_first_passes_only_send_notices(self):
        with connection.cursor() as cursor:
            for statement in voiding_statements():
                cursor.execute(statement)
        cleanup, account, restriction = self.passes(apply=True)
        self.assertEqual(cleanup.noticed, [str(self.workflow)])
        self.assertEqual(cleanup.cleaned, [])
        self.assertTrue(self.exists(self.made_resource))
        self.assertIn(self.idle_user.pk, account.noticed)
        self.assertEqual(account.anonymised, [])
        self.assertFalse(
            AccountRetention.objects.filter(anonymised_on__isnull=False).exists()
        )
        self.assertEqual(restriction.redated, [str(self.restricted.pk)])
        self.assertEqual(restriction.lifted, [])
        self.assertEqual(Embargo.objects.get().state, Embargo.ACTIVE)
        self.assertFalse(self.readable(self.restricted))
