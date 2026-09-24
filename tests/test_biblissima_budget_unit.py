"""Request budget and host breaker of outbound Biblissima calls.

Run:
    /home/rayondemiel/venv/bin/python manage.py test \\
        tests.test_biblissima_budget_unit \\
        --settings="tests.test_settings" --noinput
"""

import json
import os
import threading
import time
from collections import namedtuple
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qsl, urlsplit

import requests
from django.core.cache import cache
from urllib3.exceptions import ReadTimeoutError
from django.test import RequestFactory, TestCase

from manuspectrum.views import biblissima_proxy as bp

WIKIBASE = bp.BIBLISSIMA_WIKIBASE
WIKIBASE_HOST = urlsplit(bp.BIBLISSIMA_WIKIBASE).hostname
PORTAL_PAGE = f"{bp.BIBLISSIMA_PORTAL}/mdata{'1' * 40}"
THIRD_PARTY_MANIFEST = "https://iiif.example.org/manifest.json"

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "biblissima")
MANUSCRIPT_HASH = "mdatad3888c6b14fc49ee485c226af71a65b0d35b2ef9"
ILLUMINATION_HASH = "ifdata5be7529b7987eadf417506e4ea42ac11b8ff7105"
DESCRIPTOR_HASH = "desc0aa8475df0b814bf66ac50b45cbf4721b3c77736"
GALLICA_MANIFEST = "https://gallica.bnf.fr/iiif/ark:/12148/btv1b8455927r/manifest.json"
ENTITY_FIXTURES = {
    "Q352422": "entity_manuscript_Q352422.json",
    "Q32812": "entity_collection_Q32812.json",
    "Q27392": "entity_paris_Q27392.json",
    "Q32811": "entity_parent_Q32811.json",
}
PORTAL_FIXTURES = {
    ILLUMINATION_HASH: "illumination_ifdata5be75.html",
    MANUSCRIPT_HASH: "manuscript_mdatad3888c.html",
}
AGGREGATOR_MANIFEST = {
    "sequences": [
        {
            "canvases": [
                {
                    "@id": "https://portail.biblissima.fr/iiif/canvas/abdias",
                    "label": "Abdias (Paris, BnF, Latin 40 f.323v)",
                    "metadata": [
                        {
                            "label": "Manuscrit",
                            "value": (
                                '<a href="https://portail.biblissima.fr/ark:/43093/'
                                f'{MANUSCRIPT_HASH}">Latin 40</a>'
                            ),
                        }
                    ],
                }
            ]
        }
    ]
}


class BudgetTestCase(TestCase):
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

    def fake_session(self, status_code=200, headers=None, payload=None, error=None):
        session = MagicMock(name="session")
        session.calls = []

        def get(url, **kwargs):
            session.calls.append((url, kwargs))
            if error is not None:
                raise error
            response = MagicMock(
                status_code=status_code,
                headers=dict(headers or {}),
                ok=status_code < 400,
            )
            response.json.return_value = payload if payload is not None else {}
            return response

        session.get.side_effect = get
        return session

    def sent_timeout(self, session, index=0):
        return session.calls[index][1]["timeout"]


class SessionChoiceTests(BudgetTestCase):
    def test_a_call_under_a_budget_uses_the_no_retry_session(self):
        with bp._upstream_budget(50):
            session = bp._default_session()
        self.addCleanup(session.close)

        self.assertIs(session, bp._get_besteffort_session())
        self.assertEqual(session.get_adapter("https://x/").max_retries.total, 0)

    def test_a_call_outside_a_budget_uses_the_shared_retrying_session(self):
        session = bp._default_session()
        self.addCleanup(session.close)

        self.assertIs(session, bp._get_biblissima_session())
        self.assertEqual(session.get_adapter("https://x/").max_retries.total, 3)

    def test_the_retrying_session_ignores_retry_after(self):
        session = bp._build_biblissima_session()
        self.addCleanup(session.close)

        retry = session.get_adapter("https://x/").max_retries

        self.assertEqual(retry.total, 3)
        self.assertFalse(retry.respect_retry_after_header)

    def test_helpers_without_a_session_reuse_the_shared_one(self):
        builder = self._start(
            patch.object(
                bp,
                "_build_biblissima_session",
                side_effect=lambda retry=None: MagicMock(name="built-session"),
            )
        )
        seen = []

        def bib_request(session, url, **kwargs):
            seen.append(session)
            qids = kwargs["params"]["ids"].split("|")
            response = MagicMock(status_code=200, headers={})
            response.json.return_value = {
                "entities": {
                    qid: {"id": qid, "labels": {"fr": {"value": qid}}} for qid in qids
                }
            }
            return response

        self._start(patch.object(bp, "_bib_request", side_effect=bib_request))

        self.assertIsNotNone(bp._get_wikibase_entity("Q1"))
        self.assertIsNotNone(bp._get_wikibase_entity("Q2"))
        self.assertIn("Q3", bp._batch_get_wikibase_entities(["Q3"]))

        self.assertEqual(len(seen), 3)
        self.assertIs(seen[0], seen[1])
        self.assertIs(seen[1], seen[2])
        self.assertIs(seen[0], bp._get_biblissima_session())
        self.assertLessEqual(builder.call_count, 1)


class BudgetTimeoutTests(BudgetTestCase):
    def test_a_budget_caps_the_connect_and_keeps_the_family_read(self):
        session = self.fake_session()

        with bp._upstream_budget(50):
            bp._bib_request(session, PORTAL_PAGE, timeout=bp.PORTAL_REQUEST_TIMEOUT)

        timeout = self.sent_timeout(session)
        self.assertIsInstance(timeout, tuple)
        connect, read = timeout
        self.assertLessEqual(connect, bp.IIIF_CONNECT_TIMEOUT)
        self.assertEqual(read, bp.PORTAL_REQUEST_TIMEOUT)

    def test_the_backstop_caps_the_read(self):
        session = self.fake_session()

        with bp._upstream_budget(2):
            bp._bib_request(session, PORTAL_PAGE, timeout=bp.PORTAL_REQUEST_TIMEOUT)

        timeout = self.sent_timeout(session)
        self.assertIsInstance(timeout, tuple)
        connect, read = timeout
        self.assertTrue(0 < connect <= 2)
        self.assertTrue(0 < read <= 2)

    def test_the_slot_wait_is_capped_by_the_backstop(self):
        semaphore = threading.BoundedSemaphore(1)
        semaphore.acquire()
        self._start(patch.object(bp, "_biblissima_semaphore", semaphore))
        self._start(patch.object(bp, "_BIBLISSIMA_SLOT_TIMEOUT", 30))
        session = self.fake_session()

        started = time.monotonic()
        with bp._upstream_budget(0.3) as budget:
            with self.assertRaises(bp.BiblissimaBusy):
                bp._bib_request(session, WIKIBASE, timeout=bp.REQUEST_TIMEOUT)

        self.assertLess(time.monotonic() - started, 2)
        session.get.assert_not_called()
        self.assertIsInstance(budget.error, bp.BiblissimaBusy)
        self.assertEqual(budget.down, set())

    def test_a_spent_budget_starts_no_call(self):
        session = self.fake_session()

        with bp._upstream_budget(0) as budget:
            with self.assertRaises(bp.BiblissimaBudgetSpent):
                bp._bib_request(session, WIKIBASE, timeout=bp.REQUEST_TIMEOUT)

        session.get.assert_not_called()
        self.assertIsInstance(budget.error, bp.BiblissimaBudgetSpent)
        self.assertEqual(budget.down, set())


class HostBreakerTests(BudgetTestCase):
    def test_a_connection_failure_trips_the_host(self):
        dead = self.fake_session(error=requests.exceptions.ConnectTimeout("dead"))
        portal = self.fake_session()

        with bp._upstream_budget(50) as budget:
            with self.assertRaises(requests.exceptions.ConnectTimeout):
                bp._bib_request(dead, WIKIBASE, timeout=bp.REQUEST_TIMEOUT)
            with self.assertRaises(bp.BiblissimaHostDown):
                bp._bib_request(dead, WIKIBASE, timeout=bp.REQUEST_TIMEOUT)
            bp._bib_request(portal, PORTAL_PAGE, timeout=bp.PORTAL_REQUEST_TIMEOUT)

        self.assertEqual(dead.get.call_count, 1)
        self.assertEqual(portal.get.call_count, 1)
        self.assertIsInstance(budget.error, requests.exceptions.ConnectTimeout)
        self.assertEqual(budget.down, {WIKIBASE_HOST})

    def test_a_503_trips_the_host_and_a_500_does_not(self):
        with bp._upstream_budget(50) as budget:
            bp._bib_request(
                self.fake_session(status_code=500),
                PORTAL_PAGE,
                timeout=bp.PORTAL_REQUEST_TIMEOUT,
            )
            self.assertEqual(budget.down, set())
            portal_again = self.fake_session()
            bp._bib_request(
                portal_again, PORTAL_PAGE, timeout=bp.PORTAL_REQUEST_TIMEOUT
            )

            bp._bib_request(
                self.fake_session(status_code=503),
                WIKIBASE,
                timeout=bp.REQUEST_TIMEOUT,
            )
            wikibase_again = self.fake_session()
            with self.assertRaises(bp.BiblissimaHostDown):
                bp._bib_request(wikibase_again, WIKIBASE, timeout=bp.REQUEST_TIMEOUT)

        self.assertEqual(portal_again.get.call_count, 1)
        wikibase_again.get.assert_not_called()
        self.assertEqual(budget.down, {WIKIBASE_HOST})
        self.assertEqual(budget.error.response.status_code, 500)

    def test_a_403_is_recorded_and_trips_the_host(self):
        with bp._upstream_budget(50) as budget:
            response = bp._bib_request(
                self.fake_session(status_code=403),
                WIKIBASE,
                timeout=bp.REQUEST_TIMEOUT,
            )
            with self.assertRaises(bp.BiblissimaHostDown):
                bp._bib_request(
                    self.fake_session(), WIKIBASE, timeout=bp.REQUEST_TIMEOUT
                )

        self.assertEqual(response.status_code, 403)
        self.assertIsInstance(budget.error, requests.exceptions.HTTPError)
        self.assertEqual(budget.error.response.status_code, 403)
        self.assertEqual(budget.down, {WIKIBASE_HOST})

    def test_a_mediawiki_error_in_a_200_is_recorded(self):
        wikibase_again = self.fake_session()

        with bp._upstream_budget(50) as budget:
            bp._bib_request(
                self.fake_session(headers={"MediaWiki-API-Error": "ratelimited"}),
                WIKIBASE,
                timeout=bp.REQUEST_TIMEOUT,
            )
            bp._bib_request(wikibase_again, WIKIBASE, timeout=bp.REQUEST_TIMEOUT)

        self.assertIsInstance(budget.error, bp.BiblissimaApiError)
        self.assertEqual(budget.error.code, "ratelimited")
        self.assertEqual(budget.down, set())
        self.assertEqual(wikibase_again.get.call_count, 1)

    def test_a_4xx_is_recorded_without_tripping_the_host(self):
        wikibase_again = self.fake_session()

        with bp._upstream_budget(50) as budget:
            response = bp._bib_request(
                self.fake_session(status_code=400), WIKIBASE, timeout=5
            )
            bp._bib_request(wikibase_again, WIKIBASE, timeout=5)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(budget.error.response.status_code, 400)
        self.assertEqual(budget.down, set())
        self.assertEqual(wikibase_again.get.call_count, 1)

    def test_a_wikibase_404_is_recorded(self):
        with bp._upstream_budget(50) as budget:
            bp._bib_request(self.fake_session(status_code=404), WIKIBASE, timeout=5)

        self.assertEqual(budget.error.response.status_code, 404)

    def test_a_portal_404_is_not_recorded(self):
        with bp._upstream_budget(50) as budget:
            response = bp._bib_request(
                self.fake_session(status_code=404),
                PORTAL_PAGE,
                timeout=bp.PORTAL_REQUEST_TIMEOUT,
            )

        self.assertEqual(response.status_code, 404)
        self.assertIsNone(budget.error)
        self.assertEqual(budget.down, set())

    def test_a_failed_third_party_call_is_not_recorded(self):
        fetch = self._start(
            patch.object(
                bp,
                "safe_fetch",
                side_effect=requests.exceptions.ConnectTimeout("third party down"),
            )
        )

        with bp._upstream_budget(50) as budget:
            with self.assertLogs(bp.logger.name, level="WARNING"):
                first = bp._fetch_canvas_dimensions(THIRD_PARTY_MANIFEST, "1r")
            with self.assertLogs(bp.logger.name, level="WARNING"):
                second = bp._fetch_canvas_dimensions(THIRD_PARTY_MANIFEST, "2r")

        self.assertEqual((first, second), ({}, {}))
        self.assertEqual(fetch.call_count, 2)
        self.assertIsNone(budget.error)
        self.assertEqual(budget.down, set())

    def test_the_first_failure_is_kept(self):
        with bp._upstream_budget(50) as budget:
            bp._bib_request(
                self.fake_session(status_code=500),
                PORTAL_PAGE,
                timeout=bp.PORTAL_REQUEST_TIMEOUT,
            )
            first = budget.error
            with self.assertRaises(requests.exceptions.ConnectTimeout):
                bp._bib_request(
                    self.fake_session(error=requests.exceptions.ConnectTimeout()),
                    WIKIBASE,
                    timeout=bp.REQUEST_TIMEOUT,
                )

        self.assertIsNotNone(first)
        self.assertIs(budget.error, first)
        self.assertEqual(budget.down, {WIKIBASE_HOST})

    def test_the_budget_ends_with_its_block(self):
        with bp._upstream_budget(50):
            pass
        with self.assertRaises(RuntimeError):
            with bp._upstream_budget(50):
                raise RuntimeError("the view failed")

        self.assertIsNone(bp._upstream_budget_var.get())
        session = self.fake_session()
        bp._bib_request(session, WIKIBASE, timeout=bp.REQUEST_TIMEOUT)
        self.assertEqual(self.sent_timeout(session), bp.REQUEST_TIMEOUT)


class JsonReadTests(BudgetTestCase):
    def read(self, text="", headers=None):
        session = MagicMock(name="session")
        session.get.return_value = _response(WIKIBASE, text=text, headers=headers)
        response = bp._bib_request(session, WIKIBASE, timeout=5)
        return bp._bib_json(response)

    def test_a_json_object_is_returned(self):
        with bp._upstream_budget(50) as budget:
            payload = self.read('{"entities": {}}')

        self.assertEqual(payload, {"entities": {}})
        self.assertIsNone(budget.error)

    def test_a_body_that_is_not_json_is_a_recorded_failure(self):
        with bp._upstream_budget(50) as budget:
            with self.assertRaises(bp.BiblissimaApiError) as raised:
                self.read("<html>maintenance</html>")

        self.assertIsNone(raised.exception.code)
        self.assertIs(budget.error, raised.exception)
        self.assertEqual(budget.down, set())

    def test_a_json_list_is_a_recorded_failure(self):
        with bp._upstream_budget(50) as budget:
            with self.assertRaises(bp.BiblissimaApiError):
                self.read("[]")

        self.assertIsInstance(budget.error, bp.BiblissimaApiError)

    def test_an_error_key_is_a_recorded_failure_with_its_code(self):
        with bp._upstream_budget(50) as budget:
            with self.assertRaises(bp.BiblissimaApiError) as raised:
                self.read('{"error": {"code": "badvalue"}}')

        self.assertEqual(raised.exception.code, "badvalue")
        self.assertEqual(budget.error.code, "badvalue")

    def test_an_api_error_header_is_recorded_once(self):
        with bp._upstream_budget(50) as budget:
            with patch.object(bp._UpstreamBudget, "record", autospec=True) as record:
                with self.assertRaises(bp.BiblissimaApiError) as raised:
                    self.read(
                        '{"error": {"code": "ratelimited"}}',
                        headers={"MediaWiki-API-Error": "ratelimited"},
                    )

        self.assertEqual(raised.exception.code, "ratelimited")
        self.assertEqual(record.call_count, 1)
        self.assertIs(record.call_args.args[0], budget)

    def test_outside_a_budget_nothing_is_recorded(self):
        with self.assertRaises(bp.BiblissimaApiError):
            self.read("not json")


class EnrichmentPoolBudgetTests(BudgetTestCase):
    def test_pool_threads_see_the_budget(self):
        retries = []
        timeouts = []
        lock = threading.Lock()

        def build(retry=None):
            session = MagicMock(name="built-session")

            def get(url, **kwargs):
                with lock:
                    timeouts.append(kwargs["timeout"])
                response = MagicMock(status_code=200, headers={}, ok=True)
                response.json.return_value = {"query": {"search": []}}
                return response

            session.get.side_effect = get
            with lock:
                retries.append(retry)
            return session

        self._start(patch.object(bp, "_build_biblissima_session", side_effect=build))
        canvases = [
            {"manuscriptArk": f"ark:/43093/mdata{i:040d}", "manuscript": f"Latin {i}"}
            for i in range(2)
        ]

        with bp._upstream_budget(50):
            bp._enrich_canvases(canvases)

        self.assertTrue(retries)
        for retry in retries:
            self.assertIs(retry, bp._NO_RETRY)
        self.assertEqual(len(timeouts), 2)
        for timeout in timeouts:
            self.assertIsInstance(timeout, tuple)
            self.assertLessEqual(timeout[0], bp.IIIF_CONNECT_TIMEOUT)


class MissingEntityTests(BudgetTestCase):
    def test_a_missing_entity_is_none_and_not_memoised(self):
        response = MagicMock(status_code=200, headers={})
        response.json.return_value = {"entities": {"Q9": {"id": "Q9", "missing": ""}}}
        request = self._start(patch.object(bp, "_bib_request", return_value=response))

        self.assertIsNone(bp._get_wikibase_entity("Q9", session=MagicMock()))
        self.assertIsNone(bp._get_wikibase_entity("Q9", session=MagicMock()))

        self.assertEqual(request.call_count, 2)


class UpstreamErrorMappingTests(BudgetTestCase):
    def test_a_spent_budget_answers_504(self):
        with self.assertLogs(bp.logger.name, level="WARNING"):
            response = bp._biblissima_upstream_error(bp.BiblissimaBudgetSpent(), "ctx")

        self.assertEqual(response.status_code, 504)
        self.assertEqual(json.loads(response.content)["error"], "timeout")

    def test_a_read_timeout_during_the_body_answers_504(self):
        with self.assertRaises(requests.exceptions.ConnectionError) as raised:
            _stalled_response(WIKIBASE)

        with self.assertLogs(bp.logger.name, level="WARNING"):
            response = bp._biblissima_upstream_error(raised.exception, "ctx")

        self.assertEqual(response.status_code, 504)
        self.assertEqual(json.loads(response.content)["error"], "timeout")

    def test_a_refused_connection_still_answers_502(self):
        with self.assertLogs(bp.logger.name, level="WARNING"):
            response = bp._biblissima_upstream_error(
                requests.exceptions.ConnectionError("refused"), "ctx"
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(json.loads(response.content)["error"], "connection_error")

    def test_a_host_down_answers_502(self):
        with self.assertLogs(bp.logger.name, level="WARNING"):
            response = bp._biblissima_upstream_error(
                bp.BiblissimaHostDown(WIKIBASE_HOST), "ctx"
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(json.loads(response.content)["error"], "connection_error")


def _read_fixture(name):
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as fixture:
        return fixture.read()


def _response(url, status_code=200, payload=None, text="", headers=None):
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response.encoding = "utf-8"
    response.headers.update(headers or {})
    body = json.dumps(payload) if payload is not None else text
    response._content = body.encode("utf-8")
    return response


class _StalledBody:
    """``Response.raw`` whose body read times out, as urllib3 reports it."""

    def __init__(self, url):
        self.url = url

    def stream(self, chunk_size, decode_content=True):
        raise ReadTimeoutError(None, self.url, "Read timed out.")
        yield b""


def _stalled_response(url):
    """Headers received, then a read timeout during the body download.

    Reads the body as ``requests`` does for a non-streamed call, so what
    escapes is what ``session.get`` raises in that case.
    """
    response = requests.Response()
    response.status_code = 200
    response.url = url
    response.raw = _StalledBody(url)
    response.content
    return response


UpstreamCall = namedtuple("UpstreamCall", "route url query timeout via")


class _ThreadSession:
    """Session built by ``_build_biblissima_session``: forwards to the fake."""

    def __init__(self, upstream, retry):
        self.upstream = upstream
        self.retry = retry
        self.close = MagicMock(name="built-session.close")

    def get(self, url, params=None, **kwargs):
        return self.upstream.dispatch(self, url, params, kwargs)


class FakeUpstream:
    """Wikibase, the portal, the IIIF aggregator and Gallica, from fixtures.

    Stands for the shared sessions, for ``safe_fetch`` and, through
    ``build``, for every session a view or a pool thread builds. A request it
    does not serve raises ``AssertionError`` and is kept in ``unexpected``.
    ``answer`` replaces a route's body (a JSON payload or a text) and can add
    headers. ``fail`` makes a route answer a status, raise an error, stall
    during the body download, or behave as a dead host: sleep for the connect
    timeout it received (10 s at most), then raise ``ConnectTimeout``.
    """

    def __init__(self):
        self.calls = []
        self.unexpected = []
        self.built = []
        self.answers = {}
        self.failures = {}
        self.close = MagicMock(name="shared-session.close")
        self._lock = threading.Lock()

    def answer(self, route, payload=None, *, text="", headers=None):
        self.answers[route] = (payload, text, headers)

    def fail(self, route, *, status=None, error=None, dead=False, stalled=False):
        self.failures[route] = (status, error, dead, stalled)

    def build(self, retry=None):
        session = _ThreadSession(self, retry)
        with self._lock:
            self.built.append(session)
        return session

    def get(self, url, params=None, **kwargs):
        return self.dispatch(self, url, params, kwargs)

    def fetch(self, url, session=None, throttle=True, **kwargs):
        return self.dispatch(session, url, None, kwargs)

    def routes(self):
        return [call.route for call in self.calls]

    def dispatch(self, via, url, params, kwargs):
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        query.update({key: str(value) for key, value in (params or {}).items()})
        try:
            route, default = self._route(url, parts, query)
        except AssertionError:
            with self._lock:
                self.unexpected.append(url)
            raise
        timeout = kwargs.get("timeout")
        with self._lock:
            self.calls.append(UpstreamCall(route, url, query, timeout, via))
        status, error, dead, stalled = self.failures.get(
            route, (None, None, False, False)
        )
        if stalled:
            return _stalled_response(url)
        if dead:
            connect = timeout[0] if isinstance(timeout, tuple) else timeout
            time.sleep(min(10, connect))
            raise requests.exceptions.ConnectTimeout(f"{url} did not answer")
        if error is not None:
            raise error
        if status is not None:
            return _response(url, status, text="upstream failure")
        if route in self.answers:
            payload, text, headers = self.answers[route]
            return _response(url, payload=payload, text=text, headers=headers)
        return default()

    def _route(self, url, parts, query):
        if parts.hostname == WIKIBASE_HOST and url.startswith(WIKIBASE):
            action = query.get("action")
            if action == "wbgetentities":
                route = "claims" if query.get("props") == "claims" else "wbgetentities"
                ids = query["ids"].split("|")
                return route, lambda: _response(
                    url, payload={"entities": {qid: self._entity(qid) for qid in ids}}
                )
            if action == "wbsearchentities":
                return action, lambda: _response(url, payload={"search": []})
            if action == "query":
                return action, lambda: _response(url, payload={"query": {"search": []}})
        for route, base in (
            ("portal-fr", bp.BIBLISSIMA_PORTAL),
            ("portal-en", bp.BIBLISSIMA_PORTAL_EN),
        ):
            portal_hash = url[len(base) + 1 :] if url.startswith(f"{base}/") else None
            if portal_hash in PORTAL_FIXTURES:
                html = _read_fixture(PORTAL_FIXTURES[portal_hash])
                return route, lambda: _response(url, text=html)
        if url.startswith(bp.BIBLISSIMA_IIIF_MANIFEST):
            return "iiif", lambda: _response(url, payload=AGGREGATOR_MANIFEST)
        if url == GALLICA_MANIFEST:
            manifest = json.loads(_read_fixture("manifest_btv1b8455927r.json"))
            return "gallica", lambda: _response(url, payload=manifest)
        raise AssertionError(f"unexpected upstream request: {url} {query}")

    def _entity(self, qid):
        if qid in ENTITY_FIXTURES:
            return json.loads(_read_fixture(ENTITY_FIXTURES[qid]))["entities"][qid]
        return {"id": qid, "missing": ""}


class ViewBudgetTestCase(BudgetTestCase):
    def setUp(self):
        super().setUp()
        self.upstream = FakeUpstream()
        self._start(
            patch.object(bp, "_get_besteffort_session", return_value=self.upstream)
        )
        self._start(
            patch.object(bp, "_get_biblissima_session", return_value=self.upstream)
        )
        self._start(patch.object(bp, "safe_fetch", side_effect=self.upstream.fetch))
        self._start(
            patch.object(
                bp, "_build_biblissima_session", side_effect=self.upstream.build
            )
        )
        self._start(patch.object(bp, "logger"))
        self.addCleanup(self._no_stray_request)

    def _no_stray_request(self):
        self.assertEqual(self.upstream.unexpected, [])

    def call(self, view_class, path, params=None, **kwargs):
        request = RequestFactory().get(path, params or {})
        return view_class().get(request, **kwargs)

    def assert_partial_and_uncached(self, send):
        """Send the request twice: a partial answer, not served by the page cache.

        Returns the first response.
        """
        response = send()
        calls = len(self.upstream.calls)
        again = send()

        self.assertEqual(response.status_code, 200)
        self.assertIs(json.loads(response.content).get("partial"), True)
        self.assertIn("max-age=0", response["Cache-Control"])
        self.assertIs(json.loads(again.content).get("partial"), True)
        self.assertGreater(len(self.upstream.calls), calls)
        return response


class EntityViewBudgetTests(ViewBudgetTestCase):
    def entity(self, qid):
        return self.call(
            bp.BiblissimaEntityView, f"/api/biblissima/entity/{qid}", qid=qid
        )

    def test_an_upstream_outage_is_not_reported_as_a_missing_entity(self):
        self.upstream.fail("wbgetentities", dead=True)

        started = time.monotonic()
        response = self.entity("Q352422")

        self.assertIn(response.status_code, (502, 504))
        self.assertLess(time.monotonic() - started, 7)

    def test_a_body_that_is_not_json_answers_502(self):
        self.upstream.answer("wbgetentities", text="<html>maintenance</html>")

        response = self.entity("Q352422")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(json.loads(response.content)["error"], "invalid_response")

    def test_a_no_such_entity_error_is_a_404(self):
        self.upstream.answer(
            "wbgetentities",
            {"error": {"code": "no-such-entity"}},
            headers={"MediaWiki-API-Error": "no-such-entity"},
        )

        response = self.entity("Q352422")

        self.assertEqual(response.status_code, 404)

    def test_another_api_error_answers_502_with_its_code(self):
        self.upstream.answer(
            "wbgetentities",
            {"error": {"code": "ratelimited"}},
            headers={"MediaWiki-API-Error": "ratelimited"},
        )

        response = self.entity("Q352422")

        self.assertEqual(response.status_code, 502)
        payload = json.loads(response.content)
        self.assertEqual(
            (payload["error"], payload["code"]), ("invalid_response", "ratelimited")
        )

    def test_a_4xx_answers_502(self):
        self.upstream.fail("wbgetentities", status=400)

        response = self.entity("Q352422")

        self.assertEqual(response.status_code, 502)
        self.assertEqual(json.loads(response.content)["status"], 400)

    def test_a_read_timeout_during_the_body_answers_504(self):
        self.upstream.fail("wbgetentities", stalled=True)

        response = self.entity("Q352422")

        self.assertEqual(response.status_code, 504)
        self.assertEqual(json.loads(response.content)["error"], "timeout")

    def test_a_malformed_id_is_refused_without_a_call(self):
        for qid in ("Q0", "Q01", "Q", "q1"):
            response = self.entity(qid)

            self.assertEqual(response.status_code, 400, qid)
        self.assertEqual(self.upstream.calls, [])

    def test_a_missing_entity_is_a_404(self):
        response = self.entity("Q999999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.content), {"error": "Entity not found"})

    def test_a_partial_entity_is_not_stored_by_the_page_cache(self):
        self.upstream.fail("claims", status=503)

        response = self.assert_partial_and_uncached(lambda: self.entity("Q352422"))

        payload = json.loads(response.content)
        self.assertEqual(payload["collectionQid"], "Q32812")
        self.assertEqual(payload["locationQid"], "")

    def test_a_complete_entity_is_stored_by_the_page_cache(self):
        response = self.entity("Q352422")
        calls = len(self.upstream.calls)
        again = self.entity("Q352422")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["locationQid"], "Q27392")
        self.assertEqual(payload["geonamesId"], "2988507")
        self.assertEqual(payload["parentInstitutionQid"], "Q32811")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(len(self.upstream.calls), calls)

    def test_a_dead_wikibase_is_called_once_per_request(self):
        self._start(patch.object(bp, "IIIF_CONNECT_TIMEOUT", 0.5))
        manuscript = json.loads(_read_fixture(ENTITY_FIXTURES["Q352422"]))
        cache.set(
            bp._BIBLISSIMA_ENTITY_CACHE_KEY.format(qid="Q352422"),
            bp._extract_entity_props("Q352422", manuscript["entities"]["Q352422"]),
            60,
        )
        self.upstream.fail("wbgetentities", dead=True)
        self.upstream.fail("claims", dead=True)

        self.assert_partial_and_uncached(lambda: self.entity("Q352422"))

        self.assertEqual(len(self.upstream.calls), 2)


class SearchManuscriptsViewBudgetTests(ViewBudgetTestCase):
    def search(self, **params):
        return self.call(
            bp.BiblissimaSearchManuscriptsView,
            "/api/biblissima/search-manuscripts",
            params,
        )

    def test_a_search_whose_calls_all_failed_answers_the_error(self):
        self.upstream.fail("wbsearchentities", status=500)
        self.upstream.fail("query", status=500)

        response = self.search(q="Latin 9926")

        self.assertEqual(self.upstream.routes(), ["wbsearchentities", "query"])
        self.assertEqual(response.status_code, 502)
        payload = json.loads(response.content)
        self.assertEqual((payload["error"], payload["status"]), ("upstream_error", 500))

    def test_a_failed_entity_batch_answers_the_error(self):
        self.upstream.answer(
            "query", {"query": {"search": [{"title": "Item:Q352422"}]}}
        )
        self.upstream.fail("wbgetentities", status=503)

        response = self.search(q="Latin 9926")

        self.assertIn("wbgetentities", self.upstream.routes())
        self.assertEqual(response.status_code, 502)
        payload = json.loads(response.content)
        self.assertEqual((payload["error"], payload["status"]), ("upstream_error", 503))

    def test_a_lost_prefix_branch_makes_the_answer_partial(self):
        self.upstream.answer(
            "query", {"query": {"search": [{"title": "Item:Q352422"}]}}
        )
        for failure in (
            {"text": "<html>maintenance</html>"},
            {
                "payload": {"error": {"code": "ratelimited"}},
                "headers": {"MediaWiki-API-Error": "ratelimited"},
            },
        ):
            with self.subTest(failure=failure):
                cache.clear()
                self.upstream.answer("wbsearchentities", **failure)

                response = self.assert_partial_and_uncached(
                    lambda: self.search(q="Latin 9926")
                )

                self.assertEqual(json.loads(response.content)["total"], 1)

    def test_a_4xx_on_the_prefix_branch_makes_the_answer_partial(self):
        self.upstream.answer(
            "query", {"query": {"search": [{"title": "Item:Q352422"}]}}
        )
        self.upstream.fail("wbsearchentities", status=400)

        self.assert_partial_and_uncached(lambda: self.search(q="Latin 9926"))

    def test_every_200_carries_partial(self):
        short = self.search(q="La")
        empty = self.search(q="Latin 9926")

        self.assertEqual(json.loads(short.content), {"results": [], "partial": False})
        self.assertEqual(
            json.loads(empty.content), {"total": 0, "results": [], "partial": False}
        )

    def test_a_garbage_limit_does_not_500(self):
        response = self.search(q="Latin 9926", limit="many")

        self.assertEqual(response.status_code, 200)
        fulltext = [call for call in self.upstream.calls if call.route == "query"]
        self.assertEqual(fulltext[0].query["srlimit"], "50")


class SearchViewBudgetTests(ViewBudgetTestCase):
    def search(self):
        return self.call(
            bp.BiblissimaSearchView,
            "/api/biblissima/search",
            {"descriptors": DESCRIPTOR_HASH, "page_size": 50},
        )

    def test_a_dead_aggregator_answers_within_the_connect_cap(self):
        self.upstream.fail("iiif", dead=True)

        started = time.monotonic()
        response = self.search()

        self.assertEqual(self.upstream.routes(), ["iiif"])
        timeout = self.upstream.calls[0].timeout
        self.assertIsInstance(timeout, tuple)
        self.assertLessEqual(timeout[0], bp.IIIF_CONNECT_TIMEOUT)
        self.assertEqual(response.status_code, 504)
        self.assertLess(time.monotonic() - started, 7)

    def test_a_failed_enrichment_marks_the_page_partial(self):
        self.upstream.fail("query", status=503)

        response = self.assert_partial_and_uncached(self.search)

        self.assertEqual(self.upstream.routes(), ["iiif", "query", "query"])
        self.assertEqual(json.loads(response.content)["total"], 1)


class ManuscriptIlluminationsViewBudgetTests(ViewBudgetTestCase):
    def test_a_dead_portal_answers_within_the_connect_cap(self):
        self.upstream.fail("portal-fr", dead=True)

        started = time.monotonic()
        response = self.call(
            bp.BiblissimaManuscriptIlluminationsView,
            "/api/biblissima/manuscript-illuminations",
            {"portalHash": MANUSCRIPT_HASH},
        )

        self.assertEqual(self.upstream.routes(), ["portal-fr"])
        timeout = self.upstream.calls[0].timeout
        self.assertIsInstance(timeout, tuple)
        self.assertLessEqual(timeout[0], bp.IIIF_CONNECT_TIMEOUT)
        self.assertEqual(response.status_code, 504)
        self.assertLess(time.monotonic() - started, 7)


class IlluminationDetailViewBudgetTests(ViewBudgetTestCase):
    def detail(self):
        return self.call(
            bp.BiblissimaIlluminationDetailView,
            f"/api/biblissima/illumination/{ILLUMINATION_HASH}",
            ifdata_hash=ILLUMINATION_HASH,
        )

    def test_a_failed_english_page_marks_the_answer_partial_and_uncached(self):
        self.upstream.fail("portal-en", status=503)

        response = self.assert_partial_and_uncached(self.detail)

        self.assertEqual(json.loads(response.content)["folio"], "323v")

    def test_an_api_error_on_the_manuscript_lookup_is_not_memoised(self):
        self.upstream.answer(
            "query",
            {"error": {"code": "search-backend-error"}},
            headers={"MediaWiki-API-Error": "search-backend-error"},
        )

        response = self.assert_partial_and_uncached(self.detail)

        manuscript_hash = json.loads(response.content)["manuscriptHash"]
        self.assertIsNone(
            cache.get(
                bp._BIBLISSIMA_MANUSCRIPT_CACHE_KEY.format(ark_hash=manuscript_hash)
            )
        )

    def test_a_failed_third_party_manifest_does_not_mark_it_partial(self):
        self.upstream.fail(
            "gallica", error=requests.exceptions.ConnectionError("gallica down")
        )

        response = self.detail()
        calls = len(self.upstream.calls)
        self.detail()

        self.assertIn("gallica", self.upstream.routes())
        self.assertEqual(response.status_code, 200)
        self.assertIs(json.loads(response.content).get("partial"), False)
        self.assertEqual(len(self.upstream.calls), calls)

    def test_the_shared_session_is_not_closed(self):
        response = self.detail()

        self.assertEqual(response.status_code, 200)
        shared = bp._get_besteffort_session()
        portal_calls = [c for c in self.upstream.calls if c.route.startswith("portal")]
        self.assertEqual(len(portal_calls), 2)
        for call in portal_calls:
            self.assertIs(call.via, shared)
        shared.close.assert_not_called()
        self.assertTrue(self.upstream.built)
        for session in self.upstream.built:
            self.assertIs(session.retry, bp._NO_RETRY)
            session.close.assert_called_once()
