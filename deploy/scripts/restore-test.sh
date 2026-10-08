#!/usr/bin/env bash
# Restore test: proves that the latest backup (or RESTIC_SNAPSHOT) can be restored.
# Run on the host of the Compose stack as the service account (APP_UID), weekly
# by the systemd timer or by hand:
#   make -C deploy restore-test [RESTIC_SNAPSHOT=<restic snapshot id>]
#
# Restores /backup/db of the restic snapshot into a staging directory under
# BACKUP_DUMP_DIR, checks the files against the checksums of manifest.json,
# restores db.dump into the scratch database <PGDBNAME>_restoretest (created
# from template_postgis, with the pg_restore filter of lib-replace-data.sh),
# requires the row count of every table of the manifest to equal the count in
# the scratch database (extension tables included: a restore into
# template_postgis gives spatial_ref_sys the same rows), then runs
# `restic check --read-data-subset=10%`. The live database, the uploads and
# the services are never touched; every SQL statement names the scratch
# database, which is dropped on exit whatever happened.
#
# Exit status: 0 when every table matches and the repository check passes; 1 on
# any failed step (a Compose configuration found wrong included); 2 on a wrong
# invocation or METRICS_TEXTFILE_DIR found before any command ran. Every run that got past the configuration writes
# manuspectrum_restore_test.prom (failed 0|1, attempt time) in
# METRICS_TEXTFILE_DIR; a success also writes manuspectrum_restore_test_success.prom.
#
# Environment: as backup.sh (ENV_FILE, COMPOSE, METRICS_TEXTFILE_DIR,
# BACKUP_LOCK_WAIT, POSTGRES_WAIT); the lock is shared with backup.sh and
# restore.sh. A run stopped by SIGTERM, SIGINT or SIGHUP exits 143, 130 or 129
# and records a failure like any other.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$HERE/.." && pwd)"
COMPOSE_DIR="$DEPLOY_DIR/compose"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_NAME=restore-test
TOTAL=7
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

SNAPSHOT_ID=latest
case "${1:-}" in
  "") ;;
  --snapshot) SNAPSHOT_ID="${2:-}" ;;
  *) usage_die "usage: restore-test.sh [--snapshot ID]" ;;
esac
[[ "$SNAPSHOT_ID" =~ ^(latest|[0-9a-f]{8,64})$ ]] || usage_die "snapshot '$SNAPSHOT_ID' is not 'latest' or a restic snapshot id"

metrics_dir="${METRICS_TEXTFILE_DIR:-}"
[[ "$metrics_dir" == /* ]] || usage_die "METRICS_TEXTFILE_DIR must be an absolute path (got '$metrics_dir'); set it in $ENV_FILE"
[ -d "$metrics_dir" ] || usage_die "METRICS_TEXTFILE_DIR $metrics_dir does not exist"
[ -f "$ENV_FILE" ] || usage_die "no $ENV_FILE"

staging=""
scratch=""
scratch_created=0
restore_log="$(mktemp)"
on_exit() {
  local rc=$? now
  trap - EXIT
  now="$(date +%s)"
  if [ "$scratch_created" = 1 ]; then
    if ! psql_admin -d postgres -c "DROP DATABASE IF EXISTS \"$scratch\" WITH (FORCE)" >/dev/null; then
      log "WARNING: could not drop the scratch database $scratch: drop it by hand"
      [ "$rc" -ne 0 ] || rc=1
    fi
  fi
  [ -z "$staging" ] || rm -rf "$staging"
  rm -f "$restore_log"
  if [ "$rc" -eq 0 ]; then
    if ! { write_metrics "$metrics_dir/manuspectrum_restore_test_success.prom" \
      manuspectrum_restore_test_last_success_timestamp_seconds "$now" \
      manuspectrum_restore_test_duration_seconds "$SECONDS" \
      && write_metrics "$metrics_dir/manuspectrum_restore_test.prom" \
        manuspectrum_restore_test_last_attempt_timestamp_seconds "$now" manuspectrum_restore_test_failed 0; }; then
      log "WARNING: the metric files could not be written to $metrics_dir"
    fi
  else
    write_metrics "$metrics_dir/manuspectrum_restore_test.prom" \
      manuspectrum_restore_test_last_attempt_timestamp_seconds "$now" manuspectrum_restore_test_failed 1 \
      || log "WARNING: the metric file could not be written to $metrics_dir"
  fi
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
trap 'exit 129' HUP

umask 077

step 1 "configuration, lock and PostgreSQL health"
backup_config
scratch="$(scratch_database_name "$PGDBNAME")" \
  || usage_die "no safe scratch database name for '$PGDBNAME' (it must not end in _restoretest, and <name>_restoretest must fit 63 characters)"
[ -d "$BACKUP_DUMP_DIR" ] || die "BACKUP_DUMP_DIR $BACKUP_DUMP_DIR does not exist: run make backup-init"
take_lock "$BACKUP_LOCK_WAIT"
wait_for_postgres "$POSTGRES_WAIT"

step 2 "restoring the backup files of snapshot $SNAPSHOT_ID into a staging directory"
staging="$BACKUP_DUMP_DIR/.restore-test-$STAMP"
mkdir -m 0700 "$staging"
restic_run_with "$staging:/restore" restore "$SNAPSHOT_ID" --target /restore --include /backup/db --verify \
  || die "restic restore failed"
DUMP_DIR="$staging/backup/db"
for name in db.dump globals.sql manifest.json; do
  [ -s "$DUMP_DIR/$name" ] || die "the snapshot has no $name under /backup/db"
done

step 3 "checking the restored files against the manifest"
verify_backup_files "$DUMP_DIR" || die "the restored files do not match manifest.json"

step 4 "free space for the scratch database"
dump_bytes="$(stat -c %s "$DUMP_DIR/db.dump")"
docker_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
need_kb=$((dump_bytes * 4 / 1024 + 1))
have_kb=""
[ -z "$docker_root" ] || have_kb="$(avail_kb "$docker_root")"
if [ -z "$have_kb" ]; then
  log "WARNING: could not read the free space of the Docker data root (${docker_root:-unknown}); the scratch database needs about $need_kb KiB"
elif [ "$have_kb" -lt "$need_kb" ]; then
  die "not enough free space under the Docker data root $docker_root: $have_kb KiB free, about $need_kb KiB needed"
fi

step 5 "restoring db.dump into the scratch database $scratch"
scratch_created=1
restore_dump "$scratch" "$DUMP_DIR/db.dump"

step 6 "comparing the row count of every table with the manifest"
counts_sql="SELECT json_object_agg(table_name, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text::bigint ORDER BY table_name) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
actual_json="$(printf '%s\n' "$counts_sql" | psql_admin -d "$scratch")" || die "could not count the tables of $scratch"
[ -n "$actual_json" ] || die "the scratch database $scratch has no table"
ACTUAL_JSON="$actual_json" python3 - "$DUMP_DIR/manifest.json" <<'PY' || die "the restored database differs from the manifest"
import json
import os
import sys

expected = json.load(open(sys.argv[1], encoding="utf-8"))["counts"]
actual = json.loads(os.environ["ACTUAL_JSON"])
differences = []
for table in sorted(set(expected) | set(actual)):
    if table not in actual:
        differences.append(f"{table}: expected {expected[table]}, table absent from the restored database")
    elif table not in expected:
        differences.append(f"{table}: not in the manifest, {actual[table]} rows restored")
    elif expected[table] != actual[table]:
        differences.append(f"{table}: expected {expected[table]}, actual {actual[table]}")
if differences:
    print(f"{len(differences)} table(s) differ:", file=sys.stderr)
    for line in differences:
        print(f"  {line}", file=sys.stderr)
    sys.exit(1)
print(f"restore-test: {len(expected)} tables, every count equal to the manifest", file=sys.stderr)
PY

step 7 "reading a 10% subset of the repository data"
restic_run check --read-data-subset=10% || die "restic check failed"
log "done: snapshot $SNAPSHOT_ID restores and every table matches"
