"""The abandoned-workflow pass: notices, then cleanup outside the deletion counts (PP-4, T9).

A run is a ``workflow_history`` row; the resources it created are the
``edit_log`` creation rows written under its id. The pass is driven by an
explicit clock; ``Resource.delete_index`` is stubbed (no Elasticsearch).

Usage:
    python manage.py test tests.test_accounts_workflows --settings="tests.test_settings" --noinput
"""

import io
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest import mock

from arches.app.models.models import (
    EditLog,
    GraphModel,
    Node,
    NodeGroup,
    ResourceInstance,
    ResourceXResource,
    TileModel,
    WorkflowHistory,
)
from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from manuspectrum.accounts import workflows
from manuspectrum.accounts.creation import created_in_transaction
from manuspectrum.accounts.embargo import LOCAL_TZ
from manuspectrum.models import WorkflowCleanup
from manuspectrum.accounts.workflows import run_pass
from manuspectrum.observability import activity
from tests.explorer_fixtures import ACTIVE, DRAFT
from tests.observability_helpers import delta, sample
from tests.test_accounts_embargo_pass import Fixtures

KIND = "import-biblissima-workflow"
SUMMARY = ["ops@manuspectrum.test"]
NOW = datetime(2026, 10, 12, 3, 30, tzinfo=LOCAL_TZ)
LINKS = {
    ("project", "studied_objects"): "resource-instance-list",
    ("document", "located_in"): "resource-instance",
}


def ago(days):
    return NOW - timedelta(days=days)


class WorkflowFixtures(Fixtures):
    """A run, the resources it creates and the ways other work touches them."""

    def build(self):
        super().build()
        self.graphs["place"] = GraphModel.objects.create(
            name="place",
            isresource=True,
            is_active=True,
            slug="place",
            resource_instance_lifecycle_id="7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75",
        )
        for (slug, alias), datatype in LINKS.items():
            group = NodeGroup.objects.create(nodegroupid=uuid.uuid4(), cardinality="n")
            self.nodes[(slug, alias)] = Node.objects.create(
                nodeid=uuid.uuid4(),
                graph=self.graphs[slug],
                nodegroup=group,
                name=alias,
                alias=alias,
                datatype=datatype,
                istopnode=False,
            )
        self.runs = {}
        cache.clear()

    def begin(self, owner=None, idle=100, name=KIND, completed=False):
        """An open run whose only activity is its start, *idle* days ago."""
        workflow = uuid.uuid4()
        WorkflowHistory.objects.create(
            workflowid=workflow,
            workflowname=name,
            user=owner or self.creator,
            created=ago(idle),
            completed=completed,
        )
        return workflow

    def row(self, resource, user, edittype, workflow, idle, note=None, tile=None):
        return EditLog.objects.create(
            transactionid=workflow,
            resourceinstanceid=str(resource.pk),
            userid=str(user.pk),
            edittype=edittype,
            note=note,
            tileinstanceid=str(tile.pk) if tile else None,
            timestamp=ago(idle),
        )

    def made(
        self, workflow, user, slug="document", name="Codex", state=DRAFT, idle=100
    ):
        """A resource the run created (the bulk path's two creation rows)."""
        resource = ResourceInstance.objects.create(
            graph=self.graphs[slug],
            resource_instance_lifecycle_state_id=state,
            descriptors={"en": {"name": name}},
        )
        self.row(resource, user, "create", workflow, idle)
        self.row(
            resource, user, "tile create", workflow, idle, note="resource creation"
        )
        return resource

    def point(self, source, slug, alias, target, rows=True):
        """A reference tile of *source* to *target*, with its relation row."""
        node = self.nodes[(slug, alias)]
        tile = TileModel.objects.create(
            resourceinstance=source,
            nodegroup_id=node.nodegroup_id,
            data={str(node.nodeid): [{"resourceId": str(target.pk)}]},
        )
        ResourceXResource.objects.create(
            from_resource=source,
            to_resource=target,
            tile=tile,
            node=node,
            created=ago(1),
            modified=ago(1),
        )
        return tile

    def go(self, now, **kwargs):
        with mock.patch("arches.app.models.resource.Resource.delete_index"):
            with mock.patch("arches.app.models.resource.Resource.index"):
                with self.captureOnCommitCallbacks(execute=True):
                    return run_pass(now, **kwargs)

    def exists(self, resource):
        return ResourceInstance.objects.filter(pk=resource.pk).exists()

    def recipients(self):
        return sorted(address for m in mail.outbox for address in m.to)


@override_settings(ACCOUNT_SUMMARY_RECIPIENTS=SUMMARY)
class PassCase(WorkflowFixtures, TestCase):
    def setUp(self):
        self.build()


class NoticeTests(PassCase):
    def test_a_run_idle_68_days_is_untouched_and_the_notice_goes_at_69(self):
        workflow = self.begin(idle=68)
        made = self.made(workflow, self.creator, idle=68)
        report = self.go(NOW)
        self.assertEqual(report.noticed, [])
        self.assertEqual(mail.outbox, [])
        self.assertTrue(self.exists(made))
        report = self.go(NOW + timedelta(days=1))
        self.assertEqual(report.noticed, [str(workflow)])
        self.assertEqual(
            self.recipients(), sorted(["creator@manuspectrum.test", *SUMMARY])
        )
        self.assertIn("21 days", mail.outbox[0].body)

    def test_each_stage_goes_once(self):
        workflow = self.begin(idle=69)
        self.made(workflow, self.creator, idle=69)
        self.go(NOW)
        self.go(NOW + timedelta(hours=2))
        self.go(NOW + timedelta(days=13))
        self.assertEqual(len(mail.outbox), 2)
        mail.outbox.clear()
        self.go(NOW + timedelta(days=14))
        self.assertIn("7 days", mail.outbox[0].body)
        self.go(NOW + timedelta(days=14, hours=1))
        self.assertEqual(len(mail.outbox), 2)
        ledger = WorkflowCleanup.objects.get(workflowid=workflow)
        self.assertEqual(ledger.notices_sent, ["21@2026-10-12", "7@2026-10-26"])

    def test_the_notices_go_to_the_creators_of_created_resources_only(self):
        reused_creator = self.user("reused-creator")
        old = uuid.uuid4()
        existing = self.made(
            old, reused_creator, name="Existing", state=ACTIVE, idle=400
        )
        workflow = self.begin(idle=70)
        self.made(workflow, self.creator, idle=70)
        self.made(workflow, self.editor, name="Second", idle=70)
        self.row(existing, self.outsider, "tile edit", workflow, 70)
        self.go(NOW)
        self.assertEqual(
            self.recipients(),
            sorted(["creator@manuspectrum.test", "editor@manuspectrum.test", *SUMMARY]),
        )

    def test_a_notice_names_what_the_creator_made_and_links_to_it(self):
        workflow = self.begin(idle=70)
        made = self.made(workflow, self.creator, name="Codex Unique")
        self.go(NOW)
        body = mail.outbox[0].body
        self.assertIn("Codex Unique", body)
        self.assertIn(str(made.pk), body)
        self.assertTrue(mail.outbox[0].subject.startswith("[ManuSpectrum][Account]"))

    def test_the_summary_goes_once_per_pass_whatever_the_runs(self):
        for _ in range(3):
            workflow = self.begin(idle=70)
            self.made(workflow, self.creator, idle=70)
        self.go(NOW)
        summaries = [m for m in mail.outbox if m.to == SUMMARY]
        self.assertEqual(len(summaries), 1)

    def test_inactive_and_addressless_creators_get_nothing(self):
        workflow = self.begin(idle=70)
        self.made(workflow, self.inactive, idle=70)
        self.made(workflow, self.outsider, idle=70)
        User.objects.filter(pk=self.outsider.pk).update(email="")
        self.go(NOW)
        self.assertEqual(self.recipients(), SUMMARY)

    def test_a_reopened_run_restarts_the_clock_and_is_noticed_again_later(self):
        workflow = self.begin(idle=75)
        made = self.made(workflow, self.creator, idle=75)
        self.go(NOW)
        self.assertEqual(len(mail.outbox), 2)
        mail.outbox.clear()
        self.row(made, self.creator, "tile edit", workflow, 0)
        self.go(NOW + timedelta(days=30))
        self.go(NOW + timedelta(days=68))
        self.assertEqual(mail.outbox, [])
        self.assertTrue(self.exists(made))
        self.go(NOW + timedelta(days=69))
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("21 days", mail.outbox[0].body)

    def test_a_run_found_overdue_is_noticed_before_it_is_cleaned(self):
        workflow = self.begin(idle=200)
        made = self.made(workflow, self.creator, idle=200)
        report = self.go(NOW)
        self.assertEqual((report.noticed, report.cleaned), ([str(workflow)], []))
        self.assertTrue(self.exists(made))
        self.assertIn("7 days", mail.outbox[0].body)
        self.go(NOW + timedelta(days=6))
        self.assertTrue(self.exists(made))
        report = self.go(NOW + timedelta(days=7))
        self.assertEqual(report.cleaned, [str(workflow)])
        self.assertFalse(self.exists(made))

    def test_a_completed_run_is_never_touched(self):
        workflow = self.begin(idle=300, completed=True)
        made = self.made(workflow, self.creator, idle=300)
        report = self.go(NOW)
        self.assertEqual((report.noticed, report.cleaned), ([], []))
        self.assertEqual(mail.outbox, [])
        self.assertTrue(self.exists(made))
        self.assertTrue(WorkflowHistory.objects.filter(pk=workflow).exists())

    def test_a_workflow_of_another_kind_is_never_touched(self):
        workflow = self.begin(idle=300, name="some-other-workflow")
        made = self.made(workflow, self.creator, idle=300)
        self.assertEqual(self.go(NOW).cleaned, [])
        self.assertTrue(self.exists(made))


class CleanupTests(PassCase):
    def clean(self, idle=100, **made):
        workflow = self.begin(idle=idle)
        resource = self.made(workflow, self.creator, idle=idle, **made)
        self.go(NOW - timedelta(days=0))
        mail.outbox.clear()
        return workflow, resource

    def at_cleanup(self, workflow):
        return self.go(NOW + timedelta(days=7))

    def test_an_untouched_draft_created_by_the_run_is_deleted_with_the_history(self):
        workflow, made = self.clean()
        report = self.at_cleanup(workflow)
        self.assertEqual(report.cleaned, [str(workflow)])
        self.assertFalse(self.exists(made))
        self.assertFalse(WorkflowHistory.objects.filter(pk=workflow).exists())
        ledger = WorkflowCleanup.objects.get(workflowid=workflow)
        self.assertEqual((ledger.deleted_count, ledger.kept_count), (1, 0))
        self.assertIsNotNone(ledger.cleaned_at)

    def test_the_deletion_carries_the_ledger_transaction(self):
        workflow, made = self.clean()
        self.at_cleanup(workflow)
        ledger = WorkflowCleanup.objects.get(workflowid=workflow)
        row = EditLog.objects.get(resourceinstanceid=str(made.pk), edittype="delete")
        self.assertEqual(row.transactionid, ledger.cleanup_transaction_id)
        self.assertNotEqual(ledger.cleanup_transaction_id, workflow)

    def test_a_reused_resource_survives_and_its_creator_gets_nothing(self):
        earlier = self.user("earlier")
        existing = self.made(
            uuid.uuid4(), earlier, name="Existing", state=DRAFT, idle=400
        )
        workflow = self.begin(idle=100)
        made = self.made(workflow, self.creator)
        self.row(existing, self.creator, "tile edit", workflow, 100)
        self.go(NOW)
        mail.outbox.clear()
        report = self.at_cleanup(workflow)
        self.assertFalse(self.exists(made))
        self.assertTrue(self.exists(existing))
        self.assertNotIn("earlier@manuspectrum.test", self.recipients())
        self.assertEqual(report.kept, 0)

    def test_a_reused_resource_with_a_creation_row_of_its_own_is_not_created_by_the_run(
        self,
    ):
        existing = self.made(uuid.uuid4(), self.editor, name="Existing", idle=400)
        workflow = self.begin(idle=100)
        self.row(existing, self.creator, "create", workflow, 100)
        self.assertEqual(created_in_transaction(workflow), {})

    def test_a_created_resource_edited_outside_the_run_is_kept_and_reported(self):
        workflow = self.begin(idle=100)
        made = self.made(workflow, self.creator, name="Edited")
        self.row(made, self.editor, "tile edit", uuid.uuid4(), 20)
        self.go(NOW)
        mail.outbox.clear()
        report = self.at_cleanup(workflow)
        self.assertTrue(self.exists(made))
        self.assertEqual(report.kept_resources, [str(workflow)])
        self.assertIn("Edited", mail.outbox[0].body)
        self.assertEqual(WorkflowCleanup.objects.get().kept_count, 1)

    def test_an_active_created_resource_is_kept(self):
        workflow = self.begin(idle=100)
        active = self.made(workflow, self.creator, state=ACTIVE)
        draft = self.made(workflow, self.creator, name="Draft")
        self.go(NOW)
        self.at_cleanup(workflow)
        self.assertTrue(self.exists(active))
        self.assertFalse(self.exists(draft))

    def test_a_created_resource_referenced_from_outside_is_kept(self):
        workflow = self.begin(idle=100)
        made = self.made(workflow, self.creator)
        outside = self.resource("project", creator=self.editor, name="Outside")
        tile = self.point(outside, "project", "studied_objects", made)
        self.go(NOW)
        self.at_cleanup(workflow)
        self.assertTrue(self.exists(made))
        tile.refresh_from_db()
        self.assertEqual(list(tile.data.values())[0], [{"resourceId": str(made.pk)}])

    def test_the_link_the_run_itself_wrote_does_not_protect_the_resource(self):
        workflow = self.begin(idle=100)
        made = self.made(workflow, self.creator)
        project = self.resource("project", creator=self.editor, name="Project")
        tile = self.point(project, "project", "studied_objects", made)
        self.row(project, self.creator, "tile edit", workflow, 100, tile=tile)
        self.go(NOW)
        self.at_cleanup(workflow)
        self.assertFalse(self.exists(made))
        self.assertTrue(self.exists(project))
        tile.refresh_from_db()
        self.assertEqual(list(tile.data.values())[0], [])

    def test_a_link_edited_later_by_someone_else_protects_the_resource(self):
        workflow = self.begin(idle=100)
        made = self.made(workflow, self.creator)
        project = self.resource("project", creator=self.editor, name="Project")
        tile = self.point(project, "project", "studied_objects", made)
        self.row(project, self.creator, "tile edit", workflow, 100, tile=tile)
        self.row(project, self.editor, "tile edit", uuid.uuid4(), 30, tile=tile)
        self.go(NOW)
        self.at_cleanup(workflow)
        self.assertTrue(self.exists(made))

    def test_a_dependency_used_by_a_kept_resource_is_kept_with_it(self):
        workflow = self.begin(idle=100)
        place = self.made(workflow, self.creator, slug="place", name="Place")
        kept = self.made(workflow, self.creator, state=ACTIVE, name="Kept")
        loose = self.made(workflow, self.creator, slug="place", name="Loose place")
        self.point(kept, "document", "located_in", place)
        self.go(NOW)
        self.at_cleanup(workflow)
        self.assertTrue(self.exists(place))
        self.assertTrue(self.exists(kept))
        self.assertFalse(self.exists(loose))

    def test_a_dependency_used_only_by_deleted_resources_is_deleted(self):
        workflow = self.begin(idle=100)
        place = self.made(workflow, self.creator, slug="place", name="Place")
        document = self.made(workflow, self.creator, name="Doc")
        self.point(document, "document", "located_in", place)
        self.go(NOW)
        self.at_cleanup(workflow)
        self.assertFalse(self.exists(place))
        self.assertFalse(self.exists(document))

    def test_the_cleanup_mail_lists_what_was_deleted_and_kept(self):
        workflow = self.begin(idle=100)
        self.made(workflow, self.creator, name="Gone")
        self.made(workflow, self.creator, state=ACTIVE, name="Stays")
        self.go(NOW)
        mail.outbox.clear()
        self.at_cleanup(workflow)
        body = mail.outbox[0].body
        self.assertIn("Gone", body)
        self.assertIn("Stays", body)
        self.assertEqual(len([m for m in mail.outbox if m.to == SUMMARY]), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_the_cleanup_mail_goes_to_the_creators_of_the_run_only(self):
        reused = self.made(
            uuid.uuid4(), self.outsider, name="Reused", state=ACTIVE, idle=400
        )
        workflow = self.begin(idle=100)
        self.made(workflow, self.creator)
        self.row(reused, self.editor, "tile edit", workflow, 100)
        self.go(NOW)
        mail.outbox.clear()
        self.at_cleanup(workflow)
        self.assertEqual(
            self.recipients(), sorted(["creator@manuspectrum.test", *SUMMARY])
        )

    def test_a_pass_that_cleans_nothing_to_delete_still_drops_the_history(self):
        workflow = self.begin(idle=100)
        self.go(NOW)
        self.at_cleanup(workflow)
        self.assertFalse(WorkflowHistory.objects.filter(pk=workflow).exists())
        self.assertEqual(WorkflowCleanup.objects.get().deleted_count, 0)

    def test_a_cleaned_run_is_not_cleaned_twice(self):
        workflow, made = self.clean()
        self.at_cleanup(workflow)
        with delta(
            "manuspectrum_workflow_cleanups_total", kind=KIND, outcome="cleaned"
        ) as counted:
            self.go(NOW + timedelta(days=9))
        self.assertEqual(counted.value, 0)

    def test_a_failing_delete_rolls_the_run_back_and_is_counted(self):
        workflow, made = self.clean()
        second = self.made(workflow, self.creator, name="Second")
        calls = []
        real = workflows.Resource.delete

        def failing(self, *args, **kwargs):
            calls.append(self.pk)
            if len(calls) == 2:
                raise RuntimeError("boom")
            return real(self, *args, **kwargs)

        with delta(
            "manuspectrum_workflow_cleanups_total", kind=KIND, outcome="failed"
        ) as failed:
            with mock.patch.object(workflows.Resource, "delete", failing):
                report = self.at_cleanup(workflow)
        self.assertEqual(report.failed, [str(workflow)])
        self.assertEqual(failed.value, 1)
        self.assertTrue(self.exists(made) and self.exists(second))
        self.assertTrue(WorkflowHistory.objects.filter(pk=workflow).exists())
        self.assertIsNone(WorkflowCleanup.objects.get().cleaned_at)
        self.assertFalse(EditLog.objects.filter(edittype="delete").exists())

    def test_activity_between_the_listing_and_the_cleanup_stops_it(self):
        workflow, made = self.clean()
        real = workflows.open_runs

        def reopened(*args, **kwargs):
            runs = real(*args, **kwargs)
            self.row(made, self.creator, "tile edit", workflow, -7)
            return runs

        with mock.patch.object(workflows, "open_runs", reopened):
            report = self.at_cleanup(workflow)
        self.assertEqual(report.cleaned, [])
        self.assertTrue(self.exists(made))


class ActivityTests(PassCase):
    def window(self):
        return NOW - timedelta(days=1), NOW + timedelta(days=30)

    def counts(self):
        with activity.read_only_cursor() as cursor:
            changes = activity.resource_changes(cursor, *self.window())
        return changes.get("document", {})

    def test_a_cleaned_resource_counts_as_cleaned_not_deleted(self):
        workflow = self.begin(idle=100)
        self.made(workflow, self.creator)
        self.go(NOW)
        self.go(NOW + timedelta(days=7))
        counts = self.counts()
        self.assertEqual((counts["cleaned"], counts["deleted"]), (1, 0))

    def test_a_user_deletion_still_counts_as_deleted(self):
        workflow = self.begin(idle=100)
        made = self.made(workflow, self.creator)
        from arches.app.models.resource import Resource

        with mock.patch.object(Resource, "delete_index"):
            Resource.objects.get(pk=made.pk).delete(transaction_id=uuid.uuid4())
        EditLog.objects.filter(edittype="delete").update(timestamp=NOW)
        counts = self.counts()
        self.assertEqual((counts["cleaned"], counts["deleted"]), (0, 1))

    def test_a_deletion_without_a_transaction_row_still_counts_as_deleted(self):
        made = self.made(self.begin(idle=100), self.creator)
        EditLog.objects.create(
            transactionid=uuid.uuid4(),
            resourceinstanceid=str(made.pk),
            resourceclassid=str(self.graphs["document"].pk),
            edittype="delete",
            timestamp=NOW,
        )
        WorkflowCleanup.objects.create(
            workflowid=uuid.uuid4(), workflowname=KIND, last_activity=ago(100)
        )
        self.assertEqual(self.counts()["deleted"], 1)


class MetricsTests(PassCase):
    def test_counters_and_the_timestamp_gauge_follow_the_pass(self):
        workflow = self.begin(idle=100)
        self.made(workflow, self.creator, name="Gone")
        self.made(workflow, self.creator, state=ACTIVE, name="Stays")
        self.go(NOW)
        before = sample("manuspectrum_workflow_cleanup_timestamp_seconds")
        with (
            delta(
                "manuspectrum_workflow_cleanups_total",
                kind=KIND,
                outcome="kept_resources",
            ) as cleaned,
            delta(
                "manuspectrum_workflow_cleanup_resources_total", outcome="deleted"
            ) as deleted,
            delta(
                "manuspectrum_workflow_cleanup_resources_total", outcome="kept"
            ) as kept,
        ):
            self.go(NOW + timedelta(days=7))
        self.assertEqual((cleaned.value, deleted.value, kept.value), (1, 1, 1))
        self.assertGreater(
            sample("manuspectrum_workflow_cleanup_timestamp_seconds"), before
        )

    def test_a_clean_run_without_kept_resources_counts_cleaned(self):
        workflow = self.begin(idle=100)
        self.made(workflow, self.creator)
        self.go(NOW)
        with delta(
            "manuspectrum_workflow_cleanups_total", kind=KIND, outcome="cleaned"
        ) as cleaned:
            self.go(NOW + timedelta(days=7))
        self.assertEqual(cleaned.value, 1)

    def test_a_dry_run_leaves_the_gauge_alone(self):
        before = sample("manuspectrum_workflow_cleanup_timestamp_seconds")
        self.go(NOW, apply=False)
        self.assertEqual(
            sample("manuspectrum_workflow_cleanup_timestamp_seconds"), before
        )


class DryRunTests(PassCase):
    def test_a_dry_run_writes_and_sends_nothing(self):
        workflow = self.begin(idle=100)
        made = self.made(workflow, self.creator)
        self.go(NOW)
        mail.outbox.clear()
        ledger_before = list(WorkflowCleanup.objects.values())
        report = self.go(NOW + timedelta(days=7), apply=False)
        self.assertEqual(mail.outbox, [])
        self.assertTrue(self.exists(made))
        self.assertTrue(WorkflowHistory.objects.filter(pk=workflow).exists())
        self.assertEqual(list(WorkflowCleanup.objects.values()), ledger_before)
        plan = report.plans[str(workflow)]
        self.assertEqual(plan.deletable, [str(made.pk)])

    def test_a_dry_run_of_a_new_run_creates_no_ledger_row(self):
        workflow = self.begin(idle=70)
        self.made(workflow, self.creator, idle=70)
        report = self.go(NOW, apply=False)
        self.assertEqual(report.noticed, [str(workflow)])
        self.assertFalse(WorkflowCleanup.objects.exists())
        self.assertEqual(mail.outbox, [])

    def test_the_command_defaults_to_a_dry_run_and_applies_on_request(self):
        workflow = self.begin(idle=100)
        made = self.made(workflow, self.creator)
        out = io.StringIO()
        with mock.patch(
            "manuspectrum.accounts.workflows.timezone.now", return_value=NOW
        ):
            call_command("prune_workflow_history", stdout=out)
        self.assertIn("Dry run", out.getvalue())
        self.assertIn("would be noticed", out.getvalue())
        self.assertFalse(WorkflowCleanup.objects.exists())
        with mock.patch(
            "manuspectrum.accounts.workflows.timezone.now", return_value=NOW
        ):
            with mock.patch("arches.app.models.resource.Resource.index"):
                call_command("prune_workflow_history", "--apply", stdout=out)
        self.assertTrue(WorkflowCleanup.objects.exists())
        self.assertTrue(self.exists(made))

    def test_the_command_can_be_restricted_to_one_run(self):
        first = self.begin(idle=70)
        second = self.begin(idle=70)
        out = io.StringIO()
        with mock.patch(
            "manuspectrum.accounts.workflows.timezone.now", return_value=NOW
        ):
            call_command("prune_workflow_history", "--workflow", str(first), stdout=out)
        self.assertIn(str(first), out.getvalue())
        self.assertNotIn(str(second), out.getvalue())

    def test_the_command_refuses_bad_arguments(self):
        with self.assertRaises(CommandError):
            call_command("prune_workflow_history", "--apply", "--dry-run")
        with self.assertRaises(CommandError):
            call_command("prune_workflow_history", "--workflow", "nope")


class ScheduleTests(PassCase):
    def test_the_pass_is_scheduled_daily_at_0330_europe_paris(self):
        entry = settings.CELERY_BEAT_SCHEDULE["workflow-cleanup-pass"]
        self.assertEqual(entry["task"], "manuspectrum.workflow_cleanup_pass")
        self.assertEqual(entry["schedule"]._orig_hour, 3)
        self.assertEqual(entry["schedule"]._orig_minute, 30)
        self.assertEqual(settings.CELERY_TIMEZONE, "Europe/Paris")

    def test_the_task_runs_the_pass(self):
        from manuspectrum.tasks import workflow_cleanup_pass_task

        self.assertEqual(workflow_cleanup_pass_task()["failed"], 0)

    def test_the_settings_are_the_po_decision(self):
        self.assertEqual(settings.WORKFLOW_CLEANUP_AFTER_DAYS, 90)
        self.assertEqual(settings.WORKFLOW_NOTICE_DAYS, (21, 7))


class CreatedInTransactionTests(PassCase):
    def test_creators_are_those_of_the_creation_rows_of_the_run(self):
        workflow = self.begin()
        one = self.made(workflow, self.creator)
        two = self.made(workflow, self.editor)
        self.assertEqual(
            created_in_transaction(workflow),
            {str(one.pk): self.creator.pk, str(two.pk): self.editor.pk},
        )

    def test_a_tile_row_alone_is_not_a_creation(self):
        workflow = self.begin()
        resource = self.resource("document", creator=self.editor)
        self.row(resource, self.creator, "tile create", workflow, 1)
        self.assertEqual(created_in_transaction(workflow), {})


@override_settings(ACCOUNT_SUMMARY_RECIPIENTS=SUMMARY)
class ConcurrencyTests(WorkflowFixtures, TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.build()
        self.workflow = self.begin(idle=100)
        self.made_resource = self.made(self.workflow, self.creator)
        self.go(NOW)
        mail.outbox.clear()

    def captureOnCommitCallbacks(self, **kwargs):
        import contextlib

        return contextlib.nullcontext()

    def test_two_passes_in_threads_clean_once(self):
        entered = threading.Barrier(2)
        real = workflows.open_runs

        def slow(*args, **kwargs):
            runs = real(*args, **kwargs)
            try:
                entered.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass
            return runs

        def run(_):
            try:
                with mock.patch("arches.app.models.resource.Resource.delete_index"):
                    with mock.patch("arches.app.models.resource.Resource.index"):
                        return run_pass(NOW + timedelta(days=7))
            finally:
                connection.close()

        with mock.patch.object(workflows, "open_runs", slow):
            with ThreadPoolExecutor(2) as pool:
                reports = list(pool.map(run, range(2)))
        self.assertEqual(sorted(r.locked for r in reports), [False, True])
        self.assertEqual(sum(len(r.cleaned) for r in reports), 1)
        self.assertEqual(
            EditLog.objects.filter(
                resourceinstanceid=str(self.made_resource.pk), edittype="delete"
            ).count(),
            1,
        )
        self.assertEqual(len([m for m in mail.outbox if m.to == SUMMARY]), 1)

    def test_two_cleanups_of_one_run_without_the_lock_clean_once(self):
        meet = threading.Barrier(2)
        real = workflows.plan_cleanup

        def meeting(workflowid):
            plan = real(workflowid)
            try:
                meet.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass
            return plan

        runs = workflows.open_runs(NOW + timedelta(days=7))
        self.assertEqual(len(runs), 1)

        def clean(_):
            try:
                with mock.patch("arches.app.models.resource.Resource.delete_index"):
                    report = workflows.PassReport()
                    result = workflows._clean(runs[0], report)
                    return len(report.cleaned), result
            finally:
                connection.close()

        with mock.patch.object(workflows, "plan_cleanup", meeting):
            with ThreadPoolExecutor(2) as pool:
                outcomes = list(pool.map(clean, range(2)))
        self.assertEqual(sorted(n for n, _ in outcomes), [0, 1])
        self.assertEqual(
            EditLog.objects.filter(
                resourceinstanceid=str(self.made_resource.pk), edittype="delete"
            ).count(),
            1,
        )

    def test_the_pass_lock_is_released_after_a_pass(self):
        with mock.patch("arches.app.models.resource.Resource.delete_index"):
            with mock.patch("arches.app.models.resource.Resource.index"):
                run_pass(NOW)
                self.assertFalse(run_pass(NOW).locked)
