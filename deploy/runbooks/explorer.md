# Runbook: Explorer

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## ExplorerBundleBuildSlow

Severity: warning. The Explorer corpus rebuild is slow.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

Changes to the data reach the Explorer late; worker memory rises during rebuilds.

### Diagnosis

Dashboard Application, row Explorer: build duration, bundle size, rows. Logs of `manuspectrum.explorer` give the duration and the number of analyses of each build.

### Remediation

Accept the delay during a large import. Otherwise give the workers more memory or lower the number of gunicorn workers; the lasting answer is the incremental projection (issue #101).

### Escalation

The technical lead, then the project lead for the budget of the projection.

## ExplorerBundleBuildVerySlow

Severity: critical. The Explorer corpus rebuild is very slow.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

The Explorer shows stale data and workers risk running out of memory.

### Diagnosis

As for `ExplorerBundleBuildSlow`; check `ContainerMemoryNearLimit` and `WebMemoryNearLimit` at the same time.

### Remediation

Stop the import that causes it if any. Raise the memory limit of web and worker or reduce the workers, then plan the incremental projection (issue #101).

### Escalation

The technical lead, then the project lead for the budget of the projection.

## ExplorerRebuildFailing

Severity: warning. Background Explorer rebuilds fail.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The Explorer keeps serving the previous corpus; new data does not appear.

### Diagnosis

`make -C deploy logs` for the `manuspectrum.explorer` errors of web (a database timeout, a memory error).

### Remediation

Fix the error shown. A request that needs the build runs it in the request and shows the error to its reader.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ExplorerRebuildContinuous

Severity: info. The Explorer corpus is rebuilt all the time.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Nothing visible; the corpus is rebuilt as soon as a rebuild ends because the data keeps changing.

### Diagnosis

Dashboard Application, row Explorer. A bulk import or a loop writing to the data tables keeps the change ledger moving.

### Remediation

None needed during an import. If no import runs, find the writer in the logs.

### Escalation

Mentioned in the monthly report; the technical lead if it persists.

## DataChangeLedgerNotPruned

Severity: warning. The data change ledger is not pruned.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The ledger grows; the Explorer data version check slows down.

### Diagnosis

Check that beat and worker run (`make -C deploy status`) and the task `prune_data_changes` in the worker log.

### Remediation

Restart beat and worker. Run the prune task by hand through `make -C deploy manage`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
