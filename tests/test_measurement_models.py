import uuid

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from manuspectrum.models import (
    MeasurementDecision,
    MeasurementItem,
    MeasurementNameCode,
    MeasurementRun,
)


class MeasurementModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("meas", password="x")
        self.run = MeasurementRun.objects.create(
            id=uuid.uuid4(), user=self.user, document_id=uuid.uuid4(), language="en"
        )

    def _item(self, **kw):
        values = dict(
            run=self.run,
            origin="upload",
            source_name="a.0",
            sha256="a" * 64,
            size=3,
        )
        values.update(kw)
        return MeasurementItem.objects.create(**values)

    def test_run_defaults_and_stop_flag(self):
        run = MeasurementRun.objects.get(pk=self.run.pk)
        self.assertEqual(run.state, "collecting")
        self.assertFalse(run.stop_requested)
        self.assertIsNotNone(run.transaction_id)
        self.assertIsNone(run.finished_at)

    def test_transaction_id_unique(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            MeasurementRun.objects.create(
                id=uuid.uuid4(),
                user=self.user,
                document_id=uuid.uuid4(),
                language="fr",
                transaction_id=self.run.transaction_id,
            )

    def test_item_round_trip_defaults(self):
        item = self._item(facts=[["k", "v", ""]])
        item = MeasurementItem.objects.get(pk=item.pk)
        self.assertEqual(item.facts, [["k", "v", ""]])
        self.assertEqual(item.outcome, "pending")
        self.assertEqual(item.decision, "pending")
        self.assertEqual(item.state, "queued")
        self.assertEqual(item.written, {})
        self.assertEqual(list(self.run.items.all()), [item])

    def test_duplicate_sha_in_run_refused(self):
        self._item()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._item(source_name="b.0")

    def test_same_sha_in_other_run_allowed(self):
        self._item()
        other = MeasurementRun.objects.create(
            id=uuid.uuid4(), user=self.user, document_id=uuid.uuid4(), language="en"
        )
        self._item(run=other)

    def test_stored_source_file_unique_in_run(self):
        file_id = uuid.uuid4()
        self._item(origin="stored", source_file_id=file_id, sha256="b" * 64)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._item(origin="stored", source_file_id=file_id, sha256="c" * 64)

    def test_stored_items_may_share_sha(self):
        self._item(origin="stored", source_file_id=uuid.uuid4())
        self._item(origin="stored", source_file_id=uuid.uuid4())

    def test_paired_item_self_reference(self):
        raw = self._item()
        lab = self._item(sha256="d" * 64, paired_item=raw)
        self.assertEqual(lab.paired_item, raw)

    def test_decision_ordering_newest_first(self):
        first = MeasurementDecision.objects.create(run=self.run, action="a", before={})
        second = MeasurementDecision.objects.create(run=self.run, action="b", before={})
        self.assertEqual(
            list(MeasurementDecision.objects.filter(run=self.run)), [second, first]
        )

    def test_name_code_unique_case_insensitive_per_user(self):
        MeasurementNameCode.objects.create(user=self.user, code="Xy", family="fors")
        with self.assertRaises(IntegrityError), transaction.atomic():
            MeasurementNameCode.objects.create(user=self.user, code="xY", family="ftir")
        other = User.objects.create_user("meas2", password="x")
        MeasurementNameCode.objects.create(user=other, code="xy", family="ignore")

    def test_table_names(self):
        self.assertEqual(MeasurementRun._meta.db_table, "ms_measurement_run")
        self.assertEqual(MeasurementItem._meta.db_table, "ms_measurement_item")
        self.assertEqual(MeasurementDecision._meta.db_table, "ms_measurement_decision")
        self.assertEqual(MeasurementNameCode._meta.db_table, "ms_measurement_name_code")
