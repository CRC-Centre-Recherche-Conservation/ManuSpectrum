"""The ``annotation_frames`` command: check, stamp and unstamp the zones already stored.

Usage:
    python manage.py test tests.test_annotation_frames_command --settings=tests.test_settings --noinput
"""

import copy
import errno
import json
import os
import tempfile
import uuid
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from arches.app.models.models import (
    IIIFManifest,
    Node,
    NodeGroup,
    ResourceInstance,
    TileModel,
)

from manuspectrum.constants.biblissima import COMP_LOCATION_DOC_NODE
from manuspectrum.iiif import frame_writes, frames
from manuspectrum.management.commands import annotation_frames
from manuspectrum.utils.data_version import data_version

from tests import test_manifest_registry as reg
from tests.test_iiif_units import answered, info_json
from tests.test_zone_frame_writes import collection, sized_manifest, zone

SERVICE = reg.SERVICE
URL = reg.URL
READ_SERVICE = "https://read.example/iiif/b2/page1"
DOWN_SERVICE = "https://down.example/iiif/b3/page1"
LEGACY_SERVICE = "https://legacy.example/iiif/b4/page1"


def rectangle(width, height):
    w, h = width / 32, height / 32
    return {
        "type": "Polygon",
        "coordinates": [[[0, 0], [w, 0], [w, -h], [0, -h], [0, 0]]],
    }


@override_settings(IIIF_IMAGE_INFO_READ=True)
class AnnotationFramesCase(reg.AnnotationFixtures):
    def setUp(self):
        super().setUp()
        NodeGroup.objects.filter(pk=self.nodegroup.pk).update(cardinality="n")
        IIIFManifest.objects.create(url=URL, label="Book", manifest=sized_manifest())
        patcher = mock.patch("manuspectrum.iiif.units.safe_fetch")
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)
        self.fetch.side_effect = self.answer
        self.legacy = Node.objects.create(
            nodeid=COMP_LOCATION_DOC_NODE,
            graph=self.graph,
            nodegroup=self.nodegroup,
            name="doc",
            alias="doc",
            datatype="annotation",
            istopnode=False,
        )
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.journal = os.path.join(self.dir.name, "journal.jsonl")

    def answer(self, url, **kwargs):
        if url.startswith(SERVICE):
            return answered({}, status=403)
        if url.startswith(READ_SERVICE):
            return answered(info_json(4913, 6609, 512))
        return answered({}, status=503)

    def calls(self, service):
        return [c for c in self.fetch.call_args_list if c.args[0].startswith(service)]

    def tile(self, *features, node=None, edits=None):
        return TileModel.objects.create(
            tileid=uuid.uuid4(),
            resourceinstance=self.resource,
            nodegroup=self.nodegroup,
            data={str(node or self.annotation.pk): collection(*features)},
            provisionaledits=edits,
        )

    def row(self, tile):
        return TileModel.objects.get(pk=tile.pk)

    def run_command(self, *args):
        out = StringIO()
        call_command("annotation_frames", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def props(self, tile, fid, node=None):
        data = self.row(tile).data[str(node or self.annotation.pk)]
        return next(f for f in data["features"] if f["id"] == fid)["properties"]

    def snapshot(self):
        return {
            str(t.pk): json.dumps(
                [t.data, t.provisionaledits], sort_keys=True, default=str
            )
            for t in TileModel.objects.all()
        }


class StampTests(AnnotationFramesCase):
    def setUp(self):
        super().setUp()
        self.t1 = self.tile(zone("z1"), zone("z2", x=5.0))
        self.t2 = self.tile(zone("z3", canvas=READ_SERVICE))
        self.t3 = self.tile(zone("z4", canvas=DOWN_SERVICE))
        self.t4 = self.tile(zone("z5", canvas=SERVICE))

    def test_a_dry_run_writes_nothing(self):
        before, version = self.snapshot(), data_version()
        out = self.run_command("stamp")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(data_version(), version)
        self.assertIn("dry run", out)
        self.assertFalse(os.path.exists(self.journal))

    def test_apply_stamps_each_zone_with_one_read_per_service(self):
        out = self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertEqual(len(self.calls(SERVICE)), 1)
        self.assertEqual(len(self.calls(READ_SERVICE)), 1)
        self.assertEqual(
            {k: v for k, v in self.props(self.t2, "z3").items() if k.startswith("ms")},
            {
                "msUnit": 16,
                "msImageWidth": 4913,
                "msImageHeight": 6609,
                "msFrame": "read",
            },
        )
        for tile, fid in ((self.t1, "z1"), (self.t1, "z2"), (self.t4, "z5")):
            self.assertEqual(
                {k: v for k, v in self.props(tile, fid).items() if k.startswith("ms")},
                {
                    "msUnit": 16,
                    "msImageWidth": 4000,
                    "msImageHeight": 3000,
                    "msFrame": "estimated",
                },
            )
        self.assertIn("es reindex_database", out)
        lines = [json.loads(line) for line in open(self.journal)]
        self.assertEqual(
            sorted(line["feature"] for line in lines), ["z1", "z2", "z3", "z5"]
        )
        self.assertEqual(
            set(lines[0]),
            {
                "tile",
                "node",
                "provisional",
                "feature",
                "canvas",
                "digest",
                "before",
                "after",
            },
        )

    def test_an_unavailable_service_is_skipped_and_listed(self):
        out = self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertNotIn("msUnit", self.props(self.t3, "z4"))
        self.assertIn(DOWN_SERVICE, out)

    def test_the_service_option_restricts_the_run(self):
        self.run_command(
            "stamp", "--apply", "--journal", self.journal, "--service", READ_SERVICE
        )
        self.assertEqual(self.calls(SERVICE), [])
        self.assertIn("msUnit", self.props(self.t2, "z3"))
        self.assertNotIn("msUnit", self.props(self.t1, "z1"))

    def test_a_stamp_already_stored_is_never_overwritten(self):
        mine = {
            "msUnit": 8,
            "msImageWidth": 100,
            "msImageHeight": 200,
            "msFrame": "browser",
        }
        tile = self.tile(zone("kept", stamp=mine), zone("fresh", x=9.0))
        self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertEqual(
            {k: v for k, v in self.props(tile, "kept").items() if k.startswith("ms")},
            mine,
        )
        self.assertIn("msUnit", self.props(tile, "fresh"))
        lines = [json.loads(line) for line in open(self.journal)]
        self.assertNotIn("kept", [line["feature"] for line in lines])

    def test_a_zone_moved_between_the_read_and_the_write_is_left_alone(self):
        real = frame_writes.frame_for_service

        def moved(*args, **kwargs):
            frame = real(*args, **kwargs)
            row = self.row(self.t4)
            row.data[str(self.annotation.pk)]["features"][0]["geometry"]["coordinates"][
                0
            ][0][0] = 50.0
            TileModel.objects.filter(pk=self.t4.pk).update(data=row.data)
            return frame

        with mock.patch.object(frame_writes, "frame_for_service", moved):
            self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertNotIn("msUnit", self.props(self.t4, "z5"))

    def test_provisional_values_are_stamped_and_journaled(self):
        value = {str(self.annotation.pk): collection(zone("p1", canvas=READ_SERVICE))}
        tile = self.tile(zone("z9", canvas=READ_SERVICE), edits={"7": {"value": value}})
        self.run_command("stamp", "--apply", "--journal", self.journal)
        edited = self.row(tile).provisionaledits["7"]["value"][str(self.annotation.pk)]
        self.assertEqual(edited["features"][0]["properties"]["msFrame"], "read")
        lines = [json.loads(line) for line in open(self.journal)]
        self.assertIn("7", [line["provisional"] for line in lines])

    def test_apply_refuses_an_existing_journal(self):
        open(self.journal, "w").close()
        with self.assertRaises(CommandError):
            self.run_command("stamp", "--apply", "--journal", self.journal)

    def test_unstamp_restores_the_data_byte_for_byte(self):
        before = self.snapshot()
        self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertNotEqual(self.snapshot(), before)
        dry = self.snapshot()
        self.run_command("unstamp", "--journal", self.journal)
        self.assertEqual(self.snapshot(), dry)
        self.run_command("unstamp", "--journal", self.journal, "--apply")
        self.assertEqual(self.snapshot(), before)

    def test_unstamp_skips_a_zone_changed_since_and_lists_it(self):
        self.run_command("stamp", "--apply", "--journal", self.journal)
        row = self.row(self.t2)
        row.data[str(self.annotation.pk)]["features"][0]["properties"]["msUnit"] = 4
        TileModel.objects.filter(pk=self.t2.pk).update(data=row.data)
        out = self.run_command("unstamp", "--journal", self.journal, "--apply")
        self.assertIn("z3", out)
        self.assertEqual(self.props(self.t2, "z3")["msUnit"], 4)
        self.assertNotIn("msUnit", self.props(self.t1, "z1"))


class LegacyTests(AnnotationFramesCase):
    def legacy_zone(self, fid, width, height, canvas, manifest):
        feature = zone(fid, canvas=canvas, manifest=manifest)
        feature["geometry"] = rectangle(width, height)
        return feature

    def test_a_whole_page_zone_of_the_import_is_stamped_import_legacy(self):
        default = self.tile(
            self.legacy_zone("d", 4000, 5000, LEGACY_SERVICE, "https://m.example/x"),
            node=COMP_LOCATION_DOC_NODE,
        )
        sized = self.tile(
            self.legacy_zone("s", 4000, 3000, SERVICE, URL),
            node=COMP_LOCATION_DOC_NODE,
        )
        self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertEqual(self.fetch.call_count, 0)
        self.assertEqual(
            {
                k: v
                for k, v in self.props(default, "d", COMP_LOCATION_DOC_NODE).items()
                if k.startswith("ms")
            },
            {
                "msUnit": 32,
                "msImageWidth": 4000,
                "msImageHeight": 5000,
                "msFrame": "import-legacy",
            },
        )
        self.assertEqual(
            self.props(sized, "s", COMP_LOCATION_DOC_NODE)["msImageHeight"], 3000
        )

    def test_another_rectangle_is_read_like_any_zone(self):
        tile = self.tile(
            self.legacy_zone("o", 1234, 777, READ_SERVICE, URL),
            node=COMP_LOCATION_DOC_NODE,
        )
        self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertEqual(
            self.props(tile, "o", COMP_LOCATION_DOC_NODE)["msFrame"], "read"
        )


class CheckTests(AnnotationFramesCase):
    def test_counts_per_state_and_unresolved_canvases_without_a_request(self):
        mine = {
            "msUnit": 8,
            "msImageWidth": 100,
            "msImageHeight": 200,
            "msFrame": "browser",
        }
        guess = {**mine, "msFrame": "estimated"}
        self.tile(zone("a", stamp=mine), zone("b", x=4.0, stamp=guess))
        self.tile(zone("c", canvas=DOWN_SERVICE))
        before = self.snapshot()
        out = self.run_command("check")
        self.assertEqual(self.fetch.call_count, 0)
        self.assertEqual(self.snapshot(), before)
        self.assertRegex(out, r"measured\s*:?\s*1")
        self.assertRegex(out, r"estimated\s*:?\s*1")
        self.assertRegex(out, r"unstamped\s*:?\s*1")
        self.assertIn(DOWN_SERVICE, out)


class JournalGuardTests(AnnotationFramesCase):
    def setUp(self):
        super().setUp()
        self.t1 = self.tile(zone("z1"), zone("z2", x=5.0))

    def test_apply_needs_a_journal(self):
        with self.assertRaisesMessage(CommandError, "--journal"):
            self.run_command("stamp", "--apply")

    def test_an_unwritable_journal_fails_before_any_read(self):
        bad = os.path.join(self.dir.name, "missing", "journal.jsonl")
        with mock.patch.object(
            frame_writes, "frame_for_service", wraps=frame_writes.frame_for_service
        ) as spy:
            with self.assertRaisesMessage(CommandError, "cannot create the journal"):
                self.run_command("stamp", "--apply", "--journal", bad)
        spy.assert_not_called()
        self.assertEqual(self.fetch.call_count, 0)

    def test_an_empty_journal_is_removed(self):
        self.run_command(
            "stamp",
            "--apply",
            "--journal",
            self.journal,
            "--service",
            "https://x.example/a",
        )
        self.assertFalse(os.path.exists(self.journal))

    def test_the_summary_names_the_service_and_the_dry_run_says_it_reads(self):
        out = self.run_command("stamp", "--service", SERVICE)
        self.assertIn(f"Only the zones of {SERVICE}", out)
        self.assertIn("over the network", out)

    def test_a_journal_that_fails_to_sync_rolls_the_batch_back(self):
        before = self.snapshot()
        real = os.fsync

        def fails_on_files(fd):
            if os.path.isfile(f"/proc/self/fd/{fd}"):
                raise OSError("disk full")
            return real(fd)

        with mock.patch(
            "manuspectrum.management.commands.annotation_frames.os.fsync",
            fails_on_files,
        ):
            with self.assertRaisesMessage(CommandError, "journal write failed"):
                self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(os.path.exists(self.journal))

    def test_a_malformed_journal_names_its_line(self):
        good = {
            "tile": str(self.t1.pk),
            "node": "n",
            "provisional": None,
            "feature": "z1",
            "canvas": "c",
            "digest": "d",
            "before": {},
            "after": {},
        }
        for broken in (
            {**good, "before": []},
            {**good, "provisional": 3},
            {k: v for k, v in good.items() if k != "digest"},
            {**good, "tile": "nope"},
        ):
            with open(self.journal, "w") as handle:
                handle.write(json.dumps(good) + "\n" + json.dumps(broken) + "\n")
            with self.subTest(broken=broken):
                with self.assertRaisesMessage(CommandError, "line 2"):
                    self.run_command("unstamp", "--journal", self.journal)
        with open(self.journal, "w") as handle:
            handle.write("not json\n")
        with self.assertRaisesMessage(CommandError, "line 1"):
            self.run_command("unstamp", "--journal", self.journal)


class ReadAndBatchTests(AnnotationFramesCase):
    def test_one_frame_call_per_distinct_service_and_manifest(self):
        self.tile(zone("a"), zone("b", x=5.0))
        self.tile(zone("c", x=9.0))
        self.tile(zone("d", canvas=READ_SERVICE))
        self.tile(zone("e", x=3.0, canvas=READ_SERVICE))
        with mock.patch.object(
            frame_writes, "frame_for_service", wraps=frame_writes.frame_for_service
        ) as spy:
            self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertEqual(
            sorted(c.args[0] for c in spy.call_args_list),
            sorted([READ_SERVICE, SERVICE]),
        )

    def test_batches_of_one_tile_stamp_and_restore_everything(self):
        tiles = [self.tile(zone(f"z{i}", x=float(i))) for i in range(4)]
        before = self.snapshot()
        self.run_command("stamp", "--apply", "--journal", self.journal, "--batch", "1")
        self.assertEqual(len(open(self.journal).readlines()), 4)
        for i, tile in enumerate(tiles):
            self.assertIn("msUnit", self.props(tile, f"z{i}"))
        self.run_command(
            "unstamp", "--journal", self.journal, "--apply", "--batch", "1"
        )
        self.assertEqual(self.snapshot(), before)

    def test_a_provisional_line_is_restored(self):
        value = {str(self.annotation.pk): collection(zone("p1", canvas=READ_SERVICE))}
        self.tile(edits={"7": {"value": value}})
        before = self.snapshot()
        self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertNotEqual(self.snapshot(), before)
        self.run_command("unstamp", "--journal", self.journal, "--apply")
        self.assertEqual(self.snapshot(), before)

    def test_registered_manifests_are_loaded_once_per_run(self):
        for i in range(3):
            self.tile(
                self.legacy_zone(f"l{i}", 4000, 3000, SERVICE, URL),
                node=COMP_LOCATION_DOC_NODE,
            )
        self.tile(zone("u1"))
        self.tile(zone("u2", x=7.0))
        with mock.patch.object(
            frame_writes, "find_registered", wraps=frame_writes.find_registered
        ) as spy:
            self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(self.props(self.row_of("u1"), "u1")["msFrame"], "estimated")

    def legacy_zone(self, fid, width, height, canvas, manifest):
        feature = zone(fid, canvas=canvas, manifest=manifest)
        feature["geometry"] = rectangle(width, height)
        return feature

    def row_of(self, fid):
        return next(
            t
            for t in TileModel.objects.all()
            if any(
                f["id"] == fid
                for v in t.data.values()
                for f in (v or {}).get("features", [])
            )
        )


class UnstampGuardTests(AnnotationFramesCase):
    def test_a_zone_moved_and_restamped_with_the_same_frame_is_not_unstamped(self):
        tile = self.tile(zone("z1", canvas=READ_SERVICE))
        self.run_command("stamp", "--apply", "--journal", self.journal)
        row = self.row(tile)
        feature = row.data[str(self.annotation.pk)]["features"][0]
        feature["geometry"]["coordinates"][0][0][0] = 40.0
        TileModel.objects.filter(pk=tile.pk).update(data=row.data)
        stamped = self.snapshot()
        out = self.run_command("unstamp", "--journal", self.journal, "--apply")
        self.assertIn("changed since", out)
        self.assertEqual(self.snapshot(), stamped)


class LegacyRuleTests(AnnotationFramesCase):
    def legacy_zone(self, fid, width, height, canvas, manifest, x=0.0):
        feature = zone(fid, canvas=canvas, manifest=manifest)
        feature["geometry"] = rectangle(width, height)
        return feature

    def test_the_rectangle_is_legacy_next_to_a_user_zone_of_the_same_node(self):
        tile = self.tile(
            self.legacy_zone("w", 4000, 5000, LEGACY_SERVICE, "https://m.example/x"),
            zone("u", x=9.0, canvas=READ_SERVICE),
            node=COMP_LOCATION_DOC_NODE,
        )
        self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertEqual(
            self.props(tile, "w", COMP_LOCATION_DOC_NODE)["msFrame"], "import-legacy"
        )
        self.assertEqual(
            self.props(tile, "u", COMP_LOCATION_DOC_NODE)["msFrame"], "read"
        )

    def test_the_same_rectangle_on_another_node_is_not_legacy(self):
        tile = self.tile(
            self.legacy_zone("w", 4000, 5000, LEGACY_SERVICE, "https://m.example/x")
        )
        out = self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertNotIn("msUnit", self.props(tile, "w"))
        self.assertIn(LEGACY_SERVICE, out)

    def test_a_registered_size_no_frame_accepts_falls_back_to_the_default(self):
        big = "https://example.org/iiif/big/manifest"
        manifest = reg.v2_manifest(service=LEGACY_SERVICE)
        canvas = manifest["sequences"][0]["canvases"][0]
        canvas["width"], canvas["height"] = 2_000_000, 3000
        IIIFManifest.objects.create(url=big, label="Big", manifest=manifest)
        tile = self.tile(
            self.legacy_zone("w", 4000, 5000, LEGACY_SERVICE, big),
            node=COMP_LOCATION_DOC_NODE,
        )
        self.run_command("stamp", "--apply", "--journal", self.journal)
        props = self.props(tile, "w", COMP_LOCATION_DOC_NODE)
        self.assertEqual(
            (props["msFrame"], props["msImageWidth"], props["msImageHeight"]),
            ("import-legacy", 4000, 5000),
        )


class FullDiskTests(AnnotationFramesCase):
    def test_a_write_failing_after_a_first_batch_keeps_the_journal_readable(self):
        first = self.tile(zone("a", canvas=READ_SERVICE))
        second = self.tile(zone("b", x=5.0, canvas=READ_SERVICE))
        real = os.write
        seen = []

        def full(fd, data):
            if bytes(data).startswith(b'{"'):
                seen.append(1)
                if len(seen) == 2:
                    real(fd, bytes(data)[:10])
                    raise OSError(errno.ENOSPC, "No space left on device")
            return real(fd, data)

        with mock.patch(
            "manuspectrum.management.commands.annotation_frames.os.write", full
        ):
            with self.assertRaisesMessage(CommandError, "journal write failed"):
                self.run_command(
                    "stamp", "--apply", "--journal", self.journal, "--batch", "1"
                )
        lines = open(self.journal, "rb").read()
        self.assertTrue(lines.endswith(b"\n"))
        self.assertEqual(lines.count(b"\n"), 1)
        grouped = annotation_frames.read_journal(self.journal)
        self.assertEqual(sum(len(v) for v in grouped.values()), 1)
        stamped = [
            t for t in (first, second) if "msUnit" in next(iter(self._features(t)))
        ]
        self.assertEqual(len(stamped), 1)

    def _features(self, tile):
        return (
            f["properties"]
            for f in self.row(tile).data[str(self.annotation.pk)]["features"]
        )


class PlanningErrorTests(AnnotationFramesCase):
    def test_a_network_error_while_planning_is_not_a_journal_failure(self):
        self.tile(zone("a"))
        with mock.patch.object(
            frame_writes, "frame_for_service", side_effect=ConnectionError("down")
        ):
            with self.assertRaises(ConnectionError):
                self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertFalse(os.path.exists(self.journal))

    def test_a_journal_line_with_a_non_string_tile_is_refused_cleanly(self):
        good = {
            "tile": str(uuid.uuid4()),
            "node": "n",
            "provisional": None,
            "feature": "z",
            "canvas": "c",
            "digest": "d",
            "before": {},
            "after": {},
        }
        for tile in (3, [], {}, None):
            with open(self.journal, "w") as handle:
                handle.write(json.dumps({**good, "tile": tile}) + "\n")
            with self.subTest(tile=tile):
                with self.assertRaisesMessage(CommandError, "line 1"):
                    self.run_command("unstamp", "--journal", self.journal)


class LegacyFromImageTests(AnnotationFramesCase):
    def test_a_whole_page_rectangle_is_read_from_the_image_without_a_registered_row(
        self,
    ):
        feature = zone("w", canvas=READ_SERVICE, manifest="https://m.example/none")
        feature["geometry"] = rectangle(4913, 6609)
        tile = self.tile(feature, node=COMP_LOCATION_DOC_NODE)
        self.run_command("stamp", "--apply", "--journal", self.journal)
        props = self.props(tile, "w", COMP_LOCATION_DOC_NODE)
        self.assertEqual(
            (props["msUnit"], props["msImageWidth"], props["msFrame"]),
            (32, 4913, "import-legacy"),
        )


class JournalDurabilityTests(AnnotationFramesCase):
    def test_a_failure_after_a_commit_keeps_the_journal_of_the_committed_rows(self):
        tile = self.tile(zone("a", canvas=READ_SERVICE))
        before = self.snapshot()
        real = annotation_frames.apply_batch

        def committed_then_lost(batch, journal):
            real(batch, journal)
            raise RuntimeError("interrupted after the commit")

        with mock.patch.object(annotation_frames, "apply_batch", committed_then_lost):
            with self.assertRaises(RuntimeError):
                self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertIn("msUnit", self.props(tile, "a"))
        self.assertEqual(
            sum(len(v) for v in annotation_frames.read_journal(self.journal).values()),
            1,
        )
        self.run_command("unstamp", "--journal", self.journal, "--apply")
        self.assertEqual(self.snapshot(), before)

    def test_a_journal_directory_that_cannot_be_synced_fails_before_planning(self):
        self.tile(zone("a"))
        real = os.open

        def refuse_directories(path, flags, *args, **kwargs):
            if flags & os.O_DIRECTORY:
                raise OSError(errno.EACCES, "denied")
            return real(path, flags, *args, **kwargs)

        with mock.patch.object(
            frame_writes, "frame_for_service", wraps=frame_writes.frame_for_service
        ) as spy:
            with mock.patch(
                "manuspectrum.management.commands.annotation_frames.os.open",
                refuse_directories,
            ):
                with self.assertRaisesMessage(CommandError, "cannot create"):
                    self.run_command("stamp", "--apply", "--journal", self.journal)
        spy.assert_not_called()
        self.assertFalse(os.path.exists(self.journal))

    def test_a_write_that_accepts_no_byte_fails_instead_of_spinning(self):
        self.tile(zone("a", canvas=READ_SERVICE))
        before = self.snapshot()
        calls = []

        def stuck(fd, data):
            calls.append(1)
            if len(calls) > 5:
                raise AssertionError("the write loop spins")
            return 0

        with mock.patch(
            "manuspectrum.management.commands.annotation_frames.os.write", stuck
        ):
            with self.assertRaisesMessage(CommandError, "journal write failed"):
                self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertEqual(self.snapshot(), before)

    def test_a_short_write_is_completed(self):
        self.tile(zone("a", canvas=READ_SERVICE))
        real = os.write
        cut = []

        def short(fd, data):
            data = bytes(data)
            if data.startswith(b'{"') and not cut:
                cut.append(1)
                return real(fd, data[: len(data) // 2])
            return real(fd, data)

        with mock.patch(
            "manuspectrum.management.commands.annotation_frames.os.write", short
        ):
            self.run_command("stamp", "--apply", "--journal", self.journal)
        self.assertEqual(cut, [1])
        self.assertEqual(
            sum(len(v) for v in annotation_frames.read_journal(self.journal).values()),
            1,
        )

    def test_an_unterminated_last_segment_is_skipped_with_a_warning(self):
        self.tile(zone("a", canvas=READ_SERVICE))
        self.run_command("stamp", "--apply", "--journal", self.journal)
        with open(self.journal, "a") as handle:
            handle.write('{"tile": "')
        warnings = []
        grouped = annotation_frames.read_journal(self.journal, warnings.append)
        self.assertEqual(sum(len(v) for v in grouped.values()), 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn("line 2", warnings[0])
        out = self.run_command("unstamp", "--journal", self.journal)
        self.assertIn("1 of 1", out)
