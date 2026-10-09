# Runbook: Host

Alerts of the monitoring stack that point here. Each section has the same five parts. Commands run on the host from the repository checkout, as the service account. How alerts reach people, and how to open Grafana, is in `deploy/OBSERVABILITY.md`.

## SwapInUse

Severity: warning. The host is swapping.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Everything slows down when memory is short.

### Diagnosis

Memory by container on the Infrastructure dashboard; `ContainerMemoryNearLimit` alerts.

### Remediation

Lower the memory of the largest consumer or move to a larger host.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## MemoryPressure

Severity: warning. Processes wait for memory.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Slow answers; the kernel reclaims memory or kills processes.

### Diagnosis

Infrastructure dashboard: memory, swap and the pressure panel. `dmesg` on the host for OOM kills.

### Remediation

Reduce the load, restart the largest container, or add memory.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ClockNotSynchronised

Severity: warning. The host clock is not synchronised.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Certificates, tokens and logs depend on the time.

### Diagnosis

`timedatectl status` on the host.

### Remediation

Restart the time service of the host (`systemctl restart systemd-timesyncd`); the provider's time source may be down.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## HostRebooted

Severity: info. The host rebooted.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

None; counted in the monthly report.

### Diagnosis

`uptime` and `journalctl -b -1 -e` on the host for an unexpected one.

### Remediation

None for the planned reboot. After an unexpected one, check that the stack came back (`make -C deploy status`).

### Escalation

Not routed to a person.

## RecentlyRebooted

Severity: none. The host booted less than 15 minutes ago.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

None.

### Diagnosis

Alertmanager inhibits every other alert while this one fires.

### Remediation

None.

### Escalation

None.
