"""Search thumbnails of a Document whose manifest is local (``/manifest/<uuid>``)."""

import uuid
from types import SimpleNamespace
from unittest import mock

from arches.app.models.models import IIIFManifest
from django.test import TestCase

from manuspectrum.utils.search_thumbnail_fetchers import DocumentThumbnailFetcher

FETCHERS = "manuspectrum.utils.search_thumbnail_fetchers"
TILE_MODEL = "arches.app.models.models.TileModel"
REMOTE_FETCH = "manuspectrum.utils.iiif_tools.fetch_iiif_manifest"
SAFE_FETCH = f"{FETCHERS}.safe_fetch"
RESOURCE = SimpleNamespace(resourceinstanceid=uuid.uuid4())
THUMBNAIL = "https://img.example.org/thumb.jpg"
JPEG_BYTES = b"\xff\xd8\xff" + b"JPEGDATA"
MANIFEST = {
    "@context": "http://iiif.io/api/presentation/3/context.json",
    "id": "https://example.org/m.json",
    "thumbnail": [{"id": THUMBNAIL}],
}


def tiles_of(value):
    qs = mock.MagicMock()
    qs.__iter__.side_effect = lambda: iter([SimpleNamespace(data={"n": value})])
    return qs


def image():
    return SimpleNamespace(
        status_code=200,
        content=JPEG_BYTES,
        headers={"Content-Type": "image/jpeg"},
        url=THUMBNAIL,
    )


@mock.patch(SAFE_FETCH)
@mock.patch(REMOTE_FETCH)
@mock.patch(TILE_MODEL)
class LocalManifestThumbnailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.stored = IIIFManifest.objects.create(
            globalid=uuid.uuid4(),
            url="https://example.org/m.json",
            label="Local",
            description="",
            manifest=MANIFEST,
        )

    def thumbnail(self, tile_model, value):
        tile_model.objects.filter.return_value = tiles_of(value)
        return DocumentThumbnailFetcher(RESOURCE).get_thumbnail(retrieve=True)

    def test_a_relative_local_manifest_is_read_from_the_database(
        self, tile_model, remote, safe_fetch
    ):
        safe_fetch.return_value = image()

        found = self.thumbnail(tile_model, f"/manifest/{self.stored.globalid}")

        self.assertEqual(found, (JPEG_BYTES, "image/jpeg"))
        remote.assert_not_called()
        self.assertEqual(safe_fetch.call_args.args[0], THUMBNAIL)

    def test_a_language_prefixed_local_manifest_is_read_from_the_database(
        self, tile_model, remote, safe_fetch
    ):
        safe_fetch.return_value = image()

        found = self.thumbnail(tile_model, f"/fr/manifest/{self.stored.globalid}")

        self.assertEqual(found, (JPEG_BYTES, "image/jpeg"))
        remote.assert_not_called()

    def test_an_unknown_local_manifest_answers_no_thumbnail_without_a_fetch(
        self, tile_model, remote, safe_fetch
    ):
        self.assertIsNone(self.thumbnail(tile_model, f"/manifest/{uuid.uuid4()}"))
        remote.assert_not_called()
        safe_fetch.assert_not_called()

    def test_a_remote_manifest_still_goes_through_the_guarded_fetch(
        self, tile_model, remote, safe_fetch
    ):
        remote.return_value = SimpleNamespace(status_code=200, json=lambda: MANIFEST)
        safe_fetch.return_value = image()

        found = self.thumbnail(tile_model, "https://elsewhere.example/manifest.json")

        self.assertEqual(found, (JPEG_BYTES, "image/jpeg"))
        remote.assert_called_once_with("https://elsewhere.example/manifest.json")
