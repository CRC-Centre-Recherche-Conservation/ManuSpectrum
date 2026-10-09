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
