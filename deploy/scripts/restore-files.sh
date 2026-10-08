#!/usr/bin/env bash
# Pulls single files out of a backup into a separate directory: a deleted
# upload, a secret, the env file, a media directory restore.sh does not bring
# back. Nothing of the running stack is written: the operator looks at the
# result and copies what they need (secret-set.sh for a secret).
#   make -C deploy restore-files RESTIC_SNAPSHOT=latest INCLUDE=/backup/secrets/pg_password TARGET=/path/to/empty-dir
#
# INCLUDE is a path inside the snapshot, under /backup/ (/backup/db,
# /backup/media/uploadedfiles/<path>, /backup/secrets/<name>), without a `..`
# segment. TARGET is an absolute path that does not exist or is an empty
# directory, and is neither inside nor equal to MEDIA_HOST_DIR/uploadedfiles,
# SECRETS_DIR, RESTIC_REPOSITORY_DIR or BACKUP_DUMP_DIR (the whole directory,
# staging directories and lock included). restic restores the path under
# TARGET/backup/... with --verify. TARGET is created 0700.
#
# Environment: ENV_FILE (default deploy/compose/.env), COMPOSE (exported by the
# Makefile), RESTIC_SNAPSHOT (default latest), INCLUDE, TARGET.
# Exit status: 0 done; 1 refused or failed.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$HERE/.." && pwd)"
COMPOSE_DIR="$DEPLOY_DIR/compose"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env}"
RESTIC_SNAPSHOT="${RESTIC_SNAPSHOT:-latest}"
INCLUDE="${INCLUDE:-}"
TARGET="${TARGET:-}"
LOG_NAME=restore-files
RUN_HINT='make -C deploy restore-files RESTIC_SNAPSHOT=<id> INCLUDE=/backup/... TARGET=/path'

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

[[ "$RESTIC_SNAPSHOT" =~ ^(latest|[0-9a-f]{8,64})$ ]] || die "RESTIC_SNAPSHOT '$RESTIC_SNAPSHOT' is not 'latest' or a restic snapshot id"
[[ "$INCLUDE" == /backup/* ]] || die "INCLUDE must be a path under /backup/ (for example /backup/secrets/pg_password)"
if [[ "$INCLUDE" =~ (^|/)\.\.(/|$) ]] || [[ "$INCLUDE" =~ [[:space:]] ]]; then
  die "INCLUDE must not hold a '..' segment or a space"
fi
[[ "$TARGET" == /* ]] || die "TARGET must be an absolute path"
if [[ "$TARGET" =~ (^|/)\.\.(/|$) ]]; then die "TARGET must not hold a '..' segment"; fi
[ -f "$ENV_FILE" ] || die "no $ENV_FILE"

backup_config
require_backup_dirs
check_identity

# A path is inside PROTECTED when, once normalised, it equals it or starts with it.
target_real="$(realpath -m -- "$TARGET")"
for protected in "$MEDIA_HOST_DIR/uploadedfiles" "$SECRETS_DIR" "$RESTIC_REPOSITORY_DIR" "$BACKUP_DUMP_DIR"; do
  protected_real="$(realpath -m -- "$protected")"
  case "$target_real/" in
    "$protected_real"/*) die "TARGET $TARGET is inside $protected: it would overwrite live data; use a separate directory" ;;
  esac
done
if [ -e "$TARGET" ]; then
  [ -d "$TARGET" ] || die "TARGET $TARGET exists and is not a directory"
  [ -z "$(find "$TARGET" -mindepth 1 -print -quit)" ] || die "TARGET $TARGET is not empty"
fi

umask 077
as_app install -d -m 0700 "$TARGET"
log "restoring $INCLUDE of snapshot $RESTIC_SNAPSHOT into $TARGET"
restic_run_with "$TARGET:/restore" restore "$RESTIC_SNAPSHOT" --target /restore --include "$INCLUDE" --verify \
  || die "restic restore failed (the target $TARGET may hold a partial result)"
log "restored under $TARGET:"
find "$TARGET" -mindepth 1 -type f | sort | head -n 50
count="$(find "$TARGET" -type f | wc -l)"
if [ "$count" -gt 50 ]; then log "... $count files in all"; fi
[ "$count" -gt 0 ] || die "nothing matched $INCLUDE in snapshot $RESTIC_SNAPSHOT"
log "done: copy what you need from $TARGET; the running stack was not touched"
