# Runbook: Disks and the network filesystem

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## DiskUsageHigh

Severity: warning. A disk is more than 80 % full.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. The Disk and backups dashboard.

### Symptom

No visible effect yet; at 95 % writes start to fail.

### Diagnosis

`df -h / /data` on the host. The Disk and backups dashboard splits the usage: database, uploads, restic repository, local dumps, nginx logs, Docker images, volumes and build cache.

### Remediation

On `/`: list the images with `docker image ls` and remove unused old ones by hand, rotate logs, and check the Prometheus volume against its 8 GB cap. On `/data`: see the retention of the restic repository in BACKUP.md.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## DiskAlmostFull

Severity: critical. A disk is almost full.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. The Disk and backups dashboard.

### Symptom

PostgreSQL, uploads and backups fail to write; the site can stop.

### Diagnosis

`df -h / /data`; `du -xh --max-depth=1` on the biggest directories of the local disk (never on the network mount root).

### Remediation

Free space at once as for `DiskUsageHigh`. For `/data`, stop the backup timers until space is back.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## DiskFillingUp

Severity: warning. A disk will be full within a day.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. The Disk and backups dashboard.

### Symptom

Free space is shrinking fast.

### Diagnosis

The 7-day trend panels of the Disk and backups dashboard show what grows.

### Remediation

Find the writer (a log, an import, a backup) and stop or rotate it before the 80 % and 95 % alerts.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## NfsUnavailable

Severity: critical. The /data network filesystem is unavailable.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Access to the hosting provider's ticket system.

### Symptom

Uploads, media and backups are unreachable; image-dependent pages and every backup fail.

### Diagnosis

`findmnt /data` and `ls /data` on the host (use `timeout 10`). The Infrastructure dashboard shows when it went away.

### Remediation

Remount with the provider's procedure. Restart the containers that bind it afterwards (`make -C deploy up`). Run `make -C deploy backup` once it is back.

### Escalation

The hosting provider's support, with the time the alert fired.
