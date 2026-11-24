from django.test import SimpleTestCase

from arches.app.utils.file_validator import FileValidator

from manuspectrum.measurement_files.converters import (
    Fact,
    Reading,
    Series,
    check_csv,
    csv_name,
    write_csv,
)
from manuspectrum.measurement_files.converters.base import span
from manuspectrum.measurement_files.converters.csv_writer import format_number


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
            "header_numeric": b"1,2\n3,4\n5,6\n",
            "header_formula": b"a,=b\n1,2\n3,4\n",
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

    def test_checker_refuses_numbers_the_browser_reads_differently(self):
        for cell in ("1_000", " 1", "+1", "\uff11", "nan", "inf", "infinity", "1 "):
            with self.subTest(cell):
                data = f"x,y\n1,{cell}\n3,4\n".encode()
                self.assertEqual(check_csv(data), ("not_numeric",))

    def test_csv_name(self):
        self.assertEqual(csv_name("x.0"), "x.0.csv")
        self.assertEqual(csv_name("x.spc.0"), "x.spc.0.csv")
        self.assertEqual(csv_name("a.b.mca"), "a.b.csv")
        self.assertEqual(csv_name("noext"), "noext.csv")


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
