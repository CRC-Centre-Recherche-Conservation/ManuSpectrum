# Runbook: Containers

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## ContainerRestartLoop

Severity: warning. A container restarts in a loop.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The service flaps; requests to it fail intermittently.

### Diagnosis

`make -C deploy status`, then `make -C deploy logs` for the service. `docker inspect` shows the exit code (137 is an out-of-memory kill).

### Remediation

Fix the configuration or the dependency the service waits for. An out-of-memory kill: see `ContainerOOMKilled`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ContainerOOMKilled

Severity: warning. A container was killed for lack of memory.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The service restarted; requests in flight failed.

### Diagnosis

The memory panel of the Infrastructure dashboard before the kill. The limit is in `compose.prod.yaml`.

### Remediation

Find what grew (an Explorer rebuild, a large export). Raise the limit within the host budget or lower the load.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ContainerMemoryNearLimit

Severity: warning. A container is close to its memory limit.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

An out-of-memory kill may follow.

### Diagnosis

The memory panel of the Infrastructure dashboard; the working set excludes reclaimable cache.

### Remediation

Lower the load or raise the limit within the host budget.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## WebMemoryNearLimit

Severity: warning. The web container is close to its memory limit.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

An out-of-memory kill restarts every request in flight.

### Diagnosis

The memory panel and the Explorer bundle size (`manuspectrum_explorer_bundle_bytes`).

### Remediation

Reduce the number of gunicorn workers or raise the limit within the host budget.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ContainerUnhealthy

Severity: warning. A container is unhealthy.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The service runs but does not answer its check.

### Diagnosis

`make -C deploy status` and `make -C deploy logs` for the service.

### Remediation

Restart it; fix the dependency its check reaches.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ContainerMissing

Severity: warning. A core container is not running.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

A core service is stopped or absent.

### Diagnosis

`make -C deploy status` lists what runs; the alert `HostMetricsStale` means the collector itself is down.

### Remediation

Start the stack with `make -C deploy up`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
