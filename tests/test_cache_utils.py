import threading
import time
from unittest.mock import MagicMock

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase

from manuspectrum.utils.cache import get_or_build, if_match_allows, stable_cache_key


class StableCacheKeyTests(SimpleTestCase):
    def test_is_deterministic(self):
        self.assertEqual(stable_cache_key("p", "a", 1), stable_cache_key("p", "a", 1))

    def test_differs_on_any_part(self):
        self.assertNotEqual(
            stable_cache_key("p", "a", 1), stable_cache_key("p", "a", 2)
        )
        self.assertNotEqual(stable_cache_key("p", "a"), stable_cache_key("q", "a"))

    def test_hides_the_input_and_bounds_the_length(self):
        url = "https://example.org/" + "x" * 500 + "?q=1 2"
        key = stable_cache_key("iiif", url)
        self.assertNotIn("example.org", key)
        self.assertNotIn(" ", key)
        self.assertEqual(len(key), len("iiif:") + 40)

    def test_joining_cannot_collide(self):
        self.assertNotEqual(
            stable_cache_key("p", "a,b", "c"), stable_cache_key("p", "a", "b,c")
        )


class GetOrBuildTests(SimpleTestCase):
    KEY = "test:get-or-build"

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_miss_builds_once_and_caches(self):
        build = MagicMock(return_value={"v": 1})
        self.assertEqual(get_or_build(self.KEY, build, 60), {"v": 1})
        self.assertEqual(get_or_build(self.KEY, build, 60), {"v": 1})
        build.assert_called_once()
        self.assertIsNone(cache.get(self.KEY + ":lock"))

    def test_none_is_not_cached_and_the_lock_is_released(self):
        build = MagicMock(return_value=None)
        self.assertIsNone(get_or_build(self.KEY, build, 60))
        self.assertIsNone(cache.get(self.KEY))
        self.assertIsNone(cache.get(self.KEY + ":lock"))

    def test_empty_values_are_cached(self):
        build = MagicMock(return_value=[])
        get_or_build(self.KEY, build, 60)
        get_or_build(self.KEY, build, 60)
        build.assert_called_once()

    def test_a_failing_build_releases_the_lock_and_propagates(self):
        with self.assertRaises(RuntimeError):
            get_or_build(self.KEY, MagicMock(side_effect=RuntimeError("boom")), 60)
        self.assertIsNone(cache.get(self.KEY + ":lock"))
        self.assertEqual(get_or_build(self.KEY, lambda: "ok", 60), "ok")

    def test_waits_for_the_holder_instead_of_rebuilding(self):
        cache.add(self.KEY + ":lock", 1, 60)  # another worker is building

        def holder_finishes():
            time.sleep(0.2)
            cache.set(self.KEY, "from-holder", 60)

        holder = threading.Thread(target=holder_finishes, daemon=True)
        self.addCleanup(holder.join)
        holder.start()
        build = MagicMock(return_value="from-me")
        self.assertEqual(
            get_or_build(self.KEY, build, 60, wait=2.0, poll=0.05), "from-holder"
        )
        build.assert_not_called()

    def test_builds_itself_when_the_holder_never_delivers(self):
        cache.add(self.KEY + ":lock", 1, 60)
        build = MagicMock(return_value="fallback")
        started = time.monotonic()
        self.assertEqual(
            get_or_build(self.KEY, build, 60, wait=0.3, poll=0.05), "fallback"
        )
        self.assertGreaterEqual(time.monotonic() - started, 0.3)
        build.assert_called_once()
        self.assertEqual(cache.get(self.KEY), "fallback")


class IfMatchTests(SimpleTestCase):
    def allows(self, header, etag='"abc"'):
        headers = {} if header is None else {"If-Match": header}
        return if_match_allows(RequestFactory().put("/", headers=headers), etag)

    def test_an_absent_header_allows_the_write(self):
        self.assertTrue(self.allows(None))

    def test_the_current_tag_allows_the_write(self):
        self.assertTrue(self.allows('"abc"'))

    def test_another_tag_refuses_the_write(self):
        self.assertFalse(self.allows('"abd"'))

    def test_a_star_allows_the_write(self):
        self.assertTrue(self.allows("*"))

    def test_one_tag_of_a_list_is_enough(self):
        self.assertTrue(self.allows('"x", "abc"'))

    def test_a_weakened_copy_of_the_current_tag_allows_the_write(self):
        self.assertTrue(self.allows('W/"abc"'))

    def test_a_weakened_copy_of_another_tag_refuses_the_write(self):
        self.assertFalse(self.allows('W/"abd"'))

    def test_an_empty_header_refuses_the_write(self):
        self.assertFalse(self.allows(""))
