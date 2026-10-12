#!/usr/bin/env python3
"""Monthly operations report of ManuSpectrum, sent by e-mail in French.

Run once a month by `make -C deploy monthly-report` (systemd timer, the 1st at
08:00), and on demand by `make -C deploy report-test`. It covers the calendar
month that just ended. Python standard library only: the Make target runs it in
a throwaway container of the application image on the Compose network.

Most figures come from the Prometheus HTTP API (PROMETHEUS_URL, default
http://prometheus:9090); the content, workflow and bulk import sections come
from the database through `--activity-command`, a management command run in the
same container that prints the month's aggregates as one line of JSON
(`manage.py activity_summary --month YYYY-MM`). Nothing personal is read: only
counts (the active-accounts section reads one number,
`manuspectrum_active_accounts`), with one exception: the inactive-accounts section
names the active accounts with no sign-in for 12 months, or none 3 months after
their creation, so that the administrators can decide by hand. A section whose source fails reads "données
indisponibles"; the report is sent anyway and the exit status is then 1.
Prometheus keeps 35 days: a figure older than that reads "n/d". The growth
lines (free space, database) compare the end of the month with its start, or
with 34 days before the run when the month began earlier than that, and then
say "depuis le <date>".

Environment: EMAIL_HOST, EMAIL_PORT, EMAIL_USE_TLS (true = STARTTLS),
EMAIL_HOST_USER and EMAIL_HOST_PASSWORD_FILE (login only when the user is set),
ALERT_EMAILS (comma-separated recipients), ALERT_EMAIL_FROM.

Usage: monthly-report.py [--dry-run] [--month YYYY-MM] [--now ISO-8601]
                         [--activity-command COMMAND]
  --dry-run           print the message instead of sending it
  --month             report this month instead of the previous one
  --now               the clock for the default month (tests)
  --activity-command  command that takes `--month YYYY-MM` and prints the
                      activity JSON; without it those sections are unavailable

Exit: 0 sent and complete, 1 sent with a section unavailable, 2 not sent
(configuration or SMTP failure).
"""

import argparse
import calendar
import json
import os
import re
import shlex
import smtplib
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

UNAVAILABLE = "données indisponibles"
NO_DATA = "n/d"
ADDRESS = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
STEP = 300
RETENTION_DAYS = 34  # Prometheus keeps 35; one day of margin for block deletion
MONTHS_FR = (
    "janvier février mars avril mai juin juillet août "
    "septembre octobre novembre décembre"
).split()


MODEL_FIELDS = (
    "created",
    "created_deleted",
    "modified",
    "deleted",
    "cleaned",
    "tile_saves",
    "publication_changes",
)
WORKFLOW_FIELDS = ("started", "completed", "open", "stale")
ETL_FIELDS = (
    "succeeded",
    "failed",
    "cancelled",
    "unfinished",
    "unloaded",
    "unindexed",
    "validated",
)


class Unavailable(Exception):
    """Prometheus did not answer, or answered something unreadable."""


class Activity:
    """The month's aggregates printed by the activity command, read once."""

    def __init__(self, command, label, timeout=120):
        self.command = command
        self.label = label
        self.timeout = timeout
        self.failed = False
        self._data = None

    def parse(self, output):
        """The answer of the command: the last JSON object of its output naming a month.

        Log lines (JSON in the image) may precede or follow it. A reshaped answer
        raises ValueError.
        """
        for line in reversed(output.splitlines()):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict) and "month" in data:
                break
        else:
            raise ValueError("no activity answer in the output")
        if data["month"] != self.label:
            raise ValueError("answer for another month")
        try:
            for key in ("models", "workflows", "etl"):
                if not isinstance(data[key], dict):
                    raise TypeError(key)
            int(data["workflow_stale_after_days"])
            int(data["accounts_anonymised"])
            for rows in data["inactive_accounts"].values():
                for username, last_login, joined in rows:
                    str(username), str(joined)
                    if last_login is not None:
                        str(last_login)
            for row in data["models"].values():
                for key in ("total", *MODEL_FIELDS):
                    int(row[key])
            for row in data["workflows"].values():
                for key in WORKFLOW_FIELDS:
                    int(row[key])
            for row in data["etl"].values():
                for key in ETL_FIELDS:
                    int(row.get(key, 0))
                int(row["started"])
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise ValueError(f"activity answer reshaped: {exc!r}") from exc
        return data

    def get(self):
        if self._data is not None:
            return self._data
        try:
            if not self.command:
                raise ValueError("no activity command")
            done = subprocess.run(
                shlex.split(self.command) + ["--month", self.label],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if done.returncode != 0:
                raise ValueError(f"exit status {done.returncode}")
            data = self.parse(done.stdout)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            self.failed = True
            raise Unavailable(str(exc)) from exc
        self._data = data
        return data


class Prometheus:
    def __init__(self, base, timeout=15):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.failed = False

    def _get(self, path, params):
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                body = json.load(response)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            self.failed = True
            raise Unavailable(str(exc)) from exc
        if body.get("status") != "success":
            self.failed = True
            raise Unavailable(body.get("error", "error status"))
        return body["data"]["result"]

    def query(self, expr, at):
        """Instant vector: [(labels, float)]; NaN samples are dropped."""
        out = []
        for item in self._get("/api/v1/query", {"query": expr, "time": at}):
            value = float(item["value"][1])
            if value == value:
                out.append((item["metric"], value))
        return out

    def scalar(self, expr, at):
        rows = self.query(expr, at)
        return rows[0][1] if rows else None

    def query_range(self, expr, start, end):
        return self._get(
            "/api/v1/query_range",
            {"query": expr, "start": start, "end": end, "step": STEP},
        )


def french_number(value, digits=1):
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text


def size(value):
    if value is None:
        return NO_DATA
    sign = "-" if value < 0 else ""
    value = abs(value)
    for unit, factor in (("To", 1e12), ("Go", 1e9), ("Mo", 1e6), ("Ko", 1e3)):
        if value >= factor:
            return f"{sign}{french_number(value / factor)} {unit}"
    return f"{sign}{int(value)} o"


def percent(value, digits=2):
    return NO_DATA if value is None else f"{french_number(value * 100, digits)} %"


def date_fr(timestamp):
    if not timestamp:
        return "aucune sauvegarde enregistrée"
    day = datetime.fromtimestamp(timestamp, timezone.utc)
    return f"{day.day} {MONTHS_FR[day.month - 1]} {day.year}"


def month_bounds(label):
    year, month = (int(part) for part in label.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=calendar.monthrange(year, month)[1])
    return start, end


def previous_month(now):
    first = now.astimezone(timezone.utc).replace(day=1)
    last = first - timedelta(days=1)
    return f"{last.year:04d}-{last.month:02d}"


def section(prom, title, build):
    try:
        lines = build()
    except Unavailable:
        lines = [UNAVAILABLE]
    return [title, "-" * len(title)] + [f"  {line}" for line in lines] + [""]


def availability(prom, start, end):
    window = f"{int((end - start).total_seconds())}s"
    lines = []
    for label, job in (
        ("site public", "blackbox-edge"),
        ("application (readyz)", "blackbox-readyz"),
        ("serveur d'images", "blackbox-cantaloupe"),
    ):
        ratio = prom.scalar(
            f'avg(avg_over_time(probe_success{{job="{job}"}}[{window}]))',
            end.timestamp(),
        )
        down = (
            None if ratio is None else (1 - ratio) * (end - start).total_seconds() / 60
        )
        suffix = (
            ""
            if down is None
            else f" (environ {int(round(down))} min d'indisponibilité)"
        )
        lines.append(f"{label} : {percent(ratio)}{suffix}")
    return lines


def growth_since(start, now):
    """First instant a growth figure can be read: the month start, or the
    oldest instant Prometheus still holds."""
    return max(start, now - timedelta(days=RETENTION_DAYS))


def growth_period(start, since):
    if since <= start:
        return "sur le mois"
    return f"depuis le {date_fr(since.timestamp())}"


def disks(prom, start, end, since):
    lines = []
    for mount in ("/", "/data"):
        sel = f'{{mountpoint="{mount}",fstype!~"tmpfs|overlay|squashfs"}}'
        total = prom.scalar(f"max(node_filesystem_size_bytes{sel})", end.timestamp())
        free = prom.scalar(f"max(node_filesystem_avail_bytes{sel})", end.timestamp())
        before = (
            prom.scalar(f"max(node_filesystem_avail_bytes{sel})", since.timestamp())
            if since < end
            else None
        )
        if total is None or free is None:
            lines.append(f"{mount} : {NO_DATA}")
            continue
        growth = (
            ""
            if before is None
            else f", variation de l'espace libre {growth_period(start, since)} : {size(free - before)}"
        )
        lines.append(
            f"{mount} : {size(total - free)} utilisés sur {size(total)} "
            f"({percent((total - free) / total, 1)}), {size(free)} libres{growth}"
        )
    return lines


def sizes(prom, start, end, since):
    at = end.timestamp()
    db = prom.scalar(
        'sum(pg_database_size_bytes{datname!~"template0|template1|postgres"})', at
    )
    db_before = (
        prom.scalar(
            'sum(pg_database_size_bytes{datname!~"template0|template1|postgres"})',
            since.timestamp(),
        )
        if since < end
        else None
    )
    growth = (
        ""
        if db is None or db_before is None
        else f" (variation {growth_period(start, since)} : {size(db - db_before)})"
    )
    lines = [f"base de données : {size(db)}{growth}"]
    areas = dict(
        (labels.get("target"), value)
        for labels, value in prom.query("manuspectrum_disk_usage_bytes", at)
    )
    for label, target in (
        ("fichiers déposés (media)", "media"),
        ("dépôt de sauvegardes (restic)", "restic"),
        ("sauvegardes de la base (dumps)", "dumps"),
        ("journaux nginx", "nginx_logs"),
    ):
        lines.append(f"{label} : {size(areas.get(target))}")
    return lines


def backups(prom, start, end):
    at = end.timestamp()
    window = f"{int((end - start).total_seconds())}s"
    lines = []
    for label, last, failed in (
        (
            "dernière sauvegarde réussie",
            "manuspectrum_backup_last_success_timestamp_seconds",
            "manuspectrum_backup_failed",
        ),
        (
            "dernier test de restauration réussi",
            "manuspectrum_restore_test_last_success_timestamp_seconds",
            "manuspectrum_restore_test_failed",
        ),
    ):
        stamp = prom.scalar(f"max({last})", at)
        flag = prom.scalar(f"max(max_over_time({failed}[{window}]))", at)
        if flag is None:
            verdict = NO_DATA
        else:
            verdict = "un échec observé" if flag >= 1 else "aucun échec"
        lines.append(f"{label} : {date_fr(stamp)} ; échecs sur le mois : {verdict}")
    return lines


def restarts(prom, start, end):
    at = end.timestamp()
    window = f"{int((end - start).total_seconds())}s"
    lines = []
    # A boot time that moves by more than a minute is a reboot; the smaller
    # moves of an NTP step are not (same rule as the HostRebooted alert). The
    # `or` keeps "no data" distinct from "no reboot".
    reboots = prom.scalar(
        "count_over_time("
        "((max(node_boot_time_seconds) - max(node_boot_time_seconds offset 5m)) > 60)"
        f"[{window}:5m]) or (max(node_boot_time_seconds) * 0)",
        at,
    )
    lines.append(
        "redémarrages de la machine : "
        + (
            NO_DATA
            if reboots is None
            else str(int(reboots)) + " (un redémarrage planifié à 04h50 est normal)"
        )
    )
    for label, expr in (
        (
            "redémarrages de conteneurs",
            f"sum by (container) (increase(manuspectrum_container_restarts[{window}]))",
        ),
        (
            "arrêts par manque de mémoire (OOM)",
            f"sum by (container) (increase(manuspectrum_container_oom_kills[{window}]))",
        ),
    ):
        rows = [
            (m.get("container", "?"), round(v))
            for m, v in prom.query(expr, at)
            if round(v) > 0
        ]
        if rows:
            detail = ", ".join(f"{name} {count}" for name, count in sorted(rows))
            lines.append(f"{label} : {sum(c for _, c in rows)} ({detail})")
        else:
            lines.append(f"{label} : aucun")
    return lines


def episodes(series):
    """Number of distinct firing periods in one series of (timestamp, value)."""
    stamps = sorted(float(t) for t, _ in series)
    count = 0
    previous = None
    for stamp in stamps:
        if previous is None or stamp - previous > 2 * STEP:
            count += 1
        previous = stamp
    return count


def alerts(prom, start, end):
    result = prom.query_range(
        'ALERTS{alertstate="firing",alertname!~"Watchdog|AlertTest"}',
        start.timestamp(),
        end.timestamp(),
    )
    counts = {}
    for item in result:
        key = (
            item["metric"].get("alertname", "?"),
            item["metric"].get("severity", "?"),
        )
        counts[key] = counts.get(key, 0) + episodes(item["values"])
    if not counts:
        return ["aucune alerte déclenchée"]
    total = sum(counts.values())
    lines = [f"{total} alerte(s) déclenchée(s) :"]
    for (name, severity), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {name} ({severity}) : {n}")
    return lines


ACCOUNTS_STALE_DAYS = 2


def accounts(prom, start, end, since):
    at = end.timestamp()
    window = f"{int((end - start).total_seconds())}s"
    last = prom.scalar("max(manuspectrum_active_accounts)", at)
    peak = prom.scalar(
        f"max(max_over_time(manuspectrum_active_accounts[{window}]))", at
    )
    measured = prom.scalar("max(manuspectrum_active_accounts_timestamp_seconds)", at)

    def count(value):
        return NO_DATA if value is None else str(int(round(value)))

    age = ""
    if last is not None and measured is not None:
        age = f" (mesuré le {date_fr(measured)}"
        if at - measured > ACCOUNTS_STALE_DAYS * 86400:
            age += (
                f", périmé : plus de {ACCOUNTS_STALE_DAYS} jours avant la fin du mois"
            )
        age += ")"
    return [
        f"comptes ayant ouvert une session dans les 30 derniers jours, fin du mois : {count(last)}{age}",
        f"maximum {growth_period(start, since)} : {count(peak)}",
        "(nombre agrégé, aucun compte n'est lu ni nommé)",
    ]


def count(value):
    return str(int(round(value)))


def plural(n, one, many=None):
    return f"{n} {one if n < 2 else many or one + 's'}"


def number(n):
    return f"{int(round(n)):,}".replace(",", " ")


def by_label(rows, name):
    return {labels.get(name, "?"): value for labels, value in rows}


CONSULTATION_LINES = (
    (
        "pages publiques",
        (
            ("home", "accueil"),
            ("about", "« À propos »"),
            ("explorer_open", "ouvertures de l'Explorateur"),
        ),
    ),
    (
        "Explorateur",
        (
            ("explorer_search", "recherches"),
            ("explorer_document", "fiches document"),
            ("explorer_analysis", "fiches analyse"),
            ("explorer_compare", "comparaisons"),
        ),
    ),
    (
        "exports",
        (
            ("export_csv", "séries CSV"),
            ("export_zip", "paquets de données"),
            ("export_manifest", "manifestes IIIF"),
            ("share", "partages"),
        ),
    ),
    (
        "back-office",
        (
            ("resource_report", "fiches"),
            ("resource_summary", "aperçus"),
            ("search", "recherches"),
        ),
    ),
    (
        "IIIF",
        (
            ("iiif_annotations", "requêtes d'annotations"),
            ("iiif_manifest", "manifestes"),
        ),
    ),
    ("fichiers", (("file_download", "fichiers téléchargés"),)),
)


def consultations(prom, start, end):
    at = end.timestamp()
    window = f"{int((end - start).total_seconds())}s"
    kinds = by_label(
        prom.query(
            f"sum by (kind) (increase(manuspectrum:consultations:total[{window}]))", at
        ),
        "kind",
    )
    if not kinds:
        return [NO_DATA]
    zip_bytes = prom.scalar(
        f"sum(increase(manuspectrum_explorer_export_bytes_sum[{window}]))", at
    )
    lines = ["(requêtes servies, robots compris ; une réponse 304 compte)"]
    for title, entries in CONSULTATION_LINES:
        parts = []
        for kind, label in entries:
            text = f"{label} {number(kinds.get(kind, 0))}"
            if kind == "export_zip" and zip_bytes:
                text += f" ({size(zip_bytes)})"
            parts.append(text)
        lines.append(f"{title} : " + ", ".join(parts))
    return lines


WORKFLOW_NAMES = {
    "create-project-workflow": "Nouveau projet",
    "import-biblissima-workflow": "Import Biblissima",
}


def model_name(slug):
    return "modèle supprimé" if slug == "deleted_model" else slug


def contents(activity):
    models = activity.get()["models"]
    lines = []
    saves = changes = 0
    for slug, row in sorted(models.items()):
        saves += row["tile_saves"]
        changes += row["publication_changes"]
        if not (row["created"] or row["modified"] or row["deleted"] or row["cleaned"]):
            continue
        created = plural(row["created"], "créée")
        if row["created_deleted"]:
            created += (
                f" (dont {plural(row['created_deleted'], 'supprimée')} dans le mois)"
            )
        lines.append(
            f"{model_name(slug)} : {created}, "
            f"{plural(row['modified'], 'modifiée')}, "
            f"{plural(row['deleted'], 'supprimée')}"
            + (
                f", {plural(row['cleaned'], 'nettoyée')} (assistant abandonné)"
                if row["cleaned"]
                else ""
            )
            + f" ; {number(row['total'])} au total"
        )
    if not lines:
        return ["aucune activité"]
    lines.append(
        f"saisies enregistrées : {number(saves)} ; "
        f"changements d'état de publication : {number(changes)}"
    )
    lines.append("(journal des éditions Arches ; totaux à la date du rapport)")
    return lines


def workflows(prom, activity, start, end):
    data = activity.get()
    at = end.timestamp()
    window = f"{int((end - start).total_seconds())}s"
    lines = []
    open_total = stale_total = 0
    for name, row in sorted(data["workflows"].items()):
        open_total += row["open"]
        stale_total += row["stale"]
        if row["started"]:
            lines.append(
                f"{WORKFLOW_NAMES.get(name, name)} : "
                f"{plural(row['started'], 'commencé')}, dont {row['completed']} terminé(s)"
            )
    created = prom.query(
        "sum by (resource_type, outcome) "
        f"(increase(manuspectrum_biblissima_created_items_total[{window}]))",
        at,
    )
    made = {
        labels.get("resource_type", "?"): value
        for labels, value in created
        if labels.get("outcome") == "created" and round(value) > 0
    }
    failed = sum(v for labels, v in created if labels.get("outcome") == "failed")
    if made or failed:
        detail = ", ".join(f"{kind} {count(v)}" for kind, v in sorted(made.items()))
        lines.append(
            f"Import Biblissima : {count(sum(made.values()))} ressource(s) créée(s)"
            + (f" ({detail})" if detail else "")
            + f", {count(failed)} échec(s)"
        )
    series = (
        "django_http_responses_total_by_status_view_method_total"
        '{view="transaction_reverse",method="POST",status="200"}'
    )
    increase = f"increase({series}[{window}]) and {series} offset {window}"
    fresh = (
        f"({series} unless {series} offset {window}) "
        f"and on (job, instance) (up offset {window} == 1)"
    )
    cancelled = prom.scalar(
        f"sum(({increase}) or ({fresh}))",
        at,
    )
    if cancelled is not None and round(cancelled) > 0:
        lines.append(f"annulés par l'utilisateur : {count(cancelled)}")
    if open_total:
        days = data["workflow_stale_after_days"]
        lines.append(
            f"inachevés à la date du rapport : {open_total}, dont {stale_total} "
            f"commencés il y a plus de {days} jours (délai du nettoyage)"
        )
    return lines or ["aucune activité"]


WORKFLOW_CLEANUP_OUTCOMES = (
    ("cleaned", "nettoyé(s)"),
    ("kept_resources", "nettoyé(s) avec des ressources conservées"),
    ("failed", "en échec"),
)


def workflow_cleanups(prom, start, end):
    window = f"{int((end - start).total_seconds())}s"
    rows = by_label(
        prom.query(
            "sum by (outcome) "
            f"(increase(manuspectrum_workflow_cleanups_total[{window}]))",
            end.timestamp(),
        ),
        "outcome",
    )
    kept = by_label(
        prom.query(
            "sum by (outcome) "
            f"(increase(manuspectrum_workflow_cleanup_resources_total[{window}]))",
            end.timestamp(),
        ),
        "outcome",
    )
    parts = [
        f"{count(rows[key])} {label}"
        for key, label in WORKFLOW_CLEANUP_OUTCOMES
        if round(rows.get(key, 0)) > 0
    ]
    if not parts:
        return ["aucun assistant abandonné n'a été nettoyé"]
    lines = ["assistants abandonnés : " + ", ".join(parts)]
    deleted, conserved = round(kept.get("deleted", 0)), round(kept.get("kept", 0))
    if deleted or conserved:
        lines.append(
            f"ressources créées par ces assistants : {deleted} supprimée(s), "
            f"{conserved} conservée(s)"
        )
    return lines


EMBARGO_LIFT_OUTCOMES = (
    ("lifted", "levé(s)"),
    ("incomplete", "levé(s) en partie"),
    ("skipped_extended", "reporté(s) (prolongés)"),
    ("failed", "en échec"),
)


def embargoes(prom, start, end):
    at = end.timestamp()
    window = f"{int((end - start).total_seconds())}s"
    lifts = by_label(
        prom.query(
            f"sum by (outcome) (increase(manuspectrum_embargo_lifts_total[{window}]))",
            at,
        ),
        "outcome",
    )
    states = by_label(
        prom.query("sum by (state) (manuspectrum_embargoes)", at), "state"
    )
    lines = []
    parts = [
        f"{count(lifts[key])} {label}"
        for key, label in EMBARGO_LIFT_OUTCOMES
        if round(lifts.get(key, 0)) > 0
    ]
    lines.append("restrictions : " + (", ".join(parts) if parts else "aucune levée"))
    if not states:
        lines.append(f"état à la fin du mois : {NO_DATA}")
        return lines
    lines.append(
        "état à la fin du mois : "
        f"{count(states.get('active', 0))} active(s), "
        f"{count(states.get('due_soon', 0))} proche(s) de leur fin, "
        f"{count(states.get('overdue', 0))} échue(s) non levée(s), "
        f"{count(states.get('undated', 0))} sans date de fin"
    )
    lines.append(
        "(une restriction sans date de fin n'est jamais levée automatiquement ; "
        "une restriction échue demande une vérification : "
        "deploy/runbooks/application.md)"
    )
    return lines


def lockouts(prom, start, end):
    window = f"{int((end - start).total_seconds())}s"
    total = prom.scalar(
        f"sum(increase(manuspectrum_auth_lockouts_total[{window}]))", end.timestamp()
    )
    if total is None:
        return [NO_DATA]
    return [f"comptes verrouillés après des échecs de connexion : {count(total)}"]


def account_mails(prom, start, end):
    window = f"{int((end - start).total_seconds())}s"
    rows = prom.query(
        "sum by (kind, outcome) "
        f"(increase(manuspectrum_account_mails_total[{window}]))",
        end.timestamp(),
    )
    sent = sum(v for labels, v in rows if labels.get("outcome") == "sent")
    failed = {
        labels.get("kind", "?"): v
        for labels, v in rows
        if labels.get("outcome") == "failed" and round(v) > 0
    }
    if not rows:
        return [NO_DATA]
    lines = [f"courriels de compte envoyés : {count(sent)}"]
    if failed:
        detail = ", ".join(f"{kind} {count(v)}" for kind, v in sorted(failed.items()))
        lines.append(
            f"courriels de compte en échec : {count(sum(failed.values()))} ({detail})"
        )
    else:
        lines.append("courriels de compte en échec : aucun")
    return lines


def french_date(iso):
    year, month, day = (int(part) for part in iso.split("-"))
    return f"{day} {MONTHS_FR[month - 1]} {year}"


def inactive_accounts(activity):
    data = activity.get()["inactive_accounts"]
    lines = []
    for key, title in (
        ("dormant", "sans connexion depuis 12 mois ou plus"),
        (
            "never",
            "jamais connectés, créés il y a plus de 3 mois (invitation non activée comprise)",
        ),
    ):
        rows = data[key]
        lines.append(f"{title} : {len(rows)}")
        for username, last_login, joined in rows:
            last = french_date(last_login) if last_login else "jamais"
            lines.append(
                f"  {username} : dernière connexion {last}, créé le {french_date(joined)}"
            )
    anonymised = int(activity.get()["accounts_anonymised"])
    lines.append(
        f"comptes anonymisés dans le mois (24 mois sans connexion) : {anonymised}"
    )
    lines.append(
        "(la désactivation à 12 mois se décide à la main ; à 24 mois le compte est "
        "anonymisé automatiquement, jamais supprimé)"
    )
    return lines


def bulk_runs(activity):
    lines = []
    for slug, row in sorted(activity.get()["etl"].items()):
        text = f"{slug} : {plural(row['started'], 'lancé')}"
        text += f", {row['succeeded']} réussi(s)"
        if row["failed"]:
            text += f", {row['failed']} en échec"
        for key, label in (
            ("cancelled", "annulé(s)"),
            ("unindexed", "chargé(s) mais non indexé(s)"),
            ("unloaded", "défait(s) après chargement"),
            ("validated", "validé(s) sans chargement"),
            ("unfinished", "non terminé(s)"),
        ):
            if row.get(key):
                text += f", {row[key]} {label}"
        lines.append(text)
    return lines or ["aucune activité"]


def logins(prom, start, end):
    window = f"{int((end - start).total_seconds())}s"
    rows = by_label(
        prom.query(
            f"sum by (outcome) (increase(manuspectrum_auth_logins_total[{window}]))",
            end.timestamp(),
        ),
        "outcome",
    )
    if not rows:
        return [NO_DATA]
    return [
        f"connexions réussies : {count(rows.get('success', 0))}, "
        f"échouées : {count(rows.get('failure', 0))}"
    ]


def build_body(prom, activity, label, start, end, now):
    last_day = end - timedelta(days=1)
    head = [
        f"Rapport mensuel ManuSpectrum, {MONTHS_FR[start.month - 1]} {start.year}",
        f"Période : du 1er au {last_day.day} {MONTHS_FR[last_day.month - 1]} {last_day.year} (UTC)",
        "Source : Prometheus (conservation de 35 jours : un chiffre plus ancien s'affiche n/d) et base de données (agrégats uniquement)",
        "",
    ]
    blocks = []
    since = growth_since(start, now)
    for title, build in (
        ("Disponibilité", availability),
        ("Disques", lambda p, a, b: disks(p, a, b, since)),
        ("Tailles", lambda p, a, b: sizes(p, a, b, since)),
        ("Sauvegardes et tests de restauration", backups),
        ("Redémarrages et manques de mémoire", restarts),
        ("Alertes du mois", alerts),
        ("Consultations", consultations),
        ("Contenus", lambda p, a, b: contents(activity)),
        ("Assistants", lambda p, a, b: workflows(p, activity, a, b)),
        ("Assistants abandonnés nettoyés", workflow_cleanups),
        ("Restrictions (embargos)", embargoes),
        ("Imports et exports en masse", lambda p, a, b: bulk_runs(activity)),
        ("Connexions", logins),
        ("Verrouillages de comptes", lockouts),
        ("Courriels de compte", account_mails),
        ("Comptes actifs", lambda p, a, b: accounts(p, a, b, since)),
        ("Comptes inactifs", lambda p, a, b: inactive_accounts(activity)),
    ):
        blocks += section(prom, title, lambda b=build: b(prom, start, end))
    if prom.failed:
        blocks.append(
            "Prometheus n'a pas répondu à au moins une requête : voir deploy/runbooks/monitoring.md."
        )
    if activity.failed:
        blocks.append(
            "Le journal d'activité n'a pas pu être lu (commande activity_summary) : voir deploy/runbooks/monitoring.md."
        )
    return "\n".join(head + blocks).rstrip() + "\n"


def recipients(raw):
    items = [item.strip() for item in raw.split(",") if item.strip()]
    if not items or not all(ADDRESS.match(item) for item in items):
        raise ValueError(
            "ALERT_EMAILS must be a comma-separated list of e-mail addresses"
        )
    return items


def build_message(env, label, body, now):
    sender = env.get("ALERT_EMAIL_FROM", "")
    if not ADDRESS.match(sender):
        raise ValueError("ALERT_EMAIL_FROM is empty or not an e-mail address")
    message = EmailMessage()
    message["Subject"] = f"[ManuSpectrum][Report] Rapport mensuel {label}"
    message["From"] = sender
    message["To"] = ", ".join(recipients(env.get("ALERT_EMAILS", "")))
    message["Date"] = format_datetime(now)
    message["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[1])
    message["X-ManuSpectrum-Category"] = "Report"
    message.set_content(body, charset="utf-8")
    return message


def send(env, message):
    host = env.get("EMAIL_HOST", "")
    if not host:
        raise ValueError("EMAIL_HOST is empty")
    port = int(env.get("EMAIL_PORT") or 25)
    user = env.get("EMAIL_HOST_USER", "")
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if env.get("EMAIL_USE_TLS", "false") == "true":
            smtp.starttls()
        if user:
            with open(
                env.get("EMAIL_HOST_PASSWORD_FILE", "/run/secrets/email_password")
            ) as handle:
                smtp.login(user, handle.read())
        smtp.send_message(message)


def main(argv=None, env=None, out=sys.stdout, err=sys.stderr):
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(
        description="Send the monthly ManuSpectrum report."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--month")
    parser.add_argument("--now")
    parser.add_argument("--activity-command", default="")
    args = parser.parse_args(argv)

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    label = args.month or previous_month(now)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", label):
        print("monthly-report: --month must be YYYY-MM", file=err)
        return 2
    start, end = month_bounds(label)

    prom = Prometheus(env.get("PROMETHEUS_URL", "http://prometheus:9090"))
    activity = Activity(args.activity_command, label)
    body = build_body(prom, activity, label, start, end, now.astimezone(timezone.utc))
    try:
        message = build_message(env, label, body, now)
        if args.dry_run:
            out.write(message.as_string())
        else:
            send(env, message)
    except (ValueError, OSError, smtplib.SMTPException) as exc:
        print(f"monthly-report: not sent: {exc}", file=err)
        return 2
    if prom.failed or activity.failed:
        print(
            "monthly-report: sent, but a source did not answer (Prometheus or the activity command)",
            file=err,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
