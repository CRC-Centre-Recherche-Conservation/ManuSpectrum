import random
from pathlib import Path

from django.test import SimpleTestCase

from manuspectrum.measurement_files.converters import (
    UnreadableFile,
    UnsupportedFormat,
    registry,
)
from manuspectrum.measurement_files.converters.base import Reading
from manuspectrum.measurement_files.converters.csv_writer import write_csv
from tests.measurement_fixtures import elio_mca
from tests.test_measurement_mzxml import document as mzxml_document
from tests.test_measurement_mzxml import peaks as mzxml_peaks
from tests.test_measurement_spx import synthetic as spx

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
        self.assertEqual(caught.exception.code, "too_large")

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

    def test_a_typed_unsupported_format_from_a_reader_is_kept(self):
        class Refuses:
            FORMAT = "refuses"
            READER_VERSION = 1

            @staticmethod
            def sniff(head):
                return True

            @staticmethod
            def read(data):
                raise UnsupportedFormat("refuses")

        original = registry.READERS
        registry.READERS = (Refuses,)
        try:
            with self.assertNoLogs(registry.logger, "WARNING"):
                with self.assertRaises(UnsupportedFormat) as caught:
                    registry.convert(b"x")
        finally:
            registry.READERS = original
        self.assertEqual(caught.exception.format, "refuses")

    def test_unreadable_file_refuses_an_unknown_code(self):
        with self.assertRaises(ValueError):
            UnreadableFile("not_a_code")
        self.assertEqual(UnreadableFile("truncated", "asd").format, "asd")

    def test_only_typed_errors_escape(self):
        samples = sorted(FIXTURES.rglob("*"))
        corpus = [
            p.read_bytes()
            for p in samples
            if p.is_file()
            and p.stat().st_size
            and p.suffix not in (".md", ".json", ".py")
        ]
        corpus.append(elio_mca([(i * 7) % 50 for i in range(300)]))
        readers = {r.FORMAT: r for r in (*registry.READERS, registry.FALLBACK)}
        rng = random.Random(20261124)
        for data in corpus:
            variants = [data[: len(data) * k // 10] for k in range(10)]
            for _ in range(20):
                flipped = bytearray(data)
                flipped[rng.randrange(len(flipped))] = rng.randrange(256)
                variants.append(bytes(flipped))
            for variant in variants:
                name = registry.detect(variant)
                if name in readers:
                    try:
                        readers[name].read(variant)
                    except (UnreadableFile, UnsupportedFormat):
                        pass
                with self.assertNoLogs(registry.logger, "WARNING"):
                    try:
                        result = registry.convert(variant)
                    except (UnreadableFile, UnsupportedFormat):
                        continue
                self.assertIsInstance(result, Reading)
                if result.series is not None:
                    write_csv(result.series)

    def test_a_series_a_reader_returns_is_always_writable(self):
        elio_decreasing = elio_mca(
            [1, 2, 3], calibration=((722, "22,163"), (1926, "8,046"))
        )
        crafted = {
            "elio one channel": (elio_mca([5]), "too_few_points"),
            "elio decreasing calibration": (elio_decreasing, "malformed"),
            "elio nan calibration": (
                elio_mca([1, 2, 3], calibration=((722, "nan"), (1926, "22,163"))),
                "non_finite",
            ),
            "spx one channel": (spx(channels="5", count=1), "too_few_points"),
            "spx negative CalibLin": (spx(calib_lin="-0,5"), "malformed"),
            "spx nan CalibLin": (spx(calib_lin="nan"), "non_finite"),
            "spx inf CalibLin": (spx(calib_lin="inf"), "non_finite"),
            "mzxml one peak": (
                mzxml_document(mzxml_peaks([100.5], [2.0])),
                "too_few_points",
            ),
        }
        for name, (data, code) in crafted.items():
            with self.subTest(name):
                with self.assertRaises(UnreadableFile) as caught:
                    registry.convert(data)
                self.assertEqual(caught.exception.code, code)

    def test_an_unreadable_file_carries_its_detected_format(self):
        cases = {
            "elio_mca": elio_mca([5]),
            "bruker_spx": spx(channels="5", count=1),
            "mzxml": mzxml_document(mzxml_peaks([100.5], [2.0])),
        }
        for name, data in cases.items():
            with self.subTest(name):
                with self.assertRaises(UnreadableFile) as caught:
                    registry.convert(data)
                self.assertEqual(caught.exception.format, name)
        with self.assertRaises(UnreadableFile) as caught:
            registry.convert(
                elio_mca([1, 2, 3]).replace(b"MCA Channels: 3", b"MCA Channels: 9")
            )
        self.assertEqual(
            (caught.exception.code, caught.exception.format), ("malformed", "elio_mca")
        )

    def test_a_format_the_reader_set_is_kept(self):
        class Named:
            FORMAT = "named"
            READER_VERSION = 1

            @staticmethod
            def sniff(head):
                return True

            @staticmethod
            def read(data):
                raise UnreadableFile("malformed", format="inner")

        original = registry.READERS
        registry.READERS = (Named,)
        try:
            with self.assertRaises(UnreadableFile) as caught:
                registry.convert(b"x")
        finally:
            registry.READERS = original
        self.assertEqual(caught.exception.format, "inner")

    def test_a_reader_failure_carries_the_format_too(self):
        class Boom:
            FORMAT = "boom"
            READER_VERSION = 1

            @staticmethod
            def sniff(head):
                return True

            @staticmethod
            def read(data):
                raise RuntimeError("x")

        original = registry.READERS
        registry.READERS = (Boom,)
        try:
            with self.assertLogs(registry.logger, "WARNING"):
                with self.assertRaises(UnreadableFile) as caught:
                    registry.convert(b"x")
        finally:
            registry.READERS = original
        self.assertEqual(caught.exception.format, "boom")

    def test_text_that_is_not_a_measurement_is_unsupported(self):
        texts = {
            "json": b'{"name": "x", "values": [1, 2, 3], "ok": true}\n',
            "html": b"<html><body><h1>Report 2031</h1><p>Hello</p></body></html>\n",
            "xml": b'<?xml version="1.0"?><doc><item id="1">a</item></doc>\n',
            "readme": b"This folder holds the raw files.\nOne per sample.\n",
            "one column": b"1\n2\n3\n4\n5\n6\n",
        }
        for name, data in texts.items():
            with self.subTest(name):
                with self.assertRaises(UnsupportedFormat) as caught:
                    registry.convert(data)
                self.assertIsNone(caught.exception.format)
