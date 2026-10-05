#!/usr/bin/env bash
# deploy/scripts/tests/test_load_snapshot.sh
# Tests of load-snapshot.sh. docker and make are stubs on PATH that record
# their calls in $TMP/calls; nothing real runs. Prints `ok N` / `not ok N`;
# exits non-zero on failure.
# $? after a negated or compound test is the point of every assertion below.
# shellcheck disable=SC2319
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOAD="$HERE/../load-snapshot.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/media/uploadedfiles" "$TMP/src/uploadedfiles" "$TMP/snap"
echo old >"$TMP/media/uploadedfiles/old.txt"
echo new >"$TMP/src/uploadedfiles/new.txt"
tar -C "$TMP/src" -cf "$TMP/snap/media.tar" uploadedfiles
printf 'PGDUMP' >"$TMP/snap/db.dump"
db_sha="$(sha256sum "$TMP/snap/db.dump" | cut -d' ' -f1)"
media_sha="$(sha256sum "$TMP/snap/media.tar" | cut -d' ' -f1)"
cat >"$TMP/snap/manifest.json" <<JSON
{"counts": {"resource_instances": 7, "tiles": 9},
 "files": {"db.dump": {"sha256": "$db_sha", "bytes": 6}, "media.tar": {"sha256": "$media_sha", "bytes": 1}}}
JSON

cat >"$TMP/bin/docker" <<'STUB'
#!/bin/sh
echo "docker $*" >>"$CALLS"
case "$*" in
  *pg_restore*)
    cat >/dev/null
    case "${STUB_RESTORE_MODE:-}" in
      known)
        for l in 'schema "public" already exists' 'extension "postgis" already exists' 'extension "uuid-ossp" already exists' 'must be owner of extension unaccent'; do
          echo "pg_restore: error: could not execute query: ERROR:  $l" >&2
        done
        echo 'pg_restore: warning: errors ignored on restore: 4' >&2
        exit 1 ;;
      foo) echo 'pg_restore: error: could not execute query: ERROR:  extension "foo" already exists' >&2; exit 1 ;;
      mixed)
        echo 'pg_restore: error: could not execute query: ERROR:  extension "postgis" already exists' >&2
        echo 'pg_restore: error: could not execute query: ERROR:  must be owner of extension foo' >&2
        exit 1 ;;
      prefix) echo 'pg_restore: error: could not execute query: ERROR:  extension "postgis_topology" already exists' >&2; exit 1 ;;
    esac
    [ -z "${STUB_RESTORE_FATAL:-}" ] || { echo 'pg_restore: error: could not execute query: ERROR:  relation "x" does not exist' >&2; exit 1; }
    echo 'pg_restore: error: could not execute query: ERROR:  must be owner of extension postgis' >&2
    echo 'pg_restore: warning: errors ignored on restore: 1' >&2
    exit 1 ;;
  *"FROM resource_instances"*) echo "${STUB_RESOURCES:-7}" ;;
  *"FROM tiles"*) echo 9 ;;
esac
exit 0
STUB
cat >"$TMP/bin/make" <<'STUB'
#!/bin/sh
echo "make $*" >>"$CALLS"
STUB
chmod +x "$TMP/bin/docker" "$TMP/bin/make"

write_env() { # write_env DEPLOY_ENVIRONMENT-LINE
  cat >"$TMP/.env" <<ENV
$1
PGDBNAME=manuspectrum
PGUSERNAME=postgres
APP_UID=$(id -u)
APP_GID=$(id -g)
MEDIA_HOST_DIR=$TMP/media
ENV
}

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

run_load() { # run_load [VAR=value ...]: runs with a fresh calls file; output in $TMP/out
  : >"$TMP/calls"
  env PATH="$TMP/bin:$PATH" CALLS="$TMP/calls" ENV_FILE="$TMP/.env" COMPOSE="docker compose" \
    MAKE_CMD="make" "$@" bash "$LOAD" "$TMP/snap" >"$TMP/out" 2>&1
}

write_env "DEPLOY_ENVIRONMENT=production"
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "DEPLOY_ENVIRONMENT" "$TMP/out" && [ ! -s "$TMP/calls" ]
assert "refused when DEPLOY_ENVIRONMENT is not rehearsal, nothing run" $?

write_env "# DEPLOY_ENVIRONMENT unset"
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && [ ! -s "$TMP/calls" ]
assert "refused when DEPLOY_ENVIRONMENT is absent" $?

write_env "DEPLOY_ENVIRONMENT=rehearsal"
run_load CONFIRM=no && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "CONFIRM=yes" "$TMP/out" && [ ! -s "$TMP/calls" ]
assert "refused without CONFIRM=yes, nothing run" $?

printf 'tampered' >>"$TMP/snap/db.dump"
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "sha256 mismatch" "$TMP/out" && [ ! -s "$TMP/calls" ]
assert "refused on a sha256 mismatch, nothing run" $?
printf 'PGDUMP' >"$TMP/snap/db.dump"

run_load CONFIRM=yes STUB_RESTORE_FATAL=1 && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "pg_restore failed" "$TMP/out" && ! grep -q "manage migrate" "$TMP/calls"
assert "a real pg_restore error stops before migrate" $?

run_load CONFIRM=yes STUB_RESTORE_MODE=known && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q "skipped 4 known harmless" "$TMP/out" && grep -q "manage migrate" "$TMP/calls"
assert "only the known harmless messages continue and are listed with their count" $?

for mode in foo mixed prefix; do
  run_load CONFIRM=yes STUB_RESTORE_MODE=$mode && status=0 || status=$?
  [ "$status" -ne 0 ] && grep -q "pg_restore failed" "$TMP/out" && ! grep -q "manage migrate" "$TMP/calls"
  assert "an unknown extension error ($mode) stops before migrate" $?
done

run_load CONFIRM=yes && status=0 || status=$?
assert "happy path exits 0" "$status"

expected=(
  "up -d --wait postgres elasticsearch redis-broker redis-cache"
  "stop web worker beat"
  "DROP DATABASE IF EXISTS"
  "CREATE DATABASE \"manuspectrum\" TEMPLATE template_postgis"
  "pg_restore --no-owner --no-privileges"
  "manage migrate"
  "make admin-password"
  "refresh_geojson_geometries"
  "manage es reindex_database"
  "FROM resource_instances"
  "make up"
  "make smoke"
)
last=0 ordered=0
for pattern in "${expected[@]}"; do
  line="$(grep -n -F -- "$pattern" "$TMP/calls" | head -n 1 | cut -d: -f1)"
  if [ -z "$line" ] || [ "$line" -lt "$last" ]; then ordered=1; echo "  out of order or missing: $pattern" >&2; fi
  last="${line:-$last}"
done
assert "steps run in order" "$ordered"

grep -q "harmless" "$TMP/out" || grep -q "only harmless extension errors" "$TMP/out"
assert "harmless extension errors are reported, not fatal" $?

[ "$(cat "$TMP/media/uploadedfiles/new.txt")" = new ] && [ ! -e "$TMP/media/uploadedfiles/old.txt" ]
assert "new uploads extracted" $?

find "$TMP/media" -path '*/previous-*/uploadedfiles/old.txt' | grep -q .
assert "previous uploads moved aside, not deleted" $?

[ "$(stat -c %a "$TMP/media/uploadedfiles")" = 750 ] && [ "$(stat -c %a "$TMP/media/uploadedfiles/new.txt")" = 640 ]
assert "directories 0750 and files 0640" $?

run_load CONFIRM=yes STUB_RESOURCES=8 && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q "WARNING: resource_instances: 8" "$TMP/out"
[ "$status" -eq 0 ] && grep -q "WARNING: resource_instances: 8" "$TMP/out"
assert "a count difference is reported, not fatal" $?

exit "$failed"
