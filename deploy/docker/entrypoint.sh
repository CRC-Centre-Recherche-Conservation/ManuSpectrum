#!/usr/bin/env bash
# Entrypoint of the ManuSpectrum image. Commands:
#   web            Django's deployment checks (any warning stops the start),
#                  wait for PostgreSQL and Elasticsearch, migrate, publish the
#                  static files, then run gunicorn
#   worker         wait for PostgreSQL and Elasticsearch, then the Celery worker
#   beat           wait for PostgreSQL, then Celery beat
#   init           deployment checks as for web; first installation: Arches
#                  setup_db, then the admin
#                  password from the admin_password secret; refused when the
#                  database already exists (setup_db drops and recreates it)
#   manage ARGS    manage.py ARGS; the commands that drop the database (setup_db,
#                  packages -db / -o setup) only through `init`
#   anything else  executed as given
# web and worker empty PROMETHEUS_MULTIPROC_DIR before they start; every other
# Python process the entrypoint runs has it unset.
# Docker applies no depends_on order when it restarts containers after a host
# reboot, so every command waits for what it needs itself (WAIT_SECONDS).
set -euo pipefail

WAIT_SECONDS="${WAIT_SECONDS:-300}"

log() { echo "entrypoint: $*" >&2; }

# Empties PROMETHEUS_MULTIPROC_DIR, when set, right before the server starts: files of
# earlier processes (migrate, the probes, a previous run) would be summed with the new
# ones. A directory that is missing or not writable stops the start.
reset_metrics_dir() {
  local dir="${PROMETHEUS_MULTIPROC_DIR:-}"
  [ -n "$dir" ] || return 0
  if [ ! -d "$dir" ] || [ ! -w "$dir" ]; then
    log "PROMETHEUS_MULTIPROC_DIR ($dir) is not a writable directory"
    exit 1
  fi
  find "$dir" -mindepth 1 -delete \
    || log "some files of $dir could not be removed; continuing"
}

# Every Python process that runs before the server is a one-off: it must not write
# metric files into PROMETHEUS_MULTIPROC_DIR (observability/README.md).
oneoff() { env -u PROMETHEUS_MULTIPROC_DIR "$@"; }

# Django's deployment checks, run first by web and init so that a misconfigured
# host fails at once. `--tag security` as in the Arches deployment checks; every
# silenced check is listed with its reason in settings_docker.py.
deploy_checks() {
  oneoff python manage.py check --deploy --tag security --fail-level WARNING \
    || { log "Django's deployment checks failed (above); not starting"; exit 1; }
}

wait_for() { # wait_for NAME COMMAND...
  local name="$1" deadline=$((SECONDS + WAIT_SECONDS)) output
  shift
  until output="$("$@" 2>&1)"; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      log "$name not reachable after ${WAIT_SECONDS}s: ${output:-no output}"
      exit 1
    fi
    sleep 2
  done
  log "$name is up"
}

# -U: the containers run under a uid with no passwd entry, and pg_isready
# without a user name gives up before connecting ("no attempt").
postgres_ready() { pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSERNAME"; }

elasticsearch_ready() {
  local password="${ELASTIC_PASSWORD:-}"
  if [ -n "${ELASTIC_PASSWORD_FILE:-}" ]; then password="$(<"$ELASTIC_PASSWORD_FILE")"; fi
  # The password goes through curl's config on stdin, never on its command line.
  printf 'user = "elastic:%s"\n' "$password" \
    | curl -fsS -K - "http://${ESHOST}:${ESPORT}/_cluster/health?wait_for_status=yellow&timeout=5s"
}

# pg_probe WHAT: exit status 0 when it holds, 1 when it does not, 2 when the
# question could not be answered. WHAT is `database` (PGDBNAME exists) or
# `settings` (the Arches system settings resource instance is in PGDBNAME: a
# database that setup_db did not finish lacks it).
pg_probe() {
  oneoff python - "$1" <<'PY'
import os
import sys

try:
    import psycopg2

    what = sys.argv[1]
    path = os.environ.get("PGPASSWORD_FILE")
    if path:
        with open(path, encoding="utf-8") as handle:
            password = handle.read().strip()
    else:
        password = os.environ.get("PGPASSWORD", "")
    if what == "database":
        dbname = "postgres"
        query = ("SELECT 1 FROM pg_database WHERE datname = %s", (os.environ["PGDBNAME"],))
    else:
        from arches.settings import SYSTEM_SETTINGS_RESOURCE_ID

        dbname = os.environ["PGDBNAME"]
        query = (
            "SELECT 1 FROM resource_instances WHERE resourceinstanceid = %s",
            (SYSTEM_SETTINGS_RESOURCE_ID,),
        )
    connection = psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        user=os.environ["PGUSERNAME"],
        password=password,
        dbname=dbname,
        connect_timeout=5,
    )
    try:
        with connection, connection.cursor() as cursor:
            try:
                cursor.execute(*query)
                found = cursor.fetchone() is not None
            except psycopg2.errors.UndefinedTable:
                found = False
    finally:
        connection.close()
except Exception as error:
    print(f"entrypoint: {type(error).__name__}: {error}", file=sys.stderr)
    sys.exit(2)
sys.exit(0 if found else 1)
PY
}

database_exists() { pg_probe database; }
system_settings_exist() { pg_probe settings; }

# manage_refusal ARGS...: prints the command that drops the database when ARGS
# would run it, through Arches' setup_db or through `packages` (`-db`,
# `--setup_db` or any abbreviation argparse expands to it, `-o setup`), and returns 0; returns 1 otherwise.
manage_refusal() {
  local arg option previous="" packages=0 SETUP_DB_OPTION=--setup_db
  for arg in "$@"; do
    if [ "$arg" = setup_db ]; then
      echo "setup_db"
      return 0
    fi
    [ "$arg" = packages ] && packages=1
    if [ "$packages" = 1 ]; then
      # argparse accepts any unambiguous prefix of --setup_db, with or without =value.
      option="${arg%%=*}"
      if [ "$arg" = -db ] || { [ "${#option}" -ge 5 ] && [[ "$option" == --* ]] \
        && [ "${option}" = "${SETUP_DB_OPTION:0:${#option}}" ]; }; then
        echo "packages $arg"
        return 0
      fi
      case "$arg" in
        -osetup | -o=setup | --op*=setup)
          echo "packages -o setup"
          return 0
          ;;
      esac
      if [ "$arg" = setup ]; then
        case "$previous" in
          -o | --op | --ope | --oper | --opera | --operat | --operati | --operatio | --operation)
            echo "packages -o setup"
            return 0
            ;;
        esac
      fi
    fi
    previous="$arg"
  done
  return 1
}

# Adds the CA of a rehearsal (a non-empty file mounted at CA_CERT_FILE) to the
# trusted bundle: the image's certifi bundle plus that CA, so public trust is
# kept. requests (REQUESTS_CA_BUNDLE) and ssl (SSL_CERT_FILE) read it. An empty
# or missing file, as in production, changes nothing.
trust_local_ca() {
  local ca="${CA_CERT_FILE:-/run/ms-ca/ca.crt}" bundle="${CA_BUNDLE_FILE:-/tmp/ca-bundle.pem}" certifi
  [ -s "$ca" ] || return 0
  certifi="$(oneoff python -c 'import certifi; print(certifi.where())')" || {
    log "cannot locate the certifi bundle; not starting"
    exit 1
  }
  { cat "$certifi"; echo; cat "$ca"; } >"$bundle"
  export REQUESTS_CA_BUNDLE="$bundle" SSL_CERT_FILE="$bundle"
  log "trusting the local CA $ca"
}

command="${1:-web}"
case "$command" in
  web)
    deploy_checks
    wait_for PostgreSQL postgres_ready
    wait_for Elasticsearch elasticsearch_ready
    database_exists && status=0 || status=$?
    if [ "$status" -ne 0 ]; then
      log "database ${PGDBNAME} is missing or unreachable: run the init command once (make -C deploy init)"
      exit 1
    fi
    probe_error="$(system_settings_exist 2>&1)" && status=0 || status=$?
    if [ "$status" -ne 0 ]; then
      if [ "$status" -eq 2 ]; then
        log "cannot tell whether the Arches system settings exist: ${probe_error:-see above}; not starting"
      else
        log "database ${PGDBNAME} has no Arches system settings: the first installation did not finish; drop the database and run make -C deploy init again (deploy/README.md, \"A failed first installation\")"
      fi
      exit 1
    fi
    oneoff python manage.py set_admin_password --check-default && status=0 || status=$?
    if [ "$status" -ne 0 ]; then
      if [ "$status" -eq 3 ]; then
        log "the admin account still has Arches' default password: run make -C deploy admin-password"
      else
        log "cannot tell whether the admin account still has Arches' default password; not starting"
      fi
      exit 1
    fi
    # Migrations run without the timeouts web's requests carry.
    PG_STATEMENT_TIMEOUT_MS=0 PG_IDLE_IN_TRANSACTION_TIMEOUT_MS=0 oneoff python manage.py migrate --noinput
    publish-static /app/static /srv/static
    reset_metrics_dir
    trust_local_ca
    exec gunicorn --config /app/gunicorn.conf.py
    ;;
  worker)
    wait_for PostgreSQL postgres_ready
    wait_for Elasticsearch elasticsearch_ready
    reset_metrics_dir
    trust_local_ca
    exec celery -A manuspectrum.celery worker \
      --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
      --concurrency="${CELERY_CONCURRENCY:-2}" \
      --prefetch-multiplier=1 \
      --max-tasks-per-child=200 \
      --max-memory-per-child="${CELERY_MAX_MEMORY_PER_CHILD:-600000}"
    ;;
  beat)
    wait_for PostgreSQL postgres_ready
    # --pidfile= : no pidfile (read-only root); the schedule lives in the beat volume.
    exec celery -A manuspectrum.celery beat \
      --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
      --schedule=/var/lib/celery/celerybeat-schedule \
      --pidfile=
    ;;
  init)
    if [ "$PGDBNAME" = "$PGUSERNAME" ]; then
      log "refusing: setup_db connects to the database named after PGUSERNAME and cannot drop it; use a PGDBNAME different from PGUSERNAME"
      exit 1
    fi
    deploy_checks
    wait_for PostgreSQL postgres_ready
    wait_for Elasticsearch elasticsearch_ready
    database_exists && status=0 || status=$?
    case "$status" in
      0) log "refusing: database ${PGDBNAME} exists and setup_db would drop it"; exit 1 ;;
      1) ;;
      *) log "refusing: cannot tell whether database ${PGDBNAME} exists"; exit 1 ;;
    esac
    export PG_STATEMENT_TIMEOUT_MS=0 PG_IDLE_IN_TRANSACTION_TIMEOUT_MS=0
    oneoff python manage.py setup_db --force
    # setup_db creates the superuser admin with the publicly known password
    # "admin"; replace it before anything else can start.
    if ! oneoff python manage.py set_admin_password; then
      log "setup_db succeeded but the admin password could not be set: the account still has Arches' default password; fix ${ADMIN_PASSWORD_FILE:-ADMIN_PASSWORD_FILE}, then run: make -C deploy admin-password"
      exit 1
    fi
    log "admin password set from the admin_password secret (deploy/compose/secrets/admin_password on the host); create named accounts next and keep admin for emergencies (deploy/compose/secrets/README.md)"
    ;;
  manage)
    shift
    if refused="$(manage_refusal "$@")"; then
      log "refusing: ${refused} drops and recreates the database; the first installation goes through make -C deploy init"
      exit 1
    fi
    # Management commands (reindex, imports) run without those timeouts.
    export PG_STATEMENT_TIMEOUT_MS=0 PG_IDLE_IN_TRANSACTION_TIMEOUT_MS=0
    trust_local_ca
    exec env -u PROMETHEUS_MULTIPROC_DIR python manage.py "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
