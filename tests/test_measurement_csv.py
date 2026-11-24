from pathlib import Path

from django.test import SimpleTestCase

from arches.app.utils.file_validator import FileValidator

from manuspectrum.measurement_files.converters import (
    Fact,
    Reading,
    Series,
    UnreadableFile,
    check_csv,
    csv_name,
    write_csv,
)
from manuspectrum.measurement_files.converters.base import span
from manuspectrum.measurement_files.converters.csv_writer import format_number

REFUSED = (
    Path(__file__).parent / "fixtures" / "measurement_files" / "contract" / "refused"
)
REFUSAL_CODES = {
    "bom",
    "not_utf8",
    "line_ending",
    "no_header",
    "header_invalid",
    "comment_line",
    "separator",
    "too_few_columns",
    "quoted",
    "row_length",
    "not_numeric",
    "non_finite",
    "x_not_ascending",
    "too_few_rows",
}


class CsvWriterTests(SimpleTestCase):
    def test_writes_the_bare_contract(self):
        series = Series(("energy_keV", "counts"), ((6.26, 52.0), (6.28, 68.0)))
        self.assertEqual(write_csv(series), b"energy_keV,counts\n6.26,52\n6.28,68\n")

    def test_formats_numbers_shortest(self):
        self.assertEqual(format_number(52.0), "52")
        self.assertEqual(format_number(0.1), "0.1")
        self.assertEqual(format_number(1e-07), "1e-07")
        self.assertEqual(format_number(-1.2215), "-1.2215")

    def test_refuses_what_breaks_the_contract(self):
        cols = ("x", "y")
        bad = {
            "nan": ((1.0, float("nan")),),
            "inf": ((1.0, float("inf")),),
            "row length": ((1.0, 2.0), (2.0, 3.0, 4.0)),
            "equal x": ((1.0, 2.0), (1.0, 3.0)),
            "descending x": ((2.0, 2.0), (1.0, 3.0)),
        }
        for name, rows in bad.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    write_csv(Series(cols, rows))

    def test_what_it_writes_passes_arches_and_the_checker(self):
        series = [
            Series(("x", "y"), ((1.0, 2.5), (2.0, 3.5))),
            Series(
                ("x", "a", "b"), ((1.0, 2.0, 3.0), (2.0, 4.0, 5.5), (3.0, 1e-07, 0.0))
            ),
            Series(
                ("x", "a", "b", "c"),
                ((400.0, 1.0, 2.0, 3.0), (401.5, 0.1, 0.2, 0.3)),
            ),
        ]
        for s in series:
            data = write_csv(s)
            with self.subTest(columns=len(s.columns)):
                self.assertEqual(
                    FileValidator().test_unknown_filetypes(data, "csv"), []
                )
                self.assertEqual(check_csv(data), ())

    def test_checker_names_each_violation(self):
        cases = {
            "not_utf8": b"x,y\n\xff,2\n",
            "bom": b"\xef\xbb\xbfx,y\n1,2\n3,4\n",
            "line_ending": b"x,y\r\n1,2\r\n3,4\r\n",
            "no_header": b"",
            "header_invalid": b"1,2\n3,4\n5,6\n",
            "too_few_columns": b"x\n1\n2\n3\n",
            "quoted": b'x,y\n"1","2"\n"3","4"\n',
            "comment_line": b"x,y\n# note\n1,2\n3,4\n",
            "separator": b"x;y\n1;2\n3;4\n",
            "not_numeric": b"x,y\n1,abc\n3,4\n",
            "non_finite": b"x,y\n1,1e999\n3,4\n",
            "row_length": b"x,y\n1,2\n3\n5,6\n",
            "x_not_ascending": b"x,y\n1,2\n1,3\n",
            "too_few_rows": b"x,y\n1,2\n",
        }
        for code, data in cases.items():
            with self.subTest(code):
                self.assertEqual(check_csv(data), (code,))
        self.assertEqual(check_csv(b"x,y\n2,1\n1,1\n3,3\n"), ("x_not_ascending",))

    def test_header_cells_must_start_with_a_letter_and_hold_no_markup(self):
        for header in (
            "2theta,counts",
            "<script>,y",
            " =cmd(),y",
            "a,=b",
            "a,+b",
            "a,-b",
            "x,@y",
            "x,y;z",
            "x,",
            "_x,y",
        ):
            with self.subTest(header):
                data = f"{header}\n1,2\n3,4\n".encode()
                self.assertEqual(check_csv(data), ("header_invalid",))

    def test_every_column_name_we_write_passes(self):
        names = (
            ("energy_keV", "counts"),
            ("channel", "counts"),
            ("wavenumber_cm-1", "absorbance"),
            ("wavelength_nm", "target_dn", "white_reference_dn"),
            ("raman_shift_cm-1", "intensity"),
            ("mz", "intensity"),
            ("x", "y", "y2", "y3"),
        )
        for columns in names:
            data = ",".join(columns) + "\n" + ",".join("1" for _ in columns) + "\n"
            data += ",".join("2" for _ in columns) + "\n"
            with self.subTest(columns):
                self.assertEqual(check_csv(data.encode()), ())

    def test_checker_refuses_numbers_the_browser_reads_differently(self):
        for cell in ("1_000", " 1", "+1", "\uff11", "nan", "inf", "infinity", "1 "):
            with self.subTest(cell):
                data = f"x,y\n1,{cell}\n3,4\n".encode()
                self.assertEqual(check_csv(data), ("not_numeric",))

    def test_fits_viewer_is_true_at_the_preview_ceiling_and_false_one_byte_over(self):
        from django.test import override_settings

        from manuspectrum.measurement_files.converters import fits_viewer

        with override_settings(SPECTRUM_PREVIEW_MAX_BYTES=100):
            self.assertTrue(fits_viewer(b"x" * 100))
            self.assertFalse(fits_viewer(b"x" * 101))
            self.assertTrue(fits_viewer(b""))

    def test_csv_name(self):
        self.assertEqual(csv_name("x.0"), "x.0.csv")
        self.assertEqual(csv_name("x.spc.0"), "x.spc.0.csv")
        self.assertEqual(csv_name("a.b.mca"), "a.b.csv")
        self.assertEqual(csv_name("noext"), "noext.csv")

    def test_csv_name_drops_any_directory(self):
        self.assertEqual(csv_name("dir.v2/file"), "file.csv")
        self.assertEqual(csv_name("a/b/x.0"), "x.0.csv")
        self.assertEqual(csv_name("dir.v2/file.mca"), "file.csv")

    def test_refused_fixtures_each_give_their_code(self):
        files = sorted(REFUSED.glob("*.csv"))
        self.assertTrue(files)
        for path in files:
            code = path.stem.split("__")[0]
            with self.subTest(path.name):
                self.assertEqual(check_csv(path.read_bytes()), (code,))
        self.assertEqual(
            {p.stem.split("__")[0] for p in files} | {"line_ending"}, REFUSAL_CODES
        )


class CheckSeriesTests(SimpleTestCase):
    def refused(self, rows, columns=("x", "y")):
        from manuspectrum.measurement_files.converters.base import check_series

        with self.assertRaises(UnreadableFile) as caught:
            check_series(Series(columns, rows))
        return caught.exception.code

    def test_names_each_violation(self):
        nan, inf = float("nan"), float("inf")
        self.assertEqual(self.refused(((1.0, 2.0),)), "too_few_points")
        self.assertEqual(self.refused(()), "too_few_points")
        self.assertEqual(self.refused(((1.0, nan), (2.0, 1.0))), "non_finite")
        self.assertEqual(self.refused(((1.0, 1.0), (inf, 1.0))), "non_finite")
        self.assertEqual(self.refused(((1.0, 1.0), (2.0, 1.0, 3.0))), "malformed")
        self.assertEqual(self.refused(((2.0, 1.0), (1.0, 1.0))), "malformed")
        self.assertEqual(self.refused(((1.0, 1.0), (1.0, 2.0))), "duplicate_x")

    def test_accepts_what_write_csv_writes(self):
        from manuspectrum.measurement_files.converters.base import check_series

        check_series(Series(("x", "y"), ((-1.2, 1e-07), (0.0, 2.0))))


class BaseTypesTests(SimpleTestCase):
    def test_span_is_two_numbers_and_an_en_dash(self):
        self.assertEqual(
            span(92.5744094848, 1869.49609375), "92.57440948\u20131869.496094"
        )

    def test_fact_and_reading_reject_unknown_keys(self):
        with self.assertRaises(ValueError):
            Fact("operator", "x")
        Fact("tube_voltage", "40", "kV")
        with self.assertRaises(ValueError):
            Reading("mca", 1, None, None, warnings=("nope",))
        Reading("mca", 1, None, None, warnings=("no_calibration",))
