#!/usr/bin/env bash
# Data replacement steps shared by the scripts that swap the database and the
# uploads of the stack (load-snapshot.sh, restore.sh). Sourced, never executed;
# `set -euo pipefail` is the caller's.
#
# Provides: log, die, step, compose, as_app, manifest_value, psql_admin, then
# the steps in the order the caller runs them: preflight (check_identity,
# check_migrations, check_space), stop_services, dump_current,
# restore_database, flush_redis, swap_media, rebuild_derived_state,
# compare_counts, finish (prune_asides).
#
# Inputs set by the caller before calling any function:
#   LOG_NAME        log prefix
#   TOTAL           number of steps announced by `step`
#   STAMP           UTC stamp naming the aside directory
#   MODE            load | restore | move
#                   load: db.dump, media.tar and manifest.json in SNAPSHOT
#                   (rehearsal snapshot); restore: the aside directory of an
#                   earlier run, no manifest; move: db.dump and manifest.json
#                   in SNAPSHOT, the uploads staged in RESTORE_UPLOADS on the
#                   same filesystem as uploadedfiles/ and moved, not copied
#   DB_DUMP         the dump to restore
#   ASIDE_DUMP      file name of the dump of the replaced database, kept in the
#                   aside directory
#   ASIDE_NAME_RE   regex of an aside directory name
#   KEEP_ASIDE      number of complete aside directories kept
#   PGDBNAME, PGUSERNAME, APP_UID, APP_GID, MEDIA_HOST_DIR
#   SNAPSHOT        directory of the snapshot (manifest.json, media.tar), or empty
#   RESTORE_UPLOADS directory the uploads come from (restore: copied; move:
#                   moved out of it); empty = no uploads
#   RUN_HINT        optional: the command line shown when the identity is wrong
#                   (default: the load-snapshot one)
#   UNDO_COMMAND    optional: the command that undoes the run, `{aside}` standing
#                   for the aside directory (default: the load-snapshot one)
#   uploads         $MEDIA_HOST_DIR/uploadedfiles
#   facts, restore_log   writable scratch files, removed by the caller
#   compose_cmd, make_cmd   arrays: the Compose and Make invocations
# State kept here: aside (the aside directory, empty until first needed).
# shellcheck disable=SC2154  # the inputs above are assigned by the sourcing script

log() { echo "$LOG_NAME: $*" >&2; }
die() { log "FAIL: $*"; exit 1; }
step() { log "step $1/$TOTAL: $2"; }

compose() { "${compose_cmd[@]}" "$@"; }

# Runs a command as APP_UID:APP_GID. The preflight accepts only APP_UID itself
# or root, so there is no password prompt and no cached credential to expire.
as_app() {
  if [ "$(id -u)" = "$APP_UID" ]; then "$@"; else setpriv --reuid "$APP_UID" --regid "$APP_GID" --clear-groups "$@"; fi
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

# Whether SNAPSHOT/manifest.json describes the data being restored.
has_manifest() { [ "$MODE" != restore ]; }

psql_admin() { compose exec -T postgres psql -U "$PGUSERNAME" -v ON_ERROR_STOP=1 -Atq "$@"; }

# ------------------------------------------------------------------- step 3
check_migrations() {
  has_manifest || { log "restore mode: no manifest, migration check skipped (migrate runs later)"; return 0; }
  local image_script='
import django

django.setup()
from importlib.metadata import version
from django.apps import apps
from django.db.migrations.loader import MigrationLoader

loader = MigrationLoader(None, ignore_no_migrations=True)
print("ARCHES", version("arches"))
for config in apps.get_app_configs():
    print("APP", config.label)
for app, name in sorted(loader.disk_migrations):
    print("MIG", app, name)
for app, name in sorted(loader.graph.leaf_nodes()):
    print("LEAF", app, name)
'
  compose run --rm --no-deps -T web python -c "$image_script" | grep -E '^(ARCHES|APP|MIG|LEAF) ' >"$facts" || true
  [ -s "$facts" ] || die "could not read the migrations of the image: run 'compose run --rm --no-deps web python -c \"import django\"' to see why"
  local errors=0 line
  while IFS= read -r line; do
    case "$line" in
      ERROR:*) log "FAIL: ${line#ERROR: }"; errors=1 ;;
      WARNING:*) log "$line" ;;
    esac
  done < <(python3 - "$SNAPSHOT/manifest.json" "$facts" <<'PY'
import json
import sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
migrations, leaves, installed, arches = set(), {}, set(), ""
for line in open(sys.argv[2], encoding="utf-8"):
    kind, *rest = line.split()
    if kind == "ARCHES":
        arches = rest[0]
    elif kind == "APP":
        installed.add(rest[0])
    elif kind == "MIG":
        migrations.add(tuple(rest))
    else:
        leaves.setdefault(rest[0], []).append(rest[1])
snapshot = manifest.get("migrations", {})
not_installed = set()
for app, name in sorted(snapshot.items()):
    if (app, name) in migrations:
        if name not in leaves.get(app, []):
            print(f"WARNING: the image has newer migrations for {app} (snapshot at {name}, image at {', '.join(leaves.get(app, []))}): migrate will apply them")
    elif installed and app not in installed:
        not_installed.add(app)
    else:
        print(f"ERROR: the snapshot holds migration {app}.{name}, unknown to the image (the image is older than the development database, or the migration was amended)")
if not_installed:
    print(f"WARNING: the snapshot holds migrations of apps the image does not install ({', '.join(sorted(not_installed))}): their tables are inert and stay in the restored database")
for app in sorted(set(leaves) - set(snapshot)):
    print(f"WARNING: the image has migrations for {app} that the snapshot never applied: migrate will apply them")
major_minor = lambda v: ".".join(v.split(".")[:2])
snapshot_arches = manifest.get("arches_version", "")
if snapshot_arches and arches and major_minor(snapshot_arches) != major_minor(arches):
    print(f"WARNING: Arches {snapshot_arches} in the snapshot, {arches} in the image")
PY
)
  [ "$errors" = 0 ] || die "the snapshot does not fit the image; nothing was changed"
}

check_identity() {
  [ "$(id -u)" = "$APP_UID" ] && return 0
  if [ "$(id -u)" = 0 ] && command -v setpriv >/dev/null 2>&1; then return 0; fi
  die "run as the service account (uid $APP_UID), or as root with setpriv installed; sudo from another account is not supported (its timestamp can expire after the database is dropped): sudo -u '#$APP_UID' ${RUN_HINT:-make -C deploy load-snapshot ...}"
}

avail_kb() { df -Pk "$1" 2>/dev/null | awk 'NR == 2 {print $4}'; }
check_space() {
  local dump_bytes media_kb need_media_kb have_media_kb docker_root need_db_kb have_db_kb
  dump_bytes="$(stat -c %s "$DB_DUMP")"
  if [ "$MODE" = load ]; then
    media_kb=$(($(stat -c %s "$SNAPSHOT/media.tar") * 11 / 10 / 1024 + 1))
  elif [ -n "$RESTORE_UPLOADS" ]; then
    media_kb=$(($(as_app du -sk "$RESTORE_UPLOADS" | cut -f1) * 11 / 10 + 1))
  else
    media_kb=0
  fi
  # the new uploads (with a margin) plus the dump of the current database kept aside.
  need_media_kb=$((media_kb + dump_bytes / 1024 + 1))
  have_media_kb="$(avail_kb "$MEDIA_HOST_DIR")"
  if [ -z "$have_media_kb" ] || [ "$have_media_kb" -lt "$need_media_kb" ]; then
    die "not enough free space under $MEDIA_HOST_DIR: ${have_media_kb:-unknown} KiB free, $need_media_kb KiB needed (the new uploads x 1.1 + a dump of the current database)"
  fi
  docker_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
  need_db_kb=$((dump_bytes * 4 / 1024 + 1))
  have_db_kb=""
  [ -z "$docker_root" ] || have_db_kb="$(avail_kb "$docker_root")"
  if [ -z "$have_db_kb" ]; then
    log "WARNING: could not read the free space of the Docker data root (${docker_root:-unknown}); the restored database needs about $need_db_kb KiB"
  elif [ "$have_db_kb" -lt "$need_db_kb" ]; then
    die "not enough free space under the Docker data root $docker_root: $have_db_kb KiB free, about $need_db_kb KiB needed to restore the dump"
  fi
}

preflight() {
  step 3 "preflight: running identity, migrations and Arches version of the image, free space"
  check_identity
  check_migrations
  check_space
  log "preflight: ok"
}

# ---------------------------------------------------------------- step 4, 5
# The aside directory holds what the run replaces: the previous uploads and a
# dump of the previous database. Created on first use, never deleted by this
# command except by the keep-two-complete rule at the end.
aside=""
ensure_aside() {
  [ -z "$aside" ] || return 0
  aside="$(as_app mktemp -d "$MEDIA_HOST_DIR/previous-$STAMP-XXXXXX")"
  as_app chmod 0750 "$aside"
  log "aside directory created: $aside (what this run replaces is moved there, nothing is deleted)"
}

stop_services() {
  step 4 "starting the data services (postgres, elasticsearch, redis) and stopping web, worker, beat, cantaloupe"
  compose up -d --wait postgres elasticsearch redis-broker redis-cache
  compose stop web worker beat cantaloupe
}

dump_current() {
  step 5 "dumping the current database $PGDBNAME aside, so that a failed run can be undone"
  if [ "$(psql_admin -d postgres -c "SELECT 1 FROM pg_database WHERE datname = '$PGDBNAME'")" = 1 ]; then
    ensure_aside
    compose exec -T postgres pg_dump -Fc --no-owner --no-privileges -U "$PGUSERNAME" -d "$PGDBNAME" \
      | as_app tee "$aside/$ASIDE_DUMP" >/dev/null
    as_app chmod 0600 "$aside/$ASIDE_DUMP"
    log "previous database kept in $aside/$ASIDE_DUMP"
  else
    log "no database $PGDBNAME yet: nothing to dump"
  fi
}

# ------------------------------------------------------------------- step 6
restore_database() {
  step 6 "recreating database $PGDBNAME from template_postgis and restoring $(basename "$DB_DUMP")"
  restore_dump "$PGDBNAME" "$DB_DUMP"
}

# Recreates DBNAME from template_postgis and restores DUMPFILE into it.
restore_dump() { # restore_dump DBNAME DUMPFILE
  local dbname="$1" dumpfile="$2"
  psql_admin -d postgres -c "DROP DATABASE IF EXISTS \"$dbname\" WITH (FORCE)"
  psql_admin -d postgres -c "CREATE DATABASE \"$dbname\" TEMPLATE template_postgis"
  local restore_status=0
  compose exec -T postgres pg_restore --no-owner --no-privileges -U "$PGUSERNAME" -d "$dbname" \
    <"$dumpfile" 2>"$restore_log" || restore_status=$?
  # Only the messages a template_postgis database is known to raise are skipped:
  # the public schema and the five template extensions already exist, and their
  # COMMENT ON EXTENSION needs ownership.
  local ext_names='(postgis|uuid-ossp|unaccent|btree_gist|plpgsql)'
  local harmless="^pg_restore: error: could not execute query: ERROR:  (schema \"public\" already exists|extension \"$ext_names\" already exists|must be owner of extension $ext_names)\$"
  local errors fatal skipped
  errors="$(grep '^pg_restore: error:' "$restore_log" | grep -v 'errors ignored on restore' || true)"
  fatal="$(grep -Ev "$harmless" <<<"$errors" | grep -v '^$' || true)"
  skipped="$(grep -E "$harmless" <<<"$errors" || true)"
  if [ -n "$skipped" ]; then
    log "pg_restore: skipped $(wc -l <<<"$skipped") known harmless error(s):"
    sort <<<"${skipped//pg_restore: error: could not execute query: ERROR:  /  - }" | uniq -c >&2
  fi
  if [ -n "$fatal" ]; then
    head -n 10 <<<"$fatal" >&2
    die "pg_restore failed; the database $dbname is incomplete"
  fi
  if [ "$restore_status" -ne 0 ] && [ -z "$errors" ]; then
    tail -n 10 "$restore_log" >&2
    die "pg_restore exited with $restore_status"
  fi
  if [ -n "$skipped" ]; then log "only known harmless template errors: continuing"; fi
}

# ------------------------------------------------------------------- step 7
flush_redis() {
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
}

# ------------------------------------------------------------------- step 8
swap_media() {
  step 8 "moving the previous uploads aside, putting the new uploads into $MEDIA_HOST_DIR, resetting Cantaloupe"
  # uploadedfiles/ itself is a bind-mount source (Cantaloupe's /imageroot): only
  # its contents move, so the directory keeps its inode.
  if [ -d "$uploads" ] && [ -n "$(as_app find "$uploads" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    ensure_aside
    as_app mkdir -p -m 0750 "$aside/uploadedfiles"
    as_app find "$uploads" -mindepth 1 -maxdepth 1 -exec mv -t "$aside/uploadedfiles" {} +
    log "previous uploads kept in $aside/uploadedfiles"
  fi
  as_app mkdir -p -m 0750 "$uploads"
  if [ "$MODE" = load ]; then
    as_app tar -C "$MEDIA_HOST_DIR" --no-same-owner --no-same-permissions -xf "$SNAPSHOT/media.tar"
  elif [ -n "$RESTORE_UPLOADS" ]; then
    if [ "$MODE" = move ]; then
      as_app find "$RESTORE_UPLOADS" -mindepth 1 -maxdepth 1 -exec mv -t "$uploads" {} +
    else
      as_app cp -a --no-preserve=ownership "$RESTORE_UPLOADS/." "$uploads/"
    fi
  fi
  as_app find "$uploads" -type d -exec chmod 0750 {} +
  as_app find "$uploads" -type f -exec chmod 0640 {} +
  # Cantaloupe's derivative cache (30 days) would keep tiles for an identifier
  # that now names other content; its admin endpoint is disabled, so the volume
  # is emptied through a one-off container, then the service is recreated.
  compose run --rm --no-deps -T --entrypoint sh cantaloupe -c 'find /var/cache/cantaloupe -mindepth 1 -delete'
  compose up -d --force-recreate cantaloupe
}

# ------------------------------------------------------------- steps 9 to 13
rebuild_derived_state() {
  step 9 "migrating"
  compose run --rm --no-deps -T web manage migrate --noinput

  step 10 "replacing the admin password from the admin_password secret"
  "${make_cmd[@]}" admin-password

  step 11 "refreshing the map geometries"
  psql_admin -d "$PGDBNAME" -c "SELECT refresh_geojson_geometries();"

  step 12 "reindexing Elasticsearch"
  compose run --rm --no-deps -T web manage es reindex_database
}

compare_counts() {
  step 13 "comparing the counts with the manifest"
  has_manifest || { log "restore mode: no manifest, counts not compared"; return 0; }
  local table expected actual
  for table in resource_instances tiles; do
    expected="$(manifest_value "counts/$table")"
    actual="$(psql_admin -d "$PGDBNAME" -c "SELECT count(*) FROM $table")"
    if [ "$actual" = "$expected" ]; then
      log "$table: $actual (equal to the manifest)"
    else
      log "WARNING: $table: $actual in the database, $expected in the manifest (migrations may have changed the count)"
    fi
  done
}

# ------------------------------------------------------------------ step 14
prune_asides() {
  # Newest first by name (the stamp is UTC). Only complete directories count
  # and only they are removed; an incomplete one is a failed run's, kept.
  local name complete=() incomplete=() all=() i
  mapfile -t complete < <(as_app find "$MEDIA_HOST_DIR" -mindepth 2 -maxdepth 2 -type f -name .complete -printf '%P\n' \
    | sed 's,/\.complete$,,' | { grep -E "$ASIDE_NAME_RE" || true; } | sort -r)
  mapfile -t all < <(as_app find "$MEDIA_HOST_DIR" -mindepth 1 -maxdepth 1 -type d -name 'previous-*' -printf '%f\n' \
    | { grep -E "$ASIDE_NAME_RE" || true; } | sort -r)
  for name in "${all[@]}"; do
    [[ " ${complete[*]} " == *" $name "* ]] || incomplete+=("$name")
  done
  for ((i = 0; i < ${#complete[@]}; i++)); do
    if [ "$i" -lt "$KEEP_ASIDE" ]; then
      log "kept ${complete[i]} (complete)"
    else
      as_app rm -rf -- "${MEDIA_HOST_DIR:?}/${complete[i]}"
      log "removed ${complete[i]} (only the $KEEP_ASIDE newest complete aside directories are kept)"
    fi
  done
  for name in "${incomplete[@]}"; do
    log "kept $name (incomplete: a run that did not finish; never pruned, delete it by hand)"
  done
}

finish() {
  step 14 "starting the stack, running the smoke checks, checking Cantaloupe, pruning the aside directories"
  "${make_cmd[@]}" up
  # A file created now, after the swap, that Cantaloupe must see: a bind mount
  # that still points at the moved directory would not show it.
  local sentinel=".ms-load-check-$STAMP" seen=0
  as_app touch "$uploads/$sentinel"
  compose exec -T cantaloupe test -e "/imageroot/$sentinel" || seen=1
  as_app rm -f "$uploads/$sentinel"
  [ "$seen" = 0 ] || die "Cantaloupe does not see the new uploads (/imageroot): its bind mount is stale"
  log "Cantaloupe sees the new uploads"
  "${make_cmd[@]}" smoke

  if [ -n "$aside" ]; then as_app touch "$aside/.complete"; fi
  prune_asides
  if [ -n "$aside" ]; then
    local undo="${UNDO_COMMAND:-make -C deploy load-snapshot RESTORE_BEFORE={aside} CONFIRM=yes}"
    log "this run's aside: $aside ($(as_app du -sh "$aside" | cut -f1)); to undo this run: ${undo//\{aside\}/$aside}"
  fi
}
