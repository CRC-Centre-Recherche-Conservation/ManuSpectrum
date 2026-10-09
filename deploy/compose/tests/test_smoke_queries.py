# deploy/compose/tests/test_smoke_queries.py
"""The host-side helpers of `smoke.sh monitoring` (PP-6).

The live check that every metric a rule reads exists in Prometheus uses its own
copy of the metric extractor; the first test keeps it equal to the one that
pins the rules offline.
"""

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

COMPOSE_DIR = Path(__file__).resolve().parents[1]
HELPER = COMPOSE_DIR / "observability" / "smoke_queries.py"
DASHBOARDS = COMPOSE_DIR / "observability" / "grafana" / "dashboards"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


smoke_queries = load(HELPER, "smoke_queries")


def rules_answer(*rules):
    return {"data": {"groups": [{"rules": list(rules)}]}}


def alert(query):
    return {"type": "alerting", "name": "A", "query": query}


class BucketBoundsTests(unittest.TestCase):
    def test_the_le_values_rules_select_are_listed(self):
        answer = rules_answer(
            alert(
                'sum(increase(m_seconds_bucket{le="13.0"}[1h])) '
                '/ sum(increase(m_seconds_bucket{language="fr", le="55.0"}[1h]))'
                " and rate(other_total[5m]) > 0"
            )
        )
        self.assertEqual(
            smoke_queries.bucket_bounds(answer),
            [("m_seconds_bucket", "13.0"), ("m_seconds_bucket", "55.0")],
        )


class MissingMetricsTests(unittest.TestCase):
    def test_a_name_unknown_to_prometheus_is_reported(self):
        answer = rules_answer(alert("pg_stat_activity_cuont > 1 and up == 1"))
        names = {"data": ["up", "pg_stat_activity_count"]}
        self.assertEqual(
            smoke_queries.missing_metrics(answer, names), ["pg_stat_activity_cuont"]
        )

    def test_optional_and_recorded_series_are_not_reported(self):
        answer = rules_answer(
            {"type": "recording", "name": "job:rate", "query": "rate(up[5m])"},
            alert("job:rate > 0 or manuspectrum_backup_failed == 1 or ALERTS > 0"),
        )
        self.assertEqual(smoke_queries.missing_metrics(answer, {"data": ["up"]}), [])

    def test_the_extractor_agrees_with_the_offline_contract_test(self):
        try:
            contract = load(
                COMPOSE_DIR / "tests" / "test_rules_contract.py", "rules_contract"
            )
            rules = contract.load_rules()
        except (ImportError, TypeError):
            self.skipTest("PyYAML is not installed")
        self.assertTrue(rules)
        for _, rule in rules:
            with self.subTest(rule=rule.get("alert") or rule.get("record")):
                self.assertEqual(
                    smoke_queries.metric_names_in(rule["expr"]),
                    contract.metric_names_in(rule["expr"]),
                )


class OptionalMetricsTests(unittest.TestCase):
    METRICS_PY = (
        COMPOSE_DIR.parents[1] / "manuspectrum" / "observability" / "metrics.py"
    )

    def derived(self):
        """Series of every labelled Counter/Histogram declared in metrics.py."""
        names = set()
        for node in ast.walk(ast.parse(self.METRICS_PY.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("Counter", "Histogram")
            ):
                continue
            labels = node.args[2] if len(node.args) > 2 else None
            for keyword in node.keywords:
                if keyword.arg == "labelnames":
                    labels = keyword.value
            if labels is None or not labels.elts:
                continue
            base = node.args[0].value
            if node.func.id == "Counter":
                names.add(base + "_total")
            else:
                names.update({base + "_bucket", base + "_count", base + "_sum"})
        return names

    def test_every_labelled_counter_and_histogram_is_optional(self):
        derived = self.derived()
        self.assertIn("manuspectrum_explorer_rebuild_failures_total", derived)
        self.assertEqual(smoke_queries.LABELLED_APP_METRICS, derived)
        self.assertLessEqual(derived, smoke_queries.OPTIONAL_METRICS)

    def test_unlabelled_application_metrics_stay_strict(self):
        text = self.METRICS_PY.read_text(encoding="utf-8")
        for name in ("manuspectrum_biblissima_slot_timeouts_total",):
            self.assertIn(name[: -len("_total")], text)
            self.assertNotIn(name, smoke_queries.OPTIONAL_METRICS)

    def test_the_event_series_a_fresh_stack_lacks_are_not_reported(self):
        answer = rules_answer(
            alert("increase(manuspectrum_explorer_rebuild_failures_total[30m]) > 0"),
            alert('max(redis_key_size{key="celery"}) > 100'),
            alert("manuspectrum_unknown_total > 1"),
        )
        self.assertEqual(
            smoke_queries.missing_metrics(answer, {"data": ["up"]}),
            ["manuspectrum_unknown_total"],
        )


class DashboardQueriesTests(unittest.TestCase):
    def test_every_expression_comes_out_as_one_encoded_line(self):
        expected = smoke_queries.dashboard_expressions(DASHBOARDS)
        self.assertGreater(len(expected), 20)
        out = subprocess.run(
            [sys.executable, str(HELPER), "dashboard-queries", str(DASHBOARDS)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertEqual(
            [urllib.parse.unquote(line) for line in out],
            [" ".join(e.split()) for e in expected],
        )
        for line in out:
            self.assertNotRegex(line, r"[\s{}\"]")

    def test_no_expression_uses_a_grafana_variable(self):
        for expr in smoke_queries.dashboard_expressions(DASHBOARDS):
            self.assertNotIn("$", expr)

    def test_missing_metrics_command_prints_one_name_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = Path(tmp) / "rules.json"
            names = Path(tmp) / "names.json"
            rules.write_text(json.dumps(rules_answer(alert("typo_total > 1"))))
            names.write_text(json.dumps({"data": ["up"]}))
            out = subprocess.run(
                [
                    sys.executable,
                    str(HELPER),
                    "missing-metrics",
                    str(rules),
                    str(names),
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        self.assertEqual(out, "typo_total\n")


if __name__ == "__main__":
    unittest.main()
