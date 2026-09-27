"""The ``xyReading`` extension of spectrum bodies, its CSV header and its JSON Schema (C4).

Usage:
    python manage.py test tests.test_iiif_xy_reading --settings=tests.test_settings
"""

import json
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest import mock

from django.test import Client, SimpleTestCase
from jsonschema import Draft7Validator

from manuspectrum.constants.xy_presets import TECHNIQUE_PRESETS, XY_PRESETS
from manuspectrum.iiif import ids, xy_reading
from manuspectrum.models import RendererConfig
from manuspectrum.utils import spectrum_preview
from tests.explorer_fixtures import FEATURES, IIIFCase

SCHEMA = Path(xy_reading.__file__).parent / "schemas" / "xy-reading-1.schema.json"
FIXTURES = Path(__file__).parent / "fixtures" / "xy"
FORS = XY_PRESETS["fors"]["config"]
XRF = XY_PRESETS["xrf"]["config"]
ND = {"id": "CC-BY-ND-4.0", "url": "https://creativecommons.org/licenses/by-nd/4.0/"}


def raw_file(name="S.csv"):
    """A measurement file of the ``xy`` fixtures, as the reading functions take it."""
    return xy_reading.RawFile(
        id="0f3a9c2d-0000-4000-8000-0000000000c7",
        name=name,
        media_type="text/csv",
        path=str(FIXTURES / name),
    )


def validator():
    with SCHEMA.open(encoding="utf-8") as handle:
        return Draft7Validator(json.load(handle))


class QuantityTests(SimpleTestCase):
    def test_every_preset_key_has_a_quantity_row(self):
        keys = set(XY_PRESETS) | set(TECHNIQUE_PRESETS.values())

        self.assertEqual(keys - set(xy_reading.QUANTITIES), set())

    def test_the_quantity_labels_are_the_preset_axis_labels(self):
        for key, preset in XY_PRESETS.items():
            display = preset["config"]["display"]
            x, y = xy_reading.QUANTITIES[key]
            with self.subTest(key=key):
                self.assertEqual(x.label, display["xAxisLabel"])
                self.assertEqual(y.label, display["yAxisLabel"])


class HeaderTests(SimpleTestCase):
    def header(self, x, y):
        return xy_reading.csv_header({"display": {"xAxisLabel": x, "yAxisLabel": y}})

    def test_the_preset_titles_are_the_header(self):
        self.assertEqual(
            xy_reading.csv_header(FORS), ("Wavelength (nm)", "Reflectance (0-1)")
        )

    def test_a_title_parse_float_reads_as_a_number_is_prefixed(self):
        self.assertEqual(self.header("2θ (°)", "1/R"), ("X 2θ (°)", "Y 1/R"))
        self.assertEqual(self.header(".5 mm", "Infinity"), ("X .5 mm", "Y Infinity"))

    def test_a_y_title_matching_an_x_pattern_is_prefixed(self):
        for title in ("Channel counts", "Energy", "time (s)", "Index", "nm", "keV"):
            with self.subTest(title=title):
                self.assertEqual(self.header("Wavelength", title)[1], f"Y {title}")

    def test_commas_and_line_breaks_leave_the_titles(self):
        self.assertEqual(
            self.header("Energy, keV", 'Counts\n"raw"'),
            ("Energy; keV", "Counts 'raw'"),
        )

    def test_an_empty_title_is_x_or_y(self):
        self.assertEqual(xy_reading.csv_header({}), ("x", "y"))
        self.assertEqual(xy_reading.csv_header(None), ("x", "y"))


class ReadingTests(SimpleTestCase):
    def raw(self, name="S.csv"):
        return raw_file(name)

    def test_the_clean_body_reads_its_two_columns(self):
        reading = xy_reading.xy_reading(self.raw(), FORS)

        self.assertEqual(reading["type"], "XYReading")
        self.assertEqual(
            reading["dialect"],
            {"delimiter": ",", "headerRowCount": 1, "encoding": "utf-8"},
        )
        self.assertEqual(
            reading["columns"],
            [{"index": 0, "role": "x"}, {"index": 1, "role": "yLeft"}],
        )
        self.assertEqual(reading["x"]["quantity"], "wavelength")
        self.assertEqual(reading["x"]["unit"], "nm")
        self.assertIs(reading["x"]["reversed"], False)
        self.assertEqual(reading["y"][0]["axis"], "left")
        self.assertEqual(reading["y"][0]["quantity"], "reflectance")
        self.assertEqual(reading["corrections"], [])

    def test_the_raw_reading_names_what_apply_config_honours(self):
        derived = xy_reading.xy_reading(self.raw(), FORS)["derivedFrom"]

        self.assertEqual(derived["id"], ids.data_raw(self.raw().id))
        self.assertEqual(derived["type"], "Dataset")
        self.assertEqual(derived["format"], "text/csv")
        self.assertEqual(
            derived["xyReading"]["columns"],
            [
                {"index": 0, "role": "x"},
                {"index": 1, "role": "yLeft"},
                {"index": 2, "role": "reference"},
            ],
        )
        self.assertNotIn("dialect", derived["xyReading"])
        self.assertNotIn("x", derived["xyReading"])

    def test_reference_normalize_is_a_correction_on_the_raw_file_only(self):
        reading = xy_reading.xy_reading(self.raw(), FORS)
        raw = reading["derivedFrom"]["xyReading"]

        self.assertEqual(raw["multiY"], "reference-normalize")
        self.assertEqual(
            raw["corrections"],
            [
                {
                    "type": "reference-normalize",
                    "expression": "(y - dark) / (reference - dark)",
                    "darkDefault": 0,
                    "epsilon": 1e-12,
                    "onInvalid": "drop-point",
                }
            ],
        )
        xrf = xy_reading.xy_reading(self.raw(), XRF)["derivedFrom"]["xyReading"]
        self.assertNotIn("multiY", xrf)
        self.assertEqual(xrf["corrections"], [])

    def test_a_curator_config_without_preset_gives_labels_without_quantity(self):
        config = {"display": {"xAxisLabel": "Depth (µm)", "yAxisLabel": "Signal"}}

        reading = xy_reading.xy_reading(self.raw(), config)

        self.assertEqual(reading["x"]["label"], {"none": ["Depth (µm)"]})
        self.assertNotIn("quantity", reading["x"])
        self.assertNotIn("unit", reading["y"][0])

    def test_labels_are_language_maps_rendered_per_language(self):
        reading = xy_reading.xy_reading(self.raw(), FORS)

        self.assertEqual(set(reading["x"]["label"]), {"en", "fr"})
        self.assertEqual(reading["x"]["label"]["en"], ["Wavelength (nm)"])

    def test_every_preset_serialises_to_a_schema_valid_xy_reading(self):
        check = validator()
        for key, preset in XY_PRESETS.items():
            with self.subTest(key=key):
                reading = xy_reading.xy_reading(self.raw(), preset["config"])
                errors = sorted(check.iter_errors(reading), key=str)
                self.assertEqual(errors, [])
                raw = reading["derivedFrom"]["xyReading"]
                self.assertEqual(sorted(check.iter_errors(raw), key=str), [])

    def test_the_schema_refuses_an_unknown_role(self):
        reading = xy_reading.xy_reading(self.raw(), FORS)
        reading["columns"][0]["role"] = "z"

        self.assertTrue(list(validator().iter_errors(reading)))

    def test_an_mca_reading_states_energy_from_its_calibration(self):
        mca = self.raw("elio_xrf.mca")

        reading = xy_reading.xy_reading(mca, {})

        self.assertEqual(reading["x"]["quantity"], "energy")
        self.assertEqual(reading["x"]["unit"], "keV")
        self.assertEqual(xy_reading.csv_header({}, mca), ("Energy (keV)", "Counts"))
        self.assertNotIn("xyReading", reading["derivedFrom"])
        self.assertEqual(list(validator().iter_errors(reading)), [])


class CleanCsvTests(SimpleTestCase):
    def test_the_clean_csv_is_streamed_from_the_file(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        path = directory / "big.csv"
        path.write_text("".join(f"{350 + i},{i}\n" for i in range(10000)))
        parsed = []
        parse_rows = spectrum_preview.parse_rows

        def counted(lines):
            for row in parse_rows(lines):
                parsed.append(row)
                yield row

        with mock.patch.object(spectrum_preview, "parse_rows", counted):
            chunks = xy_reading.csv_lines(
                xy_reading.RawFile("f", "big.csv", "text/csv", str(path)), {}
            )
            header, first = next(chunks), next(chunks)
            parsed_early = len(parsed)
            rest = "".join(chunks)

        self.assertEqual(header, "x,y\r\n")
        self.assertLess(parsed_early, 10000)
        self.assertEqual(len((first + rest).splitlines()), 10000)

    def test_a_file_of_one_point_has_no_clean_csv(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, True)
        path = directory / "one.csv"
        path.write_text("1,2\n")

        self.assertIsNone(
            xy_reading.csv_lines(
                xy_reading.RawFile("f", "one.csv", "text/csv", str(path)), {}
            )
        )


class BodyTests(IIIFCase):
    def setUp(self):
        super().setUp()
        self.visitor = Client()
        self.fors = str(uuid.uuid4())
        RendererConfig.objects.create(
            configid=self.fors, rendererid=uuid.uuid4(), name="FORS", config=FORS
        )

    def annotation(self):
        response = self.visitor.get(
            f"/iiif/v3/annotation/{self.analyses['open'].pk}/{FEATURES['open']}"
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def body(self, file_id, annotation=None):
        wanted = (ids.data_series(file_id), ids.data_raw(file_id))
        return next(
            b for b in (annotation or self.annotation())["body"] if b["id"] in wanted
        )

    def test_a_readable_file_is_a_clean_csv_body(self):
        file_id = self.stored_file(
            self.analyses["open"], "S.csv", b"350,1,10\n351,2,10\n", config=self.fors
        )

        body = self.body(file_id)

        self.assertEqual(body["id"], ids.data_series(file_id))
        self.assertEqual(body["type"], "Dataset")
        self.assertEqual(body["format"], "text/csv")
        self.assertEqual(body["label"]["en"], ["S.csv, series"])
        self.assertEqual(body["xyReading"]["derivedFrom"]["id"], ids.data_raw(file_id))

    def test_the_page_lists_our_context_first_and_p3_last(self):
        self.stored_file(
            self.analyses["open"], "S.csv", b"350,1,10\n351,2,10\n", config=self.fors
        )
        document = self.documents["open"].pk

        page = self.visitor.get(
            f"/iiif/v3/annotation-collection/{document}/page-1"
        ).json()
        annotation = self.annotation()

        for doc in (page, annotation):
            self.assertEqual(
                doc["@context"],
                [
                    ids.xy_context(),
                    "http://iiif.io/api/auth/2/context.json",
                    "http://iiif.io/api/presentation/3/context.json",
                ],
            )

    def test_a_page_without_xy_reading_does_not_list_our_context(self):
        document = self.documents["open"].pk

        page = self.visitor.get(
            f"/iiif/v3/annotation-collection/{document}/page-1"
        ).json()

        self.assertEqual(
            page["@context"], "http://iiif.io/api/presentation/3/context.json"
        )

    def test_the_body_of_an_nd_csv_is_the_raw_file_with_its_reading(self):
        file_id = self.stored_file(
            self.analyses["open"],
            "S.csv",
            b"350,1,10\n351,2,10\n",
            config=self.fors,
            licence=ND,
        )

        body = self.body(file_id)

        self.assertEqual(body["id"], ids.data_raw(file_id))
        self.assertEqual(body["format"], "text/csv")
        self.assertEqual(body["xyReading"]["multiY"], "reference-normalize")
        self.assertNotIn("derivedFrom", body["xyReading"])

    def test_an_mca_is_a_clean_csv_body_in_kev(self):
        file_id = self.stored_file(
            self.analyses["open"], "X.mca", (FIXTURES / "elio_xrf.mca").read_bytes()
        )

        body = self.body(file_id)

        self.assertEqual(body["id"], ids.data_series(file_id))
        self.assertEqual(body["xyReading"]["x"]["unit"], "keV")
        self.assertEqual(
            body["xyReading"]["derivedFrom"]["format"], "application/octet-stream"
        )

    def test_the_body_of_an_unreadable_raw_file_has_no_reading(self):
        file_id = self.stored_file(self.analyses["open"], "X.spc", b"\x00\x01")

        body = self.body(file_id)

        self.assertEqual(body["id"], ids.data_raw(file_id))
        self.assertEqual(body["format"], "application/octet-stream")
        self.assertNotIn("xyReading", body)

    def test_v2_carries_the_reading_and_our_context(self):
        self.stored_file(
            self.analyses["open"], "S.csv", b"350,1,10\n351,2,10\n", config=self.fors
        )

        annotation = self.visitor.get(
            f"/iiif/v2/annotation/{self.analyses['open'].pk}"
        ).json()

        self.assertEqual(
            annotation["@context"],
            [ids.xy_context(), "http://iiif.io/api/presentation/2/context.json"],
        )
        dataset = next(
            r for r in annotation["resource"] if r["@type"] == "dctypes:Dataset"
        )
        self.assertEqual(dataset["xyReading"]["type"], "XYReading")
