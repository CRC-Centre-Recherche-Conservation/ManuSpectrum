#!/usr/bin/env bash
# Creates, or brings up to date, the PostgreSQL role the monitoring uses, and
# the pg_stat_statements extension it reads. Run once per host after the stack
# is up (and again after rotating pg_monitor_password):
#   make -C deploy monitoring-init
#
# The role `ms_monitor` is a login role with a connection limit of 3 and the
# built-in `pg_monitor` membership only: no superuser, no database creation,
# no write on the application data. Its password is the content of
# SECRETS_DIR/pg_monitor_password, sent to psql on stdin; it is never an
# argument, and an error message that quotes the statement is redacted before
# it is printed. The session turns statement logging off, and
# pg_stat_statements.track_utility off, before the password statements, so the
# server log and the statistics views never hold the value.
#
# The extension is created in the `postgres` maintenance database, where
# postgres_exporter connects: the application database, template_postgis, the
# dumps and the restores are untouched. The final query proves that
# shared_preload_libraries carries pg_stat_statements (compose.prod.yaml).
#
# Idempotent: a second run changes nothing but sets the same password again.
#
# Environment: SECRETS_DIR (absolute; the Makefile passes it), COMPOSE (the
# Compose invocation, exported by the Makefile), ENV_FILE (default
# deploy/compose/.env), POSTGRES_WAIT (seconds to wait for a healthy postgres;
# default 120).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$HERE/.." && pwd)"
COMPOSE_DIR="$DEPLOY_DIR/compose"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env}"
LOG_NAME=monitoring-init
TOTAL=3
POSTGRES_WAIT="${POSTGRES_WAIT:-120}"
MONITOR_ROLE=ms_monitor

# shellcheck source=lib-replace-data.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/lib-replace-data.sh"
# shellcheck source=lib-backup.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/lib-backup.sh"

if [ -z "${COMPOSE:-}" ]; then
  COMPOSE="docker compose --project-directory $COMPOSE_DIR --env-file $ENV_FILE -f $COMPOSE_DIR/compose.yaml -f $COMPOSE_DIR/compose.prod.yaml"
fi
read -r -a compose_cmd <<<"$COMPOSE"

case "${1:-}" in
  "") ;;
  -h | --help) sed -n '2,/^set -euo/p' "$0" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
  *) usage_die "usage: monitoring-init.sh (no argument; see --help)" ;;
esac

secrets_dir="${SECRETS_DIR:-}"
[[ "$secrets_dir" == /* ]] || usage_die "SECRETS_DIR must be an absolute path (got '$secrets_dir')"
secret_file="$secrets_dir/pg_monitor_password"

step 1 "reading the password of $MONITOR_ROLE"
[ -f "$secret_file" ] || die "$secret_file is missing: run make -C deploy secrets"
password="$(cat "$secret_file"; printf x)"
password="${password%x}"
# The value is sent unquoted through `\set`: plain characters only (what
# `make secrets` generates), at least the 32 of secrets-check.
[[ "$password" =~ ^[A-Za-z0-9+/=_.-]{32,}$ ]] \
  || die "pg_monitor_password must be 32 or more characters of A-Z a-z 0-9 + / = _ . - (make -C deploy secrets-check)"

step 2 "waiting for postgres"
wait_for_postgres "$POSTGRES_WAIT"

step 3 "creating or updating $MONITOR_ROLE and pg_stat_statements"
run_sql() {
  printf '%s\n' "\\set pw $password"
  cat <<SQL
SET client_min_messages = warning;
SET log_statement = 'none';
SET log_min_duration_statement = -1;
SET log_min_error_statement = panic;
SET pg_stat_statements.track_utility = off;
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$MONITOR_ROLE') AS role_is_new \\gset
\\if :role_is_new
CREATE ROLE $MONITOR_ROLE LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 3 PASSWORD :'pw';
\\echo created $MONITOR_ROLE
\\else
ALTER ROLE $MONITOR_ROLE LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 3 PASSWORD :'pw';
\\echo updated $MONITOR_ROLE
\\endif
\\unset pw
GRANT pg_monitor TO $MONITOR_ROLE;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
\\o /dev/null
SELECT count(*) FROM pg_stat_statements;
\\o
\\echo pg_stat_statements ready
SQL
}

rc=0
# The variable is expanded by the shell inside the container.
# shellcheck disable=SC2016
out="$(run_sql | compose exec -T postgres sh -c 'psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres' 2>&1)" || rc=$?
out="${out//"$password"/***}"
if [ "$rc" -ne 0 ]; then
  log "$out"
  case "$out" in
    *shared_preload_libraries*) log "pg_stat_statements is not preloaded: recreate postgres with compose.prod.yaml (make -C deploy down up)" ;;
  esac
  die "could not set up $MONITOR_ROLE (psql exit $rc)"
fi
log "$out"
log "done: after a rotation, recreate postgres-exporter so that it reads the new password (docker compose up -d --force-recreate postgres-exporter)"
