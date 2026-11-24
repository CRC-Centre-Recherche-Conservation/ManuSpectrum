import hashlib
import io
import json
import uuid
import zipfile
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from arches.app.models import models
from arches.app.utils.permission_backend import assign_perm

from manuspectrum.constants.xy_presets import DATA_FILE_NODE_ID
from manuspectrum.measurement_files import intake, staging
from manuspectrum.models import MeasurementItem, MeasurementRun
from tests.test_measurement_catalogue import CatalogueCase


def zip_bytes(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            archive.writestr(name, data)
    return buffer.getvalue()


class IntakeCase(CatalogueCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.editor)

    def create_run(self, user=None, **extra):
        payload = {
            "workflow_id": str(uuid.uuid4()),
            "document_id": str(self.document.pk),
            "language": "en",
            **extra,
        }
        client = self.client
        return (
            client.post(
                reverse("api-measurement-run-create"),
                json.dumps(payload),
                content_type="application/json",
            ),
            payload,
        )

    def make_run(self, user=None, **kw):
        values = {
            "id": uuid.uuid4(),
            "user": user or self.editor,
            "document_id": self.document.pk,
            "language": "en",
        }
        values.update(kw)
        return MeasurementRun.objects.create(**values)

    def url(self, name, run):
        return reverse(f"api-measurement-{name}", args=[run.id])

    def upload(self, run, files, paths=None, **extra):
        data = {"files": files}
        if paths is not None:
            data["paths"] = paths
        return self.client.post(self.url("files", run), data, **extra)

    def set_widget(self, config):
        node = models.Node.objects.get(pk=DATA_FILE_NODE_ID)
        card, _ = models.CardModel.objects.get_or_create(
            graph=node.graph,
            nodegroup=node.nodegroup,
            defaults={"name": "files", "active": True},
        )
        widget = models.Widget.objects.first()
        models.CardXNodeXWidget.objects.update_or_create(
            node=node,
            card=card,
            widget=widget,
            defaults={"config": config, "label": "Files"},
        )


class RunCreationTests(IntakeCase):
    def test_creates_a_run_and_is_idempotent(self):
        response, payload = self.create_run()
        self.assertEqual(response.status_code, 201)
        run = response.json()["run"]
        self.assertEqual(run["id"], payload["workflow_id"])
        self.assertEqual(run["state"], "collecting")
        again = self.client.post(
            reverse("api-measurement-run-create"),
            json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(MeasurementRun.objects.count(), 1)

    def test_another_users_workflow_id_is_a_bodyless_404(self):
        other = User.objects.create_user("other_ed", password="pw")
        other.groups.add(Group.objects.get(name="Resource Editor"))
        run = self.make_run(user=other)
        response = self.client.post(
            reverse("api-measurement-run-create"),
            json.dumps(
                {
                    "workflow_id": str(run.id),
                    "document_id": str(self.document.pk),
                    "language": "en",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual((response.status_code, response.content), (404, b""))
        self.assertEqual(self.client.get(self.url("run", run)).status_code, 404)

    def test_non_editor_is_refused(self):
        viewer = User.objects.create_user("plain_user", password="pw")
        self.client.force_login(viewer)
        response, _ = self.create_run()
        self.assertEqual(response.status_code, 403)

    def test_unknown_document_and_bad_input(self):
        response, _ = self.create_run(document_id=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "document_unavailable")
        response, _ = self.create_run(language="xx")
        self.assertEqual(response.status_code, 400)
        response, _ = self.create_run(workflow_id="nope")
        self.assertEqual(response.status_code, 400)

    def test_document_without_an_editable_analysis_is_refused(self):
        for analysis in (self.a_link, self.a_name, self.a_raw):
            assign_perm("no_access_to_resourceinstance", self.editor, analysis)
        response, _ = self.create_run()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "no_editable_analysis")

    def test_run_status(self):
        run = self.make_run()
        MeasurementItem.objects.create(
            run=run, origin="upload", source_name="a.0", sha256="a" * 64, size=1
        )
        with (
            mock.patch.object(intake.catalogue, "document_status") as status,
            mock.patch.object(intake.catalogue, "document_analyses") as cards,
        ):
            body = self.client.get(self.url("run", run)).json()
        status.assert_not_called()
        cards.assert_not_called()
        self.assertNotIn("document_status", body)
        self.assertEqual(body["state"], "collecting")
        self.assertEqual(body["counts"]["total"], 1)
        self.assertEqual(body["counts"]["queued"], 1)
        self.assertEqual(len(body["recent"]), 1)
        full = self.client.get(self.url("run", run) + "?with=status").json()
        self.assertEqual(full["document_status"]["analyses"], 4)


class MaxFileBytesTests(IntakeCase):
    def test_follows_the_widget_config(self):
        self.set_widget({"maxFilesize": 10})
        self.assertEqual(intake.max_file_bytes(), 10 * 1024 * 1024)
        self.set_widget({"maxFilesize": "2"})
        self.assertEqual(intake.max_file_bytes(), 2 * 1024 * 1024)

    def test_falls_back_without_a_stated_limit(self):
        self.assertEqual(
            intake.max_file_bytes(), settings.MEASUREMENT_DEFAULT_MAX_FILE_MB << 20
        )
        self.set_widget({})
        self.assertEqual(intake.max_file_bytes(), 10 * 1024 * 1024)
        self.set_widget({"maxFilesize": "many"})
        self.assertEqual(intake.max_file_bytes(), 10 * 1024 * 1024)


class UploadTests(IntakeCase):
    def test_two_files_are_staged_with_their_hash(self):
        run = self.make_run()
        response = self.upload(
            run,
            [SimpleUploadedFile("a.mca", b"alpha"), SimpleUploadedFile("b.0", b"beta")],
            ["", "sub/dir"],
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["accepted"]), 2)
        self.assertEqual(body["rejected"], [])
        item = MeasurementItem.objects.get(run=run, source_name="b.0")
        self.assertEqual(item.sha256, hashlib.sha256(b"beta").hexdigest())
        self.assertEqual(item.relative_dir, "sub/dir")
        self.assertEqual(staging.read(run.id, item.staged_name), b"beta")
        self.assertTrue(item.staged_name.startswith(str(item.id)))

    def test_a_file_one_byte_over_the_limit_is_too_large(self):
        self.set_widget({"maxFilesize": 1})
        run = self.make_run()
        limit = 1024 * 1024
        response = self.upload(
            run,
            [
                SimpleUploadedFile("ok.mca", b"x" * limit),
                SimpleUploadedFile("big.mca", b"y" * (limit + 1)),
            ],
        )
        body = response.json()
        self.assertEqual([i["name"] for i in body["accepted"]], ["ok.mca"])
        self.assertEqual(body["rejected"], [{"name": "big.mca", "reason": "too_large"}])
        self.assertEqual(MeasurementItem.objects.filter(run=run).count(), 1)

    def test_a_duplicate_is_rejected_and_not_stored_twice(self):
        run = self.make_run()
        self.upload(run, [SimpleUploadedFile("a.mca", b"same")])
        body = self.upload(
            run,
            [
                SimpleUploadedFile("copy.mca", b"same"),
                SimpleUploadedFile("n.mca", b"n"),
            ],
        ).json()
        self.assertEqual(
            body["rejected"], [{"name": "copy.mca", "reason": "duplicate"}]
        )
        self.assertEqual(MeasurementItem.objects.filter(run=run).count(), 2)

    def test_the_fifty_first_file_of_a_request_is_a_400(self):
        run = self.make_run()
        files = [SimpleUploadedFile(f"f{i}.mca", f"c{i}".encode()) for i in range(51)]
        response = self.upload(run, files)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "too_many_files")
        self.assertFalse(MeasurementItem.objects.filter(run=run).exists())

    def test_fifty_files_are_accepted(self):
        run = self.make_run()
        files = [SimpleUploadedFile(f"f{i}.mca", f"c{i}".encode()) for i in range(50)]
        self.assertEqual(len(self.upload(run, files).json()["accepted"]), 50)

    def test_system_files_are_not_measures(self):
        run = self.make_run()
        body = self.upload(
            run,
            [
                SimpleUploadedFile(".DS_Store", b"x"),
                SimpleUploadedFile("note.mca", b"y"),
            ],
            ["", "__MACOSX/sub"],
        ).json()
        self.assertEqual(
            sorted(r["reason"] for r in body["rejected"]), ["not_measure"] * 2
        )
        self.assertEqual(body["accepted"], [])

    def test_hostile_names_stay_inside_the_staging_directory(self):
        run = self.make_run()
        body = self.upload(
            run,
            [
                SimpleUploadedFile("../../etc/passwd", b"one"),
                SimpleUploadedFile("a..b.mca", b"two"),
                SimpleUploadedFile("c\x00d‮.mca", b"three"),
            ],
            ["../../x", "/abs/../dir", "a\\b/./c"],
        ).json()
        self.assertEqual(len(body["accepted"]), 3, body)
        directory = staging.run_dir(run.id).resolve()
        for item in MeasurementItem.objects.filter(run=run):
            self.assertNotIn("..", item.relative_dir.split("/"))
            self.assertFalse(item.relative_dir.startswith("/"))
            self.assertNotIn("/", item.source_name)
            self.assertEqual((directory / item.staged_name).resolve().parent, directory)
        self.assertEqual(
            sorted(MeasurementItem.objects.values_list("relative_dir", flat=True)),
            ["a/b/c", "abs/dir", "x"],
        )

    def test_run_full(self):
        run = self.make_run()
        with override_settings(MEASUREMENT_MAX_RUN_FILES=1):
            body = self.upload(
                run,
                [SimpleUploadedFile("a.mca", b"1"), SimpleUploadedFile("b.mca", b"2")],
            ).json()
        self.assertEqual(body["rejected"], [{"name": "b.mca", "reason": "run_full"}])

    def test_upload_is_for_the_owner_of_a_collecting_run(self):
        other = User.objects.create_user("other_ed2", password="pw")
        other.groups.add(Group.objects.get(name="Resource Editor"))
        theirs = self.make_run(user=other)
        self.assertEqual(
            self.upload(theirs, [SimpleUploadedFile("a.mca", b"1")]).status_code, 404
        )
        mine = self.make_run(state="preparing")
        self.assertEqual(
            self.upload(mine, [SimpleUploadedFile("a.mca", b"1")]).status_code, 409
        )

    def test_a_declared_length_over_the_zip_cap_is_refused_before_reading(self):
        run = self.make_run()
        with override_settings(MEASUREMENT_MAX_ZIP_BYTES=100):
            response = self.upload(run, [SimpleUploadedFile("a.mca", b"x" * 500)])
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"], "request_too_large")

    def test_a_request_over_the_cap_that_is_not_a_zip_is_413(self):
        run = self.make_run()
        with override_settings(MEASUREMENT_MAX_REQUEST_BYTES=100):
            response = self.upload(run, [SimpleUploadedFile("a.mca", b"x" * 500)])
            self.assertEqual(response.status_code, 413)
            archive = zip_bytes([("a.mca", b"x" * 500)])
            ok = self.upload(run, [SimpleUploadedFile("pack.zip", archive)])
        self.assertEqual(ok.status_code, 200)


class ZipTests(IntakeCase):
    def test_zip_members_are_expanded_with_their_folder(self):
        run = self.make_run()
        archive = zip_bytes(
            [
                ("top.mca", b"one"),
                ("nested/deep/b.0", b"two"),
                ("__MACOSX/nested/._b.0", b"junk"),
                ("../evil/c.mca", b"three"),
                ("empty/", b""),
            ]
        )
        body = self.upload(run, [SimpleUploadedFile("pack.zip", archive)]).json()
        self.assertEqual(len(body["accepted"]), 3, body)
        self.assertEqual([r["reason"] for r in body["rejected"]], ["not_measure"])
        dirs = {
            i.source_name: i.relative_dir
            for i in MeasurementItem.objects.filter(run=run)
        }
        self.assertEqual(dirs, {"top.mca": "", "b.0": "nested/deep", "c.mca": "evil"})
        self.assertFalse(
            [p for p in staging.run_dir(run.id).iterdir() if p.suffix == ".zip"]
        )

    def test_the_zip_is_not_kept(self):
        run = self.make_run()
        self.upload(run, [SimpleUploadedFile("pack.zip", zip_bytes([("a.mca", b"1")]))])
        names = [p.name for p in staging.run_dir(run.id).iterdir()]
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].endswith("-a.mca"))

    def test_too_many_entries_refuses_the_whole_zip(self):
        run = self.make_run()
        archive = zip_bytes([(f"f{i}.mca", str(i).encode()) for i in range(4)])
        with override_settings(MEASUREMENT_ZIP_MAX_ENTRIES=3):
            response = self.upload(run, [SimpleUploadedFile("p.zip", archive)])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "zip_too_many_entries")
        self.assertFalse(MeasurementItem.objects.filter(run=run).exists())

    def test_a_high_ratio_refuses_the_zip_before_extracting(self):
        run = self.make_run()
        archive = zip_bytes([("bomb.mca", b"\0" * 200_000)])
        with mock.patch.object(intake, "accept_upload") as accept:
            response = self.upload(run, [SimpleUploadedFile("p.zip", archive)])
        self.assertEqual(response.json()["error"], "zip_ratio")
        accept.assert_not_called()

    def test_total_uncompressed_size_refuses_the_zip(self):
        run = self.make_run()
        archive = zip_bytes([("a.mca", os_random(300)), ("b.mca", os_random(300))])
        with override_settings(MEASUREMENT_MAX_RUN_BYTES=500):
            response = self.upload(run, [SimpleUploadedFile("p.zip", archive)])
        self.assertEqual(response.json()["error"], "zip_too_large_uncompressed")

    def test_a_member_over_the_file_limit_is_rejected_alone(self):
        self.set_widget({"maxFilesize": 1})
        run = self.make_run()
        archive = zip_bytes(
            [("big.mca", os_random(1024 * 1024 + 1)), ("ok.mca", os_random(10))]
        )
        body = self.upload(run, [SimpleUploadedFile("p.zip", archive)]).json()
        self.assertEqual([i["name"] for i in body["accepted"]], ["ok.mca"])
        self.assertEqual(body["rejected"], [{"name": "big.mca", "reason": "too_large"}])

    def test_a_lying_central_directory_is_caught_while_streaming(self):
        run = self.make_run()
        archive = bytearray(zip_bytes([("a.mca", os_random(5000))]))
        # file_size in the central directory (offset 24 of the record).
        position = archive.rfind(b"PK\x01\x02")
        archive[position + 24 : position + 28] = (10).to_bytes(4, "little")
        response = self.upload(run, [SimpleUploadedFile("p.zip", bytes(archive))])
        self.assertFalse(MeasurementItem.objects.filter(run=run).exists())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["rejected"], [{"name": "a.mca", "reason": "unreadable"}]
        )

    def test_a_member_stream_refuses_to_outgrow_its_declared_size_or_budget(self):
        over = intake._Member(io.BytesIO(b"x" * 20), 10, {"left": 1000})
        with self.assertRaises(intake.ZipRefused):
            over.read(20)
        budget = intake._Member(io.BytesIO(b"x" * 20), 20, {"left": 5})
        with self.assertRaises(intake.ZipRefused):
            budget.read(20)

    def test_an_unreadable_zip_is_a_code(self):
        run = self.make_run()
        response = self.upload(run, [SimpleUploadedFile("p.zip", b"not a zip")])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "zip_bad_zip")

    def test_a_zip_with_other_files_is_refused(self):
        run = self.make_run()
        body = self.upload(
            run,
            [
                SimpleUploadedFile("p.zip", zip_bytes([("a.mca", b"1")])),
                SimpleUploadedFile("b.mca", b"2"),
            ],
        ).json()
        self.assertEqual(body["rejected"], [{"name": "p.zip", "reason": "zip_alone"}])
        self.assertEqual(len(body["accepted"]), 1)


def os_random(size):
    import os

    return os.urandom(size)


class StoredTests(IntakeCase):
    def file_id(self, analysis, name):
        for card in self.cards().values():
            for stored in card.files:
                if stored.name == name and card.id == str(analysis.pk):
                    return stored.file_id

    def test_lists_raw_files_without_twin_grouped_by_format(self):
        run = self.make_run()
        body = self.client.get(self.url("stored", run)).json()
        found = {f["format"]: [x["name"] for x in f["files"]] for f in body["formats"]}
        self.assertEqual(found, {"mca": ["c.mca"]})

    def test_selects_a_stored_raw_file(self):
        run = self.make_run()
        file_id = self.file_id(self.a_raw, "c.mca")
        response = self.client.post(
            self.url("stored", run),
            json.dumps({"file_ids": [file_id]}),
            content_type="application/json",
        )
        body = response.json()
        self.assertEqual(len(body["accepted"]), 1, body)
        item = MeasurementItem.objects.get(run=run)
        self.assertEqual(item.origin, "stored")
        self.assertEqual(str(item.source_file_id), file_id)
        self.assertEqual(str(item.source_analysis_id), str(self.a_raw.pk))
        self.assertEqual(item.sha256, hashlib.sha256(b"raw").hexdigest())
        again = self.client.post(
            self.url("stored", run),
            json.dumps({"file_ids": [file_id]}),
            content_type="application/json",
        ).json()
        self.assertEqual(again["rejected"][0]["reason"], "duplicate")

    def test_refuses_a_file_of_another_document_or_with_a_twin(self):
        elsewhere = self.new_resource("analysis", "Elsewhere")
        foreign = self.stored_file(elsewhere, "z.mca", b"z")
        twin = self.file_id(self.a_link, "a.mca")
        run = self.make_run()
        body = self.client.post(
            self.url("stored", run),
            json.dumps({"file_ids": [foreign, twin, str(uuid.uuid4())]}),
            content_type="application/json",
        ).json()
        self.assertEqual(body["accepted"], [])
        self.assertEqual({r["reason"] for r in body["rejected"]}, {"not_in_document"})
        self.assertFalse(MeasurementItem.objects.filter(run=run).exists())

    def test_bad_body(self):
        run = self.make_run()
        response = self.client.post(
            self.url("stored", run),
            json.dumps({"file_ids": ["x"]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class PrepareTests(IntakeCase):
    def test_prepare_enqueues_the_task_after_commit(self):
        run = self.make_run()
        MeasurementItem.objects.create(
            run=run, origin="upload", source_name="a.0", sha256="a" * 64, size=1
        )
        with mock.patch.object(intake, "current_app") as app:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(self.url("prepare", run))
            self.assertEqual(response.status_code, 202)
            app.send_task.assert_called_once_with(
                "manuspectrum.measurement_prepare", args=[str(run.id)]
            )
            again = self.client.post(self.url("prepare", run))
            self.assertEqual(again.status_code, 200)
            app.send_task.assert_called_once()
        run.refresh_from_db()
        self.assertEqual(run.state, "preparing")

    def test_prepare_needs_files_and_a_collecting_run(self):
        empty = self.make_run()
        self.assertEqual(self.client.post(self.url("prepare", empty)).status_code, 409)
        written = self.make_run(state="written")
        self.assertEqual(
            self.client.post(self.url("prepare", written)).status_code, 409
        )
