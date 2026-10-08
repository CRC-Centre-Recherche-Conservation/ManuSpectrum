#!/usr/bin/env bash
# Restores the stack from a backup: the database and the uploads of a restic
# snapshot, or the state a previous restore put aside. Run on the host of the
# Compose stack as the service account (APP_UID) or as root (the files are then
# handled as APP_UID through setpriv):
#   make -C deploy restore RESTIC_SNAPSHOT=latest CONFIRM=yes ERASURES_CHECKED=yes
#   make -C deploy restore ASIDE=<MEDIA_HOST_DIR>/previous-<stamp>-<id> CONFIRM=yes ERASURES_CHECKED=yes
#
# Replaces the database and the uploads of the stack. Required, in this order:
# CONFIRM=yes, ERASURES_CHECKED=yes (the erasure requests received since the
# date of the snapshot must be replayed before the site reopens: deploy/BACKUP.md,
# "Personal data"), and exactly one source: RESTIC_SNAPSHOT (a restic snapshot id
# or `latest`) or ASIDE (an aside directory of MEDIA_HOST_DIR holding
# before-restore.dump, the undo of an earlier restore).
#
# SECRETS_DIR and .env are never written, from either source: on the same host
# they are current, on a new host the operator chooses what to bring back
# (restore-files.sh, then secret-set.sh). The other top-level directories of
# the snapshot's media (concepts/, ...) are listed, not restored; restore-files.sh
# pulls them.
#
# Steps: restic restore of /backup/db into a staging directory under
# BACKUP_DUMP_DIR and of /backup/media/uploadedfiles into a staging directory
# under MEDIA_HOST_DIR (same filesystem as uploadedfiles/, so the swap is a
# rename), checksums against manifest.json, preflight (running identity,
# migrations and Arches version of the image against the manifest, free space),
# then the steps of lib-replace-data.sh: start the data services and stop the
# application, dump the current database aside, recreate the database from
# template_postgis and restore the dump, flush Redis, move the previous uploads
# aside and the new ones in, clear and recreate Cantaloupe, migrate, replace the
# admin password, refresh the map geometries, reindex Elasticsearch, compare the
# counts with the manifest (warnings only: restore-test.sh is the strict check),
# start the stack and smoke test it. Nothing is changed before the preflight
# passes; the staging directories are removed on success, and on failure before
# the first change. After a failure later on they are kept and logged.
#
# Aside directory: <MEDIA_HOST_DIR>/previous-<stamp>-<id>, holds the previous
# uploads and before-restore.dump (the previous database); the last log line
# names the command that undoes the run.
#
# Environment: ENV_FILE (default deploy/compose/.env), COMPOSE (the compose
# invocation, exported by the Makefile), MAKE_CMD (default `make -C deploy`),
# RESTIC_SNAPSHOT, ASIDE, CONFIRM, ERASURES_CHECKED. The lock of backup.sh is
# taken without waiting: a backup or a restore test in progress refuses the run.
# Exit status: 0 done; 1 refused or failed; 2 ERASURES_CHECKED missing.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$HERE/.." && pwd)"
COMPOSE_DIR="$DEPLOY_DIR/compose"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env}"
RESTIC_SNAPSHOT="${RESTIC_SNAPSHOT:-}"
ASIDE="${ASIDE:-}"
CONFIRM="${CONFIRM:-}"
ERASURES_CHECKED="${ERASURES_CHECKED:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ASIDE_NAME_RE='^previous-[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9]{6}$'
TOTAL=14
KEEP_ASIDE=2
LOG_NAME=restore
ASIDE_DUMP=before-restore.dump
RUN_HINT='make -C deploy restore RESTIC_SNAPSHOT=<id> CONFIRM=yes ERASURES_CHECKED=yes'
UNDO_COMMAND='make -C deploy restore ASIDE={aside} CONFIRM=yes ERASURES_CHECKED=yes'

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
read -r -a make_cmd <<<"${MAKE_CMD:-make -C $DEPLOY_DIR ENV_FILE=$ENV_FILE}"

[ "$CONFIRM" = yes ] || die "this replaces the database and the uploads of the stack; run again with CONFIRM=yes"
[ "$ERASURES_CHECKED" = yes ] \
  || usage_die "ERASURES_CHECKED=yes is required: the erasure requests received since the date of the backup must be replayed before the site reopens (deploy/BACKUP.md, section \"Personal data\"). Run again with ERASURES_CHECKED=yes once you have the list, and replay it after this restore."
if [ -n "$RESTIC_SNAPSHOT" ] && [ -n "$ASIDE" ]; then die "give either RESTIC_SNAPSHOT or ASIDE, not both"; fi
if [ -z "$RESTIC_SNAPSHOT" ] && [ -z "$ASIDE" ]; then
  die "give a restic snapshot (RESTIC_SNAPSHOT=latest or an id) or an aside directory to restore (ASIDE=<MEDIA_HOST_DIR>/previous-...)"
fi
if [ -n "$RESTIC_SNAPSHOT" ]; then
  [[ "$RESTIC_SNAPSHOT" =~ ^(latest|[0-9a-f]{8,64})$ ]] || die "RESTIC_SNAPSHOT '$RESTIC_SNAPSHOT' is not 'latest' or a restic snapshot id"
fi
[ -f "$ENV_FILE" ] || die "no $ENV_FILE"

backup_config
[ -d "$MEDIA_HOST_DIR" ] || die "MEDIA_HOST_DIR $MEDIA_HOST_DIR does not exist"
[ -d "$BACKUP_DUMP_DIR" ] || die "BACKUP_DUMP_DIR $BACKUP_DUMP_DIR does not exist: run make backup-init"
check_identity
take_lock 0

uploads="$MEDIA_HOST_DIR/uploadedfiles"
DB_DUMP=""
SNAPSHOT=""
RESTORE_UPLOADS=""
db_stage=""
media_stage=""
changed=0
facts="$(mktemp)"
restore_log="$(mktemp)"
on_exit() {
  local rc=$?
  trap - EXIT
  rm -f "$facts" "$restore_log"
  if [ "$rc" -eq 0 ] || [ "$changed" = 0 ]; then
    [ -z "$db_stage" ] || as_app rm -rf -- "$db_stage"
    [ -z "$media_stage" ] || as_app rm -rf -- "$media_stage"
  else
    [ -z "$db_stage$media_stage" ] || log "the staging directories are kept for inspection: $db_stage $media_stage"
    [ -z "$aside" ] || log "the data this run replaced is in $aside"
  fi
  exit "$rc"
}
trap on_exit EXIT
umask 077

# ---------------------------------------------------------------- step 1, 2
fetch_snapshot() {
  step 1 "restoring /backup/db of snapshot $RESTIC_SNAPSHOT from the repository and checking it against the manifest"
  db_stage="$BACKUP_DUMP_DIR/.restore-$STAMP"
  as_app mkdir -m 0700 "$db_stage"
  restic_run_with "$db_stage:/restore" restore "$RESTIC_SNAPSHOT" --target /restore --include /backup/db --verify \
    || die "restic restore of the database failed"
  SNAPSHOT="$db_stage/backup/db"
  local name
  for name in db.dump manifest.json; do
    [ -s "$SNAPSHOT/$name" ] || die "the snapshot has no $name under /backup/db"
  done
  verify_backup_files "$SNAPSHOT" || die "the restored files do not match manifest.json; nothing was changed"
  DB_DUMP="$SNAPSHOT/db.dump"
  log "checksums match (snapshot taken $(manifest_value created_at 2>/dev/null || echo "at an unknown date"))"

  step 2 "restoring the uploads of the snapshot next to uploadedfiles/ (same filesystem), listing what is not restored"
  local media_bytes need_kb have_kb
  media_bytes="$(manifest_value media/bytes)" || die "manifest.json has no media size"
  need_kb=$((media_bytes * 11 / 10 / 1024 + 1))
  have_kb="$(avail_kb "$MEDIA_HOST_DIR")"
  if [ -z "$have_kb" ] || [ "$have_kb" -lt "$need_kb" ]; then
    die "not enough free space under $MEDIA_HOST_DIR: ${have_kb:-unknown} KiB free, $need_kb KiB needed for the staged uploads"
  fi
  media_stage="$MEDIA_HOST_DIR/.restore-$STAMP"
  as_app mkdir -m 0700 "$media_stage"
  restic_run_with "$media_stage:/restore" restore "$RESTIC_SNAPSHOT" --target /restore --include /backup/media/uploadedfiles --verify \
    || die "restic restore of the uploads failed"
  local reference="$uploads"
  [ -d "$reference" ] || reference="$MEDIA_HOST_DIR"
  [ "$(stat -c %d "$media_stage")" = "$(stat -c %d "$reference")" ] \
    || die "the staging directory $media_stage is on another filesystem than $reference: the swap would copy the uploads instead of renaming them"
  if [ -d "$media_stage/backup/media/uploadedfiles" ]; then
    RESTORE_UPLOADS="$media_stage/backup/media/uploadedfiles"
  else
    log "the snapshot holds no uploadedfiles/: the uploads will be empty"
  fi
  local listing others
  listing="$(restic_run ls "$RESTIC_SNAPSHOT" /backup/media)" || die "restic ls failed"
  others="$(grep -E '^/backup/media/[^/]+$' <<<"$listing" | grep -vx '/backup/media/uploadedfiles' | sed 's,^/backup/media/,,' || true)"
  if [ -n "$others" ]; then
    log "not restored by this command (use restore-files, INCLUDE=/backup/media/<name>): $(tr '\n' ' ' <<<"$others")"
  fi
}

verify_aside() {
  step 1 "checking the aside directory $ASIDE"
  local real parent
  real="$(realpath -- "$ASIDE" 2>/dev/null)" || die "$ASIDE does not exist"
  parent="$(dirname "$real")"
  if ! [[ "$(basename "$real")" =~ $ASIDE_NAME_RE ]] || [ "$parent" != "$(realpath -- "$MEDIA_HOST_DIR")" ]; then
    die "$ASIDE is not an aside directory of this stack (expected $MEDIA_HOST_DIR/previous-<stamp>-<id>)"
  fi
  [ -f "$real/$ASIDE_DUMP" ] || die "$real/$ASIDE_DUMP is missing: nothing to restore"
  DB_DUMP="$real/$ASIDE_DUMP"
  if [ -d "$real/uploadedfiles" ]; then RESTORE_UPLOADS="$real/uploadedfiles"; fi

  step 2 "no staging in aside mode: the uploads come from $real/uploadedfiles"
  [ -n "$RESTORE_UPLOADS" ] || log "no uploadedfiles/ in $real: the uploads will be empty"
}

if [ -n "$RESTIC_SNAPSHOT" ]; then
  MODE=move
  fetch_snapshot
else
  MODE=restore
  verify_aside
fi

preflight
changed=1
stop_services
dump_current
restore_database
flush_redis
swap_media
rebuild_derived_state
compare_counts
finish
log "SECRETS_DIR and .env were not touched: bring back a secret or the env file with restore-files if this is a new host"
if [ "$MODE" = move ]; then
  log "done: snapshot $RESTIC_SNAPSHOT is restored. Replay the erasure requests received since $(manifest_value created_at 2>/dev/null || echo "the snapshot date") before reopening the site (deploy/BACKUP.md, \"Personal data\")"
else
  log "done: $ASIDE is restored. Replay the erasure requests received since the restored state was taken before reopening the site (deploy/BACKUP.md, \"Personal data\")"
fi
