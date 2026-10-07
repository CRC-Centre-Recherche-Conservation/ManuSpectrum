import copy
import uuid
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from arches.app.models.models import IIIFManifest

OLD = "http://dev.example:8000"
NEW = "https://example.org/"
CANTALOUPE = "http://localhost:8182/iiif"


def manifest_json(origin=OLD, name="page"):
    service = f"{origin}/iiifserver/iiif/2/{name}.jpg"
    canvas_id = f"{CANTALOUPE}/manifest/canvas/{uuid.uuid4()}.json"
    return {
        "@context": "http://iiif.io/api/presentation/2/context.json",
        "@type": "sc:Manifest",
        "label": "m",
        "thumbnail": {"@id": service + "/full/!300,300/0/default.jpg"},
        "sequences": [
            {
                "@id": f"{CANTALOUPE}/manifest/sequence/TBD.json",
                "canvases": [
                    {
                        "@id": canvas_id,
                        "images": [
                            {
                                "@id": f"{CANTALOUPE}/manifest/annotation/x.json",
                                "on": canvas_id,
                                "resource": {
                                    "@id": service + "/full/full/0/default.jpg",
                                    "service": {
                                        "@context": "http://iiif.io/api/image/2/context.json",
                                        "@id": service,
                                    },
                                },
                            }
                        ],
                        "thumbnail": {
                            "@id": service + "/full/!300,300/0/default.jpg",
                            "service": {"@id": service},
                        },
                    }
                ],
            }
        ],
    }


def make(data, label="m"):
    return IIIFManifest.objects.create(
        label=label, url=f"/manifest/{uuid.uuid4()}", manifest=data
    )


def run(*args):
    out = StringIO()
    call_command("rewrite_image_service_urls", *args, stdout=out)
    return out.getvalue()


class RewriteImageServiceUrlsTests(TestCase):
    def stored(self, row):
        return IIIFManifest.objects.get(pk=row.pk).manifest

    def test_rewrites_image_service_and_thumbnail_ids(self):
        row = make(manifest_json())
        run("--from", OLD, "--to", NEW)
        data = self.stored(row)
        canvas = data["sequences"][0]["canvases"][0]
        res = canvas["images"][0]["resource"]
        base = "https://example.org/iiifserver/iiif/2/page.jpg"
        self.assertEqual(res["service"]["@id"], base)
        self.assertEqual(res["@id"], base + "/full/full/0/default.jpg")
        self.assertEqual(canvas["thumbnail"]["service"]["@id"], base)
        self.assertEqual(
            canvas["thumbnail"]["@id"], base + "/full/!300,300/0/default.jpg"
        )
        self.assertEqual(
            data["thumbnail"]["@id"], base + "/full/!300,300/0/default.jpg"
        )
        self.assertNotIn(OLD, str(data))

    def test_leaves_everything_else_untouched(self):
        data = manifest_json()
        data["seeAlso"] = "https://gallica.bnf.fr/iiif/ark:/x/manifest.json"
        data["attribution"] = f"mirror of {OLD}/iiifserver/iiif/2/x"
        data["related"] = f"https://other.example/?u={OLD}/iiifserver/a"
        data["homepage"] = f"{OLD}/en/report/1"
        row = make(data)
        before = copy.deepcopy(data)
        run("--from", OLD, "--to", NEW)
        after = self.stored(row)
        for key in ("@context", "seeAlso", "attribution", "related", "homepage"):
            self.assertEqual(after[key], before[key])
        canvas_before = before["sequences"][0]["canvases"][0]
        canvas_after = after["sequences"][0]["canvases"][0]
        self.assertEqual(canvas_after["@id"], canvas_before["@id"])
        self.assertEqual(after["sequences"][0]["@id"], before["sequences"][0]["@id"])
        self.assertEqual(
            canvas_after["images"][0]["@id"], canvas_before["images"][0]["@id"]
        )
        self.assertEqual(canvas_after["images"][0]["on"], canvas_before["@id"])

    def test_other_origin_is_untouched(self):
        row = make(manifest_json(origin="http://elsewhere.example:8000"))
        before = self.stored(row)
        run("--from", OLD, "--to", NEW)
        self.assertEqual(self.stored(row), before)

    def test_dry_run_counts_and_writes_nothing(self):
        row = make(manifest_json())
        make(manifest_json(origin="http://elsewhere.example"))
        before = self.stored(row)
        output = run("--from", OLD, "--to", NEW, "--dry-run")
        self.assertEqual(self.stored(row), before)
        self.assertIn("1 manifest", output)
        self.assertIn("5 URL", output)
        self.assertNotIn(OLD, output)
        self.assertNotIn("example.org", output)

    def test_second_run_changes_nothing(self):
        make(manifest_json())
        first = run("--from", OLD, "--to", NEW)
        second = run("--from", OLD, "--to", NEW)
        self.assertIn("1 manifest", first)
        self.assertIn("0 manifest", second)

    @override_settings(PUBLIC_SERVER_ADDRESS="https://default.example/")
    def test_to_defaults_to_public_server_address(self):
        row = make(manifest_json())
        run("--from", OLD)
        self.assertIn("https://default.example/iiifserver/", str(self.stored(row)))

    def test_to_must_end_with_a_slash(self):
        with self.assertRaises(CommandError):
            run("--from", OLD, "--to", "https://example.org")

    def test_from_must_be_an_origin(self):
        for bad in (
            "dev.example",
            "ftp://dev.example",
            f"{OLD}/",
            f"{OLD}/iiifserver",
            "http://",
            "",
        ):
            with self.subTest(bad=bad), self.assertRaises(CommandError):
                run("--from", bad, "--to", NEW)

    def test_update_does_not_call_save(self):
        from unittest.mock import patch

        row = make(manifest_json())
        with patch.object(IIIFManifest, "save", side_effect=AssertionError("save")):
            run("--from", OLD, "--to", NEW)
        self.assertIn("example.org", str(self.stored(row)))

    def test_output_names_counts_only(self):
        make(manifest_json())
        output = run("--from", OLD, "--to", NEW)
        self.assertNotIn("http", output)
