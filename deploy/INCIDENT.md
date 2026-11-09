# Incident guide

A decision tree for the operator. Each branch ends in a command or in a runbook.
Commands run as the service account from the repository checkout, unless a line
says otherwise. Host values are `<placeholders>`.

Start here: what do you see?

| You see | Go to |
| --- | --- |
| The status page is red, or the site does not load | [Site unreachable](#site-unreachable) |
| The site loads but pages answer 500 | [Errors 500](#errors-500) |
| A disk alert, or writes fail | [Disk full](#disk-full) |
| A certificate alert, or browsers warn | [Certificate](#certificate) |
| A backup alert or mail | [Backup failure](#backup-failure) |
| An update mail says rolled back or failed | [Failed release](#failed-release) |
| Something looks like a break-in | [Suspected compromise](#suspected-compromise) |
| You plan an update or a restart | [Planned maintenance](#planned-maintenance) |

Every alert has a section named after it in the runbooks:

| File | Alerts about |
| --- | --- |
| [runbooks/site.md](runbooks/site.md) | `SiteDown`, `NotReady`, `CantaloupeDown`, `ErrorRateHigh`, search and write failures |
| [runbooks/application.md](runbooks/application.md) | `ErrorLogRateHigh`, `WebSaturated`, account mail, embargo and workflow passes |
| [runbooks/containers.md](runbooks/containers.md) | Restart loops, OOM kills, `ContainerUnhealthy`, `ContainerMissing` |
| [runbooks/datastores.md](runbooks/datastores.md) | PostgreSQL connections, Redis memory |
| [runbooks/celery.md](runbooks/celery.md) | Queue backlog, task failures, nightly passes |
| [runbooks/explorer.md](runbooks/explorer.md) | Explorer bundle builds |
| [runbooks/backup.md](runbooks/backup.md) | `BackupFailed`, `BackupMissing`, restore test |
| [runbooks/storage.md](runbooks/storage.md) | Disk usage, `NfsUnavailable` |
| [runbooks/tls.md](runbooks/tls.md) | Certificate expiry and trust |
| [runbooks/host.md](runbooks/host.md) | Swap, memory, clock, reboots |
| [runbooks/monitoring.md](runbooks/monitoring.md) | `TargetDown`, exporters, Alertmanager, `Watchdog` |
| [runbooks/release.md](runbooks/release.md) | Release watch and update |
| [runbooks/biblissima.md](runbooks/biblissima.md) | Biblissima proxy |

## Site unreachable

The external probe (Upptime, in the status-page repository) is red.

1. From your workstation: does the name resolve and answer?
   `curl -sI https://manuspectrum.huma-num.fr/ | head -1`. A certificate error
   goes to [Certificate](#certificate).
2. Can you reach the host (`ssh <account>@<host>`)? If not, the host or the
   network is down: open a ticket with the hosting provider (Huma-Num support)
   and say so on the status page. Nothing in this repository can help.
3. On the host: `make -C deploy status`. A container down or unhealthy:
   `make -C deploy up`, then `make -C deploy smoke`.
4. Still failing: `make -C deploy restart` (restarts `web`, `worker`, `beat`
   only), then `make -C deploy logs` for nginx and web.
5. The cause is not found, or it follows an update: [Failed release](#failed-release).
   The alert's own section: [runbooks/site.md](runbooks/site.md#sitedown).

A host reboot (04:50) explains a short red; `SiteDown` waits 15 minutes after one.

## Errors 500

1. `make -C deploy status`, then `make -C deploy logs`. Every response carries an
   `X-Request-ID` header; a user can give you the value, and it names every log
   line of that request (application, Celery tasks, nginx access log).
2. Find the line in the nginx access log (`NGINX_LOG_HOST_DIR`, JSON) or
   in `make -C deploy logs`, then read the web lines with the same id.
3. Grafana by SSH tunnel ([OBSERVABILITY.md](OBSERVABILITY.md#opening-grafana)):
   `ssh -L 3000:localhost:3000 <account>@<host>`, then `http://localhost:3000`;
   the error rate and saturation dashboards show whether it is one route or all.
4. One route: [runbooks/site.md](runbooks/site.md#errorratehigh) and
   [runbooks/application.md](runbooks/application.md#errorlogratehigh). All
   routes, or a resource limit: [runbooks/containers.md](runbooks/containers.md)
   and [runbooks/datastores.md](runbooks/datastores.md).
5. Right after an update: [Failed release](#failed-release).

## Disk full

1. `df -h / /data`. Never run `du` on the root of the network mount.
2. [runbooks/storage.md](runbooks/storage.md#diskalmostfull) (`DiskAlmostFull`,
   `DiskFillingUp`, `DiskUsageHigh`). For `/data`, stop the backup timers until
   there is room, then run `make -C deploy backup`.
3. `NfsUnavailable`: [runbooks/storage.md](runbooks/storage.md#nfsunavailable),
   then the hosting provider.

## Certificate

1. `echo | openssl s_client -connect <PUBLIC_HOST>:443 -servername <PUBLIC_HOST> 2>/dev/null | openssl x509 -noout -issuer -dates`
2. Expiring, or not renewed: `make -C deploy cert-renew`
   ([runbooks/tls.md](runbooks/tls.md#certificateexpiringsoon),
   [`CertificateExpiryCritical`](runbooks/tls.md#certificateexpirycritical)).
3. Untrusted (staging issuer, wrong name):
   [runbooks/tls.md](runbooks/tls.md#certificateinvalid).

## Backup failure

1. `journalctl -u manuspectrum-backup -e` and `make -C deploy backup`.
2. [runbooks/backup.md](runbooks/backup.md#backupfailed) and
   [BACKUP.md](BACKUP.md#when-things-go-wrong) (stale lock, full repository,
   wrong password).
3. A missing run: [`BackupMissing`](runbooks/backup.md#backupmissing); a restore
   that does not prove: [`RestoreTestFailed`](runbooks/backup.md#restoretestfailed).
4. Until a backup is saved, take no risky action on the data.

## Failed release

The update rolls back by itself when the new version does not become ready.

1. `ssh <account>@<host> sudo manuspectrum-update --status`, then
   `journalctl -u 'manuspectrum-update@*' -e`.
2. Rolled back (exit 3, mail `rolled back`): the site runs the previous version.
   [ADMIN.md](ADMIN.md#after-a-rollback),
   [runbooks/release.md](runbooks/release.md#updaterolledback).
3. Rollback failed (exit 4, mail `ROLLBACK FAILED`): the site may be down.
   [ADMIN.md](ADMIN.md#after-a-failed-rollback),
   [runbooks/release.md](runbooks/release.md#updaterollbackfailed). Ask the
   technical lead before restoring a backup: it replaces the database.
4. Interrupted (exit 5, or an `inflight` line with no unit running):
   [runbooks/release.md](runbooks/release.md#updateinterrupted).
5. Refused because Ansible must run first:
   [ADMIN.md](ADMIN.md#when-the-update-refuses-because-ansible-must-run-first).
6. Release not verified: [runbooks/release.md](runbooks/release.md#releaseverificationfailed).

## Suspected compromise

Examples: an unknown administrator or login, files or containers you did not
create, a leaked secret, a mail you did not send. Do not fix first; keep the
evidence first.

1. **Preserve evidence before changing anything.**
   - Ask the hosting provider for a snapshot of the VM, if it offers one.
   - Copy the logs off the live paths: the nginx access and error logs
     (`NGINX_LOG_HOST_DIR`), `make -C deploy logs` redirected to a file, and as
     administrator `sudo journalctl --since "7 days ago" > <file>` and the
     authentication log.
   - `make -C deploy backup TAG=manual` keeps the database as it is.
   - Note the time, what you saw and each command you run.
2. **Cut access, with what exists.**
   - Stop the site: `make -C deploy down` (volumes are kept). nginx then
     serves its own error page.
   - Block a source or a port at the host firewall with `sudo ufw`; ask the
     hosting provider to isolate the VM if you cannot reach it.
   - Deactivate an application account: untick « Active » in the User admin
     ([ADMIN.md](ADMIN.md#inactive-accounts)). Remove an operator: take the
     account out of `release_operators` and `admin_users` and run the playbook
     ([ADMIN.md](ADMIN.md#who-can-run-it)).
3. **Rotate the secrets** that may have been exposed, or all of them if host or
   vault access was involved ([SECRETS.md](SECRETS.md#7-when-to-rotate), procedure
   per secret in [section 6](SECRETS.md#6-rotation)). A new `django_secret_key`
   signs everyone out and clears the two-factor secrets, as that section says.
4. **Notify.**
   - The CNRS data protection officer (DPD) **within 72 hours** of becoming aware
     of the breach when personal data may be involved (GDPR, article 33): accounts,
     e-mail addresses, login records
     ([ADMIN.md](ADMIN.md#privacy-policy)). Say what you know and what you do not.
   - The hosting provider.
   - The project owner and the technical lead.
5. **Rebuild or restore** only when the cause is understood: [DEPLOY.md](DEPLOY.md)
   and [BACKUP.md](BACKUP.md#restore-the-stack).

## Planned maintenance

Before a planned update or restart:

1. Open an issue labelled `maintenance` in the status-page repository: the status
   page shows it as a planned maintenance instead of an outage. Give the start and
   the expected end.
2. Announce it on the site: `make -C deploy site-notice ARGS="plan --start <ISO> --end <ISO>"`
   ([README.md](README.md#commands)).
3. Silence the alerts that will fire:
   `make -C deploy silence ARGS='alertname=<alert> --duration=2h --comment="why"'`.
4. Run the update ([ADMIN.md](ADMIN.md#updating-the-application)), avoiding 03:50
   to 05:05.
5. When it is over, close the issue.

## After an incident

1. Write down what happened: timeline, cause, what fixed it, what was not
   understood. Keep that note with the administrators (the vault collection or the
   project's private space), not in the repository.
2. Open a GitHub issue for each fix or follow-up. Describe the defect and the
   change, never host addresses, accounts, secrets, log extracts or personal data:
   the repository is public.
3. Check that alerts and runbooks would have caught it; fix the runbook section
   that misled you.
4. Close the `maintenance` issue and tell the status page's readers when service
   is back.
