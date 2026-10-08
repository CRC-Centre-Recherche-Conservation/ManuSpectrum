#!/usr/bin/env bash
# deploy/scripts/tests/test_restore.sh
# Tests of restore.sh and restore-files.sh. docker, make, df and stat are stubs
# on PATH that record their calls in $TMP/calls; the restic stub lays a fixture
# snapshot into the mounted target; nothing real runs. Prints `ok N` /
# `not ok N`; exits non-zero on failure.
# $? after a negated or compound test is the point of every assertion below.
# shellcheck disable=SC2319
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESTORE="$HERE/../restore.sh"
FILES="$HERE/../restore-files.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

UID_NOW="$(id -u)"
GID_NOW="$(id -g)"
PW_RESTIC="$(head -c 36 /dev/urandom | base64 | tr -d '\n=+/')"
PW_PG="$(head -c 36 /dev/urandom | base64 | tr -d '\n=+/')"
ASIDE_OLD="$TMP/media/previous-20260101T000000Z-abcdef"
export OLDER_ID=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export LATEST_ID=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb

mkdir -p "$TMP/bin" "$TMP/secrets" "$TMP/dockerroot"
printf '%s' "$PW_RESTIC" >"$TMP/secrets/restic_password"
printf '%s' "$PW_PG" >"$TMP/secrets/pg_password"
echo "PGDBNAME=manuspectrum" >"$TMP/.env"

cat >"$TMP/facts" <<'FACTS'
ARCHES 8.1.4
APP arches
APP manuspectrum
MIG arches 0001_initial
MIG manuspectrum 0005_sample
LEAF arches 0001_initial
LEAF manuspectrum 0005_sample
FACTS

DEFAULT_MIGRATIONS='{"arches": "0001_initial", "manuspectrum": "0005_sample"}'
write_fixture() { # write_fixture [MIGRATIONS-JSON] [APP_UID]: config, snapshot, media, dump directory
  rm -rf "${TMP:?}/media" "${TMP:?}/dump" "${TMP:?}/snapshot" "${TMP:?}/snapshot-media"
  mkdir -p "$TMP/media/uploadedfiles" "$TMP/repo" "$TMP/dump" "$TMP/snapshot" "$TMP/snapshot-media/uploadedfiles/sub"
  echo old >"$TMP/media/uploadedfiles/old.txt"
  echo new >"$TMP/snapshot-media/uploadedfiles/new.txt"
  echo nested >"$TMP/snapshot-media/uploadedfiles/sub/n.txt"
  chmod 0666 "$TMP/snapshot-media/uploadedfiles/new.txt"
  python3 - "$TMP" "${2:-$UID_NOW}" "$GID_NOW" "${1:-$DEFAULT_MIGRATIONS}" <<'PY'
import hashlib
import json
import sys

tmp, uid, gid, migrations = sys.argv[1:5]
files = {"db.dump": b"PGDUMP", "globals.sql": b"CREATE ROLE postgres;\n", "env": b"PGDBNAME=manuspectrum\n"}
for name, data in files.items():
    open(f"{tmp}/snapshot/{name}", "wb").write(data)
json.dump({"kind": "backup", "created_at": "2026-10-07T02:00:00Z", "arches_version": "8.1.4",
           "counts": {"resource_instances": 7, "tiles": 9}, "migrations": json.loads(migrations),
           "media": {"files": 2, "bytes": 10},
           "files": {n: {"sha256": hashlib.sha256(d).hexdigest(), "bytes": len(d)} for n, d in files.items()}},
          open(f"{tmp}/snapshot/manifest.json", "w"))
json.dump({"services": {
    "web": {"user": f"{uid}:{gid}", "image": "manuspectrum:test",
            "environment": {"PGDBNAME": "manuspectrum"},
            "volumes": [{"type": "bind", "source": f"{tmp}/media", "target": "/srv/media"}]},
    "postgres": {"environment": {"POSTGRES_USER": "postgres"}},
    "restic": {"volumes": [
        {"type": "bind", "source": f"{tmp}/repo", "target": "/repo"},
        {"type": "bind", "source": f"{tmp}/dump/latest", "target": "/backup/db", "read_only": True},
        {"type": "bind", "source": f"{tmp}/media", "target": "/backup/media", "read_only": True},
        {"type": "bind", "source": f"{tmp}/secrets", "target": "/backup/secrets", "read_only": True},
    ]},
}}, open(f"{tmp}/config.json", "w"))
PY
}

cat >"$TMP/bin/docker" <<'STUB'
#!/bin/sh
echo "docker $*" | sed -n 1p >>"$CALLS"
case "$*" in
  *"config --format json"*) cat "$TMP/config.json" ;;
  *"--entrypoint sh cantaloupe"*)
    [ -z "$STUB_BLOCK_SWAP" ] || { touch "$TMP/blocked"; exec sleep 30; } ;;
  "info "*) echo "$TMP/dockerroot" ;;
  *"python -c"*) echo "noise"; cat "$TMP/facts" ;;
  *" restic --no-cache"*)
    sub="${*#*--retry-lock 30m }"
    sub="${sub%% *}"
    [ "$STUB_RESTIC_FAIL" != "$sub" ] || { echo "restic: stub failure" >&2; exit 1; }
    case "$sub" in
      snapshots)
        printf '[{"id":"%s","time":"2026-10-06T02:00:00Z"},{"id":"%s","time":"2026-10-07T02:00:00Z"}]\n' "$OLDER_ID" "$LATEST_ID" ;;
      ls)
        echo "snapshot 4a5909c7 of [/backup] filtered by [/backup/media]:"
        printf '%s\n' /backup/media /backup/media/uploadedfiles /backup/media/concepts ;;
      restore)
        mount="${*#* -v }"
        mount="${mount%%:*}"
        case "$*" in
          *"--include /backup/db "*)
            mkdir -p "$mount/backup/db" && cp "$TMP"/snapshot/* "$mount/backup/db/"
            [ -z "$STUB_BAD_FILE" ] || printf 'tampered' >"$mount/backup/db/db.dump" ;;
          *"--include /backup/media/uploadedfiles "*)
            [ -z "$STUB_DF_DROP" ] || echo 10 >"$TMP/df_avail"
            mkdir -p "$mount/backup/media" && cp -r "$TMP/snapshot-media/uploadedfiles" "$mount/backup/media/" ;;
          *)
            inc="${*#*--include }"
            inc="${inc%% *}"
            mkdir -p "$mount$(dirname "$inc")" && echo restored >"$mount$inc" ;;
        esac ;;
    esac ;;
  *"exec -T cantaloupe test -e"*) ;;
  *pg_dump*) printf BEFORE ;;
  *"FROM pg_database"*) echo 1 ;;
  *pg_restore*) cat >/dev/null ;;
  *"FROM resource_instances"*) echo 7 ;;
  *"FROM tiles"*) echo 9 ;;
esac
exit 0
STUB
cat >"$TMP/bin/make" <<'STUB'
#!/bin/sh
echo "make $*" >>"$CALLS"
STUB
cat >"$TMP/bin/df" <<'STUB'
#!/bin/sh
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "stub 99999999 1 $(cat "$TMP/df_avail" 2>/dev/null || echo 99999999) 1% /"
STUB
# stat: the device of a staging directory differs when STUB_OTHER_FS is set.
cat >"$TMP/bin/stat" <<'STUB'
#!/bin/sh
if [ "$1 $2" = "-c %d" ]; then
  case "$3" in *"/.restore-"*) [ -z "$STUB_OTHER_FS" ] && echo 1 || echo 2 ;; *) echo 1 ;; esac
  exit 0
fi
exec /usr/bin/stat "$@"
STUB
chmod +x "$TMP/bin/docker" "$TMP/bin/make" "$TMP/bin/df" "$TMP/bin/stat"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

run_script() { # run_script SCRIPT [VAR=value ...]: fresh calls file; output in $TMP/out
  local script="$1"
  shift
  : >"$TMP/calls"
  rm -f "$TMP/df_avail" "$TMP/blocked"
  env PATH="$TMP/bin:$PATH" TMP="$TMP" CALLS="$TMP/calls" ENV_FILE="$TMP/.env" COMPOSE="docker compose" \
    MAKE_CMD="make" BACKUP_LOCK_WAIT=2 "$@" bash "$script" >"$TMP/out" 2>&1
}
run_restore() { run_script "$RESTORE" "$@"; }
run_files() { run_script "$FILES" "$@"; }
OK_ENV=(CONFIRM=yes ERASURES_CHECKED=yes)
# Nothing that changes a store, a container or the data ran.
no_mutation() { ! grep -E ' stop |up -d|DROP|CREATE|pg_dump|pg_restore|FLUSH|^make |run --rm --no-deps -T --entrypoint|migrate|es reindex' "$TMP/calls" | grep -q .; }
no_restic() { ! grep -q ' restic --no-cache' "$TMP/calls"; }
no_staging() { [ -z "$(find "$TMP/dump" "$TMP/media" -maxdepth 1 -name '.restore-*')" ]; }
no_leak() { ! grep -rqF -e "$PW_RESTIC" -e "$PW_PG" "$TMP/out" "$TMP/calls" 2>/dev/null; }
untouched_secrets() { cmp -s "$TMP/.env" "$TMP/.env.before" && diff -r "$TMP/secrets" "$TMP/secrets.before" >/dev/null; }
snapshot_state() { cp "$TMP/.env" "$TMP/.env.before"; rm -rf "${TMP:?}/secrets.before"; cp -a "$TMP/secrets" "$TMP/secrets.before"; }

# --- refusals
write_fixture
run_restore RESTIC_SNAPSHOT=latest ERASURES_CHECKED=yes && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q "CONFIRM=yes" "$TMP/out" && [ ! -s "$TMP/calls" ]
assert "confirm-required: exit 1, no docker call" $?

run_restore CONFIRM=yes ERASURES_CHECKED=yes && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q "RESTIC_SNAPSHOT" "$TMP/out" && grep -q "ASIDE" "$TMP/out" && [ ! -s "$TMP/calls" ]
assert "source-required: exit 1, no docker call" $?

run_restore "${OK_ENV[@]}" RESTIC_SNAPSHOT=latest ASIDE="$ASIDE_OLD" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q "not both" "$TMP/out" && [ ! -s "$TMP/calls" ]
assert "both-sources: exit 1, no docker call" $?

run_restore CONFIRM=yes RESTIC_SNAPSHOT=latest && status=0 || status=$?
[ "$status" -eq 2 ] && grep -q "ERASURES_CHECKED=yes" "$TMP/out" && grep -q "BACKUP.md" "$TMP/out" \
  && grep -q "Personal data" "$TMP/out" && [ ! -s "$TMP/calls" ]
assert "erasures-required: exit 2, the message points to BACKUP.md Personal data, no docker call" $?
run_restore CONFIRM=yes ERASURES_CHECKED=no RESTIC_SNAPSHOT=latest && status=0 || status=$?
[ "$status" -eq 2 ] && [ ! -s "$TMP/calls" ]
assert "erasures-required: anything but yes is refused" $?
run_restore CONFIRM=yes ERASURES_CHECKED=yes ASIDE="$ASIDE_OLD" && status=0 || status=$?
[ "$status" -ne 2 ] || [ "$(grep -c 'ERASURES' "$TMP/out")" -eq 0 ]
assert "erasures-checked accepted together with an aside source" $?

run_restore "${OK_ENV[@]}" RESTIC_SNAPSHOT='latest;rm' && status=0 || status=$?
[ "$status" -eq 1 ] && [ ! -s "$TMP/calls" ]
assert "a malformed snapshot id: exit 1, no docker call" $?

# --- failures after the restic restore, before anything changes
write_fixture
run_restore "${OK_ENV[@]}" RESTIC_SNAPSHOT=latest STUB_BAD_FILE=1 && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q "do not match manifest.json" "$TMP/out" && no_mutation && no_staging
assert "checksum-bad: refused after step 1, only reads, staging removed" $?

write_fixture '{"arches": "0001_initial", "manuspectrum": "0099_unknown"}'
run_restore "${OK_ENV[@]}" RESTIC_SNAPSHOT=latest && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q "unknown to the image" "$TMP/out" && no_mutation && no_staging
assert "unknown-migration: refused before step 4, only reads, staging removed" $?

write_fixture
run_restore "${OK_ENV[@]}" RESTIC_SNAPSHOT=latest STUB_OTHER_FS=1 && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q "another filesystem" "$TMP/out" && no_mutation && no_staging \
  && ! grep -q 'include /backup/media/uploadedfiles' "$TMP/calls"
assert "other-filesystem: refused on the empty staging directory, before the uploads are restored, staging removed" $?

write_fixture
run_restore "${OK_ENV[@]}" RESTIC_SNAPSHOT=latest STUB_RESTIC_FAIL=restore && status=0 || status=$?
[ "$status" -eq 1 ] && no_mutation && no_staging
assert "restic restore fails: exit 1, only reads, staging removed" $?

if [ "$UID_NOW" -ne 0 ]; then
  write_fixture "$DEFAULT_MIGRATIONS" 12345
  run_restore "${OK_ENV[@]}" RESTIC_SNAPSHOT=latest && status=0 || status=$?
  [ "$status" -eq 1 ] && grep -q "make -C deploy restore" "$TMP/out" && ! grep -q "load-snapshot" "$TMP/out" && no_mutation && no_restic
  assert "wrong identity: refused before any restore, the hint names make restore" $?
fi

# --- success from a snapshot
write_fixture
snapshot_state
run_restore "${OK_ENV[@]}" RESTIC_SNAPSHOT=latest && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q "done: " "$TMP/out"
assert "ok-snapshot: exit 0" $?

python3 - "$TMP/calls" "$TMP/out" <<'PY'
import os
import re
import sys

calls = [line.rstrip("\n") for line in open(sys.argv[1])]
out = open(sys.argv[2]).read()
latest = os.environ["LATEST_ID"]

def first(pattern):
    return next(i for i, c in enumerate(calls) if re.search(pattern, c))

order = [
    first(r"restic --no-cache .*snapshots latest --json"),
    first(rf"restic --no-cache .*restore {latest} --target /restore --include /backup/db --verify"),
    first(rf"restic --no-cache .*restore {latest} --target /restore --include /backup/media/uploadedfiles --verify"),
    first(rf"restic --no-cache .*ls {latest} /backup/media"),
    first(r"python -c"),
    first(r"up -d --wait postgres"),
    first(r" stop web worker beat cantaloupe"),
    first(r"pg_dump"),
    first(r"DROP DATABASE IF EXISTS"),
    first(r"CREATE DATABASE"),
    first(r"pg_restore"),
    first(r"FLUSHALL"),
    first(r"--entrypoint sh cantaloupe"),
    first(r"manage migrate"),
    first(r"^make admin-password"),
    first(r"refresh_geojson_geometries"),
    first(r"es reindex_database"),
    first(r"^make up$"),
    first(r"^make smoke$"),
]
assert order == sorted(order) and len(set(order)) == len(order), order
steps = re.findall(r"restore: step (\d+)/14", out)
assert steps == [str(i) for i in range(1, 15)], steps
PY
assert "ok-snapshot: restic restore of the dump and the uploads, then the 14 steps in order, make up and smoke called" $?

grep -c "restic --no-cache.* \(restore\|ls\) $LATEST_ID " "$TMP/calls" | grep -qx 3 \
  && [ "$(grep -c 'snapshots latest --json' "$TMP/calls")" -eq 1 ] \
  && ! grep -qE 'restic --no-cache.* (restore|ls) latest ' "$TMP/calls" && grep -q "snapshot latest is $LATEST_ID" "$TMP/out"
assert "ok-snapshot: latest is resolved once to the newest id, and the db restore, the uploads restore and the listing name it" $?

before="$(find "$TMP/media" -maxdepth 1 -name 'previous-*' | head -n 1)"
[ -f "$before/before-restore.dump" ] && [ "$(cat "$before/before-restore.dump")" = BEFORE ] \
  && [ "$(cat "$before/uploadedfiles/old.txt")" = old ] && [ -f "$before/.complete" ]
assert "ok-snapshot: the previous uploads and before-restore.dump are in a complete previous-* directory" $?
[ "$(cat "$TMP/media/uploadedfiles/new.txt")" = new ] && [ "$(cat "$TMP/media/uploadedfiles/sub/n.txt")" = nested ] \
  && [ ! -e "$TMP/media/uploadedfiles/old.txt" ] \
  && [ "$(stat -c %a "$TMP/media/uploadedfiles/new.txt")" = 640 ] && [ "$(stat -c %a "$TMP/media/uploadedfiles/sub")" = 750 ]
assert "ok-snapshot: the new uploads are in uploadedfiles/ with modes 0640/0750" $?
no_staging
assert "ok-snapshot: the staging directories are gone" $?
untouched_secrets
assert "ok-snapshot: SECRETS_DIR and .env are byte-identical before and after" $?
grep -q "make -C deploy restore ASIDE=$before CONFIRM=yes ERASURES_CHECKED=yes" "$TMP/out" \
  && ! grep -q "load-snapshot" "$TMP/out" \
  && grep -qi "SECRETS_DIR and .env were not touched" "$TMP/out"
assert "ok-snapshot: the final lines name the undo command and say the secrets were not touched" $?
grep -q "concepts" "$TMP/out" && grep -q "restore-files" "$TMP/out"
assert "ok-snapshot: the other top-level entries of the snapshot are reported, not restored" $?
grep -q "erasure" "$TMP/out" && grep -q "2026-10-07" "$TMP/out"
assert "ok-snapshot: the output reminds to replay the erasures made since the snapshot date" $?
no_leak
assert "ok-snapshot: neither fake password appears in output or calls" $?

# --- the staged uploads are not counted twice in the free-space check
write_fixture
run_restore "${OK_ENV[@]}" RESTIC_SNAPSHOT=latest STUB_DF_DROP=1 && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q "preflight: ok" "$TMP/out"
assert "move mode: the preflight does not count the already staged uploads again (free space is 10 KiB after staging)" $?

# --- a run stopped by a signal during the swap
write_fixture
: >"$TMP/calls"
rm -f "$TMP/blocked" "$TMP/df_avail"
setsid env PATH="$TMP/bin:$PATH" TMP="$TMP" CALLS="$TMP/calls" ENV_FILE="$TMP/.env" COMPOSE="docker compose" \
  MAKE_CMD="make" BACKUP_LOCK_WAIT=2 CONFIRM=yes ERASURES_CHECKED=yes RESTIC_SNAPSHOT=latest STUB_BLOCK_SWAP=1 \
  bash "$RESTORE" >"$TMP/out" 2>&1 &
pid=$!
waited=0
while [ ! -e "$TMP/blocked" ] && [ "$waited" -lt 100 ]; do sleep 0.1; waited=$((waited + 1)); done
kill -TERM -- "-$pid"
wait "$pid" && status=0 || status=$?
[ "$status" -eq 143 ] && ! no_staging && grep -q "staging directories are kept" "$TMP/out" \
  && grep -q "the data this run replaced is in $TMP/media/previous-" "$TMP/out" \
  && [ "$(cat "$TMP/media/previous-"*/uploadedfiles/old.txt)" = old ]
assert "TERM mid-swap: exit 143, the staging directories are kept and the aside is named" $?

# --- success from an aside directory
write_fixture
mkdir -p "$ASIDE_OLD/uploadedfiles"
printf 'ASIDEDUMP' >"$ASIDE_OLD/before-restore.dump"
echo aside >"$ASIDE_OLD/uploadedfiles/a.txt"
snapshot_state
run_restore "${OK_ENV[@]}" ASIDE="$ASIDE_OLD" && status=0 || status=$?
[ "$status" -eq 0 ] && no_restic && grep -q "pg_restore" "$TMP/calls" && [ "$(cat "$TMP/media/uploadedfiles/a.txt")" = aside ] \
  && [ ! -e "$TMP/media/uploadedfiles/old.txt" ] && untouched_secrets && grep -q "no manifest" "$TMP/out"
assert "ok-aside: the aside dump and uploads are restored, no restic call, no manifest checks, secrets untouched" $?
run_restore "${OK_ENV[@]}" ASIDE="$TMP/elsewhere" && status=0 || status=$?
[ "$status" -eq 1 ] && no_mutation
assert "an aside outside MEDIA_HOST_DIR is refused" $?

# --- lock
write_fixture
flock -x "$TMP/dump/.lock" sleep 6 &
holder=$!
sleep 0.5
run_restore "${OK_ENV[@]}" RESTIC_SNAPSHOT=latest && status=0 || status=$?
held_status=$status
kill "$holder" 2>/dev/null
wait "$holder" 2>/dev/null
[ "$held_status" -eq 1 ] && grep -q "another backup or restore is running" "$TMP/out" && no_mutation && no_restic
assert "lock-held: refused at once, no restic call, nothing changed" $?

# --- restore-files
write_fixture
mkdir -p "$TMP/media/uploadedfiles" "$TMP/dump/latest"
FILES_OK=(RESTIC_SNAPSHOT=latest INCLUDE=/backup/secrets/pg_password)
files_refused() { # files_refused DESCRIPTION VAR=value...
  local description="$1"
  shift
  run_files "$@" && status=0 || status=$?
  [ "$status" -eq 1 ] && no_restic
  assert "files-refusals: $description: exit 1, no restic call" $?
}
files_refused "INCLUDE with .." RESTIC_SNAPSHOT=latest INCLUDE=/backup/../etc TARGET="$TMP/out1"
files_refused "INCLUDE outside /backup/" RESTIC_SNAPSHOT=latest INCLUDE=/etc/passwd TARGET="$TMP/out1"
files_refused "relative INCLUDE" RESTIC_SNAPSHOT=latest INCLUDE=backup/db TARGET="$TMP/out1"
files_refused "no INCLUDE" RESTIC_SNAPSHOT=latest TARGET="$TMP/out1"
files_refused "no TARGET" "${FILES_OK[@]}"
files_refused "relative TARGET" "${FILES_OK[@]}" TARGET=out1
files_refused "TARGET with .." "${FILES_OK[@]}" TARGET="$TMP/x/../out1"
files_refused "TARGET inside uploadedfiles" "${FILES_OK[@]}" TARGET="$TMP/media/uploadedfiles/out"
files_refused "TARGET is uploadedfiles" "${FILES_OK[@]}" TARGET="$TMP/media/uploadedfiles"
files_refused "TARGET inside SECRETS_DIR" "${FILES_OK[@]}" TARGET="$TMP/secrets/out"
files_refused "TARGET inside BACKUP_DUMP_DIR/latest" "${FILES_OK[@]}" TARGET="$TMP/dump/latest/out"
files_refused "TARGET is RESTIC_REPOSITORY_DIR" "${FILES_OK[@]}" TARGET="$TMP/repo"
files_refused "TARGET inside RESTIC_REPOSITORY_DIR" "${FILES_OK[@]}" TARGET="$TMP/repo/out"
files_refused "TARGET is BACKUP_DUMP_DIR" "${FILES_OK[@]}" TARGET="$TMP/dump"
files_refused "TARGET inside BACKUP_DUMP_DIR (a staging directory)" "${FILES_OK[@]}" TARGET="$TMP/dump/.restore-1/out"
files_refused "TARGET inside BACKUP_DUMP_DIR/previous" "${FILES_OK[@]}" TARGET="$TMP/dump/previous"
mkdir -p "$TMP/full" && echo x >"$TMP/full/f"
files_refused "non-empty TARGET" "${FILES_OK[@]}" TARGET="$TMP/full"
files_refused "malformed snapshot id" RESTIC_SNAPSHOT='x y' INCLUDE=/backup/db TARGET="$TMP/out1"
[ ! -e "$TMP/out1" ]
assert "files-refusals: no target directory was created" $?

run_files "${FILES_OK[@]}" TARGET="$TMP/out-files" && status=0 || status=$?
[ "$status" -eq 0 ] && [ "$(stat -c %a "$TMP/out-files")" = 700 ] \
  && grep -q -- "-v $TMP/out-files:/restore restic --no-cache --retry-lock 30m restore latest --target /restore --include /backup/secrets/pg_password --verify" "$TMP/calls" \
  && [ "$(cat "$TMP/out-files/backup/secrets/pg_password")" = restored ] && grep -q "$TMP/out-files/backup/secrets/pg_password" "$TMP/out"
assert "files-ok: restic restore with the include and --verify into a 0700 target, restored paths printed" $?
mkdir -p "$TMP/empty-target"
run_files RESTIC_SNAPSHOT=0123abcd INCLUDE=/backup/db TARGET="$TMP/empty-target" && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q "restore 0123abcd " "$TMP/calls" && no_mutation
assert "files-ok: an empty existing TARGET and an explicit snapshot id are accepted; nothing else is touched" $?
no_leak
assert "files-ok: neither fake password appears in output or calls" $?

exit "$failed"
