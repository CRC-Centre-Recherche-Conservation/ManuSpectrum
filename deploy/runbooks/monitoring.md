# Runbook: The monitoring stack itself

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## TargetDown

Severity: warning. A scrape target is down.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Metrics and the alerts built on them are missing for this target.

### Diagnosis

`make -C deploy status` for the exporter; the Targets page of Prometheus through the SSH tunnel.

### Remediation

Restart the exporter (`make -C deploy observability-on`). A web or worker target down is also a site problem.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## HostMetricsStale

Severity: warning. Container metrics are stale.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Container alerts (restarts, memory, health) are blind.

### Diagnosis

`systemctl status manuspectrum-container-metrics` and its journal.

### Remediation

Restart the service. Check that the service account can run `docker inspect`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## DiskUsageStale

Severity: warning. Directory size metrics are stale.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

The directory sizes of the Disk and backups dashboard are old.

### Diagnosis

`systemctl status manuspectrum-disk-usage.timer` and the journal of its service. A `du` over the network filesystem that times out also leaves it stale.

### Remediation

Run the service by hand; restart the timer.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## TextfileError

Severity: warning. node_exporter cannot read a textfile.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Backup or host metrics are missing.

### Diagnosis

The node-exporter log (`make -C deploy logs`) names the file.

### Remediation

Fix or delete the file; the writing script rewrites it atomically at its next run.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## AlertmanagerNotificationsFailing

Severity: warning. Alert e-mails fail to send.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Alerts fire but nobody is told.

### Diagnosis

`make -C deploy logs` for the alertmanager line naming the SMTP error; check `EMAIL_HOST`, `EMAIL_PORT` and the sender in `.env`.

### Remediation

Fix the relay settings then `make -C deploy alert-recipients`. Ask the provider if the relay refuses the sender.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## PrometheusRuleFailures

Severity: warning. Prometheus fails to evaluate rules.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Some alerts are not evaluated.

### Diagnosis

The Rules page of Prometheus through the SSH tunnel shows the error.

### Remediation

Fix the rule (`observability/check.sh` finds syntax faults) and restart Prometheus.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## Watchdog

Severity: none. Heartbeat of the alert chain.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

None; a missing Monday e-mail means the chain is broken.

### Diagnosis

If the Monday e-mail does not arrive: `make -C deploy status`, then `AlertmanagerNotificationsFailing`.

### Remediation

Restore the broken link (Prometheus, Alertmanager, the relay).

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
