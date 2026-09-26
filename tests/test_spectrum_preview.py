"""The spectrum preview: parser, decimator and the HTTP contract of the view.

No database and no Elasticsearch: the one row the view reads is behind
``file_record``, which is patched, or behind ``_load_file_record`` when the memo
in front of it is under test, and the files themselves are written to a
temporary directory. The decimator is exercised on a signal whose global
extremes are known, because keeping them is the whole point of a min/max
decimation.

Usage:
    python manage.py test tests.test_spectrum_preview --settings="tests.test_settings"
"""

import json
import math
import os
import tempfile
import uuid
from unittest import mock

from django.conf import settings
from django.core.exceptions import ValidationError
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import Resolver404, resolve, reverse

from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.utils.public_visibility import VisibleSet
from manuspectrum.utils.spectrum_preview import (
    build_preview,
    decimate,
    is_supported,
    parse_rows,
    read_series,
)
from manuspectrum.utils.xy_transforms import (
    SUPPORTED_MULTI_Y,
    SUPPORTED_ROLES,
    apply_config,
    multi_y_handling,
    reference_normalize,
    resolve_columns,
)
from manuspectrum.views.spectrum_preview import (
    SpectrumPreviewView,
    file_record,
    file_record_key,
    stamped_config_id,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "xy")

FILE_ID = "3f2b1c44-2c0e-4f2e-9f3a-9a1d0c5e7b21"
RESOURCE_ID = "8d1e2f30-4a5b-4c6d-8e9f-0a1b2c3d4e5f"
CONFIG_ID = "7a1c3f80-5d21-4e63-9b0a-2c4f8e1d6a03"
NODEGROUP_ID = "c4a9e6d2-1f3b-4e8a-9d57-6b0e2f1a3c88"

# The FORS preset, as the seeded row holds it.
FORS_CONFIG = {
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

FORS_CSV = """wavelength,tgt_count,ref_count
350.0,8.0,80.0
351.0,9.0,90.0
352.0,5.0,0.0
353.0,6.0,120.0
"""

CSV_LINES = [
    "wavelength,tgt_count,ref_count",
    "400.0,1.0,9",
    "400.5,2.5,9",
    "401.0,3.5,9",
    "",
    "401.5,4.5,9",
]

TAB_LINES = [
    "\r",
    "699.859825\t9.80392\r",
    "699.874089\t12.2549\r",
    "699.888354\t15.4412\r",
]


def sine(count):
    """`count` points of a sine, whose extremes sit away from both ends."""
    return [(float(i), math.sin(i * 2 * math.pi / count)) for i in range(count)]


class ParseRowsTests(SimpleTestCase):
    def test_every_column_of_a_row_is_read(self):
        rows = list(parse_rows(CSV_LINES))

        self.assertEqual(
            rows[1:],
            [
                [400.0, 1.0, 9.0],
                [400.5, 2.5, 9.0],
                [401.0, 3.5, 9.0],
                [401.5, 4.5, 9.0],
            ],
        )

    def test_a_header_reads_as_a_row_of_nothing_numeric(self):
        rows = list(parse_rows(CSV_LINES))

        self.assertTrue(all(math.isnan(value) for value in rows[0]))

    def test_tab_separated_values_with_carriage_returns_are_read(self):
        rows = list(parse_rows(TAB_LINES))

        self.assertEqual(
            rows,
            [[699.859825, 9.80392], [699.874089, 12.2549], [699.888354, 15.4412]],
        )

    def test_a_row_holding_a_single_value_is_not_a_row(self):
        rows = list(parse_rows(["# header", "1", "2", "3,4"]))

        self.assertEqual(rows, [[3.0, 4.0]])

    def test_semicolons_and_spaces_separate_columns_too(self):
        rows = list(parse_rows(["1;2", "3 4", "5  6"]))

        self.assertEqual(rows, [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])

    def test_nothing_is_read_from_an_empty_file(self):
        self.assertEqual(list(parse_rows([])), [])


class ResolveColumnsTests(SimpleTestCase):
    def test_a_file_without_a_configuration_reads_its_first_two_columns(self):
        self.assertEqual(
            resolve_columns(None),
            {"x": 0, "y": 1, "reference": None, "dark": None},
        )

    def test_the_assignments_of_a_preset_name_every_role(self):
        self.assertEqual(
            resolve_columns(FORS_CONFIG),
            {"x": 0, "y": 1, "reference": 2, "dark": None},
        )

    def test_the_first_assignment_of_a_role_wins(self):
        config = {
            "display": {
                "columnAssignments": [
                    {"role": "yLeft", "columnIndex": 3},
                    {"role": "yLeft", "columnIndex": 4},
                    {"role": "dark", "columnIndex": 5},
                ]
            }
        }

        self.assertEqual(
            resolve_columns(config),
            {"x": 0, "y": 3, "reference": None, "dark": 5},
        )

    def test_an_unusable_assignment_leaves_the_default_in_place(self):
        config = {
            "display": {
                "columnAssignments": [
                    {"role": "y", "columnIndex": 7},
                    {"role": "yLeft", "columnIndex": -1},
                    {"role": "x", "columnIndex": "nope"},
                    "not a dict",
                ]
            }
        }

        self.assertEqual(
            resolve_columns(config),
            {"x": 0, "y": 1, "reference": None, "dark": None},
        )

    def test_a_handling_that_is_not_a_normalisation_reads_as_separate(self):
        self.assertEqual(multi_y_handling(None), "separate")
        self.assertEqual(multi_y_handling({"multiYHandling": "separate"}), "separate")
        self.assertEqual(
            multi_y_handling({"multiYHandling": "reference-normalize"}),
            "reference-normalize",
        )


class ApplyConfigTests(SimpleTestCase):
    """The corrective transform the XY reader applies before drawing."""

    def points(self, rows, config):
        return list(apply_config(iter(rows), config))

    def test_a_reference_column_divides_the_measurement(self):
        rows = [[350.0, 8.0, 80.0], [351.0, 9.0, 90.0]]

        self.assertEqual(self.points(rows, FORS_CONFIG), [(350.0, 0.1), (351.0, 0.1)])

    def test_a_row_whose_reference_is_zero_is_left_out(self):
        rows = [[350.0, 8.0, 80.0], [352.0, 5.0, 0.0], [353.0, 6.0, 120.0]]

        self.assertEqual(self.points(rows, FORS_CONFIG), [(350.0, 0.1), (353.0, 0.05)])

    def test_a_dark_column_is_subtracted_from_both_terms(self):
        config = {
            "multiYHandling": "reference-normalize",
            "display": {
                "columnAssignments": [
                    {"role": "x", "columnIndex": 0},
                    {"role": "yLeft", "columnIndex": 1},
                    {"role": "reference", "columnIndex": 2},
                    {"role": "dark", "columnIndex": 3},
                ]
            },
        }
        rows = [[350.0, 6.0, 26.0, 1.0]]

        self.assertEqual(self.points(rows, config), [(350.0, 0.2)])

    def test_separate_handling_plots_the_measurement_column_as_it_stands(self):
        config = {
            "multiYHandling": "separate",
            "display": {
                "columnAssignments": [
                    {"role": "x", "columnIndex": 0},
                    {"role": "yLeft", "columnIndex": 2},
                ]
            },
        }
        rows = [[350.0, 8.0, 80.0], [351.0, 9.0, 90.0]]

        self.assertEqual(self.points(rows, config), [(350.0, 80.0), (351.0, 90.0)])

    def test_a_reference_column_without_the_normalisation_is_ignored(self):
        config = dict(FORS_CONFIG, multiYHandling="separate")
        rows = [[350.0, 8.0, 80.0]]

        self.assertEqual(self.points(rows, config), [(350.0, 8.0)])

    def test_a_row_too_short_for_its_columns_is_left_out(self):
        rows = [[350.0, 8.0], [351.0, 9.0, 90.0]]

        self.assertEqual(self.points(rows, FORS_CONFIG), [(351.0, 0.1)])

    def test_non_numeric_rows_are_left_out(self):
        rows = list(parse_rows(["wavelength,tgt,ref", "350.0,8.0,80.0"]))

        self.assertEqual(self.points(rows, FORS_CONFIG), [(350.0, 0.1)])


class SupportedExtensionTests(SimpleTestCase):
    """The readable formats are the ones the XY reader calls canonical."""

    def test_the_canonical_text_format_is_supported(self):
        self.assertEqual(settings.XY_TEXT_FILE_FORMATS, ["csv"])
        for name in ("a.csv", "b.CSV"):
            self.assertTrue(is_supported(name), name)

    def test_the_converted_and_the_binary_formats_are_not(self):
        for name in ("a.txt", "b.mca", "c.asd", "d.0", "e.tif", "noextension"):
            self.assertFalse(is_supported(name), name)

    @override_settings(XY_TEXT_FILE_FORMATS=["csv", "txt"])
    def test_widening_the_setting_widens_the_preview(self):
        self.assertTrue(is_supported("a.txt"))
        self.assertTrue(is_supported("b.csv"))
        self.assertFalse(is_supported("c.mca"))


class DecimateTests(SimpleTestCase):
    def test_a_short_series_comes_back_whole(self):
        points = [(float(i), float(i * i)) for i in range(5)]

        result = decimate(iter(points), 200)

        self.assertEqual(result["x"], [0.0, 1.0, 2.0, 3.0, 4.0])
        self.assertEqual(result["y"], [0.0, 1.0, 4.0, 9.0, 16.0])
        self.assertEqual(result["n_source"], 5)
        self.assertFalse(result["decimated"])

    def test_a_thousand_points_become_two_hundred_keeping_both_extremes(self):
        points = sine(1000)

        result = decimate(iter(points), 200)

        self.assertEqual(len(result["x"]), 200)
        self.assertEqual(len(result["y"]), 200)
        self.assertEqual(result["n_source"], 1000)
        self.assertTrue(result["decimated"])
        self.assertEqual(max(result["y"]), max(y for _, y in points))
        self.assertEqual(min(result["y"]), min(y for _, y in points))

    def test_the_kept_points_stay_in_the_order_of_their_x(self):
        result = decimate(iter(sine(1000)), 200)

        self.assertEqual(result["x"], sorted(result["x"]))

    def test_a_large_file_still_fits_the_budget(self):
        result = decimate(iter(sine(136805)), 200)

        self.assertLessEqual(len(result["x"]), 200)
        self.assertEqual(result["n_source"], 136805)
        self.assertEqual(max(result["y"]), max(y for _, y in sine(136805)))

    def test_a_series_of_fewer_than_two_points_has_no_preview(self):
        self.assertIsNone(decimate(iter([(1.0, 2.0)]), 200))
        self.assertIsNone(decimate(iter([]), 200))


class BuildPreviewTests(SimpleTestCase):
    def written(self, text, suffix=".csv"):
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as handle:
            handle.write(text)
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_a_file_without_a_configuration_is_read_on_its_first_two_columns(self):
        result = build_preview(self.written("\n".join(CSV_LINES)), 200)

        self.assertEqual(result["n_source"], 4)
        self.assertEqual(result["x"], [400.0, 400.5, 401.0, 401.5])
        self.assertEqual(result["y"], [1.0, 2.5, 3.5, 4.5])
        self.assertFalse(result["x_reversed"])

    def test_a_fors_file_is_read_as_the_reader_draws_it(self):
        result = build_preview(self.written(FORS_CSV), 200, FORS_CONFIG)

        self.assertEqual(result["x"], [350.0, 351.0, 353.0])
        self.assertEqual(result["y"], [0.1, 0.1, 0.05])
        self.assertEqual(result["n_source"], 3)

    def test_a_reversed_axis_is_carried_to_the_drawing(self):
        config = {"display": {"xReversed": True}}

        result = build_preview(self.written("\n".join(CSV_LINES)), 200, config)

        self.assertTrue(result["x_reversed"])

    def rows(self, points):
        return "\n".join(f"{x},{y}" for x, y in points)

    def test_read_series_keeps_every_point(self):
        path = self.written(self.rows((i, i * 2) for i in range(5000)))

        series = read_series(path)

        self.assertEqual(len(series["x"]), 5000)
        self.assertEqual(series["y"][-1], 9998.0)
        self.assertFalse(series["x_reversed"])

    def test_read_series_applies_the_configuration(self):
        series = read_series(self.written(FORS_CSV), FORS_CONFIG)

        self.assertEqual(series["x"], [350.0, 351.0, 353.0])
        self.assertEqual(series["y"], [0.1, 0.1, 0.05])

    def test_read_series_of_a_single_point_draws_nothing(self):
        self.assertIsNone(read_series(self.written("1,2")))

    def test_build_preview_decimates_what_read_series_reads(self):
        path = self.written(self.rows((i, (i % 7) - 3) for i in range(5000)))

        whole, preview = read_series(path), build_preview(path, 200)

        self.assertLessEqual(len(preview["x"]), 200)
        self.assertEqual(preview["n_source"], len(whole["x"]))
        points = set(zip(whole["x"], whole["y"]))
        self.assertTrue(set(zip(preview["x"], preview["y"])) <= points)
        self.assertEqual(
            (min(preview["y"]), max(preview["y"])), (min(whole["y"]), max(whole["y"]))
        )


class SpectrumPreviewViewTests(SimpleTestCase):
    """The route, the guard, the refusals and the validators."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.factory = RequestFactory()
        self.view = SpectrumPreviewView.as_view()

    def written(self, suffix, text="400.0,1.0\n401.0,2.0\n"):
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as handle:
            handle.write(text)
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def request(self, **headers):
        request = self.factory.get(f"/api/spectrum-preview/{FILE_ID}", **headers)
        request.user = AnonymousUser()
        return request

    def get(self, path, readable=True, config_id=None, config=None, **headers):
        record = None if path is None else (path, RESOURCE_ID, config_id, "ng-1")
        with (
            mock.patch(
                "manuspectrum.views.spectrum_preview.file_record", return_value=record
            ),
            mock.patch(
                "manuspectrum.views.spectrum_preview.visible_set",
                return_value=VisibleSet(
                    analyses=frozenset({RESOURCE_ID} if readable else set())
                ),
            ),
            mock.patch(
                "manuspectrum.views.spectrum_preview.readable_nodegroups",
                return_value=None,
            ),
            mock.patch(
                "manuspectrum.views.spectrum_preview.renderer_config",
                return_value=config or {},
            ),
        ):
            return self.view(self.request(**headers), file_id=FILE_ID)

    def test_the_route_is_language_neutral(self):
        self.assertEqual(
            reverse("api-spectrum-preview", args=[FILE_ID]),
            f"/api/spectrum-preview/{FILE_ID}",
        )

    def test_a_path_that_is_not_a_uuid_does_not_resolve(self):
        with self.assertRaises(Resolver404):
            resolve("/api/spectrum-preview/not-a-uuid")

    def test_a_series_is_served_with_an_etag_and_a_private_lifetime(self):
        response = self.get(self.written(".csv"))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["x"], [400.0, 401.0])
        self.assertEqual(payload["y"], [1.0, 2.0])
        self.assertEqual(payload["n_source"], 2)
        self.assertFalse(payload["decimated"])
        self.assertTrue(response.headers["ETag"].startswith('"'))
        self.assertIn("private", response.headers["Cache-Control"])
        self.assertIn("max-age=86400", response.headers["Cache-Control"])

    def test_a_client_holding_the_current_etag_gets_a_304(self):
        path = self.written(".csv")
        etag = self.get(path).headers["ETag"]

        response = self.get(path, HTTP_IF_NONE_MATCH=etag)

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.headers["ETag"], etag)

    def test_a_client_holding_any_representation_gets_a_304(self):
        path = self.written(".csv")
        etag = self.get(path).headers["ETag"]

        response = self.get(path, HTTP_IF_NONE_MATCH="*")

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.headers["ETag"], etag)

    def test_a_client_listing_several_tags_gets_a_304(self):
        path = self.written(".csv")
        etag = self.get(path).headers["ETag"]

        response = self.get(path, HTTP_IF_NONE_MATCH=f'"other", {etag}')

        self.assertEqual(response.status_code, 304)

    def test_a_client_holding_the_weak_tag_gets_a_304(self):
        path = self.written(".csv")
        etag = self.get(path).headers["ETag"]

        response = self.get(path, HTTP_IF_NONE_MATCH=f"W/{etag}")

        self.assertEqual(response.status_code, 304)

    def test_a_gzipped_series_carries_a_weak_etag_that_revalidates(self):
        path = self.written(".csv", "".join(f"{400 + n}.0,{n}.5\n" for n in range(100)))

        response = self.get(path, HTTP_ACCEPT_ENCODING="gzip")
        again = self.get(
            path, HTTP_ACCEPT_ENCODING="gzip", HTTP_IF_NONE_MATCH=response["ETag"]
        )

        self.assertEqual(response["Content-Encoding"], "gzip")
        self.assertTrue(response["ETag"].startswith('W/"'))
        self.assertEqual(again.status_code, 304)

    def test_the_payload_of_one_file_is_built_once(self):
        path = self.written(".csv")

        with mock.patch(
            "manuspectrum.views.spectrum_preview.build_preview",
            wraps=build_preview,
        ) as build:
            self.get(path)
            self.get(path)

        self.assertEqual(build.call_count, 1)

    def test_a_format_outside_the_canonical_list_has_no_preview(self):
        for suffix in (".asd", ".txt", ".mca"):
            response = self.get(self.written(suffix))

            self.assertEqual(response.status_code, 204, suffix)

    @override_settings(XY_TEXT_FILE_FORMATS=["csv", "txt"])
    def test_a_format_the_setting_adds_is_served(self):
        response = self.get(self.written(".txt"))

        self.assertEqual(response.status_code, 200)

    @override_settings(SPECTRUM_PREVIEW_MAX_BYTES=4)
    def test_a_file_over_the_ceiling_is_not_read(self):
        response = self.get(self.written(".csv"))

        self.assertEqual(response.status_code, 204)

    def test_a_file_holding_a_single_point_has_no_preview(self):
        response = self.get(self.written(".csv", text="400.0,1.0\n"))

        self.assertEqual(response.status_code, 204)

    def test_a_missing_file_has_no_preview(self):
        response = self.get("/nowhere/at/all.csv")

        self.assertEqual(response.status_code, 204)

    def test_the_stored_configuration_shapes_the_series(self):
        path = self.written(".csv", text=FORS_CSV)

        response = self.get(path, config_id=CONFIG_ID, config=FORS_CONFIG)

        payload = json.loads(response.content)
        self.assertEqual(payload["x"], [350.0, 351.0, 353.0])
        self.assertEqual(payload["y"], [0.1, 0.1, 0.05])
        self.assertFalse(payload["x_reversed"])

    def test_two_configurations_of_one_file_are_two_memo_entries(self):
        path = self.written(".csv", text=FORS_CSV)

        raw = json.loads(self.get(path).content)
        normalized = json.loads(
            self.get(path, config_id=CONFIG_ID, config=FORS_CONFIG).content
        )

        self.assertEqual(raw["y"], [8.0, 9.0, 5.0, 6.0])
        self.assertEqual(normalized["y"], [0.1, 0.1, 0.05])

    def test_a_reader_without_the_right_is_refused(self):
        response = self.get(self.written(".csv"), readable=False)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_a_file_no_row_names_is_a_404(self):
        response = self.get(None)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")

    def test_the_guard_runs_before_the_file_is_read(self):
        with mock.patch(
            "manuspectrum.views.spectrum_preview.build_preview"
        ) as build_preview_mock:
            self.get(self.written(".csv"), readable=False)

        build_preview_mock.assert_not_called()


class FileRecordTests(SimpleTestCase):
    """The one database read behind the memo, over a stubbed queryset."""

    def record(self, row):
        from manuspectrum.views import spectrum_preview

        queryset = mock.MagicMock()
        queryset.defer.return_value.select_related.return_value.first.return_value = row
        with mock.patch.object(spectrum_preview.File, "objects") as objects:
            objects.filter.return_value = queryset
            return spectrum_preview._load_file_record(FILE_ID)

    def row(self):
        row = mock.Mock(
            tile=mock.Mock(
                resourceinstance_id=uuid.UUID(RESOURCE_ID),
                nodegroup_id=uuid.UUID(NODEGROUP_ID),
                data={
                    "node-files": [{"file_id": FILE_ID, "rendererConfig": CONFIG_ID}]
                },
            )
        )
        row.path.name = "spectrum.csv"
        row.path.path = "/media/spectrum.csv"
        return row

    def test_a_row_gives_its_path_its_resource_and_its_configuration(self):
        self.assertEqual(
            self.record(self.row())[:3],
            ("/media/spectrum.csv", RESOURCE_ID, CONFIG_ID),
        )

    def test_the_join_carries_the_nodegroup_of_the_tile(self):
        self.assertEqual(self.record(self.row())[3], NODEGROUP_ID)

    def test_a_file_no_tile_holds_has_no_resource_to_check(self):
        row = mock.Mock(tile=None)
        row.path.name = "spectrum.csv"

        self.assertIsNone(self.record(row))

    def test_a_row_without_a_stored_file_is_nothing_to_read(self):
        row = mock.Mock(tile=mock.Mock(resourceinstance_id=uuid.UUID(RESOURCE_ID)))
        row.path.name = ""

        self.assertIsNone(self.record(row))

    def test_a_missing_row_is_nothing_to_read(self):
        self.assertIsNone(self.record(None))


class FileRecordMemoTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_the_join_is_read_once_per_file(self):
        with mock.patch(
            "manuspectrum.views.spectrum_preview._load_file_record",
            return_value=("/tmp/a.csv", "r-1", None, "ng-1"),
        ) as load:
            file_record(FILE_ID)
            file_record(FILE_ID)

        load.assert_called_once()

    def test_an_unknown_file_is_not_memoised(self):
        with mock.patch(
            "manuspectrum.views.spectrum_preview._load_file_record", return_value=None
        ) as load:
            file_record(FILE_ID)
            file_record(FILE_ID)

        self.assertEqual(load.call_count, 2)

    def test_the_memo_key_ignores_the_case_of_the_id(self):
        self.assertEqual(file_record_key(FILE_ID.upper()), file_record_key(FILE_ID))

    def test_an_unknown_file_never_waits_on_a_concurrent_reader(self):
        cache.add(file_record_key(FILE_ID) + ":lock", "held", 10)

        with (
            mock.patch(
                "manuspectrum.views.spectrum_preview._load_file_record",
                return_value=None,
            ) as load,
            mock.patch("manuspectrum.utils.cache.time.sleep") as sleep,
        ):
            self.assertIsNone(file_record(FILE_ID))

        load.assert_called_once()
        sleep.assert_not_called()


class SpectrumPreviewGuardTests(SimpleTestCase):
    """The permission is checked on every request, memo or not."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.view = SpectrumPreviewView.as_view()

    def request(self):
        request = RequestFactory().get(f"/api/spectrum-preview/{FILE_ID}")
        request.user = AnonymousUser()
        return request

    def test_a_memoised_file_is_refused_to_a_reader_who_lost_access(self):
        with (
            mock.patch(
                "manuspectrum.views.spectrum_preview._load_file_record",
                return_value=("/tmp/a.csv", "r-1", None, "ng-1"),
            ) as load,
            mock.patch(
                "manuspectrum.views.spectrum_preview.visible_set",
                side_effect=[
                    VisibleSet(analyses=frozenset({"r-1"})),
                    VisibleSet(analyses=frozenset()),
                ],
            ) as guard,
            mock.patch(
                "manuspectrum.views.spectrum_preview.readable_nodegroups",
                return_value=None,
            ),
            mock.patch(
                "manuspectrum.views.spectrum_preview._series",
                return_value={"x": [0, 1], "y": [0, 1]},
            ),
        ):
            self.assertEqual(
                self.view(self.request(), file_id=FILE_ID).status_code, 200
            )
            self.assertEqual(
                self.view(self.request(), file_id=FILE_ID).status_code, 404
            )

        load.assert_called_once()
        self.assertEqual(guard.call_count, 2)


class SpectrumPreviewNodegroupGuardTests(SimpleTestCase):
    """The read permission on the nodegroup of the tile that holds the file."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.view = SpectrumPreviewView.as_view()

    def get(self, nodegroups, readable=True):
        """The response, with the ``readable_nodegroups`` and ``_series`` mocks."""
        request = RequestFactory().get(f"/api/spectrum-preview/{FILE_ID}")
        request.user = AnonymousUser()
        with (
            mock.patch(
                "manuspectrum.views.spectrum_preview.file_record",
                return_value=("/tmp/a.csv", "r-1", None, "ng-1"),
            ),
            mock.patch(
                "manuspectrum.views.spectrum_preview.visible_set",
                return_value=VisibleSet(
                    analyses=frozenset({"r-1"} if readable else set())
                ),
            ),
            mock.patch(
                "manuspectrum.views.spectrum_preview.readable_nodegroups",
                return_value=nodegroups,
            ) as allowed,
            mock.patch(
                "manuspectrum.views.spectrum_preview._series",
                return_value={"x": [0, 1], "y": [0, 1]},
            ) as series,
        ):
            return self.view(request, file_id=FILE_ID), allowed, series

    def test_a_file_in_a_nodegroup_the_reader_may_not_read_is_refused(self):
        response, _, series = self.get({"other-ng"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        self.assertIn("no-store", response.headers["Cache-Control"])
        series.assert_not_called()

    def test_a_file_in_a_readable_nodegroup_is_served(self):
        response, _, _ = self.get({"other-ng", "ng-1"})

        self.assertEqual(response.status_code, 200)

    def test_no_nodegroup_restriction_checks_nothing_more(self):
        response, _, _ = self.get(None)

        self.assertEqual(response.status_code, 200)

    def test_a_reader_who_reads_no_nodegroup_is_refused(self):
        response, _, series = self.get(set())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b"")
        series.assert_not_called()

    def test_the_nodegroup_is_checked_after_the_resource(self):
        response, allowed, series = self.get({"ng-1"}, readable=False)

        self.assertEqual(response.status_code, 404)
        allowed.assert_not_called()
        series.assert_not_called()


class StampedConfigIdTests(SimpleTestCase):
    """Which configuration a file entry of a tile carries."""

    def test_the_entry_of_the_file_is_found_across_the_nodes_of_a_tile(self):
        data = {
            "node-photos": [{"file_id": str(uuid.uuid4()), "rendererConfig": "other"}],
            "node-files": [
                {"file_id": str(uuid.uuid4())},
                {"file_id": FILE_ID.upper(), "rendererConfig": CONFIG_ID},
            ],
        }

        self.assertEqual(stamped_config_id(data, FILE_ID), CONFIG_ID)

    def test_an_entry_the_trigger_never_stamped_carries_nothing(self):
        data = {"node-files": [{"file_id": FILE_ID, "rendererConfig": ""}]}

        self.assertIsNone(stamped_config_id(data, FILE_ID))

    def test_a_tile_holding_no_such_file_carries_nothing(self):
        data = {"node-text": "a string", "node-files": [{"file_id": str(uuid.uuid4())}]}

        self.assertIsNone(stamped_config_id(data, FILE_ID))
        self.assertIsNone(stamped_config_id(None, FILE_ID))


class RendererConfigTests(SimpleTestCase):
    """Loading a stored configuration, and doing without one."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def loaded(self, side_effect=None, config=None):
        from manuspectrum.views import spectrum_preview

        queryset = mock.MagicMock()
        if side_effect is not None:
            queryset.get.side_effect = side_effect
        else:
            queryset.get.return_value = config
        with mock.patch.object(spectrum_preview.RendererConfig, "objects") as objects:
            objects.values_list.return_value = queryset
            return spectrum_preview.renderer_config(CONFIG_ID), queryset

    def test_a_stored_configuration_is_read_once_and_memoised(self):
        from manuspectrum.views import spectrum_preview

        config, queryset = self.loaded(config=FORS_CONFIG)

        self.assertEqual(config, FORS_CONFIG)
        self.assertEqual(spectrum_preview.renderer_config(CONFIG_ID), FORS_CONFIG)
        self.assertEqual(queryset.get.call_count, 1)

    def test_a_file_that_names_no_configuration_reads_nothing(self):
        from manuspectrum.views import spectrum_preview

        self.assertEqual(spectrum_preview.renderer_config(None), {})

    def test_an_id_naming_no_row_falls_back_to_the_first_two_columns(self):
        from manuspectrum.views import spectrum_preview

        with self.assertLogs("manuspectrum.views.spectrum_preview", "WARNING"):
            config, _ = self.loaded(
                side_effect=spectrum_preview.RendererConfig.DoesNotExist
            )

        self.assertEqual(config, {})
        self.assertEqual(resolve_columns(config)["y"], 1)

    def test_an_id_that_is_not_a_uuid_falls_back_too(self):
        with self.assertLogs("manuspectrum.views.spectrum_preview", "WARNING"):
            config, _ = self.loaded(side_effect=ValidationError("bad uuid"))

        self.assertEqual(config, {})


class GoldenFixtureTests(SimpleTestCase):
    """The fixture the browser-side spec reads, through the Python twin.

    ``media/js/utils/xy-transforms.golden.spec.js`` runs the reader's own
    ``referenceNormalize`` over these same two files. Both sides asserting the
    same numbers is what keeps the two implementations from drifting.
    """

    def test_the_fors_preset_reproduces_the_recorded_curve(self):
        config = XY_PRESETS["fors"]["config"]
        with open(os.path.join(FIXTURES, "fors_reference.csv")) as handle:
            points = list(apply_config(parse_rows(handle), config))
        with open(os.path.join(FIXTURES, "fors_reference.expected.json")) as handle:
            expected = json.load(handle)

        self.assertEqual([point[0] for point in points], expected["x"])
        self.assertEqual([point[1] for point in points], expected["y"])

    def test_the_row_whose_reference_is_zero_is_the_one_left_out(self):
        with open(os.path.join(FIXTURES, "fors_reference.csv")) as handle:
            rows = list(parse_rows(handle))
        columns = resolve_columns(XY_PRESETS["fors"]["config"])

        dropped = [
            row[0] for row in rows[1:] if math.isnan(reference_normalize(row, columns))
        ]

        self.assertEqual(dropped, [352.0])


class PresetCoverageTests(SimpleTestCase):
    """Every seeded preset must declare a correction this twin implements.

    A preset naming a handling or a role the preview cannot reproduce would be
    drawn raw under an axis labelled with a quantity it never computed; this is
    the test that stops it reaching a release.
    """

    def test_every_preset_uses_a_supported_handling_and_supported_roles(self):
        for key, preset in XY_PRESETS.items():
            config = preset["config"]
            display = config.get("display") or {}
            with self.subTest(preset=key):
                self.assertIn(config.get("multiYHandling"), SUPPORTED_MULTI_Y)
                for assignment in display.get("columnAssignments", []):
                    self.assertIn(assignment["role"], SUPPORTED_ROLES)
