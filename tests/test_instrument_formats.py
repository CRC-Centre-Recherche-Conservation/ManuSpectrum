"""Raw instrument formats read by ``read_series``: ELIO ``.mca`` and ASD FieldSpec ``.asd``.

The fixtures are real files of the lab, copied from the development
database's uploads: ``elio_xrf.mca`` (XRF, 4096 channels, two calibration
points) and ``asd_fieldspec_as8.asd`` (FORS, ``as8``, raw target and white
reference, 350-2500 nm).

Usage:
    python manage.py test tests.test_instrument_formats --settings=tests.test_settings
"""

import shutil
import struct
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from manuspectrum.utils import instrument_formats
from manuspectrum.utils.spectrum_preview import build_preview, is_readable, read_series

FIXTURES = Path(__file__).parent / "fixtures" / "xy"
MCA = FIXTURES / "elio_xrf.mca"
ASD = FIXTURES / "asd_fieldspec_as8.asd"


class FormatCase(SimpleTestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory, True)

    def written(self, name, content):
        path = self.directory / name
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return str(path)


class McaTests(FormatCase):
    def test_a_calibrated_mca_reads_as_energy_in_kev(self):
        series = read_series(str(MCA))

        self.assertEqual(len(series["x"]), 4096)
        slope = (22.163 - 8.046) / (1926 - 722)
        self.assertAlmostEqual(series["x"][722], 8.046, places=9)
        self.assertAlmostEqual(series["x"][1926], 22.163, places=9)
        self.assertAlmostEqual(series["x"][1] - series["x"][0], slope, places=10)
        self.assertFalse(series["x_reversed"])

    def test_the_counts_are_the_file_values_in_channel_order(self):
        values = [
            float(line)
            for line in MCA.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        ]

        self.assertEqual(read_series(str(MCA))["y"], values)

    def test_the_reading_states_its_axes(self):
        native = instrument_formats.read_native(str(MCA))

        self.assertEqual(native.x.label, "Energy (keV)")
        self.assertEqual((native.x.quantity, native.x.unit), ("energy", "keV"))
        self.assertEqual((native.y.quantity, native.y.unit), ("count", "{counts}"))

    def test_an_mca_without_calibration_reads_as_channels(self):
        path = self.written(
            "x.mca",
            "# sample\r\n# MCA Channels: 3\r\n# Calibration1: 0 0\r\n#\r\n1\r\n5\r\n2\r\n",
        )

        native = instrument_formats.read_native(path)
        series = read_series(path)

        self.assertEqual(series["x"], [0.0, 1.0, 2.0])
        self.assertEqual(series["y"], [1.0, 5.0, 2.0])
        self.assertEqual(native.x.label, "Channel")
        self.assertEqual((native.x.quantity, native.x.unit), ("channel", "1"))

    def test_a_single_calibration_point_is_no_calibration(self):
        path = self.written("x.mca", "# Calibration1: 10 1,5\n#\n1\n2\n")

        self.assertEqual(instrument_formats.read_native(path).x.quantity, "channel")

    def test_an_mca_of_another_shape_is_not_read(self):
        for content in (
            "<<PMCA SPECTRUM>>\n<<DATA>>\n1\n2\n<<END>>\n",
            b"\x00\x01\x02",
            "",
            "1,2\n3,4\n",
        ):
            with self.subTest(content=content):
                path = self.written("x.mca", content)
                self.assertIsNone(read_series(path))

    def test_the_preview_reads_an_mca(self):
        preview = build_preview(str(MCA), 200)

        self.assertEqual(preview["n_source"], 4096)
        self.assertTrue(preview["decimated"])


class AsdTests(FormatCase):
    def test_a_raw_asd_with_its_reference_reads_as_reflectance(self):
        series = read_series(str(ASD))
        data = ASD.read_bytes()
        target = struct.unpack_from("<2151d", data, 484)
        reference = struct.unpack_from("<2151d", data, 484 + 2151 * 8 + 20)

        self.assertEqual(len(series["x"]), 2151)
        self.assertEqual(series["x"][0], 350.0)
        self.assertEqual(series["x"][-1], 2500.0)
        self.assertEqual(series["y"][0], target[0] / reference[0])
        self.assertEqual(series["y"][1000], target[1000] / reference[1000])

    def test_the_reading_states_its_axes(self):
        native = instrument_formats.read_native(str(ASD))

        self.assertEqual(native.x.label, "Wavelength (nm)")
        self.assertEqual((native.x.quantity, native.x.unit), ("wavelength", "nm"))
        self.assertEqual(native.y.label, "Reflectance (0-1)")
        self.assertEqual(native.config["multiYHandling"], "reference-normalize")

    def test_a_reflectance_asd_is_read_as_stored(self):
        data = bytearray(ASD.read_bytes())
        data[186] = 1

        series = read_series(self.written("r.asd", bytes(data)))

        target = struct.unpack_from("<2151d", data, 484)
        self.assertEqual(series["y"][5], target[5])

    def test_an_asd_of_another_shape_is_not_read(self):
        data = ASD.read_bytes()
        for name, content in (
            ("version", b"xx9" + data[3:]),
            ("truncated", data[:600]),
            ("empty", b""),
            ("type", data[:186] + bytes([2]) + data[187:]),
        ):
            with self.subTest(name=name):
                self.assertIsNone(read_series(self.written(f"{name}.asd", content)))


class ReadableTests(SimpleTestCase):
    def test_the_raw_formats_read_natively_are_readable(self):
        for name in ("a.csv", "b.MCA", "c.asd"):
            self.assertTrue(is_readable(name), name)
        for name in ("d.spc", "e.txt", "f.tif", "noextension"):
            self.assertFalse(is_readable(name), name)
