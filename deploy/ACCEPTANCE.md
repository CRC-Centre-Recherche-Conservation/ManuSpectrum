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

- [ ] Copy and run, from the host:
  `scp deploy/rehearsal/{host-baseline.sh,verify-baseline.sh,rehearsal.env} <admin>@192.168.123.10:`
  then `ssh -t <admin>@192.168.123.10 'sudo ./host-baseline.sh && sudo ./verify-baseline.sh'`.
  - Expected: every line starts with `OK`, exit code `0` (`echo $?`).
  - If a `MISMATCH` line appears: note the line and the output of the matching command.
- [ ] Re-run `sudo ./host-baseline.sh` → everything "already done", then `sudo ./verify-baseline.sh` → everything `OK`.
- [ ] `ls -l /etc/manuspectrum/rehearsal-host` → `-rw-r--r-- 1 root root`: the marker without which
  `make load-snapshot` is refused (the rehearsal VM only; never create it on a production host).
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

- [ ] `command -v make git` → two paths. A fresh baseline has no `make`: it mirrors what the
  hosting provider delivers, and Ansible installs it from PP-8. Until then the admin installs it
  by hand with sudo (`sudo apt-get install -y make git`); record that it was needed.
- [ ] *(service account)* `docker compose version` and `docker info --format '{{.LoggingDriver}}'` →
  Compose v2 and `json-file`.
- [ ] `sudo install -d -o manuspectrum -g manuspectrum -m 0750 /data/manuspectrum /data/manuspectrum/media /data/manuspectrum/media/uploadedfiles`
  (paths and account from `rehearsal.env`), then `sudo ls -ldn /data/manuspectrum/media` (the directory is `0750`, owned by the service
  account: without `sudo` the admin cannot list it; or run it as the service account) →
  owner and group = `id -u manuspectrum`, `id -g manuspectrum`. Directories `0750`, files
  `0640`, owned by the account: Cantaloupe is not that account, it reads the uploads through
  `group_add: APP_GID`. Files that web or worker write later get `0644` (umask 022).
  Over NFS the export must keep the uid and gid (no `root_squash` remapping of them).
- [ ] *(service account)* the repository is at `~/manuspectrum` at the commit under test:
  `git clone https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum.git manuspectrum`,
  `git -C manuspectrum checkout <commit>`, `git -C manuspectrum log -1 --format=%H` → `<commit>`.
- [ ] *(service account)* `cp deploy/compose/.env.example deploy/compose/.env`, then set
  `APP_UID`, `APP_GID` (`id -u`, `id -g`), `MEDIA_HOST_DIR`, `DOMAIN_NAMES` and
  `PUBLIC_SERVER_ADDRESS` to the rehearsal values; leave `MANUSPECTRUM_IMAGE=manuspectrum:local`.
  Check: `grep -E '^APP_(UID|GID)=' deploy/compose/.env` → the two numbers of `id -u; id -g`.
  Also set the nginx values (4.1): `CERT_MODE=local`, `CERTS_DIR`, `NGINX_LOG_HOST_DIR`,
  `PUBLIC_HOST` (the host name of `PUBLIC_SERVER_ADDRESS`, no port) and
  `LOCAL_CA_CERT=<CERTS_DIR>/ca/ca.crt` as a literal path. Create the log directory as the
  service account (`install -d -m 0750 <NGINX_LOG_HOST_DIR>`); `make -C deploy certs-local`
  (4.1) creates the certificates.
- [ ] *(service account, rehearsal VM only)* the template ships `DEPLOY_ENVIRONMENT=production`;
  the rehearsal VM sets it explicitly: `sed -i 's/^DEPLOY_ENVIRONMENT=.*/DEPLOY_ENVIRONMENT=rehearsal/' deploy/compose/.env`.
  Check: `grep '^DEPLOY_ENVIRONMENT=' deploy/compose/.env` → `DEPLOY_ENVIRONMENT=rehearsal`.
  A production host leaves `production`.
- [ ] *(service account)* `make -C deploy secrets` (creates the directory `0700` and the missing
  files; the commands by hand are in `deploy/compose/secrets/README.md`);
  `ls -l deploy/compose/secrets` → `pg_password`, `elastic_password`, `django_secret_key`,
  `email_password` (empty), `admin_password` as `-r--r--r--`, plus `README.md`; `ls -ld deploy/compose/secrets` →
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

- [ ] *(service account)* `make -C deploy volumes` → four lines `ms_pg_data`, `ms_es_data`,
  `ms_redis_broker`, `ms_cantaloupe_cache` (the output of `docker volume create`); run it
  again → four `… exists`.
- [ ] *(service account)* `make -C deploy config` → `compose files valid`.
  - On failure: the message names the unset variable of `.env`.
- [ ] *(service account)* `make -C deploy init` → Arches `setup_db` output, exit 0
  (`echo $?`).
  - On failure: `dc logs --tail=100 postgres elasticsearch`; an Elasticsearch that never
    gets healthy: `sysctl vm.max_map_count` → at least `262144`.
  - A failed first installation (Elasticsearch flapping, out of memory, Ctrl-C) leaves a
    half-created database: `make init` then refuses, and `web` refuses to start with
    `has no Arches system settings`. Drop it, then start again:
    `dc exec postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists <PGDBNAME>'` and
    `make -C deploy init` (Elasticsearch indexes are recreated by `setup_db`).
- [ ] *(service account)* The end of the `init` output says
  `admin password set from the admin_password secret`. Read the password once,
  `cat deploy/compose/secrets/admin_password`, and sign in as `admin` on the
  rehearsal address (`/en/auth/`): it works, and `admin` / `admin` is refused.
  Store it immediately in the institution's password manager (break-glass account),
  create a named account for each operator and use those day to day. To read it as the
  service account from another login: `sudo -iu <service-account> cat <SECRETS_DIR>/admin_password`.
  Change it any time from the profile page or with
  `make -C deploy manage ARGS="changepassword admin"` (interactive): the file then no
  longer matches and only served the installation, the password manager is the
  reference. PP-2 (sops) will keep an encrypted copy in Git.
  - On failure: `init` ends with `the admin password could not be set` (the database
    exists with the default password): fix the file, then `make -C deploy admin-password`.
- [ ] *(service account)* Run `make -C deploy init` again → exit ≠ 0 with
  `refusing: database <PGDBNAME> exists and setup_db would drop it`, and the data is intact
  (`deploy/compose/smoke.sh init-guard` → four `ok:` lines: `init`, `manage setup_db`,
  `manage packages ... -db`, `manage packages -o setup`). **(CI too)**
- [ ] *(service account)* `make -C deploy certs-local` (4.1), then `make -C deploy up` → returns without error (it waits for every
  service but `beat`, then starts `beat`); up to 15 minutes on a first start.
  The `nginx` service needs `CERTS_DIR` and `NGINX_LOG_HOST_DIR` to exist: `up` fails otherwise.
  - On failure: `make -C deploy status`, then `dc logs --tail=100 <service>` of the one
    that is not healthy.
- [ ] *(service account)* `make -C deploy status` → nine services: `postgres`,
  `elasticsearch`, `redis-broker`, `redis-cache`, `cantaloupe`, `web`, `worker`, `nginx` as
  `healthy`, `beat` as `running` (it has no health check on purpose).
- [ ] *(service account)* `make -C deploy smoke` (= `deploy/compose/smoke.sh check`) →
  only `ok:` lines, exit 0. **(CI too)** Among them, the three that fail most
  often on a new host:
  - `ok: database collation and encoding` (`en_US.utf8|UTF8`);
  - `ok: standard_conforming_strings` (the value is `off`: Arches needs it);
  - `ok: admin keeps Arches' default password` (the check passes when `admin`'s password is no longer `admin`);
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
  redis-broker 256MiB, redis-cache 768MiB, beat 256MiB, nginx without a limit of its own. Record the idle usage of each.
  Expected idle: elasticsearch about 2.7 GiB on an empty database, about 3.4 GiB with data
  loaded (heap 2 GiB; the rest is direct memory, metaspace, threads and page cache). The
  postgres, web and worker figures depend on the load: measured 0.1 / 0.9 / 0.3 GiB on an empty
  database and 0.36 / 0.62 / 0.29 GiB with data loaded and no traffic; cantaloupe 0.3 (1.3 warm).
- [ ] *(service account)* `docker inspect -f '{{.Name}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}' $(dc ps -q)`
  → nine lines where the two figures are equal (a container never swaps).
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
- [ ] *(admin)* `sudo ls -lh $(sudo docker inspect -f '{{.LogPath}}' manuspectrum-web-1)*` → `*-json.log`,
  no file above 10 MB. To see rotation itself, write about 12 MB:
  `docker exec manuspectrum-web-1 sh -c 'yes ms-log-test | head -c 12000000 >/proc/1/fd/1'`,
  then the same `ls` → a second file `*-json.log.1`, none larger than 10 MB, at most five.
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
  `<id1>`. Build the next commit (`git checkout <next commit>`,
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
  `host-baseline.sh` when `rehearsal.env` sets `REHEARSAL_HOST=yes`, checked by `verify-baseline.sh` then).
  - On failure: the command needs both guards. A production host has `production` and no marker
    file, and the command is refused there whatever `.env` says.
- [ ] *(service account)* `make -C deploy load-snapshot SNAPSHOT=<path>` without `CONFIRM=yes` → refused, nothing changed.
- [ ] *(service account)* `make -C deploy load-snapshot SNAPSHOT=<path> CONFIRM=yes` → fourteen `load-snapshot: step n/14`
  lines, `checksums match`, `preflight: ok`, counts `equal to the manifest` (or a `WARNING` naming
  the difference a migration explains), `done: the snapshot is loaded`.
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
  → the same fourteen steps, restoring `rehearsal-before.dump` and a copy of `uploadedfiles/`
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
secrets under sops, `/readyz` and the JSON logs, backups, the real SMTP relay, and
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
  - Expected: one line, value ≥ 50 (not five lines, not a value near 10).
  - On failure: `PROMETHEUS_MULTIPROC_DIR` is not set in the web container
    (`dc exec web env | grep PROMETHEUS`).
- [ ] *(service account)* `dc exec web sh -c 'stat -f -c %T /run/prometheus; ls /run/prometheus | head'`
  - Expected: `tmpfs`, then files `counter_<pid>.db`, `histogram_<pid>.db`, `gauge_livesum_<pid>.db`.
  - On failure: the tmpfs is missing in `compose.yaml`.
- [ ] *(service account)* Replaced workers leave no live gauge: `dc kill -s HUP web` (gunicorn replaces every
  worker gracefully), wait 20 s, then
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
  store), and add `<vm> manuspectrum.test` to `/etc/hosts`.
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
  `?format=tilecsv&format=geojson` → `404`; `?format=geojson` → answered by Django.
  `curl -s -o /dev/null -w '%{http_code}\n' -X POST https://manuspectrum.test/fr/temp_file` → `404`
  (a GET reaches Django).
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
- [ ] Mirador on one large manuscript (4.5): `grep -c '"status":429' $LOG/access.log` → `0` after the visit.

### 4.4 Error pages

- [ ] `curl -s https://manuspectrum.test/en/this-page-does-not-exist | grep -c '<html'` → `1` and the
  design is the site's (the 404 comes from Django here); `curl -s https://manuspectrum.test/en/api/resource/x`
  → nginx's own 404 page.
- [ ] *(service account)* `dc stop web`, then `curl -s -o /dev/null -w '%{http_code}\n' https://manuspectrum.test/en/` → `502` or
  `503` with the site's 500 page (`manuspectrum/templates/errors/500.htm`, self-contained), then
  `dc start web` → the site answers again with no nginx restart.
  - On failure: the bind of `500.htm` in `compose.yaml` is missing (`nginx -t` fails to start nginx).

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
- [ ] Application routes do not get the wildcard: `curl -sI -H 'Origin: https://example.org' https://manuspectrum.test/fr/api/explorer/search | grep -i access-control` → empty.
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
- [ ] the Network tab shows no request outside the domain (spec §6.2) and no 4xx or 5xx except the
  expected ones; the console lists the CSP Report-Only violations: copy them into the issue for F5.

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
- [ ] No query string, no personal data: `grep -cE '\?|password|token=|@[A-Za-z0-9.-]+\.[a-z]{2,}' $LOG/access.log` → `0`.
  - On failure: `$uri` and `$log_uri` in `logging.conf`; a log line must never carry `$request` or `$args`.
- [ ] Reset token redacted: visit one password-reset link, then
  `grep -c '/reset/\[redacted\]' $LOG/access.log` → at least `1` and the token appears nowhere
  in the file.
- [ ] The request id joins the logs: take the `X-Request-ID` of `curl -sI https://manuspectrum.test/en/`, then
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
  token included. Check `ls -l $LOG/error.log` → readable by the service account and root only
  (no `o+r`), rotated thirty days with the access log (4.9).

### 4.9 Rotation

- [ ] (admin) Render the host file by hand until PP-8 installs it: replace `@NGINX_LOG_HOST_DIR@`,
  `@APP_USER@`, `@APP_GROUP@` in `deploy/logrotate/manuspectrum-nginx.in`, then
  `sudo logrotate -f -s /tmp/state <rendered file>`.
  - Expected: dated, then compressed (next run) files appear in `$LOG`, a new `access.log` is
    created `0640` for the service account, and nginx keeps writing to it with no restart
    (`dc ps nginx` uptime unchanged, a new request lands in the new file). `rotate 30`: thirty days.
  - On failure: `su` line missing (logrotate refuses a directory not owned by root), or the
    `USR1` signal did not reach the container (`docker ps --filter label=com.docker.compose.service=nginx`).
- [ ] *(service account)* `docker inspect -f '{{.HostConfig.LogConfig}}' $(dc ps -q nginx)`
  → `{json-file map[max-file:5 max-size:10m]}` (nginx's own stdout stays bounded).

### 4.10 Data steps after loading a snapshot

The snapshot holds the origins of the development hosts in concept identifiers, controlled-list
URIs, IIIF manifests and the tiles that reference them. Run once, before the site is shown.
Commands run as the service account (no admin account runs `docker`).

- [ ] *(service account)* Dry run, one `--from` per origin the snapshot was made under (up to four
  development origins):
  `make -C deploy manage ARGS="rewrite_dev_origin --dry-run --from <dev origin 1> --from <dev origin 2> --from <dev origin 3> --from <dev origin 4>"`
  - Expected: a count per family (concepts, lists, manifests, tiles), nothing written, a
    line `anomaly: N blob: URL(s)…`. The blob URLs are dead browser object URLs, counted and never
    rewritten: record N, it is not an error.
  - On failure: all counts `0` = the origins are mistyped (scheme, port, trailing slash).
- [ ] *(service account)* The same command without `--dry-run`, then again with `--dry-run` → every count `0`.
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
the host logrotate and certificate-renewal units (PP-8; their content is checked by the tests
above).

### 4.12 Before production (nginx and TLS)

- [ ] `CERT_MODE=acme`, `ACME_EMAIL` set, `ACME_SERVER` still on staging: `make -C deploy cert-init` succeeds
  (staging certificate), then the production directory and `make -C deploy cert-init CERTBOT_ARGS=--force-renewal`.
- [ ] `LOCAL_CA_CERT` empty, `PUBLIC_SERVER_ADDRESS` and `PUBLIC_HOST` set to the real name,
  `CANTALOUPE_HTTP_ENDPOINT` follows (`<PUBLIC_SERVER_ADDRESS>iiifserver/`, set by Compose).
- [ ] Raise `HSTS_MAX_AGE` to `31536000` after one stable week.
- [ ] 4.10 run on the production database, with the origins of the snapshot as `--from`.
- [ ] The host logrotate file and the renewal timer are installed (PP-8) and `systemctl list-timers` shows the timer.

---

## Next steps

Each PR of the workstream adds its section here, on the same model (command, expected,
what to do on failure): secrets, backups, deployed observability, accounts, Ansible, delivery, then
"Before production".
