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
- **The VM clock.** Reverting to a snapshot taken while the VM ran, or taking one of a running VM,
  leaves the guest clock wrong (days behind after a revert, minutes behind after a live snapshot),
  and with it every check that reads the time: two-factor codes (TOTP), announcements, the
  reminders and the `--as-of` passes. Take snapshots with the VM shut down (`virsh shutdown`, wait for
  `shut off`, `virsh snapshot-create-as`, `virsh start`); after a revert of a running snapshot,
  `virsh shutdown` and `virsh start` the VM. Before a time-sensitive step (8.3, 8.5, 4.4) run
  `ssh <admin>@192.168.123.10 timedatectl` → `System clock synchronized: yes` and a time within a
  few seconds of the host's `date`.
- On failure, nothing is fixed by hand in the VM: note it, fix the kit, then
  go back to the snapshot and replay. An unwritten manual step is exactly what
  will be missing on moving day.

## Prerequisites

Anyone with (a) a Linux host with KVM/libvirt and (b) a clone of the repository
(`git clone --recurse-submodules https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum.git`)
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
- [ ] The ISO and `SHA256SUMS` are in `IMAGES_DIR` (default `/var/lib/libvirt/images/`):
  `cd "$IMAGES_DIR" && sha256sum --ignore-missing -c SHA256SUMS`
  → `ubuntu-26.04.1-live-server-amd64.iso: OK`.
- [ ] Storage on a secondary disk (only if `IMAGES_DIR` / `NFS_EXPORT_DIR` are set in
  `rehearsal.env`): `DRY_RUN=1 ISO=... deploy/rehearsal/make-vm.sh` and
  `sudo deploy/rehearsal/host-nfs.sh` print no refusal, the `setfacl` commands they suggest
  (if any) are applied, and `findmnt --fstab <mount point>` lists the disk (`nofail`), so it is
  mounted at boot without a login. `IMAGES_DIR` may be on NTFS/exFAT (warning: slower, timings
  not comparable); `NFS_EXPORT_DIR` may not. See README, "Storage on another disk".

### 1.3 Network and NFS (host)

- [ ] `sudo deploy/rehearsal/host-network.sh` then `virsh net-list --name` → contains
  `ms-rehearsal`; `virsh net-list --name` still contains `default`.
- [ ] Re-run `sudo deploy/rehearsal/host-network.sh` → message "already done", nothing changes.
- [ ] `sudo deploy/rehearsal/host-nfs.sh` then `sudo exportfs -v` → one line
  `/srv/ms-rehearsal-data 192.168.123.10/32(...)` with the options from `rehearsal.env`.
- [ ] Re-run `sudo deploy/rehearsal/host-nfs.sh` → "already done".
- [ ] `grep -A3 '^\[mountd\]' /etc/nfs.conf` → shows `manage-gids=n`: the server honours the
  client's supplementary groups, as the production one does (Cantaloupe reads the uploads
  through `group_add: APP_GID`).

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
- [ ] `cloud-init status` → `status: done` or `status: disabled` (both mean the installer
  finished; the Ubuntu 26.04 autoinstall disables cloud-init for later boots).

### 1.6 Host baseline (rehearsal VM)

- [ ] Play the system administrator, from the host:
  `scp deploy/rehearsal/{host-baseline.sh,rehearsal.env} <admin>@192.168.123.10:` then
  `ssh -t <admin>@192.168.123.10 'sudo ./host-baseline.sh'`.
- [ ] Verify it with Ansible, from the laptop (`deploy/ansible/README.md`): an inventory copied from
  `inventories/example/` with `baseline_mode: verify` and `rehearsal_host: true`, then
  `cd deploy/ansible && ansible-playbook -i inventories/<rehearsal> site.yml --ask-become-pass --tags preflight,baseline`.
  - Expected: no failed task, and `changed=2` for the two marker tasks of `site.yml` (the marker is touched, then removed; `changed=3` when `/run/manuspectrum` does not exist yet, as its creation also counts), nothing else.
  - If an assertion fails: its message says what to do; note it and the output of the matching command.
- [ ] Re-run `sudo ./host-baseline.sh` → everything "already done", then the Ansible verification again → the same two marker tasks only (`changed=2`).
- [ ] After a full `ansible-playbook site.yml` (not only the baseline tags): `cat /etc/docker/daemon.json` (written by the Ansible `host` role) → `json-file` logs 10m x 5, `live-restore`,
  `no-new-privileges`; `docker info --format '{{.LiveRestoreEnabled}}'` → `true`.
  When containers already run and the file would change, the play stops and asks for
  `-e docker_restart_ok=true`: the Docker restart stops the stack (plan a window on a live host).
  A `daemon.json` with keys the role does not manage stops the play: merge them by hand first.
- [ ] `ls -l /etc/manuspectrum/rehearsal-host` → `-rw-r--r-- 1 root root`: the marker without which
  `make load-snapshot` is refused (the rehearsal VM only; never create it on a production host).
- [ ] `chronyc tracking` → `Leap status : Normal` and a `Reference ID` naming a server (the clock is
  synchronised). `Not synchronised` with every source `^?` in `chronyc sources -v`: follow the runbook
  `deploy/runbooks/host.md#clocknotsynchronised` (NTS blocked on the network) and note the server used.
- [ ] `findmnt /data` → type `nfs4`, version `NFS_VERS` in the options.
- [ ] `sudo touch /data/.t && sudo chown 1000 /data/.t; ls -ln /data/.t; sudo rm /data/.t`
  → the result (owner changed or not) matches the NFS options of `rehearsal.env`
  (`no_root_squash`: `1000`; `root_squash`: the `chown` fails).
- [ ] `sudo -iu manuspectrum docker ps` → empty list without error (the service account
  talks to Docker); `sudo -l -U manuspectrum` → no sudo rights.
- [ ] From the host: `ssh -o BatchMode=yes -o PreferredAuthentications=publickey manuspectrum@192.168.123.10 true`
  → refused at once (the service account has no SSH login). Every refusal counts for fail2ban:
  repeated attempts get the host banned for 10 minutes, which also blocks the `nmap` check below
  (wait it out; the ban proves fail2ban works).
- [ ] From the host: `nmap -Pn -p 1-65535 192.168.123.10` → only 22, 80, 443
  appear (80/443 "closed" while no service runs: this is normal).

### 1.7 Starting snapshot (host)

- [ ] `virsh shutdown ms-rehearsal`, wait for `virsh domstate ms-rehearsal` → `shut off`,
  then `virsh snapshot-create-as ms-rehearsal baseline`, then `virsh start ms-rehearsal`.
- [ ] `virsh snapshot-list ms-rehearsal` → `installed` and `baseline`.

### 1.8 Rollback and robustness

- [ ] Break something on purpose: `ssh -t <admin>@192.168.123.10 'sudo ufw disable'`, then
  `virsh snapshot-revert ms-rehearsal baseline --running` → `sudo ufw status` says `active` again.
  `baseline` was taken with the VM shut down (1.7), so the guest boots afresh with a right clock; check
  with `timedatectl` (see « How to read and record »).
- [ ] Host reboot: `ssh -t <admin>@192.168.123.10 'sudo reboot'`, wait
  2 min → SSH answers, `findmnt /data` still mounts, the Ansible verification (`--tags preflight,baseline`) passes.
- [ ] If `UNATTENDED_REBOOT=true` in `rehearsal.env`:
  `grep Automatic-Reboot /etc/apt/apt.conf.d/50unattended-upgrades` → the values from
  `rehearsal.env`.

### 1.9 What cannot be tested in rehearsal

The firewall in front of the production VM, storage snapshots, the hosting
provider's backup and the real SMTP relay. They are checked in production
(step "Before production").

---

## Step 2 — Image and Compose (`deploy/docker/`, `deploy/compose/`)

The image, the Compose stack and its operator commands (`deploy/README.md`). On the
rehearsal VM, start from the `baseline` snapshot of step 1.

**What CI already proves, and what only the rehearsal VM can.** The `deploy-lint` workflow
runs on every pull request touching the stack: `check-stack.sh` (2.1), the image build and
`probe-image.sh` (2.3), then on a runner `make volumes init up`, `smoke.sh check`, `mark`,
`init-guard`, `down`/`up` + `survived`, a `systemctl restart docker` + `survived`,
`static-swap` and `down -v` + `survived`; `trivy-weekly` scans the image every Monday.
A runner has no NFS media, no 22 GB / 8 vCPU sizing, no unattended reboot and no
service account. So here the rehearsal VM is what proves: the real service account and
media directory (2.2), the memory limits and the measured memory of a full reindex
(2.5, 2.10), the host reboot (2.8), and everything the CI also runs, replayed on the
production-shaped VM. Rows marked **(CI too)** repeat a CI check on purpose.

In this step, `dc` means:
`docker compose --project-directory deploy/compose -f deploy/compose/compose.yaml -f deploy/compose/compose.prod.yaml`
(`alias dc='…'` once per terminal). Commands marked *(service account)* run after
`sudo -iu manuspectrum` and `cd ~/manuspectrum`. Host-specific values (accounts, paths,
names) come from `deploy/rehearsal/rehearsal.env` and `deploy/compose/.env`.
Only the service account is in the `docker` group (root-equivalent): the admin accounts run no
`docker`, `dc`, `make -C deploy` or `smoke.sh` command, except through `sudo`.

### 2.1 The kit is sound (host or CI)

- [ ] `bash deploy/check-stack.sh`
  - Expected: last line `check-stack.sh: all green.`
  - On failure: the section header (`== …`) names the tool (shellcheck, hadolint,
    publish-static tests, Compose rules, actionlint, uv.lock, gitleaks); fix the kit,
    not the VM.
- [ ] The pull request's `deploy-lint` run is green:
  `gh run list --workflow deploy-lint.yml --branch <branch> --limit 1` → `completed success`.
  - On failure: `gh run view <id> --log-failed`; record the failing step. The last
    `trivy-weekly` run on the default branch is also `completed success`
    (`gh run list --workflow trivy-weekly.yml --limit 1`); otherwise read the issue it opened.

### 2.2 Service account, media directory, `.env` and secrets (rehearsal VM)

- [ ] `command -v make git openssl python3` → four paths. The `app` role of `site.yml` installs them
  (`deploy/ansible/README.md`); the other steps of this section assume `site.yml` has run once
  (`--tags app` is enough after the baseline) and stopped at its first closed gate.
- [ ] *(service account)* `docker compose version` and `docker info --format '{{.LoggingDriver}}'` →
  Compose v2 and `json-file`.
- [ ] The directories are created by the `app` role (paths and account from the inventory), then
  `sudo ls -ldn /data/manuspectrum/media` (the directory is `0750`, owned by the service
  account: without `sudo` the admin cannot list it; or run it as the service account) →
  owner and group = `id -u manuspectrum`, `id -g manuspectrum`. Directories `0750`, files
  `0640`, owned by the account: Cantaloupe is not that account, it reads the uploads through
  `group_add: APP_GID`. Files that web or worker write later get `0644` (umask 022).
  Over NFS the export must keep the uid and gid (no `root_squash` remapping of them); for the
  Ansible rehearsal set `NFS_EXPORT_OPTIONS=rw,sync,no_root_squash,no_subtree_check` in `rehearsal.env`
  too, or the playbook (root) cannot create the directories on the export.
- [ ] The repository is at `~/manuspectrum`: the `app` role clones `app_git_url` at `app_git_ref` when
  `app_dir/.git` is absent and never moves an existing checkout. To test a commit, set `app_git_ref`
  in the inventory before the first run; on an existing checkout, as the service account:
  `git -C manuspectrum checkout <commit>`, `git -C manuspectrum submodule update --init`.
  `git -C manuspectrum log -1 --format=%H` → `<commit>`.
- [ ] `deploy/compose/.env` is rendered by the `app` role from the `env_*` variables of the inventory
  (one per key of `compose/.env.example`; `APP_UID` and `APP_GID` are read from the host): never edit
  it by hand, change the inventory and run the playbook again. For the rehearsal VM set
  `env_deploy_environment: rehearsal` (the template ships `production`), `env_cert_mode: local`,
  `env_local_ca_cert: <env_certs_dir>/ca/ca.crt` as a literal path, `env_public_host`,
  `env_domain_names`, `env_public_server_address` and `env_manuspectrum_image: manuspectrum:local`.
  Check: `grep -E '^APP_(UID|GID)=' deploy/compose/.env` → the two numbers of `id -u; id -g`, and
  `grep '^DEPLOY_ENVIRONMENT=' deploy/compose/.env` → `DEPLOY_ENVIRONMENT=rehearsal`. A production
  host leaves `production`. `make -C deploy certs-local` (4.1) creates the certificates and the CA
  file that `init` mounts: run it before `init` (2.4). `make up` creates `METRICS_TEXTFILE_DIR`
  (node-exporter mounts it) when it is missing.
- [ ] The parent of `SECRETS_DIR` (`/srv/manuspectrum` in the example inventory, outside the
  directories TSM backs up by default) and the nginx log directory (`env_nginx_log_host_dir`) are
  created by the `app` role, owned by the service account.
- [ ] *(service account)* `make -C deploy secrets` (creates the directory `0700` and the missing
  files; the commands by hand are in `deploy/compose/secrets/README.md`). From here on,
  `SECRETS_DIR=$(make -s -C deploy secrets-dir)` is set in the shell;
  `ls -l "$SECRETS_DIR"` → `pg_password`, `elastic_password`, `django_secret_key`,
  `email_password` (empty), `admin_password`, `restic_password`, `grafana_admin_password`, `pg_monitor_password`
  (eight files in all) as `-r--r--r--`; `ls -ld "$SECRETS_DIR"` →
  `drwx------`.
- [ ] *(service account)* `git status --short deploy/compose` → empty (neither `.env` nor
  the secrets are tracked or untracked-visible).

### 2.3 Build or load, and probe, the image (rehearsal VM; never the development VM)

- [ ] `free -g` → at least 10 GB available.
- [ ] *(service account)* `make -C deploy build` (20 to 40 min). To test an image built
  elsewhere instead: `docker load -i <archive>` then
  `docker tag <loaded image> manuspectrum:local`.
  - Expected: ends with `naming to docker.io/library/manuspectrum:local`;
    `docker image ls manuspectrum:local` lists it.
  - On failure: keep the last 50 lines; `sudo dmesg | grep -i oom` for a killed build.
- [ ] *(service account)* `bash deploy/docker/probe-image.sh manuspectrum:local`
  → last line `probe-image.sh: all green.` **(CI too)**
  - On failure: the `FAIL:` line names the property (uid, read-only root, build tool,
    gunicorn 26, `.build-id`, writable path…); fix the Dockerfile, rebuild.

### 2.4 First installation

- [ ] *(service account)* `make -C deploy volumes` → five lines `ms_pg_data`, `ms_es_data`,
  `ms_redis_broker`, `ms_cantaloupe_cache`, `ms_prometheus_data` (the output of `docker volume create`); run it
  again → five `… exists`.
- [ ] *(service account)* `make -C deploy config` → `compose files valid`.
  - On failure: the message names the unset variable of `.env`.
- [ ] *(service account)* The package is present: `ls pkg/graphs/resource_models | head -3` and
  `test -f pkg/expected-inventory.json` (`git submodule update --init` otherwise).
- [ ] *(service account)* `make -C deploy certs-local` (4.1; `init` mounts `LOCAL_CA_CERT` and refuses with this very
  command when the file is missing), then `make -C deploy init` → Arches `setup_db` output, then the lines
  `entrypoint: admin password set from the admin_password secret`,
  `entrypoint: loading the data package /srv/pkg (several minutes)`, the `load_package`
  output, `Inventory check passed: the database matches expected-inventory.json` and
  `entrypoint: data package loaded`, exit 0 (`echo $?`). A line `Inventory check FAILED` lists the
  differences and stops `init`. It takes noticeably
  longer than `setup_db` alone.
  - Refusals before `setup_db`: `holds no data package` (submodule not initialised),
    `pkg/ is not at the commit this checkout pins` (`make init` itself;
    `git submodule update --init`), `PUBLIC_SERVER_ADDRESS … must end with a slash`
    (the deployment checks, before anything else).
  - On failure: `dc logs --tail=100 postgres elasticsearch`; an Elasticsearch that never
    gets healthy: `sysctl vm.max_map_count` → at least `262144`.
  - A failed first installation (Elasticsearch flapping, out of memory, Ctrl-C) leaves a
    half-created database: `make init` then refuses, and `web` refuses to start with
    `has no Arches system settings`. Drop it, then start again:
    `dc exec postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists <PGDBNAME>'` and
    `make -C deploy init` (Elasticsearch indexes are recreated by `setup_db`).
- [ ] *(service account)* The end of the `init` output says
  `admin password set from the admin_password secret`. Read the password once,
  `cat "$SECRETS_DIR/admin_password"`, and sign in as `admin` on the
  rehearsal address (`/en/auth/`): it works, and `admin` / `admin` is refused.
  Store it immediately in the institution's password manager (break-glass account),
  create a named account for each operator and use those day to day. To read it as the
  service account from another login: `sudo -iu <service-account> cat <SECRETS_DIR>/admin_password`.
  Change it any time from the profile page or with
  `make -C deploy manage ARGS="changepassword admin"` (interactive): the file then no
  longer matches and only served the installation, the password manager is the
  reference. Step 5 puts it, with the other secrets, in the vault item.
  - On failure: `init` ends with `the admin password could not be set` (the database
    exists with the default password): fix the file, then `make -C deploy admin-password`.
- [ ] *(service account)* Run `make -C deploy init` again → exit ≠ 0 with
  `refusing: database <PGDBNAME> exists and setup_db would drop it`, and the data is intact
  (`deploy/compose/smoke.sh init-guard` → four `ok:` lines: `init`, `manage setup_db`,
  `manage packages ... -db`, `manage packages -o setup`). Without the package directory,
  Compose fails on the bind mount before the entrypoint can refuse, and the script says
  `init-guard needs the data package` (`git submodule update --init`). **(CI too)**
- [ ] *(service account, observability profile)* `make -C deploy monitoring-init` (starts `postgres` if needed and creates the
  `ms_monitor` role: until then `postgres-exporter` is `unhealthy`, `pg_up 0`, and `up` refuses to call the stack healthy).
- [ ] *(service account)* `make -C deploy up` → returns without error (it waits for every
  service but `beat`, then starts `beat`); up to 15 minutes on a first start.
  The `nginx` service needs `CERTS_DIR` and `NGINX_LOG_HOST_DIR` to exist: `up` fails otherwise (`up` itself
  creates `METRICS_TEXTFILE_DIR`).
  - On failure: `make -C deploy status`, then `dc logs --tail=100 <service>` of the one
    that is not healthy.
- [ ] *(service account)* `make -C deploy status` → nine services: `postgres`,
  `elasticsearch`, `redis-broker`, `redis-cache`, `cantaloupe`, `web`, `worker`, `nginx` as
  `healthy`, `beat` as `running` (it has no health check on purpose).
  Check: `dc ps --format '{{.Service}} {{.State}} {{.Health}}' | grep -v ' running healthy$'` → one line,
  `beat running ` (do not count lines of `make status`: make prints its own lines, and `beat` has no health).
- [ ] *(service account)* `make -C deploy smoke` (= `deploy/compose/smoke.sh check`) →
  only `ok:` lines, exit 0. **(CI too)** Among them, the three that fail most
  often on a new host:
  - `ok: database collation and encoding` (`en_US.utf8|UTF8`);
  - `ok: standard_conforming_strings` (the value is `off`: Arches needs it);
  - `ok: admin does not use Arches' default password` (the check passes when `admin`'s password is no longer `admin`);
  - `ok: /healthz for the public name` (`200`) then
    `ok: /healthz for Host localhost (not allowed)` (`400`): gunicorn answers
    `Host: web` and the `DOMAIN_NAMES` only.
  - On failure: the `FAIL:` line names the check and the value found;
    `dc logs --tail=100 <service>`.
- [ ] *(service account)* Same Host rule by hand: `dc exec -T web curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: web' http://127.0.0.1:8000/healthz`
  → `200`; with `-H 'Host: localhost'` → `400`.

### 2.5 Resources and restart policy (D-H6)

- [ ] *(service account)* `docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'` → limits (second figure):
  elasticsearch 5GiB, postgres 3GiB, web 4GiB, worker 2GiB, cantaloupe 1.75GiB,
  redis-broker 256MiB, redis-cache 768MiB, beat 256MiB, nginx 512MiB. Record the idle usage of each.
  Expected idle: elasticsearch about 2.7 GiB on an empty database, about 3.4 GiB with data
  loaded (heap 2 GiB; the rest is direct memory, metaspace, threads and page cache). The
  postgres, web and worker figures depend on the load: measured 0.1 / 0.9 / 0.3 GiB on an empty
  database and 0.36 / 0.62 / 0.29 GiB with data loaded and no traffic; cantaloupe 0.3 (1.3 warm).
- [ ] *(service account)* `docker inspect -f '{{.Name}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}' $(dc ps -q)`
  → nine lines (one per container; 17 with the observability and mailpit profiles) where the two figures are equal
  (a container never swaps).
  - On failure: a limit shown as the whole host memory means `compose.prod.yaml` was not
    applied: the `-f` list or `make` was bypassed.
- [ ] *(service account)* `docker top manuspectrum-web-1 | grep -c 'gunicorn'` → `6` (master and 5 workers;
  each worker runs 4 threads: 20 concurrent requests, `GUNICORN_WORKERS`/`GUNICORN_THREADS`).
- [ ] *(service account)* `docker exec manuspectrum-web-1 sh -c 'echo $GUNICORN_WORKERS $GUNICORN_THREADS'` → `5 4`.
- [ ] *(service account)* `docker inspect -f '{{.Config.StopTimeout}}' manuspectrum-web-1` → `310` (above gunicorn's
  `graceful_timeout` of 300 s, which bounds a stop and a `max_requests` recycle because
  `timeout` is 330 s, at least `graceful_timeout`: a download in progress survives both).
- [ ] *(service account)* `dc exec -T web python manage.py shell -c "from django.db import connection as c; k=c.cursor(); k.execute('SHOW statement_timeout'); print(k.fetchone()[0])"`
  → `1min`; the same command with `worker` instead of `web` → `0`.
- [ ] *(service account)* `dc exec -T cantaloupe id` → the groups list contains `APP_GID`.
- [ ] *(service account)* `dc exec elasticsearch sh -c 'curl -s -u "elastic:$(cat /run/secrets/elastic_password)" "localhost:9200/_nodes/_local/stats/jvm?filter_path=**.heap_max_in_bytes"'`
  → `2147483648`.
- [ ] *(service account)* `dc exec elasticsearch sh -c 'stat -c %a /tmp/elastic_password; stat -c %a /run/secrets/elastic_password'`
  → `600` then `444` (Elasticsearch reads its own `0600` copy; the host file stays shared).
- [ ] *(service account)* `docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' $(dc ps -q)` → nine lines
  `unless-stopped`.
- [ ] *(service account)* Only nginx publishes ports: `docker ps --format '{{.Names}} {{.Ports}}'` → the
  `nginx` line holds `0.0.0.0:80->80/tcp` and `0.0.0.0:443->443/tcp`, every other line no `0.0.0.0:` nor `:::` entry
  (step 4.2).

### 2.6 Logs and rotation

- [ ] *(service account)* `for c in $(dc ps -q); do docker inspect -f '{{.Name}} {{.HostConfig.LogConfig}}' $c; done`
  → nine lines ending `{json-file map[max-file:5 max-size:10m]}`.
  - On failure: `logging` is missing for that service in `compose.yaml`.
- [ ] *(admin)* `L=$(sudo docker inspect -f '{{.LogPath}}' manuspectrum-web-1); sudo sh -c "ls -lh $L*"` (the glob must be
  expanded by root's shell: the admin cannot read `/var/lib/docker/containers`) → `*-json.log`,
  no file above 10 MB. To see rotation itself, write about 12 MB:
  `docker exec manuspectrum-web-1 sh -c 'yes ms-log-test | head -c 12000000 >/proc/1/fd/1'`,
  then the same `sudo sh -c "ls -lh $L*"` → a second file `*-json.log.1`, none larger than 10 MB, at most five.
- [ ] *(service account)* `docker logs --tail=5 manuspectrum-web-1` still answers (rotation does not break it).

### 2.7 Data survives (rehearsal VM only)

- [ ] *(service account)* `deploy/compose/smoke.sh mark` → `ok: markers written (…)`.
- [ ] *(service account)* `make -C deploy down up && deploy/compose/smoke.sh check && deploy/compose/smoke.sh survived`
  → only `ok:`. **(CI too)**
- [ ] *(service account)* Docker daemon restart (what a host reboot does to the
  containers, without the reboot): `sudo systemctl restart docker` from the admin
  account, then `deploy/compose/smoke.sh wait && deploy/compose/smoke.sh check && deploy/compose/smoke.sh survived`
  → only `ok:`. **(CI too)**
  - On failure: `dc ps -a`; a service restarted before its dependency is a start-order
    defect (`entrypoint.sh` waits for PostgreSQL and Elasticsearch itself).
- [ ] *(service account)* `dc down -v` (a test gesture, never in production), then
  `docker volume ls --format '{{.Name}}' | grep -c '^ms_'` → `4` (the volumes are
  external); then `make -C deploy up && deploy/compose/smoke.sh survived` → only `ok:`.
  **(CI too)**
- [ ] `ls -ln /data/manuspectrum/media/.ms-smoke-marker` → owner = `APP_UID` (files written
  by the containers on the NFS share belong to the service account).

### 2.8 Static files follow the image, and the host reboot

- [ ] *(service account)* `deploy/compose/smoke.sh static-swap` → only `ok:` (a stale
  `current` is replaced on restart, the previous release kept once, pruned at the next
  restart). **(CI too)**
- [ ] *(service account)* After a new image: `docker exec manuspectrum-web-1 cat /app/static/.build-id` → note
  `<id1>`. Build the next commit (`git checkout <next commit>`, `git submodule update --init`,
  `make -C deploy build IMAGE=manuspectrum:next`), set `MANUSPECTRUM_IMAGE=manuspectrum:next`
  in `.env`, `make -C deploy up`. Then
  `docker exec manuspectrum-web-1 cat /app/static/.build-id` → `<id2>` and
  `docker exec manuspectrum-web-1 readlink /srv/static/current` → `releases/<id2>`
  (identical to `<id1>` only if the commits build the same files).
  - On failure: `docker exec manuspectrum-web-1 ls /srv/static/releases`; `dc logs web`
    for a `publish-static` message.
- [ ] Host reboot (the production VM reboots itself after kernel updates): from the admin
  account `sudo reboot`; wait 5 minutes and type nothing else on the VM.
  Then, *(service account)* `deploy/compose/smoke.sh wait && deploy/compose/smoke.sh check && deploy/compose/smoke.sh survived`
  → only `ok:` lines, with nobody having started anything by hand.
  - On failure: `systemctl is-enabled docker` → `enabled`; `findmnt /data` still mounted
    before Docker starts; `dc ps -a`; `dc logs --tail=100 <service>` of the one not back.

### 2.9 Load the dev snapshot (rehearsal VM only)

A snapshot made on the development machine with `deploy/rehearsal/make-dev-snapshot.sh`
(see `deploy/rehearsal/README.md`) is copied to the VM. It holds user accounts and
research data: never in Git, never in a public place.

- [ ] *(service account)* `grep '^DEPLOY_ENVIRONMENT=' deploy/compose/.env` → `DEPLOY_ENVIRONMENT=rehearsal`
  (step 2.2), and `ls -l /etc/manuspectrum/rehearsal-host` → a root-owned file (written by
  `host-baseline.sh` or the Ansible `baseline` role when `REHEARSAL_HOST=yes` / `rehearsal_host: true`, checked by the baseline verification then).
  - On failure: the command needs both guards. A production host has `production` and no marker
    file, and the command is refused there whatever `.env` says.
- [ ] *(service account)* `make -C deploy load-snapshot SNAPSHOT=<path>` without `CONFIRM=yes` → refused, nothing changed.
- [ ] *(service account)* `make -C deploy load-snapshot SNAPSHOT=<path> CONFIRM=yes` → fifteen `load-snapshot: step n/15`
  lines, `checksums match`, `uploaded files: <n> cited by the snapshot's database, <m> missing from media.tar`
  (`m` at most 10 % of `n`, see `deploy/rehearsal/README.md`), `preflight: ok`, counts
  `equal to the manifest` (or a `WARNING` naming the difference a migration explains), `done: the snapshot is loaded`.
  - A snapshot holding a migration of an installed app that the image does not know is refused before
    anything is changed; migrations of apps the image does not install (silk, for instance) give one warning.
  - The command runs as the service account (`sudo -u <service-account> make -C deploy load-snapshot ...`)
    or as root (uploads handled as the service account through `setpriv`); another account is refused.
  - On failure: a `sha256 mismatch` means the copy is damaged, copy it again; a `pg_restore failed`
    names the first errors, the database is incomplete, run the command again (it recreates it);
    a failing step stops the run, fix it and run the command again.
- [ ] *(service account)* `make -C deploy smoke` → only `ok:` lines; `ls -d /data/manuspectrum/media/previous-*` →
  the previous uploads and `rehearsal-before.dump` (the database as it was), kept; only the last
  two complete such directories are kept (a directory without `.complete`, left by a failed run, is
  never removed). The command logs the aside path when it creates it.
- [ ] Undo a load: `sudo -u <service-account> make -C deploy load-snapshot RESTORE_BEFORE=<MEDIA_HOST_DIR>/previous-<stamp>-<id> CONFIRM=yes`
  → the same fifteen steps, restoring `rehearsal-before.dump` and a copy of `uploadedfiles/`
  from that directory (the migration check and the counts are skipped, there is no manifest);
  refused when `rehearsal-before.dump` is missing; `smoke` is `ok:` afterwards.
- [ ] *(service account)* The dev admin password does not survive: `deploy/compose/smoke.sh check` is `ok:` and logging in as
  `admin` with the development password fails; with the `admin_password` secret it succeeds.

### 2.10 Memory under a full reindex (feeds the capacity review)

Measured on the data loaded in 2.9: on an empty database a reindex measures nothing, and the
idle figures of 2.5 are only a baseline. `load-snapshot` already runs a full reindex (one of its
steps).

- [ ] *(service account)* Record the idle memory again now that the snapshot is loaded:
  `docker stats --no-stream --format '{{.Name}} {{.MemUsage}}'`.
- [ ] *(service account)* In a second terminal, sample every 10 s (start it before the load of 2.9,
  or before the command below):
  `while sleep 10; do date +%T; docker stats --no-stream --format '{{.Name}} {{.MemUsage}} {{.CPUPerc}}'; done | tee ~/reindex-stats.txt`
- [ ] *(service account)* In the first, either the reindex step of a `make -C deploy load-snapshot ... CONFIRM=yes`
  run (2.9) or a separate `time dc exec -T web python manage.py es reindex_database` on the loaded
  data → exits 0. Stop the sampling. Record: the duration, the peak `MemUsage` of
  `elasticsearch`, `postgres`, `web`, `worker`, and any container at its limit.
  - Expected: no container at its limit, `docker inspect -f '{{.State.OOMKilled}}' $(dc ps -q)`
    → nine `false`, `sudo dmesg | grep -ci 'out of memory'` → `0`.
  - On failure: record the peak and the killed service; the limits in `compose.prod.yaml`
    are starting values until this figure is in.
- [ ] *(service account)* `make -C deploy smoke` → only `ok:` after the reindex.

### 2.11 Clean up

The markers of 2.7 stay in place until here: 2.8 reuses them.

- [ ] *(service account)* `deploy/compose/smoke.sh clean` → `ok: markers removed`.
- [ ] (host) optional snapshot of the installed stack:
  `virsh shutdown ms-rehearsal`, wait for `shut off`,
  `virsh snapshot-create-as ms-rehearsal stack-step2`, `virsh start ms-rehearsal`.

### 2.12 What cannot be tested in this step

the checks that need nginx, TLS and a browser (an XY chart in the editor and in a report,
the model page, Compare, a French page) are step 4;
the vault copy and the rotation of secrets (step 5), backups and restore (step 6), `/readyz` and the JSON logs, the real SMTP relay, and
pyramidal TIFFs for Cantaloupe (a separate change).

---

## Step 3 — Observability foundations (`manuspectrum/observability/`)

What the image now carries: JSON logs on stdout with a `request_id`, `/readyz`, `/metrics`
(web) and `:9808/metrics` (worker), application metrics (`manuspectrum/observability/README.md`).
Nothing here is collected yet: Prometheus, Alertmanager and Grafana come with PP-6. Uses the
`dc` alias of step 2; the stack is up (step 2.4).

**What CI already proves.** The `deploy-lint` image job runs `smoke.sh observability` and
`smoke.sh readiness` on a runner. The rehearsal VM replays them on the production-shaped
stack and adds what a runner cannot show: five gunicorn workers aggregated, a worker recycled.

### 3.1 Probes

- [ ] *(service account)* `dc exec -T web curl -s -H 'Host: web' http://127.0.0.1:8000/readyz | python3 -m json.tool`
  - Expected: `"status": "ready"`, six components `postgres`, `elasticsearch`,
    `celery-broker`, `redis-broker`, `redis-cache`, `cantaloupe`, each `"status": "up"` with
    `seconds` below 2.
  - On failure: the component named `down` or `timeout` is the one to look at
    (`dc ps`, `dc logs --tail 50 <service>`); `error` gives the exception class only, the
    detail is in `dc logs web | grep readiness`.
- [ ] *(service account)* *(CI too)* `deploy/compose/smoke.sh readiness`
  - Expected: `ok: /readyz with Elasticsearch stopped`, `ok: /readyz names Elasticsearch`,
    `ok: every service is healthy`, `ok: /readyz after Elasticsearch restarted`.
  - On failure: if the 503 never comes, `/readyz` is not reading Elasticsearch (check
    `READYZ_ENABLED` in the image); if the 200 never comes back, `dc logs elasticsearch`.
- [ ] *(service account)* `dc exec -T web curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: web' -H 'X-Forwarded-For: 1.2.3.4' http://127.0.0.1:8000/metrics`
  - Expected: `404` (a proxied request never reads the probes).
  - On failure: `observability/views.relayed()` is bypassed; do not go on to step 4.

### 3.2 Metrics

- [ ] *(service account)* *(CI too)* `deploy/compose/smoke.sh observability` → only `ok:` lines.
  - On failure: the failing line names the piece (readyz, metrics, request id, JSON log,
    access log, worker metrics, task propagation).
- [ ] *(service account)* Five workers are summed: `for i in $(seq 50); do dc exec -T web curl -s -o /dev/null -H 'Host: web' http://127.0.0.1:8000/healthz; done; dc exec -T web curl -s -H 'Host: web' http://127.0.0.1:8000/metrics | grep 'view="healthz"' | grep requests_total_by_view`
  - Expected: two lines, one per `transport` label (`http` for the internal calls made here, `https` for the ones that
    came through nginx); the `http` value is ≥ 50 (not five lines per transport, not a value near 10).
  - On failure: `PROMETHEUS_MULTIPROC_DIR` is not set in the web container
    (`dc exec web env | grep PROMETHEUS`).
- [ ] *(service account)* `dc exec web sh -c 'stat -f -c %T /run/prometheus; ls /run/prometheus | head'`
  - Expected: `tmpfs`, then files `counter_<pid>.db`, `histogram_<pid>.db`, `gauge_livesum_<pid>.db`.
  - On failure: the tmpfs is missing in `compose.yaml`.
- [ ] *(service account)* Replaced workers leave no live gauge: `dc exec -T web sh -c 'kill -HUP 1'` (PID 1 is gunicorn; it replaces every
  worker gracefully; never `dc kill -s`, which Docker records as a manual stop), wait 20 s, then
  `dc exec -T web curl -s -H 'Host: web' http://127.0.0.1:8000/metrics | grep '^manuspectrum_inflight_requests '`.
  - Expected: `manuspectrum_inflight_requests 1.0` (the scrape itself), not more.
  - On failure: `child_exit` is not called (`dc exec web grep -A3 child_exit /app/gunicorn.conf.py`).
- [ ] *(service account)* Worker: `dc exec -T worker curl -s http://127.0.0.1:9808/metrics | grep -c '^manuspectrum_'`
  - Expected: a number above 0. `dc port worker 9808` → nothing (not published).
  - On failure: `dc exec worker env | grep -E 'MS_CELERY_METRICS_PORT|PROMETHEUS'`.

### 3.3 Logs

- [ ] *(service account)* `dc logs --no-log-prefix --since 10m web worker | grep '^{' | tail -n 3 | python3 -c 'import json,sys; [print(sorted(json.loads(l))) for l in sys.stdin]'`
  - Expected: each list holds `environment`, `hostname`, `level`, `logger`, `message`,
    `request_id`, `service`, `timestamp`, `trace_id`, `version`; `environment` is `rehearsal`.
  - On failure: `MS_LOG_FORMAT` overridden in `.env`, or the image predates PP-5.
- [ ] *(service account)* `dc logs --no-log-prefix --since 1h web worker | grep -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}|msiiif1\.|password=[^[]' | wc -l`
  after logging in once and using the Biblissima import once
  - Expected: `0`.
  - On failure: a logger writes personal data the redaction does not cover; record the
    line (redacted by hand) and open an issue before production.
- [ ] *(service account)* `dc logs --no-log-prefix --since 10m web | grep -c '"GET /'`
  - Expected: `0` (gunicorn writes no access log; nginx writes it, step 4.8).

### 3.4 What cannot be tested in this step

Prometheus scraping, alert rules, dashboards and the e-mail route (PP-6); the edge rules that
deny `/metrics` and `/readyz` (step 4.3), and the check that no personal data reaches
the logs after a login and a Biblissima import (step 4.8).

---

## Step 4 — nginx and TLS (`deploy/compose/nginx/`, `deploy/certs/`)

The only service that publishes ports: TLS in three modes, the edge rules of issue #45,
the rate limits, the JSON access log and the public image URLs. Uses the `dc` alias of step 2;
the stack is up (2.4) and the data of 2.9 is loaded. In this step `<vm>` is the address of the
rehearsal VM, `$PUBLIC` the first name of `DOMAIN_NAMES` (`manuspectrum.test` in the rehearsal),
`$LOG` the `NGINX_LOG_HOST_DIR` of `.env`, and `<dev origin>` an origin the loaded snapshot
was made under (`http://<host>:<port>`, never written in this repository).

**What CI already proves, and what only the rehearsal VM can.** `test_edge.sh` (inside
`check-stack.sh`, 2.1) runs every edge rule against a real nginx and a stub upstream;
`tests/test_edge_contract.py` pins those rules to the Django URLconf and the languages;
`test_acme_pebble.sh` runs the ACME flow against Pebble; the stack job runs
`smoke.sh edge` on a runner. The rehearsal VM adds what a runner cannot: TLS seen from
another machine, the browser, a real snapshot, the host log rotation and a reboot.
Rows marked **(CI too)** repeat a CI check on purpose.

### 4.1 Certificates (local CA)

- [ ] *(service account)* `make -C deploy certs-local` then `ls -l $CERTS_DIR/ca $CERTS_DIR/live`
  - Expected: `ca/` holds `ca.crt` (`0644`) and `ca.key` (`0600`); `live/` holds `fullchain.pem` and
    `privkey.pem` (`0640`); an empty `acme-webroot/`; `openssl verify -CAfile $CERTS_DIR/ca/ca.crt $CERTS_DIR/live/fullchain.pem` → `OK`;
    `openssl x509 -in $CERTS_DIR/live/fullchain.pem -noout -ext subjectAltName` lists every name of `DOMAIN_NAMES`.
    After 4.2, `dc exec nginx ls /etc/nginx/certs` → exactly `fullchain.pem privkey.pem` (no `ca.key`).
  - On failure: the script refuses a name that is neither a host name nor an IPv4 address; the
    host needs `openssl` 3.0 or later. `ca.key` never leaves the VM.
- [ ] *(service account)* `make -C deploy up`, then `dc exec -T web test -s /tmp/ca-bundle.pem && echo bundle` and
  `dc exec -T web curl -s --cacert /tmp/ca-bundle.pem -o /dev/null -w '%{http_code}\n' https://$PUBLIC/healthz`
  (`dc exec` does not see the variables the entrypoint exports, so the bundle it builds is named
  explicitly; `smoke.sh edge` does the same)
  - Expected: `bundle`, then `200`: web and worker trust `LOCAL_CA_CERT` and reach the public
    name through the nginx network alias (`PUBLIC_HOST`).
  - On failure: `LOCAL_CA_CERT` is empty or not a literal path in `.env`, or `PUBLIC_HOST` differs
    from the host name of `PUBLIC_SERVER_ADDRESS`.
- [ ] (workstation, the laptop with the browser) Copy `ca/ca.crt` only (`scp`, never `ca/ca.key`), trust it
  (`deploy/certs/README.md`, « Trusting the CA on a workstation »: system store, Firefox or NSS
  store), and add `<vm> manuspectrum.test` to `/etc/hosts`. Chrome and Chromium on Linux ignore the system
  store: `certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n manuspectrum-local -i ca.crt` (package `libnss3-tools`),
  then restart the browser.
  - At the end of the rehearsal, remove the CA from the workstation: `certutil -d sql:$HOME/.pki/nssdb -D -n manuspectrum-local`,
    `sudo rm /usr/local/share/ca-certificates/manuspectrum-local-ca.crt && sudo update-ca-certificates --fresh`,
    the Firefox authority (Settings, Certificates, Authorities, Delete) and the `/etc/hosts` line.
  - Expected: `curl -sI https://manuspectrum.test/` with no `-k` → `HTTP/2 200` or a redirect to the
    language page; the browser shows no warning and the padlock names the local CA.
  - On failure: `curl` complaining about the issuer = the CA is not trusted on this workstation;
    a name mismatch = the name in `/etc/hosts` is not in `DOMAIN_NAMES` (run `certs-local` again).

### 4.2 Ports and TLS

- [ ] (host) `nmap -p 1-65535 <vm>` → only `22/tcp`, `80/tcp` and `443/tcp` open.
  *(service account)* `docker ps --format '{{.Names}} {{.Ports}}'` → only the `nginx` line shows ports.
  - On failure: a service publishes a port in `compose.yaml`; remove it, the stack has one door.
- [ ] (workstation) `curl -sI http://manuspectrum.test/` → `301` with `Location: https://manuspectrum.test/`.
- [ ] (workstation) Unknown names are refused: `curl -sk -o /dev/null -w '%{http_code}\n' https://<vm>/`
  (an address is not in `DOMAIN_NAMES`) → `000` (handshake refused) and
  `curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: other.example' http://<vm>/` → `000` (empty reply, 444).
  - On failure: the default servers of `manuspectrum.conf.template` are missing.
- [ ] (workstation) `curl -sI https://manuspectrum.test/en/ | grep -ci '^strict-transport-security'` → `1`
  and the value is `max-age=3600`; the same count with `x-content-type-options` and
  `referrer-policy` → `1` each, `x-frame-options` → `1` (SAMEORIGIN), `permissions-policy` → `1`,
  `content-security-policy-report-only` → `1`.
  - On failure: two lines for one header = a header set both by nginx and Django (Django owns
    X-Frame-Options, nosniff and Referrer-Policy; nginx owns the others); fix the snippet.
- [ ] (workstation) `openssl s_client -connect <vm>:443 -servername manuspectrum.test -tls1_1 </dev/null` fails
  (`no protocols available` or a handshake failure); `-tls1_2` and `-tls1_3` succeed and show
  `Verify return code: 0 (ok)` with `-CAfile ca.crt`. Optional, more complete:
  `docker run --rm -ti drwetter/testssl.sh --add-ca ca.crt manuspectrum.test` from a machine with
  Docker (no external checker reaches a private network): no protocol below TLS 1.2, no weak
  cipher, HSTS present.
- [ ] *(service account)* *(CI too)* `deploy/compose/smoke.sh edge` → only `ok:` lines.
  - On failure: the failing line names the rule (publishers, redirect, headers, querysets, files,
    IIIF, rate, forged headers, access log, timeouts).

### 4.3 Edge rules (#45)

All from the workstation, name resolved to the VM. Codes are the whole expectation.

- [ ] Denied at the edge, bodyless or with the site 404 page, never proxied (no `X-Request-ID` header):
  `for p in /en/api/resource/x /fr/api/tile/x /en/api/tile-list-create/x /fr/api/tile-new-resource/x /en/silk/ /metrics /readyz; do printf '%s ' $p; curl -s -o /dev/null -w '%{http_code}\n' https://manuspectrum.test$p; done`
  → every line `404`.
  - On failure: the rule is missing from `edge-rules.conf` (a bare `/en/` prefix missing, an
    `(en|fr)` alternation not updated). `/metrics` and `/readyz` must have an empty body.
- [ ] `curl -s https://manuspectrum.test/healthz` → `ok`, `200` (liveness stays public for the probe).
- [ ] Per-address connection limit: `limit_conn perip 20` counts HTTP/2 concurrent streams, and every
  workstation behind one NAT address shares it. Measure on the real network: open the heaviest
  viewer page (4.5, Mirador on a large manuscript) from two workstations behind the same address and
  `grep -cE '"status":(429|503)' $LOG/access.log` → `0`. Record the peak; a figure near 20 means the
  value must be raised before production.
- [ ] Bypass attempts are refused: `/en//api/resource/x` with `--path-as-is` and `/en/api/%72esource/x` → `404`.
- [ ] Core routes the project keeps stay reachable: `/en/api/tiles/<uuid>` is answered by Django (has
  `X-Request-ID`), `/en/api/relatable-resources/<g>/<n>` too.
- [ ] Search exports: `/fr/api/search/export_results?format=tilecsv` → `404`, without `format` → `404`,
  `?format=geojson&format=tilecsv` → `404`, `?format=geojson&form%61t=shp` → `404`,
  `?format=tilecsv&format=geojson` → `404`; `?format=geojson` without a session cookie → `403` with the
  site's 403 page, with one → answered by Django.
  `curl -s -o /dev/null -w '%{http_code}\n' -X POST https://manuspectrum.test/fr/temp_file` → `404`
  (a GET reaches Django).
  - Accepted behaviour (`ADMIN.md`, « Search exports by visitors »): an anonymous
    `curl -s -o /dev/null -w '%{http_code} %{time_total}\n' 'https://manuspectrum.test/fr/search/export_results?format=tilecsv&total=0'`
    runs the export in the web worker (it may end in `504` after 120 s on a loaded snapshot); a second one
    from the same address while the first runs is answered `429` by nginx. This is expected today, not a fault.
    The check feeds `SearchExportSlow` only if it takes more than 60 s; if it does, silence the alert beforehand
    (`make -C deploy silence ARGS='alertname=SearchExportSlow --duration=2h --comment="acceptance"'`).
  - From the browser, the GeoJSON export is offered only with a resource-type filter set and fewer than
    2 000 results; without a filter, or above that count, the option is absent (not a fault). Filter on one
    resource type first, signed in, to test it; the `curl` forms above do not depend on it.
- [ ] `/files/uploadedfiles/<any stored name>` direct → `404` (bytes only follow `FileView`, 4.5).
- [ ] 429 after a burst on the sign-in: `for i in $(seq 7); do curl -s -o /dev/null -w '%{http_code} ' -X POST https://manuspectrum.test/en/auth/; done`
  → the first six answered by Django (any code but 429, CSRF refusals included), the seventh `429`
  with the nginx page and a `Retry-After: 60` header. Seven `GET` of the same page never give 429.
  - On failure: no 429 = `$binary_remote_addr` is the Docker bridge address for everybody
    (check `remote_addr` in the access log is the client's, 4.8) or the `auth` zone is not applied.
- [ ] *(service account)* The slowest synchronous export, measured on the loaded snapshot:
  `time curl -s -o /dev/null -b <session cookie> 'https://manuspectrum.test/fr/search/export_results?format=tilecsv&total=1'`
  - Expected: under 120 s. Record the figure; above it, open an issue to lower `SEARCH_EXPORT_LIMIT`.
- [ ] One Biblissima import of 25 items, from the browser as an editor, runs with no `429`:
  `grep -c '"status":429' $LOG/access.log` → `0` before and after it (spec §4.2).
  One `create-all` of 5 items completes: its `request_time` in the access log may exceed 90 s only
  when the upstream was slow, and there is no `504`.
- [ ] *(service account)* Annotation pacing, measured on the loaded snapshot: open a large manuscript
  in the resource editor and let the annotation counts fill in. From the nginx JSON access log, record
  the `upstream_time` p50 and p95 of `/iiifannotations` (the service time; `request_time` also
  counts the wait in the queue; the field is a string, a comma list when nginx retried). Meanwhile,
  sample the busy threads several times:
  `dc exec -T web curl -s -H 'Host: web' http://127.0.0.1:8000/metrics | grep '^manuspectrum_inflight_requests '`.
  No load script is versioned. To drive the annotation requests from a script, read the manifest from the copy
  stored in the database (`/manifest/<uuid>`) or from a manifest the site serves: a script cannot fetch the
  holding institution's manifest (Gallica answers `403` to every client that is not a browser), and the rehearsal's local CA
  does not validate public hosts.
  - Expected: about 9 in flight plus the scrape, well under 20; the `annotations_site` rate is about
    `9 / p95` per second, which keeps ~11 of the 20 threads free. When it differs from the current
    `20r/s` in `snippets/ratelimit.conf`, change it there and the « rate x service time » line of the
    `iiifannotations` comment in `snippets/edge-rules.conf`, then run `test_edge.sh` again.
- [ ] Mirador on one large manuscript (4.5): `grep -c '"status":429' $LOG/access.log` → `0` after the visit.

### 4.4 Error pages

- [ ] `curl -s https://manuspectrum.test/en/this-page-does-not-exist | grep -c '<html'` → `1` and the
  design is the site's (the 404 comes from Django here); `curl -s https://manuspectrum.test/en/api/resource/x`
  → nginx's own 404 page.
- [ ] *(service account)* `dc stop web`, then `curl -s -o /dev/null -w '%{http_code}\n' https://manuspectrum.test/en/` → `502` or
  `503` with the site's 500 page (`manuspectrum/templates/errors/500.htm`, self-contained), then
  `dc start web` → the site answers again with no nginx restart.
  - On failure: the bind of `500.htm` in `compose.yaml` is missing (`nginx -t` fails to start nginx).

### 4.4b Site announcements (`SiteNotice`, PR #206)

Admin → **Site announcements**; times are Paris time and the server caches `/api/site-notice` for 60 seconds, so a
change shows within a minute (reload after waiting). Browser in a private window as a visitor, plus the
`curl` of the API. Saving is enough: there is no « published » box. The VM clock must be right (`timedatectl`,
« How to read and record »). Delete the test announcements at the end.

- [ ] *Event with reminders*: a Maintenance announcement, display « Event with reminders », start 30 minutes
  ahead and end 30 minutes later, reminders `10m 2m`, a text in English and in French.
  `curl -s https://manuspectrum.test/api/site-notice` lists it with its start and end (UTC) and the reminders in seconds.
  - Expected: before the first reminder nothing shows; then the banner « Maintenance · Upcoming » with the date and time
    on the homepage, About, `/fr/discover`, `/fr/search` and the sign-in page, in the page language; readable on scroll
    and at 390 px width.
- [ ] Close it with the cross: it does not return on another page or in a second private window. At the next reminder,
  after a reload, it returns. At the start it reads « In progress » with the end time.
- [ ] Edit the text while it is shown: a visitor who closed it sees it again with the new text (the version changes);
  closing it again keeps it closed. Two announcements active together: the closed one stays closed and the other shows.
- [ ] At the end time the banner disappears from a page left open, and the announcement stays listed in the admin as ended.
- [ ] *Web stopped during an event*: *(service account)* `dc stop web` while an event is in progress, then
  `curl -s -o /dev/null -w '%{http_code}\n' https://manuspectrum.test/fr/` → `502` (or `503`) with the site's error page
  showing the real status code (`<div class="code" id="ms-code">502</div>`) and the announcement box above it, in the
  language of the URL. `curl -s https://manuspectrum.test/api/site-notice` still answers the announcement (nginx serves the
  snapshot of the `site_notice` volume). `dc start web` → the site answers within about a minute with no nginx restart.
  - On failure: the box is missing = the volume snapshot is not written (`SITE_NOTICE_SNAPSHOT_DIR` on `web`, README) or the
    `@site_notice_snapshot` location is missing.
- [ ] *Shown once until a date*: an Information announcement, display « Shown once until a date », a start now, an end
  later, a details link with its two labels (English and French, in the right order): a banner with no date and no
  « Upcoming », shown at once; closed, it does not return after a reload or on other pages.
- [ ] *Preview*: an announcement dated in the future is absent from the page; its **View on site** button in the admin opens
  the homepage with it shown (`/?ms-notice-preview=<id>`).
- [ ] Delete the announcements: `curl -s https://manuspectrum.test/api/site-notice` → no notice, within a minute the banners are gone.

### 4.5 Files and images

- [ ] A file download goes through `FileView`: take the link of a file-list card in the browser (`/files/<uuid>`).
  `curl -sL -o /tmp/f -w '%{http_code} %{size_download}\n' https://manuspectrum.test/files/<uuid>`
  → `200` and the size of the file on disk; the same uuid with a user who may not read it → `404`/`403`
  from Django, never the bytes. An unknown uuid → `500`: Arches' `FileView` raises
  (`SearchExportHistory.DoesNotExist`), and nginx serves its 50x page, never the bytes.
  - On failure: the 302 is returned to the client instead of being followed inside nginx
    (`@media` in `media.conf`).
- [ ] One Arches manifest, every id on the public https host:
  `curl -s https://manuspectrum.test/en/manifest/<uuid> | jq -r '.. | objects | (."@id"?, .id?) | strings' | grep -v '^https://manuspectrum.test/'`
  → empty or only external rights and homepage URLs, to be read one by one; and the same pipe ending
  `| grep -Ec '^http://|:8000|localhost|<dev origin>'` → `0`.
  - On failure: the manifest was stored before 4.10, or `CANTALOUPE_HTTP_ENDPOINT` is not
    `<PUBLIC_SERVER_ADDRESS>iiifserver/` in the web container
    (`dc exec web printenv CANTALOUPE_HTTP_ENDPOINT`): new uploads would mint dev ids.
- [ ] Image service URLs of that manifest: `… | grep '/iiifserver/' | grep -v '^https://manuspectrum.test/iiifserver/iiif/'` → empty.
- [ ] One project document: `curl -s https://manuspectrum.test/iiif/v3/annotation-collection/<doc uuid> | jq -r '.. | objects | .id? | strings' | grep -v '^https://manuspectrum.test/'`
  → only the canvas ids of the source manifests.
- [ ] One `info.json` and one tile: `curl -sI -H 'Origin: https://example.org' https://manuspectrum.test/iiifserver/iiif/2/<name>/info.json`
  → `200` and exactly one `Access-Control-Allow-Origin: *` (`grep -ci '^access-control-allow-origin'` → `1`);
  `curl -s … | jq -r '."@id"'` → `https://manuspectrum.test/iiifserver/iiif/2/<name>`;
  `…/full/!300,300/0/default.jpg` → `200`, `image/jpeg`, the same single header.
  - On failure: two `Access-Control-Allow-Origin` lines = Cantaloupe's header is not hidden in `iiifserver.conf`.
- [ ] Application routes do not get the wildcard: `curl -sI -H 'Sec-Fetch-Site: same-origin' -H 'Sec-Fetch-Mode: cors' -H 'Origin: https://example.org' https://manuspectrum.test/fr/api/explorer/search | grep -i access-control` → empty.
- [ ] The Explorer's internal APIs answer the page only (`EXPLORER_UI_ONLY=enforce`):
  `curl -si https://manuspectrum.test/en/api/explorer/search` → `403`, `Content-Type: application/json`,
  `Cache-Control: no-store`, a `Link: <https://manuspectrum.test/en/about/data#reuse>; rel="help"` header and a JSON body naming the same address;
  the same call with `-H 'Sec-Fetch-Site: same-origin' -H 'Sec-Fetch-Mode: cors'` → `200`;
  `curl -s -o /dev/null -w '%{http_code}' https://manuspectrum.test/api/explorer/series.csv?ids=<key>` is not `403` (the data products stay open);
  a call with no Fetch Metadata but `-H 'Referer: https://manuspectrum.test/en/discover'` → `200` (legacy browsers, metric reason `referer`).
  - On failure: `EXPLORER_UI_ONLY` in `.env` is `observe` or `off` (200 everywhere), or the wrong value stops web at start.
- [ ] (browser) `/en/discover` works as before (search, a document, a spectrum plot): the page's own calls carry the Fetch Metadata headers.
- [ ] (browser) « Reuse the data » opens `/en/about/data` from the footer and from the Explorer's « Share and export » panel.
- [ ] (browser) Open the manifest in the project viewer and in one external Mirador: the images display
  (no mixed-content or certificate error in the console).

### 4.6 The browser visit

(workstation, CA trusted). Each item is ticked or recorded with a screenshot.

- [ ] an XY chart in the resource editor and in a report (the bytes come through `/files/<uuid>`);
- [ ] a file download from a file-list card;
- [ ] the model page;
- [ ] Discover, then Compare with three spectra;
- [ ] one French page (`/fr/…`) and the language switch;
- [ ] the login page and a login;
- [ ] a Biblissima import of one item as an editor (the Biblissima workflow);
- [ ] the maps (OpenFreeMap Bright basemap, no Mapbox key):
  - the search map (`/fr/search`, map tab) and a Place or Document report map show the
    basemap with its credit (« OpenFreeMap © OpenMapTiles, Data from OpenStreetMap »);
  - labels follow the page language: « Allemagne », « Espagne » on `/fr/`, « Germany », « Spain »
    on `/en/`; toggling an overlay keeps the French labels;
  - an editor draws a point and a polygon on a Place card (map widget), saves, and sees them on the
    report map; popups and hover work on the search map;
  - no address search box on the maps (removed until Arches 8.2);
  - the console shows no `access token` or Mapbox error, and the Network tab no request to
    `*.mapbox.com`;
- [ ] the Network tab shows no request outside the domain (spec §6.2) except the expected third
  parties of the privacy policy (`tiles.openfreemap.org`, the holding institutions' IIIF servers,
  `iiif.unicaen.fr` on the homepage; for signed-in editors `cke4.ckeditor.com`, and
  `svc.webspellchecker.net` only if the spell checker is switched on; Google Fonts on the thesaurus page), and no 4xx or 5xx except the expected ones; the console lists
  the CSP Report-Only violations: copy them into the issue for F5.
- [ ] *CSP reports reach the server*: on any page, force a violation of `object-src 'none'` from the console:
  `document.body.append(Object.assign(document.createElement('object'), {data: 'https://csp-test.invalid/x?k=1'}))`.
  Run it in Chromium AND in Firefox: Chromium sends the Reporting API body to `report-to`, Firefox the legacy body to
  `report-uri`. In Chromium also open DevTools → Application → Reporting API: the endpoint `csp-endpoint` is listed
  (the relative URL was accepted) and the report's status is `Success` (batched: allow up to a minute). In each
  browser, within a minute `dc logs --since 5m web | grep manuspectrum.csp` shows one line with `directive` `object-src`,
  `blocked` `https://csp-test.invalid` (no path, no query) and `document` the route name of the page (never its path),
  the « CSP violations by directive » panel of the Application dashboard counts it (two in all), and the access log
  shows `POST /api/csp-report` with status `204`. `curl -s -o /dev/null -w '%{http_code}'
  https://manuspectrum.test/api/csp-report` answers `405`.
- [ ] *Very linked resource*: open the related resources graph of the resource with the most relations
  (search → a result → the graph button) with `RELATED_RESOURCES_EXPORT_LIMIT` at 300, 500 and 1000 in `.env`
  (`make -C deploy up` between two values). For each value note whether the tab stays responsive (pan, zoom,
  select a node, search in the list) and how long the graph takes to settle; keep the highest value that does
  not freeze. The report's related resources list at most that many relations per model (Arches 8.1.5 has no
  working « Load more » there; an upstream fix is proposed).
- [ ] *Map tile load*: signed in or not, open `/fr/search`, switch on several resource layers on the map, then pan and zoom
  quickly for one minute. Meanwhile, *(service account)* every 15 seconds read the open scroll contexts:
  `dc exec -T elasticsearch sh -c 'curl -s -u "elastic:$(cat /run/secrets/elastic_password)" "localhost:9200/_nodes/stats/indices/search?filter_path=**.open_contexts"'`.
  - Expected: no `500` on `/mvt/` in the access log (`grep -c '/mvt/.*"status":500' $LOG/access.log` → `0`; `429` from the
    edge `tiles` zone may appear under extreme panning, record the count), no « too many scroll contexts » in
    `dc logs web --since 5m`, no « putting on 30 second timeout », the open contexts stay low (tens, far below the 500
    allowed by `search.max_open_scroll_context`), the polygons are drawn whole and a text search still works right after.
  - On failure: the permission framework in use is not the project's (`PERMISSION_FRAMEWORK`, E20): each tile opens a scroll
    context that Arches' default framework never closes, and a map with several layers exhausts them within a minute.

### 4.7 Restart paths

- [ ] *(service account)* `make -C deploy down up`, then `systemctl restart docker` (admin, `sudo`) and
  `dc up -d --force-recreate web`: after each, the site answers again at `https://manuspectrum.test/healthz`
  within a few minutes and `dc ps nginx` shows nginx without restart of its own for the last case
  (dynamic `resolve` of `web` and `cantaloupe`).
- [ ] After a host reboot (2.8): nginx is back and `make -C deploy smoke` and `smoke.sh edge` give only `ok:`.

### 4.8 Logs

- [ ] (host or VM, admin with read rights on `$LOG`, or the service account) The access log is JSON,
  one object per line: `tail -n 3 $LOG/access.log | python3 -c 'import json,sys; [print(sorted(json.loads(l))) for l in sys.stdin]'`
  → each list holds `bytes`, `host`, `method`, `protocol`, `referer`, `remote_addr`, `request_id`,
  `request_time`, `status`, `time`, `tls`, `upstream_status`, `upstream_time`, `uri`, `user_agent`;
  `remote_addr` is the workstation's address, not the bridge.
- [ ] No query string, no personal data: `grep -cE '\?|password=|token=|@[A-Za-z0-9.-]+\.[a-z]{2,}' $LOG/access.log` → `0`
  (`password=` and not `password`: static files such as `password_reset.js` legitimately carry the word).
  - On failure: `$uri` and `$log_uri` in `logging.conf`; a log line must never carry `$request` or `$args`.
- [ ] Reset token redacted: visit one password-reset link, then
  `grep -c '/reset/\[redacted\]' $LOG/access.log` → at least `1` and the token appears nowhere
  in the file.
- [ ] The request id joins the logs: take the `X-Request-ID` of `curl -sI https://manuspectrum.test/en/no-such-page`
  (a 404: the application logs only the requests that have something to say, an error or a 404), then
  `grep <id> $LOG/access.log` → one line, and `dc logs --no-log-prefix web | grep <id>` → the
  application line of that request.
- [ ] Deferred check 3.3: after one login and one Biblissima import,
  `dc logs --no-log-prefix --since 1h web worker | grep -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}|msiiif1\.|password=[^[]' | wc -l`
  → `0`; the same grep, without the e-mail alternative, on `dc logs --no-log-prefix --since 1h nginx` → `0`.
  - On failure: record the line (redacted by hand) and open an issue before production.
- [ ] `dc logs --no-log-prefix --since 10m web | grep -c '"GET /'` → `0` (the access log is nginx's).
- [ ] *(service account or root)* `error.log` is not redacted: rate-limit lines are at `notice` and do not
  reach it (`grep -c 'limiting' $LOG/error.log` → `0` after 4.3's burst), but upstream-error lines
  (for instance after `dc stop web`, 4.4) still carry the raw request line, query string and reset
  token included. The protection is the directory mode, not the
  file's (nginx creates its logs `0644`; only rotated files are `0640`): `stat -c %a <NGINX_LOG_HOST_DIR>`
  → `750`. Rotated thirty days with the access log (4.9).

### 4.9 Rotation

- [ ] (admin) The playbook has installed `/etc/logrotate.d/manuspectrum-nginx` (`root:root`, `0644`, rendered by the
  `app` role from `deploy/logrotate/manuspectrum-nginx.in`; logrotate ignores a file writable by group or others). Force
  a rotation: `sudo logrotate -f -s /tmp/state /etc/logrotate.d/manuspectrum-nginx`.
  - Expected: dated, then compressed (next run) files appear in `$LOG`, a new `access.log` is
    created `0640` for the service account, and nginx keeps writing to it with no restart
    (`dc ps nginx` uptime unchanged, a new request lands in the new file). `rotate 30`: thirty days.
  - On failure: `su` line missing (logrotate refuses a directory not owned by root), or the
    `nginx -s reopen` did not reach the container (`docker ps --filter label=com.docker.compose.service=nginx`).
    The rule never uses `docker kill --signal`: Docker would record a manual stop and `unless-stopped` would no
    longer restart nginx at the next boot. After a rotation, `docker inspect -f '{{.State.Status}} {{.HostConfig.RestartPolicy.Name}}' $(dc ps -q nginx)`
    stays `running unless-stopped` and nginx comes back after a reboot of the VM.
- [ ] *(service account)* `docker inspect -f '{{.HostConfig.LogConfig}}' $(dc ps -q nginx)`
  → `{json-file map[max-file:5 max-size:10m]}` (nginx's own stdout stays bounded).

### 4.10 Data steps after loading a snapshot

The snapshot holds the origins of the development hosts in concept identifiers, controlled-list
URIs, IIIF manifests and the tiles that reference them. Run once, before the site is shown.
Commands run as the service account (no admin account runs `docker`).

- [ ] *(service account)* List the development origins the snapshot carries:
  `make -C deploy manage ARGS="rewrite_dev_origin --list"` (writes nothing; one line per origin with its counts per
  family. The manifests hold one more than the concept identifiers: the Cantaloupe port of the development host).
- [ ] *(service account)* Dry run, one `--from` per origin listed above (up to four
  development origins):
  `make -C deploy manage ARGS="rewrite_dev_origin --dry-run --from <dev origin 1> --from <dev origin 2> --from <dev origin 3> --from <dev origin 4>"`
  - Expected: a count per family (concepts, lists, manifests, tiles), nothing written, a
    line `anomaly: N blob: URL(s)…`. The blob URLs are dead browser object URLs, counted and never
    rewritten: record N, it is not an error.
  - On failure: all counts `0` = the origins are mistyped (scheme, port, trailing slash).
- [ ] *(service account)* The same command without `--dry-run`, then again with `--dry-run` → every count `0`.
- [ ] *(service account)* File entries written outside the upload widget (package, CSV or ETL import, snapshot) lack their
  metadata and licence: `make -C deploy manage ARGS="repair_file_metadata"` (dry run, counts), then
  `make -C deploy manage ARGS="repair_file_metadata --apply"`, then the same dry run → nothing left to fix.
- [ ] *(service account)* Elasticsearch holds copies: `make -C deploy manage ARGS="es reindex_database"`
  (duration and memory: 2.10), then `make -C deploy smoke` → only `ok:`.
- [ ] *(service account)* No origin of development is left: `dc exec -T postgres sh -c 'psql -U "$POSTGRES_USER" <PGDBNAME> -Atc "select count(*) from iiif_manifests where manifest::text like '"'"'%<dev origin 1>%'"'"'"'` → `0` (repeat per origin).
  Re-run 4.5: the manifest checks now give an empty list on a manifest stored in the snapshot.
- [ ] *(service account)* Anonymous notifications of a database that ran with
  `RESTRICT_CELERY_EXPORT_FOR_ANONYMOUS_USER=False` (#45):
  `make -C deploy manage ARGS="shell -c \"from arches.app.models.models import UserXNotification as N; print(N.objects.filter(recipient__username='anonymous').count())\""` → `0`.
  Otherwise record the count, delete them with the same shell and `.delete()`, and re-run.

### 4.11 What cannot be tested in rehearsal

ACME against Let's Encrypt: the domain must resolve publicly, so the first real run is at go-live,
staging first (`ACME_SERVER` default) then production; Pebble covers the flow in CI
(`test_acme_pebble.sh`). A certificate trusted by every browser without a local CA, public DNS,
the external probe (PP-9), fail2ban (PP-8), the Grafana location (PP-6), and the installation of
the host logrotate and certificate-renewal units (installed by the Ansible `app` role; their content
is checked by the tests above).

### 4.12 Before production (nginx and TLS)

- [ ] `CERT_MODE=acme`, `ACME_EMAIL` set, `ACME_SERVER` still on staging: `make -C deploy cert-init` succeeds
  (staging certificate), then the production directory and `make -C deploy cert-init CERTBOT_ARGS=--force-renewal`.
- [ ] `LOCAL_CA_CERT` empty, `PUBLIC_SERVER_ADDRESS` and `PUBLIC_HOST` set to the real name,
  `CANTALOUPE_HTTP_ENDPOINT` follows (`<PUBLIC_SERVER_ADDRESS>iiifserver/`, set by Compose).
- [ ] Raise `HSTS_MAX_AGE` to `31536000` after one stable week.
- [ ] 4.10 run on the production database, with the origins of the snapshot as `--from`.
- [ ] The host logrotate file and the renewal timer are installed by `site.yml` and `systemctl list-timers` shows the timer.

---

## Step 5 — Secrets (`deploy/SECRETS.md`)

The five secret files, their copy in the project's password manager (Bitwarden), their restore and
their rotation. Uses the `dc` alias of step 2 and the same convention: *(service account)* commands
run after `sudo -iu manuspectrum` and `cd ~/manuspectrum`. Start from the installed stack of step 2.
Record where the vault item lives, never a value.

**What CI already proves.** `check-stack.sh` runs the `secret-set` and `secrets-check` tests (values
reach no argument, output or temporary file; modes; refusals; the terminal path), `test_compose.py`
(every secret has its inventory row and its Make targets), the gitleaks tests, and the `secret-scan`
workflow scans every pull request and its commits. The `deploy-lint` image job proves the strict
`check --deploy` probe and a real start through the guard. What follows proves them on the
production-shaped VM, and the rotations, which CI does not run.

### 5.1 The startup guard

- [ ] *(service account)* `dc run --rm --no-deps -T web manage check --deploy --tag security --fail-level WARNING`
  → `System check identified no issues (… silenced).` **(CI too)**
- [ ] *(service account)* `dc logs web | grep -c 'deployment checks failed'` → `0`.
  - On failure: the output names the check id (`security.W…`); a weak or development
    `SECRET_KEY`, a missing secure-cookie setting or a debug flag in `.env` are the usual causes.

### 5.2 The secrets and the vault item

- [ ] *(service account)* `make -C deploy secrets-check` → `directory: ok` and five `<name>: ok` lines,
  exit 0. Break one on purpose and watch it fail, then restore it: `chmod 600 "$SECRETS_DIR/pg_password"`
  → `pg_password: mode is 600, expected 444`, exit 1; `chmod 444` → ok again.
- [ ] The vault item `ManuSpectrum <host> secrets` exists in the shared collection, with one hidden
  field per name (`pg_password`, `elastic_password`, `django_secret_key`, `email_password`,
  `admin_password`), filled from the files (`cat "$SECRETS_DIR/<name>"`, in a terminal nobody
  watches). Both administrators open it; each knows where their recovery code is kept (do not read it).
  Record the item's location in the follow-up artifact.
  - On failure: an administrator cannot see the item: share the collection, not the item.

### 5.3 Restore drill

- [ ] *(service account)* Move the five files aside, inside `SECRETS_DIR`:
  `mkdir "${SECRETS_DIR:?}/aside" && mv "${SECRETS_DIR:?}"/{pg_password,elastic_password,django_secret_key,email_password,admin_password} "${SECRETS_DIR:?}/aside/"`
  → `make -C deploy secrets-check` now reports five `missing`, exit 1.
- [ ] *(service account)* For each of the five names,
  `make -C deploy secret-set NAME=<name>`, pasting the value from the vault at the prompt (typed twice,
  nothing is echoed). For `email_password`, Enter twice. Each prints `<name>: written`.
- [ ] *(service account)* `make -C deploy secrets-check` → all `ok`. A second `secret-set NAME=pg_password`
  with the same value → `pg_password: kept (same value)`; with another value → refused, with `FORCE=yes`
  in the message.
- [ ] *(service account)* `for f in pg_password elastic_password django_secret_key email_password admin_password; do cmp "$SECRETS_DIR/$f" "$SECRETS_DIR/aside/$f" && echo "$f identical"; done`
  → five `identical`.
- [ ] *(service account)* `make -C deploy down up`, then `deploy/compose/smoke.sh check` → only `ok:` lines.
- [ ] *(service account)* `rm -rf "${SECRETS_DIR:?}/aside"` (the files are `0444`: plain `rm -r` asks once per file); `git status --short deploy/compose` → empty.
  - On failure: `cmp` differs = the vault holds a different value, fix the vault or the file before going on.

### 5.4 Rotation drills

In this order, each with the procedure of `SECRETS.md` section 6, each followed by
`deploy/compose/smoke.sh check` → only `ok:` lines, then the vault field updated.

- [ ] Django key. Before: sign in to the rehearsal site in a browser. After: that browser session is logged out.
- [ ] Elasticsearch password. After `down up`: `dc ps elasticsearch` shows `healthy`.
  - On failure: the API call answered 401 = the mounted file no longer matches what Elasticsearch stores;
    reset it with `dc exec elasticsearch bin/elasticsearch-reset-password -u elastic -i` and follow
    « Which value to type » in `SECRETS.md`.
- [ ] PostgreSQL password. After: `dc logs postgres --since 10m | grep -cFf <(head -c 12 "$SECRETS_DIR/pg_password")`
  → `0` (the value is not in the logs).
  - On failure: `web` cannot connect after `down up` = the role was not changed; run the block again (it keeps an existing `.new` file and stops at the first failing step).
- [ ] Admin password: `make -C deploy secret-set NAME=admin_password FORCE=yes`, `make -C deploy admin-password`;
  signing in as `admin` works with the new value and is refused with the old one.
- [ ] `make -C deploy secrets-check` → all `ok`; no `*.new` file is left in `SECRETS_DIR`.

### 5.5 The commit hook

- [ ] In a clone with Docker: `pre-commit install`. On a throwaway branch, stage a file holding a fake token
  generated on the spot (`ghp_` followed by 36 random letters and digits) and `git commit -m probe` → the
  commit is refused by `gitleaks` with a redacted finding; `git log --oneline -1` shows no new commit.
  Delete the branch. `SKIP=gitleaks git commit` is only for a deliberate, reviewed case. **(CI too:**
  `test_gitleaks.sh` runs this through `pre-commit run`.)

### 5.6 What cannot be tested in rehearsal

The real production vault item and its two administrators; the Grafana password (PP-6); Ansible (PP-8); GitHub secret scanning and push protection (repository settings).

### 5.7 Before production

- [ ] The production host runs `make -C deploy secrets` itself; no rehearsal file is copied to it.
- [ ] Its vault item is filled and both administrators opened it (5.2).
- [ ] Both administrators have run 5.3 once (on the rehearsal VM).
- [ ] GitHub secret scanning and push protection are enabled on the repository (repository owner), and the
  `secret-scan` check is green on the pull request.
- [ ] `make -C deploy secrets-check` on the production host → all `ok`.

---

## Step 6 — Backups (`deploy/BACKUP.md`)

The nightly backup, the weekly restore test, the restore of one file or of the whole stack, and the
moving-day procedure, played on the rehearsal VM with the dev snapshot loaded. Uses the `dc` alias of
step 2 and the same convention: *(service account)* commands run after `sudo -iu manuspectrum` and
`cd ~/manuspectrum`. Start from the installed stack of step 2 **with the dev snapshot loaded (2.9)**
and the secrets of step 5. Record every duration and size asked for: they are written into `BACKUP.md`
before production. Never record a secret value.

**What CI already proves.** `check-stack.sh` runs the stub tests of the scripts (`test_backup.sh`,
`test_restore*.sh`, the library shared with `load-snapshot.sh`), the restic round trip
(`test_restic_roundtrip.sh`), the unit checks (`deploy/systemd/tests/test_units.sh`: `systemd-analyze
verify` on the rendered pairs, the calendars) and `test_compose.py` (the pinned `restic` service, the
secret, the documented variables). The `deploy-lint` image job runs, on a runner, `make backup`,
`make restore-test` (every table equal to the manifest), then `smoke.sh lose`, `make restore` and
`smoke.sh survived`. What follows proves them on the production-shaped VM, with real data, real
timings and the systemd timers, which CI does not run.

### 6.1 Setup

- [ ] *(service account)* Create the three directories, owned by the service account:
  `install -d -m 0700 "$(grep ^BACKUP_DUMP_DIR= deploy/compose/.env | cut -d= -f2)" "$(grep ^RESTIC_REPOSITORY_DIR= deploy/compose/.env | cut -d= -f2)"`
  (`make -C deploy backup-init`, below, adds `latest/` and `tmp/` under the first one)
  and, when `make up` has not created it already, `install -d -m 0755 "$(grep ^METRICS_TEXTFILE_DIR= deploy/compose/.env | cut -d= -f2)"`, then
  `stat -c '%a %U' <each directory>` → `700 <account>`, `700 <account>`, `755 <account>`
  (`<account>` is the output of `id -un`).
  - On failure: the repository directory is on the network filesystem: a mount that squashes the owner
    shows another user; fix the export or the mount options (step 1.3) before going on.
- [ ] *(service account)* `grep -E '^(BACKUP_DUMP_DIR|RESTIC_REPOSITORY_DIR|METRICS_TEXTFILE_DIR)=' deploy/compose/.env`
  → three lines, the first and the third under the service account's home, the second on the network
  filesystem (the example values of `.env.example` are paths, not production values).
  - On failure: a missing key makes `docker compose config` fail for every command, with a message
    naming the variable (`BACKUP_DUMP_DIR`...); add it and run again.
- [ ] *(service account)* `make -C deploy secrets` → `restic_password: created`, the five others
  `kept`. Then `make -C deploy secrets-check` → `directory: ok` and six `<name>: ok` lines, exit 0.
  - On failure: `restic_password: shorter than 32` = the file was typed by hand; delete it and run
    `make -C deploy secrets` again (before the first backup only).
- [ ] The vault item `ManuSpectrum <host> secrets` has a field `restic_password`, filled from
  `cat "$SECRETS_DIR/restic_password"` (5.2). Both administrators see it.
  - On failure: stop here. A backup whose password is not in the vault cannot be read after a loss of
    the VM.
- [ ] *(service account)* `make -C deploy backup-init` → `repository created`, exit 0, and the line
  telling that the password must be in the vault. Run it again → `repository exists and opens`.
  `stat -c '%a %U' "$BACKUP_DUMP_DIR"/latest "$BACKUP_DUMP_DIR"/tmp` → `700 <account>` twice (`tmp/` is
  restic's temporary directory; without it every `make backup` fails at the saving step).
  - On failure: `restic init failed` with a permission error = the repository directory is not
    writable by the service account (first check, above); `does not open: wrong restic_password?` =
    the repository was created with another password: take it from the vault.

### 6.2 First backup, timed

- [ ] *(service account)* In another terminal, start `docker stats` (below), then
  `time make -C deploy backup TAG=nightly` → nine `backup: step n/9` lines, `done: tag nightly`, exit 0.
  Record the duration. While it runs, in the second terminal:
  `while sleep 5; do docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep -i restic; done`
  → record the peak memory of the restic container (the capacity review reserves 150–400 MB).
  - On failure: the line naming the failed step is the last `backup:` line, then make's
    `*** [...] Error N` line: `N` is the script's status (1 a failed step, 2 a wrong invocation or
    `METRICS_TEXTFILE_DIR` found before anything ran; the message names the variable), and make itself
    exits 2 whatever `N` is. Read
    "When things go wrong" in `BACKUP.md`; a failed run changes no copy except the log and the
    `manuspectrum_backup.prom` metric.
- [ ] *(service account)* `ls -l "$BACKUP_DUMP_DIR"/latest` (the value of the `.env` key) → four files,
  `db.dump`, `globals.sql`, `manifest.json`, `env`, each `-rw-------`.
- [ ] *(service account)* `jq .counts.tiles "$BACKUP_DUMP_DIR"/latest/manifest.json` → the number of
  tiles of the dev snapshot (order of 115 000); compare with
  `dc exec postgres psql -U <db user> -d <db> -tAc 'select count(*) from tiles'` → the same number.
  - On failure: a different count after a load means a write happened between the two (stop the
    application, `dc stop web worker beat`, and compare again).
- [ ] *(service account)* `make -C deploy restic ARGS=snapshots` → one snapshot, host `manuspectrum`,
  tag `nightly`. `make -C deploy restic ARGS="ls latest" | grep -c previous-` → `0`
  (the aside directories of a load are excluded). `make -C deploy restic ARGS="ls latest /backup/secrets"`
  → the five secret files and no `*.new`, no `aside` and no `restic_password` (the vault holds it).
- [ ] *(service account)* `cat "$METRICS_TEXTFILE_DIR"/manuspectrum_backup.prom` → `manuspectrum_backup_failed 0`
  and a recent attempt timestamp; `manuspectrum_backup_success.prom` holds the success timestamp, the
  duration and `manuspectrum_backup_dump_bytes`. `stat -c %a` on both → `644`.
- [ ] Record the repository size: `du -sh "$RESTIC_REPOSITORY_DIR"` (the repository directory, **never** the
  mount root, which holds the other projects' data), and `make -C deploy restic ARGS="stats --mode raw-data"`.

### 6.3 Second backup, deduplication

- [ ] *(service account)* `make -C deploy restic ARGS="stats --mode raw-data"` (before), then
  `time make -C deploy backup TAG=manual` → nine steps, `done`; `stats --mode raw-data` again (after).
  Record the duration and the added size. Expected: seconds to minutes and a few megabytes (an unchanged
  dump re-chunks almost entirely to existing data); the retention and the repository check are skipped
  (`step 9/9: retention and check skipped (tag manual)`).
  - On failure: an added size close to the first backup's means the dump is not deduplicating (a changed
    compression or a changing header) or the media is re-read as new: note it, it decides the nightly
    network cost; run it a third time to separate the two.
- [ ] `make -C deploy restic ARGS=snapshots` → two snapshots, tags `nightly` and `manual`.

### 6.4 Restore test

- [ ] *(service account)* `time make -C deploy restore-test` → checksums verified, `restore-test: N tables,
  every count equal to the manifest`, `restic check --read-data-subset=10%` without error, exit 0.
  Record the duration.
  - On failure: a line `FAIL:` names the step. A table whose count differs means the dump and its
    manifest disagree: do not trust that snapshot, run `make -C deploy backup` again and test the new
    one. A checksum mismatch means copy A or the snapshot is damaged (`BACKUP.md`, "When things go
    wrong").
- [ ] *(service account)* `cat "$METRICS_TEXTFILE_DIR"/manuspectrum_restore_test.prom` →
  `manuspectrum_restore_test_failed 0`; `manuspectrum_restore_test_success.prom` holds the duration.
- [ ] *(service account)* `dc exec postgres psql -U <db user> -lqt | grep -c restoretest` → `0` (the scratch
  database `<db>_restoretest` is dropped), and `dc exec postgres psql -U <db user> -d <db> -tAc 'select count(*) from tiles'`
  still returns the live count (the live database was not touched).
  - On failure: a leftover `<db>_restoretest` after a killed run is dropped by the next run; if it stays,
    `dc exec postgres dropdb -U <db user> <db>_restoretest`.

### 6.5 One file

- [ ] *(service account)* Choose an upload: `f=$(find "$MEDIA_HOST_DIR/uploadedfiles" -type f | head -1)`;
  `sha256sum "$f"` (note it) and open the image in the browser (a report page showing it). Delete it:
  `rm "$f"`; the browser now shows a broken image or a 404 for it.
- [ ] *(service account)* `make -C deploy restore-files RESTIC_SNAPSHOT=latest INCLUDE=/backup/media/uploadedfiles/<relative path of $f> TARGET=$HOME/restore-one`
  (`TARGET` does not exist yet) → `done: copy what you need from …; the running stack was not touched`,
  and `sha256sum $HOME/restore-one/backup/media/uploadedfiles/<relative path>` → the sum noted above.
  - On failure: `TARGET must be absolute, not exist or be empty` or `inside the live uploads` = pick
    another directory; a path with `..` is refused on purpose.
- [ ] *(service account)* Copy it back: `install -m 0640 $HOME/restore-one/backup/media/uploadedfiles/<relative path> "$f"`;
  reload the page → the image displays. `rm -r $HOME/restore-one`.

### 6.6 Disaster drill, timed

- [ ] *(service account)* `deploy/compose/smoke.sh mark` → `ok: markers written (…)`, then
  `make -C deploy backup TAG=manual` → `done` (the snapshot holds the marker), then
  `deploy/compose/smoke.sh lose` → the PostgreSQL marker row and the uploads marker are deleted, and
  `deploy/compose/smoke.sh survived` now fails.
- [ ] *(service account)* `time make -C deploy restore RESTIC_SNAPSHOT=latest CONFIRM=yes ERASURES_CHECKED=yes`
  → fifteen `restore: step n/15` lines, then `done: snapshot latest is restored. Replay the erasure
  requests …`. Record the total duration and the duration of step 13 (the reindex) from the log
  timestamps; the share of the reindex is the part that grows with the data.
  - On failure: a step that fails before step 4 changed nothing (checksums, migrations, Arches version,
    free space are checked first); from step 4 on, the log names the aside directory and the undo
    command is below. `not enough free space` = the staged uploads need room under `MEDIA_HOST_DIR`.
- [ ] *(service account)* `deploy/compose/smoke.sh survived` → `survived`; `deploy/compose/smoke.sh check` →
  only `ok:` lines. In the browser: a resource report opens, a IIIF image of an upload displays
  (Cantaloupe saw the new `uploadedfiles/`), search returns results (the reindex ran).
  - On failure: images 404 while the files exist = the uploads swap lost Cantaloupe's view of the
    bind mount: `make -C deploy restart` and look at `dc logs cantaloupe`; record it, it is unverified
    fact 7 of the plan.
- [ ] *(service account)* Undo it. The last log line names the aside directory:
  `ls -d "$MEDIA_HOST_DIR"/previous-*` → its newest entry. `make -C deploy restore ASIDE=<that directory> CONFIRM=yes ERASURES_CHECKED=yes`
  → fifteen steps, `done: <directory> is restored`; `smoke.sh check` → only `ok:` lines, and the counts
  are those of before the drill. Then restore `latest` again (the same command as the drill) and
  `smoke.sh check` → `ok:`.

### 6.7 Refusals

- [ ] *(service account)* `make -C deploy restore RESTIC_SNAPSHOT=latest` → refused (`run again with CONFIRM=yes`),
  the script's `restore: FAIL: ...` line then make's `Error 1`, nothing changed.
  `make -C deploy restore RESTIC_SNAPSHOT=latest CONFIRM=yes` → refused, the
  message names `ERASURES_CHECKED=yes` and the « Personal data » section, then make's `Error 2`
  (`make` itself exits 2 in both cases; the script's own status is the `Error N` number). With both `RESTIC_SNAPSHOT`
  and `ASIDE` → refused.
- [ ] *(service account)* In a second terminal start `make -C deploy backup TAG=manual`; in the first, at once,
  `make -C deploy restore RESTIC_SNAPSHOT=latest CONFIRM=yes ERASURES_CHECKED=yes` → refused immediately
  (`another backup or restore is running`), the backup is not disturbed and ends `done`.
- [ ] *(service account)* Stale lock: start a backup, then `docker kill` its `restic` container
  (`docker ps --filter name=restic -q`) during step 8. The next `make -C deploy backup` either proceeds
  (restic waits up to 30 minutes, then reports the lock) or fails with the lock message that
  `BACKUP.md` explains; `make -C deploy restic ARGS=unlock` clears it, then the backup ends `done`.

### 6.8 A failure is visible

- [ ] *(service account)* `chmod 000 "$RESTIC_REPOSITORY_DIR"`, then `make -C deploy backup TAG=manual` →
  make's `Error 1` after a `FAIL:` line at the saving step (make exits 2); `manuspectrum_backup.prom` holds `manuspectrum_backup_failed 1`;
  `manuspectrum_backup_success.prom` is unchanged (`stat -c %Y` before and after).
- [ ] *(service account)* `chmod 0700 "$RESTIC_REPOSITORY_DIR"`, then `make -C deploy backup TAG=manual` →
  `done`, `manuspectrum_backup_failed 0`, the success file renewed.
  - On failure: a root-squashing mount may ignore `chmod 000`; use `chattr`-free alternatives only on a
    local test directory, or note the check as not testable there.

### 6.9 Timers

- [ ] The units are installed by `ansible-playbook site.yml` (`app` role; `BACKUP.md`, "Setup on a host", step 4
  describes the same by hand). `systemd-analyze verify /etc/systemd/system/manuspectrum-backup.service /etc/systemd/system/manuspectrum-backup.timer /etc/systemd/system/manuspectrum-restore-test.service /etc/systemd/system/manuspectrum-restore-test.timer`
  → no output.
  - On failure: a `@…@` left in a unit means a placeholder was not substituted; `ansible-playbook render.yml` and the Ansible tests catch it.
- [ ] `bash deploy/systemd/tests/test_units.sh` → only `ok` lines. **(CI too)**
- [ ] `systemctl list-timers 'manuspectrum-*'` → `manuspectrum-backup.timer` (next run 02:00 of the coming
  night) and `manuspectrum-restore-test.timer` (next run Sunday 05:30). `systemctl show -p Persistent manuspectrum-backup.timer manuspectrum-restore-test.timer`
  → `Persistent=yes` twice.
- [ ] `sudo systemctl start manuspectrum-backup.service` (waits for the end), then
  `journalctl -u manuspectrum-backup.service --since '15 min ago'` → the nine steps and `done`;
  `systemctl show -p Result -p ExecMainStatus manuspectrum-backup.service` → `Result=success`, `ExecMainStatus=0`;
  the success metric timestamp is renewed. Same for `manuspectrum-restore-test.service`.
- [ ] Missed-run catch-up (the host was off at 02:00): with the timer enabled, `sudo systemctl poweroff` the VM
  in the evening, power it on after 02:00, then `systemctl list-timers manuspectrum-backup.timer` → the
  `LAST` column shows a run at boot time, and `systemctl show -p Result manuspectrum-backup.service` →
  `Result=success` once it ends.
  - On failure: no catch-up after a boot past 02:00 = `Persistent=true` is missing from the installed
    timer (`systemctl cat manuspectrum-backup.timer`).
- [ ] `sudo reboot`, then, once the stack is up: `systemctl list-timers 'manuspectrum-*'` → both timers still
  listed with a next run; `systemctl is-enabled manuspectrum-backup.timer manuspectrum-restore-test.timer`
  → `enabled` twice. The next morning: `journalctl -u manuspectrum-backup.service` shows the 02:00 run,
  and it ended before the 04:50 reboot (record its start and end); the metric `manuspectrum_backup_last_success_timestamp_seconds`
  is from that night.
  - On failure: the 02:00 run is killed at `TimeoutStartSec=2h30min` = the backup is too slow for the
    window; record the duration of 6.2 and decide before production (`BACKUP.md`, "Daily operation").

### 6.10 Moving-day drill

Played on the same rehearsal VM, as the procedure of `BACKUP.md`, "Moving to a new host", with the vault
as the only memory.

- [ ] *(service account)* Note `sha256sum "$SECRETS_DIR/restic_password"`. Move the secrets aside as in
  5.3, **including** `restic_password`: `mkdir "${SECRETS_DIR:?}/aside" && mv "${SECRETS_DIR:?}"/*_password "${SECRETS_DIR:?}/django_secret_key" "${SECRETS_DIR:?}/aside/"`.
  `make -C deploy backup-init` now fails (the file is missing).
- [ ] *(service account)* `make -C deploy secret-set NAME=restic_password`, pasting the value **from the vault**
  → `restic_password: written`. `make -C deploy backup-init` → `repository exists and opens` (it also creates `latest/` and `tmp/` under
  `BACKUP_DUMP_DIR`, which the `restore-files` run below binds; on a host where they are missing, every restic run
  fails with `run make -C deploy backup-init`).
  `make -C deploy secrets` → the other files created (`created`), `restic_password` `kept`.
  - On failure: `does not open` = the vault holds another value than the repository's: this is the failure
    the vault field exists to prevent; fix the vault from the file in `aside/` and note it.
- [ ] *(service account)* Pull the old secrets and the old `.env` into a separate directory:
  `make -C deploy restore-files INCLUDE=/backup/secrets TARGET=$HOME/moving-secrets` and
  `make -C deploy restore-files INCLUDE=/backup/db/env TARGET=$HOME/moving-env` →
  `cmp $HOME/moving-secrets/backup/secrets/django_secret_key "$SECRETS_DIR/aside/django_secret_key"`
  identical, and `diff $HOME/moving-env/backup/db/env deploy/compose/.env` shows only the differences
  you expect. Neither command touched `SECRETS_DIR`.
- [ ] *(service account)* Restore the secrets that must be kept with `make -C deploy secret-set NAME=<name>`
  (5.3), then `make -C deploy restore RESTIC_SNAPSHOT=latest CONFIRM=yes ERASURES_CHECKED=yes` →
  fifteen steps, `done`; `smoke.sh check` → only `ok:` lines; `make -C deploy secrets-check` → all `ok`.
  `SECRETS_DIR` and `.env` are what the operator put there, **not** what the snapshot held
  (`restore` never writes them).
- [ ] *(service account)* The first passes after a restore only send notices: `make -C deploy manage ARGS="prune_workflow_history"`,
  `anonymise_inactive_accounts` and `release_expired_embargoes` (dry runs) show who will be warned, and nothing cleaned,
  anonymised or due (a run past its delay gets both notices the same day and is cleaned a week later).
- [ ] *(service account)* `rm -r $HOME/moving-secrets $HOME/moving-env "${SECRETS_DIR:?}/aside"`; then
  `make -C deploy backup` → `done` (the first backup on the restored stack).

### 6.11 What cannot be tested in rehearsal

TSM (copy C) and its activation for the VM; the hosting provider's NFS snapshots (`.snapshot/`) and their
retention; the production volume of media (timings and repository size scale with it); the PP-6 alerts
(`BackupFailed`, `BackupMissing`, `RestoreTestFailed`, `RestoreTestMissing`) until node_exporter reads the
textfile directory; PP-10's `TAG=pre-update` backup in the update procedure.

### 6.12 Before production

- [ ] The production vault item has the field `restic_password`, filled before the first backup; both
  administrators see it (6.1).
- [ ] TSM activation is requested from the hosting provider for the production VM (so that `/home`, copy A,
  leaves the VM), and its answer is recorded in the follow-up artifact.
- [ ] Ask Huma-Num for the TSM retention (how long a copy of `/home` is kept) and record it in `BACKUP.md`,
  "Personal data": the twelve-month bound holds for copy B only; copy C follows that retention.
- [ ] `ls -l /data/.snapshot` (or the provider's snapshot directory of the network filesystem) is read and
  its retention is recorded in `BACKUP.md`, "Restore one file".
- [ ] `make -C deploy backup-init` is done on the production repository; the first nightly run is seen
  `failed 0`, with its duration; `make -C deploy restore-test` run once there (6.4).
- [ ] The timings and sizes of 6.2 to 6.6 are written into `BACKUP.md`.
- [ ] The units are installed by `ansible-playbook site.yml` and `systemctl list-timers 'manuspectrum-*'`
  lists both (6.9).

## Step 7 — Monitoring (`deploy/OBSERVABILITY.md`)

Prometheus, Alertmanager, Grafana and the exporters, the alert e-mails and the monthly report, played on the
rehearsal VM with the stack of step 2, the secrets of step 5 and the backups of step 6. Same conventions:
*(service account)* commands run after `sudo -iu manuspectrum` and `cd ~/manuspectrum`; `dc` is the Compose alias
of step 2. A rehearsal has no mail relay: it uses the Mailpit profile (`COMPOSE_PROFILES=observability,mailpit`,
`EMAIL_HOST=mailpit`, `EMAIL_PORT=1025`), whose API is read from the `web` container (same network; the
busybox `wget` of `prometheus` fails with `bad address` when the host `resolv.conf` has `search .`):
`dc exec -T web curl -fsS http://mailpit:8025/api/v1/messages`.

**Reading a mail link.** Never copy a link from a terminal display or from the raw source of a mail: the text part
is quoted-printable, which cuts long lines with `=` and a line break and writes `=` as `=3D`, and a link cut or
altered that way is refused (an activation or reset link answers `410`). Print the decoded text through the API;
its `Text` field is already decoded. List the messages, then print one:
`dc exec -T web curl -fsS http://mailpit:8025/api/v1/messages | python3 -c 'import json,sys; [print(m["ID"], m["Subject"]) for m in json.load(sys.stdin)["messages"]]'`
`dc exec -T web curl -fsS http://mailpit:8025/api/v1/message/<ID> | python3 -c 'import json,sys; print(json.load(sys.stdin)["Text"])'`
Each link is on one line in that output (the `HTML` field holds the HTML part). Open it from there, or from the Mailpit
web page, without retyping it.

**What CI already proves.** `check-stack.sh` validates the configuration (`compose/observability/check.sh`: promtool
and amtool checks, the rule unit tests, the dashboards), the host-metrics, monitoring-init and monthly-report
tests, and the docs links. The image job runs `smoke.sh monitoring` and `smoke.sh mail alert` against Mailpit. What
follows proves them on the production-shaped VM: real timings, the network filesystem, the systemd timers and a
reboot.

### 7.1 Setup

- [ ] *(service account)* `.env` has `COMPOSE_PROFILES`, `ALERT_EMAILS`, `ALERT_EMAIL_FROM` and
  `DEFAULT_FROM_EMAIL` (`grep -E '^(COMPOSE_PROFILES|ALERT_EMAILS|ALERT_EMAIL_FROM|DEFAULT_FROM_EMAIL)=' deploy/compose/.env`
  → four lines; both senders are the same address on the VM's own domain).
  - On failure: without `DEFAULT_FROM_EMAIL`, `web` refuses to start (`Set the DEFAULT_FROM_EMAIL environment variable`).
- [ ] *(fresh install)* The alerts of a new host are expected until the first backup, restore test, release watch run and
  timer runs (`BackupMissing`, `RestoreTestMissing`, `ReleaseWatchStale`, and `LoginRecordsPruneStale`, `EmbargoPassStale`, `WorkflowCleanupStale`, `AccountRetentionStale` until the first night): `make -C deploy silence-fresh-install` (48 h),
  or install the timers and take a backup before `observability-on`.
- [ ] `make -C deploy volumes secrets monitoring-init up observability-on` → `grafana_admin_password: created`,
  `pg_monitor_password: created`, the others `kept`; `monitoring-init` ends without error; then
  `make -C deploy status` → the seven monitoring containers `healthy`.
  - On failure: `monitoring-init` needs `postgres` up; read `docker compose logs <service>` of the unhealthy one.
- [ ] The vault item has the fields `grafana_admin_password` and `pg_monitor_password` (`SECRETS.md`).
- [ ] The timers are installed and enabled by `ansible-playbook site.yml` once the stack is up;
  `systemctl list-timers 'manuspectrum-*'` lists them.

### 7.2 Tunnel and dashboards

- [ ] *(host)* `ssh -L 3000:localhost:3000 <admin>@192.168.123.10`, then in a browser `http://localhost:3000`:
  the login page. Log in as `admin` with `cat "$SECRETS_DIR/grafana_admin_password"`.
  - On failure: `ss -ltn | grep 3000` on the VM must show `127.0.0.1:3000` only. Anything else is a bug: stop here.
- [ ] *(host)* From the host without the tunnel, `curl -m 5 http://192.168.123.10:3000/` fails (connection refused or
  timeout), and `curl -k -m 5 https://192.168.123.10/grafana/` is the site's 404.
- [ ] The five dashboards (Overview, Application, Infrastructure, Storage and backups, Activity) open without a "No data" panel,
  except those that wait for an event (a restart, an OOM kill, a restore test not yet run). Editing a panel and
  saving is refused (read-only provisioning).
- [ ] `deploy/compose/smoke.sh monitoring` (after `make -C deploy container-metrics disk-usage`, a backup and
  `make -C deploy restore-test`, which creates the restore-test gauges; `SMOKE_EXPECT_BACKUP=1`) → every line `ok`, exit 0.

### 7.3 Disk truth

- [ ] Each panel of Storage and backups against the host, within 2 %: `/ used` and `/data used` against `df -h / /data`;
  each area against `du -sb <directory>` (uploads, restic repository, dumps, nginx logs); the database size
  against `docker compose exec -T postgres psql -U postgres -tAc "select pg_database_size('manuspectrum')"`.
  - On failure: a difference on `/data` only is the `.snapshot` directory of the network filesystem (counted by
    `df`, not by the area panels): note it, it is expected.

### 7.4 Cost of the disk measure (decides hourly or four times a day)

- [ ] *(service account)* `time make -C deploy disk-usage` on the production-sized data (step 2.9). Record the real
  time. Under 60 s: keep the hourly timer. Over 60 s, or `time` shows the site slower during the run
  (`curl -w '%{time_total}\n' -o /dev/null -s https://<name>/en/` in a second terminal): switch the timer to
  `OnCalendar=*-*-* 00,06,12,18:17` (the line is in `manuspectrum-disk-usage.timer.in`) and record it.
- [ ] `grep -c . "$METRICS_TEXTFILE_DIR"/manuspectrum_disk_usage.prom` is non-zero and `manuspectrum_disk_usage_failed 0`.
- [ ] A path that is a mountpoint is refused: `METRICS_TEXTFILE_DIR=<existing absolute dir> DISK_USAGE_AREAS="media=/data" deploy/scripts/host-metrics.sh disk`
  exits 2 with `is a mountpoint` and writes nothing.

### 7.5 Alert e-mail, report and recipients

- [ ] `make -C deploy alert-test`, then within 2 minutes the Mailpit API lists a message whose `Subject` starts with
  `[ManuSpectrum][Alert] CRITICAL AlertTest`, whose `From` is the `ALERT_EMAIL_FROM` address and which carries the
  header `X-ManuSpectrum-Category: Alert` (`smoke.sh mail alert`), even in the 15 minutes after a boot. A `RESOLVED`
  message arrives 5 to 10 minutes after the alert ends (resolution, then the next 5-minute flush).
- [ ] `make -C deploy report-test` → a message `[ManuSpectrum][Report] Rapport mensuel <YYYY-MM>`, in French, header
  `Report`; `smoke.sh mail report` agrees. `make -C deploy report-test ARGS="--month 2020-01"` shows "n/d" for
  data older than 30 days and exits 1 only when Prometheus did not answer.
- [ ] Change the recipients: set `env_alert_emails` in the inventory to two addresses and run the playbook (it renders `.env`), then `make -C deploy alert-recipients` →
  returns once Alertmanager is ready; `make -C deploy alert-test` reaches both. A bad value (`ALERT_EMAILS=a@b.test,`)
  makes the target fail with `fix .env; alertmanager was left running unchanged`, and `make -C deploy alerts` still
  answers.
- [ ] Heartbeat window: the Monday 08:00 mail needs a Monday. Check the route instead:
  `dc exec -T alertmanager amtool config routes test --config.file=/tmp/alertmanager.yml alertname=Watchdog`
  → `heartbeat`. Then on the first Monday after installation, a message
  `[ManuSpectrum][Heartbeat] Alerting chain OK` arrived between 08:00 and 08:05 (Europe/Paris), once.
  - Limit: if the VM is down no mail is sent; a missing Monday mail is the signal.

### 7.6 Real triggers

- [ ] `dc stop worker` → after the rule's duration `ContainerMissing` (warning) is in `make -C deploy alerts`, mailed only on a weekday between 08:00 and 19:00; `dc start worker`
  → a `RESOLVED` mail.
- [ ] `chmod 000 "$RESTIC_REPOSITORY_DIR"`, `make -C deploy backup TAG=manual` fails, `BackupFailed` mails;
  `chmod 700` it back and run the backup again.
- [ ] On a test host whose disk stays full, `DiskAlmostFull` (critical) is mailed again every 4 hours, also at night
  (`repeat_interval: 4h` of the critical route in `alertmanager.yml.in`): expected, not a fault.
- [ ] Fill a sparse file on `/` beyond 80 %: `fallocate -l <size> /var/tmp/fill` → after 30 minutes `DiskUsageHigh`
  (warning) is in `make -C deploy alerts`, mailed only on a weekday between 08:00 and 19:00; remove the file.
- [ ] A certificate that expires within a few days (`make certs-local` with a short validity, or the renewal timer
  cut) → `CertificateExpiringSoon`.
- [ ] A hung network filesystem, only if the export can be stopped without harm to the rehearsal data
  (`systemctl stop nfs-server` on the host, for under 10 minutes): `NfsUnavailable` (critical) fires after 5 minutes,
  Prometheus and the site's pages that do not read `/data` keep answering, and the metric timers do not pile up
  (`systemctl list-units 'manuspectrum-*' --state=activating`). Start the server again and check `/data` is readable.
  Skip this check when the export carries other work.

### 7.7 Reboot

- [ ] `sudo reboot`. Within 15 minutes after boot no alert mail arrives (`RecentlyRebooted` holds them back);
  `HostRebooted` is visible in `make -C deploy alerts`; once the stack is back, `smoke.sh monitoring` is `ok`
  and every target is up. Stopping `worker` at boot for 20 minutes lets the held alert fire after the grace period.

### 7.8 Memory

- [ ] After 1 h and after 24 h: `docker stats --no-stream` for the seven monitoring containers, and
  `prometheus_tsdb_head_series` (Prometheus through the tunnel). Record both; adjust `--storage.tsdb.retention.size`
  if the 30-day estimate exceeds 8 GB.

### 7.9 What cannot be tested in rehearsal

The real SMTP relay and the acceptance of the sender `noreply@manuspectrum.<domain>` by it (SPF and DMARC of a real
domain); delivery to the institution's generic address and who receives it; the external probe (PP-9); the real
sizes of the data directories.

### 7.10 Before production

- [ ] `ALERT_EMAILS` holds the institution's generic address; `ALERT_EMAIL_FROM` and `DEFAULT_FROM_EMAIL` the same
  sender on the host's own domain (never an institutional one).
- [ ] The vault item has `grafana_admin_password` and `pg_monitor_password`.
- [ ] On the production VM: `make -C deploy alert-test` arrives in the generic mailbox, not in quarantine, with its
  prefix and header; `make -C deploy report-test` too. Mail filters sorting `[ManuSpectrum][<Category>]` are set up.
- [ ] `AllowTcpForwarding yes` is set for the administrators' accounts and the tunnel of 7.2 works there.
- [ ] The timers are installed by PP-8 and listed by `systemctl list-timers 'manuspectrum-*'`; the disk-usage
  schedule decided in 7.4 is recorded.

## Step 8 — Accounts (`deploy/ADMIN.md`)

Sign-up closed, lockout, invitation, activation with the terms and two-factor enrolment, legal pages, embargo and
workflow cleanup. Played on the rehearsal VM with the stack of step 2 and the Mailpit profile of step 7
(`COMPOSE_PROFILES=observability,mailpit`, `EMAIL_HOST=mailpit`, `EMAIL_PORT=1025`); `<site>` is the rehearsal name.
Create the test accounts in the admin and delete them afterwards.

### 8.1 Sign-up is closed, the unsafe 2FA routes are refused

- [ ] `curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<site>/en/auth/signup` → `404`, and the same on
  `/fr/auth/confirm_signup`, `/en/two-factor-authentication-settings` and `/en/two-factor-authentication-reset`
  (bodyless, no `X-Request-ID`).
  - On failure: the `DENIED` location of `edge-rules.conf` does not match (`tests/test_edge_contract.py`).

### 8.2 Lockout

- [ ] Five wrong passwords for one existing user on `/en/auth/` (a fresh `curl` session each time, CSRF token
  included), then a right one: the answer is the lockout page, `429`, not a sign-in. The same user signs in from another
  address, and after 15 minutes from this one.
  - Expected: `manuspectrum_auth_lockouts_total` increases by one (`smoke.sh` metrics or Prometheus), the admin lists
    the row in "Access attempts". Space the attempts by about 30 seconds: the edge `auth` zone
    (`snippets/ratelimit.conf`: `rate=5r/m`, `burst=5 nodelay`, applied in `edge-rules.conf`) counts POSTs
    and one sign-in attempt is two POSTs, so five attempts inside a minute exhaust it at the third or fourth and the
    edge answers its own `429` before the lockout (4.3). The lockout page is the site's, with the Home and Contact links.
- [ ] `make -C deploy manage ARGS="axes_reset_username <user>"` unlocks at once.

### 8.3 Invitation, activation, terms and two-factor

- [ ] In the admin, Users, "Add user" with an e-mail (no password field) and **Send the invitation now** ticked: the
  save lands on the change page, and Mailpit holds one message
  with the subject prefix `[ManuSpectrum][Account]` and the header `X-ManuSpectrum-Category: Account`, English then French.
- [ ] Open the link (read it as in « Reading a mail link » of step 7: a link cut at a line break answers `410`):
  the terms of use are shown with a required checkbox; submitting without it is refused; with it, set a
  password (an 11-character or common one is refused), then enrol an authenticator at `/en/account/two-factor`.
  The admin lists the acceptance (version, date) under "Terms acceptances".
- [ ] Sign out and in again with the code. A POST to `/en/account/two-factor` and `/en/account/terms` repeated 7 times in
  a minute gets `429` from the edge.
- [ ] Bump `TERMS_VERSION` (rehearsal image only) and sign in with a test user of this step who accepted the previous
  version, not the administrator who set the stack up: the next page after sign-in is the acceptance page. A person
  who has not accepted yet sees the terms at activation instead, and the acceptance page does not appear
  for an account that already accepted the current version.
- [ ] The activation link redirects at once to a URL without the token (`.../set-password`), and the nginx access log
  shows `[redacted]` for the activation path in both `uri` and `referer`.
- [ ] Set `FORCE_TWO_FACTOR_AUTHENTICATION=true` in `.env`, recreate `web`. Invite and activate a second test user:
  after the password the browser lands on `/en/account/two-factor` and any other page sends it back there until a
  code is confirmed. Check in the browser that the enrolment page works fully (QR code, manual key, confirmation)
  for that not-yet-enrolled user. An enrolled user signs in with the code.
- [ ] Lost phone, with forced two-factor still on: as a superuser, run **Reset two-factor authentication (superuser)**
  in the admin Users list (tick the account, choose the action; the User page shows the « Account » section).
  Mailpit holds the re-enrolment mail; the link asks for the password (a wrong one counts as a
  failed sign-in), then a new code, then signs the user in. Opening the link a second time is refused.
- [ ] `make -C deploy manage ARGS="check --database default"` raises no `manuspectrum.W004` (no OAuth application with the
  password grant). Put `FORCE_TWO_FACTOR_AUTHENTICATION` back to `false` if the rehearsal continues without it.

### 8.4 Legal pages

- [ ] `/en/about/legal`, `/en/about/privacy`, `/en/about/terms` and their `/fr/` twins answer `200` in their language,
  are linked from the footer ("Legal") and listed in `/sitemap.xml`; the printed durations are those of the settings
  (6 months, 12 months, 90 days).

### 8.5 Embargo and workflow cleanup

- [ ] Restrict a test resource: in the resource's permission manager (Arches), set **No Access** for the user
  `anonymous` or the group Guest (« No Access » for any other user or group is not a restriction here: the visitor still
  gets `200` and `release_expired_embargoes` finds nothing). The visitor now gets `403`, and the Embargo row is created
  as soon as the permissions are saved, listed in the admin under Embargoes with an end 12 months out
  (the daily pass, or `make -C deploy manage ARGS="release_expired_embargoes --apply"`, only records a restriction that has no row yet).
  Shorten its "Ends on"
  to 6 days from today in the admin → refused (« at least 7 days after today »: every lift follows its final notice by 7 days,
  for a superuser too); to 7 days from today → saved. `make -C deploy manage ARGS="release_expired_embargoes"` lists nothing to
  lift yet. Send the final notice with `release_expired_embargoes --apply` (Mailpit: the « Restriction ending on … » mail; without
  it, the pass moves the end 7 days on and warns instead). Rehearse
  the lift with `release_expired_embargoes --as-of <8 days from today, YYYY-MM-DD> --apply` (an end date cannot be set in
  the past; rehearsal only: `--as-of` with `--apply` is refused when `DEPLOY_ENVIRONMENT=production`): the resource is public, the creator got the "now public" mail in Mailpit, the history shows the lift,
  `manuspectrum_embargo_lifts_total{outcome="lifted"}` increased.
- [ ] Only a superuser can clear "Ends on" (no end date): a staff account with the embargo permission is refused,
  a superuser's change is recorded as `undated` and the row is listed under "End date → No end date".
- [ ] Data moved between hosts: delete the `ms_embargo` row of a restricted test resource in the admin, run
  `release_expired_embargoes --apply`: the restriction is recorded again, dated 12 months from today.
- [ ] `make -C deploy manage ARGS="prune_workflow_history"` (dry run) lists the idle runs and what it would delete and
  keep, and says "Dry run: nothing written or sent". Do not run `--apply` on the loaded snapshot.
- [ ] A missed pass is not caught up when beat starts more than two hours after its time
  (`CELERY_BEAT_CRON_STARTING_DEADLINE`; the rule itself is pinned by `tests.test_daily_pass_schedule`): in the evening
  `dc stop beat`; the next day after 08:00 (Europe/Paris) `dc start beat`, wait two minutes:
  `dc logs beat --since 5m | grep -E "Sending due task (workflow-cleanup|account-retention|embargo)-pass"` → nothing, and no
  notice in Mailpit; the following night `dc logs beat` shows the three entries sent at 03:30, 04:30 and 06:00. Do not
  call the tasks by hand to test this (`manage shell -c '…_pass_task()'`): that runs the real pass, mails included.
- [ ] After `load-snapshot` (2.9; its step 10 voids the pending notices), the three dry runs list notices only:
  `prune_workflow_history` cleans nothing, `anonymise_inactive_accounts` anonymises nobody, and
  `release_expired_embargoes` lists every restriction ending within 7 days (or already ended) as « would be re-dated for a final
  notice », none as due.

### 8.6 Deactivation and anonymisation

- [ ] In the admin, untick "Active" on a test user with an e-mail: Mailpit holds the deactivation mail (English then
  French) with the "Contact the team" link (it opens the contact page on "Reactivate my account") and the date the
  account will be anonymised. Ticking "Active" again sends nothing.
- [ ] On another test user, set "Last login" 25 months back in the admin (Important dates). `make -C deploy manage
  ARGS="anonymise_inactive_accounts"` lists it as "would be notice sent"; with `--apply` the notice reaches Mailpit.
- [ ] `anonymise_inactive_accounts --apply --as-of <today + 31 days, YYYY-MM-DD>` (rehearsal environments only: refused when `DEPLOY_ENVIRONMENT=production`): the user is renamed
  `former-user-<id>`, has no name, e-mail or two-factor secret, is inactive; the "Edit log" of a record it edited keeps
  its first and last names and no e-mail; `manuspectrum_account_anonymisations_total{outcome="anonymised"}` increased.
  A superuser in the same situation is only listed in the administrators' summary.

### 8.6b Roles: superuser, site manager, editor (`ADMIN.md` « Who can do what »)

Two test accounts besides the superuser: `mgr` (staff status + group **Site managers**, both set by the
superuser) and `ed` (no staff status, group `Resource Editor`).

- [ ] The Users list shows the column "Staff status" (FR « Statut équipe »).
- [ ] Signed in as `mgr`, the admin index lists only Users, Site announcements, Restrictions, Terms acceptances and
  Workflow cleanups. Groups, OAuth applications and Access attempts are absent, and their URLs answer `403`.
- [ ] As `mgr`, add an account `ed2` with group `Resource Editor`: saved, invitation sent. The groups box offers no
  `Site managers`, `System Administrator` nor `Application Administrator`; the change page of `ed2` shows the user
  name, the e-mail address, "Staff status", "Superuser status", "User permissions", "Last login" and "Date joined" as
  plain text and no password link.
- [ ] As `mgr`, POST the change form of `ed2` with forged fields (browser devtools or `curl` with the session cookie and
  CSRF token): `is_superuser=on`, `is_staff=on`, a `user_permissions` id → saved, and `ed2` is still neither staff nor
  superuser and holds no permission; `email=<another address>`, `username=<another name>` or `last_login_0=2020-01-01`
  → saved, and the e-mail, user name and last login are unchanged; a `groups` id of `Site managers` → the form
  answers with an error, nothing saved.
- [ ] As `mgr`, tick `ed2` and a staff account without password created by the superuser (box « Send the invitation
  now » unticked), choose **Send invitation**: Mailpit holds one mail (to `ed2`), and the admin says one account was
  skipped.
- [ ] As `mgr`, the change page of the superuser, of `mgr` itself and of `anonymous` shows no Save button, a POST to it
  answers `403`, and `/en/admin/auth/user/<id>/password/` answers `403` for every account, `ed2` included.
- [ ] As `mgr`, edit a site announcement, then shorten a restriction's "Ends on" and extend it: all saved. Clearing
  "Ends on" or setting a past date is refused.
- [ ] Remove staff status from `mgr` (as the superuser): `mgr` no longer reaches `/en/admin/`. `ed` never does.
- [ ] Delete the test accounts afterwards (as the superuser).

### 8.7 Report

- [ ] `make -C deploy report-test`: the message has the sections "Comptes inactifs", "Verrouillages de comptes",
  "Restrictions (embargos)", "Workflows abandonnés nettoyés" and "Courriels de compte", and lists the accounts created
  in 8.3 under "jamais connectés" only once they are three months old.

### 8.8 What cannot be tested in rehearsal

Delivery of the account mail by the real relay (SPF, DMARC, quarantine); the real authenticator clock drift; real
24-month and 12-month delays (rehearsed with `--as-of`).

### 8.9 Before production (accounts)

- [ ] Deploy with `FORCE_TWO_FACTOR_AUTHENTICATION=false`; at least two superusers enrol an authenticator; then set it
  to `true` and recreate `web`, `worker` and `beat`.
- [ ] `check --database default` raises no `manuspectrum.W004`; no OAuth application allows the password grant.
- [ ] The legal notice, privacy policy and terms carry no `[À CONFIRMER]` (`manuspectrum.E003` refuses it in
  production); the legal notice details are confirmed by the scientific lead and the CNRS communication service.
- [ ] The CNRS data protection officer is informed (privacy policy and the register of processing in `ADMIN.md`).

## Step 9 — Release watch and update (`deploy/RELEASES.md`, `deploy/ADMIN.md`)

The hourly watch that arms a verified release, and the `manuspectrum-update` command that installs it, now or
at a scheduled time, with a backup before and an automatic rollback after. Played on the rehearsal VM, which
follows the `rc` channel (`env_release_channel: "rc"` in its inventory), from the installed stack of step 2 with
the timers of 6.9. *(admin)* commands run as an account of `release_operators` (`ssh -t <admin>@192.168.123.10`, with
`sudo`); *(service account)* commands run after `sudo -iu manuspectrum` and `cd ~/manuspectrum`. `<host>` is the
public host name of the rehearsal VM. Two published release candidates newer than the running version are needed
for most checks (`RELEASES.md`, « Cut a release »): call them `vA` (the first) and `vB` (the next). Mails are read in
the VM's mail catcher or `mailq`; the state is read with `sudo manuspectrum-update --status`.

**What CI already proves.** The stub tests of the scripts (`deploy/scripts/tests/test_release_*.sh`,
`deploy/sbin/tests`), the unit checks (`deploy/systemd/tests/test_units.sh`), the Ansible contract tests and the
alert rule tests. What follows proves them on the production-shaped VM, with real tags, a real registry, real
signatures, the real systemd timers and the real mail relay.

### 9.1 Installation

- [ ] *(admin)* `ls -l /usr/local/sbin/manuspectrum-update /usr/local/lib/manuspectrum/release/ /etc/manuspectrum/release.conf /etc/manuspectrum/managed-sources /etc/sudoers.d/manuspectrum-update`
  → the command and the programs owned by `root:root`, `release.conf` mode `0644`, the sudoers file mode `0440`.
- [ ] *(admin)* `stat -c '%U:%G %a' /var/lib/manuspectrum/release` → the service account, mode `750`.
- [ ] *(admin)* `getent group manuspectrum-ops` → exactly the accounts of `release_operators`.
- [ ] *(admin)* `systemctl is-enabled manuspectrum-watch.timer` → `enabled`; `systemctl is-enabled manuspectrum-update-at.timer manuspectrum-update@x.service`
  → not enabled (`disabled` or `static`, never `enabled`); `systemctl list-timers 'manuspectrum-watch*' 'manuspectrum-update*'`
  → only the watch timer has a next elapse.
- [ ] *(admin)* `sudo -k; sudo manuspectrum-update --status` → asks for **your** password (no `NOPASSWD`), then prints
  `current:` with the installed tag and `armed:    none`.
- [ ] *(admin)* `systemd-analyze verify /etc/systemd/system/manuspectrum-watch.service /etc/systemd/system/manuspectrum-watch.timer /etc/systemd/system/manuspectrum-update@.service /etc/systemd/system/manuspectrum-update-at.service /etc/systemd/system/manuspectrum-update-at.timer`
  → no output, except that `manuspectrum-update-at.timer` is refused until `--at` writes its slot (its drop-in): leave it out before 9.11.
  - On failure: a `@…@` left in a unit; the Ansible tests catch it in CI.

### 9.2 Outbound access and the first watch

- [ ] *(service account)* `curl -sS -m 15 -o /dev/null -w '%{http_code}\n' https://github.com/ https://tuf-repo-cdn.sigstore.dev/`
  → two 2xx or 3xx codes; `curl -sS -m 15 -o /dev/null -w '%{http_code}\n' https://ghcr.io/v2/` → `401`.
  - On failure: open 443 to `github.com`, `ghcr.io`, `pkg-containers.githubusercontent.com`, `tuf-repo-cdn.sigstore.dev`
    and `rekor.sigstore.dev` (`runbooks/release.md`).
- [ ] *(service account)* `docker logout ghcr.io; ls ~/.docker/config.json` → no credential for ghcr.io (the package is public;
  `SECRETS.md`); the checks below pull anonymously.
- [ ] *(admin)* **No release.** While the running version is the newest the channel allows:
  `sudo systemctl start manuspectrum-watch; journalctl -u manuspectrum-watch -o cat -n 5`
  → `no release newer than <tag>`; `--status` still shows `armed:    none`; no mail.
  `grep -c . "$(grep ^METRICS_TEXTFILE_DIR= deploy/compose/.env | cut -d= -f2)/manuspectrum_release.prom"` → the file exists
  (it is written on every run, `ReleaseWatchStale` reads it).

### 9.3 Arming

- [ ] Publish `vA` (a candidate newer than the running version). *(admin)* `sudo systemctl start manuspectrum-watch;
  journalctl -u manuspectrum-watch -o cat -n 8` → `armed vA (sha256:…), needs_ansible=0, security=0`; `--status` shows
  `armed:    vA image …@sha256:…` and `pending:  since …`; the registry digest of `vA` equals the armed one.
- [ ] One mail `[ManuSpectrum][Release] vA ready to install on <host>` with the version, channel, digest, commit, the
  release link, `Install by:` 30 days ahead, the release notes and the two commands. A second run of the watch sends
  nothing more (`NOTIFIED=1`).
- [ ] The next hourly run by the timer: `journalctl -u manuspectrum-watch -o cat` shows it armed and unchanged.
- [ ] *(security)* Publish a candidate whose signed tag carries `-m 'Security-Fix: yes'`: after the watch the mail subject
  ends `(security fix)`, the body has « This release carries a security fix. », `Install by:` is 14 days after the
  oldest waiting release and `--status` shows `security=1`.
- [ ] *(Ansible first)* On a release whose managed files differ from the host (or after removing one key of `.env`, restored
  afterwards): the mail says « Re-run Ansible first » and `--status` shows `needs_ansible=1`.

### 9.4 Access control

- [ ] *(service account, not an operator)* `sudo manuspectrum-update --status` → refused by sudo (not in the sudoers file).
  An account that is neither an operator nor the service account: same refusal.
- [ ] *(admin)* `manuspectrum-update --status` without `sudo` → `run it through sudo`.
- [ ] *(admin)* `sudo manuspectrum-update --now vA < /dev/null` (no terminal) → `needs a terminal: use ssh -t`.
- [ ] *(admin)* `ssh -t … sudo manuspectrum-update --now v9.9.9` → `v9.9.9 is not the armed release (vA)`; nothing started.
- [ ] Remove an operator from `release_operators`, run the playbook: the account leaves `manuspectrum-ops` and `sudo
  manuspectrum-update` is refused for it, unless the account is also in `sudo` (`admin_users`): a member of `sudo` keeps full
  sudo and still runs the command. To withdraw an administrator, remove it from `admin_users` too. Put it back and run the
  playbook again.

### 9.5 Ansible first

- [ ] *(admin)* With the host last configured from a checkout of an older tag, so that a file Ansible manages differs in `vA`
  (or with a key of `.env.example` removed from `.env`, restored afterwards), `ssh -t … sudo manuspectrum-update --now vA` →
  the check refuses: `files installed by Ansible differ between vA and this host` followed by the files (or `lacks keys that vA
  expects`), `the check refused vA: nothing was started`; no backup was taken and nothing changed.
- [ ] On the laptop, `git switch --detach vA` with a clean tree, run the playbook, then `--now vA` passes its check.
- [ ] A laptop checkout with an uncommitted change in a managed path: the playbook stops with « uncommitted changes in files the
  update compares with the release tag ».

### 9.6 Forced rollback

Needs the stack running `vOld` and `vA` armed.

- [ ] *(admin)* `ssh -t … sudo manuspectrum-update --now vA`, type `yes`. `make up` waits for health (`up -d --wait`), so
  stopping Cantaloupe at the first `readiness:` line is too late, and compose recreates it during `up`. Instead, *(service
  account)* follow the engine's journal (`journalctl -u 'manuspectrum-update@*' -f`) and, right after the line
  `Container manuspectrum-worker-1 Healthy`, before the first readiness probe, run `docker kill manuspectrum-cantaloupe-1`.
  The probe answers `readiness: 503`.
  - Expected: after `RELEASE_READY_WAIT_SECONDS` the log says `step 10: vA failed (the application was not ready within …)`,
    `rolling back to vOld`, then `readiness: 200`; the command ends `ROLLED BACK: vA did not start; the previous version is
    back` with exit status 3 (`echo $?`).
- [ ] `--status` → `current: vOld`, `armed:    vA`, `rollbacks: 1`, no `ROLLBACK FAILED`, no `inflight`. Mail `vA rolled back`;
  `UpdateRolledBack` fires (it reads the rollback counter, 64 hours). `git -C ~/manuspectrum describe --tags` → `vOld`; `grep ^MANUSPECTRUM_IMAGE= deploy/compose/.env`
  → the digest of `vOld`.
- [ ] `docker compose … start cantaloupe` (if the rollback left it down), `make -C deploy smoke` → passes (the data were not touched).
- [ ] A snapshot tagged `pre-update` exists: `make -C deploy restic ARGS="snapshots --tag pre-update"`.

### 9.7 SSH disconnect

- [ ] *(admin)* Start `--now vA`, type `yes`, then close the terminal (kill the SSH client) while the log runs.
  → the update goes on: `systemctl status 'manuspectrum-update@vA'` shows it active; reconnect and `journalctl -fu
  manuspectrum-update@vA -o cat` follows it to the end.
- [ ] `--status` after it ends: `current: vA`, `armed:    none`, `inflight: none`; mail `vA installed on <host>`.

### 9.8 Real update

- [ ] Publish `vB`, wait for the watch (or `sudo systemctl start manuspectrum-watch`), then `ssh -t … sudo manuspectrum-update --now vB`:
  the checks end with `check passed for vB`, the description shows `release: vB (installed: vA)`, `yes` →
  `step 5: backup (pre-update)`, `step 7: switching vA -> vB`, `readiness: 200`, `vB is installed and the application answers.`,
  exit status 0.
- [ ] `--status` → `current: vB (…)`, `previous: vA`, `armed:    none`, `pending:  none`, `rollbacks:` unchanged. `curl -sk
  https://<host>/readyz` → `200`. The site answers; `smoke.sh edge` passes. `ReleasePendingTooLong` and `UpdateRolledBack`
  are not firing once the 64 hours of a previous rollback are over.
- [ ] `docker image ls` holds the images of `vB` and `vA` (current and previous), no older armed one.

### 9.9 Refusals of the update

- [ ] *(sigstore blocked)* *(admin)* Block the sigstore hosts on the VM (`sudo iptables -I OUTPUT -d <address of
  tuf-repo-cdn.sigstore.dev> -j REJECT`, or a hosts-file entry to an unroutable address), arm a release, then run the watch:
  → `probe sigstore: … unreachable`, nothing armed, `failed_sigstore 1` in the metrics; after two hours `ReleaseWatchFailing`
  names `sigstore`. Remove the rule; the next run clears it. With `--now` on an armed release while blocked: the check refuses with
  `REASON=fetch` (the signature services do not answer) and nothing changes.
- [ ] *(backup failure)* *(service account)* `chmod 000 "$RESTIC_REPOSITORY_DIR"` (see 6.8 for a mount that ignores it), then
  `--now` → `step 5: backup (pre-update)`, then `REFUSED: the pre-update backup failed: nothing was changed`; `git describe`,
  the `.env` image and the running containers are as before; no `inflight`. Restore the mode afterwards.
- [ ] *(dirty worktree)* `touch deploy/stray.txt; git add -N deploy/stray.txt` (a tracked change) →
  the check refuses with `local changes` (`REASON=drift`); remove it.
- [ ] *(concurrency)* In two sessions start `--now vB` at once: the second answers `an update is running` or, past the
  first checks, `another update or watch holds … lock`; exactly one update runs. While an update runs,
  `sudo systemctl start manuspectrum-watch; journalctl -u manuspectrum-watch -o cat -n 2` → `update running …: nothing to do`
  and the exit status is 0.
- [ ] *(inflight)* With a file `/var/lib/manuspectrum/release/inflight` present (as after a failed rollback), `--now` refuses with
  `an update is in flight or was interrupted` (`REASON=busy`). Remove the file afterwards.

### 9.10 Production channel

- [ ] Set `env_release_channel: "prod"` in a copy of the inventory and run the playbook (or set `RELEASE_CHANNEL=prod` in `.env`),
  with a candidate newer than the running version published: the watch logs `no release newer than …` (a candidate is not
  offered); with a newer final tag it arms that one. Restore `rc`.
- [ ] `RELEASE_CHANNEL=beta` in `.env` → the watch logs `RELEASE_CHANNEL … must be prod or rc` and fails (`failed_state 1`);
  restore it.

### 9.11 Scheduling

Needs a release armed (`vA`) and no schedule. Use a slot more than 10 minutes ahead; the VM clock must be right (« How to
read and record »). Paris time everywhere.

- [ ] *(5 minutes ahead, with notice)* *(admin)* `ssh -t … sudo manuspectrum-update --at "<now+12 min, YYYY-MM-DD HH:MM>" vA`,
  `yes` → `Scheduled vA for … Paris`; mail `vA scheduled for … by <account>`; `--status` shows `scheduled: vA at …`,
  `notice id: <n>` and a `timer next elapse`; `systemctl list-timers manuspectrum-update-at.timer` shows the slot;
  `/etc/systemd/system/manuspectrum-update-at.timer.d/slot.conf` exists; the admin « Site announcements » lists a
  Maintenance announcement from the slot to the end of the window.
  - At the slot: the update runs (`journalctl -u 'manuspectrum-update@*' -f`); the announcement ends when it finishes;
    `scheduled: none`, the drop-in is gone, `systemctl is-active manuspectrum-update-at.timer` → `inactive`; mail `vA installed`.
    During the restart `curl -sk -o /dev/null -w '%{http_code}\n' https://<host>/` answers `502`/`503`, with the site error page
    holding the announcement box.
- [ ] *(cancelled)* Schedule another slot, then `sudo manuspectrum-update --cancel` → `The schedule of … is cancelled.`; the timer
  is stopped, the drop-in removed, the announcement deleted, mail `schedule of … cancelled`. At the old slot nothing runs.
  `--cancel` again → `Nothing is scheduled.`
- [ ] *(missed)* Schedule a slot 15 minutes ahead, then `virsh shutdown` the VM before it, wait past the slot plus 20 minutes,
  `virsh start`. Nothing installs at boot; the slot is reported by the next hourly watch run, not at boot
  (wait for it, or `sudo systemctl start manuspectrum-watch.service`): `journalctl -u manuspectrum-watch -o cat`
  → `scheduled update of … missed`; `--status` → `OUTCOME=missed`; mail `scheduled update of … missed`; the announcement is
  withdrawn; `ReleaseScheduleFailed` fires. `sudo manuspectrum-update --cancel` → `Acknowledged: the missed schedule … is
  cleared.`; the alert clears at the next watch.
- [ ] *(refused at the slot)* Schedule a slot 12 minutes ahead, then make the worktree dirty (`git add -N` a new file). At the slot:
  the unit exits 1; `--status` → `OUTCOME=refused REASON=drift`, the announcement withdrawn, mail `scheduled update of … refused:
  drift`, nothing changed. Acknowledge with `--cancel`.
- [ ] *(a newer release during a schedule)* Schedule `vA`, publish `vB` and run the watch: mail `vB available while vA is
  scheduled`; `--status` shows `a newer release (vB) is held back`; `armed:` still `vA`. After `vA` installs, the next watch arms `vB`
  and mails.
- [ ] *(`--at` refusals)* Each answers a refusal and leaves no schedule (`--status` → `scheduled: none`):
  - `--at "2027-03-28 02:30" vA` → `does not exist in Paris (clocks go forward)`;
  - `--at "2027-10-31 02:30" vA` → `occurs twice in Paris (clocks go back)`;
  - a past time, or one less than 10 minutes ahead → `at least 10 minutes ahead`; more than 30 days → `at most 30 days ahead`;
  - a slot within the reboot window of the host (`grep Automatic-Reboot /etc/apt/apt.conf.d/50unattended-upgrades`, 60 minutes
    before to 15 after the reboot time) → `within the automatic reboot window of this host`;
  - `--window 1m` → `--window must be between 5m and 4h`;
  - a slot at 02:10 (not a DST night) → accepted after the check, with the `warning:  02:00-03:00 Paris is when the nightly backup
    runs` line before the confirmation; answer anything but `yes`, then `--status` → `scheduled: none`.
- [ ] *(window passes during the pre-update backup)* Make the pre-update backup slow (for example a large `MEDIA_HOST_DIR`, or
  `sudo ionice -c3` on the repository disk) and schedule a slot with `--window 5m`. At the slot the unit starts and the backup runs
  past the end of the window: the update stops after the backup with `REASON=late` and changes nothing (no `inflight`), `--status`
  → `OUTCOME=missed REASON=late` (or `refused` when the engine decided), the announcement is withdrawn, a mail says the slot
  missed. A timer that fires after the window (stop the timer, wait out the window, `sudo systemctl start
  manuspectrum-update-at.service`) → `--status` → `OUTCOME=missed REASON=late`, `systemctl is-active
  manuspectrum-update@vA.service` → `inactive`, mail `scheduled update of vA missed`.
- [ ] *(Ansible started during a scheduled slot)* Schedule a slot 12 minutes ahead; from the laptop start `ansible-playbook … site.yml
  --tags app` shortly before it and keep it paused (a `pause` or a slow gate); `ls -l /run/manuspectrum/ansible-running` → a
  root-owned file. At the slot the unit is not started or exits 1 with `Ansible is running on this host`: `--status` →
  `OUTCOME=refused REASON=busy`, mail `scheduled update of … refused: busy`. Meanwhile `--now vA` and `--at …` answer `Ansible is
  running on this host`. When the playbook ends (also when it fails) the file is gone. After a Ctrl-C the file stays (Ansible runs no `always` on a controller interrupt): with `pgrep -a ansible` empty on the laptop and on the host, remove it with `sudo rm /run/manuspectrum/ansible-running`; left alone it raises the `state` failure after 2 hours, and the next Ansible run takes it again and refreshes it. The reverse: with
  an update unit running, the playbook stops at once with `An update is running`, and the marker is removed.
- [ ] *(host time zone)* `timedatectl show -p Timezone --value` → `Europe/Paris` after the baseline role ran (`baseline_mode: apply`;
  `verify` reports `The host time zone is …` otherwise). `sudo timedatectl set-timezone UTC`, then `--at "<slot>" vA` → `the host time
  zone is 'UTC', not Europe/Paris`, nothing scheduled; set `Europe/Paris` back and the same command is accepted (cancel it).
- [ ] *(`--now` while scheduled)* With a schedule open, `--now vA` → `an update is already scheduled … cancel it first`.
- [ ] *(`--no-notice`)* A schedule with `--no-notice` shows `notice id: none` and creates no announcement.

### 9.12 Mail when the stack is down

- [ ] *(service account)* `make -C deploy down`, then *(admin)* `sudo systemctl start manuspectrum-watch` with a release to arm
  (or `sudo manuspectrum-update --cancel` after a schedule): the host's own mail service still delivers the mail
  (`mailq` empty, the message in the catcher). `make -C deploy up` afterwards.
- [ ] *(failed rollback)* Start `--now` on an armed tag. When the log shows `step 10`, make the rollback's own start fail by
  stopping Docker (`sudo systemctl stop docker.socket docker`).
  - Expected: the update ends with exit status 4 and `ROLLBACK FAILED`; mail `vA ROLLBACK FAILED`, delivered although the stack is
    down, with the restore commands; `--status` prints the `ROLLBACK FAILED` block and `inflight:`;
    `manuspectrum_release_rollback_failed 1` in the release metrics file (no alert reads it: only the mail and `--status`
    announce a failed rollback). A new `--now` refuses until `sudo manuspectrum-update --resolved`.
  - Start Docker and the stack again (`make -C deploy up`), run `sudo manuspectrum-update --resolved` → `Marked as resolved.`; `--status` shows `inflight: none` and
    no `ROLLBACK FAILED` block, the release metrics say `rollback_failed 0`, and a mail `<host>: failed update marked as
    resolved by <login>` arrives.

### 9.13 What cannot be tested in rehearsal

The real production channel (`prod`) against the final tags of `main`; the real mail relay's delivery to the operators
(SPF, DMARC); the real unattended reboot hour of production; a security release judged by the technical lead.

### 9.14 Before production (updates)

- [ ] `env_release_channel: "prod"` in the production inventory and `release_operators` lists exactly the people who may
  install.
- [ ] The GHCR package is public (`docker logout ghcr.io; docker pull ghcr.io/crc-centre-recherche-conservation/manuspectrum:<tag>`
  works anonymously) and the branch protection requires `conclusion` and `gitleaks` (`RELEASES.md`).
- [ ] `ALERT_EMAILS` reaches the operators (`make -C deploy alert-test`) and one `[ManuSpectrum][Release]` mail was received.
- [ ] The first real update is scheduled for 23:00, not at 02:00-03:00.

---

---

## Next steps

Each PR of the workstream adds its section here, on the same model (command, expected,
what to do on failure): Ansible, delivery, then
"Before production".
