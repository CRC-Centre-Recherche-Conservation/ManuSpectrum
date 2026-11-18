"""The receiver that stamps annotation zones when their tile is saved, and its deferred resolution.

Usage:
    python manage.py test tests.test_zone_frame_writes --settings=tests.test_settings --noinput
"""

import copy
import uuid
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db import connection
from django.test import override_settings

from arches.app.models.models import IIIFManifest, TileModel
from arches.app.models.tile import Tile

from manuspectrum import signals
from manuspectrum.iiif import frame_writes, frames, units
from manuspectrum.iiif.units import Frame
from manuspectrum.utils.budget import current_budget, upstream_budget
from manuspectrum.utils.cache import stable_cache_key

from tests import test_manifest_registry as reg
from tests.test_iiif_units import answered, info_json

SERVICE = reg.SERVICE
URL = reg.URL
READ = Frame(16, 4913, 6609, "read")


def sized_manifest(width=4000, height=3000):
    manifest = reg.v2_manifest()
    canvas = manifest["sequences"][0]["canvases"][0]
    canvas["width"], canvas["height"] = width, height
    return manifest


def zone(fid, x=0.0, canvas=SERVICE, stamp=None, **props):
    ring = [[x, -1.0], [x + 2.0, -1.0], [x + 2.0, -3.0], [x, -1.0]]
    return {
        "id": fid,
        "type": "Feature",
        "properties": {"manifest": URL, "canvas": canvas, **(stamp or {}), **props},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def props_of(features, fid):
    return next(f for f in features if f["id"] == fid)["properties"]


def remember_info(service=SERVICE, size=(4913, 6609, 512)):
    cache.set(stable_cache_key(units._INFO_PREFIX, service), size, 600)


def in_a_request():
    return mock.patch("manuspectrum.iiif.frames.current_request", return_value=object())


class ZoneFrameCase(reg.AnnotationFixtures):
    def setUp(self):
        super().setUp()
        IIIFManifest.objects.create(url=URL, label="Book", manifest=sized_manifest())
        patcher = mock.patch("manuspectrum.iiif.units.safe_fetch")
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)
        self.fetch.side_effect = AssertionError("no request expected")

    def node(self):
        return str(self.annotation.pk)

    def serialized(self):
        return {
            "nodes": [
                {"nodeid": self.node(), "datatype": "annotation"},
                {
                    "nodeid": str(self.other.pk),
                    "datatype": "geojson-feature-collection",
                },
            ],
            "cards": [],
            "widgets": [],
        }

    def write(self, features, tile_id=None, user=None, trusted=False, request=None):
        """Save the zones as the annotation tile *tile_id* (new when None); callbacks are captured, not run."""
        tile = Tile.objects.filter(pk=tile_id).first() if tile_id else None
        if tile is None:
            tile = Tile(
                tileid=tile_id or uuid.uuid4(),
                resourceinstance_id=self.resource.pk,
                nodegroup_id=self.nodegroup.pk,
                data={self.node(): None, str(self.other.pk): None},
            )
        tile.data[self.node()] = collection(*features)
        tile.serialized_graph = self.serialized()
        guard = mock.patch(
            "manuspectrum.iiif.frames.current_request",
            return_value=None if trusted else (request or object()),
        )
        with guard, self.captureOnCommitCallbacks(execute=False) as callbacks:
            tile.save(index=False, user=user)
        return tile, callbacks

    def stored(self, tile, fid):
        row = TileModel.objects.get(pk=tile.pk)
        return props_of(row.data[self.node()]["features"], fid)

    def stored_provisional(self, tile, user, fid):
        row = TileModel.objects.get(pk=tile.pk)
        value = row.provisionaledits[str(user.pk)]["value"]
        return props_of(value[self.node()]["features"], fid)

    def editor(self, name="editor", group=None):
        user = User.objects.create_user(name, password="pw")
        if group:
            user.groups.add(Group.objects.get(name=group))
        return user


@override_settings(IIIF_IMAGE_INFO_READ=True)
class ReceiverTests(ZoneFrameCase):
    def instance(self, data=None, provisionaledits=None):
        return Tile(
            tileid=uuid.uuid4(),
            resourceinstance_id=self.resource.pk,
            nodegroup_id=self.nodegroup.pk,
            data=data,
            provisionaledits=provisionaledits,
        )

    def test_a_tile_without_annotations_runs_no_query(self):
        instance = self.instance({self.node(): None, str(self.other.pk): {"a": 1}})
        with self.assertNumQueries(0):
            signals.stamp_annotation_frames(Tile, instance)

    def test_sortorder_only_save_runs_no_query(self):
        remember_info()
        instance = self.instance({self.node(): collection(zone("z1"))})
        with self.assertNumQueries(0), in_a_request():
            signals.stamp_annotation_frames(Tile, instance, update_fields=["sortorder"])
        self.assertNotIn(
            "msUnit", props_of(instance.data[self.node()]["features"], "z1")
        )

    def test_new_zone_is_stamped_from_a_known_image(self):
        remember_info()
        tile, callbacks = self.write([zone("z1")])
        self.assertEqual(self.stored(tile, "z1")["msFrame"], "read")
        self.assertEqual(
            {k: v for k, v in self.stored(tile, "z1").items() if k.startswith("ms")},
            READ.stamp(),
        )
        self.fetch.assert_not_called()

    def test_unknown_image_is_stamped_on_commit_when_the_host_answers(self):
        self.fetch.side_effect = [answered(info_json(4913, 6609, 512))]
        tile, callbacks = self.write([zone("z1")])
        self.assertNotIn("msUnit", self.stored(tile, "z1"))
        for callback in callbacks:
            callback()
        self.assertEqual(
            {k: v for k, v in self.stored(tile, "z1").items() if k.startswith("ms")},
            READ.stamp(),
        )

    def test_unknown_image_refused_by_its_host_is_estimated_from_the_registered_manifest(
        self,
    ):
        self.fetch.side_effect = [answered({}, status=403)]
        tile, callbacks = self.write([zone("z1")])
        for callback in callbacks:
            callback()
        stored = self.stored(tile, "z1")
        self.assertEqual(
            {k: v for k, v in stored.items() if k.startswith("ms")},
            {
                "msUnit": 16,
                "msImageWidth": 4000,
                "msImageHeight": 3000,
                "msFrame": "estimated",
            },
        )

    def test_unknown_image_not_reachable_stays_unstamped(self):
        self.fetch.side_effect = [answered({}, status=503)]
        tile, callbacks = self.write([zone("z1")])
        for callback in callbacks:
            callback()
        self.assertNotIn("msUnit", self.stored(tile, "z1"))

    def test_refused_image_of_an_unregistered_manifest_stays_unstamped(self):
        self.fetch.side_effect = [answered({}, status=403)]
        other = "https://elsewhere.example/manifest"
        tile, callbacks = self.write([zone("z1", manifest=other)])
        with mock.patch("manuspectrum.signals.register_annotation_manifests"):
            for callback in callbacks:
                callback()
        self.assertNotIn("msUnit", self.stored(tile, "z1"))

    def test_zone_with_an_invalid_geometry_is_never_scheduled(self):
        bad = zone("z1")
        bad["geometry"]["coordinates"][0][0][0] = True
        with mock.patch.object(frame_writes, "resolve_pending") as resolve:
            tile, callbacks = self.write([bad, zone("z2", x=5.0)])
            for callback in callbacks:
                callback()
        pending = resolve.call_args.args[1]
        self.assertEqual({key[2] for key in pending}, {"z2"})

    def test_unrelated_save_leaves_unstamped_zones_alone(self):
        stamp = READ.stamp()
        old_a = zone("a", x=0.123456789)
        old_b = zone("b", x=5.123456789, stamp=stamp)
        tile, _ = self.write([old_a, old_b], trusted=True)
        remember_info(size=(100, 100, 256))
        rewritten_a = zone("a", x=0.123457)
        rewritten_b = zone("b", x=5.123457, style="red")
        with mock.patch.object(frame_writes, "resolve_pending") as resolve:
            _, callbacks = self.write([rewritten_a, rewritten_b], tile_id=tile.pk)
            for callback in callbacks:
                callback()
        resolve.assert_not_called()
        self.assertNotIn("msUnit", self.stored(tile, "a"))
        self.assertEqual(
            {k: v for k, v in self.stored(tile, "b").items() if k.startswith("ms")},
            stamp,
        )

    def test_first_provisional_edit_and_its_approval_keep_the_stamp(self):
        editor = self.editor()
        reviewer = self.editor("reviewer", "Resource Reviewer")
        remember_info()
        tile, _ = self.write([zone("z1")], user=editor)
        self.assertEqual(self.stored_provisional(tile, editor, "z1")["msFrame"], "read")
        cache.clear()
        approved = zone("z1")
        _, callbacks = self.write([approved], tile_id=tile.pk, user=reviewer)
        self.assertEqual(self.stored(tile, "z1")["msFrame"], "read")
        self.assertEqual(self.stored(tile, "z1")["msUnit"], 16)
        self.fetch.assert_not_called()

    def test_an_existing_stamp_in_data_survives_a_provisional_edit(self):
        editor = self.editor()
        tile, _ = self.write([zone("z1", stamp=READ.stamp())], trusted=True)
        self.write([zone("z1", style="blue")], tile_id=tile.pk, user=editor)
        self.assertEqual(self.stored_provisional(tile, editor, "z1")["msFrame"], "read")
        self.assertEqual(self.stored(tile, "z1")["msFrame"], "read")

    def test_import_outside_a_request_keeps_incoming_stamps_and_schedules_nothing(self):
        stamp = Frame(8, 3000, 2000, "import-legacy").stamp()
        with mock.patch.object(frame_writes, "resolve_pending") as resolve:
            tile, callbacks = self.write(
                [zone("z1", stamp=stamp), zone("z2", x=5.0)], trusted=True
            )
            for callback in callbacks:
                callback()
        resolve.assert_not_called()
        self.assertEqual(self.stored(tile, "z1")["msUnit"], 8)
        self.assertNotIn("msUnit", self.stored(tile, "z2"))

    def test_untrusted_incoming_stamp_is_replaced(self):
        remember_info()
        forged = Frame(2, 10, 10, "browser").stamp()
        tile, _ = self.write([zone("z1", stamp=forged)])
        self.assertEqual(self.stored(tile, "z1")["msFrame"], "read")
        self.assertEqual(self.stored(tile, "z1")["msImageWidth"], 4913)

    def test_raw_save_is_ignored(self):
        remember_info()
        instance = self.instance({self.node(): collection(zone("z1"))})
        with self.assertNumQueries(0), in_a_request():
            signals.stamp_annotation_frames(Tile, instance, raw=True)
        self.assertNotIn(
            "msUnit", props_of(instance.data[self.node()]["features"], "z1")
        )

    def test_raw_save_with_a_stamp_keeps_it_untouched(self):
        remember_info()
        forged = Frame(2, 10, 10, "browser").stamp()
        instance = self.instance({self.node(): collection(zone("z1", stamp=forged))})
        with self.assertNumQueries(0), in_a_request():
            signals.stamp_annotation_frames(Tile, instance, raw=True)
        self.assertEqual(
            props_of(instance.data[self.node()]["features"], "z1")["msUnit"], 2
        )

    def test_the_receiver_stamps_what_a_plain_save_of_the_proxy_and_the_model_write(
        self,
    ):
        remember_info()
        instance = self.instance({self.node(): collection(zone("z1"))})
        with in_a_request():
            signals.stamp_annotation_frames(TileModel, instance)
        self.assertEqual(
            props_of(instance.data[self.node()]["features"], "z1")["msFrame"], "read"
        )

    def test_an_unexpected_shape_is_skipped_not_raised(self):
        instance = self.instance(
            {self.node(): {"type": "FeatureCollection", "features": [3, None, "x"]}},
            provisionaledits={"1": "not a dict", "2": {"value": None}},
        )
        with in_a_request():
            signals.stamp_annotation_frames(Tile, instance)

    def test_the_post_save_receiver_reuses_the_annotation_nodes(self):
        instance = self.instance({self.node(): collection(zone("z1"))})
        instance._ms_annotation_nodes = frozenset({self.node()})
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            with self.assertNumQueries(0):
                signals.register_manifests_of_annotations(Tile, instance)
        self.assertEqual(len(callbacks), 1)

    def test_the_post_save_receiver_looks_the_nodes_up_when_pre_save_did_not(self):
        instance = self.instance({self.node(): collection(zone("z1"))})
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            signals.register_manifests_of_annotations(Tile, instance)
        self.assertEqual(len(callbacks), 1)


FORGED = Frame(2, 10, 10, "browser").stamp()


def bare_zone(fid):
    return {
        "id": fid,
        "type": "Feature",
        "properties": {"canvas": SERVICE},
        "geometry": {"type": "Point", "coordinates": [1.0, -1.0]},
    }


@override_settings(IIIF_IMAGE_INFO_READ=True)
class FailClosedTests(ZoneFrameCase):
    def test_an_unhashable_feature_id_does_not_let_a_forged_stamp_through(self):
        tile, _ = self.write([zone("z1", stamp=FORGED), bare_zone([])])
        self.assertNotIn("msUnit", self.stored(tile, "z1"))

    def test_a_failing_lookup_strips_the_stamps_of_an_untrusted_writer(self):
        with mock.patch.object(units, "known_info", side_effect=RuntimeError("cache")):
            tile, _ = self.write([zone("z1", stamp=FORGED), "junk", {"id": "q"}])
        self.assertNotIn("msUnit", self.stored(tile, "z1"))

    def test_a_failing_lookup_leaves_a_trusted_writers_stamps(self):
        with mock.patch.object(units, "known_info", side_effect=RuntimeError("cache")):
            tile, _ = self.write([zone("z1", stamp=FORGED)], trusted=True)
        self.assertEqual(self.stored(tile, "z1")["msUnit"], 2)


@override_settings(IIIF_IMAGE_INFO_READ=True)
class ScheduleTests(ZoneFrameCase):
    def run_callbacks(self, callbacks):
        for callback in callbacks:
            callback()

    def test_a_refused_host_is_estimated_after_its_manifest_is_registered(self):
        IIIFManifest.objects.filter(url=URL).delete()
        self.fetch.side_effect = [answered({}, status=403)]
        tile, callbacks = self.write([zone("z1")])
        with reg.fetching(sized_manifest()):
            self.run_callbacks(callbacks)
        self.assertEqual(self.stored(tile, "z1")["msFrame"], "estimated")
        self.assertEqual(self.stored(tile, "z1")["msImageWidth"], 4000)

    def test_resource_copy_keeps_the_stamps_it_copies(self):
        request = SimpleNamespace(
            resolver_match=SimpleNamespace(url_name="resource_copy")
        )
        tile, callbacks = self.write([zone("z1", stamp=FORGED)], request=request)
        self.assertEqual(self.stored(tile, "z1")["msUnit"], 2)

    def test_another_route_does_not_keep_incoming_stamps(self):
        request = SimpleNamespace(resolver_match=SimpleNamespace(url_name="tile"))
        tile, _ = self.write([zone("z1", stamp=FORGED)], request=request)
        self.assertNotIn("msUnit", self.stored(tile, "z1"))

    def test_nothing_is_scheduled_outside_a_transaction(self):
        instance = Tile(
            tileid=uuid.uuid4(),
            resourceinstance_id=self.resource.pk,
            nodegroup_id=self.nodegroup.pk,
            data={self.node(): collection(zone("z1"))},
        )
        out = mock.Mock(in_atomic_block=False)
        with (
            in_a_request(),
            mock.patch.object(signals.transaction, "get_connection", return_value=out),
            mock.patch.object(signals.transaction, "on_commit") as on_commit,
        ):
            signals.stamp_annotation_frames(Tile, instance)
        on_commit.assert_not_called()
        self.assertNotIn("_ms_pending_frames", instance.__dict__)

    def test_a_model_saved_directly_goes_through_the_receiver(self):
        remember_info()
        row = TileModel(
            tileid=uuid.uuid4(),
            resourceinstance_id=self.resource.pk,
            nodegroup_id=self.nodegroup.pk,
            data={
                self.node(): collection(
                    zone("z1"), zone("z2", x=5.0, canvas="https://img.example/b")
                )
            },
        )
        self.fetch.side_effect = [answered({}, status=403)]
        with in_a_request(), self.captureOnCommitCallbacks(execute=False) as callbacks:
            row.save()
        stored = TileModel.objects.get(pk=row.pk).data[self.node()]["features"]
        self.assertEqual(props_of(stored, "z1")["msFrame"], "read")
        self.assertEqual(len(callbacks), 1)
        self.run_callbacks(callbacks)
        self.fetch.assert_called_once()


@override_settings(IIIF_IMAGE_INFO_READ=True)
class ResolvePendingTests(ZoneFrameCase):
    def key(self, fid, node=None, user=None):
        return (node or self.node(), user, fid)

    def digest(self, feature):
        return frames.geometry_digest(feature["geometry"])

    def test_resolve_pending_stamps_a_listed_feature(self):
        feature = zone("z1")
        tile, _ = self.write([feature], trusted=True)
        remember_info()
        pending = {self.key("z1"): self.digest(feature)}
        self.assertEqual(frame_writes.resolve_pending(str(tile.pk), pending), 1)
        self.assertEqual(self.stored(tile, "z1")["msFrame"], "read")

    def test_resolve_pending_skips_a_feature_edited_meanwhile(self):
        feature = zone("z1")
        tile, _ = self.write([feature], trusted=True)
        pending = {self.key("z1"): self.digest(feature)}
        self.write([zone("z1", x=9.0)], tile_id=tile.pk, trusted=True)
        remember_info()
        self.assertEqual(frame_writes.resolve_pending(str(tile.pk), pending), 0)
        self.assertNotIn("msUnit", self.stored(tile, "z1"))

    def test_resolve_pending_keeps_a_stamp_written_meanwhile(self):
        feature = zone("z1")
        tile, _ = self.write([feature], trusted=True)
        remember_info()
        pending = {self.key("z1"): self.digest(feature)}
        row = TileModel.objects.get(pk=tile.pk)
        row.data[self.node()]["features"][0]["properties"].update(
            Frame(4, 50, 50, "browser").stamp()
        )
        TileModel.objects.filter(pk=tile.pk).update(data=row.data)
        self.assertEqual(frame_writes.resolve_pending(str(tile.pk), pending), 0)
        self.assertEqual(self.stored(tile, "z1")["msUnit"], 4)

    def test_resolve_pending_stamps_a_provisional_value(self):
        editor = self.editor()
        feature = zone("z1")
        tile, _ = self.write([feature], user=editor)
        remember_info()
        pending = {self.key("z1", user=str(editor.pk)): self.digest(feature)}
        self.assertEqual(frame_writes.resolve_pending(str(tile.pk), pending), 1)
        self.assertEqual(self.stored_provisional(tile, editor, "z1")["msFrame"], "read")

    def test_resolve_pending_on_a_deleted_tile_is_a_no_op(self):
        pending = {self.key("z1"): "digest"}
        self.assertEqual(frame_writes.resolve_pending(str(uuid.uuid4()), pending), 0)

    def test_the_write_uses_the_locked_reread(self):
        feature = zone("z1")
        tile, _ = self.write([feature], trusted=True)
        other = str(self.other.pk)

        def meanwhile(*args, **kwargs):
            row = TileModel.objects.get(pk=tile.pk)
            row.data[other] = {"changed": True}
            TileModel.objects.filter(pk=tile.pk).update(data=row.data)
            return READ

        pending = {self.key("z1"): self.digest(feature)}
        with mock.patch.object(frame_writes, "frame_for_service", meanwhile):
            self.assertEqual(frame_writes.resolve_pending(str(tile.pk), pending), 1)
        row = TileModel.objects.get(pk=tile.pk)
        self.assertEqual(row.data[other], {"changed": True})
        self.assertEqual(self.stored(tile, "z1")["msFrame"], "read")

    def test_the_budget_never_exceeds_an_ambient_one(self):
        feature = zone("z1")
        tile, _ = self.write([feature], trusted=True)
        seen = []

        def spy(*args, **kwargs):
            seen.append(current_budget().left())
            return READ

        pending = {self.key("z1"): self.digest(feature)}
        with mock.patch.object(frame_writes, "frame_for_service", spy):
            with upstream_budget(5):
                frame_writes.resolve_pending(str(tile.pk), pending)
        self.assertLessEqual(seen[0], 5)

    def test_resolve_pending_reads_the_image_before_it_opens_the_transaction(self):
        feature = zone("z1")
        tile, _ = self.write([feature], trusted=True)
        order = []

        def fake(*args, **kwargs):
            order.append("fetch")
            return answered(info_json(4913, 6609, 512))

        self.fetch.side_effect = fake
        real = frame_writes.transaction.atomic

        def spy(*args, **kwargs):
            order.append("atomic")
            return real(*args, **kwargs)

        pending = {self.key("z1"): self.digest(feature)}
        with mock.patch.object(frame_writes.transaction, "atomic", spy):
            frame_writes.resolve_pending(str(tile.pk), pending)
        self.assertEqual(order, ["fetch", "atomic"])


@override_settings(IIIF_IMAGE_INFO_READ=True)
class FrameForServiceTests(ZoneFrameCase):
    def test_a_read_info_gives_a_read_frame(self):
        remember_info()
        self.assertEqual(frame_writes.frame_for_service(SERVICE, URL, SERVICE), READ)

    def test_a_refused_host_gives_an_estimate_from_the_registered_canvas(self):
        self.fetch.side_effect = [answered({}, status=403)]
        frame = frame_writes.frame_for_service(SERVICE, URL, SERVICE)
        self.assertEqual(frame, Frame(16, 4000, 3000, "estimated"))

    def test_the_stored_name_may_be_the_canvas_id(self):
        cache.set(stable_cache_key(units._INFO_PREFIX, SERVICE), False, 600)
        frame = frame_writes.frame_for_service(
            SERVICE, URL, "https://example.org/canvas/1"
        )
        self.assertEqual(frame, Frame(16, 4000, 3000, "estimated"))

    def test_an_unavailable_host_gives_none(self):
        self.fetch.side_effect = [answered({}, status=503)]
        self.assertIsNone(frame_writes.frame_for_service(SERVICE, URL, SERVICE))

    def test_a_refused_host_without_a_known_size_gives_none(self):
        cache.set(stable_cache_key(units._INFO_PREFIX, SERVICE), False, 600)
        for url, name in (
            (None, SERVICE),
            ("https://nowhere.example/m", SERVICE),
            (URL, "https://example.org/unlisted"),
        ):
            with self.subTest(url=url, name=name):
                self.assertIsNone(frame_writes.frame_for_service(SERVICE, url, name))

    def test_a_malformed_registered_manifest_gives_none(self):
        cache.set(stable_cache_key(units._INFO_PREFIX, SERVICE), False, 600)
        with mock.patch.object(frame_writes, "canvases_of", side_effect=AttributeError):
            self.assertIsNone(frame_writes.frame_for_service(SERVICE, URL, SERVICE))

    def test_an_info_that_cannot_make_a_frame_gives_none(self):
        remember_info(size=(2_000_000, 100, 256))
        self.assertIsNone(frame_writes.frame_for_service(SERVICE, URL, SERVICE))

    def test_known_info_reads_the_cache_only(self):
        self.assertIsNone(units.known_info(SERVICE))
        remember_info()
        self.assertEqual(
            units.known_info(f"{SERVICE}/"), units.ImageInfo(4913, 6609, 512)
        )
        cache.set(stable_cache_key(units._INFO_PREFIX, SERVICE), False, 600)
        self.assertIsNone(units.known_info(SERVICE))
        self.fetch.assert_not_called()
