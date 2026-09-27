"""``/iiif/data/<file>/raw`` and ``/iiif/data/<file>/series.csv`` (C4, C9).

Files are written under the test's own ``MEDIA_ROOT`` (``ExplorerCase.setUp``).

Usage:
    python manage.py test tests.test_iiif_data --settings=tests.test_settings
"""

import json
import uuid
from pathlib import Path

from django.contrib.auth.models import Group, User
from django.test import Client, override_settings

from arches.app.models.models import File, TileModel
from arches.app.utils.permission_backend import assign_perm

from manuspectrum.constants.xy_presets import XY_PRESETS
from manuspectrum.models import RendererConfig
from manuspectrum.utils.spectrum_preview import read_series
from tests.explorer_fixtures import IIIFCase

FIXTURES = Path(__file__).parent / "fixtures" / "xy"
ND = {"id": "CC-BY-ND-4.0", "url": "https://creativecommons.org/licenses/by-nd/4.0/"}
PUBLIC = "public, no-cache"
PRIVATE = "private, no-store"


class DataCase(IIIFCase):
    def setUp(self):
        super().setUp()
        self.visitor = Client()
        self.reader = Client()
        self.reader.force_login(self.editor)
        self.fors = str(uuid.uuid4())
        RendererConfig.objects.create(
            configid=self.fors,
            rendererid=uuid.uuid4(),
            name="FORS",
            config=XY_PRESETS["fors"]["config"],
        )

    def raw(self, file_id, client=None, **headers):
        return (client or self.visitor).get(f"/iiif/data/{file_id}/raw", **headers)

    def series(self, file_id, client=None, **headers):
        return (client or self.visitor).get(
            f"/iiif/data/{file_id}/series.csv", **headers
        )

    def body(self, response):
        return (
            b"".join(response.streaming_content)
            if response.streaming
            else response.content
        )

    def stored_path(self, file_id):
        return File.objects.get(pk=file_id).path.path

    def fors_file(self, **options):
        content = (FIXTURES / "fors_reference.csv").read_bytes()
        return self.stored_file(
            self.analyses["open"], "fors.csv", content, config=self.fors, **options
        )


class RawTests(DataCase):
    def test_the_raw_file_streams_with_its_true_type(self):
        file_id = self.fors_file()

        response = self.raw(file_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertEqual(
            self.body(response), (FIXTURES / "fors_reference.csv").read_bytes()
        )
        self.assertTrue(response["Content-Disposition"].startswith("attachment;"))
        self.assertIn("fors.csv", response["Content-Disposition"])

    def test_an_mca_is_octet_stream_and_an_asd_is_not_common_lisp(self):
        mca = self.stored_file(self.analyses["open"], "X.mca", b"# a\n1\n")
        asd = self.stored_file(self.analyses["open"], "Y.asd", b"as8")

        for file_id in (mca, asd):
            with self.subTest(file_id=file_id):
                self.assertEqual(
                    self.raw(file_id)["Content-Type"], "application/octet-stream"
                )

    def test_the_file_name_cannot_inject_a_header(self):
        file_id = self.stored_file(self.analyses["open"], "a.csv", b"1,2\n3,4\n")
        tile = TileModel.objects.get(
            nodegroup_id=self.nodes[
                ("analysis", "measurement_point_data")
            ].nodegroup_id,
            resourceinstance=self.analyses["open"],
        )
        data = dict(tile.data)
        for values in data.values():
            for entry in values:
                entry["name"] = '../evil"\r\nSet-Cookie: x=1;.csv'
        TileModel.objects.filter(pk=tile.pk).update(data=data)

        response = self.raw(file_id)

        disposition = response["Content-Disposition"]
        self.assertNotIn("\r", disposition)
        self.assertNotIn("\n", disposition)
        self.assertNotIn("/", disposition.split("filename", 1)[1].replace("%2F", ""))
        self.assertFalse(response.has_header("Set-Cookie"))

    def test_nosniff_is_set(self):
        file_id = self.fors_file()

        for response in (self.raw(file_id), self.series(file_id)):
            self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_a_public_file_is_public_no_cache_with_an_etag_and_answers_304(self):
        file_id = self.fors_file()

        for get in (self.raw, self.series):
            with self.subTest(route=get.__name__):
                response = get(file_id)
                self.assertEqual(response["Cache-Control"], PUBLIC)
                self.assertEqual(response["Access-Control-Allow-Origin"], "*")
                etag = response["ETag"]
                again = get(file_id, HTTP_IF_NONE_MATCH=etag)
                self.assertEqual(again.status_code, 304)

    def test_unknown_is_404(self):
        for get in (self.raw, self.series):
            with self.subTest(route=get.__name__):
                response = get(uuid.uuid4())
                self.assertEqual(response.status_code, 404)
                self.assertEqual(self.body(response), b"")
                self.assertEqual(response["Access-Control-Allow-Origin"], "*")


class GuardTests(DataCase):
    def test_a_hidden_resource_is_401_to_the_visitor_and_403_to_a_signed_in_reader(
        self,
    ):
        file_id = self.fors_file()
        self.embargo(self.analyses["open"])
        stranger = User.objects.create_user("data_stranger", password="pw")
        stranger.groups.add(Group.objects.get(name="Resource Editor"))
        assign_perm("no_access_to_resourceinstance", stranger, self.analyses["open"])
        signed_in = Client()
        signed_in.force_login(stranger)

        for get in (self.raw, self.series):
            with self.subTest(route=get.__name__):
                refused = get(file_id)
                self.assertEqual(refused.status_code, 401)
                self.assertEqual(refused["Cache-Control"], PRIVATE)
                self.assertIn("Bearer", refused["WWW-Authenticate"])
                body = json.loads(self.body(refused))
                self.assertEqual(body["type"], "Dataset")
                route = "raw" if get == self.raw else "series.csv"
                self.assertTrue(body["id"].endswith(f"/iiif/data/{file_id}/{route}"))
                self.assertEqual(refused["Access-Control-Allow-Origin"], "*")
                forbidden = get(file_id, signed_in)
                self.assertEqual(forbidden.status_code, 403)
                self.assertEqual(self.body(forbidden), b"")
                granted = get(file_id, self.reader)
                self.assertEqual(granted.status_code, 200)
                self.assertEqual(granted["Cache-Control"], PRIVATE)

    def test_a_restricted_nodegroup_file_is_refused(self):
        file_id = self.fors_file()
        self.restrict_nodegroup(
            self.nodes[("analysis", "measurement_point_data")].nodegroup_id,
            self.editor,
        )

        self.assertEqual(self.raw(file_id).status_code, 401)
        self.assertEqual(self.raw(file_id, self.reader).status_code, 200)

    def test_a_file_named_only_in_tile_data_of_another_resource_is_refused(self):
        file_id = self.stored_file(
            self.analyses["embargoed"], "hidden.csv", b"1,2\n3,4\n"
        )
        self.tile(
            self.analyses["on_document"],
            "measurement_point_data",
            [{"file_id": file_id, "name": "hidden.csv", "type": "text/csv"}],
        )
        self.embargo(self.analyses["embargoed"])

        self.assertEqual(self.raw(file_id).status_code, 401)


class SeriesTests(DataCase):
    def test_the_clean_csv_is_the_configured_curve_never_decimated(self):
        file_id = self.fors_file()
        expected = json.loads((FIXTURES / "fors_reference.expected.json").read_text())

        response = self.series(file_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"], "text/csv; charset=utf-8; header=present"
        )
        lines = self.body(response).decode().splitlines()
        self.assertEqual(lines[0], "Wavelength (nm),Reflectance (0-1)")
        rows = [tuple(map(float, line.split(","))) for line in lines[1:]]
        self.assertEqual(rows, list(zip(expected["x"], expected["y"])))

    def test_every_point_is_written_repr_exact(self):
        rows = "".join(f"{350 + i},{i / 7},{1 + i}\n" for i in range(3000))
        file_id = self.stored_file(
            self.analyses["open"], "big.csv", rows.encode(), config=self.fors
        )
        path = self.stored_path(file_id)

        lines = self.body(self.series(file_id)).decode().splitlines()[1:]

        series = read_series(path, XY_PRESETS["fors"]["config"])
        self.assertEqual(len(lines), 3000)
        self.assertEqual(
            lines, [f"{repr(x)},{repr(y)}" for x, y in zip(series["x"], series["y"])]
        )

    def rename(self, file_id, name):
        tile = File.objects.get(pk=file_id).tile
        data = {
            node: [
                {**entry, "name": name} if entry.get("file_id") == file_id else entry
                for entry in entries
            ]
            for node, entries in tile.data.items()
        }
        TileModel.objects.filter(pk=tile.pk).update(data=data)

    def test_an_instrument_file_has_no_clean_csv_and_serves_its_raw_bytes(self):
        content = (FIXTURES / "elio_xrf.mca").read_bytes()
        file_id = self.stored_file(self.analyses["open"], "X.mca", content)

        raw = self.raw(file_id)

        self.assertEqual(self.series(file_id).status_code, 404)
        self.assertEqual(raw.status_code, 200)
        self.assertEqual(raw["Content-Type"], "application/octet-stream")
        self.assertEqual(self.body(raw), content)

    def test_the_entry_name_decides_the_format_of_the_clean_csv(self):
        file_id = self.stored_file(self.analyses["open"], "X.dat", b"1,2\n3,4\n")
        self.rename(file_id, "X.csv")

        response = self.series(file_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.body(response).decode().splitlines(), ["x,y", "1.0,2.0", "3.0,4.0"]
        )

    def test_a_text_file_named_as_an_instrument_file_has_no_clean_csv(self):
        file_id = self.stored_file(self.analyses["open"], "X.csv", b"1,2\n3,4\n")
        self.rename(file_id, "X.mca")

        self.assertEqual(self.series(file_id).status_code, 404)

    def test_a_no_derivatives_file_has_no_clean_csv(self):
        file_id = self.fors_file(licence=ND)

        self.assertEqual(self.series(file_id).status_code, 404)
        self.assertEqual(self.raw(file_id).status_code, 200)

    def test_an_unsupported_format_has_no_clean_csv(self):
        file_id = self.stored_file(self.analyses["open"], "a.spc", b"1,2\n3,4\n")

        self.assertEqual(self.series(file_id).status_code, 404)

    @override_settings(SPECTRUM_PREVIEW_MAX_BYTES=10)
    def test_an_over_size_file_has_no_clean_csv(self):
        file_id = self.fors_file()

        self.assertEqual(self.series(file_id).status_code, 404)

    def test_a_file_with_fewer_than_two_points_has_no_clean_csv(self):
        file_id = self.stored_file(self.analyses["open"], "one.csv", b"1,2\n")

        self.assertEqual(self.series(file_id).status_code, 404)
