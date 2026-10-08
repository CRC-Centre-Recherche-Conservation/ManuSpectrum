#!/usr/bin/env bash
# Replaces the data of the rehearsal stack, from a dev snapshot made by
# deploy/rehearsal/make-dev-snapshot.sh, or from the aside directory of an
# earlier load. Run on the host of the Compose stack, as the service account
# (APP_UID) or as root (the uploads are then handled as APP_UID through
# setpriv); there is no sudo path, so no credential can expire mid-run:
#   sudo -u <service-account> make -C deploy load-snapshot SNAPSHOT=/path/to/ms-snapshot CONFIRM=yes
#   sudo -u <service-account> make -C deploy load-snapshot RESTORE_BEFORE=<MEDIA_HOST_DIR>/previous-<stamp>-<id> CONFIRM=yes
#
# Two independent guards, both required: .env says DEPLOY_ENVIRONMENT=rehearsal
# (read the way Compose reads it, through `compose config`) and the host has the
# marker file /etc/manuspectrum/rehearsal-host, which host-baseline.sh creates
# in the rehearsal VM only when rehearsal.env sets REHEARSAL_HOST=yes.
# CONFIRM=yes is also required. The database is dropped and recreated.
#
# Steps (the same in both modes): verify the manifest and the archive (load) or
# the aside directory (restore), preflight (load: migrations and Arches version
# against the image; both: running identity, free space), start the data
# services and stop web/worker/beat/cantaloupe, dump the current database into
# a new aside directory, recreate the database from template_postgis and
# restore the dump, flush the Redis caches and the Celery queues, move the
# contents of uploadedfiles/ aside (never deleted) and put the new ones there as
# APP_UID:APP_GID, clear the Cantaloupe cache and recreate Cantaloupe, migrate,
# replace the admin password, refresh the map geometries, reindex
# Elasticsearch, compare the counts with the manifest (load), start the stack,
# smoke test it, check that Cantaloupe sees the new uploads, write
# <aside>/.complete and keep the two newest complete aside directories.
#
# Aside directory: <MEDIA_HOST_DIR>/previous-<stamp>-<id>, holds the previous
# uploads and rehearsal-before.dump (the previous database). Its path is logged
# when it is created. A run that fails leaves it without .complete: it is never
# pruned.
#
# RESTORE_BEFORE=<aside directory> restores <aside>/rehearsal-before.dump and a
# copy of the contents of <aside>/uploadedfiles through the steps above (the
# state it replaces is kept aside in turn); there is no manifest, so the
# migration and count checks are skipped.
#
# Environment: ENV_FILE (default deploy/compose/.env), COMPOSE (the compose
# invocation, exported by the Makefile), CONFIRM, SNAPSHOT, RESTORE_BEFORE,
# MAKE_CMD (default `make -C deploy`). Tests only, and only together with
# MS_TEST_MODE=1: MS_REHEARSAL_MARKER (the marker path).
#
# The data replacement steps live in lib-replace-data.sh (sourced below); this
# file holds the arguments, the two rehearsal guards and the source checks.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$HERE/.." && pwd)"
COMPOSE_DIR="$DEPLOY_DIR/compose"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env}"
SNAPSHOT="${1:-${SNAPSHOT:-}}"
RESTORE_BEFORE="${RESTORE_BEFORE:-}"
CONFIRM="${CONFIRM:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REHEARSAL_MARKER=/etc/manuspectrum/rehearsal-host
if [ "${MS_TEST_MODE:-}" = 1 ]; then REHEARSAL_MARKER="${MS_REHEARSAL_MARKER:-$REHEARSAL_MARKER}"; fi
ASIDE_NAME_RE='^previous-[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9]{6}$'
TOTAL=14
KEEP_ASIDE=2
LOG_NAME=load-snapshot
ASIDE_DUMP=rehearsal-before.dump

# shellcheck source=lib-replace-data.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/lib-replace-data.sh"

if [ -z "${COMPOSE:-}" ]; then
  COMPOSE="docker compose --project-directory $COMPOSE_DIR --env-file $ENV_FILE -f $COMPOSE_DIR/compose.yaml -f $COMPOSE_DIR/compose.prod.yaml"
fi
read -r -a compose_cmd <<<"$COMPOSE"
read -r -a make_cmd <<<"${MAKE_CMD:-make -C $DEPLOY_DIR ENV_FILE=$ENV_FILE}"

[ -f "$ENV_FILE" ] || die "no $ENV_FILE"
[ -f "$REHEARSAL_MARKER" ] \
  || die "this is not a rehearsal host: the rehearsal-host marker $REHEARSAL_MARKER is missing (host-baseline.sh creates it in the rehearsal VM only); this command replaces the database and is refused elsewhere, whatever .env says"

# The values Compose resolves from .env (quotes and comments handled by
# Compose, a variable exported in the shell included).
config_json="$(compose config --format json)" || die "compose config failed"
config_value() { # config_value DEPLOY_ENVIRONMENT|PGDBNAME|PGUSERNAME|USER|MEDIA_HOST_DIR
  printf '%s' "$config_json" | python3 -c '
import json
import sys

services = json.load(sys.stdin)["services"]
web, postgres = services["web"], services["postgres"]
what = sys.argv[1]
if what == "USER":
    value = web.get("user", "")
elif what == "PGUSERNAME":
    value = postgres.get("environment", {}).get("POSTGRES_USER", "")
elif what == "MEDIA_HOST_DIR":
    value = next((v["source"] for v in web.get("volumes", []) if v.get("target") == "/srv/media"), "")
else:
    value = web.get("environment", {}).get(what, "")
print("" if value is None else value)
' "$1"
}

[ "$(config_value DEPLOY_ENVIRONMENT)" = rehearsal ] \
  || die "DEPLOY_ENVIRONMENT is not 'rehearsal' in $ENV_FILE: this command replaces the database and is refused elsewhere"
[ "$CONFIRM" = yes ] || die "this replaces the database of the stack; run again with CONFIRM=yes"

if [ -n "$RESTORE_BEFORE" ]; then
  MODE=restore
  [ -z "$SNAPSHOT" ] || die "give either SNAPSHOT or RESTORE_BEFORE, not both"
else
  MODE=load
  [ -n "$SNAPSHOT" ] || die "give the snapshot directory (SNAPSHOT=/path) or an aside directory to restore (RESTORE_BEFORE=/path)"
  for f in db.dump media.tar manifest.json; do
    [ -f "$SNAPSHOT/$f" ] || die "$SNAPSHOT/$f is missing"
  done
fi

PGDBNAME="$(config_value PGDBNAME)"
PGUSERNAME="$(config_value PGUSERNAME)"
app_user="$(config_value USER)"
APP_UID="${app_user%%:*}"
APP_GID="${app_user#*:}"
MEDIA_HOST_DIR="$(config_value MEDIA_HOST_DIR)"
[[ "$PGDBNAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "PGDBNAME '$PGDBNAME' is not a plain identifier"
if ! [[ "$APP_UID" =~ ^[1-9][0-9]*$ && "$APP_GID" =~ ^[1-9][0-9]*$ ]]; then
  die "APP_UID and APP_GID must be numeric and not 0 (got '$APP_UID' and '$APP_GID'): the uploads are handled as that account, never as root"
fi
if [ -z "$PGUSERNAME" ] || [ ! -d "$MEDIA_HOST_DIR" ]; then
  die "PGUSERNAME and an existing MEDIA_HOST_DIR are required in $ENV_FILE"
fi


tmp_files=()
cleanup() { if [ "${#tmp_files[@]}" -gt 0 ]; then rm -f "${tmp_files[@]}"; fi; }
trap cleanup EXIT
facts="$(mktemp)"
restore_log="$(mktemp)"
tmp_files+=("$facts" "$restore_log")

uploads="$MEDIA_HOST_DIR/uploadedfiles"
DB_DUMP="$SNAPSHOT/db.dump"
RESTORE_UPLOADS=""

# ---------------------------------------------------------------- step 1, 2
verify_source() {
  if [ "$MODE" = load ]; then
    step 1 "verifying the manifest checksums"
    local f expected actual
    for f in db.dump media.tar; do
      expected="$(manifest_value "files/$f/sha256")"
      actual="$(sha256sum "$SNAPSHOT/$f" | cut -d' ' -f1)"
      [ "$actual" = "$expected" ] || die "sha256 mismatch for $f (manifest $expected, file $actual): copy the snapshot again"
    done
    log "checksums match"

    step 2 "checking the media archive: only uploadedfiles/, no parent path, no link"
    local bad links
    bad="$(tar -tf "$SNAPSHOT/media.tar" | grep -Ev '^uploadedfiles(/|$)' || true)"
    [ -z "$bad" ] || die "media.tar holds paths outside uploadedfiles/: $(head -n 3 <<<"$bad")"
    if tar -tf "$SNAPSHOT/media.tar" | grep -Eq '(^|/)\.\.(/|$)'; then die "media.tar holds a path with a '..' segment"; fi
    # `tar -tv` starts each line with the member type: l symlink, h hard link, b/c/p devices and pipes.
    links="$(tar -tvf "$SNAPSHOT/media.tar" | grep -E '^[lhbcp]' || true)"
    [ -z "$links" ] || die "media.tar holds links or special files (uploads never do): $(head -n 3 <<<"$links")"
  else
    step 1 "checking the aside directory $RESTORE_BEFORE"
    local real parent
    real="$(realpath -- "$RESTORE_BEFORE" 2>/dev/null)" || die "$RESTORE_BEFORE does not exist"
    parent="$(dirname "$real")"
    if ! [[ "$(basename "$real")" =~ $ASIDE_NAME_RE ]] || [ "$parent" != "$(realpath -- "$MEDIA_HOST_DIR")" ]; then
      die "$RESTORE_BEFORE is not an aside directory of this stack (expected $MEDIA_HOST_DIR/previous-<stamp>-<id>)"
    fi
    [ -f "$real/$ASIDE_DUMP" ] || die "$real/$ASIDE_DUMP is missing: nothing to restore"
    DB_DUMP="$real/$ASIDE_DUMP"
    if [ -d "$real/uploadedfiles" ]; then RESTORE_UPLOADS="$real/uploadedfiles"; fi

    step 2 "no media archive in restore mode: the uploads come from $real/uploadedfiles"
    [ -n "$RESTORE_UPLOADS" ] || log "no uploadedfiles/ in $real: the uploads will be empty"
  fi
}


verify_source
preflight
stop_services
dump_current
restore_database
flush_redis
swap_media
rebuild_derived_state
compare_counts
finish
if [ "$MODE" = load ]; then log "done: the snapshot is loaded"; else log "done: $RESTORE_BEFORE is restored"; fi
