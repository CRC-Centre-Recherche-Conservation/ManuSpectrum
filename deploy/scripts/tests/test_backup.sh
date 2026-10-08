#!/usr/bin/env bash
# deploy/scripts/tests/test_backup.sh
# Tests of backup.sh and lib-backup.sh. docker is a stub on PATH that records
# its calls in $TMP/calls (psql statements included, in the order they are
# read); nothing real runs. Prints `ok N` / `not ok N`; exits non-zero on
# failure.
# $? after a negated or compound test is the point of every assertion below.
# shellcheck disable=SC2319
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP="$HERE/../backup.sh"
LIB="$HERE/../lib-backup.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

UID_NOW="$(id -u)"
GID_NOW="$(id -g)"
PW_RESTIC="$(head -c 36 /dev/urandom | base64 | tr -d '\n=+/')"
PW_PG="$(head -c 36 /dev/urandom | base64 | tr -d '\n=+/')"
export COUNTS_JSON='{"resource_instances": 7, "tiles": 9, "users": 2}'
export MIGRATIONS_JSON='{"arches": "0001_initial", "manuspectrum": "0005_sample"}'
export SNAPSHOT_ID="00000003-1"

mkdir -p "$TMP/bin" "$TMP/secrets" "$TMP/metrics"
printf '%s' "$PW_RESTIC" >"$TMP/secrets/restic_password"
printf '%s' "$PW_PG" >"$TMP/secrets/pg_password"
echo "PGDBNAME=manuspectrum" >"$TMP/.env"

write_fixture() { # media, repository, dump directory and the Compose configuration
  rm -rf "${TMP:?}/media" "${TMP:?}/repo" "${TMP:?}/dump"
  mkdir -p "$TMP/media/uploadedfiles/a" "$TMP/repo" "$TMP/dump/latest" "$TMP/dump/tmp"
  printf 'abcde' >"$TMP/media/uploadedfiles/a/one.txt"
  printf 'xyz' >"$TMP/media/uploadedfiles/two.txt"
  python3 - "$TMP" "$UID_NOW" "$GID_NOW" "${1:-$TMP/repo}" <<'PY'
import json
import sys

tmp, uid, gid, repo = sys.argv[1:5]
json.dump({"services": {
    "web": {"user": f"{uid}:{gid}", "image": "manuspectrum:test",
            "environment": {"PGDBNAME": "manuspectrum"},
            "volumes": [{"type": "bind", "source": f"{tmp}/media", "target": "/srv/media"}]},
    "postgres": {"environment": {"POSTGRES_USER": "postgres"}},
    "restic": {"volumes": [
        {"type": "bind", "source": repo, "target": "/repo"},
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
  *"ps --format json"*)
    polls="$(cat "$TMP/pgpolls" 2>/dev/null || echo 0)"
    echo $((polls + 1)) >"$TMP/pgpolls"
    if [ -n "$STUB_PG_DOWN" ]; then echo '{"Service":"postgres","State":"exited","Health":""}'
    elif [ "$polls" -lt "${STUB_PG_STARTING_POLLS:-0}" ]; then echo '{"Service":"postgres","State":"running","Health":"starting"}'
    else echo '{"Service":"postgres","State":"running","Health":"healthy"}'; fi ;;
  *"exec -T postgres psql"*)
    while IFS= read -r line; do
      printf 'psql< %s\n' "$line" >>"$CALLS"
      case "$line" in
        *pg_export_snapshot*) echo "$SNAPSHOT_ID" ;;
        *query_to_xml*) echo "$COUNTS_JSON" ;;
        *django_migrations*) echo "$MIGRATIONS_JSON" ;;
        '\echo '*) printf '%s\n' "${line#\\echo }" ;;
        '\q') exit 0 ;;
      esac
    done ;;
  *"pg_dump --version"*) echo "pg_dump (PostgreSQL) 17.2" ;;
  *"exec -T postgres pg_dump "*)
    [ -z "$STUB_DUMP_FAIL" ] || { echo "pg_dump: error: stub failure" >&2; exit 1; }
    [ -z "$STUB_DUMP_BLOCK" ] || { touch "$TMP/blocked"; exec sleep 30; }
    [ -z "$STUB_DUMP_EMPTY" ] || exit 0
    printf PGDUMP ;;
  *"pg_restore --list"*)
    cat >/dev/null
    echo "4562; 0 16403 TABLE DATA public resource_instances postgres"
    [ -n "$STUB_LIST_BAD" ] || echo "4563; 0 16404 TABLE DATA public tiles postgres" ;;
  *"pg_dumpall"*)
    [ -n "$STUB_GLOBALS_EMPTY" ] || echo "CREATE ROLE postgres;" ;;
  *" restic --no-cache"*)
    sub="${*#*--retry-lock 30m }"
    sub="${sub%% *}"
    [ "$STUB_RESTIC_FAIL" != "$sub" ] || { echo "restic: stub failure" >&2; exit 1; }
    [ "$STUB_RESTIC_BLOCK" != "$sub" ] || { touch "$TMP/blocked"; exec sleep 30; } ;;
  *"python -c"*) echo "noise"; echo "8.1.4" ;;
esac
exit 0
STUB
cat >"$TMP/bin/rm" <<'STUB'
#!/bin/sh
case "$*" in *"/.new-"*) [ -z "$STUB_RM_SLOW" ] || { touch "$TMP/cleaning"; sleep 1; } ;; esac
exec /bin/rm "$@"
STUB
chmod +x "$TMP/bin/docker" "$TMP/bin/rm"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

run_backup() { # run_backup [VAR=value ...] -- [ARGS...]: fresh calls file; output in $TMP/out
  local envs=()
  while [ "$#" -gt 0 ] && [ "$1" != -- ]; do envs+=("$1"); shift; done
  [ "$#" -eq 0 ] || shift
  : >"$TMP/calls"
  rm -f "$TMP/pgpolls"
  env PATH="$TMP/bin:$PATH" TMP="$TMP" CALLS="$TMP/calls" ENV_FILE="$TMP/.env" COMPOSE="docker compose" \
    METRICS_TEXTFILE_DIR="$TMP/metrics" BACKUP_LOCK_WAIT=2 POSTGRES_WAIT=1 POSTGRES_WAIT_INTERVAL=0.2 \
    "${envs[@]}" bash "$BACKUP" "$@" >"$TMP/out" 2>&1
}
run_backup_signalled() { # run_backup_signalled SIGNAL: the run is blocked in restic backup when SIGNAL reaches its process group
  : >"$TMP/calls"
  rm -f "$TMP/pgpolls" "$TMP/blocked"
  setsid env PATH="$TMP/bin:$PATH" TMP="$TMP" CALLS="$TMP/calls" ENV_FILE="$TMP/.env" COMPOSE="docker compose" \
    METRICS_TEXTFILE_DIR="$TMP/metrics" BACKUP_LOCK_WAIT=2 STUB_RESTIC_BLOCK=backup bash "$BACKUP" --tag nightly >"$TMP/out" 2>&1 &
  local pid=$! waited=0
  while [ ! -e "$TMP/blocked" ] && [ "$waited" -lt 100 ]; do sleep 0.1; waited=$((waited + 1)); done
  kill -"$1" -- "-$pid"
  wait "$pid"
}
restic_calls() { grep -c ' restic --no-cache' "$TMP/calls"; }
tree_sum() { (cd "$1" && find . | sort && find . -type f | sort | xargs -r sha256sum) | sha256sum; }
no_leak() {
  ! grep -rqF -e "$PW_RESTIC" -e "$PW_PG" "$TMP/out" "$TMP/calls" "$TMP/dump" "$TMP/metrics" 2>/dev/null
}
reset() { write_fixture; rm -rf "${TMP:?}/metrics"; mkdir -p "$TMP/metrics"; }

# --- nightly run
reset
run_backup -- --tag nightly && status=0 || status=$?
L="$TMP/dump/latest"
files_private() { local f; for f in db.dump globals.sql manifest.json env; do [ -f "$L/$f" ] && [ "$(stat -c %a "$L/$f")" = 600 ] || return 1; done; }
[ "$status" -eq 0 ] && [ "$(stat -c %a "$L")" = 700 ] && files_private
assert "nightly: exit 0, latest/ is 0700 with db.dump, globals.sql, manifest.json and env at 0600" $?

python3 - "$L" "$COUNTS_JSON" "$MIGRATIONS_JSON" "$TMP/media" <<'PY'
import hashlib
import json
import sys

latest, counts, migrations = sys.argv[1:4]
m = json.load(open(f"{latest}/manifest.json"))
assert m["kind"] == "backup" and m["tag"] == "nightly", m
assert m["counts"] == json.loads(counts) and m["migrations"] == json.loads(migrations), m
assert m["arches_version"] == "8.1.4" and m["image"] == "manuspectrum:test", m
assert m["pg_dump_version"].startswith("pg_dump"), m
assert m["media"] == {"files": 2, "bytes": 8}, m["media"]
assert m["created_at"].endswith("Z"), m
for name in ("db.dump", "globals.sql", "env"):
    data = open(f"{latest}/{name}", "rb").read()
    assert m["files"][name] == {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}, name
PY
assert "nightly: manifest holds tag, counts, migrations, versions, media summary and the checksums of the files" $?

python3 - "$TMP/calls" <<'PY'
import sys

calls = [line.rstrip("\n") for line in open(sys.argv[1])]
restic = [c for c in calls if " restic --no-cache --retry-lock 30m " in c]
sub = [c.split("--retry-lock 30m ", 1)[1] for c in restic]
assert [s.split()[0] for s in sub] == ["backup", "forget", "check"], sub
backup = sub[0].split()
assert backup[backup.index("--tag") + 1] == "nightly", sub[0]
excludes = [backup[i + 1] for i, w in enumerate(backup) if w == "--exclude"]
assert excludes == ["/backup/media/previous-*", "/backup/media/.restore-*", "/backup/media/archestemp",
                    "/backup/media/export_deliverables", "/backup/secrets/*.new", "/backup/secrets/aside",
                    "/backup/secrets/restic_password"], excludes
assert backup[-1] == "/backup", backup
assert sub[1] == "forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune", sub[1]
assert sub[2] == "check", sub[2]
PY
assert "nightly: restic backup (tag, seven excludes, /backup), then forget 7/4/6 --prune, then check" $?

grep -q '^manuspectrum_backup_failed 0$' "$TMP/metrics/manuspectrum_backup.prom" \
  && grep -q '^manuspectrum_backup_last_attempt_timestamp_seconds [0-9]' "$TMP/metrics/manuspectrum_backup.prom" \
  && grep -q '^manuspectrum_backup_last_success_timestamp_seconds [0-9]' "$TMP/metrics/manuspectrum_backup_success.prom" \
  && grep -q '^manuspectrum_backup_duration_seconds [0-9]' "$TMP/metrics/manuspectrum_backup_success.prom" \
  && grep -q '^manuspectrum_backup_dump_bytes 6$' "$TMP/metrics/manuspectrum_backup_success.prom" \
  && [ "$(stat -c %a "$TMP/metrics/manuspectrum_backup.prom")" = 644 ] \
  && [ -z "$(find "$TMP/metrics" -name '*.tmp')" ]
assert "nightly: both metric files written (failed 0, success timestamp, duration, dump bytes), 0644, no .tmp left" $?

[ -z "$(find "$TMP/dump" -maxdepth 1 -name '.new-*')" ]
assert "nightly: no .new-* directory left" $?
no_leak
assert "nightly: neither fake password appears in output, calls, dump directory or metrics" $?

# --- one snapshot for the counts and the dump
awk '
  /^psql< BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY/ { begin = NR }
  /^psql< .*pg_export_snapshot\(\)/ { export = NR }
  /^psql< .*query_to_xml/ { counts = NR }
  /^psql< .*django_migrations/ { migrations = NR }
  /pg_dump .*--snapshot=00000003-1/ { dump = NR }
  /^psql< COMMIT/ { commit = NR }
  END { exit !(begin && begin < export && export < counts && export < migrations && counts < dump && migrations < dump && dump < commit) }
' "$TMP/calls"
assert "same snapshot: REPEATABLE READ, export, counts and migrations, pg_dump --snapshot=<id>, then COMMIT" $?

# --- manual tag
reset
run_backup -- --tag manual && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q ' restic --no-cache --retry-lock 30m backup ' "$TMP/calls" \
  && ! grep -qE ' restic .* (forget|check)( |$)' "$TMP/calls"
assert "manual tag: backup only, no forget, no check" $?
run_backup && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q '"tag": "manual"' "$TMP/dump/latest/manifest.json"
assert "default tag is manual" $?
run_backup -- --tag bogus && status=0 || status=$?
[ "$status" -eq 2 ] && [ "$(wc -l <"$TMP/calls")" -eq 0 ]
assert "unknown tag: exit 2 before any docker call" $?

# --- rotation
reset
run_backup -- --tag manual
first="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["created_at"])' "$TMP/dump/latest/manifest.json")"
first_sum="$(sha256sum <"$TMP/dump/latest/manifest.json")"
sleep 1
run_backup -- --tag nightly
[ "$(sha256sum <"$TMP/dump/previous/manifest.json")" = "$first_sum" ] \
  && grep -q '"tag": "nightly"' "$TMP/dump/latest/manifest.json" && [ -n "$first" ]
assert "rotation: previous/ holds the first run, latest/ the second" $?
run_backup -- --tag manual
[ "$(find "$TMP/dump" -mindepth 1 -maxdepth 1 -not -name '.*' -printf '%f\n' | sort | tr '\n' ' ')" = "latest previous tmp " ]
assert "rotation: two generations only" $?

# --- failures before anything is rotated or pushed
# prepare: one good backup, a marker success metric
failure_case() { # failure_case DESCRIPTION VAR=value [expected-message]
  reset
  run_backup -- --tag manual
  local before success
  before="$(tree_sum "$TMP/dump/latest")"
  printf 'manuspectrum_backup_last_success_timestamp_seconds 111\n' >"$TMP/metrics/manuspectrum_backup_success.prom"
  success="$(cat "$TMP/metrics/manuspectrum_backup_success.prom")"
  run_backup "$2" -- --tag nightly && status=0 || status=$?
  [ "$status" -eq 1 ] && [ "$(restic_calls)" -eq 0 ] && [ "$(tree_sum "$TMP/dump/latest")" = "$before" ] \
    && [ ! -d "$TMP/dump/previous" ] \
    && grep -q '^manuspectrum_backup_failed 1$' "$TMP/metrics/manuspectrum_backup.prom" \
    && [ "$(cat "$TMP/metrics/manuspectrum_backup_success.prom")" = "$success" ] \
    && [ -z "$(find "$TMP/dump" -maxdepth 1 -name '.new-*')" ] && no_leak
  assert "$1: exit 1, no restic call, latest/ unchanged, failed 1, success file untouched, no .new-*" $?
}
failure_case "pg_dump fails" STUB_DUMP_FAIL=1
failure_case "empty dump" STUB_DUMP_EMPTY=1
failure_case "dump without the two TABLE DATA entries" STUB_LIST_BAD=1
failure_case "empty globals.sql" STUB_GLOBALS_EMPTY=1
failure_case "postgres not running" STUB_PG_DOWN=1

# --- postgres still coming up (catch-up at boot)
reset
run_backup STUB_PG_STARTING_POLLS=2 -- --tag manual && status=0 || status=$?
[ "$status" -eq 0 ] && [ "$(cat "$TMP/pgpolls")" -eq 3 ] && [ -f "$TMP/dump/latest/manifest.json" ]
assert "postgres starting then healthy: the run waits and succeeds" $?
failure_case "postgres never becomes healthy within POSTGRES_WAIT" STUB_PG_STARTING_POLLS=9999
grep -q "after 1s" "$TMP/out"
assert "postgres never healthy: the refusal names the wait" $?

# --- a run stopped by a signal records a failure
signal_case() { # signal_case SIGNAL EXPECTED-STATUS
  reset
  printf 'manuspectrum_backup_last_success_timestamp_seconds 111\n' >"$TMP/metrics/manuspectrum_backup_success.prom"
  run_backup_signalled "$1" && status=0 || status=$?
  [ "$status" -eq "$2" ] \
    && grep -q '^manuspectrum_backup_failed 1$' "$TMP/metrics/manuspectrum_backup.prom" \
    && [ "$(cat "$TMP/metrics/manuspectrum_backup_success.prom")" = "manuspectrum_backup_last_success_timestamp_seconds 111" ] \
    && [ -z "$(find "$TMP/dump" -maxdepth 1 -name '.new-*')" ]
  assert "$1 while blocked in restic: exit $2, failed 1 written, success file untouched" $?
}
signal_case TERM 143
signal_case HUP 129

# --- the psql session ends by EOF, not by a command
reset
run_backup -- --tag manual
! grep -q '^psql< .q$' "$TMP/calls" && grep -q '^psql< COMMIT' "$TMP/calls"
assert "the psql coprocess is closed by EOF, no \\q is sent" $?

# --- restic fails: copy A is already good
reset
run_backup STUB_RESTIC_FAIL=backup -- --tag nightly && status=0 || status=$?
[ "$status" -eq 1 ] && [ -f "$TMP/dump/latest/manifest.json" ] \
  && grep -q '^manuspectrum_backup_failed 1$' "$TMP/metrics/manuspectrum_backup.prom" \
  && [ ! -e "$TMP/metrics/manuspectrum_backup_success.prom" ] \
  && ! grep -qE ' restic .* (forget|check)( |$)' "$TMP/calls"
assert "restic backup fails: exit 1, latest/ rotated and kept, failed 1, no forget" $?
run_backup STUB_RESTIC_FAIL=forget -- --tag nightly && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q '^manuspectrum_backup_failed 1$' "$TMP/metrics/manuspectrum_backup.prom" \
  && [ ! -e "$TMP/metrics/manuspectrum_backup_success.prom" ]
assert "restic forget fails: exit 1, failed 1, no success file" $?

# --- lock
reset
flock -x "$TMP/dump/.lock" sleep 6 &
holder=$!
sleep 0.5
run_backup BACKUP_LOCK_WAIT=1 -- --tag manual && status=0 || status=$?
kill "$holder" 2>/dev/null
wait "$holder" 2>/dev/null
[ "$status" -eq 1 ] && grep -q "another backup or restore is running" "$TMP/out" && [ "$(restic_calls)" -eq 0 ]
assert "lock held: exit 1 with the message after the wait, no restic call" $?

# --- configuration refusals
reset
run_backup METRICS_TEXTFILE_DIR= -- --tag manual && status=0 || status=$?
[ "$status" -eq 2 ] && [ ! -s "$TMP/calls" ]
assert "empty METRICS_TEXTFILE_DIR: exit 2, no docker call" $?
run_backup METRICS_TEXTFILE_DIR=relative/dir -- --tag manual && status=0 || status=$?
[ "$status" -eq 2 ] && [ ! -s "$TMP/calls" ]
assert "relative METRICS_TEXTFILE_DIR: exit 2, no docker call" $?
run_backup METRICS_TEXTFILE_DIR="$TMP/absent" -- --tag manual && status=0 || status=$?
[ "$status" -eq 2 ] && [ ! -s "$TMP/calls" ]
assert "missing METRICS_TEXTFILE_DIR directory: exit 2, no docker call" $?

# --- the directories the restic service binds
missing_dirs_case() { # missing_dirs_case DESCRIPTION MISSING-DIR [ARGS...]
  local description="$1" dir="$2"
  shift 2
  reset
  rmdir "$TMP/dump/$dir"
  run_backup -- "$@" && status=0 || status=$?
  [ "$status" -eq 1 ] && grep -qF "$TMP/dump/$dir is missing (the restic service binds it): run make -C deploy backup-init" "$TMP/out" \
    && ! grep -qE 'exec -T|run --rm|restic' "$TMP/calls" && [ -z "$(find "$TMP/dump" -maxdepth 1 -name '.new-*')" ]
  assert "$description: exit 1 with the backup-init hint, no docker exec or run, no restic call" $?
}
missing_dirs_case "missing tmp/" tmp --tag nightly
missing_dirs_case "missing latest/" latest --tag nightly
missing_dirs_case "--restic with a missing tmp/" tmp --restic snapshots
reset
rmdir "$TMP/dump/tmp"
run_backup -- --tag nightly
grep -q '^manuspectrum_backup_failed 1$' "$TMP/metrics/manuspectrum_backup.prom" && [ ! -d "$TMP/dump/previous" ]
assert "missing tmp/: failed 1 written, no rotation" $?

# --- a second signal does not cut the cleanup short
reset
: >"$TMP/calls"
rm -f "$TMP/blocked" "$TMP/cleaning"
setsid env PATH="$TMP/bin:$PATH" TMP="$TMP" CALLS="$TMP/calls" ENV_FILE="$TMP/.env" COMPOSE="docker compose" \
  METRICS_TEXTFILE_DIR="$TMP/metrics" BACKUP_LOCK_WAIT=2 STUB_DUMP_BLOCK=1 STUB_RM_SLOW=1 bash "$BACKUP" --tag manual >"$TMP/out" 2>&1 &
pid=$!
waited=0
while [ ! -e "$TMP/blocked" ] && [ "$waited" -lt 100 ]; do sleep 0.1; waited=$((waited + 1)); done
kill -TERM -- "-$pid"
waited=0
while [ ! -e "$TMP/cleaning" ] && [ "$waited" -lt 100 ]; do sleep 0.05; waited=$((waited + 1)); done
kill -TERM "$pid"
wait "$pid" && status=0 || status=$?
[ "$status" -eq 143 ] && grep -q '^manuspectrum_backup_failed 1$' "$TMP/metrics/manuspectrum_backup.prom" \
  && [ -z "$(find "$TMP/dump" -maxdepth 1 -name '.new-*')" ]
assert "a second TERM during the cleanup: exit 143, the staging directory is removed and failed 1 is still written" $?

# --- backup-init (backup.sh --init)
reset
rmdir "$TMP/dump/latest" "$TMP/dump/tmp"
run_backup -- --init && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q ' restic --no-cache --retry-lock 30m init$' "$TMP/calls" \
  && [ -d "$TMP/dump/latest" ] && [ "$(stat -c %a "$TMP/dump/latest")" = 700 ] \
  && [ -d "$TMP/dump/tmp" ] && [ "$(stat -c %a "$TMP/dump/tmp")" = 700 ] && grep -q "vault" "$TMP/out" && no_leak
assert "init on a new repository: restic init, latest/ and tmp/ made 0700 for the bind mounts, vault reminder" $?
touch "$TMP/repo/config"
run_backup -- --init && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q ' restic --no-cache --retry-lock 30m cat config$' "$TMP/calls" \
  && ! grep -q ' restic .* init$' "$TMP/calls" && grep -q "repository exists and opens" "$TMP/out"
assert "init on an existing repository: opens it with cat config, no init (idempotent)" $?
run_backup STUB_RESTIC_FAIL=cat -- --init && status=0 || status=$?
[ "$status" -eq 1 ]
assert "init on an existing repository that does not open: exit 1" $?
write_fixture "$TMP/no-such-repo"
run_backup -- --init && status=0 || status=$?
[ "$status" -eq 1 ] && ! grep -q ' restic ' "$TMP/calls"
assert "init refused when the repository directory does not exist, restic not run" $?

# --- make restic
reset
run_backup -- --restic snapshots --json && status=0 || status=$?
[ "$status" -eq 0 ] && grep -qE ' run --rm --no-deps restic --no-cache --retry-lock 30m snapshots --json$' "$TMP/calls"
assert "--restic: interactive restic run (no -T) with the given arguments" $?

# --- library: metrics writer and constants
(
  # shellcheck source=../lib-backup.sh
  # shellcheck source-path=SCRIPTDIR
  source "$LIB"
  f="$TMP/m.prom"
  write_metrics "$f" manuspectrum_a_total 3 manuspectrum_b 1.5 &&
    grep -q '^manuspectrum_a_total 3$' "$f" && grep -q '^# TYPE manuspectrum_b gauge$' "$f" && [ ! -e "$f.tmp" ] &&
    ! write_metrics "$f" bad_name 1 && ! write_metrics "$f" 'manuspectrum_x' 'a b' &&
    [ "$RETENTION_KEEP_DAILY $RETENTION_KEEP_WEEKLY $RETENTION_KEEP_MONTHLY" = "7 4 6" ]
)
assert "write_metrics accepts manuspectrum_* names with numeric values only; retention is 7/4/6" $?

exit "$failed"
