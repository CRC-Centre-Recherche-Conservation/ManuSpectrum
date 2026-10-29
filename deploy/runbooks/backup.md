# Runbook: Backups

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## BackupFailed

Severity: critical. The last backup failed.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. BACKUP.md.

### Symptom

The nightly backup did not complete.

### Diagnosis

`journalctl -u manuspectrum-backup -e` and the `FAIL:` line of the log. BACKUP.md, section When things go wrong, lists the usual causes (lock, full repository, network filesystem).

### Remediation

Fix the cause, then `make -C deploy backup`. The alert clears with the next successful run.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## BackupMissing

Severity: critical. No successful backup for more than 26 hours.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. BACKUP.md.

### Symptom

Backups do not run or do not report.

### Diagnosis

`systemctl list-timers 'manuspectrum-*'` and `journalctl -u manuspectrum-backup -e`. A metric missing altogether means the textfile directory is not mounted or the first backup never ran.

### Remediation

Start the timer if stopped, run `make -C deploy backup`, then check `TextfileError` if the metric stays absent.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## RestoreTestFailed

Severity: critical. The restore test failed.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. BACKUP.md.

### Symptom

A backup exists that has not been proven to restore.

### Diagnosis

`journalctl -u manuspectrum-restore-test -e` for the `FAIL:` line; BACKUP.md, section The restore test.

### Remediation

Run `make -C deploy restore-test` after fixing the cause; run `make -C deploy backup` first if the snapshot is bad.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## RestoreTestMissing

Severity: warning. No successful restore test for more than 8 days.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. BACKUP.md.

### Symptom

Backups are not being proven.

### Diagnosis

`systemctl list-timers 'manuspectrum-*'` and `journalctl -u manuspectrum-restore-test -e`.

### Remediation

Run `make -C deploy restore-test`; restart the timer if it is stopped.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
