"""``iiif.units``: the pixels of one stored annotation unit, and the zones converted with them.

Usage:
    python manage.py test tests.test_iiif_units --settings=tests.test_settings
"""

import json
import time
from unittest import mock

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from manuspectrum.iiif import memo, units
from manuspectrum.iiif.sources import canvas_index
from manuspectrum.iiif.zones import (
    FeatureRows,
    canvas_and_convert,
    canvas_and_shape,
    first_zone,
)
from manuspectrum.utils.budget import BudgetSpent, upstream_budget
from manuspectrum.utils.http import FetchedResponse, UnsafeURLError

SERVICE = "https://images.example/iiif/2/folio-1"
OTHER = "https://images.example/iiif/2/folio-2"
CANVAS = "https://docs.example/manifest/canvas/1"


def info_json(width, height, tile=None, **extra):
    body = {"width": width, "height": height, **extra}
    if tile:
        body["tiles"] = [{"width": tile, "scaleFactors": [1, 2, 4]}]
    return body


def answered(body, status=200, url=f"{SERVICE}/info.json"):
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    return FetchedResponse(url, status, {}, content)


def canvas(service=SERVICE, width=4913, height=6609, canvas_id=CANVAS):
    return {
        "id": canvas_id,
        "label": "1",
        "image": {"service": service, "url": None, "width": width, "height": height},
    }


def feature(geometry, stored=SERVICE):
    return {"id": None, "geometry": geometry, "properties": {"canvas": stored}}


def point(x, y):
    return {"type": "Point", "coordinates": [x, y]}


def box(x0, y0, x1, y1):
    """A rectangle in stored units, y upwards (``y0`` and ``y1`` negative on the image)."""
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


@override_settings(IIIF_IMAGE_INFO_READ=True)
class UnitCase(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        patcher = mock.patch("manuspectrum.iiif.units.safe_fetch")
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)

    def serve(self, *bodies):
        self.fetch.side_effect = [
            b if isinstance(b, (Exception, FetchedResponse)) else answered(b)
            for b in bodies
        ]


class NativeZoomTests(SimpleTestCase):
    def test_it_is_the_zoom_leaflet_iiif_gives_the_image(self):
        for width, height, tile, zoom in (
            (4913, 6609, 512, 4),
            (5295, 6994, 256, 5),
            (611, 947, 512, 1),
            (2419, 3191, 512, 3),
            (1866, 2696, 256, 4),
            (9000, 12000, 256, 6),
            (4096, 4096, 256, 4),
            (4097, 4096, 256, 5),
            (4219, 5715, 1024, 3),
            (200, 100, 256, 0),
        ):
            with self.subTest(width=width, height=height, tile=tile):
                self.assertEqual(units.native_zoom(width, height, tile), zoom)

    def test_the_tile_width_is_read_as_leaflet_iiif_reads_it(self):
        self.assertEqual(units.tile_width({"tiles": [{"width": 512}]}), 512)
        self.assertEqual(
            units.tile_width({"tiles": [{"width": 1024}, {"width": 256}]}), 1024
        )
        self.assertEqual(units.tile_width({"tile_width": 1024}), 1024)
        self.assertEqual(units.tile_width({"sizes": [{"width": 100}]}), 256)
        self.assertEqual(units.tile_width({"tiles": []}), 256)

    def test_a_tile_width_that_is_not_a_whole_number_falls_back_to_256(self):
        for bad in (0, 0.5, -512, True, float("nan"), float("inf"), "512", None):
            with self.subTest(tile=bad):
                self.assertEqual(units.tile_width({"tiles": [{"width": bad}]}), 256)
        self.assertEqual(units.tile_width({"tiles": [{"width": 512.0}]}), 512)


class ImageInfoTests(UnitCase):
    def test_an_info_json_is_read_once_and_kept(self):
        self.serve(info_json(4913, 6609, 512))
        first = units.image_info(SERVICE)
        second = units.image_info(f"{SERVICE}/")
        self.assertEqual(first, units.ImageInfo(4913, 6609, 512))
        self.assertEqual(second, first)
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.fetch.call_args.args[0], f"{SERVICE}/info.json")
        self.assertEqual(self.fetch.call_args.kwargs["purpose"], "image_info")

    def test_an_image_api_1_description_gives_its_tile_width(self):
        self.serve({"width": 4219, "height": 5715, "tile_width": 1024})
        self.assertEqual(units.image_info(SERVICE), units.ImageInfo(4219, 5715, 1024))

    def test_a_description_without_tiles_is_tiled_at_256(self):
        self.serve(info_json(3000, 2000, sizes=[{"width": 3000, "height": 2000}]))
        self.assertEqual(units.image_info(SERVICE), units.ImageInfo(3000, 2000, 256))

    def test_a_403_refuses_the_whole_host_for_a_while(self):
        self.serve(answered(b"blocked", status=403))
        self.assertEqual(units.image_info(SERVICE), units.REFUSED)
        self.assertEqual(units.image_info(OTHER), units.REFUSED)
        self.assertEqual(self.fetch.call_count, 1)

    def test_a_404_refuses_that_service_only(self):
        self.serve(answered(b"", status=404), info_json(1000, 1000, 256))
        self.assertEqual(units.image_info(SERVICE), units.REFUSED)
        self.assertEqual(units.image_info(SERVICE), units.REFUSED)
        self.assertEqual(units.image_info(OTHER), units.ImageInfo(1000, 1000, 256))
        self.assertEqual(self.fetch.call_count, 2)

    def test_a_body_that_describes_no_image_is_refused(self):
        for body in (b"<html>", {"width": 0, "height": 10}, ["width"]):
            with self.subTest(body=body):
                cache.clear()
                self.serve(body)
                self.assertEqual(units.image_info(SERVICE), units.REFUSED)

    def test_a_size_that_is_not_a_whole_number_describes_no_image(self):
        for bad in (0.5, 0, -1, True, float("inf"), float("nan"), "100"):
            for field in ("width", "height"):
                with self.subTest(bad=bad, field=field):
                    cache.clear()
                    body = {"width": 100, "height": 100, field: bad}
                    self.fetch.side_effect = [
                        FetchedResponse(
                            f"{SERVICE}/info.json",
                            200,
                            {},
                            json.dumps(body, allow_nan=True).encode(),
                        )
                    ]
                    self.assertEqual(units.image_info(SERVICE), units.REFUSED)

    def test_a_whole_float_size_is_read(self):
        self.serve({"width": 4913.0, "height": 6609.0, "tiles": [{"width": 512.0}]})
        self.assertEqual(units.image_info(SERVICE), units.ImageInfo(4913, 6609, 512))

    def test_a_url_the_guard_rejects_is_refused(self):
        self.serve(UnsafeURLError("private address"))
        self.assertEqual(units.image_info(SERVICE), units.REFUSED)

    def test_a_timeout_is_unavailable_and_leaves_the_host_alone(self):
        self.serve(requests.exceptions.ConnectTimeout())
        self.assertEqual(units.image_info(SERVICE), units.UNAVAILABLE)
        self.assertEqual(units.image_info(OTHER), units.UNAVAILABLE)
        self.assertEqual(self.fetch.call_count, 1)

    def test_a_name_that_does_not_resolve_is_a_failure_not_a_refusal(self):
        self.serve(UnsafeURLError("no address", reason="dns"))
        self.assertEqual(units.image_info(SERVICE), units.UNAVAILABLE)
        self.assertEqual(units.image_info(OTHER), units.UNAVAILABLE)
        self.assertEqual(self.fetch.call_count, 1)

    def test_another_guard_reason_is_still_a_refusal_of_that_service(self):
        self.serve(UnsafeURLError("private", reason="private"), info_json(10, 10, 256))
        self.assertEqual(units.image_info(SERVICE), units.REFUSED)
        self.assertEqual(units.image_info(OTHER), units.ImageInfo(10, 10, 256))

    def test_a_spent_budget_is_no_verdict_on_the_host(self):
        self.serve(BudgetSpent(), info_json(10, 10, 256))
        self.assertEqual(units.image_info(SERVICE), units.UNAVAILABLE)
        self.assertEqual(units.image_info(OTHER), units.ImageInfo(10, 10, 256))

    def test_a_timeout_under_a_shortened_read_is_no_verdict_on_the_host(self):
        self.serve(requests.exceptions.ReadTimeout(), info_json(10, 10, 256))
        self.assertEqual(
            units.image_info(SERVICE, deadline=time.monotonic() + 1),
            units.UNAVAILABLE,
        )
        self.assertEqual(units.image_info(OTHER), units.ImageInfo(10, 10, 256))

    def test_a_timeout_under_a_short_ambient_budget_is_no_verdict_either(self):
        self.serve(requests.exceptions.ReadTimeout(), info_json(10, 10, 256))
        with upstream_budget(1):
            self.assertEqual(units.image_info(SERVICE), units.UNAVAILABLE)
        self.assertEqual(units.image_info(OTHER), units.ImageInfo(10, 10, 256))

    def test_a_connection_error_marks_the_host_even_under_a_shortened_read(self):
        self.serve(requests.exceptions.ConnectionError(), info_json(10, 10, 256))
        self.assertEqual(
            units.image_info(SERVICE, deadline=time.monotonic() + 1),
            units.UNAVAILABLE,
        )
        self.assertEqual(units.image_info(OTHER), units.UNAVAILABLE)
        self.assertEqual(self.fetch.call_count, 1)

    def test_a_503_is_unavailable_and_nothing_is_kept_for_the_service(self):
        self.serve(answered(b"", status=503), info_json(1000, 1000, 256))
        self.assertEqual(units.image_info(SERVICE), units.UNAVAILABLE)
        cache.delete(units._host_key(SERVICE))
        self.assertEqual(units.image_info(SERVICE), units.ImageInfo(1000, 1000, 256))

    def test_past_the_deadline_nothing_is_requested(self):
        self.assertEqual(
            units.image_info(SERVICE, deadline=time.monotonic() - 1),
            units.UNAVAILABLE,
        )
        self.fetch.assert_not_called()

    @override_settings(IIIF_IMAGE_INFO_READ=False)
    def test_switched_off_nothing_is_requested(self):
        self.assertEqual(units.image_info(SERVICE), units.REFUSED)
        self.fetch.assert_not_called()

    @override_settings(
        CANTALOUPE_HTTP_ENDPOINT="https://manuspectrum.test/iiifserver/",
        CANTALOUPE_INTERNAL_ENDPOINT="http://cantaloupe:8182/",
    )
    def test_the_own_image_server_is_read_from_its_internal_endpoint(self):
        self.serve(info_json(4913, 6609, 512), info_json(100, 100))
        own = "https://manuspectrum.test/iiifserver/iiif/2/ILLUS_001.png"
        self.assertEqual(units.image_info(own), units.ImageInfo(4913, 6609, 512))
        call = self.fetch.call_args_list[0]
        self.assertEqual(
            call.args[0], "http://cantaloupe:8182/iiif/2/ILLUS_001.png/info.json"
        )
        self.assertIs(call.kwargs["allow_private"], True)
        units.image_info(SERVICE)
        self.assertNotIn("allow_private", self.fetch.call_args_list[1].kwargs)

    @override_settings(
        CANTALOUPE_HTTP_ENDPOINT="https://manuspectrum.test/iiifserver/",
        CANTALOUPE_INTERNAL_ENDPOINT="http://cantaloupe:8182/",
    )
    def test_only_the_own_image_server_skips_the_host_throttle(self):
        self.serve(info_json(100, 100), info_json(100, 100))
        units.image_info("https://manuspectrum.test/iiifserver/iiif/2/A.png")
        units.image_info(SERVICE)
        own, other = self.fetch.call_args_list
        self.assertIs(own.kwargs["throttle"], False)
        self.assertIs(other.kwargs["throttle"], True)


class ZoneUnitTests(UnitCase):
    def test_a_stored_unit_is_two_to_the_native_zoom_in_image_pixels(self):
        for width, height, tile, scale in (
            (611, 947, 512, 2),
            (4913, 6609, 512, 16),
            (5295, 6994, 256, 32),
            (9000, 12000, 256, 64),
        ):
            with self.subTest(scale=scale):
                cache.clear()
                self.serve(info_json(width, height, tile))
                unit = units.zone_unit(SERVICE, width, height)
                self.assertEqual((unit.x, unit.y), (scale, scale))
                self.assertTrue(unit.read)
                self.assertEqual((unit.width, unit.height), (width, height))

    def test_a_canvas_at_another_size_scales_each_axis(self):
        self.serve(info_json(4913, 6609, 512))
        unit = units.zone_unit(SERVICE, 1000, 1345)
        self.assertAlmostEqual(unit.x, 16 * 1000 / 4913)
        self.assertAlmostEqual(unit.y, 16 * 1345 / 6609)
        self.assertEqual((unit.width, unit.height), (1000, 1345))

    def test_an_unread_image_is_assumed_from_the_canvas_at_256(self):
        self.serve(answered(b"", status=403))
        unit = units.zone_unit(SERVICE, 4913, 6609)
        self.assertEqual((unit.x, unit.y, unit.read), (32, 32, False))
        self.assertIsNone(unit.width)
        small = units.zone_unit(OTHER, 1866, 2696)
        self.assertEqual((small.x, small.read), (16, False))

    @override_settings(IIIF_IMAGE_TILE_HINTS={"images.example": 1024})
    def test_a_host_hint_gives_the_tile_width_of_an_unread_image(self):
        self.serve(answered(b"", status=403))
        unit = units.zone_unit(SERVICE, 4219, 5715)
        self.assertEqual((unit.x, unit.read), (8, False))

    @override_settings(
        CANTALOUPE_HTTP_ENDPOINT="https://manuspectrum.test/iiifserver/",
        IIIF_IMAGE_TILE_HINTS={"hinted.example": 1024},
    )
    def test_an_unread_image_of_the_own_server_is_assumed_at_512(self):
        own = "https://manuspectrum.test/iiifserver/iiif/2/A.png"
        unit = units.assumed_unit(4913, 6609, own)
        self.assertEqual(unit.x, 16)
        self.assertEqual(units.assumed_unit(4913, 6609, SERVICE).x, 32)
        self.assertEqual(
            units.assumed_unit(4913, 6609, "https://manuspectrum.test/iiifserverx/a").x,
            32,
        )
        with override_settings(
            IIIF_IMAGE_TILE_HINTS={"manuspectrum.test": 1024}, IIIF_OWN_IMAGE_TILE=256
        ):
            self.assertEqual(units.assumed_unit(4913, 6609, own).x, 8)
        with override_settings(IIIF_OWN_IMAGE_TILE=256):
            self.assertEqual(units.assumed_unit(4913, 6609, own).x, 32)

    def test_a_canvas_without_a_service_is_assumed_without_a_request(self):
        unit = units.zone_unit(None, 4913, 6609)
        self.assertEqual((unit.x, unit.read), (32, False))
        self.fetch.assert_not_called()

    def test_a_failed_read_marks_the_memo_build_degraded_and_a_refusal_does_not(self):
        marks = []
        token = memo._degraded.set(marks)
        self.addCleanup(memo._degraded.reset, token)
        self.serve(answered(b"", status=403))
        units.zone_unit(SERVICE, 100, 100)
        self.assertEqual(marks, [])
        cache.clear()
        self.serve(requests.exceptions.ReadTimeout())
        units.zone_unit(SERVICE, 100, 100)
        self.assertEqual(marks, [True])


class ZoneConversionTests(UnitCase):
    def shape(self, geometry, listed=None, stored=SERVICE):
        dims = canvas_index(listed if listed is not None else [canvas()])
        return canvas_and_shape(feature(geometry, stored), dims)

    def test_a_zone_is_in_true_pixels_at_every_scale(self):
        for width, height, tile, scale in (
            (611, 947, 512, 2),
            (4913, 6609, 512, 16),
            (5295, 6994, 256, 32),
            (9000, 12000, 256, 64),
        ):
            with self.subTest(scale=scale):
                cache.clear()
                self.serve(info_json(width, height, tile))
                found, shape = self.shape(
                    box(10, -20, 15, -30), [canvas(width=width, height=height)]
                )
                self.assertEqual(found, CANVAS)
                self.assertEqual(
                    shape,
                    {
                        "type": "rect",
                        "x": 10 * scale,
                        "y": 20 * scale,
                        "w": 5 * scale,
                        "h": 10 * scale,
                    },
                )

    def test_the_zone_of_the_production_report_lands_where_arches_draws_it(self):
        self.serve(info_json(4913, 6609, 512))
        _, shape = self.shape(box(105, -57.8125, 111.625, -66.5625))
        self.assertEqual(
            shape, {"type": "rect", "x": 1680, "y": 925, "w": 106, "h": 140}
        )

    def test_a_point_is_converted_like_a_corner(self):
        self.serve(info_json(4913, 6609, 512))
        _, shape = self.shape(point(105, -57.8125))
        self.assertEqual(shape, {"type": "point", "x": 1680, "y": 925})

    def test_a_canvas_declared_at_another_size_gets_canvas_pixels(self):
        self.serve(info_json(4000, 6000, 512))
        _, shape = self.shape(point(125, -187.5), [canvas(width=1000, height=1500)])
        self.assertEqual(shape, {"type": "point", "x": 500, "y": 750})

    def test_a_zone_beyond_a_read_image_is_brought_inside_its_canvas(self):
        self.serve(info_json(4913, 6609, 512))
        _, shape = self.shape(box(300, -400, 400, -500))
        self.assertEqual(
            shape, {"type": "rect", "x": 4800, "y": 6400, "w": 112, "h": 208}
        )

    def test_with_an_assumed_unit_a_zone_keeps_its_stored_extent(self):
        self.serve(requests.exceptions.ConnectTimeout())
        _, shape = self.shape(box(300, -400, 400, -500))
        self.assertEqual(
            shape, {"type": "rect", "x": 9600, "y": 12800, "w": 3200, "h": 3200}
        )

    def test_a_zone_on_a_canvas_the_manifest_does_not_list_keeps_its_name(self):
        found, shape = self.shape(point(10, -20), stored="https://else.example/x")
        self.assertEqual(found, "https://else.example/x")
        self.assertEqual(shape, {"type": "point", "x": 320, "y": 640})
        self.fetch.assert_not_called()

    def test_a_zone_stored_under_the_canvas_id_reads_the_canvas_service(self):
        self.serve(info_json(4913, 6609, 512))
        _, shape = self.shape(point(10, -20), stored=CANVAS)
        self.assertEqual(shape, {"type": "point", "x": 160, "y": 320})
        self.assertEqual(self.fetch.call_args.args[0], f"{SERVICE}/info.json")

    def test_nothing_is_requested_until_a_shape_is_asked(self):
        self.serve(info_json(4913, 6609, 512))
        dims = canvas_index([canvas()])
        found, convert = canvas_and_convert(feature(point(10, -20)), dims)
        self.assertEqual(found, CANVAS)
        self.assertIsNone(dims.unit_used(CANVAS))
        self.fetch.assert_not_called()
        self.assertEqual(convert(), {"type": "point", "x": 160, "y": 320})
        self.assertEqual(convert(), {"type": "point", "x": 160, "y": 320})
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(
            dims.unit_used(CANVAS).payload(), {"x": 16.0, "y": 16.0, "read": True}
        )

    def test_an_invalid_geometry_is_unresolved_without_a_request(self):
        self.assertEqual(self.shape({"type": "Polygon", "coordinates": []}), ("", None))
        self.assertEqual(self.shape(None), ("", None))
        self.fetch.assert_not_called()

    def test_the_canvases_of_one_manifest_share_one_deadline(self):
        listed = [
            canvas(),
            canvas(service=OTHER, canvas_id=f"{CANVAS}-b", width=1866, height=2696),
        ]
        dims = canvas_index(listed)
        now = [100.0]
        read = answered(info_json(4913, 6609, 512))

        def slow_read(*args, **kwargs):
            now[0] = 107.0
            return read

        self.fetch.side_effect = slow_read
        with (
            override_settings(IIIF_IMAGE_INFO_DEADLINE=6),
            mock.patch("manuspectrum.iiif.units.time.monotonic", lambda: now[0]),
        ):
            first = dims.unit(SERVICE)
            second = dims.unit(OTHER)
        self.assertTrue(first.read)
        self.assertEqual((second.x, second.read), (16, False))
        self.assertEqual(self.fetch.call_count, 1)

    def test_located_rows_read_only_the_canvases_whose_shape_is_asked(self):
        self.serve(info_json(1866, 2696, 256))
        listed = [
            canvas(),
            canvas(service=OTHER, canvas_id=f"{CANVAS}-b", width=1866, height=2696),
        ]
        rows = FeatureRows(None, [], set())
        rows._by_resource["r"] = [
            (0, "r", feature(point(10, -20))),
            (1, "r", feature(point(10, -20), stored=OTHER)),
        ]
        located = list(rows.located(["r"], canvas_index(listed)))
        self.assertEqual([row[2] for row in located], [CANVAS, f"{CANVAS}-b"])
        self.fetch.assert_not_called()
        self.assertEqual(located[1][3](), {"type": "point", "x": 160, "y": 320})
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.fetch.call_args.args[0], f"{OTHER}/info.json")


class KeptZoneTests(UnitCase):
    def rows(self):
        rows = FeatureRows(None, [], set())
        rows._by_resource["r"] = [
            (0, "r", feature(point(10, -20))),
            (1, "r", feature(point(10, -20), stored=OTHER)),
        ]
        return rows

    def listed(self):
        return [
            canvas(),
            canvas(service=OTHER, canvas_id=f"{CANVAS}-b", width=1866, height=2696),
        ]

    def test_first_zone_reads_only_the_unit_of_the_zone_it_keeps(self):
        self.serve(info_json(4913, 6609, 512))
        dims = canvas_index(self.listed())
        with mock.patch(
            "manuspectrum.iiif.zones.FeatureRows", return_value=self.rows()
        ):
            zones = first_zone(mock.Mock(), ["r"], dims, set())
        self.assertEqual(
            zones,
            {"r": {"canvas": CANVAS, "shape": {"type": "point", "x": 160, "y": 320}}},
        )
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.fetch.call_args.args[0], f"{SERVICE}/info.json")
        self.assertIsNone(dims.unit_used(f"{CANVAS}-b"))

    def test_analysis_zones_reads_only_the_unit_of_the_zone_it_keeps(self):
        from manuspectrum.views.explorer import export

        self.serve(info_json(4913, 6609, 512))
        listed = self.listed()
        scope = mock.Mock(
            documents=["d"],
            analyses=["r"],
            nodegroups=set(),
        )
        scope.bundle.chains = {"r": ("d",)}
        scope.read_manifest.return_value = {}
        labels = {c["id"]: c["label"] for c in listed}
        built = {}

        def index(canvases):
            built["dims"] = canvas_index(canvases)
            return built["dims"]

        with (
            mock.patch.object(export, "Values") as values,
            mock.patch.object(export, "role_node"),
            mock.patch.object(export, "canvases_of", return_value=listed),
            mock.patch.object(export, "canvas_index", index),
            mock.patch("manuspectrum.iiif.zones.FeatureRows", return_value=self.rows()),
        ):
            values.return_value.first.return_value = "https://docs.example/m"
            zones = export.analysis_zones(scope)
        self.assertEqual(zones["r"]["canvas"], CANVAS)
        self.assertEqual(zones["r"]["label"], labels[CANVAS])
        self.assertEqual(zones["r"]["shape"], {"type": "point", "x": 160, "y": 320})
        self.assertEqual(self.fetch.call_count, 1)
        self.assertIsNone(built["dims"].unit_used(f"{CANVAS}-b"))
