"""What the project's thumbnail route adds to the Arches one.

Search results ask for one thumbnail per row, and each miss costs the fetchers
a manifest fetch plus an image fetch from a library server. The view answers
with the validators that stop the browser asking again; the fetchers themselves
are exercised in tests/test_search_thumbnail_fetchers.py.

Usage:
    python manage.py test tests.test_thumbnail_view --settings="tests.test_settings"
"""

from unittest import mock

from django.test import RequestFactory, SimpleTestCase, override_settings

from manuspectrum.views.thumbnail import CachedThumbnailView

RESOURCE_ID = "0e6d1c02-64d0-4a13-8f2a-2a1c9b3f77ad"
JPEG = b"\xff\xd8\xffTHUMB"


def fetcher(thumbnail):
    fake = mock.MagicMock()
    fake.get_thumbnail.return_value = thumbnail
    return fake


class CachedThumbnailViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view = CachedThumbnailView.as_view()

    def get(self, **headers):
        return self.factory.get(f"/thumbnail/{RESOURCE_ID}", **headers)

    @override_settings(SEARCH_THUMBNAIL_MAX_AGE=3600)
    @mock.patch.object(CachedThumbnailView, "get_thumbnail_fetcher")
    def test_a_thumbnail_is_served_with_an_etag_and_a_lifetime(self, get_fetcher):
        get_fetcher.return_value = fetcher((JPEG, "image/jpeg"))

        response = self.view(self.get(), resource_id=RESOURCE_ID)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, JPEG)
        self.assertEqual(response.headers["Content-Type"], "image/jpeg")
        self.assertTrue(response.headers["ETag"].startswith('"'))
        self.assertIn("max-age=3600", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])

    @mock.patch.object(CachedThumbnailView, "get_thumbnail_fetcher")
    def test_a_client_holding_the_current_etag_gets_a_304(self, get_fetcher):
        get_fetcher.return_value = fetcher((JPEG, "image/jpeg"))
        etag = self.view(self.get(), resource_id=RESOURCE_ID).headers["ETag"]

        response = self.view(self.get(HTTP_IF_NONE_MATCH=etag), resource_id=RESOURCE_ID)

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.headers["ETag"], etag)
        self.assertIn("max-age", response.headers["Cache-Control"])

    @mock.patch.object(CachedThumbnailView, "get_thumbnail_fetcher")
    def test_a_stale_etag_gets_the_new_bytes(self, get_fetcher):
        get_fetcher.return_value = fetcher((JPEG, "image/jpeg"))

        response = self.view(
            self.get(HTTP_IF_NONE_MATCH='"0000"'), resource_id=RESOURCE_ID
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, JPEG)

    @mock.patch.object(CachedThumbnailView, "get_thumbnail_fetcher")
    def test_two_resources_do_not_share_an_etag(self, get_fetcher):
        get_fetcher.return_value = fetcher((JPEG, "image/jpeg"))
        first = self.view(self.get(), resource_id=RESOURCE_ID).headers["ETag"]
        get_fetcher.return_value = fetcher((b"\xff\xd8\xffOTHER", "image/jpeg"))

        second = self.view(self.get(), resource_id=RESOURCE_ID).headers["ETag"]

        self.assertNotEqual(first, second)

    @mock.patch.object(CachedThumbnailView, "get_thumbnail_fetcher")
    def test_a_resource_without_a_thumbnail_is_a_plain_404(self, get_fetcher):
        get_fetcher.return_value = fetcher(None)

        response = self.view(self.get(), resource_id=RESOURCE_ID)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Cache-Control", response.headers)
        self.assertNotIn("ETag", response.headers)

    @mock.patch.object(CachedThumbnailView, "get_thumbnail_fetcher")
    def test_a_graph_with_no_fetcher_is_a_plain_404(self, get_fetcher):
        get_fetcher.return_value = None

        response = self.view(self.get(), resource_id=RESOURCE_ID)

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Cache-Control", response.headers)

    @mock.patch.object(CachedThumbnailView, "get_thumbnail_fetcher")
    def test_head_advertises_the_lifetime_without_a_body(self, get_fetcher):
        get_fetcher.return_value = fetcher((JPEG, "image/jpeg"))

        response = self.view(
            self.factory.head(f"/thumbnail/{RESOURCE_ID}"), resource_id=RESOURCE_ID
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertIn("max-age", response.headers["Cache-Control"])
