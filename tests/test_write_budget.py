"""Write-path budget: ``utils.budget`` consulted by ``safe_fetch`` and the
Biblissima create views (one budget per created item)."""

import json
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase, TestCase, override_settings

from manuspectrum.utils import budget as budget_module
from manuspectrum.utils import http as http_utils
from manuspectrum.utils.budget import BudgetSpent, current_budget, upstream_budget
from tests.test_biblissima_createall_unit import (
    CreateAllBase,
    _fake_tile,
    _item,
    _make_request,
)

PUBLIC_URL = "https://iiif.example.org/manifest.json"


def _response(status=200, location=None, body=b"{}"):
    headers = {"Location": location} if location else {}
    response = MagicMock()
    response.headers = headers
    response.status_code = status
    response.is_redirect = bool(location)
    response.url = PUBLIC_URL
    response.iter_content.return_value = iter([body])
    return response


class BudgetModuleTests(SimpleTestCase):
    def test_read_views_use_the_shared_budget(self):
        from manuspectrum.views import biblissima_proxy as bp

        self.assertIs(bp._UpstreamBudget, budget_module.UpstreamBudget)
        self.assertIs(bp._upstream_budget_var, budget_module.budget_var)
        self.assertIs(bp.BiblissimaBudgetSpent, BudgetSpent)
        with bp._upstream_budget(5) as opened:
            self.assertIs(current_budget(), opened)
        self.assertIsNone(current_budget())


@override_settings(MANIFEST_FETCH_RATE_LIMITS={})
class SafeFetchBudgetTests(SimpleTestCase):
    def setUp(self):
        patcher = patch.object(http_utils, "assert_url_is_safe")
        self.addCleanup(patcher.stop)
        guard = patcher.start()
        guard.side_effect = lambda url, **kw: SimpleNamespace(geturl=lambda: url)

    def test_spent_budget_makes_no_call(self):
        session = MagicMock()
        with upstream_budget(0):
            with self.assertRaises(BudgetSpent):
                http_utils.safe_fetch(PUBLIC_URL, session=session)
        session.get.assert_not_called()

    def test_each_call_timeout_is_capped_by_what_is_left(self):
        session = MagicMock()
        session.get.return_value = _response()
        with upstream_budget(3):
            http_utils.safe_fetch(PUBLIC_URL, session=session, timeout=(10, 45))
        connect, read = session.get.call_args.kwargs["timeout"]
        self.assertLessEqual(connect, 3)
        self.assertLessEqual(read, 3)

    def test_redirect_loop_stops_once_spent(self):
        session = MagicMock()

        def slow_redirect(url, **kwargs):
            current_budget().deadline = time.monotonic() - 1
            return _response(302, location="/next")

        session.get.side_effect = slow_redirect
        with upstream_budget(50):
            with self.assertRaises(BudgetSpent):
                http_utils.safe_fetch(PUBLIC_URL, session=session)
        self.assertEqual(session.get.call_count, 1)

    def test_throttle_never_waits_past_the_budget(self):
        with patch.object(http_utils, "_rate_limits", return_value={"default": 30}):
            http_utils.throttle_for_host(PUBLIC_URL)
            with upstream_budget(2):
                with patch.object(http_utils.time, "sleep") as sleep:
                    with self.assertRaises(BudgetSpent):
                        http_utils.safe_fetch(PUBLIC_URL, session=MagicMock())
        sleep.assert_not_called()

    def test_body_read_stops_once_the_budget_is_spent(self):
        response = _response()

        def trickle(_size):
            yield b"a"
            current_budget().deadline = time.monotonic() - 1
            for _ in range(1000):
                yield b"b"
            raise AssertionError("budget did not stop the read")

        response.iter_content.side_effect = trickle
        session = MagicMock()
        session.get.return_value = response
        with upstream_budget(50):
            with self.assertRaises(BudgetSpent):
                http_utils.safe_fetch(PUBLIC_URL, session=session)
        response.close.assert_called()

    def test_throttle_lock_wait_is_bounded_by_the_budget(self):
        with patch.object(http_utils, "_rate_limits", return_value={"default": 1}):
            key, _interval = http_utils._rate_key_and_interval("iiif.example.org")
            lock = http_utils._host_rate_locks.setdefault(key, threading.Lock())
            self.assertTrue(lock.acquire(timeout=1))
            outcome = {}

            def wait():
                with upstream_budget(0.2):
                    try:
                        http_utils.throttle_for_host(PUBLIC_URL, current_budget())
                    except BudgetSpent:
                        outcome["spent"] = True

            waiter = threading.Thread(target=wait, daemon=True)
            started = time.monotonic()
            try:
                waiter.start()
                waiter.join(timeout=5)
                self.assertFalse(waiter.is_alive(), "lock wait ignored the budget")
            finally:
                lock.release()
                waiter.join(timeout=5)
            self.assertTrue(outcome.get("spent"))
            self.assertLess(time.monotonic() - started, 5)

    def test_safe_fetch_without_session_uses_the_no_retry_session_under_a_budget(self):
        budget_session = MagicMock()
        budget_session.get.return_value = _response()
        with (
            patch.object(
                http_utils, "_get_iiif_budget_session", return_value=budget_session
            ) as budget_factory,
            patch.object(http_utils, "get_iiif_session") as default,
        ):
            with upstream_budget(5):
                http_utils.safe_fetch(PUBLIC_URL)
        budget_factory.assert_called_once()
        default.assert_not_called()
        budget_session.get.assert_called_once()

    def test_safe_fetch_without_session_uses_the_retrying_session_outside_a_budget(
        self,
    ):
        default_session = MagicMock()
        default_session.get.return_value = _response()
        with (
            patch.object(http_utils, "_get_iiif_budget_session") as budget_factory,
            patch.object(http_utils, "get_iiif_session", return_value=default_session),
        ):
            http_utils.safe_fetch(PUBLIC_URL)
        budget_factory.assert_not_called()

    def test_default_session_has_no_retries_under_a_budget(self):
        with upstream_budget(5):
            session = http_utils._get_iiif_budget_session()
        self.assertEqual(
            session.get_adapter("https://x.org/").max_retries.total,
            0,
        )

    def test_no_budget_leaves_the_call_unchanged(self):
        session = MagicMock()
        session.get.return_value = _response()
        http_utils.safe_fetch(PUBLIC_URL, session=session, timeout=(10, 45))
        self.assertEqual(session.get.call_args.kwargs["timeout"], (10, 45))


class _AtomicDepth:
    """Replacement of ``transaction.atomic`` that counts the open blocks."""

    depth = 0

    @classmethod
    @contextmanager
    def atomic(cls, *args, **kwargs):
        cls.depth += 1
        try:
            yield
        finally:
            cls.depth -= 1


@override_settings(BIBLISSIMA_WRITE_ITEM_DEADLINE=60, MANIFEST_FETCH_RATE_LIMITS={})
class CreateAllWriteBudgetTests(CreateAllBase):
    def setUp(self):
        super().setUp()
        _AtomicDepth.depth = 0
        self._start(patch("django.db.transaction.atomic", new=_AtomicDepth.atomic))
        guard = self._start(patch.object(http_utils, "assert_url_is_safe"))
        guard.side_effect = lambda url, **kw: SimpleNamespace(geturl=lambda: url)

    def _slow_first_item(self, calls):
        """``pre_tile_save`` of the first item meets an upstream that eats the
        whole budget on its first hop; the others answer at once."""

        def hook(tiles, nodes_by_id, factory, method_name):
            if method_name != "pre_tile_save":
                return
            calls.append(_AtomicDepth.depth)
            session = MagicMock()
            if len(calls) == 1:

                def slow(url, **kwargs):
                    current_budget().deadline = time.monotonic() - 1
                    return _response(302, location="/elsewhere")

                session.get.side_effect = slow
            else:
                session.get.return_value = _response()
            http_utils.safe_fetch(PUBLIC_URL, session=session)

        self.mock_run_hook.side_effect = hook

    def test_item_over_budget_fails_with_the_deadline_reason_and_the_next_succeeds(
        self,
    ):
        calls = []
        self._slow_first_item(calls)
        response, payload = self._post(
            {"resourceType": "Document", "items": [_item("slow"), _item("fast")]}
        )
        self.assertEqual(response.status_code, 200)
        slow, fast = payload["results"]
        self.assertEqual(slow["status"], "failed")
        self.assertIn("60 s", slow["error"])
        self.assertEqual(fast["status"], "created")
        self.assertEqual(len(self.view._tile_buffer), 1)

    def test_no_outbound_call_inside_an_open_transaction(self):
        calls = []
        self._slow_first_item(calls)
        self._post({"resourceType": "Document", "items": [_item("a"), _item("b")]})
        self.assertEqual(calls, [0, 0])

    def test_each_item_gets_its_own_budget(self):
        seen = []

        def hook(tiles, nodes_by_id, factory, method_name):
            if method_name == "pre_tile_save":
                seen.append(current_budget())

        self.mock_run_hook.side_effect = hook
        self._post({"resourceType": "Document", "items": [_item("a"), _item("b")]})
        self.assertEqual(len(seen), 2)
        self.assertIsNot(seen[0], seen[1])
        self.assertIsNone(current_budget())

    def test_more_than_5_items_is_refused(self):
        items = [_item(f"c{n}") for n in range(6)]
        response, payload = self._post({"resourceType": "Document", "items": items})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["max"], 5)
        self.mock_run_hook.assert_not_called()

    def test_exactly_5_items_is_accepted(self):
        items = [_item(f"c{n}") for n in range(5)]
        response, payload = self._post({"resourceType": "Document", "items": items})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["results"]), 5)


class SingleCreateWriteBudgetTests(TestCase):
    def _post(self, side_effect):
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        request = _make_request({"resourceType": "Document", "biblissimaData": {}})
        with patch.object(
            BiblissimaCreateResourceView, "_create_resource", side_effect=side_effect
        ):
            response = view.post(request)
        return response, json.loads(response.content)

    @override_settings(BIBLISSIMA_WRITE_ITEM_DEADLINE=60)
    def test_spent_budget_answers_504_with_the_reason(self):
        from manuspectrum.views.biblissima_proxy import WriteDeadlineExceeded

        response, payload = self._post(WriteDeadlineExceeded("Time limit of 60 s"))
        self.assertEqual(response.status_code, 504)
        self.assertIn("60 s", payload["error"])

    @override_settings(BIBLISSIMA_WRITE_ITEM_DEADLINE=60)
    def test_item_budget_turns_a_late_timeout_into_the_deadline_error(self):
        from manuspectrum.views.biblissima_proxy import (
            WriteDeadlineExceeded,
            _item_write_budget,
        )

        with self.assertRaises(WriteDeadlineExceeded) as caught:
            with _item_write_budget():
                current_budget().deadline = time.monotonic() - 1
                raise requests.exceptions.ReadTimeout()
        self.assertIn("60 s", str(caught.exception))
        self.assertIsNone(current_budget())

    def test_item_budget_leaves_other_failures_alone(self):
        from manuspectrum.views.biblissima_proxy import _item_write_budget

        with self.assertRaises(RuntimeError):
            with _item_write_budget():
                raise RuntimeError("boom")

    def test_the_budget_is_closed_before_the_transaction_opens(self):
        from manuspectrum.views.biblissima_proxy import BiblissimaCreateResourceView

        view = BiblissimaCreateResourceView()
        seen = {}

        def stage(*args, **kwargs):
            seen["staging"] = current_budget()

        def atomic_enter(*args, **kwargs):
            seen["atomic"] = current_budget()
            raise RuntimeError("stop at the transaction")

        with (
            patch.object(view, "_stage_tiles", side_effect=stage),
            patch.object(view, "_create_document_tiles"),
            patch.object(view, "_precollect_valid_dep_ids", return_value=set()),
            patch("django.db.transaction.atomic", side_effect=atomic_enter),
            patch("arches.app.models.resource.Resource"),
        ):
            with self.assertRaises(RuntimeError):
                view._create_resource(
                    graph_id="00000000-0000-4000-8000-000000000000",
                    resource_type="Document",
                    transaction_id=None,
                    bbma_data={},
                    dependencies={},
                    concept_mappings={},
                    user=None,
                )
        self.assertIsNotNone(seen["staging"])
        self.assertIsNone(seen["atomic"])

    def test_other_failure_stays_a_500(self):
        response, payload = self._post(RuntimeError("boom"))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload["error"], "Resource creation failed")
