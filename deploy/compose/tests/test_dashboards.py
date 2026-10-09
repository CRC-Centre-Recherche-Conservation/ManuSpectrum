# deploy/compose/tests/test_dashboards.py
"""Grafana provisioning and dashboards of the monitoring stack (PP-6).

Reads deploy/compose/observability/grafana/ and pins what an operator relies
on: the datasource and the provider are files, the dashboards are JSON in Git
with stable uids, every query reads a series that exists, the storage
dashboard answers the questions about disk usage, and Grafana sends nothing
outside. `GRAFANA_E2E=1` also starts the pinned Grafana image on the files and
asks its API for the dashboards.
"""

import json
import os
import re
import shutil
import subprocess
import unittest
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

from test_rules_contract import (
    EXPORTER_METRICS,
    HOST_METRICS,
    label_names_in,
    metric_names_in,
    registry_metrics,
    textfile_metrics,
    forbidden_label_names,
)

COMPOSE_DIR = Path(__file__).resolve().parents[1]
GRAFANA_DIR = COMPOSE_DIR / "observability" / "grafana"
RULES_DIR = COMPOSE_DIR / "observability" / "prometheus" / "rules"
DASHBOARDS_DIR = GRAFANA_DIR / "dashboards"
PROVISIONING_DIR = GRAFANA_DIR / "provisioning"
ALERT_TEMPLATE = (
    COMPOSE_DIR / "observability" / "alertmanager" / "templates" / "email.tmpl"
)

EXPECTED_DASHBOARDS = {
    "ms-overview": "ManuSpectrum - Overview",
    "ms-application": "ManuSpectrum - Application",
    "ms-infrastructure": "ManuSpectrum - Infrastructure",
    "ms-storage": "ManuSpectrum - Storage and backups",
    "ms-activity": "ManuSpectrum - Activity",
}

# Series the dashboards read that no rule reads.
DASHBOARD_METRICS = {
    "ALERTS",
    "manuspectrum_disk_usage_bytes",
    "manuspectrum_disk_usage_failed",
    "manuspectrum_disk_usage_last_success_timestamp_seconds",
    "manuspectrum_backup_dump_bytes",
    "manuspectrum_backup_duration_seconds",
    "manuspectrum_backup_last_attempt_timestamp_seconds",
    "manuspectrum_restore_test_failed",
    "manuspectrum_restore_test_duration_seconds",
    "manuspectrum_restore_test_last_attempt_timestamp_seconds",
    "manuspectrum_container_metrics_errors",
    "prometheus_tsdb_storage_blocks_bytes",
    "prometheus_tsdb_wal_storage_size_bytes",
    "prometheus_tsdb_retention_limit_bytes",
    "pg_database_size_bytes",
    "pg_up",
    "redis_up",
    "node_cpu_seconds_total",
    "node_load1",
    "node_memory_MemTotal_bytes",
    "node_memory_MemAvailable_bytes",
    "node_time_seconds",
}
DISK_TARGETS = {"media", "restic", "dumps", "nginx_logs"}


def recorded_metrics():
    """Names recorded by prometheus/rules/activity.yml."""
    text = (RULES_DIR / "activity.yml").read_text("utf-8")
    return set(re.findall(r"^\s*- record: (\S+)$", text, re.M))


def known_metrics():
    return (
        recorded_metrics()
        | registry_metrics()
        | textfile_metrics()
        | HOST_METRICS
        | EXPORTER_METRICS
        | DASHBOARD_METRICS
    )


def load_dashboards():
    result = {}
    for path in sorted(DASHBOARDS_DIR.glob("*.json")):
        result[path.name] = json.loads(path.read_text(encoding="utf-8"))
    return result


def walk_panels(dashboard):
    for panel in dashboard.get("panels", []):
        yield panel
        yield from panel.get("panels", [])


def exprs(dashboard):
    for panel in walk_panels(dashboard):
        for target in panel.get("targets", []):
            yield panel, target["expr"]


class DashboardFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboards = load_dashboards()

    def by_uid(self):
        return {d["uid"]: d for d in self.dashboards.values()}

    def test_the_dashboards_exist_with_stable_uids_and_titles(self):
        self.assertEqual(
            {d["uid"]: d["title"] for d in self.dashboards.values()},
            EXPECTED_DASHBOARDS,
        )

    def test_uids_and_titles_are_unique_and_files_are_named_by_uid(self):
        uids = [d["uid"] for d in self.dashboards.values()]
        self.assertEqual(len(uids), len(set(uids)))
        for name, dashboard in self.dashboards.items():
            self.assertEqual(name, dashboard["uid"] + ".json")

    def test_dashboards_carry_no_database_id_and_use_the_browser_timezone(self):
        for dashboard in self.dashboards.values():
            with self.subTest(uid=dashboard["uid"]):
                self.assertIsNone(dashboard.get("id"))
                self.assertEqual(dashboard["timezone"], "browser")
                self.assertIn("manuspectrum", dashboard["tags"])

    def test_panel_ids_are_unique_per_dashboard(self):
        for dashboard in self.dashboards.values():
            ids = [p["id"] for p in walk_panels(dashboard)]
            with self.subTest(uid=dashboard["uid"]):
                self.assertEqual(len(ids), len(set(ids)))

    def test_every_panel_and_target_uses_the_provisioned_datasource(self):
        for dashboard in self.dashboards.values():
            for panel in walk_panels(dashboard):
                if panel["type"] == "row" or not panel.get("targets"):
                    continue
                with self.subTest(uid=dashboard["uid"], panel=panel["title"]):
                    self.assertEqual(panel["datasource"]["uid"], "prometheus")
                    for target in panel["targets"]:
                        self.assertEqual(target["datasource"]["uid"], "prometheus")
                        self.assertTrue(target["expr"].strip())

    def test_every_panel_has_a_title_and_a_description(self):
        for dashboard in self.dashboards.values():
            for panel in walk_panels(dashboard):
                if panel["type"] == "row":
                    continue
                with self.subTest(uid=dashboard["uid"], panel=panel.get("title")):
                    self.assertTrue(panel["title"].strip())
                    self.assertTrue(panel["description"].strip())

    def test_every_query_reads_an_existing_series(self):
        known = known_metrics()
        seen = set()
        for dashboard in self.dashboards.values():
            for panel, expr in exprs(dashboard):
                with self.subTest(uid=dashboard["uid"], panel=panel["title"]):
                    names = metric_names_in(expr)
                    self.assertEqual(names - known, set())
                    seen |= names
        self.assertGreaterEqual(len(seen), 40)

    def test_no_query_uses_a_high_cardinality_label(self):
        for dashboard in self.dashboards.values():
            for panel, expr in exprs(dashboard):
                with self.subTest(uid=dashboard["uid"], panel=panel["title"]):
                    self.assertEqual(forbidden_label_names(label_names_in(expr)), set())

    def test_the_series_extractor_sees_a_typo_and_the_retired_names(self):
        self.assertEqual(
            metric_names_in("sum(manuspectrum_docker_volume_byte)") - known_metrics(),
            {"manuspectrum_docker_volume_byte"},
        )
        retired = ('area="',)
        for dashboard in self.dashboards.values():
            text = json.dumps(dashboard)
            for word in retired:
                self.assertNotIn(word, text)

    def test_no_query_depends_on_a_dashboard_variable_other_than_the_range(self):
        for dashboard in self.dashboards.values():
            for panel, expr in exprs(dashboard):
                with self.subTest(uid=dashboard["uid"], panel=panel["title"]):
                    self.assertEqual(re.findall(r"\$\w+", expr), [])

    def test_the_alert_mail_links_to_an_existing_dashboard(self):
        links = re.findall(
            r"http://localhost:3000/d/([a-z0-9-]+)", ALERT_TEMPLATE.read_text("utf-8")
        )
        self.assertTrue(links)
        for uid in links:
            self.assertIn(uid, self.by_uid())

    def test_the_application_dashboard_shows_active_accounts_as_one_number(self):
        panels = {
            p["title"]: p
            for p in walk_panels(self.by_uid()["ms-application"])
            if p.get("targets")
        }
        for title, kind in (
            ("Active accounts", "stat"),
            ("Active accounts, last 30 days", "timeseries"),
        ):
            with self.subTest(panel=title):
                self.assertEqual(panels[title]["type"], kind)
                self.assertEqual(
                    [t["expr"] for t in panels[title]["targets"]],
                    ["max(manuspectrum_active_accounts)"],
                )

    def test_the_active_accounts_panels_show_what_their_text_promises(self):
        panels = {p["title"]: p for p in walk_panels(self.by_uid()["ms-application"])}
        self.assertEqual(panels["Active accounts, last 30 days"]["timeFrom"], "30d")
        self.assertEqual(panels["Active accounts"]["options"]["graphMode"], "none")

    def test_the_activity_dashboard_inventory(self):
        panels = {
            p["title"]: p
            for p in walk_panels(self.by_uid()["ms-activity"])
            if p.get("targets")
        }
        text = "\n".join(e for _, e in exprs(self.by_uid()["ms-activity"]))
        for series in (
            "manuspectrum:consultations:total",
            "manuspectrum:consultations:rate1h",
            "manuspectrum_explorer_export_bytes_count",
            "manuspectrum_explorer_export_bytes_sum",
            "manuspectrum_auth_logins_total",
            "manuspectrum_biblissima_created_items_total",
            "manuspectrum_resources",
            "manuspectrum_resource_changes",
            "manuspectrum_workflows",
            "manuspectrum_activity_timestamp_seconds",
            'view="transaction_reverse"',
        ):
            with self.subTest(series=series):
                self.assertIn(series, text)
        self.assertEqual(
            panels["Consultations per day by kind"]["targets"][0]["interval"], "1d"
        )
        for title in ("Failing writes (5xx) by view", "Refused writes (4xx) by view"):
            with self.subTest(panel=title):
                (target,) = panels[title]["targets"]
                self.assertIn('method=~"POST|PUT|DELETE"', target["expr"])
                self.assertIn("sum by (view)", target["expr"])

    def test_the_activity_dashboard_counts_nobody(self):
        text = json.dumps(self.by_uid()["ms-activity"])
        for word in ("user", "email", "resource_id", "ip"):
            self.assertNotRegex(text, r'\b%s\b="' % word)

    def test_container_panels_use_the_container_label(self):
        for dashboard in self.dashboards.values():
            for panel, expr in exprs(dashboard):
                if "manuspectrum_container_" in expr:
                    with self.subTest(uid=dashboard["uid"], panel=panel["title"]):
                        self.assertNotIn("service", label_names_in(expr))


class StorageDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = DASHBOARDS_DIR / "ms-storage.json"
        cls.dashboard = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"panels": []}
        )
        cls.exprs = [(p["title"], e) for p, e in exprs(cls.dashboard)]
        cls.text = "\n".join(e for _, e in cls.exprs)

    def has(self, pattern):
        self.assertRegex(self.text, pattern)

    def test_free_space_and_use_of_both_filesystems(self):
        for mountpoint in ("/", "/data"):
            with self.subTest(mountpoint=mountpoint):
                self.has(
                    r'node_filesystem_avail_bytes\{[^}]*mountpoint="%s"'
                    % re.escape(mountpoint)
                )
        self.has(r"node_filesystem_size_bytes")

    def test_every_data_directory_has_its_current_size_and_its_history(self):
        self.has(r"manuspectrum_disk_usage_bytes")
        targets = set(re.findall(r'target="(\w+)"', self.text))
        for target in re.findall(r'target=~"([\w|]+)"', self.text):
            targets.update(target.split("|"))
        self.assertEqual(DISK_TARGETS - targets, set())
        kinds = {p["type"] for p in walk_panels(self.dashboard)}
        self.assertIn("timeseries", kinds)
        self.assertTrue(
            [
                t
                for t, e in self.exprs
                if "manuspectrum_disk_usage_bytes" in e and "stat" not in t.lower()
            ]
        )

    def test_growth_over_thirty_days_and_time_to_full(self):
        self.has(r"manuspectrum_disk_usage_bytes[^\n]*\[30d\]|offset 30d")
        self.has(r"deriv\(node_filesystem_avail_bytes")
        titles = " ".join(t.lower() for t, _ in self.exprs)
        self.assertIn("full", titles)
        self.assertIn("30 days", titles)

    def test_database_size_and_backup_repository_size(self):
        self.has(r"pg_database_size_bytes")
        self.has(r'manuspectrum_disk_usage_bytes\{[^}]*target="restic"')
        self.has(r"manuspectrum_backup_dump_bytes")

    def test_backup_and_restore_test_age_and_state(self):
        self.has(r"time\(\) - manuspectrum_backup_last_success_timestamp_seconds")
        self.has(r"time\(\) - manuspectrum_restore_test_last_success_timestamp_seconds")
        self.has(r"manuspectrum_backup_failed")
        self.has(r"manuspectrum_restore_test_failed")

    def test_docker_disk_use_by_kind_and_by_volume(self):
        self.has(r"manuspectrum_docker_disk_bytes")
        self.has(r"delta\(manuspectrum_docker_disk_bytes[^\n]*\[30d\]")
        self.has(r"manuspectrum_docker_volume_bytes")
        self.has(r"delta\(manuspectrum_docker_volume_bytes[^\n]*\[30d\]")
        titles = {p["title"]: p for p in walk_panels(self.dashboard)}
        self.assertEqual(titles["Volumes now"]["type"], "table")
        self.assertEqual(titles["Volumes now"]["targets"][0]["format"], "table")
        for title in ("Docker use over 30 days", "Volume size over 30 days"):
            with self.subTest(title=title):
                self.assertEqual(titles[title]["type"], "timeseries")
                self.assertEqual(titles[title]["timeFrom"], "30d")

    def test_the_labels_docker_series_carry_are_the_closed_ones(self):
        for title, expr in self.exprs:
            for label in re.findall(r"\{\{(\w+)\}\}", expr):
                self.assertNotIn(label, {"id", "name", "mountpoint"})
        legends = {
            t["legendFormat"]
            for p in walk_panels(self.dashboard)
            for t in p.get("targets", [])
            if "manuspectrum_docker_" in t["expr"]
        }
        self.assertEqual(legends - {"{{kind}}", "{{volume}}", ""}, set())

    def test_prometheus_data_size_against_its_cap(self):
        self.has(r"prometheus_tsdb_storage_blocks_bytes")
        self.has(r"prometheus_tsdb_wal_storage_size_bytes")
        self.has(r"prometheus_tsdb_retention_limit_bytes")
        self.assertIn("Prometheus data vs 8 GB cap", [t for t, _ in self.exprs])

    def test_the_measure_itself_is_shown_with_its_freshness(self):
        self.has(r"manuspectrum_disk_usage_last_success_timestamp_seconds")
        self.has(r"manuspectrum_disk_usage_failed")


@unittest.skipUnless(yaml, "PyYAML missing")
class ProvisioningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = yaml.safe_load((COMPOSE_DIR / "compose.yaml").read_text("utf-8"))
        cls.grafana = cls.compose["services"]["grafana"]

    def read(self, relative):
        return yaml.safe_load((PROVISIONING_DIR / relative).read_text("utf-8"))

    def mounts(self):
        return {
            v["target"]: v
            for v in self.grafana["volumes"]
            if isinstance(v, dict) and v["type"] == "bind"
        }

    def test_the_datasource_is_prometheus_read_only(self):
        document = self.read("datasources/prometheus.yml")
        self.assertEqual(document["apiVersion"], 1)
        (source,) = document["datasources"]
        self.assertEqual(source["uid"], "prometheus")
        self.assertEqual(source["type"], "prometheus")
        self.assertEqual(source["url"], "http://prometheus:9090")
        self.assertEqual(source["access"], "proxy")
        self.assertIs(source["editable"], False)
        self.assertIs(source["isDefault"], True)
        self.assertNotIn("basicAuth", source)
        self.assertNotIn("secureJsonData", source)
        self.assertEqual(document.get("deleteDatasources"), None)

    def test_the_prometheus_service_is_reachable_under_that_name(self):
        self.assertIn("prometheus", self.compose["services"])

    def test_the_provider_reads_the_mounted_dashboards_without_ui_updates(self):
        document = self.read("dashboards/manuspectrum.yml")
        (provider,) = document["providers"]
        self.assertIs(provider["allowUiUpdates"], False)
        self.assertIs(provider["disableDeletion"], True)
        self.assertEqual(provider["folder"], "ManuSpectrum")
        self.assertEqual(provider["type"], "file")
        self.assertEqual(provider["options"]["path"], "/etc/grafana/dashboards")
        self.assertIn("/etc/grafana/dashboards", self.mounts())

    def test_provisioning_and_dashboards_are_mounted_read_only_from_git(self):
        mounts = self.mounts()
        for target, source in (
            ("/etc/grafana/provisioning", "./observability/grafana/provisioning"),
            ("/etc/grafana/dashboards", "./observability/grafana/dashboards"),
        ):
            with self.subTest(target=target):
                self.assertEqual(mounts[target]["source"], source)
                self.assertIs(mounts[target]["read_only"], True)
                self.assertTrue((COMPOSE_DIR / source).is_dir())

    def test_only_known_provisioning_directories_exist(self):
        self.assertEqual(
            {p.name for p in PROVISIONING_DIR.iterdir()}, {"datasources", "dashboards"}
        )

    def test_grafana_is_hardened_and_calls_nothing_outside(self):
        environment = self.grafana["environment"]
        for key, value in {
            "GF_SECURITY_ADMIN_PASSWORD__FILE": "/run/secrets/grafana_admin_password",
            "GF_AUTH_ANONYMOUS_ENABLED": "false",
            "GF_AUTH_BASIC_ENABLED": "true",
            "GF_USERS_ALLOW_SIGN_UP": "false",
            "GF_USERS_ALLOW_ORG_CREATE": "false",
            "GF_SECURITY_DISABLE_GRAVATAR": "true",
            "GF_SECURITY_COOKIE_SAMESITE": "strict",
            "GF_ANALYTICS_REPORTING_ENABLED": "false",
            "GF_ANALYTICS_CHECK_FOR_UPDATES": "false",
            "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES": "false",
            "GF_ANALYTICS_FEEDBACK_LINKS_ENABLED": "false",
            "GF_NEWS_NEWS_FEED_ENABLED": "false",
            "GF_PLUGINS_PLUGIN_ADMIN_ENABLED": "false",
            "GF_PLUGINS_PREINSTALL_DISABLED": "true",
            "GF_PLUGINS_PUBLIC_KEY_RETRIEVAL_DISABLED": "true",
            "GF_UNIFIED_ALERTING_ENABLED": "false",
            "GF_ALERTING_ENABLED": "false",
            "GF_SNAPSHOTS_EXTERNAL_ENABLED": "false",
        }.items():
            with self.subTest(key=key):
                self.assertEqual(environment.get(key), value)
        self.assertNotIn("GF_SECURITY_ADMIN_PASSWORD", environment)

    def test_grafana_is_published_on_loopback_only(self):
        (port,) = self.grafana["ports"]
        self.assertEqual(port["host_ip"], "127.0.0.1")
        self.assertEqual(int(port["target"]), 3000)

    def test_no_dashboard_or_provisioning_file_holds_a_secret_or_a_public_name(self):
        for path in list(PROVISIONING_DIR.rglob("*.yml")) + list(
            DASHBOARDS_DIR.glob("*.json")
        ):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                self.assertNotRegex(text, r"(?i)password|token|secret")
                self.assertNotRegex(text, r"https?://(?!prometheus:9090|localhost)")


@unittest.skipUnless(
    os.environ.get("GRAFANA_E2E") and shutil.which("docker") and yaml,
    "set GRAFANA_E2E=1 (starts the pinned Grafana image)",
)
class GrafanaLoadsTheFilesTests(unittest.TestCase):
    def test_grafana_serves_the_dashboards(self):
        compose = yaml.safe_load((COMPOSE_DIR / "compose.yaml").read_text("utf-8"))
        image = compose["services"]["grafana"]["image"]
        environment = dict(compose["services"]["grafana"]["environment"])
        environment["GF_SECURITY_ADMIN_PASSWORD__FILE"] = "/pw"
        name = "ms-grafana-dashboards-test"
        with __import__("tempfile").TemporaryDirectory() as tmp:
            pw = Path(tmp) / "pw"
            pw.write_text("test-password-0123456789", encoding="utf-8")
            pw.chmod(0o644)
            Path(tmp).chmod(0o755)
            command = [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "--read-only",
                "--user",
                "472:472",
                "--network",
                "none",
                "--tmpfs",
                "/var/lib/grafana:rw,uid=472,gid=472",
                "--tmpfs",
                "/tmp:rw",
                "-v",
                f"{pw}:/pw:ro",
                "-v",
                f"{PROVISIONING_DIR}:/etc/grafana/provisioning:ro",
                "-v",
                f"{DASHBOARDS_DIR}:/etc/grafana/dashboards:ro",
            ]
            for key, value in environment.items():
                command += ["-e", f"{key}={value}"]
            command.append(image)
            subprocess.run(command, check=True, capture_output=True)
            try:
                self.assertEqual(self.served(name), set(EXPECTED_DASHBOARDS))
            finally:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    def served(self, name):
        import time

        for _ in range(60):
            time.sleep(2)
            ip = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                    name,
                ],
                capture_output=True,
                text=True,
            ).stdout.strip()
            probe = subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "wget",
                    "-q",
                    "-O",
                    "-",
                    "--header",
                    "Authorization: Basic "
                    + __import__("base64")
                    .b64encode(b"admin:test-password-0123456789")
                    .decode(),
                    "http://127.0.0.1:3000/api/search?type=dash-db",
                ],
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0 and probe.stdout.startswith("["):
                found = {d["uid"] for d in json.loads(probe.stdout)}
                if len(found) >= len(EXPECTED_DASHBOARDS):
                    return found
        logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        self.fail(
            "Grafana did not load the dashboards:\n"
            + logs.stdout[-3000:]
            + logs.stderr[-3000:]
        )


if __name__ == "__main__":
    unittest.main()
