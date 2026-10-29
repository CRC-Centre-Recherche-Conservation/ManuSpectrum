# Runbook: PostgreSQL and Redis

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## PostgresConnectionsHigh

Severity: warning. PostgreSQL connections are close to the limit.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

New connections will be refused; the site returns errors.

### Diagnosis

Connections by state and database in the PostgreSQL panel; idle-in-transaction sessions are the usual leak.

### Remediation

Restart the service that holds the connections. Raise `max_connections` only with the memory to match.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## RedisBrokerMemoryHigh

Severity: warning. The Celery broker memory is above 80 %.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

At the limit the broker refuses writes and tasks cannot be queued.

### Diagnosis

`redis_key_size{key="celery"}` for a backlog (`CeleryQueueBacklog`).

### Remediation

Let the worker drain the queue; purge only tasks you know are obsolete.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## RedisBrokerMemoryCritical

Severity: critical. The Celery broker memory is above 95 %.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The broker refuses writes; edits that queue indexing fail.

### Diagnosis

As for `RedisBrokerMemoryHigh`.

### Remediation

Drain the queue at once (worker health first); raise maxmemory if the load is legitimate.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
