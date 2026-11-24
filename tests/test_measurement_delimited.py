import csv
from pathlib import Path

from django.test import SimpleTestCase

from manuspectrum.measurement_files.converters import (
    UnreadableFile,
    UnsupportedFormat,
    registry,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "measurement_files"
    / "indores_albi"
    / "F1_parchment.asd.txt"
)


def read(text, encoding="utf-8"):
    data = text if isinstance(text, bytes) else text.encode(encoding)
    return registry.convert(data)


def refused(test, data):
    with test.assertRaises(UnreadableFile) as caught:
        registry.convert(data)
    return caught.exception.code


class DelimitedTests(SimpleTestCase):
    def test_reads_the_albi_text_export(self):
        text = FIXTURE.read_text(encoding="utf-8-sig")
        expected = []
        for row in csv.reader(text.splitlines(), delimiter="\t"):
            try:
                expected.append(tuple(float(v.replace(",", ".")) for v in row))
            except ValueError:
                continue
        reading = read(FIXTURE.read_bytes())
        self.assertEqual(reading.format, "delimited")
        self.assertEqual(reading.reader_version, 1)
        self.assertIsNone(reading.content_preset)
        self.assertEqual(reading.facts, ())
        self.assertEqual(reading.series.columns, ("x", "y"))
        self.assertGreater(len(expected), 2000)
        self.assertEqual(len(reading.series.rows), len(expected))
        self.assertEqual(reading.series.rows[0], expected[0])
        self.assertEqual(reading.series.rows[-1], expected[-1])

    def test_descending_rows_are_sorted(self):
        text = "\n".join(f"{x}\t{x * 2}" for x in (6, 5, 4, 3, 2, 1))
        rows = read(text).series.rows
        self.assertEqual([r[0] for r in rows], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        self.assertEqual(rows[0], (1.0, 2.0))

    def test_semicolon_decimal_comma(self):
        text = "x;y;z\n" + "\n".join(f"{i},5;{i},25;{i},75" for i in range(1, 8))
        series = read(text).series
        self.assertEqual(series.columns, ("x", "y", "y2"))
        self.assertEqual(series.rows[0], (1.5, 1.25, 1.75))

    def test_comma_separator_keeps_dot_decimals(self):
        text = "a,b\n" + "\n".join(f"{i}.5,{i}.25" for i in range(1, 8))
        self.assertEqual(read(text).series.rows[0], (1.5, 1.25))

    def test_whitespace_separated(self):
        text = "# note\n" + "\n".join(f"{i}   {i}.5  {i}.25" for i in range(1, 8))
        series = read(text).series
        self.assertEqual(series.columns, ("x", "y", "y2"))
        self.assertEqual(series.rows[2], (3.0, 3.5, 3.25))

    def test_utf8_bom_and_utf16_exports(self):
        text = "Wavelength\tnm\n" + "\n".join(f"{i}\t{i},5" for i in range(1, 8))
        expected = tuple((float(i), i + 0.5) for i in range(1, 8))
        for data in (
            text.encode("utf-8-sig"),
            text.encode("utf-16"),
            text.encode("utf-16-le", "strict").join([b"\xff\xfe", b""]),
            text.replace("nm", "é").encode("cp1252"),
        ):
            self.assertEqual(read(data).series.rows, expected)

    def test_rows_of_different_widths_are_malformed(self):
        self.assertEqual(refused(self, b"1 2\n3 4 5\n"), "malformed")

    def test_no_numbers_and_one_column_is_not_a_measurement(self):
        for data in (b"x\ty\n1\t2\n", b"hello\nworld\n", b"1\n2\n3\n4\n5\n6\n"):
            with self.subTest(data):
                with self.assertRaises(UnsupportedFormat) as caught:
                    registry.convert(data)
                self.assertIsNone(caught.exception.format)

    def test_duplicate_x_is_refused(self):
        text = "\n".join(f"{x}\t1" for x in (1, 2, 2, 3, 4, 5))
        self.assertEqual(refused(self, text.encode()), "duplicate_x")

    def test_trailing_numbers_after_a_footer_are_malformed(self):
        text = "\n".join(f"{i}\t{i}" for i in range(1, 8)) + "\nEnd of data\n9\t9\n"
        self.assertEqual(refused(self, text.encode()), "malformed")

    def test_a_footer_alone_is_fine(self):
        text = "\n".join(f"{i}\t{i}" for i in range(1, 8)) + "\nEnd of data\n"
        self.assertEqual(len(read(text).series.rows), 7)

    def test_header_text_is_never_copied(self):
        reading = read(FIXTURE.read_bytes())
        self.assertNotIn("F1_parchment", repr(reading.series.columns))
        self.assertNotIn("F1_parchment", repr(reading.facts))

    def test_known_unread_formats_do_not_fall_back(self):
        from manuspectrum.measurement_files.converters import UnsupportedFormat

        with self.assertRaises(UnsupportedFormat) as caught:
            registry.convert(b"<<PMCA SPECTRUM>>\n1\t2\n3\t4\n5\t6\n7\t8\n9\t9\n")
        self.assertEqual(caught.exception.format, "amptek_mca")

    def test_a_long_header_does_not_hide_the_separator(self):
        header = "\n".join(f"Parameter {n}: value {n}" for n in range(30))
        rows = {
            "\t": [f"{i}\t{i}.5" for i in range(1, 41)],
            ";": [f"{i};{i}.5" for i in range(1, 41)],
            ",": [f"{i},{i}.5" for i in range(1, 41)],
            " ": [f"{i} {i}.5" for i in range(1, 41)],
        }
        for separator, lines in rows.items():
            with self.subTest(repr(separator)):
                series = read(header + "\n" + "\n".join(lines)).series
                self.assertEqual(len(series.rows), 40)
                self.assertEqual(series.rows[0], (1.0, 1.5))

    def test_rows_are_converted_only_up_to_the_cap(self):
        from unittest import mock

        from manuspectrum.measurement_files.converters import delimited

        data = "\n".join(f"{i} {i}" for i in range(1, 3001)).encode()
        with mock.patch.object(delimited, "MAX_CHANNELS", 10):
            with mock.patch.object(delimited, "float", create=True, wraps=float) as spy:
                self.assertEqual(refused(self, data), "malformed")
        self.assertLess(spy.call_count, 100)


class DelimitedProbeWindowTests(SimpleTestCase):
    def test_rows_past_the_separator_probe_window_are_not_numeric_columns(self):
        data = b"a\n" * 2000 + b"1 2\n3 4\n5 6\n"
        self.assertEqual(registry.detect(data), "delimited")
        self.assertEqual(refused(self, data), "no_numeric_columns")

    def test_a_single_row_under_the_chosen_separator_has_too_few_points(self):
        data = b"1;2\n" + b"a\n" * 2000 + b"3\t4\n5\t6\n"
        self.assertEqual(registry.detect(data), "delimited")
        self.assertEqual(refused(self, data), "too_few_points")
