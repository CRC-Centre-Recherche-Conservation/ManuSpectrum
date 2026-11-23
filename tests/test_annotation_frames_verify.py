"""Frames files and the stamped zones of the ``annotation_frames`` verbs.

Usage:
    python manage.py test tests.test_annotation_frames_verify --settings=tests.test_settings --noinput
"""

import json
import os
import tempfile
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from arches.app.models.models import TileModel

from manuspectrum.iiif import frame_scope, units
from manuspectrum.iiif.units import Frame, ImageInfo
from manuspectrum.management.commands import annotation_frames

from tests.test_annotation_frames_command import AnnotationFramesCase
from tests.test_zone_frame_writes import zone

GALLICA = "https://gallica.bnf.fr/iiif/ark:/12148/btv1b1/f1"


def frames_file(**overrides):
    body = {
        "version": 1,
        "measured_at": "2026-11-23T10:00:00Z",
        "origin": "https://viewer.example",
        "frames": [
            {
                "service": GALLICA + "/",
                "info": {"width": 3435, "height": 4905, "tile_width": 1024},
            }
        ],
        "failed": [["https://down.example/iiif/x", "network error"]],
    }
    body.update(overrides)
    return body


class FramesFileTests(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def write(self, content, mode="w"):
        path = os.path.join(self.dir.name, "frames.json")
        with open(path, mode) as handle:
            handle.write(content if mode == "w" else content)
        return path

    def read(self, body):
        return frame_scope.read_frames_file(self.write(json.dumps(body)))

    def test_a_valid_file_is_read_with_its_services_normalised(self):
        found = self.read(frames_file())
        self.assertEqual(found.frames, {GALLICA: ImageInfo(3435, 4905, 1024)})
        self.assertEqual(found.measured_at, "2026-11-23T10:00:00Z")
        self.assertEqual(found.origin, "https://viewer.example")
        self.assertEqual(
            found.failed, [("https://down.example/iiif/x", "network error")]
        )

    def test_an_entry_that_is_not_an_image_description_is_failed(self):
        found = self.read(
            frames_file(
                frames=[{"service": GALLICA, "info": {"width": 0, "height": 10}}]
            )
        )
        self.assertEqual(found.frames, {})
        self.assertEqual(found.failed[-1][0], GALLICA)
        self.assertTrue(found.failed[-1][1])

    def test_a_file_that_cannot_be_used_raises_with_the_reason(self):
        cases = {
            "version": json.dumps(frames_file(version=2)),
            "object": json.dumps([1]),
            "measured_at": json.dumps(
                {k: v for k, v in frames_file().items() if k != "measured_at"}
            ),
            "origin": json.dumps(
                {k: v for k, v in frames_file().items() if k != "origin"}
            ),
            "frames": json.dumps(frames_file(frames={})),
            "JSON": "not json",
        }
        for reason, text in cases.items():
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, reason):
                    frame_scope.read_frames_file(self.write(text))

    def test_invalid_utf8_and_a_missing_path_raise(self):
        path = os.path.join(self.dir.name, "bad.json")
        with open(path, "wb") as handle:
            handle.write(b"\xff\xfe{")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            frame_scope.read_frames_file(path)
        with self.assertRaises(ValueError):
            frame_scope.read_frames_file(os.path.join(self.dir.name, "none.json"))


class StampedZonesTests(AnnotationFramesCase):
    STAMP = Frame(16, 4913, 6609, "browser").stamp()

    def setUp(self):
        super().setUp()
        other = "https://other.example/iiif/z/page1"
        edit = {
            str(self.annotation.pk): {
                "type": "FeatureCollection",
                "features": [zone("p1", canvas=GALLICA, stamp=self.STAMP)],
            }
        }
        self.tile_ = self.tile(
            zone("s1", canvas=GALLICA, stamp=self.STAMP),
            zone("u1", canvas=GALLICA),
            zone("bad", canvas=GALLICA, stamp={**self.STAMP, "msUnit": 3}),
            zone("o1", canvas=other, stamp=self.STAMP),
            edits={"7": {"value": edit}},
        )
        self.nodes = annotation_frames.annotation_nodes()

    def zones(self, **kwargs):
        return list(annotation_frames.stamped_zones(self.nodes, **kwargs))

    def test_only_valid_stamps_are_yielded_with_their_user(self):
        found = {(z.feature_id, z.user_id) for z in self.zones(host="gallica.bnf.fr")}
        self.assertEqual(found, {("s1", None), ("p1", "7")})
        first = next(z for z in self.zones() if z.feature_id == "s1")
        self.assertEqual(first.tile_id, self.tile_.pk)
        self.assertEqual(first.node_id, str(self.annotation.pk))
        self.assertEqual(first.canvas, GALLICA)
        self.assertEqual(first.frame, Frame(16, 4913, 6609, "browser"))

    def test_service_and_host_filters(self):
        self.assertEqual(
            {z.feature_id for z in self.zones(service=GALLICA + "/")}, {"s1", "p1"}
        )
        self.assertEqual(
            {z.feature_id for z in self.zones(host="GALLICA.bnf.fr")}, {"s1", "p1"}
        )
        self.assertEqual(
            {z.feature_id for z in self.zones(host="other.example")}, {"o1"}
        )

    def test_tiles_limit_the_scan(self):
        self.assertEqual(self.zones(tiles=[]), [])


READ_A = "https://read.example/iiif/a"
READ_B = "https://read.example/iiif/b"
REFUSED_1 = "https://ref1.example/iiif/a"
REFUSED_2 = "https://ref2.example/iiif/b"
SIZE = (4913, 6609, 512)


def stamp_of(unit=16, source="read", size=SIZE):
    return Frame(unit, size[0], size[1], source).stamp()


def info_file(path, *entries, failed=None):
    body = frames_file(
        frames=[
            {
                "service": service,
                "info": {"width": w, "height": h, "tile_width": tile},
            }
            for service, (w, h, tile) in entries
        ],
        **({} if failed is None else {"failed": list(failed)}),
    )
    with open(path, "w") as handle:
        json.dump(body, handle)
    return path


class VerifyTests(AnnotationFramesCase):
    def setUp(self):
        super().setUp()
        self.answers = {}
        self.reads = []
        patcher = mock.patch(
            "manuspectrum.iiif.frame_writes.fresh_info", side_effect=self.read
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, service):
        self.reads.append(service)
        answer = self.answers.get(service, units.UNAVAILABLE)
        return answer(service) if callable(answer) else answer

    def info(self, size=SIZE):
        return ImageInfo(*size)

    def verify(self, *args):
        out = StringIO()
        error = None
        try:
            call_command(
                "annotation_frames", "verify", *args, stdout=out, stderr=StringIO()
            )
        except CommandError as caught:
            error = str(caught)
        return out.getvalue(), error

    def frames_path(self, *entries, **kwargs):
        return info_file(os.path.join(self.dir.name, "frames.json"), *entries, **kwargs)

    def test_one_service_same_one_different_prints_the_difference_and_fails(self):
        self.answers = {READ_A: self.info(), READ_B: self.info()}
        self.tile(
            *[zone(f"a{i}", canvas=READ_A, stamp=stamp_of()) for i in range(3)],
            *[zone(f"b{i}", canvas=READ_B, stamp=stamp_of(32)) for i in range(3)],
        )
        out, error = self.verify()
        self.assertEqual(sorted(self.reads), [READ_A, READ_B])
        self.assertIn(f"{READ_B}: 32x4913x6609 \u2192 16x4913x6609 (3 zone(s))", out)
        self.assertNotIn(f"{READ_A}:", out)
        self.assertIn("same: 1 service(s), 3 zone(s)", out)
        self.assertIn("different: 1 service(s), 3 zone(s)", out)
        self.assertIsNotNone(error)
        self.assertIn("differ", error)

    def test_everything_the_same_exits_cleanly(self):
        self.answers = {READ_A: self.info()}
        self.tile(zone("a", canvas=READ_A, stamp=stamp_of()))
        out, error = self.verify()
        self.assertIsNone(error)
        self.assertIn("same: 1 service(s), 1 zone(s)", out)

    def test_the_first_line_gives_the_unstamped_count(self):
        self.answers = {READ_A: self.info()}
        self.tile(zone("a", canvas=READ_A, stamp=stamp_of()), zone("n", canvas=READ_A))
        out, _error = self.verify()
        self.assertEqual(
            out.splitlines()[0], "Unstamped zones: 1; run stamp to stamp them"
        )

    def test_a_host_down_after_one_failed_read_is_not_a_pass(self):
        self.tile(
            zone("a", canvas=READ_A, stamp=stamp_of()),
            zone("b", canvas=READ_B, stamp=stamp_of()),
            zone("c", canvas="https://read.example/iiif/c", stamp=stamp_of()),
        )
        out, error = self.verify()
        self.assertIn("unreadable: 3 service(s), 3 zone(s)", out)
        self.assertIn("not verified", error)
        self.assertIn("run again", error)

    def test_a_refused_service_is_a_warning_not_a_failure(self):
        self.answers = {REFUSED_1: units.REFUSED}
        self.tile(zone("r", canvas=REFUSED_1, stamp=stamp_of(source="estimated")))
        out, error = self.verify()
        self.assertIsNone(error)
        self.assertIn(
            "refused or not an image description: 1 service(s), 1 zone(s)", out
        )
        self.assertIn("--refused-out", out)

    def test_a_frames_file_answers_for_a_refused_service(self):
        self.answers = {REFUSED_1: units.REFUSED}
        self.tile(zone("r", canvas=REFUSED_1, stamp=stamp_of(source="estimated")))
        out, error = self.verify("--frames", self.frames_path((REFUSED_1 + "/", SIZE)))
        self.assertIsNone(error)
        self.assertIn("same: 1 service(s), 1 zone(s)", out)
        self.assertIn("measured 2026-11-23T10:00:00Z from https://viewer.example", out)
        self.assertIn("tile width measured on ref1.example: 512", out)
        self.assertIn("https://down.example/iiif/x: network error", out)

    def test_a_frames_file_that_disagrees_with_a_readable_service_loses(self):
        self.answers = {READ_A: self.info()}
        self.tile(zone("a", canvas=READ_A, stamp=stamp_of()))
        out, error = self.verify(
            "--frames", self.frames_path((READ_A, (1000, 1000, 256)))
        )
        self.assertIsNone(error)
        self.assertIn("same: 1 service(s), 1 zone(s)", out)

    def test_an_unreadable_frames_file_is_an_error_before_any_read(self):
        path = os.path.join(self.dir.name, "bad.json")
        with open(path, "w") as handle:
            handle.write("nope")
        self.tile(zone("a", canvas=READ_A, stamp=stamp_of()))
        _out, error = self.verify("--frames", path)
        self.assertIn("bad.json", error)
        self.assertEqual(self.reads, [])

    def test_an_import_legacy_stamp_is_counted_apart_and_never_fails(self):
        self.answers = {READ_A: self.info()}
        self.tile(zone("l", canvas=READ_A, stamp=stamp_of(32, "import-legacy")))
        out, error = self.verify()
        self.assertIsNone(error)
        self.assertIn("import-legacy: 1 service(s), 1 zone(s)", out)
        self.assertNotIn("different", out)

    def test_refused_out_writes_one_script_per_refused_host(self):
        self.answers = {REFUSED_1: units.REFUSED, REFUSED_2: units.REFUSED}
        self.tile(
            zone("r1", canvas=REFUSED_1, stamp=stamp_of(source="estimated")),
            zone("r2", canvas=REFUSED_2, stamp=stamp_of(source="estimated")),
        )
        target = os.path.join(self.dir.name, "scripts")
        os.mkdir(target)
        out, error = self.verify("--refused-out", target)
        self.assertIsNone(error)
        self.assertEqual(
            sorted(os.listdir(target)), ["ref1.example.js", "ref2.example.js"]
        )
        for host, service in (("ref1.example", REFUSED_1), ("ref2.example", REFUSED_2)):
            with open(os.path.join(target, host + ".js")) as handle:
                script = handle.read()
            self.assertIn(f"const SERVICES = {json.dumps([service])};", script)
            self.assertNotIn("__SERVICES__", script)
            self.assertIn(f"https://{host}", out)
        self.assertIn("--frames", out)

    def test_refused_out_honours_host_and_never_overwrites(self):
        self.answers = {REFUSED_1: units.REFUSED, REFUSED_2: units.REFUSED}
        self.tile(
            zone("r1", canvas=REFUSED_1, stamp=stamp_of(source="estimated")),
            zone("r2", canvas=REFUSED_2, stamp=stamp_of(source="estimated")),
        )
        target = os.path.join(self.dir.name, "scripts")
        os.mkdir(target)
        self.verify("--refused-out", target, "--host", "ref2.example")
        self.assertEqual(os.listdir(target), ["ref2.example.js"])
        before = open(os.path.join(target, "ref2.example.js")).read()
        self.reads.clear()
        _out, error = self.verify("--refused-out", target)
        self.assertIn("ref2.example.js", error)
        self.assertEqual(self.reads, [])
        self.assertEqual(os.listdir(target), ["ref2.example.js"])
        self.assertEqual(open(os.path.join(target, "ref2.example.js")).read(), before)

    def requalify_tile(self, **kwargs):
        self.answers = {READ_A: self.info()}
        return self.tile(
            zone("e", canvas=READ_A, stamp=stamp_of(source="estimated"), note="x"),
            zone("m", canvas=READ_A, stamp=stamp_of()),
            **kwargs,
        )

    def test_apply_requalifies_an_estimate_equal_to_the_measure(self):
        tile = self.requalify_tile()
        before = self.row(tile).data
        out, error = self.verify("--apply", "--journal", self.journal)
        self.assertIsNone(error)
        after = self.row(tile).data
        node = str(self.annotation.pk)
        self.assertEqual(self.props(tile, "e")["msFrame"], "read")
        expected = json.loads(json.dumps(before))
        expected[node]["features"][0]["properties"]["msFrame"] = "read"
        self.assertEqual(after, expected)
        self.assertIn("1 zone(s) requalified", out)
        self.assertIn("es reindex_database", out)
        with open(self.journal) as handle:
            lines = [json.loads(line) for line in handle]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["feature"], "e")
        self.assertEqual(lines[0]["before"]["msFrame"], "estimated")
        self.assertEqual(lines[0]["after"], {**lines[0]["before"], "msFrame": "read"})
        self.assertEqual(lines[0]["canvas"], READ_A)

    def test_apply_uses_the_browser_source_of_a_frames_file(self):
        self.answers = {REFUSED_1: units.REFUSED}
        tile = self.tile(
            zone("e", canvas=REFUSED_1, stamp=stamp_of(source="estimated"))
        )
        self.verify(
            "--apply",
            "--journal",
            self.journal,
            "--frames",
            self.frames_path((REFUSED_1, SIZE)),
        )
        self.assertEqual(self.props(tile, "e")["msFrame"], "browser")

    def test_apply_leaves_measured_and_different_estimates_alone(self):
        self.answers = {READ_A: self.info(), READ_B: self.info()}
        tile = self.tile(
            zone("m", canvas=READ_A, stamp=stamp_of()),
            zone("d", canvas=READ_B, stamp=stamp_of(32, "estimated")),
        )
        before = self.snapshot()
        out, error = self.verify("--apply", "--journal", self.journal)
        self.assertIn("differ", error)
        self.assertEqual(self.snapshot(), before)
        self.assertIn(f"{READ_B}: 32x4913x6609 \u2192 16x4913x6609", out)
        self.assertFalse(os.path.exists(self.journal))
        self.assertEqual(self.props(tile, "d")["msFrame"], "estimated")

    def test_unstamp_gives_the_tile_back_value_for_value(self):
        tile = self.requalify_tile()
        before = self.row(tile).data
        self.verify("--apply", "--journal", self.journal)
        self.assertNotEqual(self.row(tile).data, before)
        self.run_command("unstamp", "--journal", self.journal, "--apply")
        self.assertEqual(self.row(tile).data, before)

    def test_a_provisional_edit_zone_is_requalified_in_provisionaledits_only(self):
        self.answers = {READ_A: self.info()}
        edit = {
            str(self.annotation.pk): {
                "type": "FeatureCollection",
                "features": [
                    zone("p", canvas=READ_A, stamp=stamp_of(source="estimated"))
                ],
            }
        }
        tile = self.tile(
            zone("m", canvas=READ_A, stamp=stamp_of()), edits={"7": {"value": edit}}
        )
        data = self.row(tile).data
        self.verify("--apply", "--journal", self.journal)
        row = self.row(tile)
        self.assertEqual(row.data, data)
        features = row.provisionaledits["7"]["value"][str(self.annotation.pk)][
            "features"
        ]
        self.assertEqual(features[0]["properties"]["msFrame"], "read")
        with open(self.journal) as handle:
            self.assertEqual(json.loads(handle.readline())["provisional"], "7")

    def test_a_stamp_changed_between_plan_and_batch_is_listed(self):
        tile = self.requalify_tile()
        node = str(self.annotation.pk)

        def change(service):
            data = self.row(tile).data
            data[node]["features"][0]["properties"]["msUnit"] = 8
            TileModel.objects.filter(pk=tile.pk).update(data=data)
            return self.info()

        self.answers = {READ_A: change}
        out, _error = self.verify("--apply", "--journal", self.journal)
        self.assertIn(f"changed since: zone e of tile {tile.pk}", out)
        self.assertEqual(self.props(tile, "e")["msFrame"], "estimated")
        self.assertEqual(self.props(tile, "e")["msUnit"], 8)

    def test_apply_needs_a_journal_and_a_dry_run_writes_nothing(self):
        tile = self.requalify_tile()
        before = self.snapshot()
        _out, error = self.verify("--apply")
        self.assertIn("--journal", error)
        self.assertEqual(self.reads, [])
        out, error = self.verify()
        self.assertIsNone(error)
        self.assertIn("1 estimated zone(s) would be requalified", out)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.props(tile, "e")["msFrame"], "estimated")
