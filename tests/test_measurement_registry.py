import random
from pathlib import Path

from django.test import SimpleTestCase

from manuspectrum.measurement_files.converters import (
    UnreadableFile,
    UnsupportedFormat,
    registry,
)
from manuspectrum.measurement_files.converters.base import Reading
from tests.measurement_fixtures import elio_mca

FIXTURES = Path(__file__).parent / "fixtures" / "measurement_files"


class RegistryTests(SimpleTestCase):
    def test_detects_by_content_only(self):
        self.assertEqual(registry.detect(elio_mca([1, 2, 3])), "elio_mca")
        self.assertEqual(registry.convert(elio_mca([1, 2, 3])).format, "elio_mca")
        with self.assertRaises(UnsupportedFormat) as caught:
            registry.convert(b"junk\n<<PMCA SPECTRUM>>\nTAG - x\n")
        self.assertEqual(caught.exception.format, "amptek_mca")
        with self.assertRaises(UnsupportedFormat) as caught:
            registry.convert(b"WDF1" + bytes(64))
        self.assertEqual(caught.exception.format, "renishaw_wdf")
        with self.assertRaises(UnsupportedFormat) as caught:
            registry.convert(b"")
        self.assertIsNone(caught.exception.format)

    def test_declared_size_is_bounded(self):
        data = elio_mca([1, 2, 3]).replace(
            b"MCA Channels: 3", b"MCA Channels: 1000000000"
        )
        with self.assertRaises(UnreadableFile) as caught:
            registry.convert(data)
        self.assertEqual(caught.exception.code, "malformed")

    def test_unexpected_exception_becomes_malformed(self):
        class Boom:
            FORMAT = "boom"
            READER_VERSION = 1

            @staticmethod
            def sniff(head):
                return True

            @staticmethod
            def read(data):
                raise RuntimeError("secret file content")

        original = registry.READERS
        registry.READERS = (Boom,)
        try:
            with self.assertLogs(registry.logger, "WARNING") as logs:
                with self.assertRaises(UnreadableFile) as caught:
                    registry.convert(b"x")
        finally:
            registry.READERS = original
        self.assertEqual(caught.exception.code, "malformed")
        self.assertIn("RuntimeError", logs.output[0])
        self.assertNotIn("secret", logs.output[0])

    def test_only_typed_errors_escape(self):
        samples = sorted(FIXTURES.rglob("*"))
        corpus = [
            p.read_bytes()
            for p in samples
            if p.is_file() and p.suffix not in (".md", ".json", ".py")
        ]
        corpus.append(elio_mca([(i * 7) % 50 for i in range(300)]))
        rng = random.Random(20261124)
        for data in corpus:
            variants = [data[: len(data) * k // 10] for k in range(10)]
            for _ in range(20):
                flipped = bytearray(data)
                flipped[rng.randrange(len(flipped))] = rng.randrange(256)
                variants.append(bytes(flipped))
            for variant in variants:
                try:
                    result = registry.convert(variant)
                except (UnreadableFile, UnsupportedFormat):
                    continue
                self.assertIsInstance(result, Reading)
