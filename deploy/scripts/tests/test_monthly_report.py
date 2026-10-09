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
    ("manuspectrum_active_accounts_timestamp_seconds", [vector(1793491200 - 7200)]),
    ("max_over_time(manuspectrum_active_accounts", [vector(14)]),
    ("manuspectrum_active_accounts", [vector(12)]),
    (
        "manuspectrum:consultations:total",
        [
            vector(1234, kind="home"),
            vector(210, kind="about"),
            vector(480, kind="explorer_open"),
            vector(2310, kind="explorer_search"),
            vector(640, kind="explorer_document"),
            vector(1120, kind="explorer_analysis"),
            vector(95, kind="explorer_compare"),
            vector(40, kind="export_csv"),
            vector(6, kind="export_zip"),
            vector(5600, kind="iiif_annotations"),
            vector(75, kind="file_download"),
        ],
    ),
    ("manuspectrum_explorer_export_bytes_sum", [vector(1.2e9)]),
    (
        "manuspectrum_biblissima_created_items_total",
        [
            vector(6, resource_type="Document", outcome="created"),
            vector(42, resource_type="Component", outcome="created"),
            vector(1, resource_type="Document", outcome="failed"),
        ],
    ),
    ('view="transaction_reverse"', [vector(2)]),
    (
        "manuspectrum_auth_logins_total",
        [vector(85, outcome="success"), vector(7, outcome="failure")],
    ),
    ("node_boot_time_seconds", [vector(31)]),
    ("manuspectrum_container_restarts", [vector(2, container="web")]),
    ("manuspectrum_container_oom_kills", [vector(1, container="worker")]),
]

ACTIVITY = {
    "month": "2026-10",
    "start": "2026-10-01T00:00:00+00:00",
    "end": "2026-11-01T00:00:00+00:00",
    "models": {
        "analysis": {
            "total": 10082,
            "created": 12,
            "created_deleted": 2,
            "modified": 30,
            "deleted": 3,
            "tile_saves": 400,
            "publication_changes": 4,
        },
        "document": {
            "total": 55,
            "created": 1,
            "created_deleted": 0,
            "modified": 1,
            "deleted": 0,
            "tile_saves": 20,
            "publication_changes": 1,
        },
        "person": {
            "total": 3,
            "created": 0,
            "created_deleted": 0,
            "modified": 0,
            "deleted": 0,
            "tile_saves": 0,
            "publication_changes": 0,
        },
        "deleted_model": {
            "total": 0,
            "created": 0,
            "created_deleted": 0,
            "modified": 0,
            "deleted": 4,
            "tile_saves": 0,
            "publication_changes": 0,
        },
    },
    "workflows": {
        "create-project-workflow": {
            "started": 5,
            "completed": 3,
            "open": 5,
            "stale": 2,
        },
        "import-biblissima-workflow": {
            "started": 9,
            "completed": 7,
            "open": 12,
            "stale": 10,
        },
        "never-used": {"started": 0, "completed": 0, "open": 0, "stale": 0},
    },
    "workflow_stale_after_days": 30,
    "etl": {
        "import-single-csv": {
            "started": 4,
            "succeeded": 3,
            "failed": 1,
            "unfinished": 0,
        },
        "tile-excel-exporter": {
            "started": 2,
            "succeeded": 2,
            "failed": 0,
            "unfinished": 0,
        },
    },
}

STUB = """import json, sys
data = json.loads(open(sys.argv[1]).read())
month = sys.argv[sys.argv.index("--month") + 1]
if data.get("fail"):
    sys.exit(3)
data["month"] = data.get("month_override") or month
print("noise before the answer")
print(json.dumps(data))
if data.get("trailer"):
    print(json.dumps({"level": "INFO", "message": "closing"}))
    print("not json at all")
"""

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
        at = re.search(r"[?&]time=([0-9.]+)", self.path)
        stamp = float(at.group(1)) if at else None
        self.server.queries.append((expr, stamp))
        floor = self.server.floor
        if "/query_range" in self.path:
            result = ALERT_SERIES
        elif floor is not None and stamp is not None and stamp < floor:
            result = []
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
            self.prom.queries, self.prom.floor = [], None
            threading.Thread(target=self.prom.serve_forever, daemon=True).start()
        self.smtp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), SMTP)
        self.smtp.messages, self.smtp.envelope = [], []
        threading.Thread(target=self.smtp.serve_forever, daemon=True).start()

    def close(self):
        for server in (self.prom, self.smtp):
            if server:
                server.shutdown()
                server.server_close()


def activity_command(directory, data=None):
    """A command that prints `data` (default ACTIVITY) the way activity_summary does."""
    directory = Path(directory)
    (directory / "stub.py").write_text(STUB)
    (directory / "data.json").write_text(json.dumps(ACTIVITY if data is None else data))
    return f"{sys.executable} {directory / 'stub.py'} {directory / 'data.json'}"


_ACTIVITY_DIR = tempfile.TemporaryDirectory()
ACTIVITY_COMMAND = activity_command(_ACTIVITY_DIR.name)


def run(servers, extra=(), **env):
    if "--activity-command" not in extra:
        extra = [*extra, "--activity-command", ACTIVITY_COMMAND]
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
            "Consultations",
            "Contenus",
            "Assistants",
            "Imports et exports en masse",
            "Connexions",
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

    def test_active_accounts_give_the_end_of_month_value_and_the_peak(self):
        result = run(self.servers)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.sent().get_content()
        self.assertIn("fin du mois : 12", text)
        self.assertIn("maximum sur le mois : 14", text)
        self.assertNotIn("non disponible", text)
        self.assertTrue(
            any(
                q.startswith("max(max_over_time(manuspectrum_active_accounts[2678400s]")
                for q, _ in self.servers.prom.queries
            )
        )

    def test_active_accounts_without_data_read_nd(self):
        servers = Servers()
        self.addCleanup(servers.close)
        servers.prom.floor = 2**40
        result = run(servers)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = body_of(servers.smtp.messages[0]).get_content()
        self.assertIn("fin du mois : n/d", text)
        self.assertIn("maximum sur le mois : n/d", text)

    def test_the_account_count_says_when_it_was_measured(self):
        text, _ = self.growth_lines(NOW)
        self.assertIn("fin du mois : 12 (mesuré le 31 octobre 2026)", text)
        self.assertNotIn("périmé", text)

    def test_a_count_older_than_two_days_is_flagged(self):
        entry = (
            "manuspectrum_active_accounts_timestamp_seconds",
            [vector(1793491200 - 5 * 86400)],
        )
        ANSWERS.insert(0, entry)
        self.addCleanup(ANSWERS.remove, entry)
        text, _ = self.growth_lines(NOW)
        self.assertIn("fin du mois : 12 (mesuré le 27 octobre 2026, périmé", text)

    def test_a_month_inside_the_retention_says_peak_over_the_month(self):
        text, _ = self.growth_lines("2027-03-01T08:00:00+00:00")
        self.assertIn("maximum sur le mois : 14", text)

    def report(self, **kwargs):
        result = run(self.servers, **kwargs)
        return result, body_of(self.servers.smtp.messages[-1]).get_content()

    def test_consultations_are_read_by_kind_over_the_month(self):
        result, text = self.report()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("robots compris", text)
        self.assertIn(
            "pages publiques : accueil 1 234, « À propos » 210, ouvertures de l'Explorateur 480",
            text,
        )
        self.assertIn(
            "Explorateur : recherches 2 310, fiches document 640, fiches analyse 1 120, comparaisons 95",
            text,
        )
        self.assertIn("paquets de données 6 (1,2 Go)", text)
        self.assertIn("IIIF : requêtes d'annotations 5 600, manifestes 0", text)
        self.assertIn("fichiers téléchargés 75", text)
        self.assertTrue(
            any(
                q.startswith(
                    "sum by (kind) (increase(manuspectrum:consultations:total[2678400s]"
                )
                for q, _ in self.servers.prom.queries
            )
        )

    def test_contents_list_models_with_activity_and_leave_out_the_others(self):
        _, text = self.report()
        self.assertIn(
            "analysis : 12 créées (dont 2 supprimées dans le mois), 30 modifiées, 3 supprimées ; 10 082 au total",
            text,
        )
        self.assertIn("document : 1 créée, 1 modifiée, 0 supprimée ; 55 au total", text)
        self.assertIn("modèle supprimé : 0 créée, 0 modifiée, 4 supprimées", text)
        self.assertNotIn("person :", text)
        self.assertIn(
            "saisies enregistrées : 420 ; changements d'état de publication : 5", text
        )

    def test_workflows_report_runs_items_cancellations_and_open_runs(self):
        _, text = self.report()
        self.assertIn("Nouveau projet : 5 commencés, dont 3 terminé(s)", text)
        self.assertIn("Import Biblissima : 9 commencés, dont 7 terminé(s)", text)
        self.assertNotIn("never-used", text)
        self.assertIn(
            "Import Biblissima : 48 ressource(s) créée(s) (Component 42, Document 6), 1 échec(s)",
            text,
        )
        self.assertIn("annulés par l'utilisateur : 2", text)
        self.assertIn(
            "inachevés à la date du rapport : 17, dont 12 commencés il y a plus de 30 jours (délai provisoire)",
            text,
        )

    def test_bulk_runs_and_logins(self):
        _, text = self.report()
        self.assertIn("import-single-csv : 4 lancés, 3 réussi(s), 1 en échec", text)
        self.assertIn("tile-excel-exporter : 2 lancés, 2 réussi(s)", text)
        self.assertIn("connexions réussies : 85, échouées : 7", text)

    def test_a_failing_activity_command_marks_its_sections_and_exits_one(self):
        with tempfile.TemporaryDirectory() as directory:
            command = activity_command(directory, {"fail": True})
            result, text = self.report(extra=["--activity-command", command])
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(text.count(UNAVAILABLE), 3)
        self.assertIn("pages publiques : accueil 1 234", text)
        self.assertIn("journal d'activité n'a pas pu être lu", text)

    def test_an_answer_for_another_month_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            command = activity_command(
                directory, {**ACTIVITY, "month_override": "2026-09"}
            )
            result, text = self.report(extra=["--activity-command", command])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(text.count(UNAVAILABLE), 3)
        self.assertNotIn("10 082", text)

    def test_without_an_activity_command_the_database_sections_are_unavailable(self):
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--now", NOW],
            env={
                "PATH": os.environ["PATH"],
                "PROMETHEUS_URL": f"http://127.0.0.1:{self.servers.prom.server_address[1]}",
                "EMAIL_HOST": "127.0.0.1",
                "EMAIL_PORT": str(self.servers.smtp.server_address[1]),
                "ALERT_EMAILS": "one@manuspectrum.test",
                "ALERT_EMAIL_FROM": "noreply@manuspectrum.test",
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(
            body_of(self.servers.smtp.messages[0]).get_content().count(UNAVAILABLE), 3
        )

    def test_log_lines_after_the_answer_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            command = activity_command(directory, {**ACTIVITY, "trailer": True})
            result, text = self.report(extra=["--activity-command", command])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(UNAVAILABLE, text)
        self.assertIn("analysis : 12 créées", text)

    def test_a_reshaped_answer_marks_its_sections_and_still_sends(self):
        without_models = {k: v for k, v in ACTIVITY.items() if k != "models"}
        short_row = {
            **ACTIVITY,
            "models": {"analysis": {"total": 1, "created": 1}},
        }
        for name, data in (("no models", without_models), ("short row", short_row)):
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                command = activity_command(directory, data)
                result, text = self.report(extra=["--activity-command", command])
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(text.count(UNAVAILABLE), 3)
                self.assertIn("journal d'activité n'a pas pu être lu", text)

    def test_consultation_counts_are_rounded_not_truncated(self):
        entry = (
            "manuspectrum:consultations:total",
            [vector(1233.97, kind="home"), vector(2.5, kind="about")],
        )
        ANSWERS.insert(0, entry)
        self.addCleanup(ANSWERS.remove, entry)
        _, text = self.report()
        self.assertIn("accueil 1 234, « À propos » 2", text)

    def test_cancellations_count_the_first_sample_of_a_new_series(self):
        self.report()
        (query,) = [
            q for q, _ in self.servers.prom.queries if 'view="transaction_reverse"' in q
        ]
        self.assertIn(" unless ", query)
        self.assertIn(" offset 2678400s", query)
        self.assertIn("up offset 2678400s == 1", query)

    def test_etl_runs_name_every_terminal_state(self):
        etl = {
            "import-single-csv": {
                "started": 11,
                "succeeded": 3,
                "failed": 1,
                "cancelled": 2,
                "unindexed": 2,
                "unloaded": 1,
                "validated": 1,
                "unfinished": 1,
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            command = activity_command(directory, {**ACTIVITY, "etl": etl})
            _, text = self.report(extra=["--activity-command", command])
        self.assertIn(
            "import-single-csv : 11 lancés, 3 réussi(s), 1 en échec, "
            "2 annulé(s), 2 chargé(s) mais non indexé(s), 1 défait(s) après chargement, "
            "1 validé(s) sans chargement, 1 non terminé(s)",
            text,
        )

    def test_the_history_window_is_one_day_under_the_prometheus_retention(self):
        compose = (SERVICE_DIR.parent / "compose" / "compose.yaml").read_text()
        days = int(re.search(r"retention\.time=(\d+)d", compose).group(1))
        source = SCRIPT.read_text()
        match = re.search(r"^RETENTION_DAYS = (\d+)", source, re.M)
        self.assertEqual(int(match.group(1)), days - 1)

    def test_quiet_month_reads_no_activity(self):
        quiet = {**ACTIVITY, "models": {}, "workflows": {}, "etl": {}}
        with tempfile.TemporaryDirectory() as directory:
            command = activity_command(directory, quiet)
            _, text = self.report(extra=["--activity-command", command])
        # The Biblissima items come from Prometheus, so Assistants still has a line.
        self.assertEqual(text.count("aucune activité"), 2)

    def test_reboots_are_boot_time_moves_above_a_minute_not_any_change(self):
        result = run(self.servers)
        self.assertEqual(result.returncode, 0, result.stderr)
        (query,) = [
            q for q, _ in self.servers.prom.queries if "node_boot_time_seconds" in q
        ]
        self.assertNotIn("changes(", query)
        self.assertRegex(
            query,
            r"max\(node_boot_time_seconds\) - max\(node_boot_time_seconds offset 5m\)\) > 60",
        )
        self.assertIn("redémarrages de la machine : 31 ", self.sent().get_content())

    def growth_lines(self, now, month=None, floor_days=35):
        """Report as sent at `now` by a Prometheus that keeps `floor_days`."""
        from datetime import datetime, timedelta

        clock = datetime.fromisoformat(now)
        self.servers.prom.floor = (clock - timedelta(days=floor_days)).timestamp()
        extra = ["--now", now] + (["--month", month] if month else [])
        result = run(self.servers, extra=extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.sent().get_content(), clock

    def test_growth_of_a_31_day_month_is_read_inside_the_retention(self):
        text, clock = self.growth_lines("2026-11-01T08:00:00+00:00")
        self.assertIn("variation de l'espace libre sur le mois", text)
        self.assertIn("(variation sur le mois : ", text)
        self.assertNotIn("depuis le", text)
        from datetime import datetime, timezone

        start = datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp()
        at_start = [q for q, t in self.servers.prom.queries if t == start]
        self.assertEqual(len(at_start), 3)

    def test_a_late_run_says_since_the_first_readable_day(self):
        text, _ = self.growth_lines("2026-11-05T08:00:00+00:00", month="2026-10")
        self.assertIn("variation de l'espace libre depuis le 2 octobre 2026", text)
        self.assertIn("(variation depuis le 2 octobre 2026 : ", text)

    def test_a_30_day_month_read_on_the_5th_starts_at_the_oldest_readable_day(self):
        text, _ = self.growth_lines("2026-12-05T08:00:00+00:00", month="2026-11")
        self.assertIn("depuis le 1 novembre 2026", text)

    def test_growth_of_february_covers_the_whole_month(self):
        text, _ = self.growth_lines("2027-03-01T08:00:00+00:00")
        self.assertIn("variation de l'espace libre sur le mois", text)
        self.assertIn("(variation sur le mois : ", text)
        self.assertNotIn("depuis le", text)

    def test_growth_of_a_leap_february_still_fits(self):
        text, _ = self.growth_lines("2028-03-01T08:00:00+00:00")
        self.assertIn("variation de l'espace libre sur le mois", text)

    def test_a_month_past_the_retention_has_no_growth_line_not_a_crash(self):
        text, _ = self.growth_lines("2026-11-01T08:00:00+00:00", month="2026-08")
        self.assertNotIn("variation", text)

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
        self.assertEqual(message["X-ManuSpectrum-Category"], "Report")
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
        self.assertIn("X-ManuSpectrum-Category: Report", result.stdout)
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

    def test_the_make_target_runs_the_activity_command_in_the_same_container(self):
        make = MAKEFILE.read_text()
        recipe = make.split("\nmonthly-report:")[1].split("\n\n")[0]
        self.assertIn("--activity-command", recipe)
        self.assertIn("manage.py activity_summary", recipe)
        self.assertIn("PROMETHEUS_MULTIPROC_DIR", recipe)

    def test_makefile_has_both_targets(self):
        make = MAKEFILE.read_text()
        self.assertIsNotNone(re.search(r"(?m)^monthly-report:", make))
        self.assertIsNotNone(re.search(r"(?m)^report-test:", make))


UNAVAILABLE = "données indisponibles"

if __name__ == "__main__":
    unittest.main()
