"""Outbound Biblissima concurrency: slot waits and session reuse.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_concurrency_unit \\
        --settings="tests.test_settings" --noinput
"""

import json
import threading
import time
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import RequestFactory, TestCase

from manuspectrum.views import biblissima_proxy as bp

DESCRIPTORS_A = "desc" + "a" * 40
DESCRIPTORS_B = "desc" + "b" * 40


class ConcurrencyTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self._start(patch.dict(bp._biblissima_stats))
        self._start(patch.object(bp, "_biblissima_session", None))
        self._start(patch.object(bp, "_besteffort_session", None))

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

        with self.assertLogs("manuspectrum.views.biblissima_proxy", level="WARNING"):
            response = bp.BiblissimaSearchView().get(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["error"], "busy")
        self.assertEqual(response["Retry-After"], str(bp._BIBLISSIMA_SLOT_TIMEOUT))

    def test_a_given_wait_replaces_the_setting(self):
        self.semaphore.acquire()
        self._start(patch.object(bp, "_BIBLISSIMA_SLOT_TIMEOUT", 30))

        started = time.monotonic()
        with self.assertRaises(bp.BiblissimaBusy):
            with bp._biblissima_slot(timeout=0.05):
                self.fail("the block ran without a slot")

        self.assertLess(time.monotonic() - started, 5)


class BibRequestDeadlineTests(ConcurrencyTestCase):
    URL = "https://data.example/w/api.php"

    def test_the_timeouts_are_what_is_left_once_the_slot_is_held(self):
        semaphore = threading.BoundedSemaphore(1)
        self._start(patch.object(bp, "_biblissima_semaphore", semaphore))
        fetch = self._start(
            patch.object(bp, "safe_fetch", return_value=MagicMock(status_code=200))
        )
        semaphore.acquire()
        release = threading.Timer(0.3, semaphore.release)
        self.addCleanup(release.join)
        self.addCleanup(release.cancel)
        release.start()

        bp._bib_request(
            MagicMock(), self.URL, guarded=True, deadline=time.monotonic() + 1.0
        )

        connect, read = fetch.call_args.kwargs["timeout"]
        self.assertTrue(0 < connect <= 0.8)
        self.assertTrue(0 < read <= 0.8)

    def test_a_spent_deadline_starts_no_call(self):
        fetch = self._start(patch.object(bp, "safe_fetch"))

        with self.assertRaises(bp.BiblissimaBudgetSpent):
            bp._bib_request(
                MagicMock(), self.URL, guarded=True, deadline=time.monotonic() - 0.01
            )

        fetch.assert_not_called()


class BusyResponseTests(ConcurrencyTestCase):
    def test_busy_maps_to_503_with_retry_after(self):
        with self.assertLogs("manuspectrum.views.biblissima_proxy", level="WARNING"):
            response = bp._biblissima_upstream_error(bp.BiblissimaBusy(), "ctx")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], str(bp._BIBLISSIMA_SLOT_TIMEOUT))
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
        response = MagicMock(headers={})
        response.json.return_value = {"query": {"search": [{"title": "Item:Q1"}]}}
        self._start(patch.object(bp, "_bib_request", return_value=response))

    def _manuscript_batch(self):
        return {"Q1": {"portalHash": self.ark_hash, "author": "Q9", "label": "Latin 1"}}

    def test_a_saturated_pool_caches_no_manuscript_record(self):
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()
        self._start(patch.object(bp, "_biblissima_semaphore", semaphore))
        self._start(patch.object(bp, "_BIBLISSIMA_SLOT_TIMEOUT", 0.01))

        with self.assertLogs("manuspectrum.views.biblissima_proxy", level="WARNING"):
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

    def test_a_record_whose_nature_label_did_not_resolve_is_not_cached(self):
        self._search_finds_q1()
        self._start(
            patch.object(
                bp,
                "_batch_get_wikibase_entities",
                side_effect=[
                    {
                        "Q1": {
                            "portalHash": self.ark_hash,
                            "documentNatureQid": "Q8",
                            "label": "Latin 1",
                        }
                    },
                    {},
                ],
            )
        )

        bp._enrich_canvases(self.canvases, session=MagicMock())

        self.assertIsNone(self._cached_record())

    def test_a_candidate_missing_after_the_match_does_not_block_caching(self):
        response = MagicMock(headers={})
        response.json.return_value = {
            "query": {"search": [{"title": "Item:Q1"}, {"title": "Item:Q2"}]}
        }
        self._start(patch.object(bp, "_bib_request", return_value=response))
        self._start(
            patch.object(
                bp,
                "_batch_get_wikibase_entities",
                side_effect=[{"Q1": {"portalHash": self.ark_hash, "label": "Latin 1"}}],
            )
        )

        bp._enrich_canvases(self.canvases, session=MagicMock())

        self.assertEqual(self._cached_record()["label"], "Latin 1")

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


class SharedSessionTests(ConcurrencyTestCase):
    def setUp(self):
        super().setUp()

    def test_the_shared_session_is_built_once(self):
        self.assertIs(bp._get_biblissima_session(), bp._get_biblissima_session())

    def test_the_shared_session_keeps_the_retry_policy(self):
        retries = bp._get_biblissima_session().get_adapter("https://x/").max_retries

        self.assertEqual(retries.connect, 2)

    def test_the_search_view_reuses_the_shared_session_across_requests(self):
        seen = []

        def fetch(desc_hashes, session):
            seen.append(session)
            return []

        self._start(
            patch.object(
                bp,
                "_build_biblissima_session",
                side_effect=lambda retry=None: MagicMock(name="built-session"),
            )
        )
        self._start(patch.object(bp, "_fetch_biblissima_canvases", side_effect=fetch))
        self._start(patch.object(bp, "_enrich_canvases"))

        for descriptors in (DESCRIPTORS_A, DESCRIPTORS_B):
            request = RequestFactory().get(
                "/api/biblissima/search", {"descriptors": descriptors}
            )
            self.assertEqual(bp.BiblissimaSearchView().get(request).status_code, 200)

        self.assertEqual(len(seen), 2)
        self.assertIs(seen[0], seen[1])
        self.assertIs(seen[0], bp._get_besteffort_session())
        seen[0].close.assert_not_called()


class EnrichmentPoolSessionTests(ConcurrencyTestCase):
    def test_each_pool_thread_uses_its_own_session_and_closes_it(self):
        built = []
        used = []
        used_lock = threading.Lock()

        def build(retry=None):
            session = MagicMock(name=f"thread-session-{len(built)}")
            built.append(session)
            return session

        def bib_request(session, url, **kwargs):
            time.sleep(0.05)
            with used_lock:
                used.append((threading.get_ident(), session))
            response = MagicMock()
            response.json.return_value = {"query": {"search": []}}
            return response

        self._start(patch.object(bp, "_build_biblissima_session", side_effect=build))
        self._start(patch.object(bp, "_bib_request", side_effect=bib_request))
        self._start(patch.object(bp, "_batch_get_wikibase_entities", return_value={}))
        caller_session = MagicMock(name="caller-session")
        canvases = [
            {"manuscriptArk": f"ark:/43093/mdata{i:040d}", "manuscript": f"Latin {i}"}
            for i in range(6)
        ]

        bp._enrich_canvases(canvases, session=caller_session)

        self.assertEqual(len(used), 6)
        self.assertNotIn(caller_session, [session for _, session in used])
        sessions_by_thread = {}
        for ident, session in used:
            sessions_by_thread.setdefault(ident, set()).add(id(session))
        self.assertGreater(len(sessions_by_thread), 1)
        for session_ids in sessions_by_thread.values():
            self.assertEqual(len(session_ids), 1)
        self.assertEqual(len(built), len(sessions_by_thread))
        for session in built:
            session.close.assert_called_once()
        caller_session.close.assert_not_called()
