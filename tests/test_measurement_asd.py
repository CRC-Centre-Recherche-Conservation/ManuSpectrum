import struct
from unittest import mock

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


class AsdRefusalTests(SimpleTestCase):
    def assert_refused(self, data, code):
        with self.assertRaises(UnreadableFile) as caught:
            registry.convert(bytes(data))
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.format, "asd")

    def test_other_file_versions_are_unsupported(self):
        data = soil()
        data[2] = ord("7")
        self.assert_refused(data, "unsupported_variant")

    def test_channel_count_above_the_limit_is_too_large(self):
        data = soil()
        struct.pack_into("<H", data, 204, 65535)
        with mock.patch.object(asd, "MAX_CHANNELS", 1000):
            with self.assertRaises(UnreadableFile) as caught:
                asd.read(bytes(data))
        self.assertEqual(caught.exception.code, "too_large")

    def test_non_finite_first_wavelength_is_malformed(self):
        data = soil()
        struct.pack_into("<f", data, 191, float("nan"))
        self.assert_refused(data, "malformed")

    def test_single_channel_has_too_few_points(self):
        data = soil()
        struct.pack_into("<H", data, 204, 1)
        self.assert_refused(data, "too_few_points")

    def test_unknown_reference_flag_is_malformed(self):
        data = soil()
        data[REFERENCE_HEADER : REFERENCE_HEADER + 2] = b"\x01\x02"
        self.assert_refused(data, "malformed")

    def test_negative_description_length_is_malformed(self):
        data = soil()
        struct.pack_into("<h", data, REFERENCE_HEADER + 18, -1)
        self.assert_refused(data, "malformed")

    def test_non_finite_spectrum_value_is_refused(self):
        data = soil()
        struct.pack_into("<d", data, 484 + 8 * 5, float("inf"))
        self.assert_refused(data, "non_finite")

    def test_unrepresentable_acquisition_dates_are_left_out(self):
        for value in (float("nan"), 1e300):
            data = soil()
            struct.pack_into("<d", data, REFERENCE_HEADER + 2, value)
            struct.pack_into("<d", data, REFERENCE_HEADER + 10, value)
            reading = registry.convert(bytes(data))
            keys = {f.key for f in reading.facts}
            self.assertNotIn("acquired_at", keys, value)
            self.assertNotIn("reference_acquired_at", keys, value)
            self.assertIn("integration_time", keys)
