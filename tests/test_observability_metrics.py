import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from unittest.mock import patch

from django.apps import apps
from django.test import SimpleTestCase, override_settings
from prometheus_client import REGISTRY, CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client import multiprocess
from prometheus_client.metrics import MetricWrapperBase

from manuspectrum.observability import metrics

ROOT = Path(__file__).resolve().parent.parent


def declared():
    return {
        name: value
        for name, value in vars(metrics).items()
        if isinstance(value, MetricWrapperBase)
    }


class RegistryRulesTests(SimpleTestCase):
    def test_the_inventory_is_declared(self):
        self.assertEqual(len(declared()), 51)

    def test_names_carry_the_prefix_and_their_unit(self):
        for attribute, metric in declared().items():
            with self.subTest(metric=attribute):
                self.assertTrue(metric._name.startswith("manuspectrum_"))
                if isinstance(metric, Histogram):
                    self.assertRegex(metric._name, r"_(seconds|bytes)$")
                self.assertIsInstance(metric, (Counter, Gauge, Histogram))

    def test_labels_come_from_the_allowed_set(self):
        for attribute, metric in declared().items():
            with self.subTest(metric=attribute):
                labels = set(metric._labelnames)
                self.assertLessEqual(labels, metrics.ALLOWED_LABELS)
                self.assertFalse(labels & metrics.FORBIDDEN_LABELS)

    def test_every_gauge_names_its_multiprocess_mode(self):
        for attribute, metric in declared().items():
            if isinstance(metric, Gauge):
                with self.subTest(metric=attribute):
                    self.assertIn(metric._multiprocess_mode, metrics.GAUGE_MODES)

    def test_a_gauge_without_a_mode_is_refused(self):
        with self.assertRaises(ValueError):
            metrics.gauge("manuspectrum_test_unused", "doc", mode="all")

    @override_settings(LANGUAGES=[("en", "English"), ("fr", "French")])
    def test_helpers_fold_unknown_values_to_other(self):
        self.assertEqual(metrics.bounded("x", ("a",)), "other")
        self.assertEqual(metrics.bounded(None, ("a",)), "other")
        self.assertEqual(metrics.language_label("fr"), "fr")
        self.assertEqual(metrics.language_label("fr-x-<script>"), "other")
        self.assertEqual(metrics.log_source("arches.app.views"), "arches")
        self.assertEqual(metrics.log_source("urllib3.connectionpool"), "other")
        self.assertEqual(
            metrics.task_label("manuspectrum.index_resources"),
            "manuspectrum.index_resources",
        )
        self.assertEqual(metrics.task_label("evil.task"), "other")
        self.assertEqual(metrics.task_label("manuspectrum." + "x" * 200), "other")

    def test_memo_label_takes_the_longest_known_prefix_and_never_the_key(self):
        cases = {
            "iiif:0123abcd": "iiif",
            "model-graph:fr:5e1f": "model-graph",
            "summary-graph-slugs": "summary-graph-slugs",
            "summary-graph:7b0c": "summary-graph",
            "biblissima:suggest:prefix:9a9a": "biblissima:suggest:prefix",
            "biblissima:suggest:9a9a": "biblissima:suggest",
            "biblissima:wikibase:entity:Q4242": "biblissima:wikibase:entity",
            "biblissima:anything-new:Q1": "biblissima",
            "spectrum-preview:4f7e:200:c0ff": "spectrum-preview",
            "spectrum-preview-file:4f7e": "spectrum-preview-file",
            "public-visibility:visible:3:12:anon": "public-visibility",
            "unknown-memo:secret": "other",
            "iiifx:1": "other",
        }
        for key, label in cases.items():
            with self.subTest(key=key):
                self.assertEqual(metrics.memo_label(key), label)

    @override_settings(SPECTRUM_PREVIEW_TIERS=[200, 4096])
    def test_tier_label(self):
        self.assertEqual(metrics.tier_label(200), "200")
        self.assertEqual(metrics.tier_label("full"), "full")
        self.assertEqual(metrics.tier_label(999), "other")


CHILD = textwrap.dedent("""
    import os
    from manuspectrum.observability import metrics
    metrics.INFLIGHT_REQUESTS.inc()
    metrics.LOG_RECORDS.labels(level="error", source="django").inc()
    print(os.getpid())
    """)


PRIMING_CHILD = textwrap.dedent("""
    from django.conf import settings
    settings.configure(
        LANGUAGES=[("en", "English"), ("fr", "French")],
        SPECTRUM_PREVIEW_TIERS=(200, 4096),
    )
    from manuspectrum.observability import metrics
    metrics.prime_label_sets(tasks=["manuspectrum.embargo_pass", "celery.chord"])
    """)

FAILURE_SERIES = [
    ("manuspectrum_account_mails_total", {"kind": "invitation", "outcome": "failed"}),
    ("manuspectrum_embargo_lifts_total", {"outcome": "failed"}),
    ("manuspectrum_embargo_lifts_total", {"outcome": "incomplete"}),
    (
        "manuspectrum_workflow_cleanups_total",
        {"kind": "create-project-workflow", "outcome": "failed"},
    ),
    ("manuspectrum_account_anonymisations_total", {"outcome": "failed"}),
    ("manuspectrum_upstream_budget_spent_total", {"kind": "write"}),
    (
        "manuspectrum_celery_tasks_total",
        {"task": "manuspectrum.embargo_pass", "outcome": "failure"},
    ),
    ("manuspectrum_index_resources_total", {"mode": "resource", "outcome": "failed"}),
    ("manuspectrum_explorer_rebuild_failures_total", {"language": "fr"}),
    ("manuspectrum_csp_violations_total", {"directive": "script-src-elem"}),
    (
        "manuspectrum_explorer_bundle_build_seconds_bucket",
        {"language": "en", "le": "13.0"},
    ),
]


def labelled():
    return {
        metric._name: metric
        for metric in declared().values()
        if isinstance(metric, (Counter, Histogram)) and metric._labelnames
    }


class PrimingTests(SimpleTestCase):
    def test_every_labelled_counter_and_histogram_is_primed_or_listed(self):
        primed = {
            metric._name: vocabulary
            for metric, vocabulary in metrics._vocabularies(["manuspectrum.x"])
        }
        self.assertEqual(set(primed) | metrics.UNPRIMED_METRICS, set(labelled()))
        self.assertFalse(set(primed) & metrics.UNPRIMED_METRICS)
        for name, vocabulary in primed.items():
            with self.subTest(metric=name):
                self.assertEqual(tuple(vocabulary), labelled()[name]._labelnames)
                for values in vocabulary.values():
                    self.assertTrue(values)

    @override_settings(LANGUAGES=[("en", "English"), ("fr", "French")])
    def test_the_failure_series_are_in_the_vocabularies(self):
        metrics.prime_label_sets(tasks=["manuspectrum.embargo_pass"])
        for name, labels in FAILURE_SERIES:
            with self.subTest(series=name, labels=labels):
                self.assertIsNotNone(REGISTRY.get_sample_value(name, labels))

    @override_settings(
        LANGUAGES=[("en", "English"), ("fr", "French")],
        SPECTRUM_PREVIEW_TIERS=(200, 4096),
    )
    def test_priming_is_idempotent_and_bounded(self):
        tasks = [f"manuspectrum.task_{n}" for n in range(40)] + ["celery.chord"]
        first = metrics.prime_label_sets(tasks=tasks)
        self.assertEqual(metrics.prime_label_sets(tasks=tasks), first)
        self.assertEqual(first - metrics.prime_label_sets(), 40 * 3)
        self.assertLess(first, 600)

    @override_settings(LANGUAGES=None)
    def test_an_error_is_logged_and_never_raised(self):
        with self.assertLogs("manuspectrum.observability.metrics", "WARNING"):
            self.assertEqual(metrics.prime_label_sets(), 0)

    def test_the_app_primes_when_it_is_ready(self):
        config = apps.get_app_config("manuspectrum")
        with (
            patch.object(metrics, "prime_label_sets") as prime,
            patch.object(config, "_check_async_indexing_config"),
            patch.object(config, "_check_contact_email_config"),
        ):
            config.ready()
        prime.assert_called_once_with()


class MultiprocessTests(SimpleTestCase):
    def run_child(self, directory, code=CHILD):
        result = subprocess.run(
            [sys.executable, "-c", code],
            env={
                "PATH": os.environ["PATH"],
                "PYTHONPATH": str(ROOT),
                "PROMETHEUS_MULTIPROC_DIR": directory,
            },
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        return result.stdout

    def collect(self, directory):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry, path=directory)
        return registry

    def test_livesum_forgets_a_dead_process_and_counters_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            first = int(self.run_child(directory).strip().splitlines()[-1])
            self.run_child(directory)
            registry = self.collect(directory)
            self.assertEqual(
                registry.get_sample_value("manuspectrum_inflight_requests"), 2.0
            )
            multiprocess.mark_process_dead(first, path=directory)
            registry = self.collect(directory)
            self.assertEqual(
                registry.get_sample_value("manuspectrum_inflight_requests"), 1.0
            )
            self.assertEqual(
                registry.get_sample_value(
                    "manuspectrum_log_records_total",
                    {"level": "error", "source": "django"},
                ),
                2.0,
            )

    def test_a_primed_process_exposes_its_failure_series_at_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            self.run_child(directory, PRIMING_CHILD)
            registry = self.collect(directory)
            for name, labels in FAILURE_SERIES:
                with self.subTest(series=name, labels=labels):
                    self.assertEqual(registry.get_sample_value(name, labels), 0.0)
            self.assertIsNone(
                registry.get_sample_value(
                    "manuspectrum_celery_tasks_total",
                    {"task": "celery.chord", "outcome": "failure"},
                )
            )
