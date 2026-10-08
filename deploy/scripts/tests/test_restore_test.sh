#!/usr/bin/env bash
# deploy/scripts/tests/test_restore_test.sh
# Tests of restore-test.sh. docker is a stub on PATH that records its calls in
# $TMP/calls (psql statements included); the restic stub lays a fixture
# snapshot into the mounted staging directory; nothing real runs. Prints
# `ok N` / `not ok N`; exits non-zero on failure.
# $? after a negated or compound test is the point of every assertion below.
# shellcheck disable=SC2319
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../restore-test.sh"
LIB="$HERE/../lib-backup.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

UID_NOW="$(id -u)"
GID_NOW="$(id -g)"
PW_RESTIC="$(head -c 36 /dev/urandom | base64 | tr -d '\n=+/')"
PW_PG="$(head -c 36 /dev/urandom | base64 | tr -d '\n=+/')"
export COUNTS_JSON='{"resource_instances": 7, "spatial_ref_sys": 8500, "tiles": 9, "users": 2}'
SCRATCH=manuspectrum_restoretest

mkdir -p "$TMP/bin" "$TMP/secrets" "$TMP/metrics"
printf '%s' "$PW_RESTIC" >"$TMP/secrets/restic_password"
printf '%s' "$PW_PG" >"$TMP/secrets/pg_password"
echo "PGDBNAME=manuspectrum" >"$TMP/.env"

write_fixture() { # Compose configuration, dump directory, fixture snapshot
  rm -rf "${TMP:?}/media" "${TMP:?}/dump" "${TMP:?}/snapshot"
  mkdir -p "$TMP/media" "$TMP/repo" "$TMP/dump" "$TMP/snapshot"
  python3 - "$TMP" "$UID_NOW" "$GID_NOW" "${1:-manuspectrum}" <<'PY'
import hashlib
import json
import os
import sys

tmp, uid, gid, dbname = sys.argv[1:5]
files = {"db.dump": b"PGDUMP", "globals.sql": b"CREATE ROLE postgres;\n", "env": b"PGDBNAME=manuspectrum\n"}
for name, data in files.items():
    open(f"{tmp}/snapshot/{name}", "wb").write(data)
json.dump({"kind": "backup", "counts": json.loads(os.environ["COUNTS_JSON"]),
           "files": {n: {"sha256": hashlib.sha256(d).hexdigest(), "bytes": len(d)} for n, d in files.items()}},
          open(f"{tmp}/snapshot/manifest.json", "w"))
json.dump({"services": {
    "web": {"user": f"{uid}:{gid}", "image": "manuspectrum:test",
            "environment": {"PGDBNAME": dbname},
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
printf 'docker %s\n' "$*" >>"$CALLS"
case "$*" in
  *"config --format json"*) cat "$TMP/config.json" ;;
  *"exec -T postgres psql"*)
    while IFS= read -r line; do
      printf 'psql< %s\n' "$line" >>"$CALLS"
      case "$line" in
        *query_to_xml*) echo "${SCRATCH_COUNTS:-$COUNTS_JSON}" ;;
      esac
    done ;;
  *"exec -T postgres pg_restore"*)
    cat >/dev/null
    if [ -n "$STUB_RESTORE_FATAL" ]; then
      echo 'pg_restore: error: could not execute query: ERROR:  relation "tiles" already exists' >&2
      exit 1
    fi ;;
  *" restic --no-cache"*)
    sub="${*#*--retry-lock 30m }"
    sub="${sub%% *}"
    [ "$STUB_RESTIC_FAIL" != "$sub" ] || { echo "restic: stub failure" >&2; exit 1; }
    if [ "$sub" = restore ]; then
      mount="${*#* -v }"
      mount="${mount%% *}"
      mkdir -p "${mount%%:*}/backup/db"
      cp "$TMP"/snapshot/* "${mount%%:*}/backup/db/"
      [ -z "$STUB_BAD_FILE" ] || printf 'tampered' >"${mount%%:*}/backup/db/db.dump"
    fi ;;
esac
exit 0
STUB
chmod +x "$TMP/bin/docker"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

run_test() { # run_test [VAR=value ...] -- [ARGS...]: fresh calls file; output in $TMP/out
  local envs=()
  while [ "$#" -gt 0 ] && [ "$1" != -- ]; do envs+=("$1"); shift; done
  [ "$#" -eq 0 ] || shift
  : >"$TMP/calls"
  env PATH="$TMP/bin:$PATH" TMP="$TMP" CALLS="$TMP/calls" ENV_FILE="$TMP/.env" COMPOSE="docker compose" \
    METRICS_TEXTFILE_DIR="$TMP/metrics" BACKUP_LOCK_WAIT=2 "${envs[@]}" bash "$SCRIPT" "$@" >"$TMP/out" 2>&1
}
sql_calls() { grep -c 'exec -T postgres \(psql\|pg_restore\)' "$TMP/calls"; }
restic_subs() { grep ' restic --no-cache' "$TMP/calls" | sed 's/.*--retry-lock 30m //'; }
clean_dump_dir() { [ -z "$(find "$TMP/dump" -maxdepth 1 -name '.restore-test-*')" ]; }
no_leak() { ! grep -rqF -e "$PW_RESTIC" -e "$PW_PG" "$TMP/out" "$TMP/calls" "$TMP/metrics" 2>/dev/null; }
reset() { write_fixture; rm -rf "${TMP:?}/metrics"; mkdir -p "$TMP/metrics"; }
scratch_dropped_last() { # the last psql statement is the drop of the scratch database
  grep 'postgres psql' "$TMP/calls" | tail -n 1 | grep -q "DROP DATABASE IF EXISTS \"$SCRATCH\" WITH (FORCE)"
}

# --- success
reset
run_test -- && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q "every count equal to the manifest" "$TMP/out"
assert "exit 0, every table of the manifest equal" $?

python3 - "$TMP/calls" <<'PY'
import re
import sys

calls = [line.rstrip("\n") for line in open(sys.argv[1])]
sub = [c.split("--retry-lock 30m ", 1)[1] for c in calls if " restic --no-cache" in c]
assert sub[0].startswith("restore latest --target /restore --include /backup/db --verify"), sub
assert sub[-1] == "check --read-data-subset=10%", sub
assert any(re.search(r" -v \S+/\.restore-test-\S+:/restore restic ", c) for c in calls), calls

def first(pattern):
    return next(i for i, c in enumerate(calls) if re.search(pattern, c))

drop_first = first(r'DROP DATABASE IF EXISTS "manuspectrum_restoretest" WITH \(FORCE\)')
create = first(r'CREATE DATABASE "manuspectrum_restoretest" TEMPLATE template_postgis')
restore = first(r"pg_restore .* -d manuspectrum_restoretest")
counts = first(r"^psql< .*query_to_xml")
last_drop = max(i for i, c in enumerate(calls) if 'DROP DATABASE IF EXISTS "manuspectrum_restoretest"' in c)
check = first(r"restic --no-cache .* check ")
assert drop_first < create < restore < counts < check < last_drop, (drop_first, create, restore, counts, check, last_drop)
PY
assert "restic restore of /backup/db, drop, create from template_postgis, pg_restore, counts, restic check, drop" $?

python3 - "$TMP/calls" <<'PY'
import re
import sys

live = re.compile(r"\bmanuspectrum\b")
for line in open(sys.argv[1]):
    if "exec -T postgres psql" in line or "exec -T postgres pg_restore" in line:
        assert "manuspectrum_restoretest" in line or "-d postgres" in line, line
        assert "-d postgres" not in line or "manuspectrum_restoretest" in line, line
        assert not live.search(line), line
    if line.startswith("psql< "):
        assert not live.search(line), line
PY
assert "every psql and pg_restore call names the scratch database, none the live one (-d postgres only to drop and create it)" $?

grep -q '^manuspectrum_restore_test_failed 0$' "$TMP/metrics/manuspectrum_restore_test.prom" \
  && grep -q '^manuspectrum_restore_test_last_attempt_timestamp_seconds [0-9]' "$TMP/metrics/manuspectrum_restore_test.prom" \
  && grep -q '^manuspectrum_restore_test_last_success_timestamp_seconds [0-9]' "$TMP/metrics/manuspectrum_restore_test_success.prom" \
  && grep -q '^manuspectrum_restore_test_duration_seconds [0-9]' "$TMP/metrics/manuspectrum_restore_test_success.prom" \
  && [ -z "$(find "$TMP/metrics" -name '*.tmp')" ] && [ ! -e "$TMP/metrics/manuspectrum_backup.prom" ]
assert "restore_test metric files written (failed 0, success timestamp, duration), no .tmp, no backup metric touched" $?
clean_dump_dir && no_leak
assert "staging removed; neither fake password appears in output, calls or metrics" $?

run_test -- --snapshot 0123abcd && status=0 || status=$?
[ "$status" -eq 0 ] && restic_subs | head -n 1 | grep -q '^restore 0123abcd '
assert "--snapshot ID restores that snapshot" $?
run_test -- --snapshot 'latest;rm' && status=0 || status=$?
[ "$status" -eq 2 ] && [ ! -s "$TMP/calls" ]
assert "a malformed snapshot id: exit 2, no docker call" $?

# --- failures
failure_case() { # failure_case DESCRIPTION EXPECTED-MESSAGE VAR=value...
  local description="$1" message="$2"
  shift 2
  reset
  printf 'manuspectrum_restore_test_last_success_timestamp_seconds 111\n' >"$TMP/metrics/manuspectrum_restore_test_success.prom"
  run_test "$@" -- && status=0 || status=$?
  [ "$status" -eq 1 ] && grep -q -- "$message" "$TMP/out" \
    && grep -q '^manuspectrum_restore_test_failed 1$' "$TMP/metrics/manuspectrum_restore_test.prom" \
    && [ "$(cat "$TMP/metrics/manuspectrum_restore_test_success.prom")" = "manuspectrum_restore_test_last_success_timestamp_seconds 111" ] \
    && clean_dump_dir && no_leak
  assert "$description: exit 1 ($message), failed 1, success file untouched, staging removed" $?
}

failure_case "count differs" "tiles: expected 9, actual 8" SCRATCH_COUNTS='{"resource_instances": 7, "spatial_ref_sys": 8500, "tiles": 8, "users": 2}'
scratch_dropped_last
assert "count differs: the scratch database is dropped last" $?
failure_case "table missing from the restored database" "users: expected 2, table absent" SCRATCH_COUNTS='{"resource_instances": 7, "spatial_ref_sys": 8500, "tiles": 9}'
failure_case "extension table differs" "spatial_ref_sys: expected 8500, actual 8499" SCRATCH_COUNTS='{"resource_instances": 7, "spatial_ref_sys": 8499, "tiles": 9, "users": 2}'
failure_case "table not in the manifest" "extra: not in the manifest" SCRATCH_COUNTS='{"extra": 1, "resource_instances": 7, "spatial_ref_sys": 8500, "tiles": 9, "users": 2}'

failure_case "checksum mismatch" "do not match manifest.json" STUB_BAD_FILE=1
[ "$(sql_calls)" -eq 0 ]
assert "checksum mismatch: stopped before any SQL" $?

failure_case "pg_restore fatal error" "pg_restore failed" STUB_RESTORE_FATAL=1
scratch_dropped_last
assert "pg_restore fatal: the scratch database is dropped" $?

failure_case "restic check fails" "restic check failed" STUB_RESTIC_FAIL=check
scratch_dropped_last
assert "restic check fails: the scratch database is dropped" $?

failure_case "restic restore fails" "restic restore failed" STUB_RESTIC_FAIL=restore
[ "$(sql_calls)" -eq 0 ]
assert "restic restore fails: no SQL at all, no scratch database to drop" $?

# --- scratch name guard
reset
write_fixture manuspectrum_restoretest
run_test -- && status=0 || status=$?
[ "$status" -eq 2 ] && [ "$(grep -vc 'config --format json' "$TMP/calls")" -eq 0 ]
assert "database already named like a scratch one: exit 2, only the Compose configuration was read" $?
long="$(printf 'd%.0s' $(seq 63))"
write_fixture "$long"
run_test -- && status=0 || status=$?
[ "$status" -eq 2 ] && [ "$(grep -vc 'config --format json' "$TMP/calls")" -eq 0 ]
assert "a 63-character database name (the suffix would be truncated into the live name): exit 2, nothing ran" $?
(
  # shellcheck source=../lib-backup.sh
  # shellcheck source-path=SCRIPTDIR
  source "$LIB"
  [ "$(scratch_database_name manuspectrum)" = manuspectrum_restoretest ] &&
    ! scratch_database_name "$long" >/dev/null && ! scratch_database_name x_restoretest >/dev/null &&
    ! scratch_database_name 'a-b' >/dev/null && ! scratch_database_name '' >/dev/null &&
    [ "$(scratch_database_name "$(printf 'd%.0s' $(seq 51))" | wc -c)" -eq 63 ]
)
assert "scratch_database_name: suffix added; refused for a scratch-like, over-long, non-identifier or empty name" $?

# --- lock
reset
flock -x "$TMP/dump/.lock" sleep 6 &
# shellcheck disable=SC2031
holder=$!
sleep 0.5
run_test BACKUP_LOCK_WAIT=1 -- && status=0 || status=$?
kill "$holder" 2>/dev/null
wait "$holder" 2>/dev/null
[ "$status" -eq 1 ] && grep -q "another backup or restore is running" "$TMP/out" && [ "$(sql_calls)" -eq 0 ] && ! restic_subs | grep -q .
assert "lock held: exit 1 with the message, no restic call, no SQL" $?

# --- configuration refusals
reset
run_test METRICS_TEXTFILE_DIR= -- && status=0 || status=$?
[ "$status" -eq 2 ] && [ ! -s "$TMP/calls" ]
assert "empty METRICS_TEXTFILE_DIR: exit 2, no docker call" $?
run_test METRICS_TEXTFILE_DIR="$TMP/absent" -- && status=0 || status=$?
[ "$status" -eq 2 ] && [ ! -s "$TMP/calls" ]
assert "missing METRICS_TEXTFILE_DIR directory: exit 2, no docker call" $?
run_test -- --bogus && status=0 || status=$?
[ "$status" -eq 2 ] && [ ! -s "$TMP/calls" ]
assert "unknown option: exit 2, no docker call" $?

exit "$failed"
