from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from manuspectrum.observability import celery_signals
from manuspectrum.observability.context import (
    bound_request_id,
    current_request_id,
)
from manuspectrum.observability.middleware import RequestIdMiddleware


def seen_ids():
    """A middleware whose view records the id it ran under."""
    seen = []

    def view(request):
        seen.append((request.request_id, current_request_id()))
        return HttpResponse("ok")

    return RequestIdMiddleware(view), seen


class RequestIdMiddlewareTests(SimpleTestCase):
    def test_a_safe_incoming_id_is_kept_and_echoed(self):
        middleware, seen = seen_ids()
        response = middleware(
            RequestFactory().get("/", HTTP_X_REQUEST_ID="0123456789abcdef")
        )
        self.assertEqual(response["X-Request-ID"], "0123456789abcdef")
        self.assertEqual(seen, [("0123456789abcdef", "0123456789abcdef")])

    def test_unsafe_incoming_ids_are_replaced(self):
        for value in (
            "short",
            "a" * 129,
            "abc\ndef01234",
            "../../etc/passwd",
            "-leading-dash1",
            "abc def 012345",
        ):
            with self.subTest(value=value[:20]):
                middleware, seen = seen_ids()
                response = middleware(
                    RequestFactory().get("/", HTTP_X_REQUEST_ID=value)
                )
                self.assertRegex(response["X-Request-ID"], r"^[0-9a-f]{32}$")
                self.assertEqual(seen[0][0], response["X-Request-ID"])

    def test_ids_never_cross_threads_or_requests(self):
        middleware, seen = seen_ids()
        after = []

        def one(n):
            middleware(RequestFactory().get("/", HTTP_X_REQUEST_ID=f"request-{n:08d}"))
            after.append(current_request_id())

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(one, range(200)))
        self.assertEqual(len(seen), 200)
        for request_id, context_id in seen:
            self.assertEqual(request_id, context_id)
        self.assertEqual(set(after), {""})
        self.assertEqual(len({r for r, _ in seen}), 200)


class ResponseHeaderTests(TestCase):
    def test_every_response_carries_an_id(self):
        response = self.client.get("/healthz")
        self.assertRegex(response["X-Request-ID"], r"^[0-9a-f]{32}$")


class CelerySignalTests(SimpleTestCase):
    def test_publish_adds_the_bound_id_and_nothing_otherwise(self):
        headers = {}
        celery_signals.add_request_id(sender="t", headers=headers)
        self.assertNotIn(celery_signals.HEADER, headers)
        with bound_request_id("publish-00000001"):
            celery_signals.add_request_id(sender="t", headers=headers)
        self.assertEqual(headers[celery_signals.HEADER], "publish-00000001")

    def task(self, **request):
        return SimpleNamespace(
            name="manuspectrum.index_resources", request=SimpleNamespace(**request)
        )

    def test_prerun_binds_the_header_and_postrun_restores_the_previous_id(self):
        task = self.task(ms_request_id="fromheader000001")
        with bound_request_id("outer-000000001"):
            celery_signals.bind_task(task_id="1", task=task)
            self.assertEqual(current_request_id(), "fromheader000001")
            celery_signals.unbind_task(task_id="1", task=task, state="SUCCESS")
            self.assertEqual(current_request_id(), "outer-000000001")

    def test_header_nested_under_request_headers_is_read_too(self):
        task = self.task(headers={"ms_request_id": "nested-00000001"})
        celery_signals.bind_task(task_id="2", task=task)
        self.assertEqual(current_request_id(), "nested-00000001")
        celery_signals.unbind_task(task_id="2", task=task, state="SUCCESS")
        self.assertEqual(current_request_id(), "")

    def test_an_unsafe_header_is_ignored(self):
        task = self.task(ms_request_id="bad\nid")
        celery_signals.bind_task(task_id="3", task=task)
        self.assertEqual(current_request_id(), "")
        celery_signals.unbind_task(task_id="3", task=task, state="SUCCESS")

    def test_the_celery_app_connects_the_receivers(self):
        import manuspectrum.celery  # noqa: F401
        from celery.signals import before_task_publish, task_postrun, task_prerun

        for signal, uid in (
            (before_task_publish, "ms-request-id-publish"),
            (task_prerun, "ms-task-prerun"),
            (task_postrun, "ms-task-postrun"),
        ):
            with self.subTest(uid=uid):
                self.assertTrue(any(key[0] == uid for key, _ in signal.receivers))


@override_settings(EXPLORER_BACKGROUND_REBUILD=True)
class ExplorerRebuildThreadTests(SimpleTestCase):
    def test_the_background_rebuild_logs_under_the_starting_request_id(self):
        from manuspectrum.views.explorer import memo

        seen = []
        with bound_request_id("rebuild-00000001"):
            thread = memo.spawn(lambda: seen.append(current_request_id()))
        thread.join(5)
        self.assertEqual(seen, ["rebuild-00000001"])
