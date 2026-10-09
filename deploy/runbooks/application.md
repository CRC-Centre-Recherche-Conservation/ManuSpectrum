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
