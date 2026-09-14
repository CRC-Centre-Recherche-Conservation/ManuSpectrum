"""Outbound Biblissima concurrency: slot waits and session reuse.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_concurrency_unit \\
        --settings="tests.test_settings" --noinput
"""

import json
import threading
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from manuspectrum.views import biblissima_proxy as bp

DESCRIPTORS_A = "desc" + "a" * 40


class ConcurrencyTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def _start(self, patcher):
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock


class SlotTimeoutTests(ConcurrencyTestCase):
    def setUp(self):
        super().setUp()
        self.semaphore = threading.BoundedSemaphore(1)
        self._start(patch.object(bp, "_biblissima_semaphore", self.semaphore))
        self._start(patch.object(bp, "_BIBLISSIMA_SLOT_TIMEOUT", 0.01))
        self._start(
            patch.dict(
                bp._biblissima_stats, {"slot_timeouts": 0, "requests_in_flight": 0}
            )
        )

    def test_a_saturated_semaphore_raises_busy_after_the_timeout(self):
        self.semaphore.acquire()

        with self.assertRaises(bp.BiblissimaBusy):
            with bp._biblissima_slot():
                self.fail("the block ran without a slot")

        self.assertEqual(bp._biblissima_stats["slot_timeouts"], 1)
        self.assertEqual(bp._biblissima_stats["requests_in_flight"], 0)

    def test_a_timed_out_wait_releases_nothing(self):
        self.semaphore.acquire()

        with self.assertRaises(bp.BiblissimaBusy):
            with bp._biblissima_slot():
                pass

        self.assertFalse(self.semaphore.acquire(blocking=False))

    def test_the_slot_is_released_when_the_call_raises(self):
        with self.assertRaises(RuntimeError):
            with bp._biblissima_slot():
                raise RuntimeError("upstream exploded")

        self.assertTrue(self.semaphore.acquire(blocking=False))
        self.assertEqual(bp._biblissima_stats["requests_in_flight"], 0)

    def test_no_request_is_sent_without_a_slot(self):
        self.semaphore.acquire()
        session = MagicMock()

        with self.assertRaises(bp.BiblissimaBusy):
            bp._bib_request(session, "https://example.org")

        session.get.assert_not_called()

    def test_the_search_view_answers_503_when_no_slot_frees_up(self):
        self.semaphore.acquire()
        request = RequestFactory().get(
            "/api/biblissima/search", {"descriptors": DESCRIPTORS_A}
        )

        response = bp.BiblissimaSearchView().get(request)

        self.assertEqual(response.status_code, 503)
        self.assertIn("Retry-After", response)


class BusyResponseTests(ConcurrencyTestCase):
    def test_busy_maps_to_503_with_retry_after(self):
        response = bp._biblissima_upstream_error(bp.BiblissimaBusy(), "ctx")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "15")
        payload = json.loads(response.content)
        self.assertEqual(payload["error"], "busy")
        self.assertTrue(payload["message"])


class EnrichmentCacheTests(ConcurrencyTestCase):
    ark_hash = "mdata" + "1" * 40

    def setUp(self):
        super().setUp()
        self.canvases = [
            {"manuscriptArk": "ark:/43093/" + self.ark_hash, "manuscript": "Latin 1"}
        ]

    def _cached_record(self):
        return cache.get(
            bp._BIBLISSIMA_MANUSCRIPT_CACHE_KEY.format(ark_hash=self.ark_hash)
        )

    def _search_finds_q1(self):
        response = MagicMock()
        response.json.return_value = {"query": {"search": [{"title": "Item:Q1"}]}}
        self._start(patch.object(bp, "_bib_request", return_value=response))

    def _manuscript_batch(self):
        return {"Q1": {"portalHash": self.ark_hash, "author": "Q9", "label": "Latin 1"}}

    def test_a_saturated_pool_caches_no_manuscript_record(self):
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()
        self._start(patch.object(bp, "_biblissima_semaphore", semaphore))
        self._start(patch.object(bp, "_BIBLISSIMA_SLOT_TIMEOUT", 0.01))

        bp._enrich_canvases(self.canvases, session=MagicMock())

        self.assertIsNone(self._cached_record())

    def test_a_candidate_missing_from_the_entity_batch_is_not_cached(self):
        self._search_finds_q1()
        self._start(patch.object(bp, "_batch_get_wikibase_entities", return_value={}))

        bp._enrich_canvases(self.canvases, session=MagicMock())

        self.assertIsNone(self._cached_record())

    def test_a_record_whose_author_label_did_not_resolve_is_not_cached(self):
        self._search_finds_q1()
        self._start(
            patch.object(
                bp,
                "_batch_get_wikibase_entities",
                side_effect=[self._manuscript_batch(), {}],
            )
        )

        bp._enrich_canvases(self.canvases, session=MagicMock())

        self.assertIsNone(self._cached_record())

    def test_a_complete_resolution_is_cached(self):
        self._search_finds_q1()
        self._start(
            patch.object(
                bp,
                "_batch_get_wikibase_entities",
                side_effect=[
                    self._manuscript_batch(),
                    {"Q9": {"label": "Jean Fouquet"}},
                ],
            )
        )

        bp._enrich_canvases(self.canvases, session=MagicMock())

        self.assertEqual(self._cached_record()["authorLabel"], "Jean Fouquet")
