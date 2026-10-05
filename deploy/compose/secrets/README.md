# Secret files

Compose reads four files from this directory (or from `SECRETS_DIR` in `.env`):

- `pg_password`: password of the PostgreSQL superuser.
- `elastic_password`: password of the Elasticsearch `elastic` user.
- `django_secret_key`: Django `SECRET_KEY` (at least 50 characters).
- `email_password`: password of the SMTP relay. The file must exist; leave it
  empty for a relay without authentication.

One value per file, without a trailing newline. `make -C deploy secrets`
creates the directory (`0700`) and every missing file (the generated ones as
below, `email_password` empty) with the modes described next; it never
overwrites an existing file.

```bash
openssl rand -base64 48 | tr -d '\n' > pg_password
openssl rand -base64 48 | tr -d '\n' > elastic_password
python3 -c "import secrets; print(secrets.token_urlsafe(64), end='')" > django_secret_key
```

Modes: the directory `0700`, owned by the service account; the files `0444`
(the Elasticsearch container reads its file under its own uid, the directory
mode is the barrier on the host). The Elasticsearch image wants a `0400` or
`0600` password file: its Compose entrypoint hands it a `0600` copy made
inside the container, so the host file stays `0444`.

Rotating `pg_password` or `elastic_password` after the first start does not
change what PostgreSQL and Elasticsearch already store: the services keep the
old password and the applications, given the new one, fail to authenticate.
Change the password inside the service first (`ALTER USER`, the Elasticsearch
security API), then the file.

The files are never committed (`.gitignore` here ignores everything but this
README), never put in an image, a log or a clear-text backup. PP-2 replaces
this manual step with sops.
