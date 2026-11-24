# Runbook: Backups

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## BackupFailed

Severity: critical. The last backup failed.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. BACKUP.md.

### Symptom

The nightly backup did not complete.

### Diagnosis

An altered repository looks like this alert (an attack on the backups also makes the backup fail): read `sudo journalctl -t restic-repo-guard --since "2 days ago"` first. An `ALTERED:` line means go to [ResticRepoAltered](#resticrepoaltered) before repairing or re-creating the repository. 

Then `journalctl -u manuspectrum-backup -e` and the `FAIL:` line of the log. BACKUP.md, section When things go wrong, lists the usual causes (lock, full repository, network filesystem).

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

An altered repository looks like this alert (an attack on the backups also makes the backup fail): read `sudo journalctl -t restic-repo-guard --since "2 days ago"` first. An `ALTERED:` line means go to [ResticRepoAltered](#resticrepoaltered) before repairing or re-creating the repository. 

Then `systemctl list-timers 'manuspectrum-*'` and `journalctl -u manuspectrum-backup -e`. A metric missing altogether means the textfile directory is not mounted or the first backup never ran.

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

`sudo cat /var/spool/tsm/etc/inclexcl.def` shows the lines present (a line starting with `*` is a comment and does not count). `sudo dsmc query inclexcl` shows the statements TSM applies: a statement added below ours takes precedence over them. `journalctl -u manuspectrum-tsm-check -e` shows what the daily check read.

### Remediation

The include lines come back with the Ansible `host` role: run it from the repository checkout, then `sudo systemctl start manuspectrum-tsm-check`. If the provider rewrote the file, tell them the lines are managed by this deployment.

### Escalation

The technical lead. If the provider changed the file or the class, open a ticket with the hosting provider.

## ResticRepoAltered

Severity: warning. The restic repository holds a file that does not match its name.

### Prerequisites

SSH access to the host as an administrator with `sudo`: the guard, its state and the provider's job are root's. The guard exists only on hosts backed up by the hosting provider's TSM.

### Symptom

The check that runs just before the provider's nightly TSM copy found at least one repository file whose SHA-256 differs from its name, or a changed `config`. The TSM copy did not run today, on purpose: the provider's job stops before `dsmc` so the altered files do not replace the good versions TSM still holds. That stops the provider's copy of every filespace, the logs included, not only the repository. The verdict stays « altered » until a full pass finds the repository intact. If nothing is done, `ResticRepoGuardStale` and then `TsmBackupStale` follow after two days.

### Diagnosis

`sudo journalctl -t restic-repo-guard --since today` shows the `ALTERED: <path>` lines, one per file. `make -C deploy restic ARGS="check --read-data"` asks restic itself to read every file; it runs as the service account, in the checkout (`sudo -iu <service account>`, administrators are not in the docker group), while the other `sudo` commands run as an administrator. The journal shows at most the first 100 altered files and a total. Read `sudo grep restic-repo-guard /etc/cron.daily/tsm` for the two directories the job passes to the guard.

### Remediation

Treat it as a suspected compromise: start with the first step of [INCIDENT.md](../INCIDENT.md#suspected-compromise), « Protect the backups first ». Restore the repository from the provider's backup or snapshots before any new TSM copy, then re-run the guard in full as root, with the two values read from the line of `/etc/cron.daily/tsm`:

`sudo env METRICS_TEXTFILE_DIR=<metrics dir> RESTIC_REPOSITORY_DIR=<repository> RESTIC_GUARD_FULL=1 /usr/local/lib/manuspectrum/repo-guard/restic-repo-guard.sh`

Exit 0 means the repository is intact: the mismatch gauge returns to 0 and the success time moves. When `config` was changed on purpose (for instance a migration of the repository format), delete `/var/lib/manuspectrum/repo-guard/config.sha256` before that run: the next pass records the new reference. A missing `config` with packs left is reported as an alteration.

### Escalation

The technical lead at once. If the cause is a compromise of the host, follow INCIDENT.md; the hosting provider holds the previous versions of the files.

## ResticRepoGuardStale

Severity: warning. The restic repository check has not succeeded for more than two days.

### Prerequisites

SSH access to the host as an administrator with `sudo`. The guard exists only on hosts backed up by the hosting provider's TSM.

### Symptom

The guard did not complete a pass without mismatch for more than 54 hours, or never did on a host backed up by the provider's TSM. Causes: the guard cannot judge (its `FAIL:` line in the journal says why: unreadable file, full disk, unexpected error); the provider's job does not run at all (not executable after an incident freeze that was never reversed: `ls -l /etc/cron.daily/tsm`); the guard line is missing from the job; the repository path is wrong (the guard then says « no restic repository »); or it finds an alteration every day, in which case `ResticRepoAltered` fires too and the provider's TSM copy has not run on purpose. A guard that cannot run never blocks the TSM copy.

### Diagnosis

`sudo journalctl -t restic-repo-guard --since "3 days ago"` shows the guard's messages (`FAIL:` for a configuration or read error, `ALTERED:` for an alteration). `sudo ls -l /usr/local/lib/manuspectrum/repo-guard/ /etc/cron.daily/tsm` shows the program and that the job is executable. A repository directory that is missing is logged and records no success.

### Remediation

When `ResticRepoAltered` is firing, follow its section first. Otherwise fix what the log names, or run the Ansible `host` role from the repository checkout to put the script and the job line back (the guard recreates its state directory), then run the guard once by hand:

`sudo env METRICS_TEXTFILE_DIR=<metrics dir> RESTIC_REPOSITORY_DIR=<repository> RESTIC_GUARD_FULL=1 /usr/local/lib/manuspectrum/repo-guard/restic-repo-guard.sh`

with the two values of `sudo grep restic-repo-guard /etc/cron.daily/tsm`. The alert clears after a pass that exits 0.

### Escalation

The technical lead. If the cron line is missing or rewritten, tell the hosting provider that it is managed by this deployment.
