"""Tests of deploy/scripts/monthly-report.py against a stub Prometheus API and
a stub SMTP server on loopback. Run: python3 -m unittest discover -s
deploy/scripts/tests -p 'test_monthly_report.py'."""

import json
import os
import re
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SCRIPT = Path(
    os.environ.get(
        "MONTHLY_REPORT_PY",
        Path(__file__).resolve().parent.parent / "monthly-report.py",
    )
)
SERVICE_DIR = Path(__file__).resolve().parents[2] / "systemd"
MAKEFILE = Path(__file__).resolve().parents[2] / "Makefile"

NOW = "2026-11-01T08:00:00+00:00"


def vector(value, **labels):
    return {"metric": labels, "value": [0, str(value)]}


ANSWERS = [
    # Order matters: the first fragment found in the query wins.
    ('job="blackbox-edge"', [vector(0.9985)]),
    ('job="blackbox-readyz"', [vector(0.9999)]),
    ('job="blackbox-cantaloupe"', [vector(1)]),
    ("node_filesystem_size_bytes", [vector(100e9)]),
    ("node_filesystem_avail_bytes", [vector(40e9)]),
    ("pg_database_size_bytes", [vector(5.5e9)]),
    (
        "manuspectrum_disk_usage_bytes",
        [
            vector(20e9, target="media"),
            vector(8e9, target="restic"),
            vector(1.2e9, target="dumps"),
            vector(30e6, target="nginx_logs"),
        ],
    ),
    ("backup_last_success", [vector(1793433600)]),
    ("restore_test_last_success", [vector(1793000000)]),
    ("manuspectrum_backup_failed", [vector(1)]),
    ("manuspectrum_restore_test_failed", [vector(0)]),
    ("node_boot_time_seconds", [vector(31)]),
    ("manuspectrum_container_restarts", [vector(2, container="web")]),
    ("manuspectrum_container_oom_kills", [vector(1, container="worker")]),
]

ALERT_SERIES = [
    {
        "metric": {"alertname": "DiskUsageHigh", "severity": "warning"},
        "values": [[1000, "1"], [1300, "1"], [1600, "1"], [90000, "1"]],
    },
    {
        "metric": {"alertname": "BackupFailed", "severity": "critical"},
        "values": [[2000, "1"]],
    },
]


class Prometheus(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        query = re.search(r"query=([^&]*)", self.path)
        from urllib.parse import unquote_plus

        expr = unquote_plus(query.group(1)) if query else ""
        if "/query_range" in self.path:
            result = ALERT_SERIES
        else:
            result = next((r for key, r in ANSWERS if key in expr), [])
        body = json.dumps(
            {"status": "success", "data": {"resultType": "vector", "result": result}}
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())


class SMTP(socketserver.StreamRequestHandler):
    def handle(self):
        write = lambda line: (
            self.wfile.write(line.encode() + b"\r\n"),
            self.wfile.flush(),
        )
        write("220 stub ESMTP")
        message = None
        while True:
            line = self.rfile.readline().decode().rstrip("\r\n")
            if not line:
                return
            verb = line.split(" ")[0].upper()
            if verb == "EHLO" or verb == "HELO":
                write("250 stub")
            elif verb in ("MAIL", "RCPT"):
                self.server.envelope.append(line)
                write("250 ok")
            elif verb == "DATA":
                write("354 go")
                lines = []
                while True:
                    row = self.rfile.readline().decode("utf-8").rstrip("\r\n")
                    if row == ".":
                        break
                    lines.append(row)
                self.server.messages.append("\n".join(lines))
                write("250 queued")
            elif verb == "QUIT":
                write("221 bye")
                return
            else:
                write("250 ok")


class Servers:
    def __init__(self, prometheus=True):
        self.prom = None
        if prometheus:
            self.prom = HTTPServer(("127.0.0.1", 0), Prometheus)
            threading.Thread(target=self.prom.serve_forever, daemon=True).start()
        self.smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SMTP)
        self.smtp.messages, self.smtp.envelope = [], []
        threading.Thread(target=self.smtp.serve_forever, daemon=True).start()

    def close(self):
        for server in (self.prom, self.smtp):
            if server:
                server.shutdown()
                server.server_close()


def run(servers, extra=(), **env):
    base = {
        "PATH": os.environ["PATH"],
        "PROMETHEUS_URL": (
            f"http://127.0.0.1:{servers.prom.server_address[1]}"
            if servers.prom
            else "http://127.0.0.1:9"
        ),
        "EMAIL_HOST": "127.0.0.1",
        "EMAIL_PORT": str(servers.smtp.server_address[1]),
        "EMAIL_USE_TLS": "false",
        "ALERT_EMAILS": "one@manuspectrum.test, two@manuspectrum.test",
        "ALERT_EMAIL_FROM": "noreply@manuspectrum.test",
    }
    base.update(env)
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--now", NOW, *extra],
        env=base,
        capture_output=True,
        text=True,
        timeout=60,
    )


def body_of(raw):
    from email import message_from_string, policy

    return message_from_string(raw, policy=policy.default)


class MonthlyReport(unittest.TestCase):
    def setUp(self):
        self.servers = Servers()
        self.addCleanup(self.servers.close)

    def sent(self):
        self.assertEqual(len(self.servers.smtp.messages), 1)
        return body_of(self.servers.smtp.messages[0])

    def test_every_section_is_present_in_french(self):
        result = run(self.servers)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.sent().get_content()
        for heading in (
            "Disponibilité",
            "Disques",
            "Tailles",
            "Sauvegardes et tests de restauration",
            "Redémarrages et manques de mémoire",
            "Alertes du mois",
            "Comptes actifs",
        ):
            self.assertIn(heading, text)
        self.assertIn("octobre 2026", text)
        self.assertIn("99,85 %", text)
        self.assertIn("60,0 Go utilisés sur 100,0 Go", text)
        self.assertIn("base de données : 5,5 Go", text)
        self.assertIn("fichiers déposés (media) : 20,0 Go", text)
        self.assertIn("un échec observé", text)
        self.assertIn("aucun échec", text)
        self.assertIn("web 2", text)
        self.assertIn("worker 1", text)
        self.assertNotIn(UNAVAILABLE, text)

    def test_alert_episodes_are_counted_by_alertname(self):
        run(self.servers)
        text = self.sent().get_content()
        self.assertIn("- DiskUsageHigh (warning) : 2", text)
        self.assertIn("- BackupFailed (critical) : 1", text)

    def test_headers_subject_sender_and_recipients(self):
        run(self.servers)
        message = self.sent()
        self.assertEqual(
            message["Subject"], "[ManuSpectrum][Report] Rapport mensuel 2026-10"
        )
        self.assertEqual(message["X-ManuSpectrum-Category"], "report")
        self.assertEqual(message["From"], "noreply@manuspectrum.test")
        self.assertIn(
            "from:<noreply@manuspectrum.test>", self.servers.smtp.envelope[0].lower()
        )
        rcpt = [e for e in self.servers.smtp.envelope if e.upper().startswith("RCPT")]
        self.assertEqual(len(rcpt), 2)

    def test_no_address_other_than_sender_and_recipients(self):
        run(self.servers)
        raw = re.sub(r"(?m)^Message-ID:.*$", "", self.servers.smtp.messages[0])
        found = set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", raw))
        self.assertEqual(
            found,
            {
                "one@manuspectrum.test",
                "two@manuspectrum.test",
                "noreply@manuspectrum.test",
            },
        )

    def test_the_previous_month_is_reported_from_january(self):
        result = run(self.servers, extra=["--now", "2027-01-01T08:00:00+00:00"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.sent()["Subject"], "[ManuSpectrum][Report] Rapport mensuel 2026-12"
        )

    def test_prometheus_down_still_sends_and_exits_non_zero(self):
        self.servers.close()
        servers = Servers(prometheus=False)
        self.addCleanup(servers.close)
        result = run(servers)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(len(servers.smtp.messages), 1)
        text = body_of(servers.smtp.messages[0]).get_content()
        self.assertGreaterEqual(text.count(UNAVAILABLE), 6)
        self.assertIn("Disponibilité", text)

    def test_smtp_failure_exits_two(self):
        result = run(self.servers, EMAIL_PORT="9")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not sent", result.stderr)

    def test_bad_configuration_sends_nothing(self):
        for key, value in (
            ("ALERT_EMAILS", ""),
            ("ALERT_EMAILS", "a@b.test,nobody"),
            ("ALERT_EMAIL_FROM", ""),
        ):
            with self.subTest(key=key, value=value):
                result = run(self.servers, **{key: value})
                self.assertEqual(result.returncode, 2)
        self.assertEqual(self.servers.smtp.messages, [])

    def test_dry_run_prints_and_does_not_send(self):
        result = run(self.servers, extra=["--dry-run"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("X-ManuSpectrum-Category: report", result.stdout)
        self.assertEqual(self.servers.smtp.messages, [])

    def test_login_reads_the_password_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".pw") as pw:
            pw.write("s3cret")
            pw.flush()
            result = run(
                self.servers, EMAIL_HOST_USER="relay", EMAIL_HOST_PASSWORD_FILE=pw.name
            )
        # The stub offers no AUTH: the login is attempted and refused, nothing is sent.
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("s3cret", result.stderr + result.stdout)


class Units(unittest.TestCase):
    def test_timer_fires_on_the_first_at_eight_and_persists(self):
        timer = (SERVICE_DIR / "manuspectrum-monthly-report.timer.in").read_text()
        self.assertIsNotNone(re.search(r"(?m)^OnCalendar=\*-\*-01 08:00$", timer))
        self.assertIsNotNone(re.search(r"(?m)^Persistent=true$", timer))

    def test_service_runs_the_make_target_as_a_oneshot(self):
        service = (SERVICE_DIR / "manuspectrum-monthly-report.service.in").read_text()
        self.assertIn("Type=oneshot", service)
        self.assertIn("ExecStart=/usr/bin/make -C @DEPLOY_DIR@ monthly-report", service)

    def test_makefile_has_both_targets(self):
        make = MAKEFILE.read_text()
        self.assertIsNotNone(re.search(r"(?m)^monthly-report:", make))
        self.assertIsNotNone(re.search(r"(?m)^report-test:", make))


UNAVAILABLE = "données indisponibles"

if __name__ == "__main__":
    unittest.main()
