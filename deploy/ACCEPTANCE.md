# Production platform acceptance

Step-by-step procedure to check that each piece of the deployment works, on the
rehearsal VM first, then in production. Each check gives the command, the expected
result and what to do if it fails. One section per step; each PR of the
workstream adds its own.

This repository is public: this page contains no production-specific value.
Those values (resources, accounts, NFS options, SSH settings...) go in
`deploy/rehearsal/rehearsal.env`, a local file ignored by Git
(`cp deploy/rehearsal/rehearsal.env.example deploy/rehearsal/rehearsal.env`).

## How to read and record

- **Roles**, used in every step:
  - **host** = the Linux workstation running libvirt, where the repository is cloned;
  - **rehearsal VM** = the VM the kit creates (`ssh <admin>@192.168.123.10`);
  - **production VM** = the target server (compared against only, never modified by
    this procedure).
- A ticked box = the command was run and the result matches **exactly**.
  A different result is recorded with the full output of the command.
- All `virsh` commands target `qemu:///system`:
  `export LIBVIRT_DEFAULT_URI=qemu:///system` once per terminal.
- On failure, nothing is fixed by hand in the VM: note it, fix the kit, then
  go back to the snapshot and replay. An unwritten manual step is exactly what
  will be missing on moving day.

## Prerequisites

Anyone with (a) a Linux host with KVM/libvirt and (b) a clone of the repository
(`git clone https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum.git`)
can follow this page. No other machine is needed.

- Supported host OS families: Debian/Ubuntu and Fedora.
- Packages: see `deploy/rehearsal/README.md`, section 1.
- CPU virtualization enabled: `egrep -c '(vmx|svm)' /proc/cpuinfo` → greater than 0
  (or `kvm-ok` reports that KVM acceleration can be used).
- libvirt group: `sudo usermod -aG libvirt $USER`, then log in again.
- Disk space: reserve `DISK_GB` from `rehearsal.env` under `/var/lib/libvirt/images/`
  (qcow2 is thin-provisioned, but the space must exist).

---

## Step 1 — The rehearsal kit (`deploy/rehearsal/`)

Detailed build procedure: `deploy/rehearsal/README.md`. Here, the checks.

### 1.1 The kit is sound (host or CI)

- [ ] `bash deploy/rehearsal/check.sh` (the CI runs it on every pull request)
  - Expected: last line `check.sh: all green.` (a `skip` is acceptable
    only for a missing `xmllint`).
  - On failure: the output names the tool (shellcheck, tests, schema, gitleaks); do not
    run `make-vm.sh` until it is green.

### 1.2 The host is ready

- [ ] `virsh uri` → `qemu:///system`.
  Otherwise: `sudo usermod -aG libvirt $USER`, log out, log back in.
- [ ] `free -g`: free memory exceeds `RAM_MB` from `rehearsal.env` by at least 4 GB
  (otherwise free enough memory on the host: `RAM_MB` + 4 GB).
- [ ] `grep -c . deploy/rehearsal/rehearsal.env`: the file exists and contains the
  production values (re-read each line against the production VM sheet).
- [ ] The ISO and `SHA256SUMS` are in `/var/lib/libvirt/images/`:
  `cd /var/lib/libvirt/images && sha256sum --ignore-missing -c SHA256SUMS`
  → `ubuntu-26.04.1-live-server-amd64.iso: OK`.

### 1.3 Network and NFS (host)

- [ ] `sudo deploy/rehearsal/host-network.sh` then `virsh net-list --name` → contains
  `ms-rehearsal`; `virsh net-list --name` still contains `default`.
- [ ] Re-run `sudo deploy/rehearsal/host-network.sh` → message "already done", nothing changes.
- [ ] `sudo deploy/rehearsal/host-nfs.sh` then `sudo exportfs -v` → one line
  `/srv/ms-rehearsal-data 192.168.123.10/32(...)` with the options from `rehearsal.env`.
- [ ] Re-run `sudo deploy/rehearsal/host-nfs.sh` → "already done".

### 1.4 Automatic installation (host)

- [ ] `DRY_RUN=1 ISO=/var/lib/libvirt/images/ubuntu-26.04.1-live-server-amd64.iso deploy/rehearsal/make-vm.sh`
  → prints the `virt-install` command and the XML guard passes (no `firmware='efi'`).
- [ ] `ISO=… deploy/rehearsal/make-vm.sh` (10 to 15 min, asks for the admin password twice).
  - Expected: ends without error, with a message giving the next steps;
    `virsh snapshot-list ms-rehearsal` lists `installed`.
  - If it hangs: `virsh console ms-rehearsal` shows the installer; note the
    last message displayed.
- [ ] `ls /var/lib/libvirt/images/ | grep -c seed` → `0` (the seed, which contains the
  password hash, was indeed deleted).

### 1.5 The VM has the shape of production (rehearsal VM)

`ssh <admin>@192.168.123.10`, then:

- [ ] `nproc` → `VCPUS`; `free -g` → about `RAM_MB`; `swapon --show` → the `vg0-swap` volume.
- [ ] `lsblk` → `/boot` on partition 1 (2 G); `vg0-root` of size `ROOT_LV_SIZE` on `/`.
- [ ] `[ -d /sys/firmware/efi ] && echo UEFI || echo BIOS` → `BIOS`.
- [ ] `localectl status` → the `LOCALE` locale and the `KEYBOARD` keyboard from `rehearsal.env`.
- [ ] `cloud-init status` → `status: done`.

### 1.6 Host baseline (rehearsal VM)

- [ ] Copy and run, from the host:
  `scp deploy/rehearsal/{host-baseline.sh,verify-baseline.sh,rehearsal.env} <admin>@192.168.123.10:`
  then `ssh -t <admin>@192.168.123.10 'sudo ./host-baseline.sh && sudo ./verify-baseline.sh'`.
  - Expected: every line starts with `OK`, exit code `0` (`echo $?`).
  - If a `MISMATCH` line appears: note the line and the output of the matching command.
- [ ] Re-run `sudo ./host-baseline.sh` → everything "already done", then `sudo ./verify-baseline.sh` → everything `OK`.
- [ ] `findmnt /data` → type `nfs4`, version `NFS_VERS` in the options.
- [ ] `sudo touch /data/.t && sudo chown 1000 /data/.t; ls -ln /data/.t; sudo rm /data/.t`
  → the result (owner changed or not) matches the NFS options of `rehearsal.env`
  (`no_root_squash`: `1000`; `root_squash`: the `chown` fails).
- [ ] `sudo -iu manuspectrum docker ps` → empty list without error (the service account
  talks to Docker); `sudo -l -U manuspectrum` → no sudo rights.
- [ ] From the host: `ssh manuspectrum@192.168.123.10` → refused (the service
  account has no SSH login).
- [ ] From the host: `nmap -Pn -p 1-65535 192.168.123.10` → only 22, 80, 443
  appear (80/443 "closed" while no service runs: this is normal).

### 1.7 Starting snapshot (host)

- [ ] `virsh shutdown ms-rehearsal`, wait for `virsh domstate ms-rehearsal` → `shut off`,
  then `virsh snapshot-create-as ms-rehearsal baseline`, then `virsh start ms-rehearsal`.
- [ ] `virsh snapshot-list ms-rehearsal` → `installed` and `baseline`.

### 1.8 Rollback and robustness

- [ ] Break something on purpose: `ssh -t <admin>@192.168.123.10 'sudo ufw disable'`, then
  `virsh snapshot-revert ms-rehearsal baseline --running` → `sudo ufw status` says `active` again.
- [ ] Host reboot: `ssh -t <admin>@192.168.123.10 'sudo reboot'`, wait
  2 min → SSH answers, `findmnt /data` still mounts, `sudo ./verify-baseline.sh` all `OK`.
- [ ] If `UNATTENDED_REBOOT=true` in `rehearsal.env`:
  `grep Automatic-Reboot /etc/apt/apt.conf.d/50unattended-upgrades` → the values from
  `rehearsal.env`.

### 1.9 What cannot be tested in rehearsal

The firewall in front of the production VM, storage snapshots, the hosting
provider's backup and the real SMTP relay. They are checked in production
(step "Before production").

---

## Next steps

Each PR of the workstream adds its section here, on the same model (command, expected,
what to do on failure): image and Compose, application observability, nginx and TLS,
secrets, backups, deployed observability, accounts, Ansible, delivery, then
"Before production".
