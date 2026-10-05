# Rehearsal VM

This kit builds, on the host (a Linux workstation running libvirt), a VM with the
same shape as the production VM: Ubuntu 26.04, BIOS, disk partitioned as
`/boot` + LVM (`vg0`, volumes `root` and `swap`), dedicated network, `/data` over NFS and
the same system baseline. The deployment (PP-8, Ansible) is rehearsed on it before
production, and one command brings it back to zero.

The three roles (host, rehearsal VM, production VM) are defined at the top of
`../ACCEPTANCE.md`, which also holds the acceptance steps.

The acceptance steps that check this kit are in `../ACCEPTANCE.md`.

## 0. What the VM reproduces, and what it does not

This repository is public: it describes mechanisms, never production values.
The production VM values (resources, root volume size, locale,
keyboard, NFS options and version, SSH settings, automatic reboot time,
account names...) go in `rehearsal.env`, a local file ignored by
Git: `cp rehearsal.env.example rehearsal.env`, then put the real values in it.
Without this file, the kit uses generic values and the VM does not match
production.

| Item | Reproduced |
| --- | --- |
| Ubuntu 26.04.1, BIOS, `msdos` table, `/boot` ext4 + LVM `vg0` (`root`, `swap`) | yes |
| SSH: `PermitRootLogin no`; `PasswordAuthentication` per `rehearsal.env` | yes |
| UFW: deny inbound, allow outbound, `limit 22/tcp`, `allow 80/tcp`, `allow 443/tcp` | yes |
| fail2ban, `sshd` jail | yes |
| Docker CE + buildx and compose plugins (official apt repository), first admin in `docker` | yes |
| Second admin (sudo) and service account `manuspectrum` (no password, no key, in `docker`) | yes |
| `/data` over NFS, options and version per `rehearsal.env` | yes |
| unattended-upgrades and postfix | yes |
| `vm.max_map_count` and `/etc/docker/daemon.json` | no: Ansible's job |
| What sits in front of the VM in production (firewall, backup, storage snapshots) | no |

Useful habit: measure a subfolder of `/data` rather than the whole of `/data`.

## 1. Host prerequisites

- [ ] Packages. Debian/Ubuntu: `sudo apt install qemu-kvm libvirt-daemon-system virtinst virt-manager libvirt-clients qemu-utils cloud-image-utils whois nfs-kernel-server libosinfo-bin libxml2-utils`. Fedora: `sudo dnf install @virtualization virt-install libvirt-client qemu-img cloud-utils mkpasswd nfs-utils libosinfo libxml2`.
- [ ] Access to libvirt: `virsh -c qemu:///system uri` answers `qemu:///system`. Otherwise: `sudo usermod -aG libvirt $USER`, then log in again. From here on, `export LIBVIRT_DEFAULT_URI=qemu:///system` avoids repeating `-c qemu:///system` in the `virsh` commands.
- [ ] Memory: the VM takes the resources set in `rehearsal.env`; on a smaller host, pass `VCPUS=… RAM_MB=…` when running `make-vm.sh`.
- [ ] Free enough memory on the host: `RAM_MB` + 4 GB.
- [ ] Clone the repository: `git clone https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum.git`, then work from `deploy/rehearsal/`.
- [ ] CPU virtualization is enabled: `egrep -c '(vmx|svm)' /proc/cpuinfo` is greater than 0 (or `kvm-ok` says KVM acceleration can be used).
- [ ] Disk space: reserve `DISK_GB` under `/var/lib/libvirt/images/` (qcow2 is thin-provisioned, but the space must exist).
- [ ] Create your values file: `cp rehearsal.env.example rehearsal.env`, then put the real production values in it. The file is ignored by Git.
- [ ] `ubuntu-26.04.1-live-server-amd64.iso` and `SHA256SUMS` from <https://releases.ubuntu.com/26.04.1/>, in the same folder, readable by the libvirt service: a home directory usually is not, so copy them into `/var/lib/libvirt/images/`. `make-vm.sh` checks the ISO checksum and its readability.
- [ ] An SSH key exists: `~/.ssh/id_ed25519.pub` (otherwise `SSH_PUBKEY=…`).

## 2. Network and NFS

- [ ] `sudo ./host-network.sh`: the `ms-rehearsal` libvirt network (192.168.123.0/24) is active. The `default` network is never modified.
- [ ] `sudo ./host-nfs.sh`: `/srv/ms-rehearsal-data` is exported to the VM only (192.168.123.10/32), with `NFS_EXPORT_OPTIONS` from `rehearsal.env`. With firewalld (Fedora, openSUSE...), the script opens `nfs` in the `libvirt` zone and says so; without it `/data` does not mount. With ufw active on the host, allow NFS from 192.168.123.0/24 (the script reminds you).

## 3. Install the VM

- [ ] `ISO=/path/ubuntu-26.04.1-live-server-amd64.iso ./make-vm.sh` (10 to 15 minutes). The script asks for the administrator account password twice; only its SHA-512 hash is written, in a temporary folder deleted afterwards.
- [ ] Expected result: the VM answers over SSH on 192.168.123.10 and the `installed` snapshot exists (`virsh -c qemu:///system snapshot-list ms-rehearsal`).
- [ ] To see what the script would do without creating anything: `DRY_RUN=1 ISO=… ./make-vm.sh`.
- [ ] If the installer fails, `virt-install` waits forever: follow the installation with `virsh -c qemu:///system console ms-rehearsal`.
- [ ] If the VM already exists, the script refuses; to start over: `virsh -c qemu:///system undefine --remove-all-storage --snapshots-metadata ms-rehearsal`.

## 4. Baseline

- [ ] `scp host-baseline.sh verify-baseline.sh rehearsal.env <admin>@192.168.123.10:` (`<admin>` = `ADMIN_USER` of your `rehearsal.env`). After rebuilding the VM: `ssh-keygen -R 192.168.123.10`.
- [ ] `ssh -t <admin>@192.168.123.10 'sudo ./host-baseline.sh && sudo ./verify-baseline.sh'`: every line of `verify-baseline.sh` starts with `OK`, exit code 0. The script can be re-run; what is already in place is reported as "already done".
- [ ] If the Docker repository does not have the Ubuntu 26.04 suite yet, the script stops and suggests `DOCKER_APT_CODENAME=noble` in `rehearsal.env`; it never falls back silently. Note the suite actually used in production.
- [ ] Shut the VM down (`virsh -c qemu:///system shutdown ms-rehearsal`) then `virsh -c qemu:///system snapshot-create-as ms-rehearsal baseline`: the starting point of every rehearsal, equivalent to the VM as delivered. Restart: `virsh -c qemu:///system start ms-rehearsal`.

Before Ansible, `verify-baseline.sh` prints `vm.max_map_count` without checking it and requires `/etc/docker/daemon.json` to be absent. `verify-baseline.sh --after-ansible` requires `vm.max_map_count` >= 262144 and `/etc/docker/daemon.json` to be present. A failing point is printed as a `MISMATCH` line.

## 5. VM name on the host

- [ ] Add to `/etc/hosts`: `192.168.123.10 manuspectrum.test`. `ping -c1 manuspectrum.test` answers.

## 6. Back to zero

- [ ] `virsh -c qemu:///system snapshot-revert ms-rehearsal baseline` (or `installed` to replay the baseline).

## 7. Delete everything

- [ ] `virsh -c qemu:///system destroy ms-rehearsal`
- [ ] `virsh -c qemu:///system undefine --remove-all-storage --snapshots-metadata ms-rehearsal`
- [ ] `sudo ./host-nfs.sh --remove`
- [ ] `virsh -c qemu:///system net-destroy ms-rehearsal && virsh -c qemu:///system net-undefine ms-rehearsal`

## 8. What comes next

PP-8: Ansible, run from the host against this VM. `/data` is mounted there over NFS
with the options of `rehearsal.env`.

## Test data: dev snapshot

The rehearsal VM can be filled with the development database and uploads, again
and again, from one snapshot directory.

- [ ] On the development machine: `./make-dev-snapshot.sh --out ~/ms-snapshots/ms-snapshot-$(date -u +%F)`
  (options `--python`, `--repo`; `-h` for the usage). It writes `db.dump`
  (`pg_dump -Fc`, without the `silk_*` tables), `media.tar` and `manifest.json`
  (git commit, Arches version, counts, last migration per app, sha256 of the files),
  directory `0700`, files `0600`. It refuses a non-empty directory and never prints the
  database password.
- [ ] Copy it: `scp -r ~/ms-snapshots/ms-snapshot-<date> <admin>@192.168.123.10:`, then
  move it where the service account reads it.
- [ ] On the VM, as the service account, with `DEPLOY_ENVIRONMENT=rehearsal` in `deploy/compose/.env`:
  `make -C deploy load-snapshot SNAPSHOT=<path> CONFIRM=yes`. It replaces the database and the
  uploads (the previous uploads are kept in `previous-<timestamp>/` under `MEDIA_HOST_DIR`),
  migrates, replaces the admin password with the `admin_password` secret, reindexes
  Elasticsearch, compares the counts with the manifest and runs `make smoke`.
- [ ] Reload any time with the same command; to start again from a snapshot of an older
  development state, make a new snapshot.

**Data protection.** The snapshot contains user accounts and research data. Never put it in
Git, never in a public place; delete it from the VM and from the host when the rehearsal
is over. The command refuses to run unless the stack declares itself a rehearsal.

## Checks

`bash check.sh`: shellcheck, seed render tests, validation of the seed against the
subiquity autoinstall schema (pinned), network XML, gitleaks. The last line is
`check.sh: all green.`

## What never goes in Git

Public repository: no personal account name, uid, internal IP address, e-mail address,
password, private key, or setting describing production. All production-specific
values live in `deploy/rehearsal/rehearsal.env`
(ignored by Git); only `rehearsal.env.example`, with generic values, is versioned.
gitleaks runs in `check.sh` and as a `pre-commit` hook.
