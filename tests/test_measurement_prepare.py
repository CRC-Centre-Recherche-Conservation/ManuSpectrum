import io
import json
import uuid
from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from manuspectrum.constants.xy_presets import TECHNIQUE_PRESETS, XY_PRESETS
from manuspectrum.measurement_files import catalogue, intake, prepare, staging
from manuspectrum.models import MeasurementItem, MeasurementNameCode, MeasurementRun
from manuspectrum.tasks import measurement_prepare_task
from tests import test_measurement_catalogue as base
from tests.measurement_fixtures import FIXTURES, elio_mca

CONTRACT = FIXTURES / "contract"


def technique_item(preset):
    return next(i for i, p in TECHNIQUE_PRESETS.items() if p == preset)


def counts(seed=0, n=60):
    return [(i * 7 + seed) % 97 + 1 for i in range(n)]


ELIO = elio_mca(counts())
ELIO_NO_CAL = elio_mca(counts(3), calibration=((0, "0"), (0, "0")))
OPUS = (FIXTURES / "indores_albi" / "IR1_parchment.0").read_bytes()
WDF = b"WDF1" + bytes(64)


class PrepareCase(base.CatalogueCase):
    """Catalogue of ``CatalogueCase`` plus analyses on ``f. 1r`` named by technique and number."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.tile_values(
            cls.document,
            "document",
            value_of_identifier=cls.string_value("Ms 59"),
            type_of_identifier=cls.reference_value(
                "https://example.org/shelfmark", "Shelfmark"
            ),
        )
        cls.targets = {}
        for key, name, preset in (
            ("xrf7", "X 7", "xrf"),
            ("xrf8", "X 8", "xrf"),
            ("xrf9", "X 9", "xrf"),
            ("xrf10", "X 10", "xrf"),
            ("xrf11", "X 11", "xrf"),
            ("ir3", "IR 3", "ftir"),
            ("f2", "F 2", "fors"),
            ("r5", "R 5", "raman"),
            ("blank", "R 6", None),
        ):
            analysis = cls.new_resource("analysis", name)
            cls.tile(analysis, "component_observed", cls.refs(cls.comp1))
            if preset:
                cls.tile(
                    analysis, "analysis_technique_used", [cls.technique_entry(preset)]
                )
            cls.targets[key] = analysis

    @staticmethod
    def technique_entry(preset):
        item = technique_item(preset)
        return {
            "uri": f"https://example.org/{preset}",
            "list_id": str(uuid.uuid4()),
            "labels": [
                {
                    "id": str(uuid.uuid4()),
                    "value": preset,
                    "language_id": "en",
                    "list_item_id": item,
                    "valuetype_id": "prefLabel",
                }
            ],
        }

    def setUp(self):
        super().setUp()
        self.run = MeasurementRun.objects.create(
            id=uuid.uuid4(),
            user=self.editor,
            document_id=self.document.pk,
            language="en",
            state="preparing",
        )

    def upload(self, name, data, relative_dir=""):
        item = intake.accept_upload(self.run, name, relative_dir, io.BytesIO(data))
        self.assertIsInstance(item, MeasurementItem, item)
        return item

    def prepare_all(self):
        while prepare.prepare_run(self.run):
            pass
        self.run.refresh_from_db()

    def item(self, item):
        item.refresh_from_db()
        return item

    def target(self, key):
        return str(self.targets[key].pk)

    def config(self, preset):
        return uuid.UUID(XY_PRESETS[preset]["config_id"])


class ConversionTests(PrepareCase):
    def test_a_converted_file_is_ready_on_the_technique_display(self):
        item = self.upload("X7_f1r.mca", ELIO)
        self.prepare_all()
        item = self.item(item)
        self.assertEqual(self.run.state, "review")
        self.assertEqual(
            (item.outcome, item.detected_format, item.content_preset, item.state),
            ("csv", "elio_mca", "xrf", "prepared"),
        )
        self.assertEqual(str(item.proposed_analysis_id), self.target("xrf7"))
        self.assertEqual((item.decision, item.cause), ("ready", ""))
        self.assertEqual(item.display_config_id, self.config("xrf"))
        self.assertEqual(item.display_source, "technique")
        self.assertIn("tube_voltage", {f["key"] for f in item.facts})
        self.assertTrue(item.tokens)
        csv = staging.read(self.run.id, f"{item.id}-converted.csv").decode()
        self.assertTrue(csv.startswith("channel") or csv.startswith("energy"))
        description = json.loads(
            staging.read(self.run.id, f"{item.id}-description.json")
        )
        self.assertEqual(set(description), {"en", "fr"})

    def test_a_file_without_calibration_gets_the_channel_display(self):
        item = self.upload("X8_f1r.mca", ELIO_NO_CAL)
        self.prepare_all()
        item = self.item(item)
        self.assertEqual(item.content_preset, "xrf_channel")
        self.assertEqual(item.display_config_id, self.config("xrf_channel"))
        self.assertEqual(item.display_source, "converter")
        self.assertEqual((item.decision, item.cause), ("ready", ""))
        self.assertIn("no_calibration", item.warnings)

    def test_opus_reflectance_on_an_absorbance_technique_is_content_vs_display(self):
        item = self.upload("IR3_f1r.0", OPUS)
        self.prepare_all()
        item = self.item(item)
        self.assertEqual(item.content_preset, "ftir_reflection")
        self.assertEqual(str(item.proposed_analysis_id), self.target("ir3"))
        self.assertEqual((item.decision, item.cause), ("pending", "content_vs_display"))
        self.assertEqual(item.display_config_id, self.config("ftir"))

    def test_a_format_on_the_wrong_technique_is_format_vs_technique(self):
        item = self.upload("F2_f1r.0", OPUS)
        self.prepare_all()
        item = self.item(item)
        self.assertIsNone(item.proposed_analysis_id)
        self.assertEqual(
            (item.decision, item.cause), ("pending", "format_vs_technique")
        )

    def test_a_pdf_is_not_a_measure(self):
        item = self.upload("notes.pdf", b"%PDF-1.4\n%binary \xff\xfe\x00 stream")
        self.prepare_all()
        item = self.item(item)
        self.assertEqual(
            (item.outcome, item.decision, item.cause),
            ("not_measure", "aside", "not_measure"),
        )

    def test_an_unreadable_known_format_waits_for_a_choice(self):
        item = self.upload("X7_f1r.mca", elio_mca([1]))
        self.prepare_all()
        item = self.item(item)
        self.assertEqual((item.outcome, item.reason), ("unreadable", "too_few_points"))
        self.assertEqual((item.decision, item.cause), ("pending", "unreadable_raw"))
        self.assertEqual(item.display_source, "none")

    def test_a_csv_over_the_viewer_limit_keeps_the_raw_only(self):
        item = self.upload("X7_f1r.mca", ELIO)
        with override_settings(SPECTRUM_PREVIEW_MAX_BYTES=10):
            self.prepare_all()
        item = self.item(item)
        self.assertEqual((item.outcome, item.reason), ("raw_only", "too_large"))
        self.assertEqual((item.decision, item.cause), ("pending", "too_large"))

    def test_a_stored_raw_is_converted_from_its_file_and_keeps_its_analysis(self):
        analysis = self.targets["xrf11"]
        file_id = self.stored_file(analysis, "stored.mca", ELIO)
        item = MeasurementItem.objects.create(
            run=self.run,
            origin="stored",
            source_name="stored.mca",
            sha256="d" * 64,
            size=len(ELIO),
            source_file_id=file_id,
            source_analysis_id=analysis.pk,
        )
        self.prepare_all()
        item = self.item(item)
        self.assertEqual(item.outcome, "csv")
        self.assertEqual(item.proposed_analysis_id, analysis.pk)
        self.assertEqual((item.decision, item.cause), ("ready", ""))

    def test_a_stored_raw_of_another_family_is_format_vs_technique(self):
        analysis = self.targets["f2"]
        file_id = self.stored_file(analysis, "stored.0", OPUS)
        item = MeasurementItem.objects.create(
            run=self.run,
            origin="stored",
            source_name="stored.0",
            sha256="e" * 64,
            size=len(OPUS),
            source_file_id=file_id,
            source_analysis_id=analysis.pk,
        )
        self.prepare_all()
        item = self.item(item)
        self.assertEqual(
            (item.decision, item.cause), ("pending", "format_vs_technique")
        )
        self.assertEqual(item.proposed_analysis_id, analysis.pk)

    def test_a_stored_raw_that_cannot_be_read_fails_as_missing(self):
        item = MeasurementItem.objects.create(
            run=self.run,
            origin="stored",
            source_name="gone.mca",
            sha256="f" * 64,
            size=1,
            source_file_id=uuid.uuid4(),
            source_analysis_id=self.targets["xrf7"].pk,
        )
        self.prepare_all()
        item = self.item(item)
        self.assertEqual((item.state, item.error), ("failed", "missing"))
        self.assertEqual(self.run.state, "review")

    def test_a_shelfmark_of_another_document_is_set_for_a_choice(self):
        mine = self.upload("Ms59_X7_f1r.mca", ELIO)
        other = self.upload("Ms60_X7_f1r.mca", ELIO_NO_CAL)
        self.prepare_all()
        self.assertEqual(self.item(mine).proposed_analysis_id, self.targets["xrf7"].pk)
        other = self.item(other)
        self.assertEqual((other.decision, other.cause), ("pending", "other_shelfmark"))

    def test_the_shelfmark_is_the_identifier_typed_as_one(self):
        self.assertEqual(
            prepare.document_shelfmark(self.document.pk, self.editor, "en"), "Ms 59"
        )


class DatabaseCauseTests(PrepareCase):
    def test_the_same_bytes_on_the_target_analysis_are_in_database(self):
        self.stored_file(self.targets["xrf9"], "old.mca", ELIO)
        item = self.upload("X9_f1r.mca", ELIO)
        self.prepare_all()
        item = self.item(item)
        self.assertEqual((item.decision, item.cause), ("aside", "in_database"))

    def test_the_source_hash_of_a_converted_csv_is_in_database(self):
        item = self.upload("X9_f1r.mca", ELIO)
        csv = self.stored_file(self.targets["xrf9"], "other.csv", b"x,y\n")
        node = self.nodes[("analysis", "measurement_point_data")]
        tile = base.TileModel.objects.get(
            resourceinstance=self.targets["xrf9"], nodegroup_id=node.nodegroup_id
        )
        entries = tile.data[str(node.nodeid)]
        for entry in entries:
            if entry["file_id"] == csv:
                entry["msSourceSha256"] = item.sha256
        base.TileModel.objects.filter(pk=tile.pk).update(data=tile.data)
        self.prepare_all()
        self.assertEqual(self.item(item).cause, "in_database")

    def test_a_file_of_the_same_format_already_on_the_analysis_is_already_provided(
        self,
    ):
        self.stored_file(self.targets["xrf9"], "old.MCA", elio_mca(counts(5)))
        item = self.upload("X9_f1r.mca", elio_mca(counts(9)))
        self.prepare_all()
        item = self.item(item)
        self.assertEqual(item.proposed_analysis_id, self.targets["xrf9"].pk)
        self.assertEqual((item.decision, item.cause), ("pending", "already_provided"))

    def test_several_uploads_on_one_analysis_are_the_same_target(self):
        first = self.upload("X10_f1r.mca", elio_mca(counts(1)))
        second = self.upload("X10_f1r_bis.mca", elio_mca(counts(2)))
        self.prepare_all()
        for item in (self.item(first), self.item(second)):
            self.assertEqual(item.proposed_analysis_id, self.targets["xrf10"].pk)
            self.assertEqual((item.decision, item.cause), ("pending", "same_target"))


class LabCsvTests(PrepareCase):
    def test_a_lab_csv_beside_a_convertible_raw_is_set_aside(self):
        raw = self.upload("X7_f1r.mca", ELIO)
        csv = self.upload("X7_f1r.csv", (CONTRACT / "xrf.csv").read_bytes())
        self.prepare_all()
        csv, raw = self.item(csv), self.item(raw)
        self.assertEqual((csv.decision, csv.cause), ("aside", "lab_csv_set_aside"))
        self.assertEqual(csv.paired_item_id, raw.id)
        self.assertEqual((raw.decision, raw.cause), ("ready", ""))

    def test_an_opus_twin_named_with_the_full_raw_name_is_set_aside(self):
        raw = self.upload("IR3_f1r.0", OPUS)
        csv = self.upload(
            "IR3_f1r.0.csv", (CONTRACT / "ftir_reflection.csv").read_bytes()
        )
        self.prepare_all()
        self.assertEqual(self.item(csv).cause, "lab_csv_set_aside")

    def test_a_csv_in_another_folder_is_not_a_twin(self):
        self.upload("X7_f1r.mca", ELIO)
        csv = self.upload("X7_f1r.csv", (CONTRACT / "xrf.csv").read_bytes(), "other")
        self.prepare_all()
        self.assertNotEqual(self.item(csv).cause, "lab_csv_set_aside")

    def test_a_lone_csv_that_holds_the_contract_is_ready(self):
        item = self.upload("F2_f1r.csv", (CONTRACT / "fors.csv").read_bytes())
        self.prepare_all()
        item = self.item(item)
        self.assertEqual((item.outcome, item.detected_format), ("csv", "csv"))
        self.assertEqual(str(item.proposed_analysis_id), self.target("f2"))
        self.assertEqual((item.decision, item.cause), ("ready", ""))
        self.assertEqual(item.display_config_id, self.config("fors"))

    def test_a_lone_csv_that_breaks_the_contract_is_set_aside_with_its_code(self):
        item = self.upload(
            "F2_f1r.csv", (CONTRACT / "refused" / "bom.csv").read_bytes()
        )
        self.prepare_all()
        item = self.item(item)
        self.assertEqual(
            (item.outcome, item.reason, item.decision, item.cause),
            ("unreadable", "bom", "aside", "csv_contract"),
        )

    def test_an_unreadable_raw_and_its_csv_are_ready_together(self):
        raw = self.upload("R5_f1r.wdf", WDF)
        csv = self.upload("R5_f1r.csv", (CONTRACT / "raman.csv").read_bytes())
        self.prepare_all()
        raw, csv = self.item(raw), self.item(csv)
        self.assertEqual(raw.outcome, "unsupported")
        self.assertEqual((raw.paired_item_id, csv.paired_item_id), (csv.id, raw.id))
        for item in (raw, csv):
            self.assertEqual(str(item.proposed_analysis_id), self.target("r5"))
            self.assertEqual((item.decision, item.cause), ("ready", ""))
        self.assertEqual(csv.display_config_id, self.config("raman"))

    def test_an_unreadable_raw_alone_waits_for_a_choice(self):
        raw = self.upload("R5_f1r.wdf", WDF)
        self.prepare_all()
        raw = self.item(raw)
        self.assertEqual((raw.decision, raw.cause), ("pending", "unreadable_raw"))


class ChunkTests(PrepareCase):
    def test_a_chunk_reports_whether_items_remain_and_the_last_opens_the_review(self):
        for seed in range(3):
            self.upload(f"X7_f1r_{seed}.mca", elio_mca(counts(seed)))
        self.assertTrue(prepare.prepare_run(self.run, chunk=2))
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "preparing")
        self.assertFalse(prepare.prepare_run(self.run, chunk=2))
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "review")
        self.assertFalse(prepare.prepare_run(self.run))

    def test_the_catalogue_is_read_once_and_stored_in_staging(self):
        for seed in range(3):
            self.upload(f"X7_f1r_{seed}.mca", elio_mca(counts(seed)))
        with mock.patch.object(
            prepare.catalogue, "document_analyses", wraps=catalogue.document_analyses
        ) as spy:
            while prepare.prepare_run(self.run, chunk=1):
                pass
        self.assertEqual(spy.call_count, 1)
        data = json.loads((staging.run_dir(self.run.id) / "catalogue.json").read_text())
        self.assertEqual(data["shelfmark"], "Ms 59")
        self.assertIn(self.target("xrf7"), {c["id"] for c in data["cards"]})
        cards, _ = prepare.load_snapshot(self.run)
        self.assertIsInstance(cards[0], catalogue.AnalysisCard)

    def test_an_interrupted_chunk_is_finished_without_redoing_the_prepared_item(self):
        items = [
            self.upload(f"X7_f1r_{seed}.mca", elio_mca(counts(seed)))
            for seed in range(3)
        ]
        real = prepare.prepare_item
        calls = []

        def flaky(item, *args, **kwargs):
            calls.append(item.id)
            if len(calls) == 2:
                raise RuntimeError("boom")
            return real(item, *args, **kwargs)

        with mock.patch.object(prepare, "prepare_item", side_effect=flaky):
            with self.assertRaises(RuntimeError):
                prepare.prepare_run(self.run, chunk=3)
        states = {i.id: self.item(i).state for i in items}
        self.assertEqual(
            sorted(states.values()), ["failed", "prepared", "queued"], states
        )
        calls.clear()
        with mock.patch.object(prepare, "prepare_item", side_effect=flaky):
            prepare.prepare_run(self.run, chunk=3)
        done = [i.id for i in items if states[i.id] == "prepared"]
        self.assertNotIn(done[0], calls)
        self.assertEqual(len(calls), 1)
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "review")

    def test_a_fresh_claim_is_not_taken_and_a_stale_one_is(self):
        fresh = self.upload("a.mca", ELIO)
        stale = self.upload("b.mca", ELIO_NO_CAL)
        now = timezone.now()
        MeasurementItem.objects.filter(pk=fresh.pk).update(
            state="claimed", claimed_at=now - timedelta(minutes=9)
        )
        MeasurementItem.objects.filter(pk=stale.pk).update(
            state="claimed", claimed_at=now - timedelta(minutes=11)
        )
        taken = prepare.claim(self.run, ("queued",), 10)
        self.assertEqual([i.id for i in taken], [stale.id])
        self.assertEqual(self.item(stale).state, "claimed")
        self.assertGreater(self.item(stale).claimed_at, now - timedelta(minutes=1))

    def test_claim_takes_at_most_the_limit_in_a_stable_order(self):
        for name in ("c.mca", "a.mca", "b.mca"):
            self.upload(name, elio_mca(counts(len(name) + ord(name[0]))))
        taken = prepare.claim(self.run, ("queued",), 2)
        self.assertEqual([i.source_name for i in taken], ["a.mca", "b.mca"])
        self.assertEqual(self.run.items.filter(state="claimed").count(), 2)

    def test_the_codes_of_the_user_reach_the_matching(self):
        MeasurementNameCode.objects.create(user=self.editor, code="Ffsc", family="fors")
        item = self.upload("Ffsc2_f1r.csv", (CONTRACT / "fors.csv").read_bytes())
        self.prepare_all()
        self.assertEqual(str(self.item(item).proposed_analysis_id), self.target("f2"))


class TaskTests(PrepareCase):
    def test_the_task_sends_itself_again_while_items_remain(self):
        for seed in range(2):
            self.upload(f"X7_f1r_{seed}.mca", elio_mca(counts(seed)))
        with override_settings(MEASUREMENT_PREPARE_CHUNK=1):
            with mock.patch.object(intake, "current_app") as app:
                measurement_prepare_task(str(self.run.id))
                app.send_task.assert_called_once_with(
                    "manuspectrum.measurement_prepare",
                    args=[str(self.run.id)],
                    countdown=1,
                )
                app.reset_mock()
                measurement_prepare_task(str(self.run.id))
                app.send_task.assert_not_called()
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "review")

    def test_the_task_ignores_an_unknown_run(self):
        with mock.patch.object(intake, "current_app") as app:
            measurement_prepare_task(str(uuid.uuid4()))
            measurement_prepare_task("not-a-uuid")
        app.send_task.assert_not_called()


class ResumeTests(PrepareCase):
    def setUp(self):
        super().setUp()
        self.item_ = self.upload("a.mca", ELIO)
        patcher = mock.patch.object(intake, "current_app")
        self.app = patcher.start()
        self.addCleanup(patcher.stop)

    def claim_at(self, minutes):
        MeasurementItem.objects.filter(pk=self.item_.pk).update(
            state="claimed", claimed_at=timezone.now() - timedelta(minutes=minutes)
        )

    def test_unclaimed_items_with_no_claim_resend_the_task_once(self):
        self.assertTrue(intake.resume_if_stalled(self.run))
        self.app.send_task.assert_called_once_with(
            "manuspectrum.measurement_prepare", args=[str(self.run.id)]
        )
        self.assertFalse(intake.resume_if_stalled(self.run))
        self.app.send_task.assert_called_once()

    def test_a_young_claim_means_a_worker_is_on_it(self):
        self.claim_at(2)
        self.upload("b.mca", ELIO_NO_CAL)
        self.assertFalse(intake.resume_if_stalled(self.run))
        self.app.send_task.assert_not_called()

    def test_an_old_claim_with_no_young_one_resends(self):
        self.claim_at(11)
        self.assertTrue(intake.resume_if_stalled(self.run))

    def test_a_run_with_nothing_left_or_in_another_state_is_left_alone(self):
        MeasurementItem.objects.filter(pk=self.item_.pk).update(state="prepared")
        self.assertFalse(intake.resume_if_stalled(self.run))
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="review")
        self.run.refresh_from_db()
        MeasurementItem.objects.filter(pk=self.item_.pk).update(state="queued")
        self.assertFalse(intake.resume_if_stalled(self.run))
        self.app.send_task.assert_not_called()

    def test_a_writing_run_resends_the_write_task(self):
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="writing")
        MeasurementItem.objects.filter(pk=self.item_.pk).update(
            state="prepared", decision="ready"
        )
        self.run.refresh_from_db()
        self.assertTrue(intake.resume_if_stalled(self.run))
        self.app.send_task.assert_called_once_with(
            "manuspectrum.measurement_write", args=[str(self.run.id)]
        )
