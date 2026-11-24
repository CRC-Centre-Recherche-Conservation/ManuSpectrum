import struct

from django.test import SimpleTestCase

from manuspectrum.measurement_files.converters import UnreadableFile, asd, registry
from tests.measurement_fixtures import FIXTURES, assert_matches

SOIL = "asdreader/soil.asd"
CHANNELS = 2151
REFERENCE_HEADER = 484 + CHANNELS * 8


def soil() -> bytearray:
    return bytearray((FIXTURES / SOIL).read_bytes())


class AsdTests(SimpleTestCase):
    def test_reads_the_asdreader_soil_file(self):
        reading = registry.convert(bytes(soil()))
        self.assertEqual(reading.format, "asd")
        self.assertEqual(reading.content_preset, "fors")
        self.assertEqual(reading.warnings, ("detector_jumps_uncorrected",))
        assert_matches(self, reading, SOIL)
        self.assertEqual(len(reading.series.rows), 2151)
        self.assertEqual(reading.series.rows[0][0], 350.0)
        self.assertEqual(reading.series.rows[-1][0], 2500.0)
        facts = {f.key: f for f in reading.facts}
        self.assertEqual(facts["instrument"].value, "FieldSpec FR")
        self.assertEqual(facts["serial_number"].value, "16401")
        self.assertEqual(facts["integration_time"].value, "9")
        self.assertEqual(facts["integration_time"].unit, "ms")
        self.assertEqual(facts["averages"].value, "50")
        self.assertEqual(facts["dark_scans"].value, "50")
        self.assertEqual(facts["reference_scans"].value, "50")
        self.assertEqual(facts["detector_gains"].value, "921; 2220")
        self.assertEqual(facts["acquired_at"].value, "2015-08-11 16:01:08")
        self.assertIsNone(facts["acquired_at"].unit)
        self.assertEqual(facts["reference_acquired_at"].value, "2015-08-11 15:53:36")
        self.assertEqual(facts["channels"].value, "2151")
        self.assertEqual(facts["spectral_range"].value, "350–2500")
        self.assertEqual(facts["spectral_range"].unit, "nm")

    def test_comment_and_reference_description_are_never_copied(self):
        data = soil()
        data[3:160] = b"invented comment".ljust(157, b"\x00")
        description = b"invented description"
        tail = bytes(data[REFERENCE_HEADER + 20 :])
        data[REFERENCE_HEADER + 18 :] = struct.pack("<h", len(description))
        data += description + tail
        reading = registry.convert(bytes(data))
        self.assertEqual(len(reading.series.rows), CHANNELS)
        for fact in reading.facts:
            self.assertNotIn("invented", fact.value)

    def test_reflectance_file_is_unsupported(self):
        data = soil()
        data[186] = 1
        self.assertEqual(registry.detect(bytes(data)), "asd")
        with self.assertRaises(UnreadableFile) as caught:
            registry.convert(bytes(data))
        self.assertEqual(caught.exception.code, "unsupported_variant")

    def test_missing_white_reference_is_unsupported(self):
        data = soil()
        data[REFERENCE_HEADER : REFERENCE_HEADER + 2] = b"\x00\x00"
        with self.assertRaises(UnreadableFile) as caught:
            registry.convert(bytes(data))
        self.assertEqual(caught.exception.code, "unsupported_variant")

    def test_truncated_reference_is_truncated(self):
        data = bytes(soil())
        for size in (100, 484 + 100, REFERENCE_HEADER + 10, len(data) - 8000 - 1):
            with self.assertRaises(UnreadableFile) as caught:
                registry.convert(data[:size])
            self.assertEqual(caught.exception.code, "truncated", size)

    def test_int32_and_float32_spectra_are_read(self):
        base = soil()
        reference = bytes(base[REFERENCE_HEADER:])
        target = struct.unpack_from(f"<{CHANNELS}d", base, 484)
        for code, fmt, values in (
            (0, "f", target),
            (1, "i", [round(v) for v in target]),
        ):
            data = bytearray(base[:484])
            data[199] = code
            data += struct.pack(f"<{CHANNELS}{fmt}", *values) + reference
            rows = registry.convert(bytes(data)).series.rows
            self.assertEqual(len(rows), CHANNELS)
            self.assertAlmostEqual(rows[10][1], values[10], places=3)
            self.assertAlmostEqual(
                rows[10][2], struct.unpack_from("<d", reference, 20 + 80)[0]
            )

    def test_unknown_data_format_and_flat_axis_are_unreadable(self):
        data = soil()
        data[199] = 7
        with self.assertRaises(UnreadableFile) as caught:
            asd.read(bytes(data))
        self.assertEqual(caught.exception.code, "unsupported_variant")
        data = soil()
        struct.pack_into("<f", data, 195, 0.0)
        with self.assertRaises(UnreadableFile) as caught:
            asd.read(bytes(data))
        self.assertEqual(caught.exception.code, "malformed")

    def test_sniff_requires_the_version_digit(self):
        self.assertTrue(asd.sniff(b"as8" + bytes(100)))
        self.assertFalse(asd.sniff(b"as9"))
        self.assertFalse(asd.sniff(b"as"))
