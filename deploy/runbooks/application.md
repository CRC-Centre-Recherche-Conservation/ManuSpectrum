# Runbook: Web application

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## ErrorLogRateHigh

Severity: warning. The application logs errors steadily.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

No visible failure yet, but the logs carry more than three errors a minute.

### Diagnosis

`make -C deploy logs` and filter on level error; the `source` label of `manuspectrum_log_records_total` says django, arches, manuspectrum or celery.

### Remediation

Fix the cause shown in the log. An outbound service failing (Biblissima, IIIF manifests) is logged here without being a site fault.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## WebSaturated

Severity: warning. The web server has almost no free thread.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

Pages queue; long downloads (exports, series files) keep threads busy.

### Diagnosis

The Application dashboard shows in-flight requests by time; the views with the highest latency are the likely holders. A streamed export counts until its last byte.

### Remediation

Wait for the long requests to end. If it repeats, raise the number of workers or threads in the gunicorn configuration (memory limits first: see `WebMemoryNearLimit`).

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## MetricsDirFilling

Severity: warning. The multiprocess metrics directory is filling.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

When the directory is full, metrics stop being recorded and scrapes fail.

### Diagnosis

Gauge files of dead processes accumulate when workers are recycled without cleanup. The panel history shows whether the growth is steady.

### Remediation

Restart the service (`make -C deploy restart`): the directory is emptied at start.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## LoginLockouts

Severity: warning. More than five accounts were locked in one hour after repeated sign-in failures (five failures lock one account from one address for 15 minutes).

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Django admin access for the lock records.

### Symptom

Users report they cannot sign in, or the Application dashboard shows a burst of failed logins.

### Diagnosis

The login outcomes panel of the Application dashboard shows the failures. In the Django admin, "Access failure logs" lists the failures with their address and `locked_out` flag; "Access attempts" lists the locks in force. A few addresses with many accounts is a guessing attempt; many addresses on one account is a targeted one; one address on one account is usually a user who forgot the password.

### Remediation

A real user is unlocked by waiting 15 minutes, or by an administrator who deletes the row in "Access attempts". For an attack, the same password is not sufficient: locks hold. Block the address at the edge if it persists, and tell users of a targeted account to change their password.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## AccountMailFailures

Severity: warning. A notice or invitation mail could not be handed to the mail relay in the last 64 hours: an embargo or workflow notice, an account invitation, an account anonymisation notice or its summary, or a password reset. The pass that sent it carried on, so the person may not have been warned.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The alert names the mail `kind`. Users say they received no invitation or no reset link.

### Diagnosis

The web and worker logs hold one `Account mail <kind> failed: <ExceptionClass>` line per failure, with no address. `ExceptionClass` tells the cause: `SMTPAuthenticationError` (wrong relay password), `SMTPSenderRefused` (sender not accepted: check `DEFAULT_FROM_EMAIL`), `SMTPRecipientsRefused` (one address refused), `ConnectionRefusedError` or `TimeoutError` (relay unreachable). Check `EMAIL_HOST`, `EMAIL_PORT` and the relay secret in the host `.env`.

### Remediation

Fix the relay settings and restart the service (`make -C deploy restart`). Notices are sent once per stage: a failed one is not repeated by the next pass, so tell the people concerned by hand (the administrators' copy shows what was due) and, for an invitation, send a new one.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## EmbargoLiftFailures

Severity: warning. A restriction past its end date could not be lifted in the last 64 hours (`failed`), or was lifted but the data are still hidden (`incomplete`). No mail goes to the depositor in either case: this alert is the administrators' notice.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Django admin access.

### Symptom

Data the depositor expected to be public are still hidden after the day following the end date.

### Diagnosis

The Django admin "Embargoes" list shows the record and its events: `Lift incomplete` means the grants of the visitor were removed but the resource is still not visible to everyone. The usual causes are a hidden Project above an Analysis (lift or release the Project first), or a restriction held by a group or a default permission the pass does not remove. `failed` means an exception: the web and worker logs carry one error line from `manuspectrum.accounts.embargo` with the traceback (database, permission framework or search index).

### Remediation

Fix the cause, then run `make -C deploy manage ARGS="release_expired_embargoes --apply"`: a failed record is retried by every pass. For an incomplete lift, remove the remaining restriction in the resource's permissions in Arches.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## EmbargoOverdue

Severity: warning. At least one restriction has been past its end date for more than two hours and is still in force. The pass runs at 06:00 Europe/Paris, so this should clear on the next morning; if it does not, the lift is failing.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Django admin access.

### Symptom

The "overdue" series of the Embargoes panel is above zero.

### Diagnosis

Check `EmbargoLiftFailures` and `EmbargoPassStale` first. In the Django admin "Embargoes" list, filter on the state "Active" and sort by end date.

### Remediation

If the restriction must last longer, extend the end date in the admin (it restarts the notices). Otherwise follow `EmbargoLiftFailures`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## WorkflowCleanupFailures

Severity: warning. The cleanup of an abandoned workflow run failed at least once in the last 64 hours. The run keeps its drafts and its history row and the next daily pass retries it; its creators were warned but nothing was deleted.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Django admin access.

### Symptom

The alert names the workflow `kind`. The worker logs hold an error line from `manuspectrum.accounts.workflows` ("Workflow cleanup failed") with the traceback.

### Diagnosis

The traceback tells the cause: a database error (the run is cleaned in one transaction, so nothing is half-deleted), or an error from the permission or search layer raised by Arches' `Resource.delete`. A failed run is rolled back; its resources are indexed again afterwards. In the Django admin "Workflow cleanups", the run has no "Cleaned on" date. `make -C deploy manage ARGS="prune_workflow_history"` lists, for runs due, what would be deleted and kept without touching anything.

### Remediation

Fix the cause, then run `make -C deploy manage ARGS="prune_workflow_history --apply --workflow <id>"`. Do not delete the run's history row by hand: the cleanup is what removes the drafts it created.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## AccountRetentionFailures

Severity: warning. The anonymisation of an account without sign-in failed at least once in the last 64 hours. The account is rolled back whole (one transaction per account): nothing is half-erased, and the next daily pass retries it.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The worker logs hold an error line from `manuspectrum.accounts.retention` ("Account retention failed") with the traceback. The administrators' summary counts fewer accounts than the notices announced.

### Diagnosis

The traceback tells the cause, usually a database error on one of the tables the anonymisation touches (user, profile, sessions, sign-in records, `edit_log`). `make -C deploy manage ARGS="anonymise_inactive_accounts"` lists, by user id, the accounts it would notice or anonymise, without touching anything.

### Remediation

Fix the cause, then run `make -C deploy manage ARGS="anonymise_inactive_accounts --apply"`. Do not rename or empty the account by hand: the pass erases the e-mail in the edit history in the same transaction, and a hand-edited account would leave it behind.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
