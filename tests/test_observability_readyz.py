import json
import threading
import time
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from manuspectrum.observability import health
from tests.observability_helpers import sample

REAL_ELASTICSEARCH = health.probe_elasticsearch
REAL_BROKER = health.probe_broker
ON = override_settings(
    READYZ_ENABLED=True,
    READYZ_TIMEOUT=0.5,
    READYZ_REDIS_URLS={
        "redis-broker": "redis://b:6379/0",
        "redis-cache": "redis://c:6379/0",
    },
    READYZ_CANTALOUPE=True,
    CANTALOUPE_HTTP_ENDPOINT="http://cantaloupe:8182/",
)
UP = lambda *args: None  # noqa: E731


@ON
class ReadyzTests(TestCase):
    def setUp(self):
        for target, value in (("_gate", threading.Lock()), ("_last", None)):
            patcher = patch.object(health, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in (
            "probe_elasticsearch",
            "probe_broker",
            "probe_redis",
            "probe_cantaloupe",
        ):
            patcher = patch.object(health, name, UP)
            patcher.start()
            self.addCleanup(patcher.stop)

    def get(self, **headers):
        return self.client.get("/readyz", HTTP_HOST="testserver", **headers)

    def test_every_component_up_with_the_real_database(self):
        response = self.get()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("no-store", response["Cache-Control"])
        report = json.loads(response.content)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(
            set(report["components"]),
            {
                "postgres",
                "elasticsearch",
                "celery-broker",
                "redis-broker",
                "redis-cache",
                "cantaloupe",
            },
        )
        self.assertEqual(report["components"]["postgres"]["status"], "up")

    def test_each_component_down_is_503(self):
        names = {
            "postgres": "probe_postgres",
            "elasticsearch": "probe_elasticsearch",
            "celery-broker": "probe_broker",
            "redis-cache": "probe_redis",
            "cantaloupe": "probe_cantaloupe",
        }
        for component, function in names.items():
            with (
                self.subTest(component=component),
                patch.object(
                    health, function, MagicMock(side_effect=ConnectionError("x"))
                ),
            ):
                response = self.get()
                self.assertEqual(response.status_code, 503)
                entry = json.loads(response.content)["components"][component]
                self.assertEqual(entry, {"status": "down", "error": "ConnectionError"})
                self.assertEqual(
                    sample("manuspectrum_readyz_component_up", component=component),
                    0.0,
                )

    def test_failure_reports_the_class_never_the_message(self):
        failure = ConnectionError("redis://:s3cret@redis-cache:6379/0 refused")
        with patch.object(health, "probe_redis", MagicMock(side_effect=failure)):
            body = self.get().content.decode()
        self.assertNotIn("s3cret", body)
        self.assertNotIn("redis-cache:6379", body)

    def test_red_cluster_is_down(self):
        engine = MagicMock()
        engine.es.options.return_value.cluster.health.return_value = {"status": "red"}
        with (
            patch.object(health, "probe_elasticsearch", REAL_ELASTICSEARCH),
            patch.object(health, "search_engine", return_value=engine),
        ):
            entry = json.loads(self.get().content)["components"]["elasticsearch"]
        self.assertEqual(entry, {"status": "down", "error": "status red"})
        engine.es.options.assert_called_once_with(request_timeout=0.5)

    def test_a_hung_probe_is_reported_within_the_bound(self):
        with patch.object(health, "probe_cantaloupe", lambda timeout: time.sleep(3)):
            started = time.monotonic()
            response = self.get()
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.5)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["components"]["cantaloupe"],
            {"status": "timeout"},
        )

    def test_a_timed_out_probe_is_logged_once_by_component_name(self):
        with (
            patch.object(health, "probe_cantaloupe", lambda timeout: time.sleep(1.5)),
            self.assertLogs("manuspectrum.observability.health", "WARNING") as logs,
        ):
            self.get()
        self.assertEqual(
            logs.output,
            [
                "WARNING:manuspectrum.observability.health:readiness: cantaloupe timed out"
            ],
        )

    def test_probe_threads_are_daemons(self):
        seen = []

        def slow(timeout):
            seen.append(threading.current_thread())
            time.sleep(1.2)

        with patch.object(health, "probe_cantaloupe", slow):
            self.get()
        self.assertTrue(seen and all(thread.daemon for thread in seen))
        self.assertTrue(seen[0].name.startswith("readyz-"))

    def test_concurrent_calls_share_one_evaluation(self):
        calls = []

        def slow(timeout):
            calls.append(1)
            time.sleep(0.3)

        reports = []
        with patch.object(health, "probe_cantaloupe", slow):
            threads = [
                threading.Thread(target=lambda: reports.append(health.readiness()))
                for _ in range(5)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(reports), 5)
        self.assertTrue(all(report["status"] == "ready" for report in reports))

    def test_a_waiter_that_reuses_the_report_releases_the_gate(self):
        calls = []

        def slow(timeout):
            calls.append(1)
            time.sleep(0.3)

        reports = []
        with patch.object(health, "probe_cantaloupe", slow):
            threads = [
                threading.Thread(target=lambda: reports.append(health.readiness()))
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
                time.sleep(0.05)
            for thread in threads:
                thread.join()
            self.assertEqual(len(calls), 1)
            self.assertFalse(health._gate.locked())
            health._last = (time.monotonic() - 3, health._last[1])
            report = health.readiness()
        self.assertEqual(len(calls), 2)
        self.assertEqual(report["status"], "ready")
        self.assertFalse(health._gate.locked())

    def test_the_gate_is_free_after_every_path(self):
        health.readiness()
        self.assertFalse(health._gate.locked())
        with patch.object(health, "_evaluate", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                health.readiness()
        self.assertFalse(health._gate.locked())
        health._gate.acquire()
        try:
            health._last = None
            report = health.readiness()
            self.assertEqual(report["status"], "not ready")
        finally:
            health._gate.release()
        self.assertFalse(health._gate.locked())

    def test_sequential_calls_each_evaluate(self):
        calls = []
        with patch.object(health, "probe_cantaloupe", lambda t: calls.append(1)):
            self.get()
            self.get()
        self.assertEqual(len(calls), 2)

    def test_cantaloupe_is_optional(self):
        with override_settings(READYZ_CANTALOUPE=False):
            self.assertNotIn("cantaloupe", json.loads(self.get().content)["components"])

    def test_broker_probe_targets_the_celery_broker_url(self):
        with (
            patch.object(health, "probe_broker", REAL_BROKER),
            patch("kombu.Connection") as connection,
            override_settings(CELERY_BROKER_URL="redis://redis-broker:6379/0"),
        ):
            self.get()
        self.assertEqual(connection.call_args.args[0], "redis://redis-broker:6379/0")

    def test_no_language_twin_and_no_proxied_read(self):
        self.assertEqual(self.client.get("/en/readyz").status_code, 404)
        self.assertEqual(self.get(HTTP_X_FORWARDED_FOR="203.0.113.9").status_code, 404)


class ReadyzOffTests(TestCase):
    def test_off_by_default(self):
        self.assertEqual(self.client.get("/readyz").status_code, 404)
