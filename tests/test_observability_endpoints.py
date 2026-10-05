from django.test import TestCase, modify_settings, override_settings
from prometheus_client.parser import text_string_to_metric_families

from manuspectrum.observability import metrics, web
from tests.observability_helpers import sample

PROMETHEUS = modify_settings(
    MIDDLEWARE={
        "prepend": "django_prometheus.middleware.PrometheusBeforeMiddleware",
        "append": "django_prometheus.middleware.PrometheusAfterMiddleware",
    }
)
GENERIC_LABELS = {
    "method",
    "transport",
    "view",
    "status",
    "type",
    "templatename",
    "charset",
    "le",
}


class MetricsViewTests(TestCase):
    def test_off_by_default(self):
        self.assertEqual(self.client.get("/metrics").status_code, 404)

    @override_settings(METRICS_ENABLED=True)
    def test_no_language_twin_and_no_proxied_read(self):
        self.assertEqual(self.client.get("/en/metrics").status_code, 404)
        self.assertEqual(
            self.client.get("/metrics", HTTP_X_FORWARDED_FOR="203.0.113.9").status_code,
            404,
        )

    @override_settings(METRICS_ENABLED=True)
    @PROMETHEUS
    def test_exposition_carries_request_and_application_metrics(self):
        self.client.get("/healthz")
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/plain"))
        self.assertIn("no-store", response["Cache-Control"])
        body = response.content.decode()
        self.assertIn(
            'django_http_requests_total_by_view_transport_method_total{method="GET",transport="http",view="healthz"}',
            body,
        )
        self.assertIn("manuspectrum_inflight_requests ", body)

    @override_settings(METRICS_ENABLED=True)
    @PROMETHEUS
    def test_exposition_has_no_forbidden_label(self):
        metrics.MEMO_LOOKUPS.labels(memo="iiif", outcome="hit").inc()
        self.client.get("/healthz")
        body = self.client.get("/metrics").content.decode()
        for family in text_string_to_metric_families(body):
            for sample_ in family.samples:
                labels = set(sample_.labels)
                with self.subTest(metric=sample_.name):
                    self.assertFalse(labels & metrics.FORBIDDEN_LABELS)
                    if family.name.startswith("manuspectrum_"):
                        self.assertLessEqual(labels - {"le"}, metrics.ALLOWED_LABELS)
                    elif family.name.startswith("django_"):
                        self.assertLessEqual(labels, GENERIC_LABELS)


class InflightTests(TestCase):
    def test_a_request_is_counted_until_its_response_is_closed(self):
        before = sample("manuspectrum_inflight_requests")
        web.request_started_handler(sender=None)
        self.assertEqual(sample("manuspectrum_inflight_requests"), before + 1)
        web.request_finished_handler(sender=None)
        self.assertEqual(sample("manuspectrum_inflight_requests"), before)

    def test_a_real_request_leaves_the_gauge_where_it_was(self):
        before = sample("manuspectrum_inflight_requests")
        self.client.get("/healthz")
        self.assertEqual(sample("manuspectrum_inflight_requests"), before)
