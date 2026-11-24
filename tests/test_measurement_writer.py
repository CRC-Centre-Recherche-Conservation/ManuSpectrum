import hashlib
import json
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache, caches
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from arches.app.models.models import (
    CardModel,
    EditLog,
    File,
    GraphModel,
    GraphXPublishedGraph,
    Language,
    Node,
    NodeGroup,
    PublishedGraph,
    ResourceInstance,
    TileModel,
)

from manuspectrum.constants.xy_presets import (
    DATA_FILE_NODE_ID,
    DATA_FILE_NODEGROUP_ID,
    TECHNIQUE_LIST_ID,
    TECHNIQUE_NODE_ID,
    TECHNIQUE_NODEGROUP_ID,
    TECHNIQUE_PRESETS,
    XY_PRESETS,
)
from manuspectrum.measurement_files import intake, staging, writer
from manuspectrum.models import MeasurementItem, MeasurementRun
from manuspectrum.tasks import measurement_write_task
from tests.explorer_fixtures import ExplorerCase

XRF_ITEM = next(i for i, preset in TECHNIQUE_PRESETS.items() if preset == "xrf")
CSV = b"energy,counts\n1,2\n2,3\n"
DESCRIPTION = {"en": "Tube voltage: 35 kV", "fr": "Tension du tube : 35 kV"}
ENTRY_KEYS = {
    "url",
    "name",
    "path",
    "size",
    "type",
    "index",
    "status",
    "accepted",
    "file_id",
    "lastModified",
    "altText",
    "title",
    "attribution",
    "description",
    "license",
}


def technique_value(item_id=XRF_ITEM):
    return [
        {
            "uri": "61296",
            "list_id": TECHNIQUE_LIST_ID,
            "labels": [
                {
                    "id": str(uuid.uuid4()),
                    "value": "technique",
                    "language_id": "en",
                    "list_item_id": item_id,
                    "valuetype_id": "prefLabel",
                }
            ],
        }
    ]


def publish_graph(graph):
    """A publication of *graph* holding its nodes, as ``Tile.save`` reads them (8.2 saves through the published graph)."""
    nodes = [
        {
            "nodeid": str(node.nodeid),
            "name": node.name,
            "alias": node.alias,
            "datatype": node.datatype,
            "config": getattr(node.config, "raw_value", node.config) or {},
            "graph_id": str(graph.pk),
            "nodegroup_id": str(node.nodegroup_id) if node.nodegroup_id else None,
            "istopnode": node.istopnode,
        }
        for node in Node.objects.filter(graph=graph)
    ]
    publication = GraphXPublishedGraph.objects.create(graph=graph)
    for language in Language.objects.all():
        PublishedGraph.objects.create(
            publication=publication,
            language=language,
            serialized_graph={
                "nodes": nodes,
                "root": {"ontologyclass": None},
                "cards": [],
            },
        )
    GraphModel.objects.filter(pk=graph.pk).update(publication=publication)


def build_real_nodes(cls):
    """Give the file and technique nodes the ids and nodegroups of the real model.

    The file nodegroup hangs from a ``Data resource`` parent nodegroup
    (cardinality 1), and both triggers address the tiles by those ids.
    """
    files = cls.nodes[("analysis", "measurement_point_data")]
    old = files.nodegroup
    parent = NodeGroup.objects.create(nodegroupid=uuid.uuid4(), cardinality="1")
    Node.objects.create(
        nodeid=parent.pk,
        graph=cls.graphs["analysis"],
        nodegroup=parent,
        name="data_resource",
        alias="data_resource",
        datatype="semantic",
        istopnode=False,
    )
    group = NodeGroup.objects.create(
        nodegroupid=DATA_FILE_NODEGROUP_ID, cardinality="n", parentnodegroup=parent
    )
    Node.objects.filter(pk=files.pk).update(
        nodegroup=group,
        config={"maxFiles": 5, "maxFileSize": None, "imagesOnly": False},
    )
    old.delete()
    for owner, name in ((parent, "data_resource"), (group, "measurement_point_data")):
        CardModel.objects.create(
            cardid=uuid.uuid4(),
            name=name,
            graph=cls.graphs["analysis"],
            nodegroup=owner,
            active=True,
            visible=True,
        )
    technique = cls.nodes[("analysis", "analysis_technique_used")]
    old = technique.nodegroup
    technique.delete()
    old.delete()
    group = NodeGroup.objects.create(
        nodegroupid=TECHNIQUE_NODEGROUP_ID, cardinality="1"
    )
    cls.nodes[("analysis", "analysis_technique_used")] = Node.objects.create(
        nodeid=TECHNIQUE_NODE_ID,
        graph=cls.graphs["analysis"],
        nodegroup=group,
        name="analysis_technique_used",
        alias="analysis_technique_used",
        datatype="reference",
        istopnode=False,
    )
    cls.parent_group = parent
    publish_graph(cls.graphs["analysis"])
    cls.nodes[("analysis", "measurement_point_data")] = Node.objects.get(pk=files.pk)


class WriterFixtures:
    """Items, staged bytes and helpers shared by the two kinds of test case."""

    def prepare_run(self):
        self.run = MeasurementRun.objects.create(
            id=uuid.uuid4(),
            user=self.editor,
            document_id=self.documents["open"].pk,
            language="en",
            state="writing",
        )
        return self.run

    def new_analysis(self, name="Target", technique=XRF_ITEM, **kwargs):
        analysis = self.new_resource("analysis", name, **kwargs)
        if technique:
            TileModel.objects.create(
                resourceinstance=analysis,
                nodegroup_id=TECHNIQUE_NODEGROUP_ID,
                data={TECHNIQUE_NODE_ID: technique_value(technique)},
            )
        return analysis

    def make_item(
        self,
        analysis,
        name="X7_f1r.mca",
        *,
        run=None,
        raw=None,
        csv=CSV,
        origin="upload",
        outcome="csv",
        reason="",
        display=("technique", None),
        lone=False,
        **extra,
    ):
        run = run or self.run
        raw = raw if raw is not None else b"RAW " + name.encode()
        item = MeasurementItem(
            run=run,
            origin=origin,
            source_name=name,
            sha256=hashlib.sha256(raw).hexdigest(),
            size=len(raw),
            outcome=outcome,
            reason=reason,
            proposed_analysis_id=analysis.pk,
            decision="ready",
            state="prepared",
            display_source=display[0],
            display_config_id=display[1],
            **extra,
        )
        if origin == "upload":
            item.staged_name = f"{item.id}-{name}"
        item.save()
        if origin == "upload":
            staging.store(run.id, item.id, raw, name)
        if outcome == "csv" and not lone:
            staging.store(run.id, item.id, csv, "converted.csv")
            staging.store(
                run.id,
                item.id,
                json.dumps(DESCRIPTION).encode("utf-8"),
                "description.json",
            )
        return item

    def write(self, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            while writer.write_run(self.run, **kwargs):
                pass
        self.run.refresh_from_db()

    def tiles(self, analysis, group=DATA_FILE_NODEGROUP_ID):
        return list(
            TileModel.objects.filter(
                resourceinstance=analysis, nodegroup_id=group
            ).order_by("sortorder", "tileid")
        )

    def entries(self, analysis):
        return [
            entry
            for tile in self.tiles(analysis)
            for entry in tile.data[DATA_FILE_NODE_ID]
        ]

    def by_name(self, analysis):
        return {entry["name"]: entry for entry in self.entries(analysis)}

    def uploaded_names(self):
        directory = Path(self._media_root) / "uploadedfiles"
        return sorted(p.name for p in directory.iterdir()) if directory.exists() else []

    def fresh(self, item):
        item.refresh_from_db()
        return item


class WriterCase(WriterFixtures, ExplorerCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        build_real_nodes(cls)

    def setUp(self):
        super().setUp()
        self.prepare_run()
        self.target = self.new_analysis()


class AddOnlyTests(WriterCase):
    def test_raw_and_csv_become_two_new_tiles_under_a_new_parent(self):
        item = self.make_item(self.target)
        self.write()
        tiles = self.tiles(self.target)
        self.assertEqual(len(tiles), 2)
        parents = self.tiles(self.target, self.parent_group.pk)
        self.assertEqual(len(parents), 1)
        self.assertEqual({t.parenttile_id for t in tiles}, {parents[0].pk})
        self.assertEqual(
            sorted(e["name"] for e in self.entries(self.target)),
            ["X7_f1r.csv", "X7_f1r.mca"],
        )
        self.assertEqual(
            (self.run.state, self.fresh(item).state), ("written", "written")
        )
        self.assertEqual(len(self.fresh(item).written["files"]), 2)

    def test_the_entries_have_the_shape_of_the_file_widget(self):
        self.make_item(self.target)
        self.write()
        raw = self.by_name(self.target)["X7_f1r.mca"]
        csv = self.by_name(self.target)["X7_f1r.csv"]
        for entry in (raw, csv):
            self.assertTrue(ENTRY_KEYS <= set(entry), set(entry))
            self.assertEqual((entry["status"], entry["accepted"]), ("uploaded", True))
            self.assertEqual(entry["url"], f"/files/{entry['file_id']}")
            self.assertTrue(entry["path"].startswith("uploadedfiles/"))
            self.assertEqual(
                File.objects.get(pk=entry["file_id"]).path.name, entry["path"]
            )
            self.assertEqual(entry["license"]["id"], "CC-BY-SA-4.0")
        self.assertEqual(csv["type"], "text/csv")
        self.assertEqual(raw["type"], "application/octet-stream")
        self.assertEqual(csv["size"], len(CSV))
        for code, text in DESCRIPTION.items():
            self.assertEqual(
                csv["description"][code], {"value": text, "direction": "ltr"}
            )
        self.assertEqual(raw["description"]["en"]["value"], "")
        self.assertEqual(csv["msSourceFileId"], raw["file_id"])
        self.assertEqual(
            csv["msSourceSha256"], hashlib.sha256(b"RAW X7_f1r.mca").hexdigest()
        )
        self.assertNotIn("msSourceFileId", raw)
        for tile in self.tiles(self.target):
            entry = tile.data[DATA_FILE_NODE_ID][0]
            self.assertEqual(File.objects.get(pk=entry["file_id"]).tile_id, tile.pk)

    def test_no_create_row_and_every_tile_create_row_names_the_user(self):
        self.make_item(self.target)
        self.write()
        rows = EditLog.objects.filter(resourceinstanceid=str(self.target.pk))
        self.assertFalse(rows.filter(edittype="create").exists())
        created = rows.filter(transactionid=self.run.transaction_id)
        self.assertEqual(created.count(), 3)
        for row in created:
            self.assertEqual(row.edittype, "tile create")
            self.assertEqual(row.userid, str(self.editor.pk))
            self.assertEqual(row.user_username, self.editor.username)
            self.assertNotEqual(row.note, "resource creation")

    def test_what_existed_is_untouched(self):
        existing = self.stored_file(self.target, "old.mca", b"old raw")
        self.stored_file(self.target, "old.csv", b"x,y\n")
        before_tiles = {
            t.pk: digest_of(t.data)
            for t in TileModel.objects.filter(resourceinstance=self.target)
        }
        before_files = {
            f.pk: (f.path.name, f.tile_id, bytes(f.thumbnail_data or b""))
            for f in File.objects.all()
        }
        before_log = list(
            EditLog.objects.filter(resourceinstanceid=str(self.target.pk)).values_list(
                "pk", flat=True
            )
        )
        self.make_item(self.target)
        self.write()
        for tile in TileModel.objects.filter(pk__in=before_tiles):
            self.assertEqual(digest_of(tile.data), before_tiles[tile.pk])
        for pk, state in before_files.items():
            row = File.objects.get(pk=pk)
            self.assertEqual(
                (row.path.name, row.tile_id, bytes(row.thumbnail_data or b"")), state
            )
        self.assertTrue(
            set(before_log)
            <= set(
                EditLog.objects.filter(
                    resourceinstanceid=str(self.target.pk)
                ).values_list("pk", flat=True)
            )
        )
        self.assertEqual(File.objects.get(pk=existing).path.read(), b"old raw")

    def test_an_existing_parent_tile_is_reused_not_saved(self):
        parent = TileModel.objects.create(
            resourceinstance=self.target,
            nodegroup=self.parent_group,
            data={str(self.parent_group.pk): None},
        )
        item = self.make_item(self.target)
        self.write()
        self.assertEqual(self.tiles(self.target, self.parent_group.pk), [parent])
        self.assertEqual(
            {t.parenttile_id for t in self.tiles(self.target)}, {parent.pk}
        )
        self.assertEqual(
            self.fresh(item).written["parent_tile"],
            {"id": str(parent.pk), "created": False},
        )

    def test_a_missing_parent_tile_is_created_once_for_several_items(self):
        first = self.make_item(self.target, "A.mca")
        second = self.make_item(self.target, "B.mca")
        self.write()
        self.assertEqual(len(self.tiles(self.target, self.parent_group.pk)), 1)
        self.assertEqual(len(self.tiles(self.target)), 4)
        created = [
            self.fresh(i).written["parent_tile"]["created"] for i in (first, second)
        ]
        self.assertEqual(sorted(created), [False, True])

    def test_a_non_reviewer_editor_writes_real_data_not_a_provisional_edit(self):
        self.assertFalse(self.editor.groups.filter(name="Resource Reviewer").exists())
        self.make_item(self.target)
        self.write()
        for tile in self.tiles(self.target):
            self.assertTrue(tile.data[DATA_FILE_NODE_ID])
            self.assertFalse(tile.provisionaledits)

    def test_digests_are_the_sha1_of_the_stored_data(self):
        item = self.fresh(self.make_item(self.target))
        self.write()
        written = self.fresh(item).written
        self.assertEqual(len(written["tiles"]), 2)
        for tile in written["tiles"]:
            stored = TileModel.objects.get(pk=tile["id"]).data
            self.assertEqual(written["digests"][tile["id"]], digest_of(stored))
        parent = written["parent_tile"]["id"]
        self.assertIn(parent, written["digests"])


def digest_of(data):
    return hashlib.sha1(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class DisplayTests(WriterCase):
    def csv_entry(self):
        return self.by_name(self.target)["X7_f1r.csv"]

    def test_technique_display_is_stamped_auto_by_the_trigger(self):
        self.make_item(self.target)
        self.write()
        entry = self.csv_entry()
        self.assertEqual(entry["rendererConfigSource"], "auto")
        self.assertEqual(entry["rendererConfig"], XY_PRESETS["xrf"]["config_id"])
        raw = self.by_name(self.target)["X7_f1r.mca"]
        self.assertNotIn("rendererConfigSource", raw)

    def test_a_chosen_display_is_written_manual(self):
        config = XY_PRESETS["fors"]["config_id"]
        self.make_item(self.target, display=("chosen", uuid.UUID(config)))
        self.write()
        entry = self.csv_entry()
        self.assertEqual(entry["rendererConfigSource"], "manual")
        self.assertEqual(entry["rendererConfig"], config)

    def test_the_converter_display_is_written_manual(self):
        config = XY_PRESETS["xrf_channel"]["config_id"]
        self.make_item(self.target, display=("converter", uuid.UUID(config)))
        self.write()
        entry = self.csv_entry()
        self.assertEqual(
            (entry["rendererConfigSource"], entry["rendererConfig"]),
            ("manual", config),
        )

    def test_no_display_is_never_stamped(self):
        self.make_item(self.target, display=("none", None))
        self.write()
        entry = self.csv_entry()
        self.assertEqual(entry["rendererConfigSource"], "manual")
        self.assertNotIn("rendererConfig", entry)

    def test_an_analysis_without_technique_gets_no_keys_on_the_technique_display(self):
        other = self.new_analysis("No technique", technique=None)
        self.make_item(other)
        self.write()
        entry = self.by_name(other)["X7_f1r.csv"]
        self.assertNotIn("rendererConfigSource", entry)
        self.assertNotIn("rendererConfig", entry)


class KindTests(WriterCase):
    def test_a_stored_raw_gets_its_csv_only_and_its_licence(self):
        licence = {
            "id": "CC-BY-4.0",
            "url": "https://creativecommons.org/licenses/by/4.0/",
        }
        raw_id = self.stored_file(
            self.target, "old.mca", b"stored raw", licence=licence
        )
        item = self.make_item(
            self.target,
            "old.mca",
            raw=b"stored raw",
            origin="stored",
            source_file_id=raw_id,
        )
        before = len(self.tiles(self.target))
        self.write()
        self.assertEqual(len(self.tiles(self.target)), before + 1)
        csv = self.by_name(self.target)["old.csv"]
        self.assertEqual(csv["msSourceFileId"], raw_id)
        self.assertEqual(
            csv["msSourceSha256"], hashlib.sha256(b"stored raw").hexdigest()
        )
        self.assertEqual(csv["license"], licence)
        self.assertEqual(len(self.fresh(item).written["files"]), 1)

    def test_a_stored_raw_only_item_writes_nothing(self):
        raw_id = self.stored_file(self.target, "old.mca", b"stored raw")
        item = self.make_item(
            self.target,
            "old.mca",
            raw=b"stored raw",
            origin="stored",
            outcome="raw_only",
            reason="kept_raw",
            source_file_id=raw_id,
        )
        before = TileModel.objects.count()
        self.write()
        self.assertEqual(TileModel.objects.count(), before)
        self.assertEqual(self.fresh(item).state, "written")
        self.assertEqual(self.fresh(item).written["files"], [])

    def test_an_uploaded_raw_only_item_writes_the_raw_alone(self):
        item = self.make_item(
            self.target, outcome="raw_only", reason="kept_raw", display=("none", None)
        )
        self.write()
        self.assertEqual(list(self.by_name(self.target)), ["X7_f1r.mca"])
        self.assertEqual(self.fresh(item).state, "written")

    def test_a_lone_csv_is_written_as_is_without_description_or_link(self):
        data = b"x,y\n1,2\n2,3\n"
        item = self.make_item(self.target, "lab.csv", raw=data, lone=True)
        self.write()
        entry = self.by_name(self.target)["lab.csv"]
        self.assertEqual(File.objects.get(pk=entry["file_id"]).path.read(), data)
        self.assertEqual(entry["description"]["en"]["value"], "")
        self.assertNotIn("msSourceFileId", entry)
        self.assertNotIn("msSourceSha256", entry)
        self.assertEqual(len(self.fresh(item).written["tiles"]), 1)

    def test_an_unreadable_raw_is_written_with_the_lab_csv_linked_to_it(self):
        raw = self.make_item(
            self.target,
            "odd.mca",
            outcome="unreadable",
            reason="bad",
            display=("none", None),
        )
        lab_bytes = b"x,y\n5,6\n7,8\n"
        lab = self.make_item(self.target, "odd.csv", raw=lab_bytes, lone=True)
        MeasurementItem.objects.filter(pk=raw.pk).update(paired_item=lab)
        MeasurementItem.objects.filter(pk=lab.pk).update(paired_item=raw)
        self.write()
        names = self.by_name(self.target)
        self.assertEqual(sorted(names), ["odd.csv", "odd.mca"])
        self.assertEqual(
            File.objects.get(pk=names["odd.csv"]["file_id"]).path.read(), lab_bytes
        )
        self.assertEqual(
            names["odd.csv"]["msSourceFileId"], names["odd.mca"]["file_id"]
        )
        self.assertEqual(names["odd.csv"]["description"]["en"]["value"], "")
        self.assertEqual(
            (self.fresh(raw).state, self.fresh(lab).state), ("written", "written")
        )
        self.assertEqual(self.fresh(lab).written, {"with": str(raw.pk)})
        self.assertEqual(len(self.tiles(self.target)), 2)

    def test_a_converted_csv_over_the_viewer_limit_leaves_the_raw_alone(self):
        item = self.make_item(self.target)
        with override_settings(SPECTRUM_PREVIEW_MAX_BYTES=5):
            self.write()
        self.assertEqual(list(self.by_name(self.target)), ["X7_f1r.mca"])
        item = self.fresh(item)
        self.assertEqual(
            (item.state, item.outcome, item.reason),
            ("written", "raw_only", "too_large"),
        )

    def test_a_lone_csv_over_the_limit_is_refused(self):
        item = self.make_item(self.target, "lab.csv", raw=b"x,y\n1,2\n", lone=True)
        with override_settings(SPECTRUM_PREVIEW_MAX_BYTES=3):
            self.write()
        self.assertEqual(self.entries(self.target), [])
        item = self.fresh(item)
        self.assertEqual((item.state, item.error), ("failed", "too_large"))
        self.assertEqual(self.uploaded_names(), [])


class AlreadyThereTests(WriterCase):
    def test_a_second_run_adding_the_same_file_adds_nothing(self):
        self.make_item(self.target, raw=b"same bytes")
        self.write()
        before = (TileModel.objects.count(), File.objects.count())
        second = MeasurementRun.objects.create(
            id=uuid.uuid4(),
            user=self.editor,
            document_id=self.documents["open"].pk,
            language="en",
            state="writing",
        )
        again = self.make_item(self.target, run=second, raw=b"same bytes")
        self.run = second
        self.write()
        self.assertEqual((TileModel.objects.count(), File.objects.count()), before)
        again = self.fresh(again)
        self.assertEqual(again.state, "written")
        self.assertEqual(again.written, {"skipped": writer.ALREADY_WRITTEN})

    def test_a_raw_kept_alone_is_found_by_its_bytes(self):
        self.stored_file(self.target, "have.mca", b"present")
        item = self.make_item(
            self.target,
            "other.mca",
            raw=b"present",
            outcome="raw_only",
            reason="kept_raw",
        )
        before = TileModel.objects.count()
        self.write()
        self.assertEqual(TileModel.objects.count(), before)
        self.assertEqual(self.fresh(item).written, {"skipped": writer.ALREADY_WRITTEN})


class RecheckTests(WriterCase):
    def test_retired_deleted_and_unwritable_analyses_fail_the_others_go_on(self):
        retired = self.new_analysis(
            "Retired", state="d95d9c0e-0e2c-4450-93a3-d788b91abcc8"
        )
        gone = self.new_analysis("Gone")
        forbidden = self.new_analysis("Forbidden")
        fine = self.new_analysis("Fine")
        items = {
            key: self.make_item(analysis, f"{key}.mca")
            for key, analysis in (
                ("retired", retired),
                ("gone", gone),
                ("forbidden", forbidden),
                ("fine", fine),
            )
        }
        ResourceInstance.objects.filter(pk=gone.pk).delete()
        real = writer.user_can_edit_resource

        def deny_forbidden(user, resource=None, **kwargs):
            if resource is not None and resource.pk == forbidden.pk:
                return False
            return real(user, resource=resource, **kwargs)

        with mock.patch.object(writer, "user_can_edit_resource", deny_forbidden):
            self.write()
        states = {
            k: (self.fresh(i).state, self.fresh(i).error) for k, i in items.items()
        }
        self.assertEqual(
            states,
            {
                "retired": ("failed", "not_editable"),
                "gone": ("failed", "analysis_missing"),
                "forbidden": ("failed", "not_editable"),
                "fine": ("written", ""),
            },
        )
        self.assertEqual(File.objects.count(), 2)
        self.assertEqual(len(self.uploaded_names()), 2)
        for analysis in (retired, forbidden):
            self.assertEqual(self.tiles(analysis), [])
        self.assertEqual(self.run.state, "written")

    def test_an_analysis_the_run_cannot_name_fails_its_items(self):
        item = self.make_item(self.target)
        MeasurementItem.objects.filter(pk=item.pk).update(proposed_analysis_id=None)
        self.write()
        self.assertEqual(
            (self.fresh(item).state, self.fresh(item).error), ("failed", "no_analysis")
        )


class FailureTests(WriterCase):
    def test_an_exception_after_the_csv_file_leaves_no_file_no_bytes_no_tile(self):
        item = self.make_item(self.target)
        real = writer._save_tile

        def boom(run, tile, written, role):
            if role == "csv":
                raise RuntimeError("injected")
            return real(run, tile, written, role)

        before = (File.objects.count(), TileModel.objects.count())
        with mock.patch.object(writer, "_save_tile", boom):
            self.write()
        self.assertEqual((File.objects.count(), TileModel.objects.count()), before)
        self.assertEqual(self.uploaded_names(), [])
        item = self.fresh(item)
        self.assertEqual((item.state, item.error), ("failed", "write_failed"))
        self.assertEqual(item.written, {})
        self.assertEqual(self.tiles(self.target, self.parent_group.pk), [])

    def test_a_failed_item_does_not_stop_the_others_of_its_analysis(self):
        bad = self.make_item(self.target, "bad.mca")
        good = self.make_item(self.target, "good.mca")
        real = writer._save_tile

        def boom(run, tile, written, role):
            name = tile.data.get(DATA_FILE_NODE_ID, [{}])[0].get("name", "")
            if name.startswith("bad"):
                raise RuntimeError("injected")
            return real(run, tile, written, role)

        with mock.patch.object(writer, "_save_tile", boom):
            self.write()
        self.assertEqual(self.fresh(bad).state, "failed")
        self.assertEqual(self.fresh(good).state, "written")
        self.assertEqual(sorted(self.by_name(self.target)), ["good.csv", "good.mca"])
        self.assertEqual(len(self.uploaded_names()), 2)

    def test_a_rerun_writes_the_failed_item_once(self):
        item = self.make_item(self.target)
        with mock.patch.object(writer, "_save_tile", side_effect=RuntimeError("x")):
            self.write()
        self.assertEqual(self.fresh(item).state, "failed")
        MeasurementItem.objects.filter(pk=item.pk).update(
            state="prepared", error="", decision="ready"
        )
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="writing")
        self.write()
        self.write()
        self.assertEqual(self.fresh(item).state, "written")
        self.assertEqual(
            sorted(self.by_name(self.target)), ["X7_f1r.csv", "X7_f1r.mca"]
        )
        self.assertEqual(len(self.tiles(self.target)), 2)
        self.assertEqual(len(self.uploaded_names()), 2)


class RunTests(WriterCase):
    def test_each_analysis_is_indexed_once_after_commit(self):
        other = self.new_analysis("Other")
        self.make_item(self.target, "A.mca")
        self.make_item(self.target, "B.mca")
        self.make_item(other, "C.mca")
        with mock.patch.object(writer, "_index_resource") as index:
            self.write()
        self.assertEqual(
            sorted(c.args[0] for c in index.call_args_list),
            sorted([str(self.target.pk), str(other.pk)]),
        )

    def test_no_index_for_an_analysis_that_received_nothing(self):
        self.stored_file(self.target, "have.mca", b"present")
        self.make_item(
            self.target, "x.mca", raw=b"present", outcome="raw_only", reason="kept_raw"
        )
        with mock.patch.object(writer, "_index_resource") as index:
            self.write()
        index.assert_not_called()

    def test_a_chunk_reports_whether_items_remain(self):
        for n in range(3):
            self.make_item(self.new_analysis(f"T{n}"), f"f{n}.mca")
        with mock.patch.object(writer, "_index_resource"):
            self.assertTrue(writer.write_run(self.run, chunk=1))
            self.assertTrue(writer.write_run(self.run, chunk=1))
            self.assertFalse(writer.write_run(self.run, chunk=1))
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "written")
        self.assertFalse(writer.write_run(self.run))

    def test_the_end_notifies_the_owner_in_the_run_language_without_a_type(self):
        MeasurementRun.objects.filter(pk=self.run.pk).update(language="fr")
        self.make_item(self.target)
        with mock.patch("arches.app.tasks.notify_completion") as notify:
            self.write()
        self.assertIsNotNone(self.run.finished_at)
        notify.assert_called_once()
        args, kwargs = notify.call_args
        self.assertEqual(args[1], self.editor)
        self.assertEqual(len(args), 2)
        self.assertEqual(kwargs, {})
        self.assertEqual(
            args[0], "Fichiers de mesure - ajoutés : 2, analyses : 1, échecs : 0."
        )

    def test_the_message_in_english(self):
        self.make_item(self.target)
        with mock.patch("arches.app.tasks.notify_completion") as notify:
            self.write()
        self.assertEqual(
            notify.call_args.args[0],
            "Measurement files - added: 2, analyses: 1, failed: 0.",
        )

    def test_a_stop_is_honoured_between_analyses_and_keeps_what_was_written(self):
        first = self.make_item(self.new_analysis("First"), "a.mca")
        second = self.make_item(self.new_analysis("Second"), "b.mca")
        real = writer.write_analysis

        def write_then_stop(run, analysis_id, items):
            result = real(run, analysis_id, items)
            MeasurementRun.objects.filter(pk=run.pk).update(stop_requested=True)
            return result

        with mock.patch.object(writer, "write_analysis", write_then_stop):
            with mock.patch.object(writer, "_index_resource"):
                self.assertFalse(writer.write_run(self.run, chunk=10))
        self.run.refresh_from_db()
        self.assertEqual((self.run.state, self.run.stop_requested), ("review", False))
        self.assertEqual(
            sorted((self.fresh(first).state, self.fresh(second).state)),
            ["prepared", "written"],
        )
        self.assertIsNone(self.fresh(second).claimed_at)
        self.assertIsNone(self.run.finished_at)

    def test_a_run_not_writing_does_nothing(self):
        item = self.make_item(self.target)
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="review")
        self.assertFalse(writer.write_run(self.run))
        self.assertEqual(self.fresh(item).state, "prepared")
        self.assertEqual(self.tiles(self.target), [])

    def test_the_task_sends_itself_again_while_items_remain(self):
        for n in range(2):
            self.make_item(self.new_analysis(f"T{n}"), f"f{n}.mca")
        with override_settings(MEASUREMENT_WRITE_CHUNK=1):
            with mock.patch.object(intake, "send") as send:
                with mock.patch.object(writer, "_index_resource"):
                    measurement_write_task(str(self.run.id))
                    send.assert_called_once_with(
                        intake.WRITE_TASK, self.run.id, countdown=1
                    )
                    send.reset_mock()
                    measurement_write_task(str(self.run.id))
                    send.assert_not_called()
        measurement_write_task("not-a-uuid")
        measurement_write_task(str(uuid.uuid4()))

    def test_file_types_admit_the_instrument_extensions(self):
        from django.conf import settings

        for extension in ("spx", "mzxml", "mzXML", "spc", "0", "1", "5", "9"):
            self.assertIn(extension, settings.FILE_TYPES)


class WriteRouteTests(WriterCase):
    def post(self, action, user=None, run=None):
        client = self.client
        client.force_login(user or self.editor)
        run = run or self.run
        return client.post(f"/api/measurement-files/runs/{run.id}/{action}")

    def setUp(self):
        super().setUp()
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="review")
        patcher = mock.patch.object(intake, "send")
        self.send = patcher.start()
        self.addCleanup(patcher.stop)

    def test_write_starts_a_reviewed_run(self):
        self.make_item(self.target)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post("write")
        self.assertEqual(response.status_code, 202)
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "writing")
        self.send.assert_called_once_with(intake.WRITE_TASK, self.run.id)

    def test_write_is_refused_with_a_pending_item_or_nothing_to_write(self):
        self.assertEqual(self.post("write").json(), {"error": "nothing_to_write"})
        item = self.make_item(self.target)
        MeasurementItem.objects.filter(pk=item.pk).update(decision="pending")
        response = self.post("write")
        self.assertEqual(
            (response.status_code, response.json()["error"]), (409, "items_pending")
        )
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="collecting")
        self.assertEqual(self.post("write").json(), {"error": "run_not_in_review"})
        self.send.assert_not_called()

    def test_write_while_writing_is_a_no_op(self):
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="writing")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post("write")
        self.assertEqual(
            (response.status_code, response.json()), (200, {"state": "writing"})
        )
        self.send.assert_not_called()

    def test_another_user_gets_a_bodyless_404(self):
        other = User.objects.create_user("other_editor", password="pw")
        other.groups.add(Group.objects.get(name="Resource Editor"))
        for action in ("write", "retry", "stop"):
            response = self.post(action, user=other)
            self.assertEqual((response.status_code, response.content), (404, b""))

    def test_retry_puts_the_failed_writes_back_and_leaves_the_others(self):
        failed = self.make_item(self.target, "a.mca")
        prep = self.make_item(self.target, "b.mca")
        MeasurementItem.objects.filter(pk=failed.pk).update(
            state="failed", error="write_failed"
        )
        MeasurementItem.objects.filter(pk=prep.pk).update(
            state="failed", error="prepare"
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post("retry")
        self.assertEqual((response.status_code, response.json()["retried"]), (202, 1))
        self.assertEqual(self.fresh(failed).state, "prepared")
        self.assertEqual(self.fresh(failed).error, "")
        self.assertEqual(
            (self.fresh(prep).state, self.fresh(prep).error), ("failed", "prepare")
        )
        self.run.refresh_from_db()
        self.assertEqual(self.run.state, "writing")
        self.send.assert_called_once()

    def test_retry_with_nothing_failed_is_refused(self):
        self.assertEqual(self.post("retry").json(), {"error": "nothing_to_retry"})

    def test_stop_flags_a_writing_run_only(self):
        self.assertEqual(self.post("stop").status_code, 409)
        MeasurementRun.objects.filter(pk=self.run.pk).update(state="writing")
        response = self.post("stop")
        self.assertEqual(response.status_code, 202)
        self.run.refresh_from_db()
        self.assertTrue(self.run.stop_requested)


class ConcurrencyTests(WriterFixtures, TransactionTestCase):
    serialized_rollback = True

    for _name in (
        "new_resource",
        "tile",
        "tile_values",
        "string_value",
        "refs",
        "reference_value",
        "_item_id",
        "term_list",
        "annotation_value",
        "stored_file",
    ):
        locals()[_name] = ExplorerCase.__dict__[_name]
    del _name

    def setUp(self):
        cache.clear()
        caches["user_permission"].clear()
        self._media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._media_root, True)
        media = override_settings(MEDIA_ROOT=self._media_root)
        media.enable()
        self.addCleanup(media.disable)
        type(self).setUpTestData.__func__(type(self))
        build_real_nodes(type(self))
        self.prepare_run()
        self.target = self.new_analysis()

    @classmethod
    def setUpTestData(cls):
        ExplorerCase.setUpTestData.__func__(cls)

    def captureOnCommitCallbacks(self, **kwargs):
        import contextlib

        return contextlib.nullcontext()

    def test_two_threads_writing_the_same_file_to_the_same_analysis_add_one_csv(self):
        other = MeasurementRun.objects.create(
            id=uuid.uuid4(),
            user=self.editor,
            document_id=self.documents["open"].pk,
            language="en",
            state="writing",
        )
        runs = [self.run, other]
        for run in runs:
            self.make_item(self.target, run=run, raw=b"identical bytes")
        real = writer._entries

        meeting = threading.Barrier(2)
        met = []

        def slow(scope):
            try:
                meeting.wait(timeout=1.5)
                met.append(True)
            except threading.BrokenBarrierError:
                pass
            return real(scope)

        def go(run):
            try:
                with mock.patch.object(writer, "_index_resource"):
                    while writer.write_run(run):
                        pass
            finally:
                connection.close()

        with mock.patch.object(writer, "_entries", slow):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(go, runs))
        csv_entries = [
            e for e in self.entries(self.target) if e["name"].endswith(".csv")
        ]
        self.assertEqual(len(csv_entries), 1)
        self.assertEqual(len(self.entries(self.target)), 2)
        self.assertEqual(len(self.tiles(self.target, self.parent_group.pk)), 1)
        states = sorted(
            MeasurementItem.objects.filter(run__in=runs).values_list("state", flat=True)
        )
        self.assertEqual(states, ["written", "written"])
        self.assertEqual(File.objects.count(), 2)
        self.assertEqual(len(self.uploaded_names()), 2)
