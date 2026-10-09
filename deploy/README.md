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
| `compose/secrets/` | Secret files read by Compose (see its README); the default `SECRETS_DIR` |
| `BACKUP.md` | Backups: what is kept where, the schedule, the restore test, restore of a file or of the stack, moving day, personal data |
| `SECRETS.md` | Secret inventory, the vault item, restore and rotation of each secret, scanning |
| `scripts/` | `secret-set.sh`, `secrets-check.sh`, `gitleaks.sh`, `load-snapshot.sh`, `backup.sh`, `restore-test.sh`, `restore.sh`, `restore-files.sh`, the libraries they share and their tests |
| `compose/postgres/init/` | Creates `template_postgis` the way Arches does |
| `compose/nginx/` | nginx configuration: `nginx.conf`, the server template (names, HSTS), `snippets/` (TLS, headers, edge rules, rate limits, media, IIIF image server, logs), error pages, `tests/test_edge.sh` |
| `compose/certbot/` | Deploy hook of the `certbot` service (`CERT_MODE=acme`) |
| `certs/` | `make-local-ca.sh` (rehearsal CA, self-signed placeholder), `README.md` (modes, trust), tests |
| `logrotate/` | Host `logrotate` template for the nginx logs (thirty days) |
| `systemd/` | Service and timer templates: certificate renewal, nightly backup (02:00), weekly restore test (Sunday 05:30) |
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
| `smoke` | Read-only checks of the running stack (`smoke.sh edge` checks nginx over HTTPS) |
| `nginx-test` | `nginx -t` in the running container |
| `nginx-reload` | Check, then reload nginx (new certificate or configuration) |
| `certs-local` | `CERT_MODE=local`: make the rehearsal CA and the certificate for `DOMAIN_NAMES` in `CERTS_DIR` |
| `cert-init` | `CERT_MODE=acme`: placeholder certificate, nginx up, first certificate, reload (`CERTBOT_ARGS=--force-renewal` to replace one) |
| `cert-renew` | `CERT_MODE=acme`: renew when due, reload nginx only if the certificate changed |
| `secrets` | Create the secrets directory (`0700`) and the missing secret files |
| `secret-set` | `NAME=<secret> [FORCE=yes]`: write one secret file from a value typed twice without echo, or piped on stdin; never an argument |
| `secrets-check` | Presence, modes and lengths of the secret files, one line each, no value printed |
| `backup-init` | Once per host: create the restic repository, or check that it opens with `restic_password` (idempotent) |
| `backup` | `[TAG=nightly\|manual\|pre-update]`: dump, uploads and secrets into copy A and the restic repository; `nightly` also applies the retention and checks; exit 0 only when saved |
| `restore-test` | `[RESTIC_SNAPSHOT=<id>]`: restore the latest backup into a scratch database and compare every table with the manifest |
| `restore` | `RESTIC_SNAPSHOT=<id\|latest>` or `ASIDE=<dir>`, `CONFIRM=yes ERASURES_CHECKED=yes`: replace the database and the uploads from a backup |
| `restore-files` | `INCLUDE=/backup/... TARGET=<dir> [RESTIC_SNAPSHOT=<id>]`: pull files from a backup into a separate directory |
| `restic` | `ARGS="snapshots"`: run restic on the repository, interactive |

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
- The data package (graphs, controlled lists, System Settings) is the `pkg`
  git submodule. Clone with `git clone --recurse-submodules …`, or run
  `git submodule update --init` in an existing clone. `PKG_DIR` in the env file
  (default `../../pkg`, relative to `deploy/compose`) names the directory; the
  image never contains it.
- The first installation goes through `make init` only. It runs the `init`
  service (profile `init`, not started by `up`): `setup_db`, the admin password,
  then `packages -o load_package -s /srv/pkg -y` (the package, mounted
  read-only) and `i18n synclanguages`; the controlled lists are made searchable
  by the package's own post SQL.
  It takes several minutes longer than `setup_db` alone (graphs, 30 000 list
  values, a full reindex). It refuses to run when the database exists, because
  `setup_db` drops and recreates it; before `setup_db` it also refuses an empty
  or missing package (`git submodule update --init`); `make init` itself refuses
  when `git submodule status pkg` shows the package is not at the commit the
  checkout pins (`-`, `+` or `U`: `git submodule update --init` first; the check
  is skipped, with a notice, when `PKG_DIR` resolves to another directory; outside a
  Git checkout (a release archive) or without `git`, `make init` refuses until
  `PKG_DIR` names an extracted package). A
  `PUBLIC_SERVER_ADDRESS` without trailing slash is refused by the deployment
  checks (`settings_docker.py`): the lists would lose their sort order. `load_package` copies the package's `System_Settings.json` into
  the application directory, so the `init` service puts a tmpfs on
  `/app/manuspectrum/system_settings`; the image's own copy is not read during
  `init`. At the end `init` runs the application's
  `manage.py check_pkg_inventory` against the package's `expected-inventory.json`
  (a difference fails `init`) and warns when the origin the package was
  written for differs from `PUBLIC_SERVER_ADDRESS` (the list sort orders are
  then not loaded; acceptable on a rehearsal host only). The
  entrypoint's `manage` refuses every command that would do it: `setup_db`,
  `packages ... -db` / `--setup_db`, `packages -o setup`. `web` refuses to
  start on a database that exists without the Arches system settings.
- A failed first installation (the database is half created, a package
  step failed): `make init` refuses because the database exists, and `web` may
  log `has no Arches system settings`. Drop the database and start again:
  `docker compose ... exec postgres sh -c 'dropdb -U "$POSTGRES_USER" <PGDBNAME>'`
  (the `dc` alias of `ACCEPTANCE.md`), then `make -C deploy init`.
- Secrets: `make -C deploy secrets` creates the `0700` directory and the
  missing files, including an empty `email_password` (a relay without
  authentication) and `admin_password`, the password `init` gives the
  superuser `admin` in place of Arches' public default `admin`.
  `secret-set` and `secrets-check` restore and verify them; the off-host copy
  is one item of the project's password manager, never a file in Git, and the
  rotation of each secret is in `SECRETS.md`.
- Backups (`BACKUP.md`): a nightly dump of the whole database (copy A, two
  generations) and a restic repository (copy B: dump, `MEDIA_HOST_DIR`,
  `SECRETS_DIR`) kept 7 daily, 4 weekly and 6 monthly; a weekly restore test into
  a scratch database. One lock serialises backup, restore test and restore.
  `make restore` needs `CONFIRM=yes` and `ERASURES_CHECKED=yes`, and never writes
  `SECRETS_DIR` or `.env`: on a new host `restic_password` comes from the vault
  first, the rest is pulled with `restore-files`. Elasticsearch, Redis, the
  Cantaloupe cache, static files, certificates and nginx logs are not backed up.
- Upgrading a host that already has a `.env`: add `BACKUP_DUMP_DIR`,
  `RESTIC_REPOSITORY_DIR` and `METRICS_TEXTFILE_DIR` (see `compose/.env.example`)
  **before pulling this version**. Compose interpolates the services of a disabled
  profile too, so without the three keys every Compose command, `up` included,
  fails with `set BACKUP_DUMP_DIR in .env`. Then create the directories and run
  `make -C deploy backup-init` (`BACKUP.md`, "Setup on a host").
- `web` and `init` run Django's deployment checks first
  (`check --deploy --tag security --fail-level WARNING`) and refuse to start
  on any warning.
- `web` runs gunicorn `gthread`: `GUNICORN_WORKERS` processes of
  `GUNICORN_THREADS` threads each; production sets 5 x 4, a ceiling of 20
  concurrent requests.
- The development VM never builds the image nor starts the stack.
- Only `nginx` publishes ports (`HTTP_PORT` and `HTTPS_PORT`, 80 and 443 by
  default); it listens on 80 and 443 inside its container, as the service account.
  No other service publishes a port.
- nginx never serves `MEDIA_ROOT` or `/files/` directly: the bytes of an uploaded
  file leave nginx only after Arches' `FileView` has answered for that file id
  and nginx has followed its 302 internally.
- `/iiifserver/` goes straight to Cantaloupe, with its own rate limit; nginx
  hides Cantaloupe's CORS headers and sets one `Access-Control-Allow-Origin: *`.
- Every rule above the language boundary carries `(en|fr)`; a new language
  edits every alternation. `tests/test_edge_contract.py` fails otherwise, and
  `compose/nginx/tests/test_edge.sh` runs every rule against a real nginx and a
  stub upstream (also inside `check-stack.sh`).
- nginx owns HSTS (`HSTS_MAX_AGE`), Permissions-Policy and the Report-Only CSP;
  Django owns X-Frame-Options, nosniff and Referrer-Policy. The querysets API,
  `/silk/`, `/metrics` and `/readyz` are refused at the edge. The 404, 429 and
  50x pages are nginx's own; the 50x page is the site's
  `manuspectrum/templates/errors/500.htm`.
- Trust boundary: gunicorn's `forwarded_allow_ips="*"` and the client address
  Django reads from `X-Real-IP` (`utils/client_ip.py`) are safe only because
  nothing but nginx reaches `web:8000` (the port is not published and the
  network is internal). Never publish that port or attach another service
  that can send requests to it: both headers become spoofable.
- Rate limits and timeouts live in nginx (`snippets/ratelimit.conf`,
  `edge-rules.conf`); the client IP read by Django comes from nginx.
- The access log is JSON, one line per request with the request id, no query
  string and the reset token redacted. It is written to `NGINX_LOG_HOST_DIR`
  (owned by the service account), rotated daily and kept thirty days by the
  host `logrotate` file (`logrotate/manuspectrum-nginx.in`, installed by PP-8;
  nginx reopens its files on `USR1`, no restart). Container stdout stays bounded
  by `json-file` (10 MB x 5). `error.log` is not redacted: upstream-error lines
  carry the raw request line (query string and reset token included). It is
  rotated with the access log (thirty days) and readable by the service account
  and root only; rate-limit lines are logged at `notice`, below the `warn`
  level of `error_log`, so they never reach it.
- Certificates are files under `CERTS_DIR`, in separate directories so that each
  container sees only what it needs: `live/` (`fullchain.pem`, `privkey.pem`, the
  only certificate directory nginx mounts, read-only), `acme-webroot/` (nginx,
  read-only, and certbot), `letsencrypt/` (certbot state, never in nginx) and
  `ca/` (`ca.crt`, `ca.key`, local mode; only `ca.crt` is ever mounted, into web
  and worker). `CERT_MODE` chooses who writes them (details: `certs/README.md`):
  `local` (`make certs-local`: a CA of the rehearsal; web and worker trust it
  through `LOCAL_CA_CERT`), `acme` (certbot and Let's Encrypt: `make cert-init`,
  then `make cert-renew` twice a day from the systemd timer; staging first) and
  `provided` (the operator drops the two files and reloads nginx).
- Concept images (`/files/concepts/...`) are not served: only `/files/<uuid>`
  goes through `FileView`, and nginx never reads `uploadedfiles/` directly. This
  is a decision (pre-existing, issue #71), not an oversight.
- web and worker reach the public name through the `PUBLIC_HOST` network alias
  of nginx, so `PUBLIC_SERVER_ADDRESS` (https, trailing slash) and `PUBLIC_HOST`
  must name the same host; `CANTALOUPE_HTTP_ENDPOINT` is
  `<PUBLIC_SERVER_ADDRESS>iiifserver/`, so canvas and image ids are public.
- After loading a snapshot taken on a development host, run
  `make -C deploy manage ARGS="rewrite_dev_origin --dry-run --from <dev origin> …"`
  (one `--from` per origin), then without `--dry-run`, then
  `make -C deploy manage ARGS="es reindex_database"`. Steps and expected counts:
  `ACCEPTANCE.md`, 4.10.

## Environment variables of the edge

Set in `compose/.env` (`compose/.env.example` documents each one):

| Variable | Role |
| --- | --- |
| `CERT_MODE` | `local`, `acme` or `provided` |
| `CERTS_DIR` | Host directory with `live/` (`fullchain.pem`, `privkey.pem`), `acme-webroot/`, `letsencrypt/` (acme) and `ca/` (`ca.crt`, `ca.key`, local mode) |
| `NGINX_LOG_HOST_DIR` | Host directory of the nginx access and error logs |
| `HSTS_MAX_AGE` | Seconds; 3600 the first week, then 31536000 |
| `LOCAL_CA_CERT` | Local mode only: path of `ca/ca.crt`, trusted by web and worker (never a private key) |
| `HTTP_PORT`, `HTTPS_PORT` | Host ports published by nginx |
| `ACME_EMAIL`, `ACME_SERVER` | certbot contact and directory (staging by default) |
| `DOMAIN_NAMES` | Names nginx answers to and the certificate covers |
| `PUBLIC_SERVER_ADDRESS`, `PUBLIC_HOST` | Public https address (trailing slash) and its host name, the nginx network alias |

## Checks

`deploy-lint.yml` renders the Compose files, runs the tests of `compose/tests/`,
lints the shell scripts and checks `uv.lock`. The smoke checks run in CI
with `compose/smoke.sh`.

Developers run `pre-commit install` once per clone: the `gitleaks` hook scans
every commit for secrets with a pinned image, so it needs Docker
(`SKIP=gitleaks` bypasses it deliberately, see `SECRETS.md`).

## What comes next

- PP-5: `/readyz` and JSON logs.
- PP-8: Ansible writes `.env` and creates the volumes.
- PP-10: image publication and the update command.
