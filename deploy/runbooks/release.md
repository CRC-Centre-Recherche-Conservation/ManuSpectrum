# Runbook: Release watch and update

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host as an operator of the `manuspectrum-ops` group; the update commands go through `sudo`. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`; the release procedure is in `deploy/RELEASES.md`.

Outbound hosts of the release watch (HTTPS, port 443), checked at installation: `github.com`, `ghcr.io`, `pkg-containers.githubusercontent.com`, `tuf-repo-cdn.sigstore.dev`, `rekor.sigstore.dev`. A refused connection to one of them fails the matching step of `ReleaseWatchFailing` (`git`: github.com; `registry`: ghcr.io and pkg-containers.githubusercontent.com; `sigstore`: the two sigstore hosts).

`sudo manuspectrum-update --status` prints the current release, the armed one, how long it has waited, the schedule and the last rollback; start every diagnosis with it.

## ReleaseVerificationFailed

Severity: critical. A release failed its signature or revision check.

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`). RELEASES.md.

### Symptom

The release watch found a tag whose image signature, image digest or signed revision does not verify. It armed nothing and pulled nothing: the site runs the release it already had.

### Diagnosis

`journalctl -u manuspectrum-watch -e` and `sudo manuspectrum-update --status`. A tag still being published (image or signature not yet there) is retried quietly for six hours and does not raise this alert; a failure after that, or a signature from an unexpected identity, does.

### Remediation

Do not install the tag. Compare the tag with the GitHub release and its workflow run. If the publication was incomplete, the maintainers re-run the release workflow; the alert clears with the next good watch run. If the tag or the image may have been tampered with, keep the site on its current release and treat it as a security incident.

### Escalation

The technical lead at once. A signature that cannot be explained is a supply-chain incident: do not update until it is understood.

## UpdateRolledBack

Severity: critical. An update was rolled back.

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`). BACKUP.md for the restore.

### Symptom

An update failed its readiness checks and the previous release was restored. The site runs the previous version; the release is still armed. The alert stays for 64 hours after the rollback.

If the rollback itself failed (mail subject `ROLLBACK FAILED`, `manuspectrum_release_rollback_failed` at 1), the site may be down or running a mixed state.

### Diagnosis

`sudo manuspectrum-update --status`, then `journalctl -u 'manuspectrum-update@*' -e` and `make -C deploy status`. The cause is usually a service that did not become ready (`/readyz`), a migration error or a full disk.

### Remediation

Rollback succeeded: fix the cause, then install again with `sudo manuspectrum-update --now <TAG>`. The alert clears by itself 64 hours after the rollback.

Rollback failed: the pre-update snapshot is the way back. Restore it as BACKUP.md describes (`make -C deploy restore` with the snapshot taken before the update), check the site, then remove the in-flight marker so another update can start: `sudo rm /var/lib/manuspectrum/release/inflight`. `ROLLBACK_FAILED` clears on the next successful update.

### Escalation

The technical lead at once if the site is down or a restore is needed.

## ReleaseWatchFailing

Severity: warning. The release watch fails at one step (the alert names it).

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`).

### Symptom

The hourly watch has failed at the named step for two hours: `git`, `registry`, `sigstore`, `pull`, `mail` or `state`. No new release is detected or armed meanwhile.

### Diagnosis

`journalctl -u manuspectrum-watch -e`. Test the hosts of the step from the host: `curl -sSI https://github.com` for `git`, `https://ghcr.io/v2/` (answers 401) for `registry` and `pull`, `https://tuf-repo-cdn.sigstore.dev` and `https://rekor.sigstore.dev` for `sigstore`. `mail`: `systemctl status postfix` and `mailq`. `state`: the state directory `/var/lib/manuspectrum/release` is writable by the service account and the disk is not full.

### Remediation

Restore the outbound access or the failing component. The next hourly run clears the alert; to run it now, `sudo systemctl start manuspectrum-watch`.

### Escalation

The technical lead. If an outbound host is unreachable, open a ticket with the hosting provider (443 to the hosts above).

## ReleaseWatchStale

Severity: warning. The release watch has not run for more than 3 hours.

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`).

### Symptom

The watch writes its metrics on every run, even when nothing is new. A stale or missing `manuspectrum_release.prom` means the timer does not fire or the run dies early. A fresh install raises it until the first run (`make -C deploy silence-fresh-install`).

### Diagnosis

`systemctl list-timers 'manuspectrum-watch*' 'manuspectrum-update*'`, `journalctl -u manuspectrum-watch -e`, and `ls -l` of `manuspectrum_release.prom` in the node-exporter textfile directory. A missing metric with a fresh file points at `TextfileError`.

### Remediation

Enable and start the timer if stopped (`sudo systemctl enable --now manuspectrum-watch.timer`), then `sudo systemctl start manuspectrum-watch`. If the run hangs on a lock, an update is running: check `sudo manuspectrum-update --status`.

### Escalation

The technical lead. If the cause is the host or its network, open a ticket with the hosting provider.

## ReleasePendingTooLong

Severity: warning. A release has waited for an operator for too long.

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`). RELEASES.md.

### Symptom

A release is armed and nobody installed it: more than 30 days, or more than 14 days when it carries a security fix (`Security-Fix` trailer in the signed tag).

### Diagnosis

`sudo manuspectrum-update --status` shows the armed tag, its age and whether it is a security release; read the release notes on GitHub.

### Remediation

Install it (`sudo manuspectrum-update <TAG>`) or schedule it (`sudo manuspectrum-update --at "YYYY-MM-DD HH:MM" <TAG>`). If the release was judged unfit, a newer tag replaces it when published. The alert clears once the release is installed.

### Escalation

The technical lead, who decides whether to defer a security release.

## ReleaseScheduleFailed

Severity: warning. The scheduled update was refused or missed.

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`). RELEASES.md.

### Symptom

At the slot the update did not run. Refused: a pre-check failed (dirty worktree, free space, a newer release, a reboot window; the reason is in the mail). Missed: the host was off or the watch noticed the slot had passed more than 15 minutes ago; a missed slot is never run afterwards. Nothing was installed and the site notice, if any, was withdrawn.

### Diagnosis

`sudo manuspectrum-update --status` shows the outcome and the reason; `journalctl -u manuspectrum-update-at -e` the pre-check output.

### Remediation

Fix the reason if there is one, acknowledge the failed slot with `sudo manuspectrum-update --cancel` (the alert clears on the next watch run), then schedule a new slot or install at once.

### Escalation

The technical lead.
