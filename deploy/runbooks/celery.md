# Runbook: Celery and indexing

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## CeleryQueueBacklog

Severity: warning. The Celery queue is backing up.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Indexing and background tasks run late; search results lag behind edits.

### Diagnosis

`make -C deploy status` for worker and beat; `make -C deploy logs` for the worker. The Celery row of the Application dashboard shows the task outcomes.

### Remediation

Restart the worker with `make -C deploy restart`. A task that keeps failing blocks the others: see `CeleryTaskFailures`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## CeleryTaskFailures

Severity: warning. A Celery task fails.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

A background job does not complete.

### Diagnosis

`make -C deploy logs` and search the worker log for the task name.

### Remediation

Fix the cause; the task can be run again from the application or `make -C deploy manage`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## IndexingFailures

Severity: warning. Search indexing fails.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Edited resources do not appear in the search.

### Diagnosis

Elasticsearch health (`NotReady` shows it), the worker log for the indexing error.

### Remediation

Fix Elasticsearch, then re-index the affected resources with `make -C deploy manage ARGS="es reindex_database"`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ActiveAccountsStale

Severity: warning. The active accounts count is more than two days old.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The monthly report flags the active accounts figure as out of date; the dashboard panel stays flat.

### Diagnosis

The `beat` container is running (`ContainerMissing` shows it) and its log lists `record-active-accounts` once a day; the worker log shows `manuspectrum.record_active_accounts` succeeding. `CeleryTaskFailures` fires when the task itself fails.

### Remediation

Restart the application containers (`make -C deploy restart`); the worker also refreshes the count when it starts.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ActivityStale

Severity: warning. The activity gauges (resources per model, changes of the last 24 hours, open workflows) are more than three hours old.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The panels of the Contents and Workflows rows of the dashboard Activity stay flat.

### Diagnosis

The `beat` container is running (`ContainerMissing` shows it) and its log lists `record-activity` every hour; the worker log shows `manuspectrum.record_activity` succeeding. `CeleryTaskFailures` fires when the task itself fails.

### Remediation

Restart the application containers (`make -C deploy restart`); the worker also refreshes the gauges when it starts.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## LoginRecordsPruneStale

Severity: warning. The login records have not been pruned for more than three days.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The Django admin still lists login records older than six months; the monthly report flags the prune as out of date.

### Diagnosis

`make -C deploy status` for worker and beat; `make -C deploy logs` for the task `manuspectrum.prune_login_records`. The Celery row of the Application dashboard shows its outcomes.

### Remediation

Restart the worker and beat (`make -C deploy restart`). To prune by hand, run `axes_reset_logs --age 183` and `axes_reset_failure_logs --age 183` through `make -C deploy manage`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## EmbargoPassStale

Severity: warning. The daily embargo pass has not completed for more than two days: restrictions are neither recorded, announced nor lifted.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

No notice or "now public" mail went out; the Embargoes panel of the Activity dashboard stays flat.

### Diagnosis

`make -C deploy status` for worker and beat; `make -C deploy logs` for the task `manuspectrum.embargo_pass` (scheduled at 06:00 Europe/Paris, entry `embargo-pass`). A pass that finds another one holding the lock does nothing and does not stamp its time: a lock left by a killed worker expires after 30 minutes. `CeleryTaskFailures` fires when the task itself fails.

### Remediation

Restart the application containers (`make -C deploy restart`), then run the pass by hand: `make -C deploy manage ARGS="release_expired_embargoes"` lists what it would do, and `--apply` does it. The pass is idempotent: notices go once per stage and a lift happens once.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
