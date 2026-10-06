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
- [ ] Disk space: reserve `DISK_GB` under `IMAGES_DIR` (default `/var/lib/libvirt/images/`; qcow2 is thin-provisioned, but the space must exist).
- [ ] Create your values file: `cp rehearsal.env.example rehearsal.env`, then put the real production values in it. The file is ignored by Git.
- [ ] `ubuntu-26.04.1-live-server-amd64.iso` and `SHA256SUMS` from <https://releases.ubuntu.com/26.04.1/>, in the same folder, readable by the libvirt service: a home directory usually is not, so copy them into `IMAGES_DIR` (default `/var/lib/libvirt/images/`). `make-vm.sh` checks the ISO checksum and its readability.
- [ ] An SSH key exists: `~/.ssh/id_ed25519.pub` (otherwise `SSH_PUBKEY=…`).

## 2. Network and NFS

- [ ] `sudo ./host-network.sh`: the `ms-rehearsal` libvirt network (192.168.123.0/24) is active. The `default` network is never modified.
- [ ] `sudo ./host-nfs.sh`: `NFS_EXPORT_DIR` (default `/srv/ms-rehearsal-data`) is exported to the VM only (192.168.123.10/32), with `NFS_EXPORT_OPTIONS` from `rehearsal.env`. With firewalld (Fedora, openSUSE...), the script opens `nfs` in the `libvirt` zone and says so; without it `/data` does not mount. With ufw active on the host, allow NFS from 192.168.123.0/24 (the script reminds you).

## 3. Install the VM

- [ ] `ISO=/path/ubuntu-26.04.1-live-server-amd64.iso ./make-vm.sh` (10 to 15 minutes). The script asks for the administrator account password twice; only its SHA-512 hash is written, in a temporary folder deleted afterwards.
- [ ] Expected result: the VM answers over SSH on 192.168.123.10 and the `installed` snapshot exists (`virsh -c qemu:///system snapshot-list ms-rehearsal`).
- [ ] To see what the script would do without creating anything: `DRY_RUN=1 ISO=… ./make-vm.sh`.
- [ ] If the installer fails, `virt-install` waits forever: follow the installation with `virsh -c qemu:///system console ms-rehearsal`.
- [ ] If the VM already exists, the script refuses; to start over: `virsh -c qemu:///system undefine --remove-all-storage --snapshots-metadata ms-rehearsal`.

## 4. Baseline

- [ ] `scp host-baseline.sh verify-baseline.sh rehearsal.env <admin>@192.168.123.10:` (`<admin>` = `ADMIN_USER` of your `rehearsal.env`). After rebuilding the VM: `ssh-keygen -R 192.168.123.10`.
- [ ] `ssh -t <admin>@192.168.123.10 'sudo ./host-baseline.sh && sudo ./verify-baseline.sh'`: every line of `verify-baseline.sh` starts with `OK`, exit code 0. When `rehearsal.env` sets `REHEARSAL_HOST=yes` (the example does; never set it on a production host) the baseline also writes `/etc/manuspectrum/rehearsal-host`, the marker `make load-snapshot` requires, and `verify-baseline.sh` checks it; without it no marker is written. The script can be re-run; what is already in place is reported as "already done".
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

## Storage on another disk

By default the VM disk lives in `/var/lib/libvirt/images` and the NFS data in
`/srv/ms-rehearsal-data`, on the system disk. To use a secondary disk, set both in
`rehearsal.env` (a value passed in the environment wins), for example:

```
IMAGES_DIR=/media/<user>/<label>/ms-rehearsal/images
NFS_EXPORT_DIR=/media/<user>/<label>/ms-rehearsal/data
```

`NFS_EXPORT` (the path the VM mounts) follows `NFS_EXPORT_DIR`; if you set it too it must be
equal, `host-baseline.sh` and `verify-baseline.sh` refuse otherwise. `make-vm.sh` and
`host-nfs.sh` check the directory before creating anything:

- `NFS_EXPORT_DIR` must be on a Linux filesystem (ext4, xfs, btrfs): vfat, exfat and ntfs are
  refused (no Unix permissions or ACLs; `exportfs` refuses them too). `IMAGES_DIR` may sit on
  NTFS/exFAT (for example a BitLocker disk mounted as fuseblk/ntfs-3g): the qcow2 file works,
  with a warning, but I/O is slower and the timings measured in rehearsal are not comparable
  to production (memory figures are). An unresolved fuseblk gets a warning for both.
- The directory must exist: `sudo install -d -m 0755 <IMAGES_DIR>`.
- The hypervisor user (`libvirt-qemu` on Debian/Ubuntu, `qemu` on Fedora) must traverse every
  parent directory and read/write `IMAGES_DIR`. A `/media/<user>` directory is usually closed
  to it; the script prints the exact fix:
  `sudo setfacl -m u:libvirt-qemu:x <each parent lacking x>` and
  `sudo setfacl -m u:libvirt-qemu:rwx <IMAGES_DIR>`.
- Mount the disk at boot. A desktop automount under `/media` appears only after a login,
  so after a reboot the VM would not find its disk. If the mount point is not in
  `/etc/fstab` the scripts warn (they do not refuse) and print the line to add, from
  `findmnt -no UUID -T <dir>`:
  `UUID=<uuid>  /media/<user>/<label>  ext4  defaults,nofail,x-systemd.device-timeout=10s  0  2`
  then `sudo mount -a`. Exporting a directory of a removable automount is fragile: the
  export fails whenever the disk is absent.
- Copy the Ubuntu ISO and `SHA256SUMS` into `IMAGES_DIR` and run
  `ISO=<IMAGES_DIR>/ubuntu-26.04.1-live-server-amd64.iso ./make-vm.sh`.

AppArmor (Debian/Ubuntu hosts): libvirt generates a profile per VM for its disk paths, so a
custom directory works. If `virt-install` still reports a permission denied although the ACLs
are right, look at `dmesg | grep apparmor` (or `journalctl -k | grep apparmor`).

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
- [ ] On the VM, as the service account, set the environment explicitly: the template
  `deploy/compose/.env.example` ships `DEPLOY_ENVIRONMENT=production`, so run
  `sed -i 's/^DEPLOY_ENVIRONMENT=.*/DEPLOY_ENVIRONMENT=rehearsal/' deploy/compose/.env`. The command
  also requires the host marker `/etc/manuspectrum/rehearsal-host`, written by `host-baseline.sh`
  in the VM and checked by `verify-baseline.sh`; without it (a production host) the command is
  refused whatever `.env` says.
- [ ] `sudo -u <service-account> make -C deploy load-snapshot SNAPSHOT=<path> CONFIRM=yes` (or as root; the
  uploads are then handled as the service account through `setpriv`; any other account is refused). Before anything is changed, a
  preflight refuses a snapshot holding a migration of an installed app that the image does not know
  (migrations of apps the image does not install, silk for instance, give one warning), warns when
  the image has newer migrations or another Arches major.minor, and checks the free space (`MEDIA_HOST_DIR` and the Docker data root). Then it dumps the current
  database, replaces the database and the uploads, flushes the Redis caches and the Celery queues
  (redis-cache `FLUSHALL`; redis-broker databases 0, the Celery queue, and 3, the IIIF sign-ins,
  which a rehearsal does not keep), clears the Cantaloupe derivative cache and recreates
  Cantaloupe, migrates, replaces the admin password with the `admin_password` secret, reindexes
  Elasticsearch, compares the counts with the manifest, runs `make smoke` and checks that
  Cantaloupe sees the new uploads.
- [ ] What is replaced is kept in `previous-<timestamp>/` under `MEDIA_HOST_DIR`: the previous
  uploads (the `uploadedfiles/` directory itself stays in place, it is Cantaloupe's mount) and
  `rehearsal-before.dump`, the previous database. The aside path is logged when it is created. A run that finishes writes `previous-<timestamp>/.complete`;
  only the two newest complete directories are kept and the command prints what it keeps and removes. A
  directory without `.complete` (a failed run) is never removed.
- [ ] To undo a load: `sudo -u <service-account> make -C deploy load-snapshot RESTORE_BEFORE=<MEDIA_HOST_DIR>/previous-<timestamp>-<id> CONFIRM=yes`.
  It restores `rehearsal-before.dump` and a copy of `uploadedfiles/` through the same steps and guards
  as a load (drop and recreate the database, Redis flush, Cantaloupe cache, migrate, reindex, smoke);
  the state it replaces is kept in a new aside directory. It refuses when the dump is missing.
- [ ] Reload any time with the same command; to start again from a snapshot of an older
  development state, make a new snapshot.

**Data protection.** The snapshot contains user accounts and research data. Never put it in
Git, never in a public place; delete it from the VM and from the host when the rehearsal
is over. The command refuses to run unless the stack declares itself a rehearsal twice: `DEPLOY_ENVIRONMENT=rehearsal` in `.env` and the host marker file.

## Checks

`bash check.sh`: shellcheck, seed render tests, dev snapshot and storage directory tests, validation of the seed against the
subiquity autoinstall schema (pinned), network XML, gitleaks. The last line is
`check.sh: all green.`

## What never goes in Git

Public repository: no personal account name, uid, internal IP address, e-mail address,
password, private key, or setting describing production. All production-specific
values live in `deploy/rehearsal/rehearsal.env`
(ignored by Git); only `rehearsal.env.example`, with generic values, is versioned.
gitleaks runs in `check.sh` and as a `pre-commit` hook.
