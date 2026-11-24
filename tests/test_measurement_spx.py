import xml.etree.ElementTree as ET
from pathlib import Path

from django.test import SimpleTestCase

from manuspectrum.measurement_files.converters import UnreadableFile, bruker_spx
from manuspectrum.measurement_files.converters.registry import convert, detect

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "measurement_files"
    / "indores_albi"
    / "X16_parchment.spx"
)


def synthetic(*, channels="1,2,3,4", count=4, calib_lin="0,5", filter_="Al 12,5 µm"):
    lin = f"<CalibLin>{calib_lin}</CalibLin>" if calib_lin is not None else ""
    text = (
        '<?xml version="1.0" encoding="WINDOWS-1252" standalone="yes"?>\n'
        '<TRTSpectrum><ClassInstance Type="TRTSpectrum">'
        "<TRTHeaderedClass>"
        '<ClassInstance Type="TRTRFAHeader">'
        f"<Filter>{filter_}</Filter></ClassInstance>"
        '<ClassInstance Type="TRTInformationHeader"><User>Someone</User>'
        "</ClassInstance></TRTHeaderedClass>"
        '<ClassInstance Type="TRTSpectrumHeader">'
        f"<ChannelCount>{count}</ChannelCount><CalibAbs>-1,5</CalibAbs>{lin}"
        "</ClassInstance>"
        f"<Channels>{channels}</Channels>"
        "</ClassInstance></TRTSpectrum>"
    )
    return text.encode("cp1252")


class BrukerSpxTests(SimpleTestCase):
    def test_reads_the_albi_spectrum(self):
        data = FIXTURE.read_bytes()
        reading = bruker_spx.read(data)
        counts = [
            int(v)
            for v in ET.fromstring(data)
            .find("ClassInstance")
            .find("Channels")
            .text.split(",")
        ]
        rows = reading.series.rows
        self.assertEqual(len(rows), 4096)
        self.assertAlmostEqual(rows[0][0], -1.2215, delta=1e-12)
        self.assertAlmostEqual(rows[1][0], -1.2215 + 0.012623, delta=1e-12)
        self.assertEqual([r[1] for r in rows], counts)
        self.assertEqual(reading.series.columns, ("energy_keV", "counts"))
        self.assertEqual(reading.content_preset, "xrf")
        self.assertEqual(reading.format, "bruker_spx")
        facts = {f.key: f for f in reading.facts}
        self.assertEqual(facts["tube_voltage"].value, "50")
        self.assertEqual(facts["tube_anode"].value, "42")
        self.assertEqual(facts["live_time"].value, "179869")
        self.assertEqual(facts["acquired_at"].value, "29.6.2016 17:36:1")
        self.assertEqual(facts["serial_number"].value, "04003L02")
        self.assertEqual(facts["calibration"].value, "-1,2215; 0,012623")
        self.assertTrue(all(f.unit is None for f in reading.facts))
        self.assertEqual(detect(data), "bruker_spx")
        self.assertEqual(convert(data).format, "bruker_spx")

    def test_user_is_never_copied(self):
        data = FIXTURE.read_bytes()
        user = ET.fromstring(data).find(".//User").text
        self.assertTrue(user)
        for fact in bruker_spx.read(data).facts:
            self.assertNotIn(user, fact.value)

    def test_cp1252_mu_survives(self):
        facts = {f.key: f.value for f in bruker_spx.read(synthetic()).facts}
        self.assertEqual(facts["filter"], "Al 12,5 µm")
        self.assertNotIn("User", facts)

    def test_entity_expansion_is_refused(self):
        bomb = (
            '<?xml version="1.0"?><!DOCTYPE TRTSpectrum ['
            '<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">'
            '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;">]>'
            '<TRTSpectrum><ClassInstance Type="TRTSpectrum">&c;</ClassInstance>'
            "</TRTSpectrum>"
        ).encode()
        with self.assertRaises(UnreadableFile) as caught:
            bruker_spx.read(bomb)
        self.assertEqual(caught.exception.code, "malformed")

    def test_uncalibrated_spx(self):
        reading = bruker_spx.read(synthetic(calib_lin=None))
        self.assertEqual(reading.series.columns, ("channel", "counts"))
        self.assertEqual(reading.content_preset, "xrf_channel")
        self.assertIn("no_calibration", reading.warnings)
        self.assertEqual(reading.series.rows[2], (2.0, 3.0))
        zero = bruker_spx.read(synthetic(calib_lin="0"))
        self.assertEqual(zero.content_preset, "xrf_channel")

    def test_calibrated_synthetic(self):
        reading = bruker_spx.read(synthetic())
        self.assertEqual(reading.series.rows[2], (-0.5, 3.0))
        self.assertNotIn("no_calibration", reading.warnings)

    def test_count_mismatch_and_oversize_are_malformed(self):
        for data in (
            synthetic(count=5),
            synthetic(count=2_000_000, channels="1,2"),
            synthetic(channels="1,x,3,4"),
            b"<?xml version='1.0'?><TRTSpectrum>",
        ):
            with self.assertRaises(UnreadableFile) as caught:
                bruker_spx.read(data)
            self.assertEqual(caught.exception.code, "malformed")

    def test_sniff(self):
        self.assertTrue(bruker_spx.sniff(b"\xef\xbb\xbf<?xml ?><TRTSpectrum>"))
        self.assertFalse(bruker_spx.sniff(b"<?xml ?><other/>"))
        self.assertFalse(bruker_spx.sniff(b"TRTSpectrum"))

    def test_a_nested_fitted_spectrum_is_ignored(self):
        nested = (
            b'<ClassInstance Type="TRTResult"><ClassInstance Type="TRTSpectrum">'
            b"<ChannelCount>2</ChannelCount><CalibAbs>-9</CalibAbs>"
            b"<CalibLin>9</CalibLin><Filter>nested</Filter>"
            b"<Channels>7,7</Channels></ClassInstance></ClassInstance>"
        )
        data = synthetic().replace(b"<Channels>", nested + b"<Channels>", 1)
        data = data.replace(
            b'<ClassInstance Type="TRTRFAHeader">',
            nested + b'<ClassInstance Type="TRTRFAHeader">',
            1,
        )
        reading = bruker_spx.read(data)
        self.assertEqual(reading.series.rows[2], (-0.5, 3.0))
        self.assertEqual(len(reading.series.rows), 4)
        facts = {f.key: f.value for f in reading.facts}
        self.assertEqual(facts["filter"], "Al 12,5 µm")
        self.assertEqual(facts["calibration"], "-1,5; 0,5")
