# deploy/compose/tests/test_prometheus_config.py
"""Scrape jobs and probe modules of the monitoring stack (PP-6).

Parses deploy/compose/observability/{prometheus,blackbox}/*.yml and pins what
each job scrapes and how often; the real `promtool` and blackbox exporter
checks run through observability/check.sh when docker is available.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

COMPOSE_DIR = Path(__file__).resolve().parents[1]
OBSERVABILITY = COMPOSE_DIR / "observability"
COMPOSE_YAML = COMPOSE_DIR / "compose.yaml"

JOB_INTERVALS = {
    "prometheus": None,
    "alertmanager": None,
    "web": "30s",
    "worker": "30s",
    "node": "60s",
    "postgres": "60s",
    "redis": "60s",
    "blackbox-readyz": "30s",
    "blackbox-edge": "60s",
    "blackbox-edge-verified": "60s",
    "blackbox-cantaloupe": "60s",
}
# Compose service names a job may address: the monitoring services and the
# application services Prometheus scrapes or probes on the internal network.
SCRAPE_HOSTS = {
    "localhost",
    "alertmanager",
    "web",
    "worker",
    "node-exporter",
    "postgres-exporter",
    "redis-exporter",
    "blackbox-exporter",
    "redis-broker",
    "redis-cache",
    "cantaloupe",
}


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def static_targets(job):
    return [t for group in job.get("static_configs", []) for t in group["targets"]]


@unittest.skipUnless(yaml, "PyYAML missing")
class PrometheusConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = load(OBSERVABILITY / "prometheus" / "prometheus.yml")
        cls.jobs = {job["job_name"]: job for job in cls.config["scrape_configs"]}

    def interval(self, name):
        job = self.jobs[name]
        return job.get("scrape_interval", self.config["global"]["scrape_interval"])

    def test_jobs_and_intervals(self):
        self.assertEqual(set(self.jobs), set(JOB_INTERVALS))
        for name, expected in JOB_INTERVALS.items():
            with self.subTest(job=name):
                if expected:
                    self.assertEqual(self.interval(name), expected)

    def test_rules_and_alertmanager(self):
        self.assertEqual(self.config["rule_files"], ["/etc/prometheus/rules/*.yml"])
        alertmanagers = self.config["alerting"]["alertmanagers"]
        self.assertEqual(
            [
                t
                for a in alertmanagers
                for s in a["static_configs"]
                for t in s["targets"]
            ],
            ["alertmanager:9093"],
        )

    def test_application_is_scraped_directly_on_the_internal_network(self):
        for name, target in (("web", "web:8000"), ("worker", "worker:9808")):
            job = self.jobs[name]
            with self.subTest(job=name):
                self.assertEqual(static_targets(job), [target])
                self.assertEqual(job.get("metrics_path", "/metrics"), "/metrics")
                self.assertEqual(job.get("scheme", "http"), "http")
                # A scrape through nginx or with a forwarded address gets a 404.
                self.assertNotIn("X-Forwarded-For", str(job.get("http_headers", "")))
                self.assertNotIn("proxy_url", job)

    def test_every_scrape_target_is_a_monitoring_service(self):
        compose = load(COMPOSE_YAML)["services"]
        for name, job in self.jobs.items():
            targets = static_targets(job)
            for entry in job.get("file_sd_configs", []):
                self.assertTrue(entry["files"])
            for target in targets:
                host = re.sub(r"^\w+://", "", target).split(":")[0].split("/")[0]
                with self.subTest(job=name, target=target):
                    self.assertIn(host, SCRAPE_HOSTS)
                    if host != "localhost":
                        self.assertIn(host, compose)

    def test_redis_goes_through_the_exporter_multi_target_endpoint(self):
        job = self.jobs["redis"]
        self.assertEqual(job["metrics_path"], "/scrape")
        self.assertEqual(
            sorted(static_targets(job)), ["redis-broker:6379", "redis-cache:6379"]
        )
        replacements = [r.get("replacement") for r in job["relabel_configs"]]
        self.assertIn("redis-exporter:9121", replacements)
        targets = [
            r
            for r in job["relabel_configs"]
            if r.get("target_label") == "__param_target"
        ]
        self.assertEqual(targets[0]["source_labels"], ["__address__"])

    def probe(self, name, module, target):
        job = self.jobs[name]
        self.assertEqual(job["metrics_path"], "/probe")
        self.assertEqual(job["params"], {"module": [module]})
        replacements = [r.get("replacement") for r in job["relabel_configs"]]
        self.assertIn("blackbox-exporter:9115", replacements)
        sources = [
            r["source_labels"] for r in job["relabel_configs"] if "source_labels" in r
        ]
        self.assertIn(["__address__"], sources)
        self.assertEqual(static_targets(job), [target] if target else [])
        return job

    def test_readyz_probe_is_internal(self):
        self.probe("blackbox-readyz", "http_readyz", "http://web:8000/readyz")

    def test_cantaloupe_probe(self):
        self.probe(
            "blackbox-cantaloupe", "http_cantaloupe", "http://cantaloupe:8182/iiif/3"
        )

    def test_edge_probes_read_the_file_the_entrypoint_writes(self):
        for name, module in (
            ("blackbox-edge", "http_edge"),
            ("blackbox-edge-verified", "http_edge_verified"),
        ):
            job = self.probe(name, module, None)
            files = [f for entry in job["file_sd_configs"] for f in entry["files"]]
            self.assertEqual(files, ["/tmp/edge_targets.json"])
        text = (OBSERVABILITY / "prometheus" / "entrypoint.sh").read_text()
        self.assertIn("edge_targets.json", text)
        prometheus = load(COMPOSE_YAML)["services"]["prometheus"]
        self.assertNotIn("configs", prometheus)

    def test_labels_stay_bounded(self):
        names = {
            r.get("target_label")
            for j in self.jobs.values()
            for r in j.get("relabel_configs", [])
        }
        self.assertNotIn("path", names)
        self.assertNotIn("url", names)
        glob = self.config["global"]
        self.assertIn("label_limit", glob)
        self.assertIn("label_value_length_limit", glob)


@unittest.skipUnless(yaml, "PyYAML missing")
class BlackboxConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = load(OBSERVABILITY / "blackbox" / "blackbox.yml")["modules"]

    def test_modules(self):
        self.assertEqual(
            set(self.modules),
            {"http_readyz", "http_edge", "http_edge_verified", "http_cantaloupe"},
        )
        for name, module in self.modules.items():
            with self.subTest(module=name):
                self.assertEqual(module["prober"], "http")
                self.assertEqual(module["http"]["valid_status_codes"], [200])
                self.assertFalse(module["http"]["follow_redirects"])

    def test_the_verified_edge_module_checks_the_certificate_chain(self):
        http = self.modules["http_edge_verified"]["http"]
        self.assertNotIn("tls_config", http)
        self.assertTrue(http["fail_if_not_ssl"])
        self.assertNotIn("headers", http)

    def test_readyz_sends_the_internal_host(self):
        http = self.modules["http_readyz"]["http"]
        self.assertEqual(http["headers"], {"Host": "web"})
        self.assertNotIn("X-Forwarded-For", http["headers"])

    def test_edge_measures_the_certificate_whatever_the_authority(self):
        http = self.modules["http_edge"]["http"]
        self.assertTrue(http["tls_config"]["insecure_skip_verify"])
        self.assertTrue(http["fail_if_not_ssl"])
        self.assertNotIn("headers", http)


class EdgeEntrypointTests(unittest.TestCase):
    ENTRYPOINT = OBSERVABILITY / "prometheus" / "entrypoint.sh"

    def run_entrypoint(self, host, *args):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "PATH": os.environ["PATH"],
                "PROMETHEUS_TARGETS_DIR": tmp,
                "PROMETHEUS_BIN": "/bin/echo",
            }
            if host is not None:
                env["PUBLIC_HOST"] = host
            result = subprocess.run(
                ["sh", str(self.ENTRYPOINT), *args],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            written = Path(tmp) / "edge_targets.json"
            return result, written.read_text() if written.exists() else None

    def test_it_writes_the_target_and_starts_prometheus_with_the_arguments(self):
        result, written = self.run_entrypoint("example.org", "--config.file=/x.yml")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "--config.file=/x.yml")
        self.assertEqual(
            json.loads(written),
            [
                {
                    "targets": ["https://example.org/healthz"],
                    "labels": {"rehearsal": "false"},
                }
            ],
        )

    def test_a_test_name_is_marked_as_a_rehearsal(self):
        _, written = self.run_entrypoint("manuspectrum.test")
        self.assertEqual(json.loads(written)[0]["labels"], {"rehearsal": "true"})
        _, written = self.run_entrypoint("attest.example.org")
        self.assertEqual(json.loads(written)[0]["labels"], {"rehearsal": "false"})

    def test_a_value_that_is_not_a_host_name_starts_nothing(self):
        for host in (None, "", "a b", 'x"y', "a/b", "a.b/c", "-a.org", "a..org", "a;b"):
            with self.subTest(host=host):
                result, written = self.run_entrypoint(host)
                self.assertEqual(result.returncode, 1)
                self.assertIn("PUBLIC_HOST", result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertIsNone(written)


@unittest.skipUnless(
    yaml and shutil.which("docker") and shutil.which("bash"), "docker or PyYAML missing"
)
class ConfigCheckTests(unittest.TestCase):
    def test_promtool_and_blackbox_accept_the_configuration(self):
        result = subprocess.run(
            ["bash", str(OBSERVABILITY / "check.sh")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SUCCESS", result.stdout + result.stderr)

    def test_check_refuses_a_broken_scrape_config(self):
        result = subprocess.run(
            ["bash", str(OBSERVABILITY / "check.sh")],
            capture_output=True,
            text=True,
            env={**os.environ, "PROMETHEUS_CONFIG": str(Path(__file__))},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
