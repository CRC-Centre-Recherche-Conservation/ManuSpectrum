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

SSH access to the host as an account with sudo. The host keeps its time with chrony (Ubuntu's default), not systemd-timesyncd.

### Symptom

Certificates, two-factor codes, tokens, scheduled passes and logs depend on the time. The kernel has reported the clock as unsynchronised for 30 minutes.

### Diagnosis

- `systemctl is-active chrony systemd-timesyncd` → `active` then `inactive`: the rest of this section is for chrony; a host that kept systemd-timesyncd needs chrony installed (`sudo apt install chrony` replaces it).
- `timedatectl` → `System clock synchronized: no`, `NTP service: active`.
- `chronyc tracking` → `Leap status : Not synchronised` (synchronised reads `Normal`, with a `Reference ID` naming the server).
- `chronyc sources -v` → every source `^?` with `Reach` 0: no time server answered.
- `journalctl -u chrony --since -2h` → lines `NTS-KE session with ... timed out` (or `Connection reset`).
- Ubuntu's default sources (`/etc/chrony/sources.d/ubuntu-ntp-pools.sources`) use NTS: a TLS key exchange on TCP 4460 before any NTP packet. Some networks cut that handshake. List the NTS hosts with `grep -h '^\(pool\|server\).* nts' /etc/chrony/sources.d/*.sources`, then test each one: `openssl s_client -connect <host>:4460 -alpn ntske/1 </dev/null` must print `ALPN protocol: ntske/1`; no answer, a timeout or `errno=104` means NTS is blocked on this network, and chrony never syncs while these are its only sources.
- `sudo chronyc -N authdata` shows the NTS sources with no cookies (`Cook` 0) in that case.
- A plain NTP server (UDP 123) of the hosting provider or the institution can be tested without touching the clock: `sudo chronyd -Q -t 20 'server ntp.example.org iburst'` (replace `ntp.example.org` with the server they document) prints the offset it measured.

### Remediation

- NTS blocked: add the plain NTP server in a drop-in, then reload the sources:
  `printf 'server ntp.example.org iburst\n' | sudo tee /etc/chrony/sources.d/local-ntp.sources` (the documented server instead of `ntp.example.org`), then `sudo chronyc reload sources`. To silence the NTS timeouts as well, rename Ubuntu's file so it no longer ends in `.sources` (`sudo mv /etc/chrony/sources.d/ubuntu-ntp-pools.sources{,.disabled}`) and reload again. Within a few minutes `chronyc sources -v` shows `^*` on the server and `chronyc tracking` reads `Normal`; the alert resolves after the next scrapes.
- Sources reachable but the clock still unsynchronised: `sudo systemctl restart chrony`; with a large offset `sudo chronyc makestep` steps the clock once.
- Record the drop-in in the host notes: a reinstalled host needs it again.

### Escalation

The technical lead. If neither NTS nor a documented NTP server is reachable, open a ticket with the hosting provider for an NTP server or for TCP 4460.

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
