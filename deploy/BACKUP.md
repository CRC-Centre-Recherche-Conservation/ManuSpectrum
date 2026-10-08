# Backups and restore

How the stack is backed up, how a backup is proven, and how to come back from a
lost file, a lost database or a lost host. Commands run as the service account
from the repository root, as `make -C deploy <target>`. The scripts are in
`scripts/`, the timers in `systemd/`; this page is the runbook the alerts point
to.

## What is kept where

| Copy | Where | What | Kept |
| --- | --- | --- | --- |
| A | `BACKUP_DUMP_DIR`, local disk of the service account (under `/home`) | `latest/` and `previous/`, each with `db.dump`, `globals.sql`, `manifest.json`, `env` | The last two nightly dumps |
| B | `RESTIC_REPOSITORY_DIR`, a restic repository on the network filesystem, encrypted | Copy A `latest/`, the whole `MEDIA_HOST_DIR`, `SECRETS_DIR` | 7 daily, 4 weekly, 6 monthly snapshots |
| C | The hosting provider's TSM backup, once it is activated for the VM | The daily incremental backup of the VM's `/home` includes copy A | The provider's policy |
| D | Snapshots of the VM disks, by the hosting provider | The virtual disks | The provider's policy (frequent for a week, then weekly for a month) |

Copy B is the one this repository controls, and the only one restored by the
commands below. Copy C is not an independent site: TSM runs in the same computing
centre as the VM, its storage and its snapshots, so a loss of that centre takes
every copy. A second restic repository on another site is a later decision; until
then the honest summary is that copies A to D protect against a mistake, a
corrupted database, a lost VM and a lost disk, not against the loss of the site.

### What the backups hold

- **The whole PostgreSQL database**, one `pg_dump -Fc`: the thesauri and
  controlled lists, the graphs and every designer edit, resources and tiles,
  annotations, IIIF manifests, resource relations, accounts and permissions,
  the summary and map-layer configurations, the login records.
- **The media directory** (`MEDIA_HOST_DIR`): uploaded files served by
  Cantaloupe and the concept images. Excluded inside it: `previous-*` (the data
  a restore put aside), `.restore-*` (restore staging), `archestemp/` and
  `export_deliverables/` (rebuilt on demand).
- **The secrets** (`SECRETS_DIR`, without `*.new` and `aside`) and a copy of
  `.env` (it holds no secret by rule).
- **`manifest.json`**: the row count of every table of the `public` schema taken
  in the dump's own snapshot, the latest migration of every app, the Arches and
  `pg_dump` versions, a summary of the uploads, and the checksum and size of each
  file. The restore test compares against it.

The excludes are the `RESTIC_EXCLUDES` list in `scripts/lib-backup.sh`.

### What is never backed up

| Not backed up | Why, and how it comes back |
| --- | --- |
| Elasticsearch | Derived from the database: `es reindex_database` (a restore runs it) |
| Redis | Broker and cache, rebuilt |
| Cantaloupe cache | Derived from the uploads (a restore clears it) |
| `static` | Republished from the image at each `web` start |
| TLS certificates | `make cert-init` issues them again, and a new host has a new address |
| nginx logs | Thirty days on the host; a longer copy would break that limit |

### Database and files are not taken atomically

The dump comes first and the files second. A file uploaded in between is an
orphan after a restore (harmless); a file deleted in between comes back. At 02:00
the window is seconds.

## Setup on a host

1. In `compose/.env` set `BACKUP_DUMP_DIR` (local disk, under the service
   account's home), `RESTIC_REPOSITORY_DIR` (the network filesystem) and
   `METRICS_TEXTFILE_DIR` (local disk). Create the three directories as the
   service account: the first two `0700`, the metrics directory `0755`.
2. `make -C deploy secrets` creates `restic_password`. **Put it in the vault item
   now** (`SECRETS.md`, section 3), before the first backup: without it no backup
   can ever be read.
3. `make -C deploy backup-init` creates the repository, or checks that an
   existing one opens with this password. Run it again at any time.
4. Install the timers. The configuration management does it in production; by
   hand, substitute the two placeholders and enable them:

   ```bash
   for unit in backup restore-test; do
     for kind in service timer; do
       sed -e "s|@APP_USER@|$(id -un)|" -e "s|@DEPLOY_DIR@|$PWD/deploy|" \
         deploy/systemd/manuspectrum-$unit.$kind.in |
         sudo tee /etc/systemd/system/manuspectrum-$unit.$kind >/dev/null
     done
   done
   sudo systemctl daemon-reload
   sudo systemctl enable --now manuspectrum-backup.timer manuspectrum-restore-test.timer
   ```

## Daily operation

| Unit | When | Runs | Limit |
| --- | --- | --- | --- |
| `manuspectrum-backup.timer` | Every day at 02:00 | `make -C deploy backup TAG=nightly` | `TimeoutStartSec=2h30min`: it ends before the unattended reboot at 04:50 |
| `manuspectrum-restore-test.timer` | Every Sunday at 05:30 | `make -C deploy restore-test` | `TimeoutStartSec=2h` |

Both timers are `Persistent=true`: a night missed because the host was off runs at
the next boot.

- `make -C deploy backup TAG=nightly|manual|pre-update` logs nine numbered steps.
  Only `nightly` then applies the retention (7 daily, 4 weekly, 6 monthly,
  `forget --prune`) and runs `restic check`; `manual` and `pre-update` stay short.
  It exits 0 only when the dump is verified and the restic snapshot is saved: the
  update procedure runs `make -C deploy backup TAG=pre-update` and stops on any
  other status. Exit 2 is a wrong configuration found before anything ran.
- **One lock** (`BACKUP_DUMP_DIR/.lock`) serialises backup, restore test and
  restore. A backup or a restore test waits up to an hour for it
  (`BACKUP_LOCK_WAIT`); a restore refuses at once.
- **The retention** is the constants `RETENTION_KEEP_DAILY=7`,
  `RETENTION_KEEP_WEEKLY=4` and `RETENTION_KEEP_MONTHLY=6` in
  `scripts/lib-backup.sh`: 7 daily, 4 weekly, 6 monthly. "Personal data" gives the
  reason for six months.
- Look at the repository with restic itself (interactive, one-off container):

  ```bash
  make -C deploy restic ARGS="snapshots"
  make -C deploy restic ARGS="stats"
  ```

  Snapshots carry the fixed host name `manuspectrum` (one group across a move to
  a new VM) and the tag given to `make backup`.
- **Metrics**, in `METRICS_TEXTFILE_DIR`, written atomically for the node_exporter
  textfile collector:

  | File | Written | Gauges |
  | --- | --- | --- |
  | `manuspectrum_backup.prom` | Every run | `manuspectrum_backup_last_attempt_timestamp_seconds`, `manuspectrum_backup_failed` (0 or 1) |
  | `manuspectrum_backup_success.prom` | Success only | `manuspectrum_backup_last_success_timestamp_seconds`, `manuspectrum_backup_duration_seconds`, `manuspectrum_backup_dump_bytes` |
  | `manuspectrum_restore_test.prom` | Every run | `manuspectrum_restore_test_last_attempt_timestamp_seconds`, `manuspectrum_restore_test_failed` |
  | `manuspectrum_restore_test_success.prom` | Success only | `manuspectrum_restore_test_last_success_timestamp_seconds`, `manuspectrum_restore_test_duration_seconds` |

  The monitoring alerts are `BackupFailed` (`failed == 1`), `BackupMissing` (no
  success for 26 hours, also when the timer never ran), `RestoreTestFailed` and
  `RestoreTestMissing` (no success for 8 days). Each points here.

## The restore test

```bash
make -C deploy restore-test                      # the latest snapshot
make -C deploy restore-test RESTIC_SNAPSHOT=<id>
```

It restores `/backup/db` of the snapshot into a staging directory, checks the
checksums of `manifest.json`, restores the dump into the scratch database
`<PGDBNAME>_restoretest` (created from `template_postgis`, dropped on exit
whatever happens, refused when the name equals the live database), requires the
row count of **every table** to equal the manifest, then runs
`restic check --read-data-subset=10%` (a random tenth of the repository's data is
read and verified). The live database, the uploads and the services are never
touched.

A failure is a line `FAIL:` in the log (`journalctl -u manuspectrum-restore-test`
under the timer) naming the step: a checksum or size mismatch (the snapshot or
copy A is damaged: run `make -C deploy backup` for a new one and look at the
repository, "When things go wrong"), a table whose count differs (the dump and its manifest
disagree: do not trust that snapshot), or `restic check` errors ("When things go wrong").
Until the test passes on a recent snapshot, treat the backups as unproven.

## Restore one file

A deleted upload, a secret, the `.env` copy: pull it into a separate directory,
look, and copy what you need. The running stack is not touched.

```bash
make -C deploy restore-files RESTIC_SNAPSHOT=<id|latest> \
  INCLUDE=/backup/media/uploadedfiles/<path> TARGET=/path/to/empty-dir
```

`INCLUDE` is a path inside the snapshot under `/backup/` (`/backup/db`,
`/backup/media/...`, `/backup/secrets/<name>`), without `..`. `TARGET` must be
absolute, not exist or be empty, and not inside the live uploads, `SECRETS_DIR` or
`BACKUP_DUMP_DIR/latest`. The file lands under `TARGET/backup/...`, verified.
Copy an upload back as the service account with mode `0640`, in its original
directory; for a secret, use `make -C deploy secret-set NAME=<name>`.

For the last hours, the hosting provider's `.snapshot/` directories of the
network filesystem are quicker (look for the directory by name; never `du` the
mount root).

## Restore the stack

Replaces the database and the uploads. It needs both confirmations:

```bash
make -C deploy restore RESTIC_SNAPSHOT=<id|latest> CONFIRM=yes ERASURES_CHECKED=yes
```

`ERASURES_CHECKED=yes` says you have the list of erasure requests received since
the date of the snapshot and will replay them before the site reopens: read
"Personal data" below. Without it the command refuses.

What it does: restores the dump and the uploads into staging, checks the
checksums, the migrations and the Arches version against the manifest and the free
space (nothing is changed before this passes), stops the application, dumps the
current database aside, recreates the database from `template_postgis` and
restores the dump, flushes Redis, moves the previous uploads aside and the new
ones in, clears Cantaloupe, runs `migrate`, sets the `admin` password from its
secret, refreshes the map geometries, reindexes Elasticsearch, compares the
counts with the manifest (warnings only; the strict check is the restore test),
starts the stack and smoke-tests it. The stack is down for minutes, plus the
reindex; the rehearsal figures are in `ACCEPTANCE.md`.

- **Never restored automatically:** `SECRETS_DIR` and `.env`. On the same host they
  are current; on a new host an automatic overwrite would lock the stack out of its
  own PostgreSQL. Bring them back by hand ("Moving to a new host"). The media directories other
  than `uploadedfiles/` are listed, not restored: `restore-files` pulls them.
- **Undo.** The run keeps what it replaced in
  `<MEDIA_HOST_DIR>/previous-<stamp>-<id>` (the previous uploads and
  `before-restore.dump`) and its last log line prints the command that undoes it:

  ```bash
  make -C deploy restore ASIDE=<MEDIA_HOST_DIR>/previous-<stamp>-<id> CONFIRM=yes ERASURES_CHECKED=yes
  ```

  The two newest aside directories are kept.
- After the restore, replay the erasure requests ("Personal data"), then reopen.

## Moving to a new host

1. Install the host as for a first installation (`make volumes`, directories of
   "Setup on a host", `.env`), but **before `make secrets`**:
   `make -C deploy secret-set NAME=restic_password`, typing the value from the
   vault item. `make secrets` never overwrites a file, so the order matters.
2. `make -C deploy secrets` creates the other files; set the ones you want to keep
   from the vault (`SECRETS.md`, section 5). To read an old value that is not in
   the vault, pull it from the backup:

   ```bash
   make -C deploy restore-files INCLUDE=/backup/secrets/django_secret_key TARGET=/path/to/empty-dir
   ```

   and the old `.env` the same way with `INCLUDE=/backup/db/env`.
3. Point `RESTIC_REPOSITORY_DIR` at the repository (copy it first when the
   network filesystem is not shared) and run `make -C deploy backup-init`: it
   checks that the repository opens.
4. `make -C deploy restore RESTIC_SNAPSHOT=latest CONFIRM=yes ERASURES_CHECKED=yes`.
   No `make init`: the restore recreates the database from `template_postgis`,
   which the postgres image creates in a new cluster.
5. When the public address changed, run `rewrite_dev_origin` and
   `es reindex_database` (README, rule on snapshots from another host).
6. Replay the erasure requests ("Personal data"), run `make -C deploy backup-init`, then
   `make -C deploy backup` once, then reopen.

## When things go wrong

- **"another backup or restore is running"**: wait; the lock is released when
  the process ends. A stale restic lock in the repository (a container killed in
  the middle) is cleared with `make -C deploy restic ARGS="unlock"`, after
  checking that no `restic` container runs (`docker ps`). Calls already wait up
  to 30 minutes for a held lock.
- **The repository is full or the network filesystem is down**: the run fails and
  `BackupFailed` fires. Free space or restore the mount, run `make -C deploy
  backup`. Copy A on the local disk still holds the last two dumps meanwhile.
- **Wrong password** (`backup-init` says the repository does not open): the file
  in `SECRETS_DIR` is not the one the repository was created with. Take it from
  the vault item.
- **The restic password is lost**: the backups are unreadable, all of them, and
  nothing can recover them. This is why `restic_password` goes in the vault before
  the first backup. Recover the stack from copy A or the provider's copies,
  create a new repository and start again.
- **`restic check` fails**: read the errors with
  `make -C deploy restic ARGS="check --read-data"`. Take a copy of the whole
  repository directory before trying `repair index`, then
  `make -C deploy restic ARGS="repair index"`; a damaged pack is repaired by the
  next `backup` re-uploading what is missing.

## Personal data

This section is the reference the scripts point to: `restore.sh` refuses without
`ERASURES_CHECKED=yes` and names it.

**What the backups hold.** The whole database, therefore everything personal in it:
accounts (names, e-mail addresses, password hashes, group memberships), the
records of who signed in and when, and any personal data in the scientific
records. The uploaded files and the secrets are in the repository too. nginx logs
are not.

**Retention, and why.** Snapshots follow the retention above: 7 daily, 4 weekly,
6 monthly, so the oldest backup is about six months old. The login records are
kept six months in the database. The longest a login record can exist is therefore
under twelve months: six months in the live database, then at most six months
more in the monthly snapshots. That is inside the "six months to one year" the
CNIL recommends for traces of operations
([Guide de la sécurité des données personnelles, fiche 16](https://www.cnil.fr/sites/default/files/2026-05/cnil_guide_securite_personnelle.pdf)).
The purpose of the long tail is to recover an earlier state of the scientific data
after a silent corruption found late. The retention and the encrypted copies must
appear in the register of processing and in the privacy notice.

**Encryption.** Every restic snapshot is encrypted and authenticated with the
repository key (`restic_password`); copy A and the VM copies sit on the hosting
provider's disks, as the live database does. The password is held in the vault,
never in the repository. This follows the CNIL's "back up, and protect the
backups at the same level as the servers"
([fiche 17, Sauvegarder](https://www.cnil.fr/fr/securite-sauvegarder)).

**Erasure requests are not purged from the backups.** Rewriting every snapshot to
remove one person is not reasonable. The copy is encrypted, nobody reads it
except during a restore, and the monthly rotation destroys it within six months;
the answer to the person says so. The UK regulator accepts this under conditions
that apply here too: the data is put "beyond use" and disappears on an
established schedule
([ICO, right to erasure](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/)).
The CNIL has not published a position on backups; it notes the difficulty
([bilan des contrôles, 18/02/2026](https://www.cnil.fr/fr/droit-effacement-bilan-cnil-action-europeenne)).

**After any restore, the erasures are replayed before the site reopens.** A restore
brings back people who asked to be erased since the snapshot. Keep a register of
erasure requests (date, internal identifier, what was removed or anonymised, no
more personal data than needed) outside the backed-up database, and keep each entry
as long as a snapshot older than the erasure exists (six months and a day, then
purge it). Before `make restore`:

1. list the requests dated after the snapshot you restore;
2. run the restore with `ERASURES_CHECKED=yes`;
3. replay each request on the restored database;
4. only then reopen the site.

**Breach register.** Every loss of availability, integrity or confidentiality of
personal data is recorded in the internal breach register, including a restore
after a loss: date, what was lost, snapshot used, data window lost, decision on
notification (GDPR art. 33.5;
[CNIL, fiche 19](https://www.cnil.fr/fr/securite-gerer-les-incidents-et-les-violations)).

**Notification to the CNIL within 72 hours, only when there is a risk.** A breach
is notified within 72 hours of discovery unless it is unlikely to create a risk for
people (GDPR art. 33.1). The CNIL lists as not notifiable the deletion of data that
was backed up and immediately restored, and the loss of data protected by
state-of-the-art encryption whose key is safe and of which a copy remains
([Les violations de données personnelles](https://www.cnil.fr/fr/les-violations-de-donnees-personnelles)).
A restore that returns the site to the last night's state with nothing personal
lost beyond the day's activity is recorded, not notified. A loss of the only copy
of accounts, or a leak of the repository together with its password, is assessed
for risk at once and notified when there is one.

## Limits

- Copy B is on the same infrastructure as the VM; copy C is in the same computing
  centre ("What is kept where"). There is no second site yet.
- The media directory has no off-site copy until TSM covers it or a second
  repository is chosen.
- Restores are logical: minutes of downtime and an Elasticsearch reindex, not a
  hot failover.
- The backup is as old as its last night: up to a day of edits is lost.
