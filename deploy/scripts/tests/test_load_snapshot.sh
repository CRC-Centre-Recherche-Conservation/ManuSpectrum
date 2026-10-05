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

mkdir -p "$TMP/bin" "$TMP/media/uploadedfiles" "$TMP/src/uploadedfiles" "$TMP/dockerroot"
echo old >"$TMP/media/uploadedfiles/old.txt"
echo new >"$TMP/src/uploadedfiles/new.txt"
: >"$TMP/marker"

DEFAULT_MIGRATIONS='{"arches": "0001_initial", "manuspectrum": "0005_sample"}'
make_snap() { # make_snap DIR TAR-SOURCE-DIR [MIGRATIONS-JSON] [ARCHES]
  mkdir -p "$1"
  tar -C "$2" -cf "$1/media.tar" uploadedfiles
  finish_snap "$1" "${3:-$DEFAULT_MIGRATIONS}" "${4:-8.1.4}"
}
finish_snap() { # finish_snap DIR MIGRATIONS-JSON ARCHES: db.dump and manifest next to an existing media.tar
  printf 'PGDUMP' >"$1/db.dump"
  python3 - "$1" "$2" "$3" <<'PY'
import hashlib
import json
import os
import sys

d, migrations, arches = sys.argv[1:4]
files = {}
for name in ("db.dump", "media.tar"):
    data = open(os.path.join(d, name), "rb").read()
    files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
json.dump({"counts": {"resource_instances": 7, "tiles": 9}, "arches_version": arches,
           "migrations": json.loads(migrations), "files": files},
          open(os.path.join(d, "manifest.json"), "w"))
PY
}
make_snap "$TMP/snap" "$TMP/src"

cat >"$TMP/facts" <<'FACTS'
ARCHES 8.1.4
MIG arches 0001_initial
MIG manuspectrum 0004_resource_summary
MIG manuspectrum 0005_sample
LEAF arches 0001_initial
LEAF manuspectrum 0005_sample
FACTS

# docker stub: records every call; `config --format json` answers the file
# config.json (what Compose resolves from .env).
cat >"$TMP/bin/docker" <<'STUB'
#!/bin/sh
echo "docker $*" | sed -n 1p >>"$CALLS"
case "$*" in
  *"config --format json"*) cat "$TMP/config.json" ;;
  "info "*) echo "$TMP/dockerroot" ;;
  *"python -c"*) echo "noise"; cat "${STUB_FACTS:-$TMP/facts}" ;;
  *"exec -T cantaloupe test -e"*) [ -z "$STUB_CANT_MISSING" ] || exit 1 ;;
  *pg_dump*) printf BEFORE ;;
  *"FROM pg_database"*) [ -n "$STUB_NO_DB" ] || echo 1 ;;
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
# STUB_SUDO_FAIL: sudo needs a password. Otherwise the command after the user
# and group options runs as is.
cat >"$TMP/bin/sudo" <<'STUB'
#!/bin/sh
[ -z "$STUB_SUDO_FAIL" ] || exit 1
[ "$1" != -n ] || shift
shift 4
exec "$@"
STUB
# STUB_DF_KB: free kilobytes reported for every path.
cat >"$TMP/bin/df" <<'STUB'
#!/bin/sh
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "stub 99999999 1 ${STUB_DF_KB:-99999999} 1% /"
STUB
chmod +x "$TMP/bin/docker" "$TMP/bin/make" "$TMP/bin/sudo" "$TMP/bin/df"

write_env() { # write_env DEPLOY_ENVIRONMENT-LINE [APP_UID] [APP_GID]
  local uid="${2:-$(id -u)}" gid="${3:-$(id -g)}"
  cat >"$TMP/.env" <<ENV
$1
PGDBNAME=manuspectrum
PGUSERNAME=postgres
APP_UID=$uid
APP_GID=$gid
MEDIA_HOST_DIR=$TMP/media
ENV
  python3 - "$1" "$uid" "$gid" "$TMP" <<'PY'
import json
import re
import sys

line, uid, gid, tmp = sys.argv[1:5]
environment = {"PGDBNAME": "manuspectrum"}
match = re.match(r"DEPLOY_ENVIRONMENT=(.*)$", line)
if match:
    environment["DEPLOY_ENVIRONMENT"] = match.group(1)
json.dump({"services": {
    "web": {"user": f"{uid}:{gid}", "environment": environment,
            "volumes": [{"type": "bind", "source": f"{tmp}/media", "target": "/srv/media"}]},
    "postgres": {"environment": {"POSTGRES_USER": "postgres"}},
}}, open(f"{tmp}/config.json", "w"))
PY
}
n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

SNAP_DIR="$TMP/snap"
run_load() { # run_load [VAR=value ...]: runs with a fresh calls file; output in $TMP/out
  : >"$TMP/calls"
  env PATH="$TMP/bin:$PATH" TMP="$TMP" CALLS="$TMP/calls" ENV_FILE="$TMP/.env" COMPOSE="docker compose" \
    MAKE_CMD="make" MS_REHEARSAL_MARKER="$TMP/marker" "$@" bash "$LOAD" "$SNAP_DIR" >"$TMP/out" 2>&1
}
# Nothing that changes a store or a container ran: only reads of the stack.
only_reads() { ! grep -vE 'config --format json|^docker info|python -c' "$TMP/calls" | grep -q .; }
# reset_media: one old upload (and a dotfile) in uploadedfiles, no aside directory
reset_media() {
  rm -rf "${TMP:?}/media"
  mkdir -p "$TMP/media/uploadedfiles"
  echo old >"$TMP/media/uploadedfiles/old.txt"
  echo hidden >"$TMP/media/uploadedfiles/.hidden"
}

write_env "DEPLOY_ENVIRONMENT=production"
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "DEPLOY_ENVIRONMENT" "$TMP/out" && only_reads
assert "refused when DEPLOY_ENVIRONMENT is not rehearsal, nothing run" $?

write_env "# DEPLOY_ENVIRONMENT unset"
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && only_reads
assert "refused when DEPLOY_ENVIRONMENT is absent" $?

write_env "DEPLOY_ENVIRONMENT=rehearsal"
run_load CONFIRM=no && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "CONFIRM=yes" "$TMP/out" && only_reads
assert "refused without CONFIRM=yes, nothing run" $?

rm -f "$TMP/marker"
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "rehearsal-host" "$TMP/out" && [ ! -s "$TMP/calls" ]
assert "refused without the host marker even with DEPLOY_ENVIRONMENT=rehearsal, no call at all" $?

write_env "DEPLOY_ENVIRONMENT=production"
: >"$TMP/marker"
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "DEPLOY_ENVIRONMENT" "$TMP/out" && only_reads
assert "refused with the host marker but DEPLOY_ENVIRONMENT=production" $?

write_env "DEPLOY_ENVIRONMENT=rehearsal"

printf 'tampered' >>"$SNAP_DIR/db.dump"
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "sha256 mismatch" "$TMP/out" && only_reads
assert "refused on a sha256 mismatch, nothing run" $?
printf 'PGDUMP' >"$SNAP_DIR/db.dump"

# Archive members: each variant is refused before anything runs.
mkdir -p "$TMP/bad/link/uploadedfiles" "$TMP/bad/hard/uploadedfiles" "$TMP/bad/dots/uploadedfiles"
ln -s /etc/passwd "$TMP/bad/link/uploadedfiles/link"
echo x >"$TMP/bad/hard/uploadedfiles/a"
ln "$TMP/bad/hard/uploadedfiles/a" "$TMP/bad/hard/uploadedfiles/b"
echo x >"$TMP/bad/dots/uploadedfiles/scan..tif"
make_snap "$TMP/snap-link" "$TMP/bad/link"
make_snap "$TMP/snap-hard" "$TMP/bad/hard"
make_snap "$TMP/snap-dots" "$TMP/bad/dots"
mkdir -p "$TMP/snap-dotdot"
python3 - "$TMP/snap-dotdot/media.tar" <<'PY'
import io
import sys
import tarfile

with tarfile.open(sys.argv[1], "w") as t:
    info = tarfile.TarInfo("uploadedfiles/../evil")
    info.size = 1
    t.addfile(info, io.BytesIO(b"x"))
PY
finish_snap "$TMP/snap-dotdot" "$DEFAULT_MIGRATIONS" 8.1.4
for kind in link hard dotdot; do
  SNAP_DIR="$TMP/snap-$kind"
  run_load CONFIRM=yes && status=0 || status=$?
  [ "$status" -ne 0 ] && only_reads
  assert "an archive with a $kind member is refused, nothing run" $?
done
SNAP_DIR="$TMP/snap-dots"
reset_media
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -eq 0 ] && [ -e "$TMP/media/uploadedfiles/scan..tif" ]
assert "a file named scan..tif is not mistaken for a parent path" $?
SNAP_DIR="$TMP/snap"

write_env "DEPLOY_ENVIRONMENT=rehearsal" 0
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "APP_UID and APP_GID" "$TMP/out" && only_reads
assert "APP_UID=0 is refused, nothing run" $?
write_env "DEPLOY_ENVIRONMENT=rehearsal" abc
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "APP_UID and APP_GID" "$TMP/out" && only_reads
assert "a non-numeric APP_UID is refused, nothing run" $?
write_env "DEPLOY_ENVIRONMENT=rehearsal" "$(id -u)" 0
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "APP_UID and APP_GID" "$TMP/out" && only_reads
assert "APP_GID=0 is refused, nothing run" $?
write_env "DEPLOY_ENVIRONMENT=rehearsal"

# Preflight: refused before anything is stopped, dumped or dropped.
printf 'MIG arches 0001_initial\nLEAF arches 0001_initial\nARCHES 8.1.4\n' >"$TMP/facts-unknown"
run_load CONFIRM=yes STUB_FACTS="$TMP/facts-unknown" && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "manuspectrum.0005_sample" "$TMP/out" && grep -q "unknown to the image" "$TMP/out" && only_reads
assert "preflight refuses a snapshot migration the image does not know" $?

sed 's/^LEAF manuspectrum.*/LEAF manuspectrum 0006_newer/;s/^MIG manuspectrum 0005_sample/&\nMIG manuspectrum 0006_newer/' "$TMP/facts" >"$TMP/facts-newer"
reset_media
run_load CONFIRM=yes STUB_FACTS="$TMP/facts-newer" && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q "WARNING: .*manuspectrum.*0006_newer" "$TMP/out" && grep -q "manage migrate" "$TMP/calls"
assert "preflight warns when the image has newer migrations and continues" $?

sed 's/^ARCHES .*/ARCHES 8.2.0/' "$TMP/facts" >"$TMP/facts-arches"
reset_media
run_load CONFIRM=yes STUB_FACTS="$TMP/facts-arches" && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q "WARNING: .*Arches" "$TMP/out"
assert "preflight warns on an Arches version mismatch and continues" $?

write_env "DEPLOY_ENVIRONMENT=rehearsal" "$(($(id -u) + 1))"
run_load CONFIRM=yes STUB_SUDO_FAIL=1 && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "sudo -n" "$TMP/out" && only_reads
assert "preflight refuses when sudo to APP_UID needs a password, nothing run" $?
write_env "DEPLOY_ENVIRONMENT=rehearsal"

run_load CONFIRM=yes STUB_DF_KB=1 && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "free space" "$TMP/out" && only_reads
assert "preflight refuses when the media filesystem lacks space, nothing run" $?

reset_media
run_load CONFIRM=yes STUB_RESTORE_FATAL=1 && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "pg_restore failed" "$TMP/out" && ! grep -q "manage migrate" "$TMP/calls"
assert "a real pg_restore error stops before migrate" $?

reset_media
run_load CONFIRM=yes STUB_RESTORE_MODE=known && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q "skipped 4 known harmless" "$TMP/out" && grep -q "manage migrate" "$TMP/calls"
assert "only the known harmless messages continue and are listed with their count" $?

for mode in foo mixed prefix; do
  run_load CONFIRM=yes STUB_RESTORE_MODE=$mode && status=0 || status=$?
  [ "$status" -ne 0 ] && grep -q "pg_restore failed" "$TMP/out" && ! grep -q "manage migrate" "$TMP/calls"
  assert "an unknown extension error ($mode) stops before migrate" $?
done

reset_media
inode_before="$(stat -c %i "$TMP/media/uploadedfiles")"
run_load CONFIRM=yes && status=0 || status=$?
assert "happy path exits 0" "$status"

expected=(
  "up -d --wait postgres elasticsearch redis-broker redis-cache"
  "stop web worker beat cantaloupe"
  "pg_dump -Fc"
  "DROP DATABASE IF EXISTS"
  "CREATE DATABASE \"manuspectrum\" TEMPLATE template_postgis"
  "pg_restore --no-owner --no-privileges"
  "exec -T redis-cache redis-cli FLUSHALL"
  "exec -T redis-broker redis-cli -n 0 FLUSHDB"
  "--entrypoint sh cantaloupe"
  "up -d --force-recreate cantaloupe"
  "manage migrate"
  "make admin-password"
  "refresh_geojson_geometries"
  "manage es reindex_database"
  "FROM resource_instances"
  "make up"
  "exec -T cantaloupe test -e /imageroot/.ms-load-check-"
  "make smoke"
)
last=0 ordered=0
for pattern in "${expected[@]}"; do
  line="$(grep -n -F -- "$pattern" "$TMP/calls" | head -n 1 | cut -d: -f1)"
  if [ -z "$line" ] || [ "$line" -lt "$last" ]; then ordered=1; echo "  out of order or missing: $pattern" >&2; fi
  last="${line:-$last}"
done
assert "steps run in order" "$ordered"

grep -q "preflight: ok" "$TMP/out"
assert "the preflight reports ok" $?

grep -q "harmless" "$TMP/out" || grep -q "only harmless extension errors" "$TMP/out"
assert "harmless extension errors are reported, not fatal" $?

[ "$(cat "$TMP/media/uploadedfiles/new.txt")" = new ] && [ ! -e "$TMP/media/uploadedfiles/old.txt" ]
assert "new uploads extracted" $?

find "$TMP/media" -path '*/previous-*/uploadedfiles/old.txt' | grep -q . \
  && find "$TMP/media" -path '*/previous-*/uploadedfiles/.hidden' | grep -q .
assert "previous uploads, dotfiles included, moved aside, not deleted" $?

[ "$(stat -c %i "$TMP/media/uploadedfiles")" = "$inode_before" ]
assert "the uploadedfiles directory itself is never moved (it is a bind-mount source)" $?

[ "$(cat "$(find "$TMP/media" -name rehearsal-before.dump | head -n 1)")" = BEFORE ]
assert "the previous database is dumped next to the previous uploads" $?

[ "$(stat -c %a "$TMP/media/uploadedfiles")" = 750 ] && [ "$(stat -c %a "$TMP/media/uploadedfiles/new.txt")" = 640 ]
assert "directories 0750 and files 0640" $?

reset_media
run_load CONFIRM=yes STUB_CANT_MISSING=1 && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "Cantaloupe does not see" "$TMP/out"
assert "the run fails when Cantaloupe does not see a file of the new snapshot" $?

reset_media
run_load CONFIRM=yes STUB_NO_DB=1 && status=0 || status=$?
[ "$status" -eq 0 ] && ! grep -q "pg_dump" "$TMP/calls"
assert "no database dump when there is no database yet" $?

# Only the last two aside directories are kept.
reset_media
for stamp in 20200101T000000Z 20200102T000000Z 20200103T000000Z; do
  mkdir -p "$TMP/media/previous-$stamp-aaaaaa"
  touch -d "${stamp:0:4}-${stamp:4:2}-${stamp:6:2}" "$TMP/media/previous-$stamp-aaaaaa"
done
run_load CONFIRM=yes && status=0 || status=$?
[ "$status" -eq 0 ] && [ "$(find "$TMP/media" -maxdepth 1 -name 'previous-*' | wc -l)" -eq 2 ] \
  && [ ! -e "$TMP/media/previous-20200101T000000Z-aaaaaa" ] && grep -q "removed previous-20200101T000000Z-aaaaaa" "$TMP/out"
assert "only the last two aside directories are kept and the removed ones are printed" $?

reset_media
run_load CONFIRM=yes STUB_RESOURCES=8 && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q "WARNING: resource_instances: 8" "$TMP/out"
assert "a count difference is reported, not fatal" $?

exit "$failed"
