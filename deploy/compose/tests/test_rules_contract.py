# deploy/compose/tests/test_rules_contract.py
"""Contract of the Prometheus alert rules (PP-6).

Reads deploy/compose/observability/prometheus/rules/*.yml and pins what an
operator relies on: closed label sets, a bounded `for`, a runbook section per
alert, only metrics that exist, no high-cardinality label, and a promtool unit
case for the alerts that guard data and money. The rule semantics themselves
are proved by `promtool test rules` (observability/check.sh).
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

COMPOSE_DIR = Path(__file__).resolve().parents[1]
REPO = COMPOSE_DIR.parents[1]
OBSERVABILITY = COMPOSE_DIR / "observability"
RULES_DIR = OBSERVABILITY / "prometheus" / "rules"
RULE_TESTS_DIR = OBSERVABILITY / "prometheus" / "rule-tests"
RUNBOOKS = REPO / "deploy" / "runbooks"
METRICS_PY = REPO / "manuspectrum" / "observability" / "metrics.py"
MULTIPROC_PY = REPO / "manuspectrum" / "observability" / "multiproc.py"
TEXTFILE_SCRIPTS = [
    REPO / "deploy" / "scripts" / "backup.sh",
    REPO / "deploy" / "scripts" / "restore-test.sh",
]

RUNBOOK_BASE = (
    "https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum/"
    "blob/main/deploy/runbooks/"
)
SEVERITIES = {"critical", "warning", "info", "none"}
# `none` is for the two rules that route nothing to a human.
NONE_ALERTS = {"Watchdog", "RecentlyRebooted"}
SERVICES = {
    "site",
    "application",
    "explorer",
    "biblissima",
    "celery",
    "host",
    "storage",
    "containers",
    "postgres",
    "redis",
    "tls",
    "backup",
    "monitoring",
}
MAX_FOR_SECONDS = {
    "critical": 30 * 60,
    "warning": 6 * 3600,
    "info": 2 * 3600,
    "none": 0,
}
RUNBOOK_SECTIONS = [
    "Prerequisites",
    "Symptom",
    "Diagnosis",
    "Remediation",
    "Escalation",
]

# Label names that would make a series per request, user or object.
HIGH_CARDINALITY_LABELS = {
    "email",
    "file_id",
    "id",
    "ip",
    "path",
    "qid",
    "query",
    "request_id",
    "resource_id",
    "resourceid",
    "uri",
    "url",
    "user",
    "user_id",
    "userid",
    "username",
    "client",
    "remote_addr",
    "queryid",
}

# Alerts a promtool case must cover (plan, Task 4).
REQUIRED_TESTED = {
    "BackupMissing",
    "BackupFailed",
    "RestoreTestFailed",
    "RestoreTestMissing",
    "DiskUsageHigh",
    "DiskAlmostFull",
    "NfsUnavailable",
    "CertificateExpiringSoon",
    "CertificateExpiryCritical",
    "ContainerRestartLoop",
    "ContainerOOMKilled",
    "WebMemoryNearLimit",
    "ErrorRateHigh",
    "HostRebooted",
    "RecentlyRebooted",
    "Watchdog",
    "DiskFillingUp",
    "MetricsDirFilling",
}

# Series written by deploy/scripts/host-metrics.sh (Task 6 keeps these names).
HOST_METRICS = {
    "manuspectrum_container_up",
    "manuspectrum_container_healthy",
    "manuspectrum_container_restarts",
    "manuspectrum_container_oom_kills",
    "manuspectrum_container_memory_working_set_bytes",
    "manuspectrum_container_memory_limit_bytes",
    "manuspectrum_container_metrics_last_run_timestamp_seconds",
    "manuspectrum_disk_usage_last_run_timestamp_seconds",
    "manuspectrum_container_oom_cgroup",
    "manuspectrum_disk_usage_last_success_timestamp_seconds",
    "manuspectrum_docker_disk_bytes",
    "manuspectrum_docker_volume_bytes",
}
# Series of the exporters and of Prometheus itself that the rules may read.
EXPORTER_METRICS = {
    "up",
    "probe_success",
    "probe_ssl_earliest_cert_expiry",
    "node_filesystem_avail_bytes",
    "node_filesystem_size_bytes",
    "node_filesystem_device_error",
    "node_boot_time_seconds",
    "node_memory_SwapTotal_bytes",
    "node_memory_SwapFree_bytes",
    "node_pressure_memory_waiting_seconds_total",
    "node_timex_sync_status",
    "node_textfile_scrape_error",
    "pg_stat_activity_count",
    "pg_settings_max_connections",
    "redis_key_size",
    "redis_memory_used_bytes",
    "redis_memory_max_bytes",
    "alertmanager_notifications_failed_total",
    "prometheus_rule_evaluation_failures_total",
    "django_http_responses_total_by_status_view_method_total",
    "django_http_requests_latency_seconds_by_view_method_bucket",
    "django_http_requests_latency_seconds_by_view_method_count",
}

PROMQL_WORDS = {
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


def registry_metrics():
    """Series exposed by manuspectrum/observability/metrics.py, with suffixes."""
    names = set()
    text = METRICS_PY.read_text(encoding="utf-8")
    for kind, name in re.findall(
        r'(Counter|Histogram|gauge)\(\s*"(manuspectrum_[a-z_]+)"', text
    ):
        if kind == "Counter":
            names.add(name + "_total")
        elif kind == "Histogram":
            names.update({name + "_bucket", name + "_sum", name + "_count"})
        else:
            names.add(name)
    for match in re.findall(
        r'DIR_BYTES_NAME = "(manuspectrum_[a-z_]+)"', MULTIPROC_PY.read_text("utf-8")
    ):
        names.add(match)
    return names


def textfile_metrics():
    names = set()
    for script in TEXTFILE_SCRIPTS:
        names.update(
            re.findall(
                r"\bmanuspectrum_[a-z_]+\b(?!\.prom)",
                script.read_text(encoding="utf-8"),
            )
        )
    return names


def forbidden_label_names(label_names):
    return {n for n in label_names if n in HIGH_CARDINALITY_LABELS}


def label_names_in(expr):
    """Label names used in matchers and in by/without/on/ignoring/group clauses."""
    names = set()
    for body in re.findall(r"\{([^{}]*)\}", expr):
        names.update(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:=~|!~|!=|=)", body))
    for body in re.findall(
        r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\(([^()]*)\)", expr
    ):
        names.update(n.strip() for n in body.split(",") if n.strip())
    return names


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


def duration_seconds(text):
    if text in (None, "", 0, "0"):
        return 0
    match = re.fullmatch(r"(\d+)([smhd])", str(text))
    assert match, f"bad duration {text!r}"
    return (
        int(match.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    )


def slug(heading):
    return re.sub(r"[^a-z0-9 _-]", "", heading.lower()).replace(" ", "-")


def load_rules():
    rules = []
    for path in sorted(RULES_DIR.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for group in document["groups"]:
            for rule in group["rules"]:
                rules.append((path.name, rule))
    return rules


def runbook_headings(path):
    """{alert heading: [its ### sub-headings]} of one runbook file."""
    result, current = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            result[current] = []
        elif line.startswith("### ") and current is not None:
            result[current].append(line[4:].strip())
    return result


@unittest.skipUnless(yaml, "PyYAML missing")
class RuleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = load_rules()
        cls.alerts = [(f, r) for f, r in cls.rules if "alert" in r]

    def test_there_are_rules(self):
        self.assertGreaterEqual(len(self.alerts), 40)

    def test_alert_names_are_unique(self):
        names = [r["alert"] for _, r in self.alerts]
        self.assertEqual(len(names), len(set(names)))

    def test_labels_come_from_the_closed_sets(self):
        for _, rule in self.alerts:
            with self.subTest(alert=rule["alert"]):
                labels = rule.get("labels", {})
                self.assertIn(labels.get("severity"), SEVERITIES)
                self.assertIn(labels.get("service"), SERVICES)
                if labels["severity"] == "none":
                    self.assertIn(rule["alert"], NONE_ALERTS)

    def test_for_is_bounded_by_severity(self):
        for _, rule in self.alerts:
            severity = rule["labels"]["severity"]
            with self.subTest(alert=rule["alert"]):
                if rule["alert"] == "Watchdog":
                    continue
                self.assertLessEqual(
                    duration_seconds(rule.get("for")), MAX_FOR_SECONDS[severity]
                )

    def test_annotations_are_complete_and_english_sentences(self):
        for _, rule in self.alerts:
            with self.subTest(alert=rule["alert"]):
                annotations = rule.get("annotations", {})
                for key in ("summary", "description", "runbook_url"):
                    self.assertTrue(annotations.get(key, "").strip(), key)

    def test_every_runbook_url_names_an_existing_section_with_five_parts(self):
        for filename, rule in self.alerts:
            url = rule["annotations"]["runbook_url"]
            with self.subTest(alert=rule["alert"]):
                self.assertTrue(url.startswith(RUNBOOK_BASE), url)
                path_part, _, fragment = url[len(RUNBOOK_BASE) :].partition("#")
                runbook = RUNBOOKS / path_part
                self.assertTrue(runbook.is_file(), f"{runbook} is missing")
                headings = runbook_headings(runbook)
                by_slug = {slug(h): h for h in headings}
                self.assertIn(fragment, by_slug, f"no section for #{fragment}")
                self.assertEqual(headings[by_slug[fragment]], RUNBOOK_SECTIONS)

    def test_section_title_is_the_alert_name(self):
        for _, rule in self.alerts:
            url = rule["annotations"]["runbook_url"]
            self.assertTrue(url.endswith("#" + rule["alert"].lower()), rule["alert"])

    def test_no_runbook_section_is_orphaned(self):
        wanted = {
            r["annotations"]["runbook_url"].partition("#")[2] for _, r in self.alerts
        }
        for runbook in RUNBOOKS.glob("*.md"):
            for heading in runbook_headings(runbook):
                with self.subTest(runbook=runbook.name, heading=heading):
                    self.assertIn(slug(heading), wanted)

    def test_no_high_cardinality_label_in_rules(self):
        for _, rule in self.rules:
            with self.subTest(rule=rule.get("alert") or rule.get("record")):
                self.assertEqual(
                    forbidden_label_names(label_names_in(rule["expr"])), set()
                )
                self.assertEqual(
                    forbidden_label_names(rule.get("labels", {}).keys()), set()
                )

    def test_alert_labels_never_overwrite_a_series_label(self):
        for _, rule in self.alerts:
            with self.subTest(alert=rule["alert"]):
                clash = label_names_in(rule["expr"]) & set(rule["labels"])
                self.assertEqual(clash, set())

    def test_forbidden_label_detector_sees_a_bad_expression(self):
        bad = 'sum by (path) (rate(x_total{user="a"}[5m]))'
        self.assertEqual(forbidden_label_names(label_names_in(bad)), {"path", "user"})

    def test_every_metric_in_an_expression_exists(self):
        known = (
            registry_metrics() | textfile_metrics() | HOST_METRICS | EXPORTER_METRICS
        )
        for _, rule in self.rules:
            with self.subTest(rule=rule.get("alert") or rule.get("record")):
                unknown = metric_names_in(rule["expr"]) - known - {"ALERTS"}
                self.assertEqual(unknown, set())

    def test_metric_extractor_sees_a_typo(self):
        expr = 'sum(rate(manuspectrum_log_record_total{level="error"}[5m])) > 1 and up == 1'
        self.assertEqual(metric_names_in(expr), {"manuspectrum_log_record_total", "up"})
        self.assertNotIn("manuspectrum_log_record_total", registry_metrics())

    def test_registry_names_carry_their_suffixes(self):
        names = registry_metrics()
        self.assertIn("manuspectrum_log_records_total", names)
        self.assertIn("manuspectrum_explorer_bundle_build_seconds_bucket", names)
        self.assertIn("manuspectrum_metrics_dir_bytes", names)
        self.assertIn("manuspectrum_backup_failed", textfile_metrics())

    def test_critical_alerts_are_few(self):
        critical = [r for _, r in self.alerts if r["labels"]["severity"] == "critical"]
        self.assertLessEqual(len(critical), 16)

    def test_every_required_alert_has_a_promtool_case(self):
        tested = set()
        for path in RULE_TESTS_DIR.glob("*.yml"):
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            for case in document.get("tests", []):
                for entry in case.get("promql_expr_test", []):
                    tested.update(re.findall(r'alertname="(\w+)"', entry["expr"]))
        self.assertEqual(REQUIRED_TESTED - tested, set())
        defined = {r["alert"] for _, r in self.alerts}
        self.assertEqual(REQUIRED_TESTED - defined, set())

    def test_retired_alerts_stay_retired(self):
        names = {r["alert"] for _, r in self.alerts}
        self.assertFalse({n for n in names if "Traffic" in n or "BurnRate" in n})

    def test_disk_alerts_cover_both_filesystems(self):
        by_name = {r["alert"]: r["expr"] for _, r in self.alerts}
        for name in ("DiskUsageHigh", "DiskAlmostFull", "DiskFillingUp"):
            with self.subTest(alert=name):
                self.assertRegex(by_name[name], r'mountpoint=~"/\|/data"')

    def test_event_warnings_read_a_stored_window_not_in_memory_state(self):
        events = {
            "ContainerOOMKilled",
            "ContainerRestartLoop",
            "CeleryTaskFailures",
            "IndexingFailures",
            "ExplorerRebuildFailing",
            "WriteBudgetSpent",
            "PrometheusRuleFailures",
        }
        by_name = {r["alert"]: r for _, r in self.alerts}
        for name in events:
            with self.subTest(alert=name):
                self.assertNotIn("keep_firing_for", by_name[name])
                # Friday 19:00 to Monday 08:00 is 61 hours.
                hours = {
                    int(h)
                    for h in re.findall(r"\[(\d+)h(?::\d+m)?\]", by_name[name]["expr"])
                }
                self.assertTrue(
                    any(61 <= h <= 96 for h in hours), by_name[name]["expr"]
                )

    def test_no_rule_uses_keep_firing_for(self):
        for _, rule in self.alerts:
            with self.subTest(alert=rule["alert"]):
                self.assertNotIn("keep_firing_for", rule)

    def test_node_exporter_outage_is_critical_and_not_a_target_down(self):
        by_name = {r["alert"]: r for _, r in self.alerts}
        down = by_name["NodeExporterDown"]
        self.assertEqual(down["labels"]["severity"], "critical")
        self.assertEqual(down["labels"]["service"], "monitoring")
        self.assertIn('up{job="node"} == 0', down["expr"])
        self.assertIn('job!="node"', by_name["TargetDown"]["expr"])

    def test_annotations_use_only_labels_the_series_carries(self):
        by_name = {r["alert"]: r for _, r in self.alerts}
        # manuspectrum_container_oom_cgroup is one unlabelled gauge.
        self.assertNotIn(
            "$labels.container",
            by_name["OomSourceDegraded"]["annotations"]["description"],
        )

    def test_absent_based_alerts_wait_for_node_exporter(self):
        for _, rule in self.alerts:
            if "absent(" in rule["expr"]:
                with self.subTest(alert=rule["alert"]):
                    self.assertIn('up{job="node"} == 1', rule["expr"])

    def test_the_fresh_install_silence_covers_the_alerts_a_new_host_raises(self):
        makefile = (REPO / "deploy" / "Makefile").read_text(encoding="utf-8")
        recipe = makefile.split("\nsilence-fresh-install:")[1].split("\n\n")[0]
        matcher = re.search(r"alertname=~\"([^\"]+)\"", recipe)[1]
        silenced = set(matcher.split("|"))
        absent_based = {r["alert"] for _, r in self.alerts if "absent(" in r["expr"]}
        self.assertLessEqual(absent_based - {"NfsUnavailable"}, silenced)
        self.assertIn("--duration=48h", recipe)
        self.assertIn("--comment=", recipe)

    def test_slow_build_alerts_need_a_minimum_of_builds(self):
        by_name = {r["alert"]: r["expr"] for _, r in self.alerts}
        for name in ("ExplorerBundleBuildSlow", "ExplorerBundleBuildVerySlow"):
            with self.subTest(alert=name):
                self.assertRegex(
                    by_name[name], r"bundle_build_seconds_count\[1h\].*>= 3"
                )

    def test_certificate_invalid_is_off_on_rehearsal_names(self):
        rule = {r["alert"]: r["expr"] for _, r in self.alerts}["CertificateInvalid"]
        self.assertIn('rehearsal="false"', rule)

    def test_labelled_counters_default_to_zero(self):
        by_name = {r["alert"]: r["expr"] for _, r in self.alerts}
        for name in ("ErrorRateHigh", "BiblissimaBusy"):
            with self.subTest(alert=name):
                self.assertIn("or vector(0)", by_name[name])


@unittest.skipUnless(
    yaml and shutil.which("docker") and shutil.which("bash"), "docker or PyYAML missing"
)
class RuleUnitTests(unittest.TestCase):
    def test_promtool_checks_and_tests_the_rules(self):
        result = subprocess.run(
            ["bash", str(OBSERVABILITY / "check.sh")], capture_output=True, text=True
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("SUCCESS: prometheus rules and unit tests", output)


if __name__ == "__main__":
    unittest.main()
