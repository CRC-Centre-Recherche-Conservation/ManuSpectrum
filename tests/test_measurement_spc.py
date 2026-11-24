import struct
from pathlib import Path

from django.test import SimpleTestCase

from manuspectrum.measurement_files.converters import (
    UnreadableFile,
    galactic_spc,
    registry,
)
from tests.measurement_fixtures import FIXTURES, assert_matches
from tests.measurement_fixtures import galactic_spc as synthetic

ALBI = "indores_albi/Raman_Ms29f57v_s1_532_vert2.spc"


def msb_variant():
    data = bytearray(synthetic([1.0, 2.0, 3.0], version=0x4C))
    struct.pack_into(">I", data, 4, 3)
    return bytes(data)


class GalacticSpcTests(SimpleTestCase):
    def test_reads_the_albi_raman_spectrum(self):
        reading = registry.convert((FIXTURES / ALBI).read_bytes())
        self.assertEqual(reading.format, "galactic_spc")
        self.assertEqual(reading.content_preset, "raman")
        assert_matches(self, reading, ALBI)
        facts = {f.key: f for f in reading.facts}
        self.assertEqual(facts["acquired_at"].value, "2016-07-22 13:20")
        self.assertEqual(facts["channels"].value, "1015")
        self.assertEqual(facts["spectral_range"].value, "92.57440948\u20131869.496094")
        self.assertEqual(facts["spectral_range"].unit, "cm-1")
        self.assertNotIn("date_order_unknown", reading.warnings)
        for fact in reading.facts:
            self.assertNotIn("WiRE", fact.value)

    def test_integer_y_is_scaled_and_x_array_is_read(self):
        data = synthetic([4, 2, 1], exp=31, xtype=3, x=[500.0, 510.0, 520.0])
        reading = registry.convert(data)
        self.assertEqual(reading.series.columns, ("wavelength_nm", "intensity"))
        self.assertEqual(
            reading.series.rows, ((500.0, 2.0), (510.0, 1.0), (520.0, 0.5))
        )
        self.assertIsNone(reading.content_preset)

    def test_descending_x_is_reversed(self):
        data = synthetic([1.0, 2.0, 3.0], xtype=1, first=300.0, last=100.0)
        rows = galactic_spc.read(data).series.rows
        self.assertEqual(rows, ((100.0, 3.0), (200.0, 2.0), (300.0, 1.0)))

    def test_log_block_is_never_read(self):
        reading = galactic_spc.read(synthetic([1.0, 2.0, 3.0]))
        for fact in reading.facts:
            self.assertNotIn("private", fact.value)
            self.assertNotIn("invented", fact.value)

    def test_old_format_is_an_unsupported_variant(self):
        data = bytearray(synthetic([1.0, 2.0, 3.0]))
        data[1] = 0x4D
        struct.pack_into("<f", data, 4, 3.0)
        self.assertEqual(registry.detect(bytes(data)), "galactic_spc")
        with self.assertRaises(UnreadableFile) as caught:
            registry.convert(bytes(data))
        self.assertEqual(caught.exception.code, "unsupported_variant")

    def test_multifile_and_xyxy_are_unsupported_variants(self):
        for data in (
            synthetic([1.0, 2.0, 3.0], nsub=2),
            synthetic([1.0, 2.0, 3.0], flags=0x40),
            synthetic([1.0, 2.0, 3.0], flags=0x01),
            msb_variant(),
        ):
            with self.assertRaises(UnreadableFile) as caught:
                registry.convert(data)
            self.assertEqual(caught.exception.code, "unsupported_variant")

    def test_truncated_and_flat_axis_are_unreadable(self):
        data = synthetic([1.0, 2.0, 3.0, 4.0])
        cases = {
            "truncated": data[:550],
            "too_few_points": synthetic([1.0]),
            "duplicate_x": synthetic([1.0, 2.0], first=5.0, last=5.0),
            "non_finite": synthetic([1.0, float("nan"), 3.0]),
        }
        for code, blob in cases.items():
            with self.assertRaises(UnreadableFile) as caught:
                galactic_spc.read(blob)
            self.assertEqual(caught.exception.code, code, code)

    def test_text_starting_with_K_is_not_spc(self):
        self.assertFalse(galactic_spc.sniff(b"OK 1 2\n"))
        self.assertFalse(galactic_spc.sniff(b"OK 1 2\n" * 200))
        self.assertNotEqual(registry.detect(b"OK 1 2\n"), "galactic_spc")
