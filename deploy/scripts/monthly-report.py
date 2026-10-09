#!/usr/bin/env python3
"""Monthly operations report of ManuSpectrum, sent by e-mail in French.

Run once a month by `make -C deploy monthly-report` (systemd timer, the 1st at
08:00), and on demand by `make -C deploy report-test`. It covers the calendar
month that just ended. Python standard library only: the Make target runs it in
a throwaway container of the application image on the Compose network.

Every figure comes from the Prometheus HTTP API (PROMETHEUS_URL, default
http://prometheus:9090). Nothing personal is read: only aggregated metrics, and
the active-accounts line stays a note until the application exports such a
metric. A section whose query fails reads "données indisponibles"; the report
is sent anyway and the exit status is then 1. Prometheus keeps 30 days: a
figure older than that reads "n/d". The growth lines (free space, database)
compare the end of the month with its start, or with 29 days before the run
when the month began earlier than that, and then say "depuis le <date>".

Environment: EMAIL_HOST, EMAIL_PORT, EMAIL_USE_TLS (true = STARTTLS),
EMAIL_HOST_USER and EMAIL_HOST_PASSWORD_FILE (login only when the user is set),
ALERT_EMAILS (comma-separated recipients), ALERT_EMAIL_FROM.

Usage: monthly-report.py [--dry-run] [--month YYYY-MM] [--now ISO-8601]
  --dry-run  print the message instead of sending it
  --month    report this month instead of the previous one
  --now      the clock for the default month (tests)

Exit: 0 sent and complete, 1 sent with a section unavailable, 2 not sent
(configuration or SMTP failure).
"""

import argparse
import calendar
import json
import os
import re
import smtplib
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
RETENTION_DAYS = 29  # Prometheus keeps 30; one day of margin for block deletion
MONTHS_FR = (
    "janvier février mars avril mai juin juillet août "
    "septembre octobre novembre décembre"
).split()


class Unavailable(Exception):
    """Prometheus did not answer, or answered something unreadable."""


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


def accounts(prom, start, end):
    return [
        "non disponible : l'application n'exporte pas encore de compteur de comptes actifs "
        "(aucune donnée personnelle n'est lue pour ce rapport)"
    ]


def build_body(prom, label, start, end, now):
    last_day = end - timedelta(days=1)
    head = [
        f"Rapport mensuel ManuSpectrum, {MONTHS_FR[start.month - 1]} {start.year}",
        f"Période : du 1er au {last_day.day} {MONTHS_FR[last_day.month - 1]} {last_day.year} (UTC)",
        "Source : Prometheus (conservation de 30 jours : un chiffre plus ancien s'affiche n/d)",
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
        ("Comptes actifs", accounts),
    ):
        blocks += section(prom, title, lambda b=build: b(prom, start, end))
    if prom.failed:
        blocks.append(
            "Prometheus n'a pas répondu à au moins une requête : voir deploy/runbooks/monitoring.md."
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
    message["X-ManuSpectrum-Category"] = "report"
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
    body = build_body(prom, label, start, end, now.astimezone(timezone.utc))
    try:
        message = build_message(env, label, body, now)
        if args.dry_run:
            out.write(message.as_string())
        else:
            send(env, message)
    except (ValueError, OSError, smtplib.SMTPException) as exc:
        print(f"monthly-report: not sent: {exc}", file=err)
        return 2
    if prom.failed:
        print(
            "monthly-report: sent, but Prometheus did not answer every query", file=err
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
