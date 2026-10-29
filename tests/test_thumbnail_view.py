"""What the project's thumbnail route adds to the Arches one.

Search results ask for one thumbnail per row, and each miss costs the fetchers
a manifest fetch plus an image fetch from a library server. The view answers
with the validators that stop the browser asking again; the fetchers themselves
are exercised in tests/test_search_thumbnail_fetchers.py.

Usage:
    python manage.py test tests.test_thumbnail_view --settings="tests.test_settings"
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from urllib.parse import urlparse

import requests
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from manuspectrum.utils.search_thumbnail_fetchers import _fetch_thumbnail
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
        readable = mock.patch(
            "manuspectrum.views.thumbnail.user_can_read_resource", return_value=True
        )
        self.readable = readable.start()
        self.addCleanup(readable.stop)

    def get(self, **headers):
        request = self.factory.get(f"/thumbnail/{RESOURCE_ID}", **headers)
        request.user = mock.sentinel.reader
        return request

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

        request = self.factory.head(f"/thumbnail/{RESOURCE_ID}")
        request.user = mock.sentinel.reader
        response = self.view(request, resource_id=RESOURCE_ID)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertIn("max-age", response.headers["Cache-Control"])


class ThumbnailHostDownTests(SimpleTestCase):
    """A thumbnail whose image server does not answer fails fast, once per host."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.view = CachedThumbnailView.as_view()
        self.calls = []
        self.lock = threading.Lock()
        session = mock.MagicMock()
        session.get.side_effect = self.refuse
        for target in (
            "manuspectrum.views.thumbnail.user_can_read_resource",
            "manuspectrum.utils.http.assert_url_is_safe",
            "manuspectrum.utils.http.get_iiif_session",
            "manuspectrum.utils.http._get_iiif_budget_session",
        ):
            patcher = mock.patch(target)
            started = patcher.start()
            self.addCleanup(patcher.stop)
            if target.endswith("user_can_read_resource"):
                started.return_value = True
            elif target.endswith("assert_url_is_safe"):
                started.side_effect = lambda url, **_: urlparse(url)
            else:
                started.return_value = session
        patcher = mock.patch.object(
            CachedThumbnailView, "get_thumbnail_fetcher", side_effect=self.fetcher
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def refuse(self, url, timeout=None, **kwargs):
        with self.lock:
            self.calls.append((url, timeout))
        time.sleep(0.05)
        raise requests.exceptions.ConnectTimeout(url)

    @staticmethod
    def fetcher(resource_id):
        """A fetcher that reads its image the way the project's fetchers do."""

        def get_thumbnail(retrieve=False):
            try:
                return _fetch_thumbnail(f"https://{resource_id}.example/full.jpg")
            except Exception:
                return None

        fake = mock.MagicMock()
        fake.get_thumbnail.side_effect = get_thumbnail
        return fake

    def get(self, host="down"):
        request = RequestFactory().get(f"/thumbnail/{RESOURCE_ID}")
        request.user = mock.sentinel.reader
        return self.view(request, resource_id=host)

    @override_settings(SEARCH_THUMBNAIL_CONNECT_TIMEOUT=2.5)
    def test_a_host_that_does_not_connect_is_tried_once_with_a_short_connect(self):
        response = self.get()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(self.calls), 1)
        connect, _read = self.calls[0][1]
        self.assertLessEqual(connect, 2.5)

    def test_a_host_found_down_is_skipped_by_every_request_until_it_expires(self):
        self.get()
        self.get()
        self.get(host="other")

        self.assertEqual(
            [url for url, _ in self.calls],
            ["https://down.example/full.jpg", "https://other.example/full.jpg"],
        )

    @override_settings(SEARCH_THUMBNAIL_HOST_DOWN_TTL=0.2)
    def test_a_host_is_tried_again_once_its_ttl_has_passed(self):
        self.get()
        time.sleep(0.3)
        self.get()

        self.assertEqual(len(self.calls), 2)

    def test_a_host_tripped_in_one_thread_is_skipped_by_every_other_thread(self):
        with ThreadPoolExecutor(max_workers=1) as pool:
            tripping = pool.submit(self.get).result().status_code
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=10) as pool:
            others = list(pool.map(lambda _: self.get().status_code, range(10)))

        self.assertEqual([tripping] + others, [404] * 11)
        self.assertEqual(len(self.calls), 1)
        self.assertLess(time.monotonic() - started, 1)
