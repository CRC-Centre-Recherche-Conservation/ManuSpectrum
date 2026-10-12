"""The daily embargo pass: reconcile, notices, lift and lift notice (PP-4, T7).

Restrictions are Arches' ``no_access_to_resourceinstance`` grants on the
``anonymous`` user, written through ``assign_perm``; the pass is driven by an
explicit clock.

Usage:
    python manage.py test tests.test_accounts_embargo_pass --settings="tests.test_settings"
"""

import io
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.conf import settings

from arches.app.models.models import (
    EditLog,
    GraphModel,
    Node,
    NodeGroup,
    ResourceInstance,
    TileModel,
)
from arches.app.utils import permission_backend as apb
from arches.app.utils.permission_backend import assign_perm
from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.cache import cache, caches
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from manuspectrum.accounts import embargo
from manuspectrum.accounts.embargo import LOCAL_TZ, run_pass
from manuspectrum.models import Embargo, EmbargoEvent
from manuspectrum.utils.public_visibility import (
    anonymous_user,
    permission_epoch,
)
from tests.explorer_fixtures import ACTIVE
from tests.observability_helpers import delta, sample

NO_ACCESS = "no_access_to_resourceinstance"
LIFECYCLE = "7e3cce56-fbfb-4a4b-8e83-59b9f9e7cb75"
NODES = {
    # (graph slug, alias): (datatype)
    ("document", "label_of_name"): "string",
    ("project", "label_of_name"): "string",
    ("component", "item_visual_is_part_of_document"): "resource-instance",
    ("analysis", "component_observed"): "resource-instance-list",
    ("analysis", "analysis_by_project"): "resource-instance",
}
ENDS = date(2026, 10, 12)
LIFT_TIME = datetime(2026, 10, 13, 6, 0, tzinfo=LOCAL_TZ)
SUMMARY = ["ops@manuspectrum.test"]


def at(day, hour=6):
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=LOCAL_TZ)


class Fixtures:
    """Graphs, users and helpers shared by the lift and concurrency cases."""

    def build(self):
        cache.clear()
        caches["user_permission"].clear()
        self.graphs = {}
        self.nodes = {}
        for slug in ("document", "component", "project", "analysis"):
            self.graphs[slug] = GraphModel.objects.create(
                name=slug,
                isresource=True,
                is_active=True,
                slug=slug,
                resource_instance_lifecycle_id=LIFECYCLE,
            )
        for (slug, alias), datatype in NODES.items():
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
        self.anonymous = User.objects.get(username="anonymous")
        self.creator = self.user("creator")
        self.setter = self.user("setter")
        self.editor = self.user("editor")
        self.outsider = self.user("outsider")
        self.inactive = self.user("inactive", is_active=False)

    def user(self, name, **kwargs):
        return User.objects.create_user(
            name, f"{name}@manuspectrum.test", "pw", **kwargs
        )

    def resource(self, slug="document", creator=None, name="Codex X"):
        resource = ResourceInstance.objects.create(
            graph=self.graphs[slug],
            resource_instance_lifecycle_state_id=ACTIVE,
            descriptors={"en": {"name": name}},
        )
        if creator is not None:
            self.log(resource, creator, "create")
        return resource

    def link(self, source, slug, alias, *targets):
        node = self.nodes[(slug, alias)]
        TileModel.objects.create(
            resourceinstance=source,
            nodegroup_id=node.nodegroup_id,
            data={
                str(node.nodeid): (
                    [{"resourceId": str(t.pk)} for t in targets]
                    if node.datatype.endswith("list")
                    else [{"resourceId": str(targets[0].pk)}]
                )
            },
        )

    def analysis_of(self, project, creator):
        """An Analysis of *project* observing a Component of a new Document."""
        document = self.resource("document", name="Doc")
        component = self.resource("component", name="Comp")
        self.link(component, "component", "item_visual_is_part_of_document", document)
        analysis = self.resource("analysis", creator=creator, name="Analysis")
        self.link(analysis, "analysis", "component_observed", component)
        self.link(analysis, "analysis", "analysis_by_project", project)
        return analysis

    def log(self, resource, user, edittype, note=None):
        EditLog.objects.create(
            resourceinstanceid=str(resource.pk),
            userid=str(user.pk),
            edittype=edittype,
            note=note,
            timestamp=datetime(2026, 1, 1, tzinfo=LOCAL_TZ),
        )

    def restrict(self, resource, ends_on=None, by=None, undated=False):
        """Restrict *resource* from the visitor and record it, as a request of *by* would.

        The row is dated by the detection rule unless *ends_on* sets another end
        or *undated* clears it.
        """
        with mock.patch(
            "manuspectrum.signals.current_request",
            return_value=mock.Mock(user=by) if by else None,
        ):
            with self.captureOnCommitCallbacks(execute=True):
                assign_perm(NO_ACCESS, self.anonymous, resource)
        row = Embargo.objects.get(resourceinstance=resource)
        if ends_on or undated:
            row.change_end(ends_on, by=None)
            row.events.all().delete()
        return row

    def go(self, now, **kwargs):
        with mock.patch("arches.app.models.resource.Resource.index") as index:
            with self.captureOnCommitCallbacks(execute=True):
                report = run_pass(now, **kwargs)
        return report, index

    def readable(self, resource):
        caches["user_permission"].clear()
        return apb.user_can_read_resource(anonymous_user(), resource=resource)


@override_settings(ACCOUNT_SUMMARY_RECIPIENTS=SUMMARY)
class PassCase(Fixtures, TestCase):
    def setUp(self):
        self.build()
        self.resource_x = self.resource(creator=self.creator)

    def recipients(self):
        return sorted(address for m in mail.outbox for address in m.to)


class ReconcileTests(PassCase):
    def test_a_restriction_added_in_arches_is_recorded_with_its_setter(self):
        self.restrict(self.resource_x, by=self.setter)
        row = Embargo.objects.get(resourceinstance=self.resource_x)
        self.assertEqual(row.set_by, self.setter)
        self.assertEqual(
            row.ends_on,
            date.today() + relativedelta(months=settings.EMBARGO_MAX_MONTHS),
        )
        detected, dated = row.events.order_by("pk")
        self.assertEqual(
            (detected.kind, detected.by), (EmbargoEvent.DETECTED, self.setter)
        )
        self.assertEqual(
            (dated.kind, dated.by, dated.from_date, dated.to_date),
            (EmbargoEvent.DATED, None, None, row.ends_on),
        )

    def test_the_pass_records_a_restriction_written_without_a_request(self):
        assign_perm(NO_ACCESS, self.anonymous, self.resource_x)
        self.assertFalse(Embargo.objects.exists())
        report, _ = self.go(LIFT_TIME)
        row = Embargo.objects.get(resourceinstance=self.resource_x)
        self.assertEqual(report.detected, [str(self.resource_x.pk)])
        self.assertIsNone(row.set_by)
        self.assertEqual(row.ends_on, date(2027, 10, 13))
        self.assertEqual(
            [e.kind for e in row.events.order_by("pk")],
            [EmbargoEvent.DETECTED, EmbargoEvent.DATED],
        )

    def test_a_restriction_found_without_a_row_is_dated_from_its_detection_day(self):
        assign_perm(NO_ACCESS, self.anonymous, self.resource_x)
        Embargo.objects.all().delete()
        self.go(at(date(2027, 1, 31)))
        self.assertEqual(Embargo.objects.get().ends_on, date(2028, 1, 31))

    def test_a_row_that_exists_keeps_its_dates_when_the_pass_runs(self):
        row = self.restrict(self.resource_x, ENDS + timedelta(days=100))
        self.go(at(ENDS))
        row.refresh_from_db()
        self.assertEqual(row.ends_on, ENDS + timedelta(days=100))
        self.assertEqual(row.events.count(), 0)

    def test_a_row_already_past_its_end_is_lifted_with_the_notice(self):
        self.log(self.resource_x, self.creator, "create")
        row = self.restrict(self.resource_x, ENDS)
        Embargo.objects.filter(pk=row.pk).update(notices_sent=["30", "7"])
        report, _ = self.go(at(ENDS + timedelta(days=400)))
        row.refresh_from_db()
        self.assertEqual(report.lifted, [str(self.resource_x.pk)])
        self.assertEqual(row.state, Embargo.LIFTED)
        self.assertTrue(self.readable(self.resource_x))
        self.assertIn(self.creator.email, self.recipients())

    def test_a_grant_to_someone_else_records_nothing(self):
        with self.captureOnCommitCallbacks(execute=True):
            assign_perm(NO_ACCESS, self.outsider, self.resource_x)
        self.assertFalse(Embargo.objects.exists())

    def test_a_restriction_removed_by_hand_is_released(self):
        row = self.restrict(self.resource_x, by=self.setter)
        apb.remove_perm(NO_ACCESS, self.anonymous, self.resource_x)
        report, _ = self.go(LIFT_TIME)
        row.refresh_from_db()
        self.assertEqual(report.released, [str(self.resource_x.pk)])
        self.assertEqual(row.state, Embargo.RELEASED)
        self.assertEqual(row.events.last().kind, EmbargoEvent.RELEASED)

    def test_a_released_resource_restricted_again_starts_over(self):
        row = self.restrict(self.resource_x, ENDS, by=self.setter)
        apb.remove_perm(NO_ACCESS, self.anonymous, self.resource_x)
        self.go(LIFT_TIME - timedelta(days=30))
        assign_perm(NO_ACCESS, self.anonymous, self.resource_x)
        self.go(LIFT_TIME - timedelta(days=29))
        row.refresh_from_db()
        self.assertEqual(
            (row.state, row.ends_on),
            (
                Embargo.ACTIVE,
                (LIFT_TIME - timedelta(days=29)).date() + relativedelta(months=12),
            ),
        )
        self.assertEqual(row.notices_sent, [])


class DatingTests(PassCase):
    def test_a_row_dated_by_the_pass_ends_exactly_the_maximum_after_its_local_day(self):
        from manuspectrum.accounts.embargo import record_restriction

        chicago = ZoneInfo("America/Chicago")
        detected = datetime(2026, 3, 2, 23, 30, tzinfo=chicago)
        self.assertEqual(detected.astimezone(LOCAL_TZ).date(), date(2026, 3, 3))
        with mock.patch(
            "django.utils.timezone.now", return_value=detected.replace(tzinfo=None)
        ):
            self.assertTrue(record_restriction(self.resource_x.pk, now=detected))
        row = Embargo.objects.get(resourceinstance=self.resource_x)
        expected = date(2026, 3, 3) + relativedelta(months=settings.EMBARGO_MAX_MONTHS)
        self.assertEqual(row.ends_on, expected)
        self.assertEqual(row.start, date(2026, 3, 3))
        self.assertEqual(row.latest_allowed_end(), expected)


class NoticeTests(PassCase):
    def test_the_30_day_notice_goes_once_to_the_creator_and_the_setter(self):
        self.restrict(self.resource_x, ENDS + timedelta(days=30), by=self.setter)
        self.log(self.resource_x, self.outsider, "tile edit")
        today = at(ENDS)
        self.go(today)
        self.assertEqual(
            self.recipients(),
            sorted(
                [
                    "creator@manuspectrum.test",
                    "setter@manuspectrum.test",
                    *SUMMARY,
                ]
            ),
        )
        self.assertIn("30 days", mail.outbox[0].body)
        mail.outbox.clear()
        self.go(today + timedelta(hours=3))
        self.go(at(ENDS + timedelta(days=1)))
        self.assertEqual(mail.outbox, [])
        row = Embargo.objects.get()
        self.assertEqual(row.notices_sent, ["30"])
        self.assertEqual(row.events.filter(kind=EmbargoEvent.NOTICED).count(), 1)

    def test_the_7_day_notice_follows_the_30_day_one(self):
        self.restrict(self.resource_x, ENDS + timedelta(days=30), by=self.setter)
        self.go(at(ENDS))
        mail.outbox.clear()
        self.go(at(ENDS + timedelta(days=22)))
        self.assertEqual(mail.outbox, [])
        self.go(at(ENDS + timedelta(days=23)))
        self.assertIn("7 days", mail.outbox[0].body)
        self.assertEqual(Embargo.objects.get().notices_sent, ["30", "7"])

    def test_a_restriction_dated_inside_both_stages_gets_one_notice(self):
        self.restrict(self.resource_x, ENDS + timedelta(days=5))
        self.go(at(ENDS))
        creator_mails = [
            m for m in mail.outbox if m.to == ["creator@manuspectrum.test"]
        ]
        self.assertEqual(len(creator_mails), 1)
        self.assertEqual(Embargo.objects.get().notices_sent, ["30", "7"])

    def test_inactive_and_addressless_creators_get_nothing(self):
        other = self.resource(creator=self.inactive, name="Other")
        self.restrict(other, ENDS + timedelta(days=5), by=self.setter)
        User.objects.filter(pk=self.setter.pk).update(email="")
        self.go(at(ENDS))
        self.assertEqual(self.recipients(), SUMMARY)

    def test_an_extension_restarts_the_notices_against_the_new_date(self):
        row = self.restrict(self.resource_x, ENDS + timedelta(days=30))
        self.go(at(ENDS))
        mail.outbox.clear()
        row.refresh_from_db()
        row.change_end(ENDS + timedelta(days=90), by=self.editor)
        self.go(at(ENDS + timedelta(days=40)))
        self.assertEqual(mail.outbox, [])
        self.go(at(ENDS + timedelta(days=60)))
        self.assertTrue(mail.outbox)
        self.assertIn("30 days", mail.outbox[0].body)

    def test_a_project_notice_reaches_the_creators_of_its_analyses(self):
        project = self.resource("project", creator=self.creator, name="Project P")
        self.analysis_of(project, self.outsider)
        self.analysis_of(self.resource("project"), self.editor)
        self.restrict(project, ENDS + timedelta(days=5))
        self.go(at(ENDS))
        self.assertEqual(
            self.recipients(),
            sorted(
                ["creator@manuspectrum.test", "outsider@manuspectrum.test", *SUMMARY]
            ),
        )

    def test_the_notice_names_the_resource_and_links_to_it(self):
        self.restrict(self.resource_x, ENDS + timedelta(days=5))
        self.go(at(ENDS))
        body = mail.outbox[0].body
        self.assertIn("Codex X", body)
        self.assertIn(f"/report/{self.resource_x.pk}", body)
        self.assertNotIn("setter", body)

    def test_a_dry_run_sends_and_writes_nothing(self):
        self.restrict(self.resource_x, ENDS + timedelta(days=5))
        report, _ = self.go(at(ENDS), apply=False)
        self.assertEqual(report.noticed, [str(self.resource_x.pk)])
        self.assertEqual(mail.outbox, [])
        self.assertEqual(Embargo.objects.get().notices_sent, [])


class LiftTests(PassCase):
    def test_nothing_is_lifted_before_6_the_day_after_the_end_date(self):
        self.restrict(self.resource_x, ENDS)
        self.go(at(ENDS, hour=23))
        self.go(datetime(2026, 10, 13, 5, 59, tzinfo=LOCAL_TZ))
        self.assertFalse(self.readable(self.resource_x))
        self.assertEqual(Embargo.objects.get().state, Embargo.ACTIVE)

    def test_the_lift_removes_the_visitor_grants_and_keeps_an_editors(self):
        self.restrict(self.resource_x, ENDS, by=self.setter)
        assign_perm("change_resourceinstance", self.editor, self.resource_x)
        before = permission_epoch()
        with delta("manuspectrum_embargo_lifts_total", outcome="lifted") as lifts:
            report, index = self.go(LIFT_TIME)
        self.assertEqual(report.lifted, [str(self.resource_x.pk)])
        self.assertEqual(lifts.value, 1)
        self.assertEqual(list(apb.get_user_perms(self.anonymous, self.resource_x)), [])
        self.assertIn(
            "change_resourceinstance",
            [p.codename for p in apb.get_user_perms(self.editor, self.resource_x)],
        )
        self.assertTrue(self.readable(self.resource_x))
        self.assertNotEqual(permission_epoch(), before)
        index.assert_called_once()
        row = Embargo.objects.get()
        self.assertEqual(row.state, Embargo.LIFTED)
        self.assertEqual(row.events.last().kind, EmbargoEvent.LIFTED)

    def test_the_lift_tells_the_people_concerned_and_the_administrators(self):
        self.restrict(self.resource_x, ENDS, by=self.setter)
        mail.outbox.clear()
        self.go(LIFT_TIME)
        self.assertEqual(
            self.recipients(),
            sorted(["creator@manuspectrum.test", "setter@manuspectrum.test", *SUMMARY]),
        )
        self.assertIn("now public", mail.outbox[0].subject)

    def test_a_second_pass_changes_nothing(self):
        self.restrict(self.resource_x, ENDS)
        self.go(LIFT_TIME)
        mail.outbox.clear()
        with delta("manuspectrum_embargo_lifts_total", outcome="lifted") as lifts:
            report, index = self.go(LIFT_TIME + timedelta(days=1))
        self.assertEqual((report.lifted, lifts.value, mail.outbox), ([], 0, []))
        index.assert_not_called()
        self.assertEqual(Embargo.objects.get().events.filter(kind="lifted").count(), 1)

    def test_an_undated_restriction_is_never_lifted_and_is_counted(self):
        self.restrict(self.resource_x, undated=True)
        report, _ = self.go(LIFT_TIME + timedelta(days=4000))
        self.assertFalse(self.readable(self.resource_x))
        self.assertEqual((report.lifted, report.undated), ([], 1))
        self.assertEqual(sample("manuspectrum_embargoes", state="undated"), 1)

    def test_an_extension_between_the_choice_and_the_lift_wins(self):
        row = self.restrict(self.resource_x, ENDS)
        real = embargo.lift_one

        def extend_then_lift(pk, now):
            Embargo.objects.get(pk=pk).change_end(
                ENDS + timedelta(days=60), by=self.editor
            )
            return real(pk, now)

        with mock.patch.object(embargo, "lift_one", side_effect=extend_then_lift):
            with delta(
                "manuspectrum_embargo_lifts_total", outcome="skipped_extended"
            ) as skipped:
                report, _ = self.go(LIFT_TIME)
        row.refresh_from_db()
        self.assertEqual(report.skipped_extended, [str(self.resource_x.pk)])
        self.assertEqual(skipped.value, 1)
        self.assertEqual(row.state, Embargo.ACTIVE)
        self.assertFalse(self.readable(self.resource_x))
        self.assertEqual(mail.outbox, [])

    def test_an_analysis_of_a_visible_project_is_lifted(self):
        project = self.resource("project", creator=self.creator, name="Project P")
        analysis = self.analysis_of(project, self.creator)
        self.restrict(analysis, ENDS)
        report, _ = self.go(LIFT_TIME)
        self.assertEqual(report.lifted, [str(analysis.pk)])

    def test_an_analysis_under_a_hidden_project_is_lifted_incomplete(self):
        project = self.resource("project", creator=self.creator, name="Project P")
        analysis = self.analysis_of(project, self.creator)
        self.restrict(project)
        self.restrict(analysis, ENDS)
        mail.outbox.clear()
        with delta("manuspectrum_embargo_lifts_total", outcome="incomplete") as bad:
            report, _ = self.go(LIFT_TIME)
        self.assertEqual(report.incomplete, [str(analysis.pk)])
        self.assertEqual(bad.value, 1)
        row = Embargo.objects.get(resourceinstance=analysis)
        self.assertEqual(row.events.last().kind, EmbargoEvent.LIFT_INCOMPLETE)
        self.assertEqual(mail.outbox, [])

    def test_a_restriction_the_pass_cannot_remove_is_incomplete_and_stays_active(self):
        self.restrict(self.resource_x, ENDS)
        with mock.patch.object(embargo, "remove_visitor_grants"):
            report, _ = self.go(LIFT_TIME)
        self.assertEqual(report.incomplete, [str(self.resource_x.pk)])
        self.assertEqual(Embargo.objects.get().state, Embargo.ACTIVE)
        self.assertEqual(mail.outbox, [])

    def test_a_failed_lift_alerts_without_a_mail_to_the_depositor(self):
        self.restrict(self.resource_x, ENDS, by=self.setter)
        other = self.resource(creator=self.creator, name="Other")
        self.restrict(other, ENDS)
        mail.outbox.clear()
        real = embargo.remove_visitor_grants

        def fail_for_first(resource_instance):
            if resource_instance.pk == self.resource_x.pk:
                raise RuntimeError("database went away")
            return real(resource_instance)

        with mock.patch.object(embargo, "remove_visitor_grants", fail_for_first):
            with delta("manuspectrum_embargo_lifts_total", outcome="failed") as failed:
                with self.assertLogs("manuspectrum.accounts.embargo", "ERROR"):
                    report, _ = self.go(LIFT_TIME)
        self.assertEqual(failed.value, 1)
        self.assertEqual(report.failed, [str(self.resource_x.pk)])
        self.assertEqual(report.lifted, [str(other.pk)])
        self.assertFalse(self.readable(self.resource_x))
        self.assertEqual(
            Embargo.objects.get(resourceinstance=self.resource_x).state, "active"
        )
        self.assertEqual(sample("manuspectrum_embargoes", state="overdue"), 1)
        for message in mail.outbox:
            self.assertNotIn("setter@manuspectrum.test", message.to)
            self.assertNotIn("Codex X", message.body)

    def test_a_dry_run_lifts_and_sends_nothing(self):
        self.restrict(self.resource_x, ENDS)
        report, index = self.go(LIFT_TIME, apply=False)
        self.assertEqual(report.due, [str(self.resource_x.pk)])
        self.assertFalse(self.readable(self.resource_x))
        self.assertEqual((mail.outbox, Embargo.objects.get().state), ([], "active"))
        index.assert_not_called()

    def test_the_pass_stamps_its_success_time_only_when_it_ran(self):
        before = sample("manuspectrum_embargo_pass_timestamp_seconds")
        self.go(LIFT_TIME, apply=False)
        self.assertEqual(sample("manuspectrum_embargo_pass_timestamp_seconds"), before)
        self.go(LIFT_TIME)
        self.assertGreater(
            sample("manuspectrum_embargo_pass_timestamp_seconds"), before
        )

    def test_the_beat_task_lifts_on_the_naive_clock_of_a_deployment_without_tz(self):
        from manuspectrum.tasks import embargo_pass_task

        later = self.resource(creator=self.creator, name="Later")
        self.restrict(self.resource_x, ENDS)
        self.restrict(later, ENDS + timedelta(days=30))
        naive_now = datetime(2026, 10, 13, 7, 0)
        with mock.patch("django.utils.timezone.now", return_value=naive_now):
            with mock.patch("arches.app.models.resource.Resource.index"):
                with self.captureOnCommitCallbacks(execute=True):
                    result = embargo_pass_task()
        self.assertEqual((result["lifted"], result["failed"]), (1, 0))
        self.assertTrue(self.readable(self.resource_x))
        self.assertFalse(self.readable(later))
        self.assertEqual(sample("manuspectrum_embargoes", state="active"), 1)

    def test_the_gauges_count_each_state(self):
        soon = self.resource(creator=self.creator, name="Soon")
        later = self.resource(creator=self.creator, name="Later")
        gone = self.resource(creator=self.creator, name="Gone")
        none = self.resource(creator=self.creator, name="None")
        today = ENDS + timedelta(days=100)
        self.restrict(soon, today + timedelta(days=3))
        self.restrict(later, today + timedelta(days=200))
        self.restrict(gone, today - timedelta(days=1))
        self.restrict(none, undated=True)
        self.restrict(self.resource_x, today - timedelta(days=1))
        with mock.patch.object(embargo, "lift_due"):
            self.go(at(today))
        values = {
            state: sample("manuspectrum_embargoes", state=state)
            for state in ("active", "undated", "due_soon", "overdue")
        }
        self.assertEqual(
            values, {"active": 2, "undated": 1, "due_soon": 1, "overdue": 2}
        )


class CommandTests(PassCase):
    def test_the_command_is_a_dry_run_unless_applied(self):
        self.restrict(self.resource_x, ENDS)
        out = io.StringIO()
        with mock.patch(
            "manuspectrum.accounts.embargo.timezone.now", return_value=LIFT_TIME
        ):
            call_command("release_expired_embargoes", stdout=out)
        self.assertIn("Dry run", out.getvalue())
        self.assertIn(str(self.resource_x.pk), out.getvalue())
        self.assertEqual(Embargo.objects.get().state, Embargo.ACTIVE)

    def test_as_of_runs_the_pass_at_6_in_paris_on_that_day(self):
        self.restrict(self.resource_x, date.today() + timedelta(days=2))
        out = io.StringIO()
        call_command("release_expired_embargoes", stdout=out)
        self.assertNotIn("would be due", out.getvalue())
        tomorrow = (date.today() + timedelta(days=3)).isoformat()
        with mock.patch("arches.app.models.resource.Resource.index"):
            with self.captureOnCommitCallbacks(execute=True):
                call_command(
                    "release_expired_embargoes",
                    "--apply",
                    "--as-of",
                    tomorrow,
                    stdout=out,
                )
        self.assertEqual(Embargo.objects.get().state, Embargo.LIFTED)
        with self.assertRaises(CommandError):
            call_command("release_expired_embargoes", "--as-of", "yesterday")

    def test_as_of_with_apply_is_refused_in_production(self):
        self.restrict(self.resource_x, date.today() + timedelta(days=2))
        later = (date.today() + timedelta(days=3)).isoformat()
        with mock.patch.dict("os.environ", {"DEPLOY_ENVIRONMENT": "production"}):
            with self.assertRaises(CommandError):
                call_command(
                    "release_expired_embargoes",
                    "--apply",
                    "--as-of",
                    later,
                    stdout=io.StringIO(),
                )
            out = io.StringIO()
            call_command("release_expired_embargoes", "--as-of", later, stdout=out)
        self.assertIn("Dry run", out.getvalue())
        self.assertEqual(Embargo.objects.get().state, Embargo.ACTIVE)


class ScheduleTests(TestCase):
    def test_the_pass_is_scheduled_daily_at_6_in_paris(self):
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE["embargo-pass"]
        self.assertEqual(entry["task"], "manuspectrum.embargo_pass")
        self.assertEqual(entry["schedule"]._orig_hour, 6)
        self.assertEqual(entry["schedule"]._orig_minute, 0)
        self.assertEqual(settings.CELERY_TIMEZONE, "Europe/Paris")

    @override_settings(ACCOUNT_SUMMARY_RECIPIENTS=[])
    def test_the_task_runs_the_pass(self):
        from manuspectrum.tasks import embargo_pass_task

        self.assertEqual(embargo_pass_task()["failed"], 0)


@override_settings(ACCOUNT_SUMMARY_RECIPIENTS=SUMMARY)
class ConcurrencyTests(Fixtures, TransactionTestCase):
    serialized_rollback = True

    def setUp(self):
        self.build()
        self.resource_x = self.resource(creator=self.creator)
        self.row = self.restrict(self.resource_x, ENDS, by=self.setter)

    def captureOnCommitCallbacks(self, **kwargs):
        import contextlib

        return contextlib.nullcontext()

    def test_two_passes_in_threads_lift_once(self):
        entered = threading.Barrier(2)
        real = embargo.reconcile

        def slow_reconcile(*args, **kwargs):
            try:
                entered.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass
            return real(*args, **kwargs)

        def run(_):
            try:
                with mock.patch("arches.app.models.resource.Resource.index"):
                    return run_pass(LIFT_TIME)
            finally:
                connection.close()

        with mock.patch.object(embargo, "reconcile", slow_reconcile):
            with ThreadPoolExecutor(2) as pool:
                reports = list(pool.map(run, range(2)))
        self.assertEqual(sorted(r.locked for r in reports), [False, True])
        self.assertEqual(sum(len(r.lifted) for r in reports), 1)
        self.assertEqual(self.row.events.filter(kind=EmbargoEvent.LIFTED).count(), 1)
        creator_mails = [
            m for m in mail.outbox if m.to == ["creator@manuspectrum.test"]
        ]
        self.assertEqual(len(creator_mails), 1)

    def test_the_pass_lock_is_released_after_a_pass(self):
        with mock.patch("arches.app.models.resource.Resource.index"):
            run_pass(LIFT_TIME)
            self.assertFalse(run_pass(LIFT_TIME).locked)

    def test_two_lifts_of_one_row_in_threads_lift_once(self):
        meet = threading.Barrier(2)
        real = embargo.remove_visitor_grants

        def meeting(resource_instance):
            real(resource_instance)
            try:
                meet.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass

        def lift(_):
            try:
                with mock.patch("arches.app.models.resource.Resource.index"):
                    return embargo.lift_one(self.row.pk, LIFT_TIME)
            finally:
                connection.close()

        with mock.patch.object(embargo, "remove_visitor_grants", meeting):
            with ThreadPoolExecutor(2) as pool:
                outcomes = list(pool.map(lift, range(2)))
        self.assertEqual(sorted(o or "" for o in outcomes), ["", "lifted"])
        self.assertEqual(self.row.events.filter(kind=EmbargoEvent.LIFTED).count(), 1)
