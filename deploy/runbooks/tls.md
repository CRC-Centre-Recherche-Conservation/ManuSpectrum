# Runbook: TLS certificate

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## CertificateExpiringSoon

Severity: warning. The TLS certificate expires within 14 days.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Browsers will refuse the site when it expires.

### Diagnosis

`make -C deploy status`; the renewal timer and `make -C deploy cert-renew` output (CERT_MODE=acme).

### Remediation

Run `make -C deploy cert-renew`; check that port 80 reaches the ACME challenge.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## CertificateExpiryCritical

Severity: critical. The TLS certificate expires within 3 days.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Browsers will refuse the site within days.

### Diagnosis

As for `CertificateExpiringSoon`.

### Remediation

Renew now (`make -C deploy cert-renew`), or install a certificate by hand and run `make -C deploy nginx-reload`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
