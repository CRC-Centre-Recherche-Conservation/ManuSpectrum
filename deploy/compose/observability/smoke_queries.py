#!/usr/bin/env python3
"""Helpers of `deploy/compose/smoke.sh monitoring`, run on the host.

  smoke_queries.py dashboard-queries DIR
      One URL-encoded PromQL expression per line, taken from the panels of
      every dashboard JSON in DIR (duplicates removed), ready for the
      `query` parameter of `/api/v1/query`.
  smoke_queries.py missing-metrics RULES_JSON NAMES_JSON
      The metric names that rules read and Prometheus does not know.
      RULES_JSON is the answer of `/api/v1/rules`, NAMES_JSON the one of
      `/api/v1/label/__name__/values`. Series of OPTIONAL_METRICS and the
      names recorded by the rules themselves are not reported.

Standard library only.
"""

import json
import re
import sys
import urllib.parse
from pathlib import Path

# Series that can be legitimately absent from a running stack: the backup and
# restore-test gauges exist only after the first run of those jobs, ALERTS
# only while an alert is pending or firing.
OPTIONAL_METRICS = frozenset(
    {
        "ALERTS",
        "manuspectrum_backup_failed",
        "manuspectrum_backup_last_attempt_timestamp_seconds",
        "manuspectrum_backup_last_success_timestamp_seconds",
        "manuspectrum_backup_dump_bytes",
        "manuspectrum_backup_duration_seconds",
        "manuspectrum_restore_test_failed",
        "manuspectrum_restore_test_last_attempt_timestamp_seconds",
        "manuspectrum_restore_test_last_success_timestamp_seconds",
        "manuspectrum_restore_test_duration_seconds",
    }
)

PROMQL_WORDS = frozenset(
    {
        "by",
        "without",
        "on",
        "ignoring",
        "group_left",
        "group_right",
        "and",
        "or",
        "unless",
        "bool",
        "offset",
        "inf",
        "nan",
    }
)


def metric_names_in(expr):
    """Metric names an expression reads (identifiers that are not functions)."""
    text = re.sub(r'"[^"]*"', '""', expr)
    text = re.sub(r"\{[^{}]*\}", "", text)
    text = re.sub(
        r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^()]*\)", " ", text
    )
    text = re.sub(r"\[[^\]]*\]", "", text)
    names = set()
    for match in re.finditer(
        r"(?<![A-Za-z0-9_:.])([A-Za-z_:][A-Za-z0-9_:]*)(?![A-Za-z0-9_:])(?!\s*\()", text
    ):
        word = match.group(1)
        if word in PROMQL_WORDS or re.fullmatch(r"\d+(e\d+)?", word):
            continue
        names.add(word)
    return names


def dashboard_expressions(directory):
    """Every distinct `expr` of the panels (rows included) of the dashboards."""
    found = []

    def walk(panels):
        for panel in panels:
            for target in panel.get("targets", []):
                if target.get("expr") and target["expr"] not in found:
                    found.append(target["expr"])
            walk(panel.get("panels", []))

    for path in sorted(Path(directory).glob("*.json")):
        walk(json.loads(path.read_text(encoding="utf-8")).get("panels", []))
    return found


def missing_metrics(rules_answer, names_answer):
    """Names read by the rules, unknown to Prometheus, not optional."""
    rules = [
        rule for group in rules_answer["data"]["groups"] for rule in group["rules"]
    ]
    recorded = {rule["name"] for rule in rules if rule["type"] == "recording"}
    known = set(names_answer["data"]) | recorded | OPTIONAL_METRICS
    wanted = set()
    for rule in rules:
        wanted |= metric_names_in(rule["query"])
    return sorted(wanted - known)


def main(argv):
    if len(argv) == 3 and argv[1] == "dashboard-queries":
        for expr in dashboard_expressions(argv[2]):
            print(urllib.parse.quote(" ".join(expr.split()), safe=""))
        return 0
    if len(argv) == 4 and argv[1] == "missing-metrics":
        answers = [json.loads(Path(p).read_text(encoding="utf-8")) for p in argv[2:]]
        for name in missing_metrics(*answers):
            print(name)
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
