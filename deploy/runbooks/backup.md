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

## TsmBackupStale

Severity: warning. No successful TSM backup of the host for more than two days.

### Prerequisites

SSH access to the host as an administrator with `sudo`: the provider's report is root's. BACKUP.md, section Logs.

### Symptom

The hosting provider's daily backup did not finish for `/data` and `/var/log`, or left no report today. The server logs on the host are not copied until it runs again.

### Diagnosis

`sudo tail -40 /var/spool/tsm/log/dsmc.incremental.local.log` shows the last run: the date, a `Successful incremental backup of` line per filespace, and the failed-object count. `journalctl -u manuspectrum-tsm-check -e` shows what the daily check read.

### Remediation

The provider's job is theirs: open a ticket with the hosting provider when it fails two nights in a row. Then `sudo systemctl start manuspectrum-tsm-check`; the alert clears with the next check that reads a successful report.

### Escalation

The technical lead. The cause is on the provider's side (TSM client or server, network, node password).

## TsmLogIncludeMissing

Severity: warning. The server logs are no longer bound to the provider's log class.

### Prerequisites

SSH access to the host as an administrator with `sudo`: the include file is root's. BACKUP.md, section Logs.

### Symptom

The TSM include file no longer holds one `include <dir>/.../* LOG_ROTATED_FILES_MG` line for every log directory, so the logs would be kept under the default class instead of 365 days after deletion.

### Diagnosis

`sudo cat /var/spool/tsm/etc/inclexcl.def` shows the lines present (a line starting with `*` is a comment and does not count). `journalctl -u manuspectrum-tsm-check -e` shows what the daily check read.

### Remediation

The include lines come back with the Ansible `host` role: run it from the repository checkout, then `sudo systemctl start manuspectrum-tsm-check`. If the provider rewrote the file, tell them the lines are managed by this deployment.

### Escalation

The technical lead. If the provider changed the file or the class, open a ticket with the hosting provider.
