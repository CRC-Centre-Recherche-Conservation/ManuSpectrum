# Monitoring and alerts

Reference for the monitoring stack of the deployment: what runs, how to open the
dashboards, which alerts exist, who receives them and how to sort the mail. The
application side (metrics, logs, `/healthz`, `/readyz`) is in
`manuspectrum/observability/README.md`; what to do when an alert fires is in
[`runbooks/`](runbooks/monitoring.md). Nothing here is specific to one host:
values of a host live in `compose/.env`.

## What runs

The `observability` Compose profile, switched on by `COMPOSE_PROFILES` in `.env`
(empty keeps it off). It adds seven containers, none of which mounts the Docker
socket:

| Service | Role |
| --- | --- |
| `prometheus` | Scrapes the application, Prometheus and Alertmanager every 30 s and the exporters every 60 s, evaluates the rules; 30 days of data, capped at 8 GB, on a local volume (never the network filesystem) |
| `alertmanager` | Routes the alerts by severity and mails them through the SMTP relay of the stack |
| `grafana` | Four read-only dashboards; listens on `127.0.0.1:3000` of the host only |
| `node-exporter` | Host CPU, memory, load, clock, filesystems, and the textfile metrics below |
| `postgres-exporter` | PostgreSQL through the read-only `ms_monitor` role (`pg_monitor`); no query text |
| `redis-exporter` | Broker and cache |
| `blackbox-exporter` | Probes the public name (`/healthz`, certificate expiry) and Cantaloupe |

The application is scraped directly on the internal network (`web:8000`,
`worker:9808`): nginx refuses `/metrics` from outside. Two host timers write the
metrics a container cannot read (next section). Grafana is on the `monitoring`
network only, so it cannot reach `web`.

Make targets (`make -C deploy <target>`):

| Target | Effect |
| --- | --- |
| `monitoring-init` | Once per host, with `postgres` up: create or update the `ms_monitor` role and `pg_stat_statements` |
| `observability-on`, `observability-off` | Start, or stop and remove, the monitoring containers (volumes kept) |
| `alert-recipients` | After editing `ALERT_EMAILS`, the sender or the relay in `.env`: validate, recreate Alertmanager |
| `alert-test` | Raise a critical `AlertTest` for five minutes: a mail must arrive |
| `alerts` | List the alerts Alertmanager holds |
| `silence` | Silence an alert for maintenance |
| `silence-fresh-install` | Silence for 48 h the alerts a new install raises before its first backup, restore test and timers |
| `report-test`, `monthly-report` | Send the monthly report now |
| `container-metrics`, `disk-usage` | Write the host metrics (the timers call them) |

## Opening Grafana

Grafana is never proxied by nginx and has no public address. Open an SSH tunnel
from your workstation to the host, with your own account:

```bash
ssh -L 3000:localhost:3000 <account>@<host>
```

Leave it open and browse `http://localhost:3000`. The login is `admin` and the
password is the file `grafana_admin_password` of the secrets directory
(`SECRETS.md`; sign-up, anonymous access, plugins, update checks and Grafana's own
alerting are off). Grafana stores only its administrator account and the
preferences of whoever signs in, on the `grafana_data` volume.

## Dashboards

Provisioned from `compose/observability/grafana/dashboards/*.json`, read-only in
Grafana. A change is made in Git (edit the JSON, redeploy), never in the browser:
a modification made there is lost at the next start.

| Dashboard | Answers |
| --- | --- |
| Overview | Is it working? Site, readiness, image server, alerts firing, certificate, disks, last good backup |
| Application | Requests, errors, Explorer latency and corpus builds, Celery tasks, upstream calls, sign-in attempts |
| Infrastructure | Containers (state, memory against its limit, restarts, OOM kills), host CPU, memory, swap, clock, PostgreSQL, Redis, scrape targets |
| Storage and backups | Filesystem use and time until full for `/` and `/data`, size of each data area, database size, backup repository, last backup and restore test |

**Disk numbers.** The `/` and `/data` panels come from the filesystem itself
(`df`). The area panels (uploads, backup repository, dumps, nginx logs) come from
`du` of those named directories, once an hour. The database size comes from
PostgreSQL. They are different measures: the sizes of the areas do not add up to
the filesystem use, and a network filesystem's `.snapshot` directory counts only
in the filesystem number.

**Never `du` on a mount root.** `du` of `/data` on the network filesystem is slow
and counts snapshots. `host-metrics.sh disk` measures only the named
sub-directories, refuses a path that is a mountpoint, and runs under `nice`,
`ionice` and a timeout. Do not add a panel, a script or a command that measures
a mount root.

## Alerts

51 rules in `compose/observability/prometheus/rules/*.yml`, one file per area
(site, application, containers, host, storage, backup, tls, celery, datastores,
explorer, biblissima, monitoring). Every rule has a `severity`, a `service`, a
`summary`, a `description` and a `runbook_url` that points to a section of
[`runbooks/`](runbooks/site.md) named after the alert.

| Severity | Mail | Timing |
| --- | --- | --- |
| `critical` | At once | Grouped by alert and service, first mail 30 s after the alert, repeated every 4 h while it fires |
| `warning` | Grouped by service, sent only on weekdays 08:00-19:00 (Europe/Paris); one raised outside waits for the window | First mail 2 min after the alert is grouped, then at most every 30 min for new alerts, repeated every 24 h |
| `info`, `none` | Never | Visible in Grafana and `make alerts` |

Each alert also waits for its `for:` duration in Prometheus. **Event warnings**
(`ContainerOOMKilled`, `ContainerRestartLoop`, `CeleryTaskFailures`,
`IndexingFailures`, `ExplorerRebuildFailing`, `WriteBudgetSpent`,
`PrometheusRuleFailures`) fire on a single event and read a 64 h window of stored
samples (`increase(counter[64h]) > 0`; `ContainerRestartLoop` takes the
maximum over 64 h of its hourly rise). A warning raised at night or on a weekend
would otherwise clear before the next weekday window and, since Alertmanager drops
the resolved alerts of a muted group, never be mailed. 64 h covers Friday 19:00 to
Monday 08:00 (61 h); a public holiday delays the mail to the next working day. The
window lives in the TSDB, so a Prometheus restart or a reboot does not lose the
event. The cost: an event of Tuesday noon is repeated every 24 h until 64 h have
passed. The alert then resolves; its `RESOLVED` mail follows only when that moment
falls inside the weekday 08:00-19:00 window (Alertmanager drops the resolved
notification of a muted warning group, so an event of Tuesday noon, resolved on
Friday 04:00, is usually never closed by a mail). The monthly report counts one
episode per 64 h of such an event.
`ExplorerBundleBuildSlow` and `ExplorerBundleBuildVerySlow` need at least three
builds in the hour, so one slow cold build alerts nobody. Disk thresholds:
`DiskUsageHigh` warning above 80 %, `DiskAlmostFull` critical above 95 %,
`DiskFillingUp` warning when the 6 h trend fills a disk within 24 h. There is no
"no traffic" alert: a quiet site is not a fault.

**Inhibitions.**

- A critical alert hides the warnings of the same `service`.
- `RecentlyRebooted` (the host booted less than 15 minutes ago) hides every
  critical and warning alert except the `AlertTest` of `make alert-test`. The nightly 04:50 reboot is therefore silent; a
  stack that is not back after 15 minutes fires normally.

**Maintenance.** `make -C deploy silence ARGS='alertname=DiskUsageHigh --duration=2h --comment="why"'`
silences one alert; silences live on a volume and survive a restart.
`make -C deploy observability-off` stops the stack (volumes kept).

**Node exporter down.** `NfsUnavailable`, `BackupMissing`, `RestoreTestMissing`,
`HostMetricsStale`, `DiskUsageStale` and `ContainerMissing` read series that only
node_exporter carries. They count a missing series only while node_exporter is up,
so its outage raises `NodeExporterDown` alone (critical, after 15 minutes, since it
blinds the backup and NFS alerts; `TargetDown` covers the other targets).

**Certificate trust.** `http_edge` measures the expiry without verifying the chain
(so the local and staging authorities pass); `http_edge_verified` verifies it and
`CertificateInvalid` (warning) fires when the site answers but the chain or name
does not verify. The Prometheus entrypoint marks a target `rehearsal="true"` when
`PUBLIC_HOST` ends in `.test`, which turns the alert off in CI and rehearsal. With
`CERT_MODE=acme` against the Let's Encrypt staging authority it fires, as it should.

**Fresh install.** Until the first backup, the first Sunday restore test and the
first run of the systemd timers, `BackupMissing` (critical), `RestoreTestMissing`,
`HostMetricsStale`, `DiskUsageStale` and `ContainerMissing` fire. Install the
timers and take a first backup before `observability-on`, or run
`make -C deploy silence-fresh-install` (48 h, with a comment) and let the first
backup, restore test and timers land within it.

**Heartbeat.** The always-firing `Watchdog` alert becomes one mail on Monday at
08:00 (Europe/Paris, a five-minute window). It proves that Prometheus evaluates
the rules, that Alertmanager routes them and that the relay delivers. Its limit:
the absence of the mail is the signal, so someone has to notice it. If the whole
VM is down, nothing is sent; the external probe of PP-9 covers that case.

**Monitoring the monitors.** `TargetDown`, `NodeExporterDown`, `HostMetricsStale`, `DiskUsageStale`,
`TextfileError`, `AlertmanagerNotificationsFailing`, `PrometheusRuleFailures` and
`Watchdog` watch the stack itself ([`runbooks/monitoring.md`](runbooks/monitoring.md#targetdown)).

## Recipients and sender

Every mail setting of the host `.env` at a glance. With one generic institutional
address, the recipient settings all hold that address and the sender settings all
hold an address on the host's own domain:

| Setting | Role | Holds |
| --- | --- | --- |
| `CONTACT_EMAIL` | address shown on the public pages and used by the contact form | the generic address |
| `ALERT_EMAILS` | receives alerts, the Monday heartbeat and the monthly report | the generic address |
| `ADMINS` | receives Django's server-error mails (optional) | the generic address |
| `ACME_EMAIL` | Let's Encrypt account, certificate notices (`CERT_MODE=acme`) | the generic address |
| `ALERT_EMAIL_FROM` | sender of alerts, heartbeat and report | `noreply@<host domain>` |
| `DEFAULT_FROM_EMAIL` | sender of application mail (password reset, Arches notices); required | `noreply@<host domain>` |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS` | the outgoing relay | the hosting provider's relay |

Outside `.env`, the host's `root` alias (system mail) points to the same generic
address (set by the host role, PP-8). Every message carries a subject prefix and
header to sort it (« Sorting the mail » below).

**Recipients.** One comma-separated list, `ALERT_EMAILS`, in the host `.env`
(never in Git). It serves the alerts, the monthly report and the Monday
heartbeat. A generic list address managed by the institution is recommended: who
receives the mail then changes without touching the host. To change the list:
SSH to the host, edit `.env`, then

```bash
make -C deploy alert-recipients
```

It validates the list on the host first (a bad list leaves Alertmanager running
unchanged), then recreates Alertmanager. Nothing is stored in the database.

**Sender.** `ALERT_EMAIL_FROM` (alerts, heartbeat, report) and
`DEFAULT_FROM_EMAIL` (application mail) are the same address on the domain of
the host itself, for example `noreply@manuspectrum.huma-num.fr`. `DEFAULT_FROM_EMAIL`
is required: the settings refuse to start without it and never fall back to
`CONTACT_EMAIL`. Why not an institutional sender:

- The relay delivers mail for the hosting provider's domain; it rewrites the
  envelope sender to that domain, so SPF and DKIM pass for the provider.
- A sender on another organisation's domain is checked against that domain's
  DMARC policy; when it is `p=quarantine` with strict alignment and the relay is
  not in its SPF, the mail is quarantined.
- A sender on the host's own domain needs no permission and passes.

Alertmanager introduces itself to the relay (SMTP HELO) with `PUBLIC_HOST`, the host's
own validated name, whatever the sender's domain.

## Sorting the mail

Every message the platform sends carries a subject prefix
`[ManuSpectrum][<Category>]` and, when the sender controls headers, an
`X-ManuSpectrum-Category` header. One address receives everything; mail filters
sort on either.

| Category | Sent by | Subject | Header |
| --- | --- | --- | --- |
| Alert | Alertmanager | `[ManuSpectrum][Alert] CRITICAL\|WARNING <alertname> - <summary>`; `RESOLVED …` when it clears | `alert` |
| Heartbeat | Alertmanager, Monday 08:00 | `[ManuSpectrum][Heartbeat] Alerting chain OK` | `heartbeat` |
| Report | Monthly report | `[ManuSpectrum][Report] Rapport mensuel <YYYY-MM>` | `report` |
| Contact | Public contact form | `[ManuSpectrum][Contact] <reason> — <name>` | none (a `mailto:` link cannot set a header: filter on the subject) |
| Account | Reserved for PP-4: access requests, embargo and workflow notices | `[ManuSpectrum][Account] …` | `account` |
| System | Host mail (`root` alias: unattended upgrades, cron) | Unchanged | none (filter on the sender `root@<host>`) |

## Monthly report

On the 1st at 08:00 the `manuspectrum-monthly-report` timer sends a report of the
previous month, in French, to `ALERT_EMAILS`: availability, disks, sizes, backups and
restore tests, restarts and out-of-memory kills, alerts of the month, active accounts. Growth is given "sur le mois"
when Prometheus still holds the start of the month, else "depuis le <date>" from its oldest sample (retention is 30
days). Metrics that could not be read are listed
under "données indisponibles" and the command exits 1. `make -C deploy report-test
[ARGS="--month YYYY-MM"]` sends one now.

## Host metrics

Two timers write Prometheus textfiles that `node-exporter` reads from
`METRICS_TEXTFILE_DIR`, through `scripts/host-metrics.sh` and the shared
`scripts/lib-metrics.sh` (atomic writes, bounded label values):

| Unit | Schedule | Metrics |
| --- | --- | --- |
| `manuspectrum-container-metrics` | Every 30 s | Per Compose service: running, health, restarts, OOM kills, memory against its limit |
| `manuspectrum-disk-usage` | Every hour at :17 | Size of the uploads, the backup repository, the dumps and the nginx logs, plus the Docker sizes below. The unit file carries the four-times-a-day calendar to use if a measure proves slow on the network filesystem |

Docker sizes (one `docker system df -v` call under `nice` and `ionice`, each kind
the sum of its entries, about four significant digits; the images figure counts
the unique size of each image, so it is about 0.3 % under `docker system df`):
`manuspectrum_docker_disk_bytes{kind=images|build_cache|containers|volumes}` and
`manuspectrum_docker_volume_bytes{volume=ms_*}` (the external data volumes).
`manuspectrum_container_oom_cgroup` is 1 when a container's OOM kills are counted
from the cgroup v2 `memory.events` file (a kill of a child process included) and 0
when the collector fell back on Docker's `OOMKilled` flag, which misses most kills;
0 for an hour raises `OomSourceDegraded`. A disk run has a budget of 840 s: `du`
300 s per target and `docker system df -v` 120 s, all under `timeout`. The
checks that stat a directory before `du` (existence, mountpoint) run outside any
timeout, so a hard-hung mount can hold the run until systemd stops the unit at
`TimeoutStartSec` (15 min); a `du` stuck in uninterruptible I/O is not killed by
its timeout either. Either case leaves `DiskUsageStale` to report it.

The backup and restore-test timers write their own textfiles (`BACKUP.md`). A
stale file raises `HostMetricsStale` or `DiskUsageStale`.

**Labels.** Metric labels are closed vocabularies (service names, area names,
severities), never an id, a user, a URL or a path. Textfile label values match
`^[a-z0-9_-]+$`; an application label comes from `ALLOWED_LABELS`
(`manuspectrum/observability/metrics.py`). Metrics carry no personal data.

## Checking a running stack

`compose/smoke.sh` (CI and the rehearsal VM; read-only except the test mail):

| Command | Checks |
| --- | --- |
| `smoke.sh monitoring` | Every Prometheus target up, every rule evaluating, `Watchdog` firing, the series each rule and dashboard expression reads, Grafana healthy with its four dashboards. Run `make container-metrics disk-usage` (and a backup) first. `SMOKE_EXPECT_BACKUP=1` also requires the backup and restore-test gauges to exist and read 0 |
| `smoke.sh mail alert` | After `make alert-test`: the `AlertTest` mail reached Mailpit with the `[ManuSpectrum][Alert]` prefix and its category header (CI and rehearsal, where `COMPOSE_PROFILES` includes `mailpit`) |
| `smoke.sh mail report` | The same after `make report-test`, for `[ManuSpectrum][Report] Rapport mensuel` |

## Installing and upgrading

The units are installed by the configuration management (PP-8). Until then, on a
host, render the `deploy/systemd/*.in` files (`@APP_USER@`, `@DEPLOY_DIR@`), copy
them to `/etc/systemd/system/` and `systemctl enable --now` the timers.

A host that already has a `.env` must add `COMPOSE_PROFILES`, `ALERT_EMAILS`,
`ALERT_EMAIL_FROM` and a `DEFAULT_FROM_EMAIL` (`compose/.env.example` documents
each) **before pulling this version**: the settings refuse to start without the
sender. Then:

```bash
make -C deploy volumes secrets up monitoring-init observability-on
```

`secrets` creates the two new secrets (`grafana_admin_password`,
`pg_monitor_password`) and keeps the others; copy both into the vault item
(`SECRETS.md`). Check the chain with `make -C deploy alert-test` and
`make -C deploy report-test`.

## What is never backed up

Prometheus data, Alertmanager silences and Grafana's database are monitoring
state, rebuilt from the configuration in Git. They are not part of any backup
(`BACKUP.md`); the retention (30 days) is an operational choice, not a legal
limit on personal data.

## Runbooks

One file per area, one section per alert, each with prerequisites, symptom,
diagnosis, remediation and escalation:
[site](runbooks/site.md), [application](runbooks/application.md),
[containers](runbooks/containers.md), [host](runbooks/host.md),
[storage](runbooks/storage.md), [backup](runbooks/backup.md),
[TLS](runbooks/tls.md), [Celery](runbooks/celery.md),
[datastores](runbooks/datastores.md), [Explorer](runbooks/explorer.md),
[Biblissima](runbooks/biblissima.md), [monitoring](runbooks/monitoring.md).
