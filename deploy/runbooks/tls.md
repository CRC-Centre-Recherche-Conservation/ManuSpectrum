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

## CertificateInvalid

Severity: warning. The public site answers, but its certificate chain or host name does not verify against the system trust store. Expiry is covered by the two alerts above; this one is about trust. It is off when `PUBLIC_HOST` ends in `.test` (CI and rehearsal), and it also fires with `CERT_MODE=acme` against the Let's Encrypt staging authority.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Browsers show a certificate warning (self-signed, wrong name, unknown authority or incomplete chain) although the site is up.

### Diagnosis

`openssl s_client -connect <PUBLIC_HOST>:443 -servername <PUBLIC_HOST> </dev/null` from the host: read the verify return code and the chain. `make -C deploy status`; check `CERT_MODE` and `PUBLIC_HOST` in `.env`.

### Remediation

With `CERT_MODE=acme`, run `make -C deploy cert-renew` and check that the production authority (not staging) issued the certificate. With `CERT_MODE=local` on a real host, switch to `acme` or install the certificate chain and run `make -C deploy nginx-reload`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
