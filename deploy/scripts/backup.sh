#!/usr/bin/env bash
# Nightly and on-demand backup of the stack, and the initialisation of its
# restic repository. Run on the host of the Compose stack as the service
# account (APP_UID):
#   make -C deploy backup [TAG=nightly|manual|pre-update]
#   make -C deploy backup-init        (once per host, idempotent)
#   make -C deploy restic ARGS="snapshots"
#
# Copy A (local disk, BACKUP_DUMP_DIR): latest/ and previous/, each holding
# db.dump (pg_dump -Fc of the whole database), globals.sql (pg_dumpall
# --globals-only --no-role-passwords), manifest.json (counts of every table of
# the public schema taken in the dump's own snapshot, latest migration per app,
# Arches and pg_dump versions, uploads summary, checksums) and env (a copy of
# .env, which holds no secret). Copy B (RESTIC_REPOSITORY_DIR, encrypted): copy
# A latest/, the whole MEDIA_HOST_DIR and SECRETS_DIR, taken by the `restic`
# Compose service.
#
# Not backed up: Elasticsearch (rebuilt by `es reindex_database`), Redis, the
# Cantaloupe cache, static files, the data volume files, the TLS certificates
# (`make cert-init` re-issues them), the nginx logs, and under MEDIA_HOST_DIR
# the aside directories (previous-*), restore staging (.restore-*),
# archestemp/ and export_deliverables/. The first part of the backup is the
# dump, the second the files: a file uploaded in between is an orphan after a
# restore, a file deleted in between comes back.
#
# Steps: 1 configuration, lock and PostgreSQL health; 2 staging directory;
# 3 consistent dump and counts (one REPEATABLE READ transaction exports a
# snapshot, the counts and the migrations are read in it and pg_dump reads the
# same snapshot); 4 globals; 5 verification of the dump; 6 manifest; 7
# rotation; 8 restic backup; 9 (tag nightly only) forget with the retention of
# lib-backup.sh, then check.
#
# Exit status (the contract of the update procedure, which stops on non-zero):
# 0 only when the dump is verified and the restic snapshot is saved; 1 on any
# failed step (a Compose configuration found wrong included); 2 on a wrong
# invocation or METRICS_TEXTFILE_DIR found before any command ran. Every run that got past the configuration writes
# manuspectrum_backup.prom (failed 0|1, attempt time) in METRICS_TEXTFILE_DIR;
# a success also writes manuspectrum_backup_success.prom.
#
# Environment: ENV_FILE (default deploy/compose/.env), COMPOSE (the compose
# invocation, exported by the Makefile), METRICS_TEXTFILE_DIR (absolute,
# existing), BACKUP_LOCK_WAIT (seconds to wait for another backup, restore
# test or restore; default 3600), POSTGRES_WAIT (seconds to wait for postgres to
# be running and healthy before refusing, for a catch-up run at boot; default 600).
#
# A run stopped by SIGTERM, SIGINT or SIGHUP exits 143, 130 or 129 and records
# a failure like any other.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$HERE/.." && pwd)"
COMPOSE_DIR="$DEPLOY_DIR/compose"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_NAME=backup
TOTAL=9
BACKUP_LOCK_WAIT="${BACKUP_LOCK_WAIT:-3600}"
POSTGRES_WAIT="${POSTGRES_WAIT:-600}"

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

mode=backup
TAG=manual
case "${1:-}" in
  "") ;;
  --init) mode=init ;;
  --restic) mode=restic; shift ;;
  --tag) TAG="${2:-}" ;;
  *) usage_die "usage: backup.sh [--tag nightly|manual|pre-update] | --init | --restic ARGS..." ;;
esac
case "$TAG" in nightly | manual | pre-update) ;; *) usage_die "unknown tag '$TAG' (nightly, manual or pre-update)" ;; esac

if [ "$mode" = restic ]; then
  RESTIC_INTERACTIVE=1 restic_run "$@"
  exit $?
fi

metrics_dir="${METRICS_TEXTFILE_DIR:-}"
if [ "$mode" = backup ]; then
  [[ "$metrics_dir" == /* ]] || usage_die "METRICS_TEXTFILE_DIR must be an absolute path (got '$metrics_dir'); set it in $ENV_FILE"
  [ -d "$metrics_dir" ] || usage_die "METRICS_TEXTFILE_DIR $metrics_dir does not exist"
fi

new=""
metrics_ready=0
[ "$mode" != backup ] || metrics_ready=1
on_exit() {
  local rc=$? now
  trap - EXIT
  [ -z "${session_pid:-}" ] || kill "$session_pid" 2>/dev/null || true
  if [ "$mode" = backup ] && [ "$metrics_ready" = 1 ]; then
    now="$(date +%s)"
    [ -z "$new" ] || rm -rf "$new"
    if [ "$rc" -eq 0 ]; then
      if ! { write_metrics "$metrics_dir/manuspectrum_backup_success.prom" \
        manuspectrum_backup_last_success_timestamp_seconds "$now" \
        manuspectrum_backup_duration_seconds "$SECONDS" \
        manuspectrum_backup_dump_bytes "$dump_bytes" \
        && write_metrics "$metrics_dir/manuspectrum_backup.prom" \
          manuspectrum_backup_last_attempt_timestamp_seconds "$now" manuspectrum_backup_failed 0; }; then
        log "WARNING: the metric files could not be written to $metrics_dir"
      fi
    else
      write_metrics "$metrics_dir/manuspectrum_backup.prom" \
        manuspectrum_backup_last_attempt_timestamp_seconds "$now" manuspectrum_backup_failed 1 \
        || log "WARNING: the metric file could not be written to $metrics_dir"
    fi
  fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP
trap : PIPE

[ -f "$ENV_FILE" ] || die "no $ENV_FILE"
umask 077
dump_bytes=0

# ------------------------------------------------------------------ init
if [ "$mode" = init ]; then
  backup_config
  [ -d "$BACKUP_DUMP_DIR" ] || die "BACKUP_DUMP_DIR $BACKUP_DUMP_DIR does not exist: create it (0700) as the service account"
  if ! [ -d "$RESTIC_REPOSITORY_DIR" ] || ! [ -w "$RESTIC_REPOSITORY_DIR" ]; then
    die "RESTIC_REPOSITORY_DIR $RESTIC_REPOSITORY_DIR does not exist or is not writable by $(id -un)"
  fi
  take_lock "$BACKUP_LOCK_WAIT"
  # The restic service binds latest/ (the sources) and tmp/ (its temporary
  # packs) and refuses to create a missing host path.
  install -d -m 0700 "$BACKUP_DUMP_DIR/latest" "$BACKUP_DUMP_DIR/tmp"
  if [ -f "$RESTIC_REPOSITORY_DIR/config" ]; then
    restic_run cat config >/dev/null || die "the repository in $RESTIC_REPOSITORY_DIR does not open: wrong restic_password?"
    log "repository exists and opens"
  else
    restic_run init || die "restic init failed"
    log "repository created"
  fi
  log "the restic password must be in the vault item now (deploy/SECRETS.md): without it no backup can be read"
  exit 0
fi

# ---------------------------------------------------------------- backup
step 1 "configuration, lock and PostgreSQL health"
backup_config
[ -d "$BACKUP_DUMP_DIR" ] || die "BACKUP_DUMP_DIR $BACKUP_DUMP_DIR does not exist: create it (0700) as the service account"
[ -d "$MEDIA_HOST_DIR" ] || die "MEDIA_HOST_DIR $MEDIA_HOST_DIR does not exist"
take_lock "$BACKUP_LOCK_WAIT"
wait_for_postgres "$POSTGRES_WAIT"

step 2 "staging directory"
new="$BACKUP_DUMP_DIR/.new-$STAMP"
mkdir -m 0700 "$new"

# --------------------------------------------------- consistent dump (3)
step 3 "consistent dump and counts"
END_MARK=__MS_END__
psql_ask() { # psql_ask SQL-ON-ONE-LINE: prints the answer, ends at the marker
  printf '%s\n\\echo %s\n' "$1" "$END_MARK" >&"$to_psql" || return 1
  local line out=""
  while IFS= read -r -t 900 -u "$from_psql" line; do
    if [ "$line" = "$END_MARK" ]; then printf '%s' "$out"; return 0; fi
    out+="${out:+$'\n'}$line"
  done
  return 1
}
coproc PSQL { compose exec -T postgres psql -U "$PGUSERNAME" -d "$PGDBNAME" -X -Atq -v ON_ERROR_STOP=1; }
# Bash unsets PSQL and closes its descriptors when the coprocess ends: keep a pid and descriptors of our own.
session_pid=$PSQL_PID
exec {to_psql}>&"${PSQL[1]}" {from_psql}<&"${PSQL[0]}"
psql_ask 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;' >/dev/null || die "could not open the dump transaction"
snapshot_id="$(psql_ask 'SELECT pg_export_snapshot();')" || die "could not export the snapshot"
[[ "$snapshot_id" =~ ^[0-9A-F-]+$ ]] || die "unexpected snapshot id"
counts_json="$(psql_ask "SELECT json_object_agg(table_name, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text::bigint ORDER BY table_name) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';")" \
  || die "could not count the tables"
migrations_json="$(psql_ask "SELECT json_object_agg(app, name) FROM (SELECT DISTINCT ON (app) app, name FROM django_migrations ORDER BY app, id DESC) m;")" \
  || die "could not read the migrations"
if [ -z "$counts_json" ] || [ -z "$migrations_json" ]; then die "empty counts or migrations: is the database initialised?"; fi
compose exec -T postgres pg_dump -Fc --no-owner --no-privileges --snapshot="$snapshot_id" -U "$PGUSERNAME" -d "$PGDBNAME" >"$new/db.dump" \
  || die "pg_dump failed"
psql_ask 'COMMIT;' >/dev/null || die "could not close the dump transaction"
exec {to_psql}>&- {from_psql}<&-
[ -z "${PSQL[1]:-}" ] || eval "exec ${PSQL[1]}>&- ${PSQL[0]}<&-"
wait "$session_pid" || die "the psql session ended with an error"
session_pid=""

step 4 "database roles and settings"
compose exec -T postgres pg_dumpall --globals-only --no-role-passwords -U "$PGUSERNAME" >"$new/globals.sql" \
  || die "pg_dumpall failed"

step 5 "verifying the dump"
[ -s "$new/db.dump" ] || die "db.dump is empty"
[ -s "$new/globals.sql" ] || die "globals.sql is empty"
dump_list="$(compose exec -T postgres pg_restore --list <"$new/db.dump")" || die "pg_restore --list cannot read db.dump"
for table in resource_instances tiles; do
  grep -Eq "TABLE DATA public $table([[:space:]]|\$)" <<<"$dump_list" || die "db.dump has no data entry for public.$table"
done

step 6 "manifest"
arches_version="$(compose run --rm --no-deps -T web python -c 'from importlib.metadata import version; print(version("arches"))' \
  | grep -E '^[0-9]+(\.[0-9A-Za-z+-]+)+$' | tail -n 1 || true)"
[ -n "$arches_version" ] || die "could not read the Arches version of the image"
pg_dump_version="$(compose exec -T postgres pg_dump --version)" || die "could not read the pg_dump version"
media_files=0 media_bytes=0
if [ -d "$MEDIA_HOST_DIR/uploadedfiles" ]; then
  read -r media_files media_bytes < <(as_app find "$MEDIA_HOST_DIR/uploadedfiles" -type f -printf '%s\n' \
    | awk '{ n++; b += $1 } END { printf "%d %d\n", n, b }')
fi
cp "$ENV_FILE" "$new/env"
export COUNTS_JSON="$counts_json" MIGRATIONS_JSON="$migrations_json" ARCHES_VERSION="$arches_version" \
  PG_DUMP_VERSION="$pg_dump_version" IMAGE="$MANUSPECTRUM_IMAGE" TAG MEDIA_FILES="$media_files" MEDIA_BYTES="$media_bytes"
python3 - "$new" <<'PY'
import datetime
import hashlib
import json
import os
import sys

directory = sys.argv[1]
files = {}
for name in ("db.dump", "globals.sql", "env"):
    data = open(os.path.join(directory, name), "rb").read()
    files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
manifest = {
    "kind": "backup",
    "tag": os.environ["TAG"],
    "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "image": os.environ["IMAGE"],
    "arches_version": os.environ["ARCHES_VERSION"],
    "pg_dump_version": os.environ["PG_DUMP_VERSION"],
    "counts": json.loads(os.environ["COUNTS_JSON"]),
    "migrations": json.loads(os.environ["MIGRATIONS_JSON"]),
    "files": files,
    "media": {"files": int(os.environ["MEDIA_FILES"]), "bytes": int(os.environ["MEDIA_BYTES"])},
}
with open(os.path.join(directory, "manifest.json"), "w", encoding="utf-8") as out:
    json.dump(manifest, out, indent=2, sort_keys=True)
PY
chmod 0600 "$new"/*
dump_bytes="$(stat -c %s "$new/db.dump")"

step 7 "rotating the local copies"
rm -rf "$BACKUP_DUMP_DIR/previous"
if [ -f "$BACKUP_DUMP_DIR/latest/manifest.json" ]; then
  mv "$BACKUP_DUMP_DIR/latest" "$BACKUP_DUMP_DIR/previous"
else
  rm -rf "$BACKUP_DUMP_DIR/latest"
fi
mv "$new" "$BACKUP_DUMP_DIR/latest"
new=""

step 8 "saving into the restic repository"
exclude_args=()
for pattern in "${RESTIC_EXCLUDES[@]}"; do exclude_args+=(--exclude "$pattern"); done
restic_run backup --tag "$TAG" "${exclude_args[@]}" /backup || die "restic backup failed (the local copies are good)"

if [ "$TAG" = nightly ]; then
  step 9 "applying the retention and checking the repository"
  restic_run forget --keep-daily "$RETENTION_KEEP_DAILY" --keep-weekly "$RETENTION_KEEP_WEEKLY" \
    --keep-monthly "$RETENTION_KEEP_MONTHLY" --prune || die "restic forget failed"
  restic_run check || die "restic check failed"
else
  step 9 "retention and check skipped (tag $TAG)"
fi
log "done: tag $TAG, dump $dump_bytes bytes"
