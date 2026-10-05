#!/usr/bin/env bash
# Replaces the data of the rehearsal stack with a dev snapshot made by
# deploy/rehearsal/make-dev-snapshot.sh. Run on the host of the Compose stack:
#   make -C deploy load-snapshot SNAPSHOT=/path/to/ms-snapshot CONFIRM=yes
#
# Refused unless .env says DEPLOY_ENVIRONMENT=rehearsal and CONFIRM=yes is
# given: the database is dropped and recreated. Steps: verify the manifest,
# stop web/worker/beat, recreate the database from template_postgis and
# restore the dump, move the previous uploads aside (never deleted) and extract
# the new ones as APP_UID:APP_GID, migrate, replace the admin password, refresh
# the map geometries, reindex Elasticsearch, compare the counts with the
# manifest, start the stack and smoke-test it.
#
# Environment: ENV_FILE (default deploy/compose/.env), COMPOSE (the compose
# invocation, exported by the Makefile), CONFIRM, MAKE_CMD (default
# `make -C deploy`).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$HERE/.." && pwd)"
COMPOSE_DIR="$DEPLOY_DIR/compose"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env}"
SNAPSHOT="${1:-${SNAPSHOT:-}}"
CONFIRM="${CONFIRM:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

log() { echo "load-snapshot: $*" >&2; }
die() { log "FAIL: $*"; exit 1; }
env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; }

if [ -z "${COMPOSE:-}" ]; then
  COMPOSE="docker compose --project-directory $COMPOSE_DIR --env-file $ENV_FILE -f $COMPOSE_DIR/compose.yaml -f $COMPOSE_DIR/compose.prod.yaml"
fi
read -r -a compose_cmd <<<"$COMPOSE"
read -r -a make_cmd <<<"${MAKE_CMD:-make -C $DEPLOY_DIR ENV_FILE=$ENV_FILE}"
compose() { "${compose_cmd[@]}" "$@"; }

[ -f "$ENV_FILE" ] || die "no $ENV_FILE"
[ "$(env_value DEPLOY_ENVIRONMENT)" = rehearsal ] \
  || die "DEPLOY_ENVIRONMENT is not 'rehearsal' in $ENV_FILE: this command replaces the database and is refused elsewhere"
[ "$CONFIRM" = yes ] || die "this replaces the database of the stack; run again with CONFIRM=yes"
[ -n "$SNAPSHOT" ] || die "give the snapshot directory: SNAPSHOT=/path"
for f in db.dump media.tar manifest.json; do
  [ -f "$SNAPSHOT/$f" ] || die "$SNAPSHOT/$f is missing"
done

PGDBNAME="$(env_value PGDBNAME)"
PGUSERNAME="$(env_value PGUSERNAME)"
APP_UID="$(env_value APP_UID)"
APP_GID="$(env_value APP_GID)"
MEDIA_HOST_DIR="$(env_value MEDIA_HOST_DIR)"
[[ "$PGDBNAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "PGDBNAME '$PGDBNAME' is not a plain identifier"
if [ -z "$PGUSERNAME" ] || [ -z "$APP_UID" ] || [ -z "$APP_GID" ] || [ ! -d "$MEDIA_HOST_DIR" ]; then
  die "PGUSERNAME, APP_UID, APP_GID and an existing MEDIA_HOST_DIR are required in $ENV_FILE"
fi

manifest_value() { # manifest_value SLASH/SEPARATED/PATH
  python3 - "$SNAPSHOT/manifest.json" "$1" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
for part in sys.argv[2].split("/"):
    value = value[part]
print(value)
PY
}

log "step 1/12: verifying the manifest checksums"
for f in db.dump media.tar; do
  expected="$(manifest_value "files/$f/sha256")"
  actual="$(sha256sum "$SNAPSHOT/$f" | cut -d' ' -f1)"
  [ "$actual" = "$expected" ] || die "sha256 mismatch for $f (manifest $expected, file $actual): copy the snapshot again"
done
log "checksums match"

log "step 2/12: checking the media archive holds only uploadedfiles/"
bad="$(tar -tf "$SNAPSHOT/media.tar" | grep -Ev '^uploadedfiles(/|$)' || true)"
[ -z "$bad" ] || die "media.tar holds paths outside uploadedfiles/: $(head -n 3 <<<"$bad")"
if tar -tf "$SNAPSHOT/media.tar" | grep -q '\.\.'; then die "media.tar holds a path with '..'"; fi

log "step 3/12: starting the data services (postgres, elasticsearch, redis) and stopping web, worker, beat"
compose up -d --wait postgres elasticsearch redis-broker redis-cache
compose stop web worker beat

psql_admin() { compose exec -T postgres psql -U "$PGUSERNAME" -v ON_ERROR_STOP=1 -Atq "$@"; }

log "step 4/12: recreating database $PGDBNAME from template_postgis"
psql_admin -d postgres -c "DROP DATABASE IF EXISTS \"$PGDBNAME\" WITH (FORCE)"
psql_admin -d postgres -c "CREATE DATABASE \"$PGDBNAME\" TEMPLATE template_postgis"

log "step 5/12: restoring db.dump"
restore_log="$(mktemp)"
trap 'rm -f "$restore_log"' EXIT
restore_status=0
compose exec -T postgres pg_restore --no-owner --no-privileges -U "$PGUSERNAME" -d "$PGDBNAME" \
  <"$SNAPSHOT/db.dump" 2>"$restore_log" || restore_status=$?
# Only the messages a template_postgis database is known to raise are skipped:
# the public schema and the five template extensions already exist, and their
# COMMENT ON EXTENSION needs ownership.
ext_names='(postgis|uuid-ossp|unaccent|btree_gist|plpgsql)'
harmless="^pg_restore: error: could not execute query: ERROR:  (schema \"public\" already exists|extension \"$ext_names\" already exists|must be owner of extension $ext_names)\$"
errors="$(grep '^pg_restore: error:' "$restore_log" | grep -v 'errors ignored on restore' || true)"
fatal="$(grep -Ev "$harmless" <<<"$errors" | grep -v '^$' || true)"
skipped="$(grep -E "$harmless" <<<"$errors" || true)"
if [ -n "$skipped" ]; then
  log "pg_restore: skipped $(wc -l <<<"$skipped") known harmless error(s):"
  sort <<<"${skipped//pg_restore: error: could not execute query: ERROR:  /  - }" | uniq -c >&2
fi
if [ -n "$fatal" ]; then
  head -n 10 <<<"$fatal" >&2
  die "pg_restore failed; the database $PGDBNAME is incomplete"
fi
if [ "$restore_status" -ne 0 ] && [ -z "$errors" ]; then
  tail -n 10 "$restore_log" >&2
  die "pg_restore exited with $restore_status"
fi
if [ -n "$skipped" ]; then log "only known harmless template errors: continuing"; fi

log "step 6/12: moving the previous uploads aside and extracting media.tar into $MEDIA_HOST_DIR"
as_app() {
  if [ "$(id -u)" = "$APP_UID" ]; then "$@"; else sudo -u "#$APP_UID" -g "#$APP_GID" "$@"; fi
}
if [ -e "$MEDIA_HOST_DIR/uploadedfiles" ] && [ -n "$(ls -A "$MEDIA_HOST_DIR/uploadedfiles" 2>/dev/null)" ]; then
  aside="$(as_app mktemp -d "$MEDIA_HOST_DIR/previous-$STAMP-XXXXXX")"
  as_app chmod 0750 "$aside"
  as_app mv "$MEDIA_HOST_DIR/uploadedfiles" "$aside/uploadedfiles"
  log "previous uploads kept in $aside (delete it by hand when no longer needed)"
fi
as_app mkdir -p -m 0750 "$MEDIA_HOST_DIR/uploadedfiles"
as_app tar -C "$MEDIA_HOST_DIR" --no-same-owner --no-same-permissions -xf "$SNAPSHOT/media.tar"
as_app find "$MEDIA_HOST_DIR/uploadedfiles" -type d -exec chmod 0750 {} +
as_app find "$MEDIA_HOST_DIR/uploadedfiles" -type f -exec chmod 0640 {} +

log "step 7/12: migrating"
compose run --rm --no-deps -T web manage migrate --noinput

log "step 8/12: replacing the admin password from the admin_password secret"
"${make_cmd[@]}" admin-password

log "step 9/12: refreshing the map geometries"
psql_admin -d "$PGDBNAME" -c "SELECT refresh_geojson_geometries();"

log "step 10/12: reindexing Elasticsearch"
compose run --rm --no-deps -T web manage es reindex_database

log "step 11/12: comparing the counts with the manifest"
for table in resource_instances tiles; do
  expected="$(manifest_value "counts/$table")"
  actual="$(psql_admin -d "$PGDBNAME" -c "SELECT count(*) FROM $table")"
  if [ "$actual" = "$expected" ]; then
    log "$table: $actual (equal to the manifest)"
  else
    log "WARNING: $table: $actual in the database, $expected in the manifest (migrations may have changed the count)"
  fi
done

log "step 12/12: starting the stack and running the smoke checks"
"${make_cmd[@]}" up
"${make_cmd[@]}" smoke
log "done: the snapshot is loaded"
