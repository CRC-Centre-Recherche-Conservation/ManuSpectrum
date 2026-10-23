# Deployment

Everything needed to build and run ManuSpectrum as containers. Nothing here
belongs to one host: host-specific values live in `deploy/compose/.env` (never
committed) and in the secret files of `SECRETS_DIR`.

## Layout

| Path | Role |
| --- | --- |
| `docker/Dockerfile` | Multi-stage production image (webpack, uv, runtime) |
| `docker/entrypoint.sh` | Container commands: `web`, `worker`, `beat`, `init`, `manage` |
| `docker/publish-static.sh` | Publishes the image's static files into the shared volume |
| `docker/gunicorn.conf.py` | gunicorn settings of `web` |
| `docker/placeholder.env`, `docker/probe-image.sh` | Build-time values and the image probe |
| `compose/compose.yaml` | The stack: security, health checks, persistence |
| `compose/compose.prod.yaml` | Sizing of the production host only |
| `compose/.env.example` | Variables to copy into `compose/.env` |
| `compose/secrets/` | Secret files read by Compose (see its README) |
| `compose/postgres/init/` | Creates `template_postgis` the way Arches does |
| `compose/smoke.sh` | Checks of a running stack |
| `compose/tests/` | Rules of the rendered Compose files (no container is started) |
| `Makefile` | Operator commands |
| `rehearsal/` | Rehearsal VM kit |

## Commands

Run as `make -C deploy <target>`; every target uses both Compose files.

| Target | Effect |
| --- | --- |
| `help` | List the targets |
| `config` | Validate the merged Compose files |
| `volumes` | Create the external data volumes (once per host, idempotent) |
| `build` | Build the image (CI or rehearsal VM only) |
| `init` | First installation: Arches `setup_db` then the `admin` password from the `admin_password` secret, refused when the database exists |
| `admin-password` | Set (or rotate) the `admin` password from the `admin_password` secret |
| `manage` | Run `manage.py ARGS` in a one-off `web` container (interactive); the commands that drop the database stay refused |
| `up` | Start or update the stack and wait until it is healthy |
| `down` | Stop and remove the containers; volumes are kept |
| `restart` | Restart `web`, `worker` and `beat` |
| `status` | Containers and their health |
| `logs` | Follow the last 200 lines of every service |
| `smoke` | Read-only checks of the running stack |
| `secrets` | Create the secrets directory (`0700`) and the missing secret files |

## Rules

- Data volumes (`ms_pg_data`, `ms_es_data`, `ms_redis_broker`,
  `ms_cantaloupe_cache`) are external: `make volumes` creates them, no
  Compose command deletes them, `down -v` included. No target removes a
  volume; deleting one is a deliberate `docker volume rm` typed by an
  operator, never part of an update. Never run `down -v` in production.
- Media is a bind mount of `MEDIA_HOST_DIR`, which must exist beforehand with
  an `uploadedfiles/` subdirectory owned by `APP_UID`; Docker never creates it.
- Static files are not persistent: each `web` start republishes them from the
  image into `/srv/static/current`.
- `web`, `worker` and `beat` run as `APP_UID:APP_GID` on a read-only root
  filesystem; the image works under any uid.
- The first installation goes through `make init` only. It refuses to run when
  the database exists, because `setup_db` drops and recreates it. The
  entrypoint's `manage` refuses every command that would do it: `setup_db`,
  `packages ... -db` / `--setup_db`, `packages -o setup`. `web` refuses to
  start on a database that exists without the Arches system settings.
- A failed first installation (the database is half created): `make init`
  refuses because the database exists, and `web` logs
  `has no Arches system settings`. Drop the database and start again:
  `docker compose ... exec postgres sh -c 'dropdb -U "$POSTGRES_USER" <PGDBNAME>'`
  (the `dc` alias of `ACCEPTANCE.md`), then `make -C deploy init`.
- Secrets: `make -C deploy secrets` creates the `0700` directory and the
  missing files, including an empty `email_password` (a relay without
  authentication) and `admin_password`, the password `init` gives the
  superuser `admin` in place of Arches' public default `admin`.
- `web` runs gunicorn `gthread`: `GUNICORN_WORKERS` processes of
  `GUNICORN_THREADS` threads each; production sets 5 x 4, a ceiling of 20
  concurrent requests.
- The development VM never builds the image nor starts the stack.
- No service publishes a port; the reverse proxy comes later.

## Checks

`deploy-lint.yml` renders the Compose files, runs the tests of `compose/tests/`,
lints the shell scripts and checks `uv.lock`. The smoke checks run in CI
with `compose/smoke.sh`.

## What comes next

- PP-2: secrets managed with sops instead of manual files.
- PP-3: nginx and TLS, the only published ports.
- PP-5: `/readyz` and JSON logs.
- PP-7: backups.
- PP-8: Ansible writes `.env` and creates the volumes.
- PP-10: image publication and the update command.
