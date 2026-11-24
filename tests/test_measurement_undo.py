import uuid
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Group, User

from arches.app.models.models import EditLog, File, TileModel

from manuspectrum.constants.xy_presets import DATA_FILE_NODE_ID, DATA_FILE_NODEGROUP_ID
from manuspectrum.measurement_files import intake, staging, undo
from manuspectrum.models import MeasurementDecision, MeasurementItem, MeasurementRun
from manuspectrum.tasks import measurement_undo_task
from tests.test_measurement_writer import WriterCase


class UndoCase(WriterCase):
    def written(self, *items_args, **kwargs):
        """Write the items made so far, then put the run in ``undoing``."""
        self.write()
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="undoing")
        self.run.refresh_from_db()

    def undo(self, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            while undo.undo_run(self.run, **kwargs):
                pass
        self.run.refresh_from_db()

    def snapshot(self, **labels):
        """The run's catalogue snapshot names the analyses *labels* (``{pk: name}``)."""
        cards = [SimpleNamespace(id=str(pk), name=name) for pk, name in labels.items()]
        patcher = mock.patch.object(
            undo.prepare, "load_snapshot", return_value=(cards, "")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def file_rows(self):
        return set(File.objects.values_list("pk", flat=True))

    def edit_csv(self, analysis):
        tile = next(
            t
            for t in self.tiles(analysis)
            if t.data[DATA_FILE_NODE_ID][0]["name"].endswith(".csv")
        )
        data = dict(tile.data)
        data[DATA_FILE_NODE_ID] = [dict(data[DATA_FILE_NODE_ID][0], title="edited")]
        TileModel.objects.filter(pk=tile.pk).update(data=data)
        return tile


class RemovesOnlyAdditionsTests(UndoCase):
    def test_the_additions_go_and_what_existed_stays(self):
        keep = self.stored_file(self.target, "old.mca", b"old raw")
        before_tiles = set(
            TileModel.objects.filter(resourceinstance=self.target).values_list(
                "pk", flat=True
            )
        )
        before_files = self.file_rows()
        item = self.make_item(self.target)
        self.written()
        self.assertEqual(len(self.tiles(self.target, self.parent_group.pk)), 1)
        self.assertEqual(len(self.uploaded_names()), 3)
        self.undo()
        self.assertEqual(
            set(
                TileModel.objects.filter(resourceinstance=self.target).values_list(
                    "pk", flat=True
                )
            ),
            before_tiles,
        )
        self.assertEqual(self.file_rows(), before_files)
        self.assertEqual(File.objects.get(pk=keep).path.read(), b"old raw")
        self.assertEqual(len(self.uploaded_names()), 1)
        self.assertEqual(self.fresh(item).state, "removed")
        self.assertEqual(self.run.state, "undone")
        self.assertFalse(
            staging.run_dir(self.run.id).exists()
            and any(staging.run_dir(self.run.id).iterdir())
        )

    def test_a_tile_edited_since_is_kept_with_its_files_and_reported(self):
        self.snapshot(**{str(self.target.pk): "Target"})
        item = self.make_item(self.target)
        self.written()
        self.edit_csv(self.target)
        files = self.file_rows()
        self.undo()
        self.assertEqual(len(self.tiles(self.target)), 2)
        self.assertEqual(self.file_rows(), files)
        self.assertEqual(len(self.uploaded_names()), 2)
        self.assertEqual(self.fresh(item).state, "kept")
        report = undo.report(self.run)
        self.assertEqual(report["removed"], 0)
        self.assertEqual(
            report["kept_modified"],
            [
                {
                    "item": str(item.id),
                    "name": item.source_name,
                    "analysis": str(self.target.pk),
                    "label": "Target",
                }
            ],
        )

    def test_the_kept_item_does_not_stop_the_others(self):
        kept = self.make_item(self.target, "A.mca")
        gone = self.make_item(self.new_analysis("Other"), "B.mca")
        self.written()
        self.edit_csv(self.target)
        self.undo()
        self.assertEqual(
            (self.fresh(kept).state, self.fresh(gone).state), ("kept", "removed")
        )

    def test_a_tile_removed_since_is_already_gone(self):
        item = self.make_item(self.target)
        self.written()
        TileModel.objects.filter(
            resourceinstance=self.target, nodegroup_id=DATA_FILE_NODEGROUP_ID
        ).delete()
        self.undo()
        self.assertEqual(self.fresh(item).state, "removed")
        report = undo.report(self.run)
        self.assertEqual((report["removed"], report["already_gone"]), (0, 1))

    def test_a_created_parent_stays_while_a_child_is_left(self):
        self.make_item(self.target, "A.mca")
        self.written()
        parent = self.tiles(self.target, self.parent_group.pk)[0]
        TileModel.objects.create(
            resourceinstance=self.target,
            nodegroup_id=DATA_FILE_NODEGROUP_ID,
            parenttile=parent,
            data={DATA_FILE_NODE_ID: []},
        )
        self.undo()
        self.assertEqual(self.tiles(self.target, self.parent_group.pk), [parent])
        self.assertEqual(len(self.tiles(self.target)), 1)

    def test_a_created_parent_goes_once_its_last_item_does(self):
        self.make_item(self.target, "A.mca")
        self.make_item(self.target, "B.mca")
        self.written()
        self.undo(chunk=1)
        self.assertEqual(self.tiles(self.target, self.parent_group.pk), [])
        self.assertEqual(self.tiles(self.target), [])

    def test_an_existing_parent_is_never_deleted(self):
        parent = TileModel.objects.create(
            resourceinstance=self.target,
            nodegroup=self.parent_group,
            data={str(self.parent_group.pk): None},
        )
        self.make_item(self.target)
        self.written()
        self.undo()
        self.assertEqual(self.tiles(self.target, self.parent_group.pk), [parent])
        self.assertEqual(self.tiles(self.target), [])

    def test_an_item_that_wrote_nothing_is_removed_without_touching_anything(self):
        self.stored_file(self.target, "have.mca", b"present")
        item = self.make_item(
            self.target, "x.mca", raw=b"present", outcome="raw_only", reason="kept_raw"
        )
        self.written()
        before = self.file_rows()
        self.undo()
        self.assertEqual(self.fresh(item).state, "removed")
        self.assertEqual(self.file_rows(), before)
        self.assertEqual(len(self.tiles(self.target)), 1)

    def test_the_lab_csv_of_a_pair_follows_its_raw_item(self):
        raw = self.make_item(
            self.target, "A.mca", outcome="unreadable", csv=None, lone=True
        )
        lab = self.make_item(
            self.target, "A.csv", outcome="csv", lone=True, raw=b"x,y\n1,2\n"
        )
        MeasurementItem.objects.filter(pk=raw.pk).update(paired_item=lab)
        MeasurementItem.objects.filter(pk=lab.pk).update(paired_item=raw)
        self.written()
        self.undo()
        self.assertEqual(
            (self.fresh(raw).state, self.fresh(lab).state), ("removed", "removed")
        )
        self.assertEqual(self.tiles(self.target), [])


class EditLogTests(UndoCase):
    def test_deletes_are_logged_under_the_undo_transaction_with_the_author(self):
        self.make_item(self.target)
        self.written()
        self.undo()
        tx = undo.undo_transaction_id(self.run)
        self.assertNotEqual(tx, self.run.transaction_id)
        rows = EditLog.objects.filter(transactionid=tx)
        self.assertEqual(rows.count(), 3)
        for row in rows:
            self.assertEqual(row.edittype, "tile delete")
            self.assertEqual(row.userid, str(self.editor.pk))

    def test_nothing_of_ours_is_under_the_workflow_id(self):
        self.make_item(self.target)
        self.written()
        self.undo()
        self.assertFalse(EditLog.objects.filter(transactionid=self.run.id).exists())
        self.assertFalse(
            EditLog.objects.filter(
                resourceinstanceid=str(self.target.pk), edittype="create"
            ).exists()
        )


class RollbackTests(UndoCase):
    def test_a_failure_after_the_tile_delete_keeps_tiles_rows_and_bytes(self):
        item = self.make_item(self.target)
        self.written()
        files = self.file_rows()
        tiles = len(self.tiles(self.target))
        with mock.patch.object(undo, "attribute", side_effect=RuntimeError("boom")):
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaises(RuntimeError):
                    undo.undo_analysis(self.run, self.target.pk, [item])
        self.assertEqual(len(self.tiles(self.target)), tiles)
        self.assertEqual(self.file_rows(), files)
        self.assertEqual(len(self.uploaded_names()), 2)
        for row in File.objects.all():
            self.assertTrue(row.tile_id)
            self.assertTrue(row.path.read())
        self.assertEqual(self.fresh(item).state, "written")

    def test_a_failing_analysis_goes_to_failed_and_a_new_undo_retries_it(self):
        item = self.make_item(self.target)
        self.written()
        with mock.patch.object(undo, "attribute", side_effect=RuntimeError("boom")):
            self.undo()
        self.assertEqual(self.run.state, "undone")
        self.assertEqual(
            (self.fresh(item).state, self.fresh(item).error), ("failed", "undo_failed")
        )
        self.assertEqual(undo.report(self.run)["failed"], 1)
        self.assertEqual(len(self.tiles(self.target)), 2)
        self.assertEqual(undo.reset_failed(self.run), 1)
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="undoing")
        self.undo()
        self.assertEqual(self.tiles(self.target), [])

    def test_the_bytes_go_only_on_commit(self):
        item = self.make_item(self.target)
        self.written()
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            undo.undo_analysis(self.run, self.target.pk, [item])
        self.assertEqual(len(self.uploaded_names()), 2)
        for callback in callbacks:
            callback()
        self.assertEqual(self.uploaded_names(), [])


class RunTests(UndoCase):
    def test_a_run_not_undoing_does_nothing(self):
        self.make_item(self.target)
        self.write()
        self.assertFalse(undo.undo_run(self.run))
        self.assertEqual(len(self.tiles(self.target)), 2)

    def test_a_chunk_reports_whether_work_remains(self):
        self.make_item(self.target, "A.mca")
        self.make_item(self.new_analysis("Other"), "B.mca")
        self.written()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(undo.undo_run(self.run, chunk=1))
            self.assertFalse(undo.undo_run(self.run, chunk=1))
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "undone")
        self.assertIsNotNone(self.run.finished_at)

    def test_the_analysis_is_indexed_once_after_the_undo(self):
        self.make_item(self.target, "A.mca")
        self.written()
        with mock.patch.object(undo, "_index_resource") as index:
            self.undo()
        index.assert_called_once_with(str(self.target.pk))

    def test_an_analysis_the_user_can_no_longer_edit_keeps_its_items(self):
        item = self.make_item(self.target)
        self.written()
        with mock.patch.object(undo, "user_can_edit_resource", return_value=False):
            self.undo()
        self.assertEqual(self.fresh(item).state, "kept")
        self.assertEqual(len(self.tiles(self.target)), 2)
        self.assertEqual(len(undo.report(self.run)["not_editable"]), 1)

    def test_the_task_sends_itself_again_while_work_remains(self):
        self.make_item(self.target)
        self.written()
        with (
            mock.patch.object(intake, "send") as send,
            mock.patch.object(undo, "undo_run", return_value=True),
        ):
            measurement_undo_task(str(self.run.id))
        send.assert_called_once_with(intake.UNDO_TASK, self.run.id, countdown=1)
        with mock.patch.object(intake, "send") as send:
            measurement_undo_task(str(self.run.id))
        send.assert_not_called()
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "undone")

    def test_a_stalled_undoing_run_is_resumed_once(self):
        self.make_item(self.target)
        self.written()
        with mock.patch.object(intake, "send") as send:
            self.assertTrue(intake.resume_if_stalled(self.run))
            self.assertFalse(intake.resume_if_stalled(self.run))
        send.assert_called_once_with(intake.UNDO_TASK, self.run.id)


class UndoRouteTests(UndoCase):
    def post(self, user=None):
        self.client.force_login(user or self.editor)
        return self.client.post(f"/api/measurement-files/runs/{self.run.id}/undo")

    def get(self):
        self.client.force_login(self.editor)
        return self.client.get(f"/api/measurement-files/runs/{self.run.id}")

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(intake, "send")
        self.send = patcher.start()
        self.addCleanup(patcher.stop)

    def test_before_any_write_it_only_removes_staging_items_and_decisions(self):
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="review")
        self.make_item(self.target)
        MeasurementDecision.objects.create(run=self.run, action="x")
        files = self.file_rows()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "undone")
        self.assertFalse(self.run.items.exists())
        self.assertFalse(self.run.decisions.exists())
        self.assertFalse(any(staging.run_dir(self.run.id).iterdir()))
        self.assertEqual(self.file_rows(), files)
        self.send.assert_not_called()

    def test_after_a_write_it_starts_the_undo_task(self):
        self.make_item(self.target)
        self.write()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"state": "undoing"})
        self.send.assert_called_once_with(intake.UNDO_TASK, self.run.id)

    def test_a_repeated_call_is_a_no_op(self):
        self.make_item(self.target)
        self.write()
        self.post()
        self.send.reset_mock()
        self.assertEqual(self.post().json(), {"state": "undoing"})
        self.send.assert_not_called()

    def test_the_report_is_served_once_undone(self):
        self.snapshot(**{str(self.target.pk): "Target"})
        item = self.make_item(self.target)
        self.written()
        self.edit_csv(self.target)
        self.make_item(self.new_analysis("Other"), "B.mca")
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="writing")
        self.write()
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="undoing")
        self.run.refresh_from_db()
        self.assertNotIn("report", self.get().json())
        self.undo()
        body = self.get().json()
        self.assertEqual(body["state"], "undone")
        self.assertEqual(body["report"]["removed"], 1)
        self.assertEqual(body["report"]["kept_modified"][0]["label"], "Target")
        self.assertEqual(body["report"]["kept_modified"][0]["item"], str(item.id))

    def test_another_user_gets_a_bodyless_404(self):
        other = User.objects.create_user("other_editor", password="pw")
        other.groups.add(Group.objects.get(name="Resource Editor"))
        response = self.post(other)
        self.assertEqual((response.status_code, response.content), (404, b""))

    def test_an_unknown_run_is_a_bodyless_404(self):
        self.client.force_login(self.editor)
        response = self.client.post(f"/api/measurement-files/runs/{uuid.uuid4()}/undo")
        self.assertEqual((response.status_code, response.content), (404, b""))


class RaceTests(UndoCase):
    def test_undo_is_refused_while_the_run_is_writing(self):
        self.make_item(self.target)
        patcher = mock.patch.object(intake, "send")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.editor)
        response = self.client.post(f"/api/measurement-files/runs/{self.run.id}/undo")
        self.assertEqual(
            (response.status_code, response.json()), (409, {"error": "writing"})
        )
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "writing")
        self.assertTrue(self.run.items.exists())

    def test_a_write_chunk_after_the_run_moved_to_undoing_writes_nothing(self):
        from manuspectrum.measurement_files import writer

        item = self.make_item(self.target)
        MeasurementItem.objects.filter(pk=item.pk).update(state="claimed")
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="undoing")
        item.refresh_from_db()
        self.assertEqual(writer.write_analysis(self.run, self.target.pk, [item]), [])
        self.assertEqual(self.tiles(self.target), [])
        self.assertEqual(self.uploaded_names(), [])
        self.assertEqual(self.fresh(item).state, "prepared")

    def test_an_item_deleted_meanwhile_does_not_raise(self):
        from manuspectrum.measurement_files import writer

        item = self.make_item(self.target)
        MeasurementItem.objects.filter(pk=item.pk).update(state="claimed")
        item.refresh_from_db()
        item.delete()
        self.assertEqual(writer.write_analysis(self.run, self.target.pk, [item]), [])
