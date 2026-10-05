#!/usr/bin/env bash
# Replaces the data of the rehearsal stack with a dev snapshot made by
# deploy/rehearsal/make-dev-snapshot.sh. Run on the host of the Compose stack:
#   make -C deploy load-snapshot SNAPSHOT=/path/to/ms-snapshot CONFIRM=yes
#
# Two independent guards, both required: .env says DEPLOY_ENVIRONMENT=rehearsal
# (read the way Compose reads it, through `compose config`) and the host has the
# marker file /etc/manuspectrum/rehearsal-host, which only
# deploy/rehearsal/host-baseline.sh creates, in the rehearsal VM. CONFIRM=yes is
# also required. The database is dropped and recreated.
#
# Steps: verify the manifest and the archive, preflight (migrations and Arches
# version against the image, sudo to APP_UID, free space), start the data
# services and stop web/worker/beat/cantaloupe, dump the current database into
# the aside directory, recreate the database from template_postgis and restore
# the dump, flush the Redis caches and the Celery queues, move the contents of
# uploadedfiles/ aside (never deleted) and extract the new ones as
# APP_UID:APP_GID, clear the Cantaloupe cache and recreate Cantaloupe, migrate,
# replace the admin password, refresh the map geometries, reindex
# Elasticsearch, compare the counts with the manifest, start the stack, smoke
# test it, check that Cantaloupe sees the new uploads, keep the last two aside
# directories.
#
# Undo a load (the previous database is in <aside>/rehearsal-before.dump):
#   compose exec -T postgres pg_restore --clean --if-exists --no-owner \
#     -U <PGUSERNAME> -d <PGDBNAME> < <aside>/rehearsal-before.dump
# and move the contents of <aside>/uploadedfiles back into uploadedfiles/.
#
# Environment: ENV_FILE (default deploy/compose/.env), COMPOSE (the compose
# invocation, exported by the Makefile), CONFIRM, MAKE_CMD (default
# `make -C deploy`), MS_REHEARSAL_MARKER (the marker path; for tests only).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$HERE/.." && pwd)"
COMPOSE_DIR="$DEPLOY_DIR/compose"
ENV_FILE="${ENV_FILE:-$COMPOSE_DIR/.env}"
SNAPSHOT="${1:-${SNAPSHOT:-}}"
CONFIRM="${CONFIRM:-}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REHEARSAL_MARKER="${MS_REHEARSAL_MARKER:-/etc/manuspectrum/rehearsal-host}"
TOTAL=14
KEEP_ASIDE=2

log() { echo "load-snapshot: $*" >&2; }
die() { log "FAIL: $*"; exit 1; }
step() { log "step $1/$TOTAL: $2"; }

if [ -z "${COMPOSE:-}" ]; then
  COMPOSE="docker compose --project-directory $COMPOSE_DIR --env-file $ENV_FILE -f $COMPOSE_DIR/compose.yaml -f $COMPOSE_DIR/compose.prod.yaml"
fi
read -r -a compose_cmd <<<"$COMPOSE"
read -r -a make_cmd <<<"${MAKE_CMD:-make -C $DEPLOY_DIR ENV_FILE=$ENV_FILE}"
compose() { "${compose_cmd[@]}" "$@"; }

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
[ -n "$SNAPSHOT" ] || die "give the snapshot directory: SNAPSHOT=/path"
for f in db.dump media.tar manifest.json; do
  [ -f "$SNAPSHOT/$f" ] || die "$SNAPSHOT/$f is missing"
done

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

as_app() {
  if [ "$(id -u)" = "$APP_UID" ]; then "$@"; else sudo -n -u "#$APP_UID" -g "#$APP_GID" "$@"; fi
}

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

step 1 "verifying the manifest checksums"
for f in db.dump media.tar; do
  expected="$(manifest_value "files/$f/sha256")"
  actual="$(sha256sum "$SNAPSHOT/$f" | cut -d' ' -f1)"
  [ "$actual" = "$expected" ] || die "sha256 mismatch for $f (manifest $expected, file $actual): copy the snapshot again"
done
log "checksums match"

step 2 "checking the media archive: only uploadedfiles/, no parent path, no link"
bad="$(tar -tf "$SNAPSHOT/media.tar" | grep -Ev '^uploadedfiles(/|$)' || true)"
[ -z "$bad" ] || die "media.tar holds paths outside uploadedfiles/: $(head -n 3 <<<"$bad")"
if tar -tf "$SNAPSHOT/media.tar" | grep -Eq '(^|/)\.\.(/|$)'; then die "media.tar holds a path with a '..' segment"; fi
# `tar -tv` starts each line with the member type: l symlink, h hard link, b/c/p devices and pipes.
links="$(tar -tvf "$SNAPSHOT/media.tar" | grep -E '^[lhbcp]' || true)"
[ -z "$links" ] || die "media.tar holds links or special files (uploads never do): $(head -n 3 <<<"$links")"

step 3 "preflight: migrations and Arches version of the image, sudo, free space"
tmp_files=()
cleanup() { if [ "${#tmp_files[@]}" -gt 0 ]; then rm -f "${tmp_files[@]}"; fi; }
trap cleanup EXIT
facts="$(mktemp)"
restore_log="$(mktemp)"
tmp_files+=("$facts" "$restore_log")
image_script='
import django

django.setup()
from importlib.metadata import version
from django.db.migrations.loader import MigrationLoader

loader = MigrationLoader(None, ignore_no_migrations=True)
print("ARCHES", version("arches"))
for app, name in sorted(loader.disk_migrations):
    print("MIG", app, name)
for app, name in sorted(loader.graph.leaf_nodes()):
    print("LEAF", app, name)
'
compose run --rm --no-deps -T web python -c "$image_script" | grep -E '^(ARCHES|MIG|LEAF) ' >"$facts" || true
[ -s "$facts" ] || die "could not read the migrations of the image: run 'compose run --rm --no-deps web python -c \"import django\"' to see why"
errors=0
while IFS= read -r line; do
  case "$line" in
    ERROR:*) log "FAIL: ${line#ERROR: }"; errors=1 ;;
    WARNING:*) log "$line" ;;
  esac
done < <(python3 - "$SNAPSHOT/manifest.json" "$facts" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
migrations, leaves, arches = set(), {}, ""
for line in open(sys.argv[2], encoding="utf-8"):
    kind, *rest = line.split()
    if kind == "ARCHES":
        arches = rest[0]
    elif kind == "MIG":
        migrations.add(tuple(rest))
    else:
        leaves.setdefault(rest[0], []).append(rest[1])
snapshot = manifest.get("migrations", {})
for app, name in sorted(snapshot.items()):
    if (app, name) not in migrations:
        print(f"ERROR: the snapshot holds migration {app}.{name}, unknown to the image (the image is older than the development database, or the migration was amended)")
    elif name not in leaves.get(app, []):
        print(f"WARNING: the image has newer migrations for {app} (snapshot at {name}, image at {', '.join(leaves.get(app, []))}): migrate will apply them")
for app in sorted(set(leaves) - set(snapshot)):
    print(f"WARNING: the image has migrations for {app} that the snapshot never applied: migrate will apply them")
major_minor = lambda v: ".".join(v.split(".")[:2])
snapshot_arches = manifest.get("arches_version", "")
if snapshot_arches and arches and major_minor(snapshot_arches) != major_minor(arches):
    print(f"WARNING: Arches {snapshot_arches} in the snapshot, {arches} in the image")
PY
)
[ "$errors" = 0 ] || die "the snapshot does not fit the image; nothing was changed"

if [ "$(id -u)" != "$APP_UID" ] && ! sudo -n -u "#$APP_UID" -g "#$APP_GID" true 2>/dev/null; then
  die "cannot run commands as uid $APP_UID without a password (sudo -n -u '#$APP_UID' -g '#$APP_GID' true failed): run 'sudo -v' first or log in as the service account"
fi

avail_kb() { df -Pk "$1" 2>/dev/null | awk 'NR == 2 {print $4}'; }
dump_bytes="$(stat -c %s "$SNAPSHOT/db.dump")"
tar_bytes="$(stat -c %s "$SNAPSHOT/media.tar")"
# media.tar extracted (with a margin) plus the dump of the current database kept aside.
need_media_kb=$(((tar_bytes * 11 / 10 + dump_bytes) / 1024 + 1))
have_media_kb="$(avail_kb "$MEDIA_HOST_DIR")"
if [ -z "$have_media_kb" ] || [ "$have_media_kb" -lt "$need_media_kb" ]; then
  die "not enough free space under $MEDIA_HOST_DIR: ${have_media_kb:-unknown} KiB free, $need_media_kb KiB needed (media.tar x 1.1 + a dump of the current database)"
fi
docker_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
need_db_kb=$((dump_bytes * 4 / 1024 + 1))
have_db_kb=""
[ -z "$docker_root" ] || have_db_kb="$(avail_kb "$docker_root")"
if [ -z "$have_db_kb" ]; then
  log "WARNING: could not read the free space of the Docker data root (${docker_root:-unknown}); the restored database needs about $need_db_kb KiB"
elif [ "$have_db_kb" -lt "$need_db_kb" ]; then
  die "not enough free space under the Docker data root $docker_root: $have_db_kb KiB free, about $need_db_kb KiB needed to restore db.dump"
fi
log "preflight: ok"

step 4 "starting the data services (postgres, elasticsearch, redis) and stopping web, worker, beat, cantaloupe"
compose up -d --wait postgres elasticsearch redis-broker redis-cache
compose stop web worker beat cantaloupe

psql_admin() { compose exec -T postgres psql -U "$PGUSERNAME" -v ON_ERROR_STOP=1 -Atq "$@"; }

# The aside directory holds what the load replaces: the previous uploads and a
# dump of the previous database. Created on first use, never deleted by this
# command except by the keep-last-two rule at the end.
aside=""
ensure_aside() {
  [ -z "$aside" ] || return 0
  aside="$(as_app mktemp -d "$MEDIA_HOST_DIR/previous-$STAMP-XXXXXX")"
  as_app chmod 0750 "$aside"
}

step 5 "dumping the current database $PGDBNAME aside, so that a failed load can be undone"
if [ "$(psql_admin -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$PGDBNAME'")" = 1 ]; then
  ensure_aside
  compose exec -T postgres pg_dump -Fc --no-owner --no-privileges -U "$PGUSERNAME" -d "$PGDBNAME" \
    | as_app tee "$aside/rehearsal-before.dump" >/dev/null
  as_app chmod 0600 "$aside/rehearsal-before.dump"
  log "previous database kept in $aside/rehearsal-before.dump"
else
  log "no database $PGDBNAME yet: nothing to dump"
fi

step 6 "recreating database $PGDBNAME from template_postgis and restoring db.dump"
psql_admin -d postgres -c "DROP DATABASE IF EXISTS \"$PGDBNAME\" WITH (FORCE)"
psql_admin -d postgres -c "CREATE DATABASE \"$PGDBNAME\" TEMPLATE template_postgis"
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

step 7 "flushing the Redis caches and the Celery queues (user and resource ids now name other rows)"
# redis-cache holds only derived data (default cache, Arches user_permission,
# Explorer bundles): FLUSHALL. redis-broker: db 0 is the Celery queue (queued
# tasks name old resource ids) and db 3 the IIIF sign-ins, which a rehearsal
# does not keep; both are flushed with FLUSHDB, so no worker container is needed
# and the queue keys are not guessed. Other databases, the smoke markers of db 5
# among them, are left alone.
compose exec -T redis-cache redis-cli FLUSHALL
compose exec -T redis-broker redis-cli -n 0 FLUSHDB
compose exec -T redis-broker redis-cli -n 3 FLUSHDB

step 8 "moving the previous uploads aside, extracting media.tar into $MEDIA_HOST_DIR, resetting Cantaloupe"
# uploadedfiles/ itself is a bind-mount source (Cantaloupe's /imageroot): only
# its contents move, so the directory keeps its inode.
uploads="$MEDIA_HOST_DIR/uploadedfiles"
if [ -d "$uploads" ] && [ -n "$(as_app find "$uploads" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
  ensure_aside
  as_app mkdir -p -m 0750 "$aside/uploadedfiles"
  as_app find "$uploads" -mindepth 1 -maxdepth 1 -exec mv -t "$aside/uploadedfiles" {} +
  log "previous uploads kept in $aside/uploadedfiles"
fi
as_app mkdir -p -m 0750 "$uploads"
as_app tar -C "$MEDIA_HOST_DIR" --no-same-owner --no-same-permissions -xf "$SNAPSHOT/media.tar"
as_app find "$uploads" -type d -exec chmod 0750 {} +
as_app find "$uploads" -type f -exec chmod 0640 {} +
# Cantaloupe's derivative cache (30 days) would keep tiles for an identifier
# that now names other content; its admin endpoint is disabled, so the volume
# is emptied through a one-off container, then the service is recreated.
compose run --rm --no-deps -T --entrypoint sh cantaloupe -c 'find /var/cache/cantaloupe -mindepth 1 -delete'
compose up -d --force-recreate cantaloupe

step 9 "migrating"
compose run --rm --no-deps -T web manage migrate --noinput

step 10 "replacing the admin password from the admin_password secret"
"${make_cmd[@]}" admin-password

step 11 "refreshing the map geometries"
psql_admin -d "$PGDBNAME" -c "SELECT refresh_geojson_geometries();"

step 12 "reindexing Elasticsearch"
compose run --rm --no-deps -T web manage es reindex_database

step 13 "comparing the counts with the manifest"
for table in resource_instances tiles; do
  expected="$(manifest_value "counts/$table")"
  actual="$(psql_admin -d "$PGDBNAME" -c "SELECT count(*) FROM $table")"
  if [ "$actual" = "$expected" ]; then
    log "$table: $actual (equal to the manifest)"
  else
    log "WARNING: $table: $actual in the database, $expected in the manifest (migrations may have changed the count)"
  fi
done

step 14 "starting the stack, running the smoke checks, checking Cantaloupe, pruning the aside directories"
"${make_cmd[@]}" up
# A file created now, after the swap, that Cantaloupe must see: a bind mount
# that still points at the moved directory would not show it.
sentinel=".ms-load-check-$STAMP"
as_app touch "$uploads/$sentinel"
seen=0
compose exec -T cantaloupe test -e "/imageroot/$sentinel" || seen=1
as_app rm -f "$uploads/$sentinel"
[ "$seen" = 0 ] || die "Cantaloupe does not see the new uploads (/imageroot): its bind mount is stale"
log "Cantaloupe sees the new uploads"
"${make_cmd[@]}" smoke

# Only the last KEEP_ASIDE aside directories stay (newest first by mtime).
mapfile -t asides < <(as_app find "$MEDIA_HOST_DIR" -mindepth 1 -maxdepth 1 -type d -name 'previous-*' -printf '%T@ %f\n' | sort -rn | cut -d' ' -f2-)
for ((i = KEEP_ASIDE; i < ${#asides[@]}; i++)); do
  if [[ "${asides[i]}" =~ ^previous-[0-9]{8}T[0-9]{6}Z-[A-Za-z0-9]{6}$ ]]; then
    as_app rm -rf -- "$MEDIA_HOST_DIR/${asides[i]}"
    log "removed ${asides[i]} (only the last $KEEP_ASIDE aside directories are kept)"
  fi
done
if [ -n "$aside" ]; then log "kept: $aside ($(as_app du -sh "$aside" | cut -f1)); delete it by hand when no longer needed"; fi
log "done: the snapshot is loaded"
