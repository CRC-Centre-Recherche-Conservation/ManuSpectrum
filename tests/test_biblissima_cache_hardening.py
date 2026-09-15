"""Cache keys and their inputs on the Biblissima proxy (PR-8)."""

import threading
import time
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from manuspectrum.views import biblissima_proxy as bp

HEX40 = "a" * 40


def _editor(username="cache_hardening_editor"):
    user = User.objects.create_user(username, password="pw")
    user.groups.add(Group.objects.get(name="Resource Editor"))
    return user


class HashPrefixVocabularyTests(SimpleTestCase):
    def test_every_prefix_is_accepted_by_the_portal_hash_pattern(self):
        for prefix in bp.BIBLISSIMA_HASH_PREFIXES:
            self.assertTrue(bp._PORTAL_HASH_RE.fullmatch(prefix + HEX40), prefix)

    def test_every_prefix_normalizes_to_the_desc_form(self):
        for prefix in bp.BIBLISSIMA_HASH_PREFIXES:
            self.assertEqual(
                bp._normalize_descriptors(prefix + HEX40), ["desc" + HEX40], prefix
            )


class InputShapeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client.force_login(_editor("cache_hardening_editor"))

    def tearDown(self):
        cache.clear()

    def test_a_malformed_portal_hash_is_refused_before_any_fetch(self):
        with patch.object(bp, "_bib_request") as fetch:
            for bad in (
                "mdataXYZ",
                "mdata" + HEX40 + "x",
                "../etc",
                "mdata" + "A" * 40,
            ):
                resp = self.client.get(
                    "/api/biblissima/manuscript-illuminations", {"portalHash": bad}
                )
                self.assertEqual(resp.status_code, 400, bad)
                self.assertIn("message", resp.json(), bad)
        fetch.assert_not_called()

    def test_a_well_formed_portal_hash_reaches_the_portal(self):
        with patch.object(
            bp, "_bib_request", return_value=MagicMock(text="<html></html>")
        ) as fetch:
            resp = self.client.get(
                "/api/biblissima/manuscript-illuminations",
                {"portalHash": "mdata" + HEX40},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(fetch.call_count, 1)

    def test_a_malformed_descriptor_is_refused(self):
        with patch.object(bp, "_bib_request") as fetch:
            for bad in ("desc123", "desc" + HEX40 + ",zzz", HEX40[:-1]):
                resp = self.client.get("/api/biblissima/search", {"descriptors": bad})
                self.assertEqual(resp.status_code, 400, bad)
                self.assertIn("message", resp.json(), bad)
        fetch.assert_not_called()

    def test_too_many_descriptors_are_refused(self):
        many = ",".join(f"desc{i:040x}" for i in range(bp._MAX_SEARCH_DESCRIPTORS + 1))
        resp = self.client.get("/api/biblissima/search", {"descriptors": many})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "too many descriptors")
        self.assertEqual(resp.json()["max"], bp._MAX_SEARCH_DESCRIPTORS)
        self.assertIn(str(bp._MAX_SEARCH_DESCRIPTORS), resp.json()["message"])

    def test_exactly_the_maximum_number_of_descriptors_is_accepted(self):
        enough = ",".join(f"desc{i:040x}" for i in range(bp._MAX_SEARCH_DESCRIPTORS))
        with (
            patch.object(bp, "_fetch_biblissima_canvases", return_value=[]),
            patch.object(bp, "_enrich_canvases"),
        ):
            resp = self.client.get("/api/biblissima/search", {"descriptors": enough})
        self.assertEqual(resp.status_code, 200)

    def test_a_malformed_qid_is_refused_before_any_fetch(self):
        with patch.object(bp, "_bib_request") as fetch:
            for bad in ("Q12|Q13", "x"):
                resp = self.client.get(f"/api/biblissima/entity/{bad}")
                self.assertEqual(resp.status_code, 400, bad)
        fetch.assert_not_called()

    def test_a_well_formed_qid_reaches_the_wikibase(self):
        resp = MagicMock()
        resp.json.return_value = {"entities": {"Q27392": {}}}
        with patch.object(bp, "_bib_request", return_value=resp) as fetch:
            page = self.client.get("/api/biblissima/entity/Q27392")
        self.assertNotEqual(page.status_code, 400)
        self.assertEqual(fetch.call_count, 1)

    def test_a_malformed_ifdata_hash_is_refused(self):
        with patch.object(bp, "_bib_request") as fetch:
            resp = self.client.get("/api/biblissima/illumination/ifdataXYZ")
        self.assertEqual(resp.status_code, 400)
        fetch.assert_not_called()


class HashedKeyTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_manifest_canvas_key_never_carries_the_url(self):
        manifest = {
            "sequences": [
                {"canvases": [{"@id": "https://example/c/1", "width": 1, "height": 2}]}
            ]
        }
        resp = MagicMock()
        resp.json.return_value = manifest
        with (
            patch.object(bp, "_bib_request", return_value=resp),
            patch.object(bp.cache, "set", wraps=bp.cache.set) as set_,
        ):
            bp._fetch_canvas_dimensions(
                "https://evil.example/a b?c=d", "1r", MagicMock()
            )
        key = set_.call_args[0][0]
        self.assertNotIn("evil.example", key)
        self.assertNotIn(" ", key)
        self.assertTrue(key.startswith("biblissima:manifest-canvas:"))

    def test_search_raw_key_never_carries_the_descriptor_list(self):
        self.client.force_login(_editor("cache_hardening_search_editor"))
        with (
            patch.object(bp, "_fetch_biblissima_canvases", return_value=[]),
            patch.object(bp.cache, "set", wraps=bp.cache.set) as set_,
        ):
            self.client.get("/api/biblissima/search", {"descriptors": "desc" + HEX40})
        keys = [call.args[0] for call in set_.call_args_list]
        raw = [k for k in keys if k.startswith("biblissima:search:raw:")]
        self.assertEqual(len(raw), 1)
        self.assertNotIn(HEX40, raw[0])

    def test_iiif_manifest_key_never_carries_the_url(self):
        from manuspectrum.views.iiif_annotation import IIIFAnnotationMixin

        with (
            patch(
                "manuspectrum.utils.iiif_tools.CanvasIIIF.fetch_manifest",
                return_value={"@id": "m"},
            ),
            patch(
                "manuspectrum.views.iiif_annotation.cache.set", wraps=cache.set
            ) as set_,
        ):
            IIIFAnnotationMixin()._get_manifest_data("https://evil.example/m?x=1")
        key = set_.call_args[0][0]
        self.assertNotIn("evil.example", key)
        self.assertTrue(key.startswith("iiif_manifest_data:"))


class StampedeTests(TestCase):
    def setUp(self):
        cache.clear()
        self._deliveries = []

    def tearDown(self):
        for thread in self._deliveries:
            thread.join()
        cache.clear()

    def _deliver_later(self, key, value, delay=0.2):
        def run():
            time.sleep(delay)
            cache.set(key, value, 60)

        thread = threading.Thread(target=run)
        self._deliveries.append(thread)
        thread.start()

    def test_entity_lookup_waits_for_the_worker_holding_the_lock(self):
        key = bp._BIBLISSIMA_ENTITY_CACHE_KEY.format(qid="Q1")
        cache.add(key + ":lock", 1, 60)
        self._deliver_later(key, {"qid": "Q1", "label": "from-holder"})
        with patch.object(bp, "_bib_request") as fetch:
            self.assertEqual(bp._get_wikibase_entity("Q1")["label"], "from-holder")
        fetch.assert_not_called()

    def test_entity_failure_is_not_cached_and_releases_the_lock(self):
        key = bp._BIBLISSIMA_ENTITY_CACHE_KEY.format(qid="Q2")
        with patch.object(bp, "_bib_request", side_effect=RuntimeError("down")):
            self.assertIsNone(bp._get_wikibase_entity("Q2"))
        self.assertIsNone(cache.get(key))
        self.assertIsNone(cache.get(key + ":lock"))

    def test_search_fetch_waits_for_the_worker_holding_the_lock(self):
        self.client.force_login(_editor())
        key = bp.stable_cache_key("biblissima:search:raw", "desc" + HEX40)
        cache.add(key + ":lock", 1, 60)
        self._deliver_later(key, [{"canvasId": "c1"}])
        with (
            patch.object(bp, "_fetch_biblissima_canvases") as fetch,
            patch.object(bp, "_enrich_canvases"),
        ):
            resp = self.client.get(
                "/api/biblissima/search", {"descriptors": "desc" + HEX40}
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 1)
        fetch.assert_not_called()

    def test_illuminations_scrape_waits_for_the_worker_holding_the_lock(self):
        self.client.force_login(_editor())
        key = bp._BIBLISSIMA_RAW_ILLUMINATIONS_CACHE_KEY.format(
            portal_hash="mdata" + HEX40
        )
        cache.add(key + ":lock", 1, 60)
        self._deliver_later(key, [{"illuminationId": "i1"}])
        with patch.object(bp, "_bib_request") as fetch:
            resp = self.client.get(
                "/api/biblissima/manuscript-illuminations",
                {"portalHash": "mdata" + HEX40},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 1)
        fetch.assert_not_called()

    def test_illuminations_scrape_error_still_returns_the_upstream_error(self):
        self.client.force_login(_editor())
        with patch.object(
            bp, "_bib_request", side_effect=bp.requests.ConnectionError("x")
        ):
            resp = self.client.get(
                "/api/biblissima/manuscript-illuminations",
                {"portalHash": "mdata" + HEX40},
            )
        self.assertEqual(resp.status_code, 502)
        key = bp._BIBLISSIMA_RAW_ILLUMINATIONS_CACHE_KEY.format(
            portal_hash="mdata" + HEX40
        )
        self.assertIsNone(cache.get(key))
        self.assertIsNone(cache.get(key + ":lock"))

    def test_raw_caches_use_the_settings_ttl(self):
        self.assertEqual(
            bp._BIBLISSIMA_RAW_CACHE_TTL, settings.BIBLISSIMA_RAW_CACHE_TTL
        )
        manifest = {
            "sequences": [
                {"canvases": [{"@id": "https://example/c/1", "width": 1, "height": 2}]}
            ]
        }
        resp = MagicMock()
        resp.json.return_value = manifest
        with (
            patch.object(bp, "_bib_request", return_value=resp),
            patch.object(bp.cache, "set", wraps=bp.cache.set) as set_,
        ):
            bp._fetch_canvas_dimensions("https://example/m", "1r", MagicMock())
        self.assertEqual(set_.call_args[0][2], settings.BIBLISSIMA_RAW_CACHE_TTL)

    def test_entity_misses_hold_the_lock_ninety_seconds(self):
        with (
            patch.object(bp, "get_or_build", return_value=None) as build,
            patch.object(bp, "_bib_request"),
        ):
            bp._get_wikibase_entity("Q1")
        self.assertEqual(build.call_args.kwargs["lock_timeout"], 90)

    def test_view_misses_wait_ten_seconds_and_hold_the_lock_four_minutes(self):
        self.client.force_login(_editor())
        with (
            patch.object(bp, "get_or_build", return_value=[]) as build,
            patch.object(bp, "_fetch_biblissima_canvases", return_value=[]),
            patch.object(bp, "_enrich_canvases"),
            patch.object(
                bp, "_bib_request", return_value=MagicMock(text="<html></html>")
            ),
        ):
            self.client.get("/api/biblissima/search", {"descriptors": "desc" + HEX40})
            self.client.get(
                "/api/biblissima/manuscript-illuminations",
                {"portalHash": "mdata" + HEX40},
            )
        self.assertEqual(build.call_count, 2)
        for call in build.call_args_list:
            timeout = call.args[2] if len(call.args) > 2 else call.kwargs["timeout"]
            self.assertEqual(timeout, bp._BIBLISSIMA_RAW_CACHE_TTL)
            self.assertEqual(call.kwargs["wait"], 10.0)
            self.assertEqual(call.kwargs["lock_timeout"], 240)
