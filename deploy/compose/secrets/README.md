# Secret files

Compose reads three files from this directory (or from `SECRETS_DIR` in `.env`):

- `pg_password`: password of the PostgreSQL superuser.
- `elastic_password`: password of the Elasticsearch `elastic` user.
- `django_secret_key`: Django `SECRET_KEY` (at least 50 characters).

One value per file, without a trailing newline.

```bash
openssl rand -base64 48 | tr -d '\n' > pg_password
openssl rand -base64 48 | tr -d '\n' > elastic_password
python3 -c "import secrets; print(secrets.token_urlsafe(64), end='')" > django_secret_key
```

Modes: the directory `0700`, owned by the service account; the files `0444`
(the Elasticsearch container reads its file under its own uid, the directory
mode is the barrier on the host).

The files are never committed (`.gitignore` here ignores everything but this
README), never put in an image, a log or a clear-text backup. PP-2 replaces
this manual step with sops.
