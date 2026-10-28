# Runbook: Release watch and update

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host as an operator of the `manuspectrum-ops` group; the update commands go through `sudo`. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`; the release procedure is in `deploy/RELEASES.md`.

Outbound hosts of the release watch and update (HTTPS, port 443): `github.com`, `ghcr.io`, `pkg-containers.githubusercontent.com` (image layers), `tuf-repo-cdn.sigstore.dev`, `rekor.sigstore.dev`. Each watch run probes `https://github.com/` (step `git`), `https://ghcr.io/v2/`, which must answer 401 (step `registry`), and `https://tuf-repo-cdn.sigstore.dev/` (step `sigstore`); a blocked layer or Rekor host shows as a failed pull or verification.

The unit log of an update (or of a scheduled slot) is `journalctl -u manuspectrum-update@<tag>`; the watch's is `journalctl -u manuspectrum-watch`.

`sudo manuspectrum-update --status` prints the current release, the armed one, how long it has waited, the schedule and the last rollback; start every diagnosis with it.

## ReleaseVerificationFailed

Severity: critical. A release failed its signature or revision check.

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`). RELEASES.md.

### Symptom

The release watch found a tag whose image signature, image digest or signed revision does not verify. It armed nothing and pulled nothing: the site runs the release it already had. The revision check reads the `org.opencontainers.image.revision` label of the image, which is only visible after the pull: a label that differs from the tag's commit fails after the pull, as a verification failure (not a pull failure).

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

If the rollback itself failed (mail subject `ROLLBACK FAILED`, `manuspectrum_release_rollback_failed` at 1), the critical alert `UpdateRollbackFailed` fires: follow its section below.

### Diagnosis

`sudo manuspectrum-update --status`, then `journalctl -u 'manuspectrum-update@*' -e` and `make -C deploy status`. The cause is usually a service that did not become ready (`/readyz`), a migration error or a full disk.

### Remediation

Fix the cause, then install again with `sudo manuspectrum-update --now <TAG>`. The alert clears by itself 64 hours after the rollback.

A migration that takes long is the usual reason for a rollback that was not a bug: the engine waits `RELEASE_READY_WAIT_SECONDS` (default 600, at most 1800) for `/readyz` and then rolls back, and a migration that was running at that moment is interrupted. The rollback never restores the data, so check that the database is consistent with the previous release before trying again. A release with long migrations says how long its readiness takes (RELEASES.md, pre-tag checklist): raise `RELEASE_READY_WAIT_SECONDS` in `.env` first, then install.

### Escalation

The technical lead at once if the site is down or a restore is needed.

## UpdateRollbackFailed

Severity: critical. An update failed or was interrupted and the previous release could not be put back.

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`). BACKUP.md (« Restore the stack », « Personal data »).

### Symptom

The mail `ROLLBACK FAILED` (or `update of <tag> interrupted`) was sent and `manuspectrum_release_rollback_failed` is 1. The site may be down or running a mixed state (new code on the previous database, or the reverse). `/var/lib/manuspectrum/release/inflight` is kept: no update runs until it is removed. The engine never restores data by itself.

### Diagnosis

`sudo manuspectrum-update --status`, `journalctl -u 'manuspectrum-update@*' -e`, `make -C deploy status`, and `git -C ~/manuspectrum describe --tags --always` with the `MANUSPECTRUM_IMAGE` line of `.env` to see which release the checkout and the stack are on.

### Remediation

First try to repair by hand: check out the previous release's tag in the checkout, put its `MANUSPECTRUM_IMAGE` back in `.env` (`sudo manuspectrum-update --status` prints both), and `make -C deploy up`. If the data are damaged or the stack will not start, restore the snapshot taken just before the update as BACKUP.md describes (`make -C deploy restic ARGS="snapshots --tag pre-update"`, then `make -C deploy restore RESTIC_SNAPSHOT=<id> CONFIRM=yes ERASURES_CHECKED=yes`). Once the site answers on the release `current` names, mark the failure as resolved: `sudo manuspectrum-update --resolved` (terminal, asks for `yes`; refused while an update unit is active or an Ansible run holds its marker). It removes the in-flight marker so another update can start, sets `ROLLBACK_FAILED` to 0, rewrites the metrics (the alert clears at the next scrape) and mails who did it. Without it, `ROLLBACK_FAILED` clears only at the next successful update, which cannot start while the marker exists.

### Escalation

The technical lead at once: the site may be down.

## UpdateInterrupted

Severity: warning. An update has been in flight for more than 5.5 hours.

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`). BACKUP.md for a restore.

### Symptom

`manuspectrum_release_inflight_since_timestamp_seconds` names an update that started more than 5.5 hours ago, past the longest a unit can live (4 hours to start plus 1 h 15 min to stop, about 5 h 16 min). The engine did not finish or roll back: the host restarted during the update, the engine was killed, or it hung. When the unit stopped on its own (timeout, kill), the engine's `--after-stop` step has already raised `UpdateRollbackFailed` and mailed `update of <tag> interrupted`; this warning is the net for a host that restarted before it could.

### Diagnosis

`sudo manuspectrum-update --status`, `systemctl status 'manuspectrum-update@*'`, `journalctl -u 'manuspectrum-update@*' -e`, `cat /var/lib/manuspectrum/release/inflight` (FROM_TAG, TO_TAG, STARTED_AT) and `make -C deploy status`.

### Remediation

Inflight after a crash, in order:

1. Make sure no update still runs: `systemctl list-units 'manuspectrum-update@*'`. If one does, let it end or stop it with `sudo systemctl stop 'manuspectrum-update@<tag>'`; its trap rolls back first.
2. Find which release the checkout (`git describe --tags`) and `.env` (`MANUSPECTRUM_IMAGE`) are on, against FROM_TAG and TO_TAG of the marker, and whether the site answers (`curl -s -o /dev/null -w '%{http_code}' https://<host>/readyz`).
3. Site healthy on FROM_TAG: nothing else is needed. Site healthy on TO_TAG: the state files still name FROM_TAG as current and the next update refuses with `drift` until they are corrected, so tell the technical lead before marking it as resolved. Otherwise repair or restore as in `UpdateRollbackFailed`.
4. Mark it as resolved: `sudo manuspectrum-update --resolved` (removes the in-flight marker and clears `ROLLBACK_FAILED`). The next `sudo manuspectrum-update --now <tag>` then starts from a clean state.

### Escalation

The technical lead if the site is down, half switched, or a restore is considered.

## ReleaseWatchFailing

Severity: warning. The release watch fails at one step (the alert names it).

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`).

### Symptom

The hourly watch has failed at the named step for two hours: `git`, `registry`, `sigstore`, `pull`, `mail` or `state`. No new release is detected or armed meanwhile.

### Diagnosis

`journalctl -u manuspectrum-watch -e`. Test the hosts of the step from the host: `curl -sSI https://github.com` for `git`, `https://ghcr.io/v2/` (answers 401) for `registry` and `pull`, `https://tuf-repo-cdn.sigstore.dev` and `https://rekor.sigstore.dev` for `sigstore`. `mail`: `systemctl status postfix` and `mailq`. `state`: the state directory `/var/lib/manuspectrum/release` is writable by the service account and the disk is not full. `state` also fires when `/run/manuspectrum/ansible-running` is older than 2 hours (`journalctl` says `Ansible marker older than 2 h`): an Ansible run was interrupted and left its marker, which stops the watch, the update command and the release engine. Check that no playbook is running (`pgrep -a ansible`), then remove the file (`sudo rm /run/manuspectrum/ansible-running`); an Ansible run refreshes its modification time each time it takes the marker.

### Remediation

Restore the outbound access or the failing component. The next hourly run clears the alert; to run it now, `sudo systemctl start manuspectrum-watch`.

Step `git` with `! [rejected] <tag> -> <tag> (would clobber existing tag)` in the log: the origin now names a different commit for a tag this host already has. Release tags never move (RELEASES.md), so treat it as a possible tag rewrite and as a security incident: do not install that tag, do not delete the local tag, compare it with the GitHub release and the repository ruleset, and call the technical lead. Only once the lead has confirmed the move is legitimate, delete the stray local tag as the service account (`git -C ~manuspectrum/manuspectrum tag -d <tag>`); the next watch run fetches the tag again. A local tag that the origin never had needs no action: the watch and the engine fetch with `--prune-tags` and drop it.

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

Install it (`sudo manuspectrum-update --now <TAG>`) or schedule it (`sudo manuspectrum-update --at "YYYY-MM-DD HH:MM" <TAG>`). If the release was judged unfit, a newer tag replaces it when published. The alert clears once the release is installed.

### Escalation

The technical lead, who decides whether to defer a security release.

## ReleaseScheduleFailed

Severity: warning. The scheduled update was refused or missed.

### Prerequisites

SSH access to the host as an operator (`manuspectrum-ops`). RELEASES.md.

### Symptom

At the slot the update did not run. Refused: a check failed at the slot (worktree or image drift, tag or registry digest moved, new `.env` keys, managed files changed, signature, pre-update backup, lock; the reason is in the mail and in `--status`). Missed: the host was off or the watch noticed the slot had passed more than 15 minutes ago; a missed slot is never run afterwards. Nothing was installed and the site notice, if any, was withdrawn.

### Diagnosis

`sudo manuspectrum-update --status` shows the outcome and the reason; `journalctl -u manuspectrum-update-at -e` the pre-check output.

### Remediation

The reasons are those of the engine: `drift`, `unarmed`, `tag_moved`, `env_keys`, `managed_sources`, `verify`, `backup`, `lock`, `busy` (an update in flight, or Ansible running on the host), `fetch` (git or the signature services unreachable) and `late` (the slot started, or the backup ended, after the window closed: the pre-update backup may have taken the window; a `late` slot is recorded as `missed`, whoever noticed it, and mailed as `scheduled update of <tag> missed (past its window)`). The log of the slot is `journalctl -u manuspectrum-update@<tag>`.

Fix the reason if there is one, acknowledge the failed slot with `sudo manuspectrum-update --cancel` (the alert clears on the next watch run), then schedule a new slot or install at once.

### Escalation

The technical lead.
