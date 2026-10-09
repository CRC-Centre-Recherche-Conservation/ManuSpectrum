import json
import uuid
from datetime import datetime, timedelta, timezone
from io import StringIO
from zoneinfo import ZoneInfo

from arches.app.models.models import (
    EditLog,
    ETLModule,
    GraphModel,
    LoadEvent,
    ResourceInstance,
    WorkflowHistory,
)
from celery.signals import worker_ready
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DatabaseError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from unittest.mock import patch

from manuspectrum import tasks
from manuspectrum.observability import activity, celery_signals, metrics
from tests.explorer_fixtures import ACTIVE, LIFECYCLE
from tests.observability_helpers import sample

UTC = timezone.utc
START = datetime(2026, 9, 1, tzinfo=UTC)
END = datetime(2026, 10, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
LOCAL = ZoneInfo(settings.TIME_ZONE)


def local(moment):
    """The naive local time Arches stores for a UTC instant (USE_TZ = False)."""
    return moment.astimezone(LOCAL).replace(tzinfo=None)


def graph(slug, system=False):
    return GraphModel.objects.create(
        graphid=uuid.uuid4(),
        name=slug,
        slug=slug,
        isresource=True,
        is_active=True,
        resource_instance_lifecycle_id=LIFECYCLE,
    )


class ActivityCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.analysis = graph("analysis")
        cls.sample = graph("sample")
        cls.system = graph(activity.SYSTEM_GRAPH_SLUG)
        cls.stranger = graph("someting_else")
        cls.when = START + timedelta(days=5)

    def log(self, model, resource, edittype, note=None, at=None, user="u"):
        return EditLog.objects.create(
            resourceclassid=str(model.graphid),
            resourceinstanceid=str(resource),
            edittype=edittype,
            note=note,
            timestamp=local(at or self.when),
            user_email=f"{user}@manuspectrum.test",
            userid="12",
            user_username=user,
        )

    def figures(self, start=START, end=END, now=NOW):
        return activity.collect(start, end, now)


class ChangesTests(ActivityCase):
    def test_a_resource_created_by_several_saves_counts_once(self):
        res = uuid.uuid4()
        for _ in range(3):
            self.log(self.analysis, res, "create")
        row = self.figures()["models"]["analysis"]
        self.assertEqual(row["created"], 1)

    def test_a_biblissima_resource_has_no_create_row_only_noted_tile_rows(self):
        res = uuid.uuid4()
        self.log(self.analysis, res, "tile create", "resource creation")
        self.log(self.analysis, res, "tile create", "resource creation")
        row = self.figures()["models"]["analysis"]
        self.assertEqual(
            (row["created"], row["modified"], row["tile_saves"]), (1, 0, 0)
        )

    def test_cards_saved_after_the_creation_are_not_modifications(self):
        res = uuid.uuid4()
        self.log(self.analysis, res, "create")
        self.log(self.analysis, res, "tile create")
        self.log(self.analysis, res, "tile edit")
        row = self.figures()["models"]["analysis"]
        self.assertEqual(
            (row["created"], row["modified"], row["tile_saves"]), (1, 0, 2)
        )

    def test_an_existing_resource_edited_twice_is_modified_once(self):
        res = uuid.uuid4()
        self.log(self.analysis, res, "tile edit")
        self.log(self.analysis, res, "tile delete")
        row = self.figures()["models"]["analysis"]
        self.assertEqual(
            (row["created"], row["modified"], row["tile_saves"]), (0, 1, 2)
        )

    def test_created_then_deleted_in_the_window_counts_both(self):
        res = uuid.uuid4()
        self.log(self.analysis, res, "create")
        self.log(self.analysis, res, "delete")
        row = self.figures()["models"]["analysis"]
        self.assertEqual(
            (row["created"], row["created_deleted"], row["deleted"]), (1, 1, 1)
        )

    def test_a_deletion_of_an_older_resource_is_not_created_deleted(self):
        self.log(self.analysis, uuid.uuid4(), "delete")
        row = self.figures()["models"]["analysis"]
        self.assertEqual(
            (row["created"], row["created_deleted"], row["deleted"]), (0, 0, 1)
        )

    def test_publication_changes_are_counted_by_model(self):
        self.log(self.sample, uuid.uuid4(), "update_resource_instance_lifecycle_state")
        self.assertEqual(self.figures()["models"]["sample"]["publication_changes"], 1)

    def test_the_system_settings_graph_is_left_out(self):
        self.log(self.system, uuid.uuid4(), "create")
        ResourceInstance.objects.create(graph=self.system)
        self.assertNotIn(activity.SYSTEM_GRAPH_SLUG, self.figures()["models"])

    def test_rows_of_a_deleted_graph_are_grouped_under_one_name(self):
        for _ in range(2):
            EditLog.objects.create(
                resourceclassid=str(uuid.uuid4()),
                resourceinstanceid=str(uuid.uuid4()),
                edittype="delete",
                timestamp=local(self.when),
            )
        row = self.figures()["models"][activity.DELETED_MODEL]
        self.assertEqual(row["deleted"], 2)

    def test_the_window_is_in_utc_not_in_the_local_zone(self):
        res = uuid.uuid4()
        late_september_chicago = datetime(2026, 10, 1, 1, 0, tzinfo=UTC)
        self.assertEqual(local(late_september_chicago).month, 9)
        self.log(self.analysis, res, "create", at=late_september_chicago)
        september = activity.collect(START, END, NOW)["models"]
        october = activity.collect(END, datetime(2026, 11, 1, tzinfo=UTC), NOW)
        self.assertNotIn("analysis", september)
        self.assertEqual(october["models"]["analysis"]["created"], 1)

    def test_the_end_of_the_window_is_excluded(self):
        self.log(self.analysis, uuid.uuid4(), "create", at=END)
        self.assertNotIn("analysis", self.figures()["models"])

    def test_totals_come_from_the_resource_table(self):
        before = self.figures()["models"].get("sample", {}).get("total", 0)
        for _ in range(2):
            ResourceInstance.objects.create(
                graph=self.sample, resource_instance_lifecycle_state_id=ACTIVE
            )
        self.assertEqual(self.figures()["models"]["sample"]["total"], before + 2)

    def test_nothing_personal_leaves_the_figures(self):
        res = uuid.uuid4()
        self.log(self.analysis, res, "create", user="curator")
        text = json.dumps(self.figures())
        for forbidden in ("curator", "manuspectrum.test", str(res)):
            self.assertNotIn(forbidden, text)


class WorkflowAndEtlTests(ActivityCase):
    def run_row(self, name, created, completed):
        return WorkflowHistory.objects.create(
            workflowid=uuid.uuid4(),
            workflowname=name,
            created=local(created),
            completed=completed,
        )

    def test_started_completed_open_and_stale(self):
        name = "create-project-workflow"
        self.run_row(name, START + timedelta(days=2), True)
        self.run_row(name, START + timedelta(days=3), False)
        self.run_row(name, START - timedelta(days=60), False)
        self.run_row(name, START - timedelta(days=60), True)
        row = self.figures()["workflows"][name]
        self.assertEqual(row, {"started": 2, "completed": 1, "open": 2, "stale": 2})

    def test_an_open_run_younger_than_the_delay_is_not_stale(self):
        name = "import-biblissima-workflow"
        self.run_row(
            name, NOW - timedelta(days=activity.WORKFLOW_STALE_AFTER_DAYS - 1), False
        )
        self.assertEqual(self.figures()["workflows"][name]["stale"], 0)

    def load(self, slug, status, at):
        module = ETLModule.objects.filter(
            slug=slug
        ).first() or ETLModule.objects.create(
            name=slug,
            slug=slug,
            etl_type="import",
            component="c",
            componentname="c",
            modulename="m.py",
            classname="M",
            config={},
            icon="i",
            helpsortorder=1,
            helptemplate="t",
            reversible=False,
        )
        user = get_user_model().objects.get_or_create(username="etl-user")[0]
        return LoadEvent.objects.create(
            etl_module=module, user=user, status=status, load_start_time=local(at)
        )

    def test_etl_runs_by_module_and_outcome(self):
        at = START + timedelta(days=4)
        self.load("import-single-csv", "indexed", at)
        self.load("import-single-csv", "failed", at)
        self.load("import-single-csv", "running", at)
        self.load("import-single-csv", "indexed", START - timedelta(days=1))
        row = self.figures()["etl"]["import-single-csv"]
        self.assertEqual(
            row,
            {
                "started": 3,
                "succeeded": 1,
                "failed": 1,
                "unindexed": 0,
                "unloaded": 0,
                "validated": 0,
                "unfinished": 1,
            },
        )

    def test_every_terminal_status_arches_writes_has_its_own_count(self):
        at = START + timedelta(days=4)
        for status in (
            "completed",
            "indexed",
            "unindexed",
            "unloaded",
            "validated",
            "validated",
            "failed",
            "running",
            "reversing",
        ):
            self.load("import-single-csv", status, at)
        row = self.figures()["etl"]["import-single-csv"]
        self.assertEqual(
            row,
            {
                "started": 9,
                "succeeded": 2,
                "failed": 1,
                "unindexed": 1,
                "unloaded": 1,
                "validated": 2,
                "unfinished": 2,
            },
        )


class ReadOnlyTests(ActivityCase):
    def test_a_write_inside_the_block_is_refused_and_allowed_after_it(self):
        with self.assertRaises(DatabaseError):
            with activity.read_only_cursor() as cursor:
                cursor.execute("DELETE FROM edit_log WHERE false")
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM edit_log WHERE false")

    def test_the_block_bounds_its_statements_and_restores_the_setting(self):
        def timeout():
            with connection.cursor() as cursor:
                cursor.execute("SHOW statement_timeout")
                return cursor.fetchone()[0]

        before = timeout()
        with activity.read_only_cursor() as cursor:
            cursor.execute("SHOW statement_timeout")
            self.assertEqual(cursor.fetchone()[0], activity.STATEMENT_TIMEOUT)
        self.assertEqual(timeout(), before)

    def test_collect_only_reads(self):
        with CaptureQueriesContext(connection) as captured:
            self.figures()
        statements = [q["sql"].lstrip().split(None, 1)[0].upper() for q in captured]
        self.assertTrue(statements)
        self.assertLessEqual(
            set(statements),
            {"SELECT", "WITH", "SET", "SAVEPOINT", "ROLLBACK", "RELEASE"},
        )
        self.assertTrue(
            all(
                s == "SELECT"
                or s == "WITH"
                or q["sql"].startswith(
                    ("SET LOCAL", "SAVEPOINT", "ROLLBACK", "RELEASE")
                )
                for s, q in zip(statements, captured)
            )
        )


class MonthTests(ActivityCase):
    def test_the_window_of_a_month_is_utc_and_december_rolls_over(self):
        self.assertEqual(
            activity.month_window("2026-12")[1], datetime(2027, 1, 1, tzinfo=UTC)
        )
        self.assertEqual(
            activity.month_window("2026-02")[0], datetime(2026, 2, 1, tzinfo=UTC)
        )

    def test_a_bad_month_is_refused(self):
        for label in ("2026-13", "26-01", "", None, "2026-1"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                activity.month_window(label)

    def test_the_command_prints_json_totals(self):
        self.log(self.analysis, uuid.uuid4(), "create")
        out = StringIO()
        call_command("activity_summary", month="2026-09", stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["month"], "2026-09")
        self.assertEqual(data["models"]["analysis"]["created"], 1)
        self.assertEqual(
            set(data),
            {
                "month",
                "start",
                "end",
                "models",
                "workflows",
                "workflow_stale_after_days",
                "etl",
            },
        )

    def test_the_command_refuses_a_bad_month(self):
        with self.assertRaises(CommandError):
            call_command("activity_summary", month="2026-00", stdout=StringIO())


class GaugeTests(ActivityCase):
    def test_changes_of_the_last_24_hours_set_the_gauges_by_model_and_kind(self):
        recent = NOW - timedelta(hours=3)
        old = NOW - timedelta(hours=30)
        self.log(self.analysis, uuid.uuid4(), "create", at=recent)
        self.log(self.analysis, uuid.uuid4(), "tile edit", at=recent)
        self.log(self.analysis, uuid.uuid4(), "delete", at=recent)
        self.log(self.analysis, uuid.uuid4(), "create", at=old)
        activity.publish_gauges(NOW)
        for kind in ("created", "modified", "deleted"):
            self.assertEqual(
                sample("manuspectrum_resource_changes", model="analysis", kind=kind), 1
            )

    def test_an_unknown_model_is_folded_to_other_and_zero_models_are_set(self):
        recent = NOW - timedelta(hours=1)
        self.log(self.stranger, uuid.uuid4(), "create", at=recent)
        activity.publish_gauges(NOW)
        self.assertEqual(
            sample("manuspectrum_resource_changes", model="other", kind="created"), 1
        )
        self.assertEqual(
            sample("manuspectrum_resource_changes", model="person", kind="created"), 0
        )

    def test_a_stale_value_is_replaced_by_the_next_run(self):
        self.log(self.analysis, uuid.uuid4(), "create", at=NOW - timedelta(hours=1))
        activity.publish_gauges(NOW)
        activity.publish_gauges(NOW + timedelta(days=2))
        self.assertEqual(
            sample("manuspectrum_resource_changes", model="analysis", kind="created"), 0
        )

    def test_resources_per_model(self):
        ResourceInstance.objects.create(
            graph=self.analysis, resource_instance_lifecycle_state_id=ACTIVE
        )
        ResourceInstance.objects.create(
            graph=self.stranger, resource_instance_lifecycle_state_id=ACTIVE
        )
        activity.publish_gauges(NOW)
        self.assertGreaterEqual(sample("manuspectrum_resources", model="analysis"), 1)
        self.assertGreaterEqual(sample("manuspectrum_resources", model="other"), 1)

    def test_workflows_open_and_stale(self):
        for age in (1, 45):
            WorkflowHistory.objects.create(
                workflowid=uuid.uuid4(),
                workflowname="create-project-workflow",
                created=local(NOW - timedelta(days=age)),
                completed=False,
            )
        WorkflowHistory.objects.create(
            workflowid=uuid.uuid4(),
            workflowname="unheard-of",
            created=local(NOW),
            completed=False,
        )
        activity.publish_gauges(NOW)
        labels = {"kind": "create-project-workflow"}
        self.assertEqual(sample("manuspectrum_workflows", state="open", **labels), 2)
        self.assertEqual(sample("manuspectrum_workflows", state="stale", **labels), 1)
        self.assertEqual(
            sample("manuspectrum_workflows", state="open", kind="other"), 1
        )

    def test_the_last_run_time_is_set(self):
        activity.publish_gauges(NOW)
        self.assertEqual(
            sample("manuspectrum_activity_timestamp_seconds"), NOW.timestamp()
        )

    def test_the_vocabularies_match_the_labels(self):
        self.assertLessEqual({"model", "state", "kind"}, metrics.ALLOWED_LABELS)
        self.assertEqual(len(metrics.RESOURCE_MODELS), 12)


class TaskTests(TestCase):
    def test_the_task_publishes_the_gauges(self):
        with patch.object(activity, "publish_gauges") as publish:
            tasks.record_activity_task()
        publish.assert_called_once_with()

    def test_the_task_runs_every_hour(self):
        entry = settings.CELERY_BEAT_SCHEDULE["record-activity"]
        self.assertEqual(entry["task"], "manuspectrum.record_activity")
        self.assertEqual(entry["schedule"], 3600)

    def test_worker_start_sets_the_gauges_and_survives_an_error(self):
        with (
            patch.object(activity, "publish_gauges") as publish,
            patch("django.db.connections.close_all") as close,
        ):
            worker_ready.send(sender=None)
        publish.assert_called_once_with()
        close.assert_called()
        with (
            patch.object(activity, "publish_gauges", side_effect=RuntimeError),
            patch("django.db.connections.close_all") as close,
            patch.object(metrics.RESOURCES, "labels") as resources,
            patch.object(metrics.ACTIVITY_MEASURED, "set") as measured,
            self.assertLogs(
                "manuspectrum.observability.celery_signals", "WARNING"
            ) as logs,
        ):
            celery_signals.record_activity_gauges()
        self.assertIn("activity gauges not set", logs.output[0])
        resources.assert_not_called()
        measured.assert_not_called()
        close.assert_called()
