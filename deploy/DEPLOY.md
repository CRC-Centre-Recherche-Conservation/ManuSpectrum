# Rebuild production from zero

The ordered path from a fresh VM to the site online. Each step names the command
and the document that explains it; this file repeats none of them. Host values
(address, accounts, paths) are `<placeholders>`: the real ones live in the
Ansible inventory and in the host's password-manager item, never in Git.

Shells used below:

- **laptop**: the administrator's checkout, where Ansible runs;
- **admin**: SSH as your own account (`<account>@<host>`, with `sudo`);
- **service**: the service account, in its checkout (`sudo -iu <service account>`,
  then `cd` to the application directory). Every `make -C deploy` command runs there.

Restoring from a backup instead of installing an empty site: step 7 has the branch.

## Before you start

1. **Vault item.** Create the item `ManuSpectrum <host> secrets` in the password
   manager ([SECRETS.md](SECRETS.md#3-the-vault-item)). It will hold the
   inventory (step 3) and one field per secret (step 5).
2. **The host** is provided with the base system, SSH access for the administrators,
   ports 80 and 443 open, a DNS name pointing at it and an outgoing mail relay.
   What is checked is listed in [ansible/README.md](ansible/README.md#prerequisites).
3. **Laptop checkout on the release tag**, clean tree, package at its pinned commit:

   ```bash
   git fetch --tags origin
   git switch --detach vX.Y.Z
   git submodule update --init --force
   git status --short                  # nothing
   ```

4. **Ansible** in a virtual environment and the collections
   ([ansible/README.md](ansible/README.md#prerequisites)):

   ```bash
   python3.12 -m venv ~/.venvs/ansible
   ~/.venvs/ansible/bin/pip install -r deploy/ansible/requirements-dev.txt
   ~/.venvs/ansible/bin/ansible-galaxy collection install -r deploy/ansible/requirements.yml
   ```

## The installation

1. **Inventory.** Copy `deploy/ansible/inventories/example/` to
   `deploy/ansible/inventories/<host>/` and set every value
   ([ansible/README.md](ansible/README.md#inventory)). Set `app_git_ref` to the
   tag, `env_manuspectrum_image` to the digest of that release
   ([RELEASES.md](RELEASES.md#verify-an-image-by-hand)), `env_acme_server` to the
   Let's Encrypt **staging** directory for now, and `env_hsts_max_age` to `"3600"`.
   Git ignores the directory: keep a copy in the vault item.

2. **Check the host, then the first pass** (laptop):

   ```bash
   cd deploy/ansible && export ANSIBLE_CONFIG=$PWD/ansible.cfg
   ~/.venvs/ansible/bin/ansible-playbook -i inventories/<host> site.yml --ask-become-pass --tags preflight,baseline
   ~/.venvs/ansible/bin/ansible-playbook -i inventories/<host> site.yml --ask-become-pass
   ```

   The first command only asserts (`failed=0`); a failure means the host differs
   from the inventory: change nothing, fix the inventory or ask the hosting
   provider. The second prepares the host, then lists the closed gates (secrets,
   certificate, database) and ends with exit code 0. That is expected
   ([ansible/README.md](ansible/README.md#first-installation)).

3. **Secrets** (service):

   ```bash
   make -C deploy secrets
   ```

   Copy each secret into the vault item, `restic_password` first: without it no
   backup can be read ([SECRETS.md](SECRETS.md#1-inventory)). Then:

   ```bash
   make -C deploy secrets-check
   ```

   One `ok` per file, no value printed. On a host that holds the vault values
   already, set them with `make -C deploy secret-set NAME=<secret>` instead
   ([SECRETS.md](SECRETS.md#5-restore-on-a-new-host)).

4. **Certificate** (service), staging first ([certs/README.md](certs/README.md)):

   ```bash
   make -C deploy cert-init
   ```

   Then set `env_acme_server` to the production directory in the inventory, run
   the playbook again, and replace the certificate:

   ```bash
   make -C deploy cert-init CERTBOT_ARGS=--force-renewal
   ```

   With `CERT_MODE=provided`, put `fullchain.pem` and `privkey.pem` in
   `CERTS_DIR/live` and run `make -C deploy nginx-reload`.

5. **Database and package** (service), once: it refuses when the database exists
   ([README.md](README.md#rules), « The first installation goes through `make init` only »).

   ```bash
   make -C deploy init
   ```

   If the image is not in a registry yet, `make -C deploy build` comes first, on
   a machine with the memory for it (never the development VM).

6. **Second pass** (laptop): run the playbook again. It goes to the end: stack
   up, ports and `/readyz` checked, timers enabled. Then (service):

   ```bash
   make -C deploy silence-fresh-install
   make -C deploy status
   make -C deploy smoke
   deploy/compose/smoke.sh edge
   ```

   The silence lasts 48 hours and includes `ContainerMissing`: check
   `make -C deploy status` meanwhile
   ([OBSERVABILITY.md](OBSERVABILITY.md#alerts)).

7. **Backups** (service) ([BACKUP.md](BACKUP.md#setup-on-a-host)):

   ```bash
   make -C deploy backup-init
   make -C deploy backup TAG=manual
   make -C deploy restore-test
   make -C deploy alert-test
   ```

   `alert-test` must deliver a mail to `ALERT_EMAILS` within five minutes
   ([OBSERVABILITY.md](OBSERVABILITY.md#recipients-and-sender)).

8. **Accounts and two-factor** ([ADMIN.md](ADMIN.md#create-an-account-and-invite-the-person)):
   sign in as `admin` with the `admin_password` secret, create the administrators'
   accounts and send the invitations. When they have enrolled
   ([ADMIN.md](ADMIN.md#two-factor-authentication)), set
   `env_force_two_factor_authentication: "true"` in the inventory and run the
   playbook again.

9. **Data.** The package holds no business data. After an import:

   ```bash
   make -C deploy manage ARGS="repair_file_metadata --apply"
   make -C deploy manage ARGS='shell -c "from django.db import connection; connection.cursor().execute(\"SELECT refresh_geojson_geometries()\")"'
   make -C deploy backup TAG=manual
   ```

   The second command fills the map layers' geometries (an import does not).

10. **After going live.**
    - Next morning: the night backup did not fail, `make -C deploy alerts` shows
      nothing unexpected.
    - After a week: `env_hsts_max_age: "31536000"`, run the playbook, then
      `make -C deploy nginx-reload`.
    - First Sunday: the `restore-test` of 05:30 passed.
    - The status page (the external probe, see [INCIDENT.md](INCIDENT.md)) watches
      the new site.
    - The vault item holds the current inventory and every secret.

## Restore from backup instead of an empty install

For a new host that takes over an existing site, replace steps 3, 5 and 7:

1. Run steps 1 and 2, and the certificate (step 4).
2. Set `restic_password` first from the vault, then the other secrets, before
   `make -C deploy secrets` ([BACKUP.md](BACKUP.md#moving-to-a-new-host),
   [SECRETS.md](SECRETS.md#5-restore-on-a-new-host)).
3. `make -C deploy backup-init`, then
   `make -C deploy restore RESTIC_SNAPSHOT=latest CONFIRM=yes ERASURES_CHECKED=yes`.
   Never run `make init` here.
4. Replay the erasure requests received since the snapshot
   ([BACKUP.md](BACKUP.md#personal-data)), run the playbook again, then take a
   backup before reopening.

The restore of an existing host after a loss is
[BACKUP.md](BACKUP.md#restore-the-stack).

## Roll back a release

- **The update rolls back by itself** when the new version does not answer
  `/readyz` in time. It returns to the previous image and commit, never restores
  data, and leaves the release armed:
  [ADMIN.md](ADMIN.md#after-a-rollback), alert `UpdateRolledBack`
  ([runbooks/release.md](runbooks/release.md#updaterolledback)).
- **The rollback failed** (exit code 4, mail `ROLLBACK FAILED`):
  [ADMIN.md](ADMIN.md#after-a-failed-rollback) and
  [runbooks/release.md](runbooks/release.md#updaterollbackfailed). Restoring the
  `pre-update` backup is a human decision.
- **A release that started but misbehaves** has no downgrade command: migrations
  stay applied. Ship a fixed release, or restore the `pre-update` backup as in
  the failed-rollback procedure.

## Annual maintenance window

Once a year, outside 03:50 to 05:05 (the host reboots at 04:50); announce it with
a site notice (`make -C deploy site-notice`) and a `maintenance` issue
([INCIDENT.md](INCIDENT.md#planned-maintenance)).

1. **Operating system.** Upgrade the host with the hosting provider, reboot, then
   `make -C deploy status` and `make -C deploy smoke`. The baseline is re-checked
   by `--tags preflight,baseline` (step 2).
2. **Release.** Install the newest signed release
   ([ADMIN.md](ADMIN.md#updating-the-application)).
3. **Certificate.** `make -C deploy cert-renew` reports nothing due, or renews; the
   alerts `CertificateExpiringSoon` and `CertificateInvalid` are quiet
   ([runbooks/tls.md](runbooks/tls.md)).
4. **Accepted vulnerabilities.** Review the expiry dates in `.trivyignore` at the
   repository root: each one forces a new decision.
5. **Backups.** `make -C deploy restore-test` passes and the repository is checked
   ([BACKUP.md](BACKUP.md#the-restore-test)). The retention is 7 daily, 4 weekly,
   6 monthly.
6. **Accounts.** Read the « Comptes inactifs » section of the monthly report and
   decide ([ADMIN.md](ADMIN.md#inactive-accounts)); remove from the vault
   collection and from `admin_users` anyone who left, and rotate the secrets if
   someone with host or vault access left ([SECRETS.md](SECRETS.md#7-when-to-rotate)).
7. **Embargoes.** Review the open restrictions ([ADMIN.md](ADMIN.md#restrictions-embargoes)).
8. **Vault item.** Compare it with the host: `make -C deploy secrets-check`, and the
   inventory copy against `deploy/ansible/inventories/<host>/`.
9. **Alert recipients.** Check that `ALERT_EMAILS` still names the right people
   (`make -C deploy alert-test`).
