# deploy/compose/tests/test_smoke_queries.py
"""The host-side helpers of `smoke.sh monitoring` (PP-6).

The live check that every metric a rule reads exists in Prometheus uses its own
copy of the metric extractor; the first test keeps it equal to the one that
pins the rules offline.
"""

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
