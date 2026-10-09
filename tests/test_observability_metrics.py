import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from django.test import SimpleTestCase, override_settings
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
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
        self.assertEqual(len(declared()), 34)

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


class MultiprocessTests(SimpleTestCase):
    def run_child(self, directory):
        result = subprocess.run(
            [sys.executable, "-c", CHILD],
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
        return int(result.stdout.strip().splitlines()[-1])

    def collect(self, directory):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry, path=directory)
        return registry

    def test_livesum_forgets_a_dead_process_and_counters_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.run_child(directory)
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
