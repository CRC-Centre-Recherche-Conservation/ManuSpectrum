"""Frames files and the stamped zones of the ``annotation_frames`` verbs.

Usage:
    python manage.py test tests.test_annotation_frames_verify --settings=tests.test_settings --noinput
"""

import json
import os
import tempfile

from django.test import SimpleTestCase

from manuspectrum.iiif import frame_scope
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
