# Runbook: Biblissima

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## BiblissimaBusy

Severity: warning. Biblissima calls are refused as busy.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Editors see partial results in the Biblissima import.

### Diagnosis

Dashboard Application, row Biblissima: in-flight calls, slot timeouts, outcomes by endpoint.

### Remediation

Wait; the slots are per process. A steady load calls for a higher `BIBLISSIMA_CONCURRENCY_LIMIT` per process (memory counted per process).

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## WriteBudgetSpent

Severity: warning. A Biblissima write ran out of time.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Some imported items are missing or incomplete.

### Diagnosis

Dashboard Application, row Biblissima: upstream latency and outcomes; the worker log names the item.

### Remediation

Retry the import of the missing items later. A slow upstream is not ours to fix; persistent slowness is raised with Biblissima.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
