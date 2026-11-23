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

The alert reads the memory the kernel cannot drop (`anon` plus `shmem` of the cgroup's `memory.stat`), not the working set: the working set also counts the active page cache, which the kernel drops when the container reaches its limit, so an image server such as Cantaloupe sits near 100 % of it without any risk. A container whose `memory.stat` the collector cannot read falls back on the working set.

The memory panels of the Infrastructure dashboard show both series. On the host, as the service account (`<service>` is the Compose service, for example `cantaloupe`):

```bash
CID=$(docker ps -qf label=com.docker.compose.service=<service>)
CG=/sys/fs/cgroup/system.slice/docker-$(docker inspect -f '{{.Id}}' $CID).scope   # cgroupfs driver: /sys/fs/cgroup/docker/<id>
cat $CG/memory.events
grep -E '^(anon|shmem|file|active_file|inactive_file|kernel) ' $CG/memory.stat | awk '{printf "%-14s %6.0f MiB\n",$1,$2/1048576}'
```

`oom_kill` above 0 means a kill already happened (`ContainerOOMKilled`). A high `max` with `oom_kill 0` only says the kernel reclaimed page cache at the limit.

### Remediation

Lower the load or raise the limit within the host budget. For a Java service (Cantaloupe, Elasticsearch) the heap is fixed by `-Xmx`; what grows past it is off-heap (metaspace, threads, direct buffers, native decoders), which `-XX:MaxDirectMemorySize` and `-XX:MaxMetaspaceSize` bound.

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

## ContainerSwapAllowed

Severity: warning. A container may swap: the kernel limit `memory.swap.max` is not `0`.

### Prerequisites

SSH access to the host as the service account, from the repository checkout. For the remediation, an admin account with sudo on the host and a laptop checkout at the running tag (`git switch --detach vX.Y.Z`).

### Symptom

None at first. Under memory pressure the kernel moves the pages of the container to swap instead of only dropping page cache, and a Java service (Cantaloupe, Elasticsearch) slows down. `ContainerSwapping` follows once pages have moved.

### Diagnosis

`memswap_limit` in `compose.prod.yaml` makes Docker write `0` to the cgroup file, but runc does not hand that value to systemd: the container's scope unit keeps `MemorySwapMax=infinity`, and the next `systemctl daemon-reload` (an apt upgrade, Ansible) writes `max` back. The host role installs a drop-in that gives every `docker-<id>.scope` `MemorySwapMax=0`. On the host (`<service>` is the Compose service):

```bash
CID=$(docker inspect -f '{{.Id}}' "$(docker ps -qf label=com.docker.compose.service=<service>)")
cat /sys/fs/cgroup/system.slice/docker-$CID.scope/memory.swap.max      # expected: 0
systemctl show docker-$CID.scope -p MemorySwapMax                      # expected: MemorySwapMax=0
systemctl cat docker-$CID.scope                                        # lists 10-manuspectrum-no-swap.conf
ls -l /etc/systemd/system/docker-.scope.d/
```

A missing `10-manuspectrum-no-swap.conf`, or a later file that sets another `MemorySwapMax` (a container started with a swap allowance writes its own `50-MemorySwapMax.conf`), explains the alert.

### Remediation

Re-run the Ansible host role from the laptop checkout at the running tag (`ansible-playbook -i inventories/<host> site.yml --tags host --ask-become-pass`, see `deploy/ansible/README.md`): it restores the drop-in and reloads systemd, which applies the value to the running containers without restarting Docker. Check the three commands above again. Pages already in swap stay there: see `ContainerSwapping`.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## ContainerSwapping

Severity: warning. A container holds memory in swap.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

Slower responses of the container; `SwapInUse` fires when the amount is large.

### Diagnosis

The alert reads `memory.swap.current` of the container. On the host:

```bash
for d in /sys/fs/cgroup/system.slice/docker-*.scope; do
  id=$(basename "$d" .scope); id=${id#docker-}
  printf '%s %s\n' "$(docker inspect -f '{{.Name}}' "$id")" "$(( $(cat "$d/memory.swap.current") / 1048576 )) MiB"
done
```

Check that the limit now holds (`ContainerSwapAllowed`, `memory.swap.max` must be `0`).

### Remediation

Once the limit holds, nothing moves new pages to swap, but the old ones stay there until the container restarts. Restart it off-peak to bring them back (`docker restart "$(docker ps -qf label=com.docker.compose.service=<service>)"`). If the limit does not hold, fix that first, or the pages return to swap.

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

`make -C deploy silence-fresh-install` also silences this alert for 48 hours. A container that disappears during that window raises no alert: check `make -C deploy status` meanwhile.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.

## OomSourceDegraded

Severity: warning. The OOM kill counter of a container is read from Docker's `OOMKilled` flag instead of the cgroup v2 `memory.events` file.

### Prerequisites

SSH access to the host as the service account, from the repository checkout.

### Symptom

`ContainerOOMKilled` and the OOM panels may miss kills: Docker resets the flag when a container restarts, and a killed child process never sets it for a running container.

### Diagnosis

`ls /sys/fs/cgroup/system.slice/docker-<container id>.scope/memory.events` as the service account; `stat -fc %T /sys/fs/cgroup` should print `cgroup2fs`. Run `make -C deploy container-metrics` and read its log lines.

### Remediation

Restore read access to the cgroup files (cgroup v2 hierarchy, systemd cgroup driver) or fix the path the collector reads, then run `make -C deploy container-metrics` and check `manuspectrum_container_oom_cgroup` is 1.

### Escalation

The technical lead. If the cause is the host, the network filesystem or the mail relay, open a ticket with the hosting provider.
