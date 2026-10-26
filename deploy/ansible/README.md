# Ansible: install and verify a ManuSpectrum host

One `ansible-playbook site.yml`, run from the administrator's laptop, brings an
Ubuntu or Debian host to the state `deploy/` expects, verifying what the
host's system administrator already set and applying the rest, then proves it.

Roles, played in order:

| Role | What it does |
|---|---|
| `preflight` | Assertions only: OS, memory, CPUs, free space, Docker version, `vm.max_map_count`, clock, ports 80/443, DNS (warning), SMTP relay. |
| `baseline` | `baseline_mode: apply` sets the system baseline (accounts, sshd, UFW, fail2ban, Docker CE, data mount, unattended-upgrades, postfix); both modes then run the same assertion list on the host's effective state (`sshd -T`, `ufw status`, `apt-config dump`, `findmnt`...). |
| `host` | `/etc/docker/daemon.json` (validated by `dockerd --validate`) and the journald drop-in. |
| `app` | Directories, checkout, `.env`, logrotate and systemd units, then the gates, `make up`, the checks and the timers. |

It never runs `make init`, `make restore`, `make cert-init` or `make secrets`,
never moves an existing checkout (it clones only when `app_dir/.git` is
absent) and never writes a secret.

## Prerequisites

- A controller with **Python 3.12 or later** and **ansible-core 2.20**: Ubuntu
  26.04 runs Python 3.14 and only ansible-core 2.20 and later manage a 3.14
  target (the reasoning is in `requirements-dev.txt`). Install the pinned tools
  in a virtual environment, never system-wide:

  ```bash
  python3 -m venv ~/.venvs/ansible
  ~/.venvs/ansible/bin/pip install -r deploy/ansible/requirements-dev.txt
  ~/.venvs/ansible/bin/ansible-galaxy collection install -r deploy/ansible/requirements.yml
  ```

- A personal SSH account on the host with a key and `sudo`. The playbook asks
  for the sudo password at every run (`--ask-become-pass`): there is no
  `deploy` user and no `NOPASSWD`. Nothing is installed on the host besides
  what the playbook sets.

## Inventory

`inventories/example/` holds fake values only. A real inventory is a copy of
that directory named after the host (`inventories/<host>/`). Git ignores
everything under `inventories/` except `example/`, so keep a copy in the
host's password-manager item (Bitwarden). No secret belongs in an inventory:
secrets stay in `SECRETS_DIR` on the host (`deploy/SECRETS.md`). Every
variable is explained in `inventories/example/group_vars/all.yml`; the
`env_<key>` variables are the keys of `deploy/compose/.env.example`.

## First installation

1. `ansible-playbook -i inventories/<host> site.yml --ask-become-pass`. The
   play prepares the host and stops at the first closed gate with the list of
   what is still to do (exit code 0).
2. On the host, as the service account: `make -C deploy secrets`, then copy
   the secrets into the password-manager item.
3. `make -C deploy cert-init` (`CERT_MODE=acme`) or `make -C deploy certs-local`
   (`local`); with `provided`, put `fullchain.pem` and `privkey.pem` in
   `CERTS_DIR/live`.
4. `make -C deploy build` if the image is not in a registry, then
   `make -C deploy init`.
5. Run the playbook again: it goes to the end (stack up, ports and `/readyz`
   checked, timers enabled). It reminds you to run
   `make -C deploy silence-fresh-install`.

## Changing hosts

Copy the inventory directory, adjust it (`ansible_host`, domain, paths), then
run the playbook: it stops at the secrets gate. `make -C deploy secret-set
NAME=<secret>` for each secret from the password manager, restore the
certificate, `make -C deploy restore RESTIC_SNAPSHOT=<id> CONFIRM=yes
ERASURES_CHECKED=yes` (`deploy/BACKUP.md`), run the playbook again, switch the
DNS, and with `CERT_MODE=acme` run `make -C deploy cert-init`.

## Verifying a host the system administrator set up

`baseline_mode: verify` (the default of the example) asserts the baseline
without touching it; only the effective state counts, never our files.
To check the baseline alone:

```bash
ansible-playbook -i inventories/<host> site.yml --ask-become-pass --tags preflight,baseline
```

`baseline_mode: apply` sets everything, then runs the same assertions. On
Ubuntu 26.04 the Docker repository must have a suite for the release; if it
has none, apply stops and names `docker_apt_codename` (set it to a suite that
exists, for example `noble`); it never installs from another suite silently.
`vm.max_map_count` is only verified, never written. sshd is checked with
`sshd -t` and reloaded, never restarted.

A second run on an installed host reports `changed=0`.

## How the `app` role decides

Four gates, each a fact: `app_gate_secrets` (`make secrets-check`),
`app_gate_image` (`docker image inspect`, and `docker pull` when the image
name carries a registry host), `app_gate_cert` (`fullchain.pem` and
`privkey.pem` in `CERTS_DIR/live`) and `app_gate_db`.

The database gate must answer while the stack is down and without writing.
When the postgres container runs, it reads the Arches system settings row
(`SELECT` through `docker exec ... psql`, the row the web entrypoint demands).
When it does not run the gate stays closed, and the `PG_VERSION` file of the
`ms_pg_data` volume (a `stat`, no container started) only decides which hint
is printed: never initialised (`make -C deploy init` or `restore`) or stopped
(start postgres, then run again). `make -C deploy init` leaves postgres up, so
the second pass finds it.

`changed` reporting relies on documented output: `make volumes` prints
`<volume> exists` for an existing volume; `make up` changes when Docker
Compose prints `Container <name> Created|Recreated|Started` (checked against
Compose v2.32; `Running` and `Healthy` are not changes). With the
`observability` profile, `make monitoring-init` runs before `make up`
(the exporters' health checks need its role).

## The running version

Ansible never changes the running version; the update command does. The
rendered `.env` takes `MANUSPECTRUM_IMAGE` from the inventory
(`env_manuspectrum_image`) only while no `.env` exists (first installation);
afterwards the value already in `.env` is kept, and the image gate checks that
one.

## Audit and checks without a host

`ansible-playbook -i inventories/<host> audit.yml --ask-become-pass` installs
lynis, runs it and fails under `lynis_min_index`; it is on demand, never
scheduled.

CI (and you, before a push) runs, from `deploy/ansible/`:

```bash
ansible-lint --profile production
ansible-playbook --syntax-check -i inventories/example site.yml audit.yml
python3 -m unittest discover -s tests
ansible-playbook -i inventories/example render.yml -e render_dir=/tmp/rendered
RENDERED_UNITS_DIR=/tmp/rendered/units bash ../systemd/tests/test_units.sh
```

`render.yml` renders `.env`, the twelve units and the logrotate rule from the
example inventory into a scratch directory, without privileges.
