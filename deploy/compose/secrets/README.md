# Secret files

Compose reads six files from this directory (or from `SECRETS_DIR` in `.env`):

- `pg_password`: password of the PostgreSQL superuser.
- `elastic_password`: password of the Elasticsearch `elastic` user.
- `django_secret_key`: Django `SECRET_KEY` (at least 50 characters).
- `email_password`: password of the SMTP relay. The file must exist; leave it
  empty for a relay without authentication.
- `admin_password`: password of the Arches superuser `admin`. `setup_db` creates
  that account with the publicly known password `admin`; `make -C deploy init`
  replaces it with this file's content right after (`set_admin_password`).
  Mounted on `web` only. At least 16 characters.
- `restic_password`: password of the backup repository, mounted on the `restic`
  service only (profile `backup`). At least 32 characters. Keep it in the vault
  before the first backup: without it no backup can be read (`deploy/BACKUP.md`).

One value per file, without a trailing newline. `make -C deploy secrets`
creates the directory (`0700`) and every missing file (the generated ones as
below, `email_password` empty) with the modes described next; it never
overwrites an existing file.

```bash
openssl rand -base64 48 | tr -d '\n' > pg_password
openssl rand -base64 48 | tr -d '\n' > elastic_password
python3 -c "import secrets; print(secrets.token_urlsafe(64), end='')" > django_secret_key
openssl rand -base64 48 | tr -d '\n' > admin_password
openssl rand -base64 48 | tr -d '\n' > restic_password
```

Modes: the directory `0700`, owned by the service account; the files `0444`
(the Elasticsearch container reads its file under its own uid, the directory
mode is the barrier on the host). The Elasticsearch image wants a `0400` or
`0600` password file: its Compose entrypoint hands it a `0600` copy made
inside the container, so the host file stays `0444`.

Rotating `pg_password` or `elastic_password` after the first start does not
change what PostgreSQL and Elasticsearch already store: the services keep the
old password and the applications, given the new one, fail to authenticate.
Change the password inside the service first, then the file: the exact
commands are in `deploy/SECRETS.md`.

Operator procedure for `admin_password` (the break-glass account):

1. Read it once, as the service account:
   `sudo -iu <service-account> cat <SECRETS_DIR>/admin_password`.
2. Store it immediately in the institution's password manager.
3. Log in as `admin`, create a named account for each operator, and use those
   accounts day to day; `admin` is kept for emergencies.
4. Change it whenever needed, from the profile page or interactively with
   `make -C deploy manage ARGS="changepassword admin"`. The file then no
   longer matches and only served the installation: the password manager is
   the reference. To reset the account to the file's value instead, write the
   new value into the file (deliberately; `make secrets` never replaces it),
   then `make -C deploy admin-password`.

The off-host copy of the secrets is one item of the project's password manager,
and `make -C deploy secret-set NAME=<name>` puts a value back from it without
echo or argument; `make -C deploy secrets-check` verifies the directory. Both,
the rotation of each secret and the restore are in `deploy/SECRETS.md`.

The files are never committed, encrypted or not (`.gitignore` here ignores
everything but this README), never put in an image, a log or a clear-text
backup.
