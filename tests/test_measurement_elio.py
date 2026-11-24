from django.test import SimpleTestCase

from manuspectrum.measurement_files.converters import UnreadableFile
from manuspectrum.measurement_files.converters import elio_mca
from tests.measurement_fixtures import elio_mca as build

COUNTS = [(i * 7) % 50 for i in range(4096)]


class ElioMcaTests(SimpleTestCase):
    def test_calibrated_spectrum(self):
        reading = elio_mca.read(build(COUNTS))
        gain = (22.163 - 8.046) / 1204
        first, last = reading.series.rows[0], reading.series.rows[-1]
        self.assertAlmostEqual(first[0], 8.046 - 722 * gain, delta=1e-12)
        self.assertAlmostEqual(last[0], 8.046 + (4095 - 722) * gain, delta=1e-12)
        self.assertEqual(first[1], COUNTS[0])
        self.assertEqual(last[1], COUNTS[-1])
        self.assertEqual(reading.series.columns, ("energy_keV", "counts"))
        self.assertEqual(reading.content_preset, "xrf")
        self.assertEqual(reading.format, "elio_mca")
        self.assertEqual(reading.warnings, ("date_order_unknown",))
        facts = {f.key: f for f in reading.facts}
        self.assertEqual(
            set(facts),
            {
                "acquired_at",
                "serial_number",
                "tube_anode",
                "tube_voltage",
                "tube_current",
                "measurement_time",
                "live_time",
                "dead_time",
                "channels",
                "calibration",
                "excitation_angle",
                "working_distance",
                "beam_size",
            },
        )
        self.assertEqual(facts["acquired_at"].value, "11/05/2031 09:41:07")
        self.assertEqual(facts["tube_anode"].value, "Ag")
        self.assertEqual(facts["live_time"].value, "118,5")
        self.assertEqual(facts["channels"].value, "4096")
        self.assertEqual(facts["calibration"].value, "722 8,046; 1926 22,163")
        self.assertTrue(all(f.unit is None for f in reading.facts))

    def test_uncalibrated_spectrum(self):
        reading = elio_mca.read(build([1, 2, 3], calibration=((0, "0"), (0, "0"))))
        self.assertEqual(reading.series.columns, ("channel", "counts"))
        self.assertEqual(reading.content_preset, "xrf_channel")
        self.assertIn("no_calibration", reading.warnings)
        self.assertEqual(reading.series.rows[2], (2, 3))
        self.assertNotIn("calibration", {f.key for f in reading.facts})

    def test_crlf_and_lf_read_the_same(self):
        self.assertEqual(
            elio_mca.read(build(COUNTS, crlf=True)), elio_mca.read(build(COUNTS))
        )

    def test_title_is_never_a_fact(self):
        reading = elio_mca.read(build(COUNTS, title="my sample title"))
        self.assertNotIn("my sample title", [f.value for f in reading.facts])

    def test_channel_count_mismatch_is_malformed(self):
        data = build(COUNTS).replace(b"MCA Channels: 4096", b"MCA Channels: 4095")
        with self.assertRaises(UnreadableFile) as caught:
            elio_mca.read(data)
        self.assertEqual(caught.exception.code, "malformed")

    def test_non_integral_count_is_malformed(self):
        data = build([1, 2, 3]).replace(b"2.00000000E+00", b"2.50000000E+00")
        with self.assertRaises(UnreadableFile) as caught:
            elio_mca.read(data)
        self.assertEqual(caught.exception.code, "malformed")

    def test_sniff_needs_hash_and_channels_line(self):
        self.assertTrue(elio_mca.sniff(build([1, 2])[:4096]))
        self.assertFalse(elio_mca.sniff(b"# just a comment\n1\n2\n"))
        self.assertFalse(elio_mca.sniff(b"MCA Channels: 3\n"))


class ElioHardeningTests(SimpleTestCase):
    def refused(self, data):
        with self.assertRaises(UnreadableFile) as caught:
            elio_mca.read(data)
        return caught.exception.code

    def test_three_usable_calibration_points_are_an_unsupported_variant(self):
        data = build([1, 2, 3]).replace(
            b"Calibration3: 0 0", b"Calibration3: 3000 35,5"
        )
        self.assertEqual(self.refused(data), "unsupported_variant")

    def test_a_corrupted_value_is_malformed_never_a_value_error(self):
        base = build([1, 2, 3])
        for name, data in {
            "count line": base.replace(b"1.00000000E+00", b"1.0000x000E+00"),
            "count inf": base.replace(b"1.00000000E+00", b"inf"),
            "count nan": base.replace(b"1.00000000E+00", b"nan"),
            "channels nan": base.replace(b"MCA Channels: 3", b"MCA Channels: nan"),
            "channels inf": base.replace(b"MCA Channels: 3", b"MCA Channels: inf"),
            "channels word": base.replace(b"MCA Channels: 3", b"MCA Channels: many"),
            "calibration word": base.replace(b"722 8,046", b"722 eight"),
        }.items():
            with self.subTest(name):
                self.assertEqual(self.refused(data), "malformed")

    def facts(self, data):
        return {f.key: f.value for f in elio_mca.read(data).facts}

    def test_a_free_text_second_or_third_line_is_not_kept(self):
        data = build([1, 2, 3]).replace(
            b"# 11/05/2031 09:41:07", b"# Operator: Jane Doe"
        )
        data = data.replace(b"# SN000", b"# Notes: sample of the south door, P/N 4")
        facts = self.facts(data)
        self.assertNotIn("acquired_at", facts)
        self.assertNotIn("serial_number", facts)
        self.assertNotIn("Jane", repr(facts))
        self.assertNotIn("door", repr(facts))

    def test_a_date_and_a_serial_with_the_expected_shape_are_kept(self):
        data = build([1, 2, 3]).replace(b"# SN000", b"# AB-12 x_3")
        facts = self.facts(data)
        self.assertEqual(facts["acquired_at"], "11/05/2031 09:41:07")
        self.assertEqual(facts["serial_number"], "AB-12 x_3")

    def test_the_title_line_is_never_a_fact(self):
        data = build([1, 2, 3], title="Operator Jane Doe 11/05/2031 09:41:07")
        self.assertNotIn("Jane", repr(self.facts(data)))
