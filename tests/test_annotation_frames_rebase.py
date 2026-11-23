"""The ``annotation_frames rebase`` verb: factors, scaled geometry and the guarded batches.

Usage:
    python manage.py test tests.test_annotation_frames_rebase --settings=tests.test_settings --noinput
"""

import copy
import errno
import json
import os
import uuid
from datetime import datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from arches.app.models.models import EditLog, TileModel
from arches.app.models.tile import Tile

from manuspectrum.iiif import frame_scope, frames, units
from manuspectrum.iiif.units import Frame, ImageInfo
from manuspectrum.management.commands import annotation_frames
from manuspectrum.views.explorer.values import _pixel

from tests.test_annotation_frames_command import AnnotationFramesCase
from tests.test_zone_frame_writes import collection, remember_info, zone

SVC = "https://rb.example/iiif/a"
SVC_B = "https://rb.example/iiif/b"
REFUSED = "https://rb-refused.example/iiif/a"
SIZE = (4913, 6609)


def point(fid, pixel, unit, canvas=SVC, stamp=None):
    """A Point zone drawn at image *pixel* in a frame of *unit* pixels per stored unit."""
    feature = zone(fid, canvas=canvas, stamp=stamp)
    feature["geometry"] = {
        "type": "Point",
        "coordinates": [pixel[0] / unit, -pixel[1] / unit],
    }
    return feature


def live(unit, size=SIZE):
    """The image description whose leaflet-iiif unit is *unit*: the tile width that gives it."""
    for tile in (2**n for n in range(4, 14)):
        info = ImageInfo(size[0], size[1], tile)
        if units.frame_from_info(info).unit == unit:
            return info
    raise AssertionError(unit)


def read_pixel(feature, canvas_size):
    """The canvas pixel the project read gives *feature*: stamp -> ``unit_of_frame`` -> ``_pixel``."""
    unit = units.unit_of_frame(frames.frame_of(feature), *canvas_size)
    return _pixel(feature["geometry"]["coordinates"], *canvas_size, (unit.x, unit.y))


class RebaseFactorTests(SimpleTestCase):
    def test_same_size_gives_the_ratio_of_the_units(self):
        old, new = Frame(32, 100, 200, "read"), Frame(16, 100, 200, "browser")
        self.assertEqual(frame_scope.rebase_factors(old, new, False), (2.0, 2.0))
        self.assertEqual(frame_scope.rebase_factors(new, old, False), (0.5, 0.5))

    def test_another_size_needs_resize_and_the_same_aspect(self):
        old, new = Frame(16, 3435, 4905, "read"), Frame(64, 6870, 9810, "read")
        self.assertIsNone(frame_scope.rebase_factors(old, new, False))
        self.assertEqual(frame_scope.rebase_factors(old, new, True), (0.5, 0.5))

    def test_the_two_axes_can_differ_within_one_pixel_of_aspect(self):
        old, new = Frame(16, 1000, 1000, "read"), Frame(16, 2000, 2001, "read")
        fx, fy = frame_scope.rebase_factors(old, new, True)
        self.assertEqual((fx, fy), (2.0, 2.001))

    def test_another_aspect_is_refused_even_with_resize(self):
        old, new = Frame(16, 3435, 4905, "read"), Frame(16, 3435, 4000, "read")
        self.assertIsNone(frame_scope.rebase_factors(old, new, True))


class ScaledGeometryTests(SimpleTestCase):
    def test_every_position_of_every_type_is_scaled_and_rounded(self):
        cases = {
            "Point": ([1.0, -2.0], [2.0, -4.0]),
            "LineString": ([[1.0, -1.0], [3.0, -2.0]], [[2.0, -2.0], [6.0, -4.0]]),
            "Polygon": ([[[1.0, -1.0], [3.0, -2.0]]], [[[2.0, -2.0], [6.0, -4.0]]]),
            "MultiPoint": ([[1.0, -1.0]], [[2.0, -2.0]]),
            "MultiLineString": ([[[1.0, -1.0]]], [[[2.0, -2.0]]]),
            "MultiPolygon": ([[[[1.0, -1.0]]]], [[[[2.0, -2.0]]]]),
        }
        for kind, (before, after) in cases.items():
            with self.subTest(kind=kind):
                got = frame_scope.scaled_geometry(
                    {"type": kind, "coordinates": before}, 2.0, 2.0
                )
                self.assertEqual(got, {"type": kind, "coordinates": after})

    def test_the_result_is_rounded_as_leaflet_does_and_the_input_is_kept(self):
        geometry = {"type": "Point", "coordinates": [1001 / 64, -1001 / 64]}
        got = frame_scope.scaled_geometry(geometry, 0.5, 0.5)
        self.assertEqual(got["coordinates"], [7.820313, -7.820312])
        self.assertEqual(geometry["coordinates"], [1001 / 64, -1001 / 64])

    def test_each_axis_has_its_own_factor(self):
        got = frame_scope.scaled_geometry(
            {"type": "Point", "coordinates": [2.0, -2.0]}, 3.0, 0.5
        )
        self.assertEqual(got["coordinates"], [6.0, -1.0])

    def test_another_type_or_a_refused_value_raises(self):
        for geometry in (
            {"type": "GeometryCollection", "geometries": []},
            {"type": "Point", "coordinates": [float("nan"), 1.0]},
            {"type": "Point", "coordinates": [True, 1.0]},
            {"type": "Point", "coordinates": [1.0]},
            {"type": "Polygon", "coordinates": "x"},
            None,
        ):
            with self.subTest(geometry=geometry):
                with self.assertRaises(ValueError):
                    frame_scope.scaled_geometry(geometry, 2.0, 2.0)


class RebaseCase(AnnotationFramesCase):
    def setUp(self):
        super().setUp()
        self.answers = {}
        self.reads = []
        patcher = mock.patch(
            "manuspectrum.iiif.frame_writes.fresh_info", side_effect=self.fresh
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def fresh(self, service):
        self.reads.append(service)
        answer = self.answers.get(service, units.UNAVAILABLE)
        return answer(service) if callable(answer) else answer

    def rebase(self, *args, scoped=True):
        if scoped and not {"--service", "--host"} & set(args):
            args = ("--host", "rb.example", *args)
        out = StringIO()
        error = None
        try:
            call_command(
                "annotation_frames", "rebase", *args, stdout=out, stderr=StringIO()
            )
        except CommandError as caught:
            error = str(caught)
        return out.getvalue(), error

    def apply(self, *args, **kwargs):
        return self.rebase("--apply", "--journal", self.journal, *args, **kwargs)

    def feature(self, tile, fid):
        data = self.row(tile).data[str(self.annotation.pk)]
        return next(f for f in data["features"] if f["id"] == fid)

    def journal_lines(self):
        with open(self.journal) as handle:
            return [json.loads(line) for line in handle]


class RebaseReadTests(RebaseCase):
    """What the project reads, through the real stamp -> unit -> pixel path."""

    def moved(self, old_unit, live_unit, pixel, size=SIZE):
        self.answers = {SVC: live(live_unit, size)}
        stamp = Frame(old_unit, *size, "read").stamp()
        tile = self.tile(point("z", pixel, old_unit, stamp=stamp))
        before = copy.deepcopy(self.feature(tile, "z"))
        _out, error = self.apply()
        self.assertIsNone(error)
        return before, self.feature(tile, "z")

    def test_a_shrinking_unit_multiplies_and_reads_the_same_pixel(self):
        before, after = self.moved(32, 16, (1000, 2000))
        self.assertEqual(before["geometry"]["coordinates"], [31.25, -62.5])
        self.assertEqual(after["geometry"]["coordinates"], [62.5, -125.0])
        self.assertEqual(read_pixel(before, SIZE), (1000, 2000))
        self.assertEqual(read_pixel(after, SIZE), (1000, 2000))
        self.assertEqual(
            {k: v for k, v in after["properties"].items() if k.startswith("ms")},
            Frame(16, *SIZE, "read").stamp(),
        )

    def test_a_growing_unit_divides_and_keeps_the_pixel(self):
        before, after = self.moved(32, 64, (1000, 2000))
        self.assertEqual(after["geometry"]["coordinates"], [15.625, -31.25])
        self.assertEqual(read_pixel(after, SIZE), read_pixel(before, SIZE))

    def test_a_negative_tie_moves_the_read_by_at_most_one_pixel(self):
        before, after = self.moved(64, 128, (1000, 1001))
        self.assertEqual(before["geometry"]["coordinates"][1], -1001 / 64)
        self.assertEqual(after["geometry"]["coordinates"][1], -7.820312)
        moved = [
            abs(a - b)
            for a, b in zip(read_pixel(after, SIZE), read_pixel(before, SIZE))
        ]
        self.assertEqual(read_pixel(before, SIZE), (1000, 1001))
        self.assertEqual(read_pixel(after, SIZE), (1000, 1000))
        self.assertLessEqual(max(moved), 1)

    def resize_case(self):
        old = (3435, 4905)
        new = (6870, 9810)
        self.answers = {SVC: ImageInfo(*new, 256)}
        stamp = Frame(16, *old, "read").stamp()
        tile = self.tile(point("z", (1000, 2000), 16, stamp=stamp))
        return tile, new

    def test_a_resize_needs_the_flag_and_lands_within_one_pixel(self):
        tile, new = self.resize_case()
        before = copy.deepcopy(self.feature(tile, "z"))
        out, _error = self.apply()
        self.assertIn(
            f"size changed, same aspect: give --resize: zone z of tile {tile.pk}", out
        )
        self.assertEqual(self.feature(tile, "z"), before)
        self.assertFalse(os.path.exists(self.journal))
        out, error = self.apply("--resize")
        self.assertIsNone(error)
        after = self.feature(tile, "z")
        self.assertEqual(after["geometry"]["coordinates"], [31.25, -62.5])
        for a, b in zip(read_pixel(after, new), read_pixel(before, new)):
            self.assertLessEqual(abs(a - b), 1)
        self.assertEqual(
            {k: v for k, v in after["properties"].items() if k.startswith("ms")},
            Frame(64, *new, "read").stamp(),
        )

    def test_another_aspect_is_listed_even_with_resize(self):
        self.answers = {SVC: ImageInfo(3435, 4000, 256)}
        stamp = Frame(16, 3435, 4905, "read").stamp()
        tile = self.tile(point("z", (10, 10), 16, stamp=stamp))
        before = copy.deepcopy(self.feature(tile, "z"))
        out, _error = self.apply("--resize")
        self.assertIn(f"size changed: redraw: zone z of tile {tile.pk}", out)
        self.assertNotIn("give --resize", out)
        self.assertEqual(self.feature(tile, "z"), before)

    def test_another_aspect_without_resize_says_redraw(self):
        self.answers = {SVC: ImageInfo(3435, 4000, 256)}
        stamp = Frame(16, 3435, 4905, "read").stamp()
        tile = self.tile(point("z", (10, 10), 16, stamp=stamp))
        out, _error = self.apply()
        self.assertIn(f"size changed: redraw: zone z of tile {tile.pk}", out)


class RebaseSelectionTests(RebaseCase):
    def stamp(self, unit, source="read"):
        return Frame(unit, *SIZE, source).stamp()

    def test_only_the_zones_off_the_target_move(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(
            point("old", (320, 640), 32, stamp=self.stamp(32)),
            point("ok", (320, 640), 16, stamp=self.stamp(16)),
        )
        ok = copy.deepcopy(self.feature(tile, "ok"))
        out, error = self.apply()
        self.assertIsNone(error)
        self.assertEqual(self.feature(tile, "ok"), ok)
        self.assertEqual(
            self.feature(tile, "old")["geometry"]["coordinates"], [20.0, -40.0]
        )
        self.assertIn("rebased: 1 zone(s)", out)
        self.assertIn("unchanged: 1 zone(s)", out)
        self.assertIn("es reindex_database", out)
        self.assertIn("Run with editing closed", out)
        self.assertEqual(len(self.journal_lines()), 1)

    def test_an_estimated_zone_without_since_is_left_and_listed(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point("e", (320, 640), 32, stamp=self.stamp(32, "estimated")))
        before = copy.deepcopy(self.feature(tile, "e"))
        out, _error = self.apply()
        self.assertEqual(self.feature(tile, "e"), before)
        self.assertIn(f"estimated: give --since: zone e of tile {tile.pk}", out)

    def test_a_refused_service_plans_nothing(self):
        self.answers = {REFUSED: units.REFUSED}
        self.tile(point("r", (1, 1), 32, canvas=REFUSED, stamp=self.stamp(32)))
        before = self.snapshot()
        out, error = self.apply("--host", "rb-refused.example")
        self.assertIsNone(error)
        self.assertEqual(self.snapshot(), before)
        self.assertIn(f"{REFUSED}: refused or not an image description", out)
        self.assertFalse(os.path.exists(self.journal))

    def test_an_unreadable_service_plans_nothing_and_fails(self):
        self.tile(point("u", (1, 1), 32, stamp=self.stamp(32)))
        before = self.snapshot()
        out, error = self.apply()
        self.assertEqual(self.snapshot(), before)
        self.assertIn(f"{SVC}: unreadable", out)
        self.assertIn("not measured", error)
        self.assertFalse(os.path.exists(self.journal))

    def test_a_frames_file_measures_a_refused_service(self):
        self.answers = {REFUSED: units.REFUSED}
        path = os.path.join(self.dir.name, "frames.json")
        with open(path, "w") as handle:
            json.dump(
                {
                    "version": 1,
                    "measured_at": "2026-11-23T10:00:00Z",
                    "origin": "https://viewer.example",
                    "frames": [
                        {
                            "service": REFUSED,
                            "info": {
                                "width": SIZE[0],
                                "height": SIZE[1],
                                "tile_width": 512,
                            },
                        }
                    ],
                    "failed": [],
                },
                handle,
            )
        tile = self.tile(
            point("r", (320, 640), 32, canvas=REFUSED, stamp=self.stamp(32))
        )
        self.apply("--frames", path, "--host", "rb-refused.example")
        found = self.feature(tile, "r")
        self.assertEqual(found["properties"]["msFrame"], "browser")
        self.assertEqual(found["properties"]["msUnit"], 16)

    def test_an_invalid_geometry_is_listed_and_left(self):
        self.answers = {SVC: live(16)}
        bad = point("bad", (320, 640), 32, stamp=self.stamp(32))
        bad["geometry"]["type"] = "GeometryCollection"
        tile = self.tile(bad)
        out, _error = self.apply()
        self.assertIn(f"invalid geometry: zone bad of tile {tile.pk}", out)
        self.assertEqual(self.feature(tile, "bad"), bad)

    def test_the_dry_run_writes_nothing_and_says_what_would_move(self):
        self.answers = {SVC: live(16)}
        self.tile(point("old", (320, 640), 32, stamp=self.stamp(32)))
        before = self.snapshot()
        out, error = self.rebase()
        self.assertIsNone(error)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("would be rebased: 1 zone(s)", out)
        self.assertIn("dry run", out)
        self.assertFalse(os.path.exists(self.journal))

    def test_a_service_is_read_once(self):
        self.answers = {SVC: live(16)}
        self.tile(
            point("a", (1, 1), 32, stamp=self.stamp(32)),
            point("b", (1, 1), 32, stamp=self.stamp(32)),
        )
        self.rebase()
        self.assertEqual(self.reads, [SVC])

    def test_service_and_host_filters(self):
        self.answers = {SVC: live(16), SVC_B: live(16)}
        tile = self.tile(
            point("a", (320, 640), 32, stamp=self.stamp(32)),
            point("b", (320, 640), 32, canvas=SVC_B, stamp=self.stamp(32)),
        )
        self.apply("--service", SVC_B + "/")
        self.assertEqual(self.feature(tile, "a")["properties"]["msUnit"], 32)
        self.assertEqual(self.feature(tile, "b")["properties"]["msUnit"], 16)

    def test_the_arguments_are_checked(self):
        _out, error = self.rebase(scoped=False)
        self.assertIn("--service or --host", error)
        _out, error = self.rebase("--service", SVC, "--apply")
        self.assertIn("--journal", error)
        _out, error = self.rebase("--service", SVC, "--since", "yesterday")
        self.assertIn("--since", error)


class RebaseSinceTests(RebaseCase):
    SINCE = "2026-11-10"

    def setUp(self):
        super().setUp()
        self.answers = {SVC: live(16)}
        self.stamp = Frame(32, *SIZE, "estimated").stamp()
        self.node = str(self.annotation.pk)

    def log(self, tile, old, when=datetime(2026, 11, 15, 9, 0), **extra):
        EditLog.objects.create(
            tileinstanceid=str(tile.pk),
            timestamp=when,
            edittype="tile edit",
            oldvalue=old,
            **extra,
        )

    def test_a_zone_present_unchanged_before_the_date_is_rebased(self):
        old = point("old", (320, 640), 32, stamp=self.stamp)
        tile = self.tile(old)
        self.log(tile, {self.node: collection(old)})
        out, _error = self.apply("--since", self.SINCE)
        self.assertEqual(
            self.feature(tile, "old")["geometry"]["coordinates"], [20.0, -40.0]
        )

    def test_a_zone_added_after_the_date_is_listed_and_untouched(self):
        old = point("old", (320, 640), 32, stamp=self.stamp)
        new = point("new", (320, 640), 16, stamp=self.stamp)
        tile = self.tile(old, new)
        self.log(tile, {self.node: collection(old)})
        before_new = copy.deepcopy(self.feature(tile, "new"))
        out, _error = self.apply("--since", self.SINCE)
        self.assertEqual(
            self.feature(tile, "old")["geometry"]["coordinates"], [20.0, -40.0]
        )
        self.assertEqual(self.feature(tile, "new"), before_new)
        self.assertIn(
            f"drawn or moved since {self.SINCE}: review in the editor \u2014 looks moved: "
            f"rebase --zone; looks right: relabel: zone new of tile {tile.pk}",
            out,
        )
        self.assertNotIn("zone old of tile", out)

    def test_a_zone_moved_after_the_date_is_listed(self):
        before_move = point("z", (320, 640), 32, stamp=self.stamp)
        moved = point("z", (640, 640), 32, stamp=self.stamp)
        tile = self.tile(moved)
        self.log(tile, {self.node: collection(before_move)})
        out, _error = self.apply("--since", self.SINCE)
        self.assertEqual(self.feature(tile, "z"), moved)
        self.assertIn("drawn or moved since", out)

    def test_the_earliest_row_after_the_date_gives_the_value_before_it(self):
        old = point("z", (320, 640), 32, stamp=self.stamp)
        later = point("z", (640, 640), 32, stamp=self.stamp)
        tile = self.tile(old)
        self.log(tile, {self.node: collection(later)}, when=datetime(2026, 11, 20))
        self.log(tile, {self.node: collection(old)}, when=datetime(2026, 11, 12))
        self.log(tile, {self.node: collection()}, when=datetime(2026, 11, 1))
        self.apply("--since", self.SINCE)
        self.assertEqual(
            self.feature(tile, "z")["geometry"]["coordinates"], [20.0, -40.0]
        )

    def test_the_date_is_that_day_at_midnight_local(self):
        eve = self.tile(point("eve", (320, 640), 32, stamp=self.stamp))
        midnight = self.tile(point("mid", (320, 640), 32, stamp=self.stamp))
        self.log(eve, {self.node: collection()}, when=datetime(2026, 11, 9, 23, 59))
        self.log(midnight, {self.node: collection()}, when=datetime(2026, 11, 10, 0, 0))
        out, _error = self.apply("--since", self.SINCE)
        self.assertEqual(
            self.feature(eve, "eve")["geometry"]["coordinates"], [20.0, -40.0]
        )
        self.assertEqual(
            self.feature(midnight, "mid")["geometry"]["coordinates"], [10.0, -20.0]
        )
        self.assertIn(f"zone mid of tile {midnight.pk}", out)

    def test_a_tile_without_a_row_after_the_date_is_all_old(self):
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp))
        self.log(tile, {self.node: collection()}, when=datetime(2026, 11, 1))
        self.apply("--since", self.SINCE)
        self.assertEqual(
            self.feature(tile, "z")["geometry"]["coordinates"], [20.0, -40.0]
        )

    def test_a_tile_created_after_the_date_is_listed(self):
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp))
        self.log(tile, {})
        out, _error = self.apply("--since", self.SINCE)
        self.assertIn("drawn or moved since", out)

    def test_a_measured_zone_goes_through_the_same_check_with_since(self):
        measured = Frame(32, *SIZE, "read").stamp()
        zone_ = point("z", (320, 640), 32, stamp=measured)
        tile = self.tile(zone_)
        self.log(tile, {self.node: collection()})
        out, _error = self.apply("--since", self.SINCE)
        self.assertIn("drawn or moved since", out)

    def test_a_provisional_zone_reads_the_old_provisional_value(self):
        old = point("p", (320, 640), 32, stamp=self.stamp)
        new = point("q", (320, 640), 32, stamp=self.stamp)
        edit = {self.node: collection(old, new)}
        tile = self.tile(edits={"7": {"value": edit}}, node=None)
        self.log(
            tile,
            {},
            oldprovisionalvalue={self.node: collection(old)},
            provisional_userid="7",
        )
        out, _error = self.apply("--since", self.SINCE)
        value = self.row(tile).provisionaledits["7"]["value"][self.node]["features"]
        by_id = {f["id"]: f for f in value}
        self.assertEqual(by_id["p"]["geometry"]["coordinates"], [20.0, -40.0])
        self.assertEqual(by_id["q"]["geometry"], new["geometry"])
        self.assertIn(f"zone q of tile {tile.pk}", out)

    def test_one_query_serves_the_whole_scope(self):
        for i in range(3):
            tile = self.tile(point(f"z{i}", (32, 32), 32, stamp=self.stamp))
            self.log(tile, {self.node: collection()})
        with mock.patch.object(
            EditLog.objects, "filter", wraps=EditLog.objects.filter
        ) as filtered:
            self.rebase("--since", self.SINCE)
        self.assertEqual(filtered.call_count, 1)

    def create_row(self, tile, when=datetime(2026, 11, 15, 9, 0)):
        EditLog.objects.create(
            resourceinstanceid=str(tile.resourceinstance_id),
            timestamp=when,
            edittype="create",
        )

    def test_a_tile_of_a_resource_created_since_has_no_old_zone(self):
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp))
        self.create_row(tile)
        before = copy.deepcopy(self.feature(tile, "z"))
        out, _error = self.apply("--since", self.SINCE)
        self.assertEqual(self.feature(tile, "z"), before)
        self.assertIn(f"drawn or moved since {self.SINCE}", out)
        self.assertIn(f"zone z of tile {tile.pk}", out)

    def test_a_tile_of_a_resource_created_before_the_date_is_rebased(self):
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp))
        self.create_row(tile, datetime(2026, 11, 1))
        self.apply("--since", self.SINCE)
        self.assertEqual(
            self.feature(tile, "z")["geometry"]["coordinates"], [20.0, -40.0]
        )

    def test_the_creation_of_a_resource_since_wins_over_a_row_of_its_tile(self):
        old = point("old", (320, 640), 32, stamp=self.stamp)
        tile = self.tile(old)
        self.create_row(tile)
        self.log(tile, {self.node: collection(old)})
        before = copy.deepcopy(self.feature(tile, "old"))
        out, _error = self.apply("--since", self.SINCE)
        self.assertEqual(self.feature(tile, "old"), before)
        self.assertIn(f"drawn or moved since {self.SINCE}", out)

    def test_a_provisional_zone_of_a_resource_created_since_is_listed(self):
        node = self.node
        edit = {node: collection(point("p", (320, 640), 32, stamp=self.stamp))}
        tile = self.tile(edits={"7": {"value": edit}}, node=None)
        self.create_row(tile)
        out, _error = self.apply("--since", self.SINCE)
        value = self.row(tile).provisionaledits["7"]["value"][node]["features"]
        self.assertEqual(value[0]["geometry"]["coordinates"], [10.0, -20.0])
        self.assertIn(f"zone p of tile {tile.pk}", out)

    def test_a_row_is_read_once_per_tile_and_user(self):
        tile = self.tile(point("z", (32, 32), 32, stamp=self.stamp))
        for day in (12, 13, 14):
            self.log(tile, {self.node: collection()}, when=datetime(2026, 11, day))
        original = annotation_frames._zone_keys
        with mock.patch.object(
            annotation_frames, original.__name__, wraps=original
        ) as keys:
            annotation_frames.values_before([tile.pk], datetime(2026, 11, 10))
        self.assertEqual(keys.call_count, 1)


class RebaseWriteTests(RebaseCase):
    def stamp(self, unit=32):
        return Frame(unit, *SIZE, "read").stamp()

    def test_a_geometry_changed_between_plan_and_write_is_listed_and_untouched(self):
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp()))
        node = str(self.annotation.pk)

        def change(service):
            data = self.row(tile).data
            data[node]["features"][0]["geometry"]["coordinates"] = [5.0, -5.0]
            TileModel.objects.filter(pk=tile.pk).update(data=data)
            return live(16)

        self.answers = {SVC: change}
        out, _error = self.apply()
        self.assertEqual(
            self.feature(tile, "z")["geometry"]["coordinates"], [5.0, -5.0]
        )
        self.assertEqual(self.feature(tile, "z")["properties"]["msUnit"], 32)
        self.assertIn(f"changed since: zone z of tile {tile.pk}", out)
        self.assertFalse(os.path.exists(self.journal))

    def test_a_provisional_zone_is_rebased_in_provisionaledits_only(self):
        self.answers = {SVC: live(16)}
        node = str(self.annotation.pk)
        edit = {node: collection(point("p", (320, 640), 32, stamp=self.stamp()))}
        tile = self.tile(
            point("d", (320, 640), 32, stamp=self.stamp(16)),
            edits={"7": {"value": edit}},
        )
        data = self.row(tile).data
        self.apply()
        row = self.row(tile)
        self.assertEqual(row.data, data)
        feature = row.provisionaledits["7"]["value"][node]["features"][0]
        self.assertEqual(feature["geometry"]["coordinates"], [20.0, -40.0])
        self.assertEqual(self.journal_lines()[0]["provisional"], "7")

    def test_the_journal_line_carries_the_new_digest_and_the_old_geometry(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp()))
        original = copy.deepcopy(self.feature(tile, "z"))
        self.apply()
        (line,) = self.journal_lines()
        after = self.feature(tile, "z")
        self.assertEqual(line["digest"], frames.geometry_digest(after["geometry"]))
        self.assertEqual(line["geometry_before"], original["geometry"])
        self.assertEqual(line["before"], original["properties"])
        self.assertEqual(line["after"], after["properties"])
        self.assertEqual(line["canvas"], SVC)

    def test_unstamp_gives_data_and_provisionaledits_back_value_for_value(self):
        self.answers = {SVC: live(16)}
        node = str(self.annotation.pk)
        edit = {node: collection(point("p", (320, 640), 32, stamp=self.stamp()))}
        self.tile(
            point("d", (320, 640), 32, stamp=self.stamp()),
            edits={"7": {"value": edit}},
        )
        before = self.snapshot()
        self.apply()
        self.assertNotEqual(self.snapshot(), before)
        self.run_command("unstamp", "--journal", self.journal, "--apply")
        self.assertEqual(self.snapshot(), before)

    def stale_save(self, tile, *stale):
        """Save *tile* through ``Tile.save`` with the features *stale* (the geometry of a tab opened before the rebase)."""
        row = Tile.objects.get(pk=tile.pk)
        node = str(self.annotation.pk)
        row.data = {node: collection(*stale), str(self.other.pk): None}
        row.serialized_graph = {
            "nodes": [
                {"nodeid": node, "datatype": "annotation"},
                {
                    "nodeid": str(self.other.pk),
                    "datatype": "geojson-feature-collection",
                },
            ],
            "cards": [],
            "widgets": [],
        }
        self.fetch.side_effect = AssertionError("no request expected")
        remember_info(SVC, (*SIZE, 512))
        guard = mock.patch(
            "manuspectrum.iiif.frames.current_request", return_value=object()
        )
        with guard, self.captureOnCommitCallbacks(execute=True):
            row.save(index=False)

    def reverted_zone(self):
        """A zone rebased from unit 32 to 16 and then saved with its old geometry by a stale tab; returns ``(tile, stale feature)``."""
        self.answers = {SVC: live(16)}
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp()))
        stale = copy.deepcopy(self.feature(tile, "z"))
        stale["properties"]["note"] = "edited in a stale tab"
        self.apply()
        self.stale_save(tile, stale)
        return tile, stale

    @override_settings(IIIF_IMAGE_INFO_READ=True)
    def test_a_stale_editor_save_after_the_rebase_is_named_by_a_dry_unstamp(self):
        tile, stale = self.reverted_zone()
        saved = self.feature(tile, "z")
        self.assertEqual(saved["geometry"], stale["geometry"])
        self.assertEqual(saved["properties"]["msUnit"], 16)
        self.assertNotEqual(saved["properties"], self.journal_lines()[0]["after"])
        before = self.snapshot()
        out = self.run_command("unstamp", "--journal", self.journal)
        self.assertIn(
            f"geometry reverted by a later save: zone z of tile {tile.pk}", out
        )
        self.assertNotIn("changed since", out)
        self.assertIn("--zone TILE:FEATURE --apply (puts the old stamp back", out)
        self.assertEqual(self.snapshot(), before)

    @override_settings(IIIF_IMAGE_INFO_READ=True)
    def test_unstamp_apply_puts_the_old_stamp_back_and_a_second_rebase_moves_it(self):
        tile, stale = self.reverted_zone()
        out = self.run_command("unstamp", "--journal", self.journal, "--apply")
        self.assertIn(
            f"stamp put back on reverted geometry: zone z of tile {tile.pk}", out
        )
        back = self.feature(tile, "z")
        self.assertEqual(back["geometry"], stale["geometry"])
        self.assertEqual(
            {k: v for k, v in back["properties"].items() if k.startswith("ms")},
            self.stamp(),
        )
        self.assertEqual(back["properties"]["note"], "edited in a stale tab")
        self.assertEqual(len(self.journal_lines()), 1)
        again = os.path.join(self.dir.name, "again.jsonl")
        _out, error = self.rebase("--apply", "--journal", again)
        self.assertIsNone(error)
        moved = self.feature(tile, "z")
        self.assertEqual(moved["geometry"]["coordinates"], [20.0, -40.0])
        self.assertEqual(frames.frame_of(moved), Frame(16, *SIZE, "read"))
        self.assertEqual(moved["properties"]["note"], "edited in a stale tab")

    @override_settings(IIIF_IMAGE_INFO_READ=True)
    def test_a_reverted_zone_without_a_stamp_key_before_loses_it(self):
        tile, _stale = self.reverted_zone()
        lines = self.journal_lines()
        lines[0]["before"].pop("msFrame")
        with open(self.journal, "w") as handle:
            handle.write(json.dumps(lines[0]) + "\n")
        self.run_command("unstamp", "--journal", self.journal, "--apply")
        self.assertNotIn("msFrame", self.feature(tile, "z")["properties"])

    def test_a_restored_zone_is_reported_already_restored_by_a_second_dry_unstamp(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp()))
        self.apply()
        self.run_command("unstamp", "--journal", self.journal, "--apply")
        out = self.run_command("unstamp", "--journal", self.journal)
        self.assertIn(f"already restored: zone z of tile {tile.pk}", out)
        self.assertNotIn("reverted", out)
        self.assertNotIn("changed since", out)

    def test_a_relabel_journal_restored_twice_says_already_restored(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(
            point("z", (320, 640), 32, stamp=Frame(32, *SIZE, "estimated").stamp())
        )
        self.run_command(
            "relabel",
            "--service",
            SVC,
            "--apply",
            "--journal",
            self.journal,
            "--zone",
            f"{tile.pk}:z",
        )
        self.run_command("unstamp", "--journal", self.journal, "--apply")
        out = self.run_command("unstamp", "--journal", self.journal)
        self.assertIn(f"already restored: zone z of tile {tile.pk}", out)


class RelabelTests(RebaseCase):
    def stamp(self, unit=32, source="estimated"):
        return Frame(unit, *SIZE, source).stamp()

    def relabel(self, *args):
        out = StringIO()
        error = None
        try:
            call_command(
                "annotation_frames",
                "relabel",
                "--service",
                SVC,
                *args,
                stdout=out,
                stderr=StringIO(),
            )
        except CommandError as caught:
            error = str(caught)
        return out.getvalue(), error

    def apply_zones(self, *zones, extra=()):
        args = [a for z in zones for a in ("--zone", z)]
        return self.relabel("--apply", "--journal", self.journal, *args, *extra)

    def test_the_named_zone_gets_the_target_stamp_and_its_geometry_is_kept(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(
            point("a", (320, 640), 32, stamp=self.stamp()),
            point("b", (320, 640), 32, stamp=self.stamp()),
        )
        a, b = self.feature(tile, "a"), copy.deepcopy(self.feature(tile, "b"))
        out, error = self.apply_zones(f"{tile.pk}:a")
        self.assertIsNone(error)
        after = self.feature(tile, "a")
        self.assertEqual(after["geometry"], a["geometry"])
        self.assertEqual(frames.frame_of(after), Frame(16, *SIZE, "read"))
        self.assertEqual(self.feature(tile, "b"), b)
        self.assertIn("1 of 1 planned zone(s) relabeled", out)
        self.assertIn("es reindex_database", out)
        (line,) = self.journal_lines()
        self.assertEqual(line["tile"], str(tile.pk))
        self.assertEqual(line["feature"], "a")
        self.assertEqual(line["canvas"], SVC)
        self.assertEqual(line["before"], a["properties"])
        self.assertEqual(line["after"], after["properties"])
        self.assertEqual(line["digest"], frames.geometry_digest(a["geometry"]))
        self.assertNotIn("geometry_before", line)

    def test_dry_run_writes_nothing(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point("a", (320, 640), 32, stamp=self.stamp()))
        before = self.snapshot()
        out, error = self.relabel("--zone", f"{tile.pk}:a")
        self.assertIsNone(error)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("1 zone(s) would be relabeled (dry run)", out)
        self.assertFalse(os.path.exists(self.journal))

    def test_bad_zone_arguments_and_missing_journal_are_refused(self):
        for bad in ("nope", "x:a", f"{uuid.uuid4()}:", f"{uuid.uuid4()}"):
            with self.subTest(bad=bad):
                _out, error = self.relabel("--zone", bad)
                self.assertIn("expected TILE-UUID:FEATURE-ID", error)
        _out, error = self.relabel("--apply", "--zone", f"{uuid.uuid4()}:a")
        self.assertIn("--journal", error)

    def test_missing_other_service_and_equal_zones_are_listed(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(
            point("same", (320, 640), 16, stamp=self.stamp(16, "read")),
            point("elsewhere", (1, 1), 32, canvas=SVC_B, stamp=self.stamp()),
        )
        ghost = uuid.uuid4()
        before = self.snapshot()
        out, error = self.apply_zones(
            f"{tile.pk}:same", f"{tile.pk}:elsewhere", f"{ghost}:z"
        )
        self.assertIsNone(error)
        self.assertEqual(self.snapshot(), before)
        self.assertIn(f"already equal: zone same of tile {tile.pk}", out)
        self.assertIn(f"on another service: zone elsewhere of tile {tile.pk}", out)
        self.assertIn(f"not found or not stamped: zone z of tile {ghost}", out)
        self.assertFalse(os.path.exists(self.journal))

    def test_a_refused_service_plans_nothing(self):
        self.answers = {SVC: units.REFUSED}
        tile = self.tile(point("a", (1, 1), 32, stamp=self.stamp()))
        before = self.snapshot()
        out, error = self.apply_zones(f"{tile.pk}:a")
        self.assertIsNone(error)
        self.assertEqual(self.snapshot(), before)
        self.assertIn(f"{SVC}: refused or not an image description", out)

    def test_an_unreadable_service_plans_nothing_and_fails(self):
        tile = self.tile(point("a", (1, 1), 32, stamp=self.stamp()))
        before = self.snapshot()
        out, error = self.apply_zones(f"{tile.pk}:a")
        self.assertEqual(self.snapshot(), before)
        self.assertIn(f"{SVC}: unreadable", out)
        self.assertIn("not measured", error)

    def test_a_provisional_zone_is_relabeled_in_provisionaledits_only(self):
        self.answers = {SVC: live(16)}
        node = str(self.annotation.pk)
        edit = {node: collection(point("a", (320, 640), 32, stamp=self.stamp()))}
        tile = self.tile(
            point("d", (320, 640), 32, stamp=self.stamp()),
            edits={"7": {"value": edit}},
        )
        data = self.row(tile).data
        out, error = self.apply_zones(f"{tile.pk}:a")
        self.assertIsNone(error)
        row = self.row(tile)
        self.assertEqual(row.data, data)
        feature = row.provisionaledits["7"]["value"][node]["features"][0]
        self.assertEqual(frames.frame_of(feature), Frame(16, *SIZE, "read"))
        self.assertEqual(self.journal_lines()[0]["provisional"], "7")

    def test_unstamp_restores_the_zone(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point("a", (320, 640), 32, stamp=self.stamp()))
        before = self.snapshot()
        self.apply_zones(f"{tile.pk}:a")
        self.assertNotEqual(self.snapshot(), before)
        self.run_command("unstamp", "--journal", self.journal, "--apply")
        self.assertEqual(self.snapshot(), before)

    def test_a_zone_changed_between_plan_and_write_is_listed_and_untouched(self):
        node = str(self.annotation.pk)
        tile = self.tile(point("a", (320, 640), 32, stamp=self.stamp()))

        def change(service):
            data = self.row(tile).data
            data[node]["features"][0]["geometry"]["coordinates"] = [5.0, -5.0]
            TileModel.objects.filter(pk=tile.pk).update(data=data)
            return live(16)

        self.answers = {SVC: change}
        out, _error = self.apply_zones(f"{tile.pk}:a")
        self.assertEqual(self.feature(tile, "a")["properties"]["msUnit"], 32)
        self.assertIn(f"changed since: zone a of tile {tile.pk}", out)
        self.assertFalse(os.path.exists(self.journal))


class RebaseZoneTests(RebaseCase):
    SINCE = "2026-11-10"

    def stamp(self, unit=32, source="estimated"):
        return Frame(unit, *SIZE, source).stamp()

    def zone_args(self, *zones):
        return [a for z in zones for a in ("--zone", z)]

    def test_a_named_estimated_zone_moves_without_since_and_the_others_stay(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(
            point("named", (320, 640), 32, stamp=self.stamp()),
            point("other", (320, 640), 32, stamp=self.stamp(32, "read")),
        )
        other = copy.deepcopy(self.feature(tile, "other"))
        out, error = self.apply(*self.zone_args(f"{tile.pk}:named"))
        self.assertIsNone(error)
        self.assertEqual(
            self.feature(tile, "named")["geometry"]["coordinates"], [20.0, -40.0]
        )
        self.assertEqual(self.feature(tile, "other"), other)
        self.assertIn("rebased: 1 zone(s)", out)
        self.assertEqual(len(self.journal_lines()), 1)

    def test_a_named_zone_skips_the_since_gate(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point("new", (320, 640), 32, stamp=self.stamp()))
        EditLog.objects.create(
            tileinstanceid=str(tile.pk),
            timestamp=datetime(2026, 11, 15),
            edittype="tile create",
            oldvalue={},
        )
        out, _error = self.apply(
            "--since", self.SINCE, *self.zone_args(f"{tile.pk}:new")
        )
        self.assertEqual(
            self.feature(tile, "new")["geometry"]["coordinates"], [20.0, -40.0]
        )

    def test_a_named_zone_still_needs_a_stamp_other_than_the_target(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point("same", (320, 640), 16, stamp=self.stamp(16, "read")))
        before = self.snapshot()
        out, _error = self.apply(*self.zone_args(f"{tile.pk}:same"))
        self.assertEqual(self.snapshot(), before)
        self.assertIn("rebased: 0 zone(s)", out)
        self.assertFalse(os.path.exists(self.journal))

    def test_a_named_zone_with_another_aspect_is_listed(self):
        self.answers = {SVC: ImageInfo(3435, 4000, 256)}
        stamp = Frame(16, 3435, 4905, "read").stamp()
        tile = self.tile(point("z", (10, 10), 16, stamp=stamp))
        before = self.snapshot()
        out, _error = self.apply("--resize", *self.zone_args(f"{tile.pk}:z"))
        self.assertEqual(self.snapshot(), before)
        self.assertIn(f"size changed: redraw: zone z of tile {tile.pk}", out)

    def test_a_zone_not_found_or_outside_the_scope_is_listed(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point("a", (1, 1), 32, stamp=self.stamp()))
        ghost = uuid.uuid4()
        out, _error = self.apply(
            "--service",
            SVC_B,
            *self.zone_args(f"{tile.pk}:a", f"{ghost}:z"),
        )
        self.assertIn(f"not found or not stamped: zone a of tile {tile.pk}", out)
        self.assertIn(f"not found or not stamped: zone z of tile {ghost}", out)

    def test_a_bad_zone_argument_is_refused(self):
        _out, error = self.rebase("--zone", "nope")
        self.assertIn("expected TILE-UUID:FEATURE-ID", error)

    def test_an_integer_feature_id_is_matched_by_its_text(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point(7, (320, 640), 32, stamp=self.stamp()))
        self.apply(*self.zone_args(f"{tile.pk}:7"))
        self.assertEqual(
            self.feature(tile, 7)["geometry"]["coordinates"], [20.0, -40.0]
        )

    def test_relabel_matches_an_integer_feature_id(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point(7, (320, 640), 32, stamp=self.stamp()))
        out = StringIO()
        call_command(
            "annotation_frames",
            "relabel",
            "--service",
            SVC,
            "--zone",
            f"{tile.pk}:7",
            "--apply",
            "--journal",
            self.journal,
            stdout=out,
            stderr=StringIO(),
        )
        self.assertEqual(
            frames.frame_of(self.feature(tile, 7)), Frame(16, *SIZE, "read")
        )
        self.assertNotIn("not found", out.getvalue())


class RebaseReportTests(RebaseCase):
    def stamp(self, unit=32, source="read"):
        return Frame(unit, *SIZE, source).stamp()

    def section(self, out, canvas):
        """The lines printed under the header line of *canvas*."""
        lines = out.splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith(f"{canvas}:"))
        found = []
        for line in lines[start + 1 :]:
            if not line.startswith("  "):
                break
            found.append(line.strip())
        return found

    def test_an_import_legacy_zone_is_counted_apart_and_never_moved(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(
            point("l", (320, 640), 32, stamp=self.stamp(32, "import-legacy"))
        )
        before = self.snapshot()
        out, _error = self.apply()
        self.assertEqual(self.snapshot(), before)
        self.assertIn("import-legacy: 1 zone(s), never moved", out)
        self.assertNotIn("size changed", out)
        self.assertNotIn(f"zone l of tile {tile.pk}", out)

    def test_a_change_since_is_listed_under_its_own_canvas_when_ids_collide(self):
        node = str(self.annotation.pk)
        tile = self.tile(
            point("z", (320, 640), 32, canvas=SVC, stamp=self.stamp()),
            point("z", (320, 640), 32, canvas=SVC_B, stamp=self.stamp()),
        )

        def change(service):
            data = self.row(tile).data
            data[node]["features"][0]["geometry"]["coordinates"] = [5.0, -5.0]
            TileModel.objects.filter(pk=tile.pk).update(data=data)
            return live(16)

        self.answers = {SVC: change, SVC_B: live(16)}
        out, _error = self.apply()
        self.assertIn(
            f"changed since: zone z of tile {tile.pk}", self.section(out, SVC)
        )
        self.assertIn("rebased: 0 zone(s)", self.section(out, SVC))
        self.assertIn("rebased: 1 zone(s)", self.section(out, SVC_B))
        self.assertNotIn(
            f"changed since: zone z of tile {tile.pk}", self.section(out, SVC_B)
        )

    def test_the_rebased_count_follows_the_journal_lines(self):
        self.answers = {SVC: live(16)}
        twin = point("z", (320, 640), 32, stamp=self.stamp())
        self.tile(twin, copy.deepcopy(twin))
        out, _error = self.apply()
        self.assertEqual(len(self.journal_lines()), 2)
        self.assertIn("rebased: 2 zone(s)", self.section(out, SVC))


class UnstampZoneTests(RebaseCase):
    SINCE = "2026-11-10"

    def stamp(self, unit=32, source="estimated"):
        return Frame(unit, *SIZE, source).stamp()

    def unstamp(self, *args):
        out = StringIO()
        call_command(
            "annotation_frames",
            "unstamp",
            "--journal",
            self.journal,
            *args,
            stdout=out,
            stderr=StringIO(),
        )
        return out.getvalue()

    def two_zones(self):
        self.answers = {SVC: live(16)}
        node = str(self.annotation.pk)
        stale = point("z", (320, 640), 32, stamp=self.stamp())
        stale["properties"]["note"] = "edited in a stale tab"
        other = point("y", (640, 640), 32, stamp=self.stamp())
        tile = self.tile(copy.deepcopy(stale), copy.deepcopy(other))
        EditLog.objects.create(
            tileinstanceid=str(tile.pk),
            timestamp=datetime(2026, 11, 15),
            edittype="tile edit",
            oldvalue={node: collection(stale, other)},
        )
        return tile, stale

    @override_settings(IIIF_IMAGE_INFO_READ=True)
    def test_a_since_rebase_is_repaired_zone_by_zone_end_to_end(self):
        tile, stale = self.two_zones()
        self.apply("--since", self.SINCE)
        self.assertEqual(
            self.feature(tile, "y")["geometry"]["coordinates"], [40.0, -40.0]
        )
        RebaseWriteTests.stale_save(self, tile, stale, self.feature(tile, "y"))
        self.assertEqual(self.feature(tile, "z")["properties"]["msUnit"], 16)
        out = self.unstamp("--zone", f"{tile.pk}:z", "--apply")
        self.assertIn(
            f"stamp put back on reverted geometry: zone z of tile {tile.pk}", out
        )
        z, y = self.feature(tile, "z"), self.feature(tile, "y")
        self.assertEqual(z["geometry"], stale["geometry"])
        self.assertEqual(
            {k: v for k, v in z["properties"].items() if k.startswith("ms")},
            self.stamp(),
        )
        self.assertEqual(z["properties"]["note"], "edited in a stale tab")
        self.assertEqual(y["geometry"]["coordinates"], [40.0, -40.0])
        self.assertEqual(frames.frame_of(y), Frame(16, *SIZE, "read"))
        again = os.path.join(self.dir.name, "again.jsonl")
        _out, error = self.rebase(
            "--service", SVC, "--zone", f"{tile.pk}:z", "--apply", "--journal", again
        )
        self.assertIsNone(error)
        moved = self.feature(tile, "z")
        self.assertEqual(moved["geometry"]["coordinates"], [20.0, -40.0])
        self.assertEqual(frames.frame_of(moved), Frame(16, *SIZE, "read"))
        self.assertEqual(self.feature(tile, "y"), y)

    def test_a_zone_absent_from_the_journal_is_listed_and_nothing_is_written(self):
        tile, _stale = self.two_zones()
        self.apply("--since", self.SINCE)
        before = self.snapshot()
        out = self.unstamp("--zone", f"{tile.pk}:nope", "--apply")
        self.assertEqual(self.snapshot(), before)
        self.assertIn(f"not in the journal: zone nope of tile {tile.pk}", out)
        self.assertIn("0 of 0 journaled zone(s) restored", out)

    def test_only_the_named_zone_is_restored(self):
        tile, _stale = self.two_zones()
        self.apply("--since", self.SINCE)
        out = self.unstamp("--zone", f"{tile.pk}:z", "--apply")
        self.assertIn("1 of 1 journaled zone(s) restored", out)
        self.assertEqual(
            self.feature(tile, "z")["geometry"]["coordinates"], [10.0, -20.0]
        )
        self.assertEqual(
            self.feature(tile, "y")["geometry"]["coordinates"], [40.0, -40.0]
        )

    def test_a_bad_zone_argument_is_refused(self):
        with self.assertRaisesMessage(CommandError, "expected TILE-UUID:FEATURE-ID"):
            self.unstamp("--zone", "nope")


class RebaseOddityTests(RebaseCase):
    def test_since_is_said_to_be_ignored_with_zone(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(
            point("z", (320, 640), 32, stamp=Frame(32, *SIZE, "read").stamp())
        )
        out, _error = self.rebase("--since", "2026-11-10", "--zone", f"{tile.pk}:z")
        self.assertIn("--since is ignored with --zone", out)
        out, _error = self.rebase("--zone", f"{tile.pk}:z")
        self.assertNotIn("--since is ignored", out)

    def test_two_stamps_on_the_same_id_geometry_and_canvas_are_both_planned(self):
        self.answers = {SVC: live(16)}
        first = point("z", (320, 640), 32, stamp=Frame(32, *SIZE, "read").stamp())
        second = point("z", (320, 640), 32, stamp=Frame(32, *SIZE, "browser").stamp())
        tile = self.tile(first, second)
        self.apply()
        data = self.row(tile).data[str(self.annotation.pk)]["features"]
        self.assertEqual(
            [f["geometry"]["coordinates"] for f in data], [[20.0, -40.0]] * 2
        )
        self.assertEqual(len(self.journal_lines()), 2)


class RepairEdgeTests(RebaseCase):
    def stamp(self, unit=32, source="read"):
        return Frame(unit, *SIZE, source).stamp()

    def call(self, verb, *args):
        out, err = StringIO(), StringIO()
        error = None
        try:
            call_command("annotation_frames", verb, *args, stdout=out, stderr=err)
        except CommandError as caught:
            error = str(caught)
        return out.getvalue(), err.getvalue(), error

    def frames_path(self, content):
        path = os.path.join(self.dir.name, "frames.json")
        with open(path, "w") as handle:
            handle.write(content)
        return path

    def test_a_journal_failing_on_the_second_batch_keeps_the_first_line_and_says_so(
        self,
    ):
        self.answers = {SVC: live(16)}
        first = self.tile(point("a", (320, 640), 32, stamp=self.stamp()))
        second = self.tile(point("b", (320, 640), 32, stamp=self.stamp()))
        real, seen = os.write, []

        def full(fd, data):
            if bytes(data).startswith(b'{"'):
                seen.append(1)
                if len(seen) == 2:
                    raise OSError(errno.ENOSPC, "No space left on device")
            return real(fd, data)

        with mock.patch(
            "manuspectrum.management.commands.annotation_frames.os.write", full
        ):
            _out, err, error = self.call(
                "rebase", "--host", "rb.example", "--batch", "1",
                "--apply", "--journal", self.journal,
            )  # fmt: skip
        self.assertIn("journal write failed", error)
        self.assertIn("No space left", error)
        self.assertIn(f"The run stopped; the journal {self.journal} was kept", err)
        self.assertIn(f"annotation_frames unstamp --journal {self.journal}", err)
        lines = self.journal_lines()
        self.assertEqual(len(lines), 1)
        units_after = {
            t.pk: self.feature(t, f)["properties"]["msUnit"]
            for t, f in ((first, "a"), (second, "b"))
        }
        written_tile = {str(first.pk): first, str(second.pk): second}[lines[0]["tile"]]
        self.assertEqual(units_after[written_tile.pk], 16)
        self.assertEqual(sorted(units_after.values()), [16, 32])

    def test_a_tile_deleted_between_plan_and_write_is_listed_changed_since(self):
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp()))

        def delete(service):
            TileModel.objects.filter(pk=tile.pk).delete()
            return live(16)

        self.answers = {SVC: delete}
        out, _error = self.apply()
        self.assertIn(f"changed since: zone z of tile {tile.pk}", out)
        self.assertFalse(os.path.exists(self.journal))

    def test_a_node_value_that_stopped_being_a_collection_is_listed_changed_since(
        self,
    ):
        node = str(self.annotation.pk)
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp()))

        def blank(service):
            TileModel.objects.filter(pk=tile.pk).update(data={node: None})
            return live(16)

        self.answers = {SVC: blank}
        out, _error = self.apply()
        self.assertIn(f"changed since: zone z of tile {tile.pk}", out)
        self.assertEqual(self.row(tile).data, {node: None})

    def test_a_geometry_the_change_refuses_is_listed_and_the_tile_untouched(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp()))
        before = self.row(tile).data
        real, calls = frame_scope.scaled_geometry, []

        def refuse_when_writing(geometry, fx, fy):
            calls.append(1)
            if len(calls) > 1:
                raise ValueError("not a coordinate")
            return real(geometry, fx, fy)

        with mock.patch(
            "manuspectrum.management.commands.annotation_frames.frame_scope"
            ".scaled_geometry",
            refuse_when_writing,
        ):
            out, _error = self.apply()
        self.assertIn(f"changed since: zone z of tile {tile.pk}", out)
        self.assertEqual(self.row(tile).data, before)
        self.assertFalse(os.path.exists(self.journal))

    def test_an_unreadable_frames_file_names_the_file_for_rebase_and_relabel(self):
        path = self.frames_path("not json")
        for verb, args in (
            ("rebase", ("--service", SVC)),
            ("relabel", ("--service", SVC, "--zone", f"{uuid.uuid4()}:z")),
        ):
            with self.subTest(verb=verb):
                _out, _err, error = self.call(verb, *args, "--frames", path)
                self.assertTrue(error.startswith(f"{path}: not JSON"), error)

    def test_a_rebase_with_nothing_stamped_says_so(self):
        out, _error = self.rebase("--service", SVC)
        self.assertIn("No stamped zone to rebase.", out)

    def test_a_relabel_listing_the_same_stamped_zone_twice_plans_it_once(self):
        self.answers = {SVC: live(16)}
        twin = point("z", (320, 640), 32, stamp=self.stamp(source="estimated"))
        tile = self.tile(twin, copy.deepcopy(twin))
        out, _err, _error = self.call(
            "relabel", "--service", SVC, "--zone", f"{tile.pk}:z"
        )
        self.assertIn("1 zone(s) would be relabeled (dry run)", out)


class MeasuresTests(RebaseCase):
    def test_a_server_read_that_cannot_be_a_frame_is_refused(self):
        self.answers = {SVC: ImageInfo(1_000_001, 10, 512)}
        self.assertEqual(
            annotation_frames.Measures().frame(SVC), annotation_frames.REFUSED_STATE
        )

    def test_a_file_entry_that_cannot_be_a_frame_falls_back_to_the_server_answer(self):
        bad = ImageInfo(1_000_001, 10, 512)
        listed = frame_scope.FramesFile({SVC: bad}, [], "2026-11-23T10:00:00Z", "o")
        for answer, state in (
            (units.REFUSED, annotation_frames.REFUSED_STATE),
            (units.UNAVAILABLE, annotation_frames.UNREADABLE_STATE),
        ):
            with self.subTest(answer=answer):
                self.answers = {SVC: answer}
                self.assertEqual(annotation_frames.Measures(listed).frame(SVC), state)

    def test_a_file_entry_stands_in_for_a_refused_service(self):
        self.answers = {SVC: units.REFUSED}
        listed = frame_scope.FramesFile({SVC: live(16)}, [], "2026-11-23", "o")
        got = annotation_frames.Measures(listed).frame(SVC)
        self.assertEqual((got.unit, got.source), (16, "browser"))
