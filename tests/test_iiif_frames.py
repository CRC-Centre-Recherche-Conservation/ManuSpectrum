"""Image frames of annotation zones: the stamp, its validity and the stamping rule.

Usage:
    python manage.py test tests.test_iiif_frames --settings=tests.test_settings
"""

import copy

from django.test import SimpleTestCase, override_settings

from manuspectrum.iiif import frames
from manuspectrum.iiif.units import (
    Frame,
    ImageInfo,
    ZoneUnit,
    frame_assumed,
    frame_from_info,
    unit_of_frame,
)

NODE = "node-1"
CANVAS = "https://img/iiif/2/a/"
SERVICE = "https://img/iiif/2/a"
POLY = {"type": "Polygon", "coordinates": [[[1.0, 2.0], [3.0, 2.0], [3.0, 4.0]]]}


def stamp(unit=16, width=4913, height=6609, source="read"):
    return {
        "msUnit": unit,
        "msImageWidth": width,
        "msImageHeight": height,
        "msFrame": source,
    }


def feature(fid="f1", geometry=POLY, canvas=CANVAS, **extra):
    return {
        "id": fid,
        "type": "Feature",
        "properties": {"canvas": canvas, **extra},
        "geometry": copy.deepcopy(geometry),
    }


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def previous_of(*features, provisional=()):
    data = {NODE: collection(*features)}
    edits = {
        f"user{i}": {"value": {NODE: collection(f)}} for i, f in enumerate(provisional)
    }
    return frames.PreviousFeatures(data, edits)


class Calls:
    def __init__(self, frame=Frame(16, 100, 100, "browser")):
        self.frame = frame
        self.services = []

    def __call__(self, service):
        self.services.append(service)
        return self.frame


class FrameOfTests(SimpleTestCase):
    def test_frame_of_reads_a_valid_stamp(self):
        self.assertEqual(
            frames.frame_of(feature(**stamp())), Frame(16, 4913, 6609, "read")
        )

    def test_frame_of_rejects_partial_or_invalid_stamps(self):
        bad = [
            {k: v for k, v in stamp().items() if k != "msImageWidth"},
            stamp(unit=12),
            stamp(unit=0),
            stamp(unit=True),
            stamp(unit="16"),
            stamp(unit=16.5),
            stamp(width=0),
            stamp(source="guess"),
        ]
        for properties in bad:
            with self.subTest(properties=properties):
                self.assertIsNone(frames.frame_of(feature(**properties)))

    def test_same_geometry_ignores_float_noise(self):
        def point(x):
            return {"type": "Point", "coordinates": [x, 1]}

        self.assertTrue(
            frames.same_geometry(point(307.06250000000006), point(307.0625))
        )
        self.assertFalse(frames.same_geometry(point(307.0625), point(307.0626)))

    def test_geometry_digest_ignores_noise_below_1e6(self):
        a = {"type": "Point", "coordinates": [307.0625, 1]}
        b = {"type": "Point", "coordinates": [307.06250000000006, 1]}
        c = {"type": "Point", "coordinates": [307.0626, 1]}
        self.assertEqual(frames.geometry_digest(a), frames.geometry_digest(b))
        self.assertNotEqual(frames.geometry_digest(a), frames.geometry_digest(c))


class StampTests(SimpleTestCase):
    def run_rule(self, new, previous, frame_for, trusted=False):
        return frames.stamp_collection(new, previous, NODE, frame_for, trusted)

    def test_new_feature_is_stamped_with_its_service_frame(self):
        frame_for = Calls(Frame(16, 100, 200, "browser"))
        out, todo = self.run_rule(
            collection(feature(msUnit=64)), previous_of(), frame_for
        )
        self.assertEqual(frame_for.services, [SERVICE])
        self.assertEqual(todo, {})
        props = out["features"][0]["properties"]
        self.assertEqual(props["msUnit"], 16)
        self.assertEqual(props["msFrame"], "browser")
        self.assertEqual(props["canvas"], CANVAS)

    def test_matched_stamped_feature_keeps_its_stamp_over_client_values(self):
        frame_for = Calls(Frame(16, 1, 1, "browser"))
        before = previous_of(feature(**stamp(unit=32)))
        out, todo = self.run_rule(
            collection(feature(**stamp(unit=64))), before, frame_for
        )
        self.assertEqual(out["features"][0]["properties"]["msUnit"], 32)
        self.assertEqual(frame_for.services, [])
        self.assertEqual(todo, {})

    def test_matched_unstamped_feature_stays_unstamped(self):
        frame_for = Calls()
        out, todo = self.run_rule(
            collection(feature(**stamp())), previous_of(feature()), frame_for
        )
        props = out["features"][0]["properties"]
        self.assertFalse(set(props) & set(frames.STAMP_KEYS))
        self.assertEqual(frame_for.services, [])
        self.assertEqual(todo, {})

    def test_stamp_found_in_a_previous_provisional_value_is_kept(self):
        frame_for = Calls()
        before = previous_of(provisional=[feature(**stamp(unit=8))])
        out, _ = self.run_rule(collection(feature()), before, frame_for)
        self.assertEqual(out["features"][0]["properties"]["msUnit"], 8)
        self.assertEqual(frame_for.services, [])

    def test_moved_geometry_and_moved_canvas_are_restamped(self):
        moved = {"type": "Polygon", "coordinates": [[[9.0, 9.0], [8.0, 9.0]]]}
        before = previous_of(feature(**stamp(unit=32)))
        for new in (
            feature(geometry=moved),
            feature(canvas="https://img/iiif/2/b/"),
        ):
            with self.subTest(new=new):
                frame_for = Calls(Frame(16, 1, 1, "browser"))
                out, _ = self.run_rule(collection(new), before, frame_for)
                self.assertEqual(out["features"][0]["properties"]["msUnit"], 16)
                self.assertEqual(len(frame_for.services), 1)

    def test_trusted_writer_keeps_an_incoming_stamp_and_schedules_nothing(self):
        frame_for = Calls()
        out, todo = self.run_rule(
            collection(feature(**stamp(unit=64))), previous_of(), frame_for, True
        )
        self.assertEqual(out["features"][0]["properties"]["msUnit"], 64)
        self.assertEqual(todo, {})
        self.assertEqual(frame_for.services, [])

    def test_untrusted_incoming_stamp_on_a_new_feature_is_replaced(self):
        frame_for = Calls(Frame(16, 1, 1, "browser"))
        out, _ = self.run_rule(
            collection(feature(**stamp(unit=64))), previous_of(), frame_for
        )
        self.assertEqual(out["features"][0]["properties"]["msUnit"], 16)

    def test_unknown_service_is_listed_for_resolution(self):
        out, todo = self.run_rule(
            collection(feature(**stamp(unit=64))), previous_of(), lambda s: None
        )
        self.assertEqual(todo, {"f1": SERVICE})
        self.assertFalse(set(out["features"][0]["properties"]) & set(frames.STAMP_KEYS))

    def test_inputs_are_not_mutated(self):
        new = collection(feature(**stamp(unit=64)))
        snapshot = copy.deepcopy(new)
        self.run_rule(new, previous_of(), Calls())
        self.assertEqual(new, snapshot)

    def test_empty_collection_passes_through(self):
        self.assertEqual(self.run_rule(None, previous_of(), Calls()), (None, {}))


class TrustTests(SimpleTestCase):
    def test_trusted_writes_context(self):
        from manuspectrum.accounts import lockout

        token = lockout._current_request.set(object())
        try:
            self.assertFalse(frames.is_trusted())
            with frames.trusted_writes():
                self.assertTrue(frames.is_trusted())
            self.assertFalse(frames.is_trusted())
        finally:
            lockout._current_request.reset(token)

    def test_no_request_is_trusted(self):
        self.assertTrue(frames.is_trusted())


class FrameHelperTests(SimpleTestCase):
    def test_frame_helpers(self):
        self.assertEqual(
            frame_from_info(ImageInfo(4913, 6609, 512)),
            Frame(16, 4913, 6609, "read"),
        )
        with override_settings(IIIF_IMAGE_TILE_HINTS={}):
            assumed = frame_assumed("https://gallica.bnf.fr/iiif/ark:/x/f1", 4442, 5864)
        self.assertEqual(assumed, Frame(32, 4442, 5864, "estimated"))
        self.assertFalse(assumed.measured)
        self.assertTrue(Frame(16, 1, 1, "read").measured)
        self.assertEqual(
            unit_of_frame(Frame(16, 4912, 6608, "read"), 2456, 3304),
            ZoneUnit(8.0, 8.0, True, 2456, 3304),
        )
        self.assertFalse(unit_of_frame(assumed, 2221, 2932).read)

    def test_unit_of_frame_without_canvas_size_uses_the_frame_size(self):
        self.assertEqual(
            unit_of_frame(Frame(16, 100, 200, "browser"), 0, None),
            ZoneUnit(16.0, 16.0, True, 100, 200),
        )

    def test_stamp_round_trips(self):
        frame = Frame(16, 10, 20, "import-legacy")
        self.assertEqual(frames.frame_of({"properties": frame.stamp()}), frame)


def point(*coordinates):
    return {"type": "Point", "coordinates": list(coordinates)}


class LeafletRoundTests(SimpleTestCase):
    def test_leaflet_round_rounds_halves_up_like_format_num(self):
        self.assertEqual(frames.leaflet_round(0.0078125), 0.007813)
        self.assertEqual(frames.leaflet_round(-0.0), 0.0)
        self.assertEqual(str(frames.leaflet_round(-1e-7)), "0.0")
        self.assertEqual(frames.leaflet_round(3), 3.0)

    def test_leaflet_round_refuses_non_coordinates(self):
        for bad in (True, float("nan"), float("inf"), 1e308, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    frames.leaflet_round(bad)

    def test_client_leaflet_rounding_of_a_stored_coordinate_still_matches(self):
        stored = feature(geometry=point(0.0078125, 1), **stamp(unit=32))
        sent = feature(geometry=point(0.007813, 1), **stamp(unit=64))
        out, _ = frames.stamp_collection(
            collection(sent), previous_of(stored), NODE, Calls(), False
        )
        self.assertEqual(out["features"][0]["properties"]["msUnit"], 32)

    def test_digest_agrees_with_same_geometry(self):
        pairs = [
            (point(1, 2), point(1.0, 2.0)),
            (point(-1e-7, 0), point(0, 0)),
            (point(0.0078125), point(0.007813)),
        ]
        for a, b in pairs:
            with self.subTest(a=a, b=b):
                self.assertTrue(frames.same_geometry(a, b))
                self.assertEqual(frames.geometry_digest(a), frames.geometry_digest(b))

    def test_invalid_coordinates_equal_nothing(self):
        for bad in (
            point(float("nan"), 1),
            point(float("inf"), 1),
            point(True, 1),
        ):
            with self.subTest(bad=bad):
                self.assertFalse(frames.same_geometry(bad, bad))
                self.assertNotEqual(
                    frames.geometry_digest(bad), frames.geometry_digest(point(1, 1))
                )


class FrameBoundsTests(SimpleTestCase):
    def test_frame_refuses_invalid_values(self):
        for args in (
            (12, 10, 10, "read"),
            (0, 10, 10, "read"),
            (True, 10, 10, "read"),
            (2**21, 10, 10, "read"),
            (16, 0, 10, "read"),
            (16, 10, 1_000_001, "read"),
            (16, 10.0, 10, "read"),
            (16, 10, 10, "guess"),
        ):
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    Frame(*args)

    def test_frame_of_applies_the_same_bounds(self):
        self.assertIsNone(frames.frame_of(feature(**stamp(unit=2**1100))))
        self.assertIsNone(frames.frame_of(feature(**stamp(height=1_000_001))))

    def test_helpers_fail_loudly_on_a_bad_size(self):
        with self.assertRaises(ValueError):
            frame_from_info(ImageInfo(0, 10, 256))
        with self.assertRaises(ValueError):
            frame_assumed("https://img/a", 10, 2_000_000)


class FeatureIdTests(SimpleTestCase):
    def run_rule(self, new, previous):
        return frames.stamp_collection(new, previous, NODE, Calls(), False)

    def test_feature_without_a_usable_id_is_neither_stamped_nor_listed(self):
        for fid in (None, ["a"], {"a": 1}, True):
            with self.subTest(fid=fid):
                new = feature(**stamp(unit=64))
                new["id"] = fid
                out, todo = self.run_rule(collection(new), previous_of())
                self.assertEqual(todo, {})
                self.assertFalse(
                    set(out["features"][0]["properties"]) & set(frames.STAMP_KEYS)
                )

    def test_stored_feature_with_a_list_id_does_not_break_a_save(self):
        stored = feature(**stamp())
        stored["id"] = ["x"]
        out, todo = self.run_rule(collection(feature()), previous_of(stored))
        self.assertEqual(todo, {})
        self.assertEqual(out["features"][0]["properties"]["msUnit"], 16)


class ReviewFocusTests(SimpleTestCase):
    def test_unrelated_save_keeps_the_untouched_features_as_they_were(self):
        stamped = feature("a", point(0.0078125, 1), **stamp(unit=32))
        bare = feature("b", point(5, 5))
        before = previous_of(stamped, bare)
        sent = collection(
            feature("a", point(0.007813, 1), **stamp(unit=64)),
            feature("b", point(5.0000000001, 5), **stamp(unit=64)),
            feature("c", point(9, 9)),
        )
        out, _ = frames.stamp_collection(sent, before, NODE, Calls(), False)
        units = [f["properties"].get("msUnit") for f in out["features"]]
        self.assertEqual(units, [32, None, 16])

    def test_a_stamped_candidate_wins_over_an_unstamped_one(self):
        before = previous_of(feature(), provisional=[feature(**stamp(unit=8))])
        out, _ = frames.stamp_collection(
            collection(feature()), before, NODE, Calls(), False
        )
        self.assertEqual(out["features"][0]["properties"]["msUnit"], 8)

    def test_trusted_writer_without_a_stamp_asks_the_frame_and_schedules_nothing(self):
        frame_for = Calls()
        out, todo = frames.stamp_collection(
            collection(feature()), previous_of(), NODE, frame_for, True
        )
        self.assertEqual(frame_for.services, [SERVICE])
        self.assertEqual(todo, {})
        self.assertEqual(out["features"][0]["properties"]["msUnit"], 16)
        out, todo = frames.stamp_collection(
            collection(feature()), previous_of(), NODE, lambda s: None, True
        )
        self.assertEqual(todo, {})

    def test_two_features_of_one_canvas_keep_their_own_stamps(self):
        before = previous_of(
            feature("a", point(1, 1), **stamp(unit=8)),
            feature("b", point(2, 2), **stamp(unit=32)),
        )
        out, _ = frames.stamp_collection(
            collection(feature("a", point(1, 1)), feature("b", point(2, 2))),
            before,
            NODE,
            Calls(),
            False,
        )
        self.assertEqual([f["properties"]["msUnit"] for f in out["features"]], [8, 32])


class TrustedIdlessTests(SimpleTestCase):
    def test_trusted_keeps_a_valid_stamp_on_an_idless_feature_untrusted_strips_it(self):
        new = feature(**stamp(unit=64))
        del new["id"]
        for trusted, expected in ((True, 64), (False, None)):
            with self.subTest(trusted=trusted):
                out, todo = frames.stamp_collection(
                    collection(new), previous_of(), NODE, Calls(), trusted
                )
                self.assertEqual(todo, {})
                self.assertEqual(
                    out["features"][0]["properties"].get("msUnit"), expected
                )
