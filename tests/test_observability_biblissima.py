import threading
import time
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from django.test import TestCase

from manuspectrum.utils import budget as budget_module
from manuspectrum.views import biblissima_proxy as bp
from tests.observability_helpers import delta, sample


def _make_response(status_code=200):
    """A Mock that quacks enough like a ``requests.Response`` (never import a test module:
    unittest would run its tests again here)."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.headers = requests.structures.CaseInsensitiveDict()
    return response


class UpstreamOutcomeTests(TestCase):
    def setUp(self):
        self.patch = patch.dict(bp._biblissima_stats)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def call(self, status=None, error=None, url=None):
        session = MagicMock()
        if error is not None:
            session.get.side_effect = error
        else:
            session.get.return_value = _make_response(status_code=status)
        return bp._bib_request(session, url or bp.BIBLISSIMA_WIKIBASE)

    def test_status_outcomes(self):
        for status, outcome in (
            (200, "ok"),
            (404, "not_found"),
            (429, "rate_limited"),
            (403, "client_error"),
            (503, "server_error"),
        ):
            with (
                self.subTest(status=status),
                delta(
                    "manuspectrum_biblissima_upstream_requests_total",
                    endpoint="wikibase",
                    outcome=outcome,
                ) as counted,
                delta(
                    "manuspectrum_biblissima_upstream_latency_seconds_count",
                    endpoint="wikibase",
                ) as timed,
            ):
                self.call(status)
            self.assertEqual((counted.value, timed.value), (1, 1))

    def test_timeouts_and_errors(self):
        with delta(
            "manuspectrum_biblissima_upstream_requests_total",
            endpoint="wikibase",
            outcome="timeout",
        ) as timeouts:
            with self.assertRaises(requests.exceptions.Timeout):
                self.call(error=requests.exceptions.Timeout())
        with delta(
            "manuspectrum_biblissima_upstream_requests_total",
            endpoint="other",
            outcome="error",
        ) as errors:
            with self.assertRaises(ValueError):
                self.call(error=ValueError(), url="https://example.org/x")
        self.assertEqual((timeouts.value, errors.value), (1, 1))

    def test_a_busy_slot_is_counted_without_latency(self):
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()
        with (
            patch.object(bp, "_biblissima_semaphore", semaphore),
            patch.object(bp, "_BIBLISSIMA_SLOT_TIMEOUT", 0.01),
            delta(
                "manuspectrum_biblissima_upstream_requests_total",
                endpoint="wikibase",
                outcome="busy",
            ) as busy,
            delta("manuspectrum_biblissima_slot_timeouts_total") as slots,
            delta(
                "manuspectrum_biblissima_upstream_latency_seconds_count",
                endpoint="wikibase",
            ) as timed,
        ):
            with self.assertRaises(bp.BiblissimaBusy):
                self.call(200)
        self.assertEqual((busy.value, slots.value, timed.value), (1, 1, 0))

    def test_in_flight_is_one_inside_the_slot_and_returns_to_zero(self):
        with delta("manuspectrum_biblissima_inflight") as inflight:
            with bp._biblissima_slot():
                self.assertEqual(sample("manuspectrum_biblissima_inflight"), 1)
            self.call(200)
        self.assertEqual(inflight.value, 0)

    def test_a_failing_metric_never_keeps_the_slot(self):
        with patch.object(bp, "_incr_stat", side_effect=[None, RuntimeError("metric")]):
            with self.assertRaises(RuntimeError):
                with bp._biblissima_slot():
                    pass
        for _ in range(bp._BIBLISSIMA_CONCURRENCY_LIMIT):
            self.assertTrue(bp._biblissima_semaphore.acquire(timeout=0))
        for _ in range(bp._BIBLISSIMA_CONCURRENCY_LIMIT):
            bp._biblissima_semaphore.release()


class CacheMirrorTests(TestCase):
    def test_cache_hits_and_misses_are_mirrored(self):
        with (
            patch.dict(bp._biblissima_stats),
            delta("manuspectrum_biblissima_cache_total", outcome="hit") as hits,
            delta("manuspectrum_biblissima_cache_total", outcome="miss") as misses,
        ):
            bp._incr_stat("cache_hits")
            bp._incr_stat("cache_misses", 2)
        self.assertEqual((hits.value, misses.value), (1, 2))


class SuggestPrefixTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_upstream_then_own_entry(self):
        entry = {"complete": True, "items": [], "entities": {}}
        with (
            patch.object(bp, "_suggest_prefix_entry", return_value=entry),
            patch.object(bp, "_suggest_typed_hits", return_value=[]),
            delta(
                "manuspectrum_biblissima_suggest_prefix_total", source="upstream"
            ) as upstream,
        ):
            bp._suggest_prefix_results("abc", "fr", "Q1", 10, time.monotonic() + 4)
        with (
            patch.object(bp, "_suggest_cached_entry", return_value=(entry, None)),
            patch.object(bp, "_suggest_typed_hits", return_value=[]),
            delta("manuspectrum_biblissima_suggest_prefix_total", source="own") as own,
        ):
            bp._suggest_prefix_results("abc", "fr", "Q1", 10, time.monotonic() + 4)
        self.assertEqual((upstream.value, own.value), (1, 1))


class BudgetTests(TestCase):
    def test_a_block_ending_after_its_deadline_is_counted_by_kind(self):
        with (
            delta("manuspectrum_upstream_budget_spent_total", kind="write") as spent,
            delta("manuspectrum_upstream_budget_spent_total", kind="read") as read,
        ):
            with budget_module.upstream_budget(0, kind="write"):
                pass
            with budget_module.upstream_budget(60):
                pass
        self.assertEqual((spent.value, read.value), (1, 0))


class CreatedItemsTests(TestCase):
    def test_outcomes_of_a_create_all_answer(self):
        results = [
            {"status": "created"},
            {"status": "created"},
            {"status": "failed", "error": "x"},
            {"status": "failed", "error": "Time limit"},
        ]
        with (
            delta(
                "manuspectrum_biblissima_created_items_total",
                resource_type="Document",
                outcome="created",
            ) as created,
            delta(
                "manuspectrum_biblissima_created_items_total",
                resource_type="Document",
                outcome="failed",
            ) as failed,
            delta(
                "manuspectrum_biblissima_created_items_total",
                resource_type="Document",
                outcome="deadline",
            ) as deadline,
        ):
            bp._count_created_items("Document", results, out_of_budget=1)
        self.assertEqual((created.value, failed.value, deadline.value), (2, 1, 1))
