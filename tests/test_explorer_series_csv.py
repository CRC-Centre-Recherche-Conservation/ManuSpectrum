"""``GET /api/explorer/series.csv``: the Selection's spectra in long format, never decimated.

Usage:
    python manage.py test tests.test_explorer_series_csv --settings="tests.test_settings"
"""

import csv
import io
import uuid
from unittest import mock

from django.conf import settings
from django.http import QueryDict

from arches.app.models.models import TileModel

from manuspectrum.models import RendererConfig
from manuspectrum.views.explorer.scopes import resolve_scope
from manuspectrum.views.explorer.series import HEADER
from tests.test_explorer_api import FETCH, MANIFEST_JSON, CorpusCase

FORS = {
    "presetKey": "fors",
    "multiYHandling": "reference-normalize",
    "display": {
        "xReversed": False,
        "columnAssignments": [
            {"role": "x", "columnIndex": 0},
            {"role": "yLeft", "columnIndex": 1},
            {"role": "reference", "columnIndex": 2},
        ],
    },
}
ND = {"id": "CC-BY-ND-4.0", "url": "https://creativecommons.org/licenses/by-nd/4.0/"}
BY = {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


class SeriesCsvTests(CorpusCase):
    def setUp(self):
        super().setUp()
        self.config = str(uuid.uuid4())
        RendererConfig.objects.create(
            configid=self.config, rendererid=uuid.uuid4(), name="FORS", config=FORS
        )

    def pk(self, key):
        return str(self.analyses[key].pk)

    def get(self, query):
        with mock.patch(FETCH, return_value=MANIFEST_JSON):
            return self.client.get(f"/api/explorer/series.csv?{query}")

    def text(self, query):
        response = self.get(query)
        self.assertEqual(response.status_code, 200, query)
        return b"".join(response.streaming_content).decode()

    def split(self, text):
        """``(comment lines, csv rows)`` of a body."""
        lines = text.splitlines()
        comments = [line for line in lines if line.startswith("#")]
        rows = list(
            csv.reader(io.StringIO("\n".join(l for l in lines if l not in comments)))
        )
        return comments, rows

    def spectrum(self, key="on_document", name="S1.csv", rows=None, **options):
        rows = rows if rows is not None else [(400.0, 1.5), (401.0, -2.25)]
        content = "".join(",".join(str(v) for v in row) + "\n" for row in rows)
        options.setdefault(
            "config", self.config if len(rows[0]) > 2 else str(uuid.uuid4())
        )
        return self.stored_file(self.analyses[key], name, content.encode(), **options)

    def selection(self, *keys):
        return "ids=" + ",".join(f"an:{self.pk(k)}:-" for k in keys)

    def test_long_format_header_and_rows(self):
        file_id = self.spectrum()

        comments, rows = self.split(self.text(self.selection("on_document")))

        self.assertEqual(rows[0], ["curve", "analysis", "file", "x", "y"])
        self.assertEqual(
            rows[1:],
            [
                ["c1", self.pk("on_document"), file_id, "400.0", "1.5"],
                ["c1", self.pk("on_document"), file_id, "401.0", "-2.25"],
            ],
        )
        self.assertTrue(comments)

    def test_every_point_is_kept(self):
        self.spectrum(rows=[(float(i), float(i % 7)) for i in range(5000)])

        _, rows = self.split(self.text(self.selection("on_document")))

        self.assertEqual(len(rows) - 1, 5000)

    def test_the_configured_curve_is_written(self):
        self.spectrum(
            rows=[(350.0, 8.0, 80.0), (351.0, 9.0, 90.0), (353.0, 6.0, 120.0)]
        )

        _, rows = self.split(self.text(self.selection("on_document")))

        self.assertEqual([r[4] for r in rows[1:]], ["0.1", "0.1", "0.05"])

    def test_negative_values_are_written_as_numbers(self):
        self.spectrum(rows=[(-1.5, -0.001), (2.0, -3e-07)])

        _, rows = self.split(self.text(self.selection("on_document")))

        self.assertEqual(
            [r[3:] for r in rows[1:]], [["-1.5", "-0.001"], ["2.0", "-3e-07"]]
        )

    def test_curves_are_numbered_in_scope_order(self):
        files = {
            self.pk("on_document"): self.spectrum(key="on_document", name="A.csv"),
            self.pk("draft"): self.spectrum(key="draft", name="B.csv"),
        }
        query = self.selection("on_document", "draft")
        order = resolve_scope(QueryDict(query), "en").analyses

        _, rows = self.split(self.text(query))

        self.assertEqual(
            sorted({(r[0], r[1], r[2]) for r in rows[1:]}),
            [("c1", order[0], files[order[0]]), ("c2", order[1], files[order[1]])],
        )

    def test_a_no_derivatives_curve_is_excluded_with_its_raw_file_named(self):
        self.spectrum(name="X.csv", licence=ND)
        raw = self.stored_file(self.analyses["on_document"], "X.mca", b"\x00\x01")

        comments, rows = self.split(self.text(self.selection("on_document")))

        self.assertEqual(rows, [["curve", "analysis", "file", "x", "y"]])
        (excluded,) = [c for c in comments if "X.csv" in c]
        self.assertIn(ND["url"], excluded)
        self.assertIn(f"{settings.PUBLIC_SERVER_ADDRESS}files/{raw}", excluded)
        self.assertIn("derivatives", excluded)

    def test_each_curve_names_licence_attribution_configuration_and_raw_file(self):
        readable = self.spectrum(
            name="Y.csv", rows=[(350.0, 8.0, 80.0), (351.0, 9.0, 90.0)], licence=BY
        )
        raw = self.stored_file(self.analyses["on_document"], "Y.asd", b"\x00")
        self.set_attribution(readable, "CRC, Paris")

        comments, _ = self.split(self.text(self.selection("on_document")))

        (curve,) = [c for c in comments if c.startswith("# c1:")]
        self.assertIn("FORS_009 — f. 1v — Y.csv", curve)
        self.assertIn("https://creativecommons.org/licenses/by/4.0/", curve)
        self.assertIn("CRC, Paris", curve)
        self.assertIn("fors", curve)
        self.assertIn(f"{settings.PUBLIC_SERVER_ADDRESS}files/{raw}", curve)
        self.assertIn(
            f"{settings.PUBLIC_SERVER_ADDRESS}report/{self.pk('on_document')}",
            "\n".join(comments),
        )

    def set_attribution(self, file_id, text):
        node = str(self.nodes[("analysis", "measurement_point_data")].nodeid)
        for tile in TileModel.objects.filter(
            resourceinstance=self.analyses["on_document"]
        ):
            entries = (tile.data or {}).get(node)
            if not entries:
                continue
            for entry in entries:
                if entry["file_id"] == file_id:
                    entry["attribution"] = {"en": {"value": text, "direction": "ltr"}}
            TileModel.objects.filter(pk=tile.pk).update(data=tile.data)

    def comment_lines(self, *keys):
        lines = self.text(self.selection(*keys)).splitlines()
        return lines[: next(i for i, l in enumerate(lines) if l.startswith("curve"))]

    def assert_no_cell_opens_a_formula(self, comments):
        for line in comments:
            self.assertTrue(line.startswith("#"), line)
            self.assertNotIn('"', line)
            self.assertNotIn("\r", line)
            for delimiter in (",", ";"):
                for cell in next(csv.reader([line], delimiter=delimiter)):
                    with self.subTest(line=line, delimiter=delimiter, cell=cell):
                        self.assertNotIn(cell.lstrip(" ")[:1], FORMULA_STARTS)

    def test_curator_text_cannot_start_a_formula_in_a_comment(self):
        self.spectrum(name="=HYPERLINK(1),@x.csv")

        self.assert_no_cell_opens_a_formula(self.comment_lines("on_document"))

    def test_a_quoted_or_semicolon_formula_is_neutralised_in_its_comment_line(self):
        self.spectrum(name='x,"=HYPERLINK(""https://evil"",""Open"")",y.csv')
        self.spectrum(key="open", name="a;=cmd|' /C calc'!A0.csv")

        comments = self.comment_lines("on_document", "open")

        self.assert_no_cell_opens_a_formula(comments)
        self.assertTrue([c for c in comments if "'=HYPERLINK(''https://evil''" in c])
        self.assertTrue([c for c in comments if "a;'=cmd|' /C calc'!A0.csv" in c])

    def test_a_separator_before_plus_at_or_minus_gets_a_leading_quote(self):
        readable = self.spectrum(name="p,+1,@x, -2.csv", licence=BY)
        self.set_attribution(readable, "CRC; =SUM(1)\t,\t@y")

        comments = self.comment_lines("on_document")

        self.assert_no_cell_opens_a_formula(comments)
        (curve,) = [c for c in comments if c.startswith("# c1:")]
        self.assertIn("p,'+1,'@x,' -2.csv", curve)
        self.assertIn("CRC;' =SUM(1) ,' @y", curve)

    def test_every_metadata_line_starts_with_a_hash_before_the_data_rows(self):
        self.spectrum()
        self.spectrum(key="open", name='a,"=1";@b.csv')

        text = self.text(self.selection("on_document", "open"))
        lines = text.splitlines()
        data = [l for l in lines if not l.startswith("#")]

        self.assertEqual(data[0], ",".join(HEADER))
        self.assertEqual(len(data), 5)
        for row in csv.reader(data[1:]):
            self.assertEqual(len(row), len(HEADER))
            float(row[3]), float(row[4])
        try:
            import pandas
        except ImportError:
            return
        frame = pandas.read_csv(io.StringIO(text), comment="#")
        self.assertEqual(list(frame.columns), list(HEADER))
        self.assertEqual(len(frame), 4)

    def test_a_raw_instrument_file_is_never_read(self):
        self.stored_file(self.analyses["on_document"], "Z.mca", b"1,2\n3,4\n")

        with mock.patch("manuspectrum.views.explorer.series.read_series") as read:
            self.text(self.selection("on_document"))

        read.assert_not_called()

    def test_a_file_over_the_preview_ceiling_is_named_not_read(self):
        file_id = self.spectrum(name="Big.csv")

        with (
            self.settings(SPECTRUM_PREVIEW_MAX_BYTES=10),
            mock.patch("manuspectrum.views.explorer.series.read_series") as read,
        ):
            comments, rows = self.split(self.text(self.selection("on_document")))

        read.assert_not_called()
        self.assertEqual(len(rows), 1)
        (line,) = [c for c in comments if "Big.csv" in c]
        self.assertIn(f"{settings.PUBLIC_SERVER_ADDRESS}files/{file_id}", line)

    def test_drafts_mark_the_header(self):
        self.spectrum(key="draft")

        drafted, _ = self.split(self.text(self.selection("draft")))
        self.spectrum(key="on_document")
        plain, _ = self.split(self.text(self.selection("on_document")))

        self.assertIn("# Contains drafts", drafted)
        self.assertNotIn("# Contains drafts", plain)

    def test_an_embargoed_analysis_key_is_left_out(self):
        hidden = self.spectrum(key="on_document", name="H.csv")
        shown = self.spectrum(key="draft", name="D.csv")
        self.embargo(self.analyses["on_document"])

        text = self.text(self.selection("on_document", "draft"))

        self.assertNotIn(self.pk("on_document"), text)
        self.assertNotIn(hidden, text)
        self.assertNotIn("FORS_009", text)
        self.assertIn(shown, text)

    def test_a_document_scope_is_a_bad_request(self):
        for query in (
            f"document={self.documents['open'].pk}",
            f"project={self.projects['main'].pk}",
            f"{self.selection('on_document')}&document={self.documents['open'].pk}",
            f"{self.selection('on_document')}&lang=xx",
            "",
        ):
            with self.subTest(query=query):
                response = self.get(query)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.content, b"")

    def test_more_than_thirty_keys_is_a_bad_request(self):
        keys = ",".join(
            f"an:{uuid.uuid4()}:-" for _ in range(settings.EXPLORER_ITEMS_MAX + 1)
        )

        response = self.get(f"ids={keys}")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content, b"")

    def test_a_scope_with_nothing_visible_is_the_bodyless_404(self):
        self.embargo(self.analyses["on_document"])

        response = self.get(self.selection("on_document"))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_the_download_is_a_private_attachment(self):
        self.spectrum()

        response = self.get(self.selection("on_document"))

        self.assertTrue(response.streaming)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertRegex(
            response["Content-Disposition"],
            r'^attachment; filename="manuspectrum-series-[0-9a-f]{12}\.csv"$',
        )
        self.assertNotIn("Content-Encoding", response)

    def test_the_header_follows_lang(self):
        self.spectrum(key="draft")

        comments, _ = self.split(self.text(f"{self.selection('draft')}&lang=fr"))

        self.assertIn("# Contient des brouillons", comments)
