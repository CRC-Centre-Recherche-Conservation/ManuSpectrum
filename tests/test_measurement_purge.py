"""Staging purge of measurement-files runs and the batch metrics.

python manage.py test tests.test_measurement_purge --settings="tests.test_settings"
"""

import os
import shutil
import tempfile
import uuid
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from prometheus_client import REGISTRY

from arches.app.models.models import File

from manuspectrum.measurement_files import purge, staging, writer
from manuspectrum.measurement_files.purge import LOCK_KEY
from manuspectrum.models import MeasurementItem, MeasurementRun
from manuspectrum.observability import metrics
from tests.observability_helpers import delta, sample
from tests.test_measurement_prepare import ELIO, PrepareCase
from tests.test_measurement_undo import UndoCase

FILES = "manuspectrum_measurement_files_total"
RUNS = "manuspectrum_measurement_runs_total"
STAMP = "manuspectrum_measurement_purge_timestamp_seconds"


class PurgeCase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user("purger", password="x")
        cache.delete(LOCK_KEY)

    def run_of(self, state, age_days):
        run = MeasurementRun.objects.create(
            id=uuid.uuid4(),
            user=self.user,
            document_id=uuid.uuid4(),
            language="en",
            state=state,
        )
        when = timezone.now() - timedelta(days=age_days)
        MeasurementRun.objects.filter(pk=run.pk).update(updated_at=when)
        return run

    def item_of(self, run, state="prepared", **extra):
        item = MeasurementItem.objects.create(
            run=run,
            origin="upload",
            source_name="a.mca",
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            size=3,
            state=state,
            **extra,
        )
        staging.store(run.id, item.id, b"raw", "a.mca")
        return item

    def staged(self, run):
        return os.path.isdir(
            os.path.join(self.media, "measurement-staging", str(run.id))
        )

    def uploaded(self, name, *, age_days=3):
        directory = os.path.join(self.media, "uploadedfiles")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, name)
        with open(path, "wb") as handle:
            handle.write(b"bytes")
        old = (timezone.now() - timedelta(days=age_days)).timestamp()
        os.utime(path, (old, old))
        return path

    def stamp(self):
        return sample(STAMP)


class WhatGoesTests(PurgeCase):
    def test_an_old_run_not_written_loses_its_staging_and_its_rows(self):
        old = self.run_of("review", 31)
        item = self.item_of(old)
        recent = self.run_of("review", 5)
        kept = self.item_of(recent)
        report = purge.purge()
        self.assertFalse(self.staged(old))
        self.assertFalse(MeasurementRun.objects.filter(pk=old.pk).exists())
        self.assertFalse(MeasurementItem.objects.filter(pk=item.pk).exists())
        self.assertTrue(self.staged(recent))
        self.assertTrue(MeasurementItem.objects.filter(pk=kept.pk).exists())
        self.assertEqual(report.runs_deleted, [str(old.id)])

    def test_an_old_written_or_undone_run_loses_its_staging_only(self):
        runs = [self.run_of("written", 40), self.run_of("undone", 40)]
        items = [self.item_of(run, state="written") for run in runs]
        report = purge.purge()
        for run, item in zip(runs, items):
            with self.subTest(state=run.state):
                self.assertFalse(self.staged(run))
                self.assertTrue(MeasurementRun.objects.filter(pk=run.pk).exists())
                self.assertTrue(MeasurementItem.objects.filter(pk=item.pk).exists())
        self.assertEqual(
            sorted(report.staging_removed), sorted(str(r.id) for r in runs)
        )
        self.assertEqual(report.runs_deleted, [])

    def test_an_old_run_not_written_that_holds_written_items_keeps_its_rows(self):
        stuck = self.run_of("writing", 60)
        item = self.item_of(stuck, state="written")
        purge.purge()
        self.assertFalse(self.staged(stuck))
        self.assertTrue(MeasurementItem.objects.filter(pk=item.pk).exists())

    def test_the_age_is_measured_from_the_setting(self):
        run = self.run_of("review", 5)
        self.item_of(run)
        with override_settings(MEASUREMENT_STAGING_DAYS=3):
            purge.purge()
        self.assertFalse(MeasurementRun.objects.filter(pk=run.pk).exists())

    def test_a_dry_run_writes_nothing_and_reports_what_would_go(self):
        old = self.run_of("review", 31)
        item = self.item_of(old)
        orphan = self.uploaded(f"{item.id}-a.mca")
        before = self.stamp()
        with delta(RUNS, outcome="purged") as moved:
            report = purge.purge(apply=False)
        self.assertEqual(moved.value, 0)
        self.assertTrue(self.staged(old))
        self.assertTrue(MeasurementRun.objects.filter(pk=old.pk).exists())
        self.assertTrue(os.path.exists(orphan))
        self.assertEqual(self.stamp(), before)
        self.assertEqual(report.runs_deleted, [str(old.id)])
        self.assertEqual(report.orphans, [os.path.basename(orphan)])
        self.assertFalse(report.applied)


class OrphanTests(PurgeCase):
    def setUp(self):
        super().setUp()
        self.run = self.run_of("written", 1)
        self.item = self.item_of(self.run, state="written")

    def test_an_unreferenced_stored_name_of_an_item_is_removed(self):
        path = self.uploaded(f"{self.item.id}-X7.mca")
        report = purge.purge()
        self.assertFalse(os.path.exists(path))
        self.assertEqual(report.orphans, [os.path.basename(path)])

    def test_a_file_row_keeps_its_bytes(self):
        row = File(fileid=uuid.uuid4())
        row.path.save(f"{self.item.id}-X7.mca", ContentFile(b"x"), save=False)
        File.objects.bulk_create([row])
        path = os.path.join(self.media, row.path.name)
        os.utime(path, (1, 1))
        purge.purge()
        self.assertTrue(os.path.exists(path))

    def test_a_name_of_no_known_item_stays(self):
        path = self.uploaded(f"{uuid.uuid4()}-X7.mca")
        other = self.uploaded("plain-upload.csv")
        purge.purge()
        self.assertTrue(os.path.exists(path))
        self.assertTrue(os.path.exists(other))

    def test_a_name_written_within_the_grace_period_stays(self):
        path = self.uploaded(f"{self.item.id}-X7.mca", age_days=0)
        purge.purge()
        self.assertTrue(os.path.exists(path))

    def test_the_items_of_a_run_deleted_by_the_same_pass_are_covered(self):
        old = self.run_of("review", 31)
        item = self.item_of(old)
        path = self.uploaded(f"{item.id}-X7.mca")
        purge.purge()
        self.assertFalse(os.path.exists(path))


class StampTests(PurgeCase):
    def test_an_applied_pass_sets_the_gauge(self):
        before = self.stamp()
        purge.purge()
        self.assertGreater(self.stamp(), before)

    def test_a_dry_run_does_not(self):
        before = self.stamp()
        purge.purge(apply=False)
        self.assertEqual(self.stamp(), before)

    def test_a_pass_that_finds_the_lock_taken_does_nothing(self):
        old = self.run_of("review", 31)
        self.item_of(old)
        before = self.stamp()
        cache.set(LOCK_KEY, "someone", 60)
        report = purge.purge()
        self.assertTrue(report.locked)
        self.assertTrue(self.staged(old))
        self.assertEqual(self.stamp(), before)


class MetricTests(PurgeCase):
    def test_a_purged_run_is_counted(self):
        self.item_of(self.run_of("review", 31))
        with delta(RUNS, outcome="purged") as moved:
            purge.purge()
        self.assertEqual(moved.value, 1)


class SurfaceTests(PurgeCase):
    def test_the_task_returns_the_counts(self):
        from manuspectrum.tasks import measurement_staging_purge_task

        self.item_of(self.run_of("review", 31))
        result = measurement_staging_purge_task()
        self.assertEqual(result["runs_deleted"], 1)
        self.assertFalse(result["locked"])

    def test_the_beat_entry_runs_daily_at_0515_with_a_start_deadline(self):
        entry = settings.CELERY_BEAT_SCHEDULE["measurement-staging-purge"]
        self.assertEqual(entry["task"], "manuspectrum.measurement_staging_purge")
        self.assertEqual(
            (entry["schedule"].hour, entry["schedule"].minute), ({5}, {15})
        )
        self.assertEqual(
            entry["options"], {"expires": settings.CELERY_BEAT_CRON_STARTING_DEADLINE}
        )

    def test_the_command_is_a_dry_run_unless_applied(self):
        old = self.run_of("review", 31)
        self.item_of(old)
        out = StringIO()
        call_command("purge_measurement_staging", stdout=out)
        self.assertIn("Dry run", out.getvalue())
        self.assertTrue(self.staged(old))
        call_command("purge_measurement_staging", "--apply", stdout=StringIO())
        self.assertFalse(self.staged(old))


class PreparedCountTests(PrepareCase):
    def test_a_converted_file_counts_by_format_and_outcome(self):
        self.upload("X7_f1r.mca", ELIO)
        with delta(FILES, format="elio_mca", outcome="csv") as moved:
            self.prepare_all()
        self.assertEqual(moved.value, 1)

    def test_an_unreadable_file_counts_under_its_format(self):
        from tests.test_measurement_prepare import elio_mca

        self.upload("X7_f1r.mca", elio_mca([1]))
        with delta(FILES, format="elio_mca", outcome="unreadable") as moved:
            self.prepare_all()
        self.assertEqual(moved.value, 1)

    def test_an_unknown_format_folds_into_other(self):
        from tests.test_measurement_prepare import WDF

        self.upload("R5_f1r.wdf", WDF)
        with delta(FILES, format="other", outcome="unsupported") as moved:
            self.prepare_all()
        self.assertEqual(moved.value, 1)

    def test_a_file_that_is_not_a_measure_counts_nowhere(self):
        self.upload("notes.pdf", b"%PDF-1.4\n%binary \xff\xfe\x00 stream")
        with mock.patch.object(metrics, "measurement_file") as counted:
            self.prepare_all()
        counted.assert_not_called()


class WrittenCountTests(UndoCase):
    def test_a_written_item_and_its_run_are_counted(self):
        self.make_item(self.target, detected_format="elio_mca")
        with (
            delta(FILES, format="elio_mca", outcome="written") as files,
            delta(RUNS, outcome="written") as runs,
        ):
            self.write()
        self.assertEqual((files.value, runs.value), (1, 1))

    def test_a_failed_item_is_counted(self):
        self.make_item(self.target, detected_format="elio_mca")
        with (
            mock.patch.object(writer, "_write_item", side_effect=RuntimeError("boom")),
            delta(FILES, format="elio_mca", outcome="failed") as moved,
        ):
            self.write()
        self.assertEqual(moved.value, 1)

    def test_a_failure_of_the_counter_never_reaches_the_write(self):
        self.make_item(self.target, detected_format="elio_mca")
        with mock.patch.object(
            metrics.MEASUREMENT_FILES, "labels", side_effect=RuntimeError
        ):
            self.write()
        self.assertEqual(self.run.state, "written")


class UndoneCountTests(UndoCase):
    def test_a_removed_item_and_the_run_are_counted(self):
        self.make_item(self.target, detected_format="elio_mca")
        self.written()
        with (
            delta(FILES, format="elio_mca", outcome="removed") as files,
            delta(RUNS, outcome="undone") as runs,
        ):
            self.undo()
        self.assertEqual((files.value, runs.value), (1, 1))

    def test_a_kept_item_is_counted(self):
        self.make_item(self.target, detected_format="elio_mca")
        self.written()
        self.edit_csv(self.target)
        with delta(FILES, format="elio_mca", outcome="kept") as moved:
            self.undo()
        self.assertEqual(moved.value, 1)


class VocabularyTests(TestCase):
    def test_the_formats_are_the_converter_formats(self):
        from manuspectrum.measurement_files.converters import (
            asd,
            bruker_spx,
            delimited,
            elio_mca,
            galactic_spc,
            mzxml,
            opus,
        )

        modules = (asd, bruker_spx, delimited, elio_mca, galactic_spc, mzxml, opus)
        self.assertEqual(set(metrics.MEASUREMENT_FORMATS), {m.FORMAT for m in modules})

    def test_a_csv_counts_as_delimited_and_an_unknown_name_as_other(self):
        with delta(FILES, format="delimited", outcome="csv") as moved:
            metrics.measurement_file("csv", "csv")
        self.assertEqual(moved.value, 1)
        with delta(FILES, format="other", outcome="other") as moved:
            metrics.measurement_file("evil", "evil")
        self.assertEqual(moved.value, 1)

    def test_every_label_set_is_primed(self):
        metrics.prime_label_sets()
        for name, labels in (
            (FILES, {"format": "asd", "outcome": "removed"}),
            (FILES, {"format": "other", "outcome": "kept"}),
            (RUNS, {"outcome": "purged"}),
        ):
            self.assertIsNotNone(REGISTRY.get_sample_value(name, labels), labels)
