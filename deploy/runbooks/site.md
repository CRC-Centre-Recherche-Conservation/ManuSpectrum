# Runbook: Site and application errors

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## SiteDown

Severity: critical. The public site does not answer.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel (see OBSERVABILITY.md).

### Symptom

Visitors get an error or nothing. The alert does not fire during the 15 minutes that follow a host reboot (the 04:50 reboot).

### Diagnosis

`make -C deploy status` shows which container is down or unhealthy. `make -C deploy logs` for nginx and web. `curl -sk https://localhost/healthz` from the host separates nginx and the network from the application. A certificate failure shows in the `CertificateExpiringSoon` and `CertificateExpiryCritical` alerts.

### Remediation

Start what is down with `make -C deploy up`. After a bad update, roll back to the previous image (README, update section). A full disk is the usual hidden cause: see `DiskAlmostFull`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## NotReady

Severity: critical. The application reports it is not ready.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

The site may answer /healthz but one dependency (PostgreSQL, Elasticsearch, Celery broker, a Redis, Cantaloupe) does not. Searches or logins fail.

### Diagnosis

In Grafana (or Prometheus), query `manuspectrum_readyz_component_up == 0` to name the component. `make -C deploy status` for the container, `make -C deploy logs` for its last lines.

### Remediation

Restart the failing dependency with `docker compose` through `make -C deploy up`. Elasticsearch red or unassigned shards: see the datastores runbook and the production README. A dependency that is up but unreachable points to the Compose network.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## CantaloupeDown

Severity: critical. The IIIF image server does not answer.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Manuscript images and thumbnails do not load; the rest of the site works.

### Diagnosis

`make -C deploy status` for the cantaloupe container, `make -C deploy logs` for its Java errors (out of memory, unreadable source).

### Remediation

Restart it with `make -C deploy up`. An out-of-memory kill also shows in `ContainerOOMKilled`. If the source images come from the network filesystem, check `NfsUnavailable`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ErrorRateHigh

Severity: critical. More than 1 % of the requests fail with a 5xx.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

Visitors or editors meet error pages.

### Diagnosis

The Application dashboard shows the failing views (`view` label). `make -C deploy logs` for the tracebacks of web; each log line carries a request id. A dependency problem shows as `NotReady`.

### Remediation

Fix or roll back the change that introduced the error. A saturated service shows in `WebSaturated`. A database or Elasticsearch outage: see the datastores runbook.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## SearchLatencyHigh

Severity: warning. The Explorer search is slow.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel.

### Symptom

The Explorer takes seconds to answer a search.

### Diagnosis

Check `ExplorerBundleBuildSlow` (a rebuild of the corpus bundle), the CPU and memory panels of the Infrastructure dashboard, and PostgreSQL activity (`pg_stat_activity_count`).

### Remediation

Wait for a running rebuild to end. A host short of memory: see `MemoryPressure`. A slow query: read the top statements by `queryid` in the PostgreSQL panel.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## WriteRequestsFailing

Severity: warning. At least three write requests (POST, PUT or DELETE) answered a server error in the last 30 minutes. Severity is warning on purpose: the site is up and the failures are few, which `ErrorRateHigh` (critical) does not see; a curator's input may be lost, so it is read the same working day.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. Grafana through the SSH tunnel (dashboard Activity, panel "Failing writes (5xx) by view").

### Symptom

A curator reports that a save, an import step or a deletion failed with an error page, or no one has noticed yet.

### Diagnosis

The panel "Failing writes (5xx) by view" gives the `view` of the failing requests (`tile`, `plugins`, `workflow_history`, `biblissima-create-resource`, ...). Read the web log for that period (`make -C deploy logs`, lines at ERROR with the request id). A database, Elasticsearch or Redis outage shows in `NotReady` or in the datastore alerts. A series seen for the first time counts from its second sample, so the first error on a view that never failed before may not raise this alert; the panel still shows it.

### Remediation

Fix the cause the log names. Tell the curators whose save failed to repeat it and check the record afterwards: a write that died halfway can leave a resource without its cards.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
