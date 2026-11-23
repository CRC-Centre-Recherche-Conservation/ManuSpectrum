"""The ``annotation_frames rebase`` verb: factors, scaled geometry and the guarded batches.

Usage:
    python manage.py test tests.test_annotation_frames_rebase --settings=tests.test_settings --noinput
"""

import copy
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
    """Review focus 5: what the project reads, through the real stamp -> unit -> pixel path."""

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
        self.assertIn("size changed: redraw, or relabel by hand", out)
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
        self.assertIn("size changed: redraw, or relabel by hand", out)
        self.assertEqual(self.feature(tile, "z"), before)


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
            f"drawn or moved since {self.SINCE}: review, then relabel: zone new of tile {tile.pk}",
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

    @override_settings(IIIF_IMAGE_INFO_READ=True)
    def test_a_stale_editor_save_after_the_rebase_is_named_by_a_dry_unstamp(self):
        self.answers = {SVC: live(16)}
        tile = self.tile(point("z", (320, 640), 32, stamp=self.stamp()))
        stale = copy.deepcopy(self.feature(tile, "z"))
        stale["properties"]["note"] = "edited in a stale tab"
        self.apply()
        row = Tile.objects.get(pk=tile.pk)
        node = str(self.annotation.pk)
        row.data = {node: collection(stale), str(self.other.pk): None}
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
        self.assertEqual(self.snapshot(), before)
