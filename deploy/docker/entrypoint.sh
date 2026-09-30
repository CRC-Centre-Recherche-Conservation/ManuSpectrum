#!/usr/bin/env bash
# Entrypoint of the ManuSpectrum image. Commands:
#   web            wait for PostgreSQL and Elasticsearch, migrate, publish the
#                  static files, then run gunicorn
#   worker         wait for PostgreSQL and Elasticsearch, then the Celery worker
#   beat           wait for PostgreSQL, then Celery beat
#   init           first installation: Arches setup_db, refused when the
#                  database already exists (setup_db drops and recreates it)
#   manage ARGS    manage.py ARGS; setup_db only through `init`
#   anything else  executed as given
# Docker applies no depends_on order when it restarts containers after a host
# reboot, so every command waits for what it needs itself (WAIT_SECONDS).
set -euo pipefail

WAIT_SECONDS="${WAIT_SECONDS:-300}"

log() { echo "entrypoint: $*" >&2; }

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

# Exit status 0: PGDBNAME exists; 1: it does not; 2: the question could not be answered.
database_exists() {
  python - <<'PY'
import os
import sys

try:
    import psycopg2

    path = os.environ.get("PGPASSWORD_FILE")
    if path:
        with open(path, encoding="utf-8") as handle:
            password = handle.read().strip()
    else:
        password = os.environ.get("PGPASSWORD", "")
    connection = psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        user=os.environ["PGUSERNAME"],
        password=password,
        dbname="postgres",
        connect_timeout=5,
    )
    with connection, connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (os.environ["PGDBNAME"],))
        found = cursor.fetchone() is not None
    connection.close()
except Exception as error:
    print(f"entrypoint: {type(error).__name__}: {error}", file=sys.stderr)
    sys.exit(2)
sys.exit(0 if found else 1)
PY
}

command="${1:-web}"
case "$command" in
  web)
    wait_for PostgreSQL postgres_ready
    wait_for Elasticsearch elasticsearch_ready
    database_exists && status=0 || status=$?
    if [ "$status" -ne 0 ]; then
      log "database ${PGDBNAME} is missing or unreachable: run the init command once (make -C deploy init)"
      exit 1
    fi
    python manage.py migrate --noinput
    publish-static /app/static /srv/static
    exec gunicorn --config /app/gunicorn.conf.py
    ;;
  worker)
    wait_for PostgreSQL postgres_ready
    wait_for Elasticsearch elasticsearch_ready
    exec celery -A manuspectrum.celery worker \
      --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
      --concurrency="${CELERY_CONCURRENCY:-2}" \
      --prefetch-multiplier=1 \
      --max-tasks-per-child=200
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
    wait_for PostgreSQL postgres_ready
    wait_for Elasticsearch elasticsearch_ready
    database_exists && status=0 || status=$?
    case "$status" in
      0) log "refusing: database ${PGDBNAME} exists and setup_db would drop it"; exit 1 ;;
      1) ;;
      *) log "refusing: cannot tell whether database ${PGDBNAME} exists"; exit 1 ;;
    esac
    exec python manage.py setup_db --force
    ;;
  manage)
    shift
    if [ "${1:-}" = setup_db ]; then
      log "refusing: setup_db drops the database; use the init command"
      exit 1
    fi
    exec python manage.py "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
