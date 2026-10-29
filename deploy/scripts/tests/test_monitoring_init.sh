#!/usr/bin/env bash
# deploy/scripts/tests/test_monitoring_init.sh
# Tests of monitoring-init.sh. docker is a stub on PATH that records its argv
# in $TMP/calls and the SQL it reads on stdin in $TMP/sql; nothing real runs.
# The password is random and generated at run time. Prints `ok N` / `not ok N`;
# exits non-zero on failure.
# $? after a negated or compound test is the point of every assertion below.
# shellcheck disable=SC2319
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INIT="$HERE/../monitoring-init.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PW="$(head -c 48 /dev/urandom | base64 -w0 | tr -d '\n=' | tr '/+' 'aB' | head -c 40)"
mkdir -p "$TMP/bin" "$TMP/secrets"
chmod 700 "$TMP/secrets"
printf '%s' "$PW" >"$TMP/secrets/pg_monitor_password"
chmod 444 "$TMP/secrets/pg_monitor_password"
echo "PGDBNAME=manuspectrum" >"$TMP/.env"

cat >"$TMP/bin/docker" <<'STUB'
#!/bin/sh
printf 'docker %s\n' "$*" >>"$CALLS"
case "$*" in
  *"ps --format json"*)
    if [ -n "$STUB_PG_DOWN" ]; then echo '{"Service":"postgres","State":"exited","Health":""}'
    else echo '{"Service":"postgres","State":"running","Health":"healthy"}'; fi ;;
  *"exec -T postgres sh -c"*)
    cat >>"$SQL"
    [ -z "$STUB_PSQL_FAIL" ] || { printf '%s\n' "$STUB_PSQL_FAIL" >&2; exit 3; }
    echo "created ms_monitor"
    echo "pg_stat_statements ready" ;;
esac
exit 0
STUB
chmod +x "$TMP/bin/docker"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

run_init() { # run_init [VAR=value ...]: fresh calls and sql files; output in $TMP/out
  : >"$TMP/calls"
  : >"$TMP/sql"
  env PATH="$TMP/bin:$PATH" CALLS="$TMP/calls" SQL="$TMP/sql" ENV_FILE="$TMP/.env" COMPOSE="docker compose" \
    SECRETS_DIR="$TMP/secrets" POSTGRES_WAIT=1 POSTGRES_WAIT_INTERVAL=0.2 "$@" bash "$INIT" >"$TMP/out" 2>&1
}
put_password() { # put_password VALUE: replaces the 0444 secret file
  rm -f "$TMP/secrets/pg_monitor_password"
  printf '%s' "$1" >"$TMP/secrets/pg_monitor_password"
  chmod 444 "$TMP/secrets/pg_monitor_password"
}
line_of() { grep -n -m1 -- "$1" "$TMP/sql" | cut -d: -f1; }

# --- a normal run
run_init
assert "a run against a healthy postgres succeeds" $?
grep -q 'exec -T postgres sh -c' "$TMP/calls"
assert "the statements go through one psql in the postgres container" $?
grep -q -- '-d postgres' "$TMP/calls"
assert "psql connects to the postgres maintenance database" $?
grep -q -- 'ON_ERROR_STOP=1' "$TMP/calls"
assert "psql stops at the first error" $?
[ "$(head -n 1 "$TMP/sql")" = "\\set pw $PW" ]
assert "the password reaches psql as its first stdin line" $?
! grep -qF -- "$PW" "$TMP/calls"
assert "the password is in no argument" $?
! grep -qF -- "$PW" "$TMP/out"
assert "the password is in neither stdout nor stderr" $?
[ "$(grep -cF -- "$PW" "$TMP/sql")" -eq 1 ]
assert "the password appears once in the SQL, as the \\set line (statements use :'pw')" $?

set_log="$(line_of "SET log_statement = 'none'")"
set_min="$(line_of 'SET log_min_duration_statement = -1')"
set_err="$(line_of 'SET log_min_error_statement = panic')"
set_util="$(line_of 'SET pg_stat_statements.track_utility = off')"
create="$(line_of 'CREATE ROLE ms_monitor')"
alter="$(line_of 'ALTER ROLE ms_monitor')"
grant="$(line_of 'GRANT pg_monitor TO ms_monitor')"
ext="$(line_of 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements')"
check="$(line_of 'FROM pg_stat_statements')"
[ -n "$set_log" ] && [ -n "$set_min" ] && [ -n "$set_err" ] && [ -n "$set_util" ] && [ -n "$create" ] && [ -n "$alter" ]
assert "the SQL holds the log settings and both the create and the alter branch" $?
[ "$set_log" -lt "$create" ] && [ "$set_min" -lt "$create" ] && [ "$set_err" -lt "$create" ] && [ "$set_util" -lt "$create" ] \
  && [ "$set_log" -lt "$alter" ] && [ "$set_util" -lt "$alter" ]
assert "the statement logging and utility tracking are off before the role statements" $?
[ "$create" -lt "$grant" ] && [ "$alter" -lt "$grant" ] && [ "$grant" -lt "$ext" ] && [ "$ext" -lt "$check" ]
assert "the order is role, grant, extension, preload check" $?
grep -q "PASSWORD :'pw'" "$TMP/sql" && [ "$(grep -c "PASSWORD :'pw'" "$TMP/sql")" -eq 2 ]
assert "both role statements take the password from the psql variable" $?
grep -q 'CONNECTION LIMIT 3' "$TMP/sql" && grep -q 'NOSUPERUSER' "$TMP/sql" && grep -q 'NOCREATEDB' "$TMP/sql" && grep -q 'NOCREATEROLE' "$TMP/sql" && grep -q 'NOREPLICATION' "$TMP/sql"
assert "the role has a connection limit of 3 and no privilege of its own" $?
[ "$(grep -c '^GRANT ' "$TMP/sql")" -eq 1 ] && ! grep -qi 'SUPERUSER' <(grep -v NOSUPERUSER "$TMP/sql") && ! grep -qiE 'GRANT (ALL|SELECT|INSERT|UPDATE|DELETE|pg_write|pg_execute|pg_read_server)' "$TMP/sql"
assert "the only grant is pg_monitor" $?
grep -q '^\\if :role_is_new' "$TMP/sql" && grep -q '^\\else' "$TMP/sql" && grep -q '^\\endif' "$TMP/sql"
assert "the create-or-alter is a psql conditional (a second run takes the alter branch)" $?
! grep -qi 'DROP ' "$TMP/sql"
assert "nothing is dropped" $?
cp "$TMP/sql" "$TMP/sql.first"

# --- a second run sends the same statements
run_init
assert "a second run succeeds" $?
cmp -s "$TMP/sql" "$TMP/sql.first"
assert "a second run sends the same statements (the conditional decides, nothing accumulates)" $?

# --- refusals
run_init STUB_PG_DOWN=1
rc=$?
[ "$rc" -ne 0 ] && grep -q 'postgres is not running' "$TMP/out" && [ ! -s "$TMP/sql" ]
assert "a postgres that is down is refused before any statement is sent" $?
! grep -qF -- "$PW" "$TMP/out"
assert "the refusal does not print the password" $?

mv "$TMP/secrets/pg_monitor_password" "$TMP/secrets/pg_monitor_password.keep"
run_init
rc=$?
[ "$rc" -ne 0 ] && grep -q 'pg_monitor_password is missing' "$TMP/out" && [ ! -s "$TMP/sql" ]
assert "a missing secret file is refused" $?
mv "$TMP/secrets/pg_monitor_password.keep" "$TMP/secrets/pg_monitor_password"

for bad in "short" "has space $(printf 'x%.0s' $(seq 1 40))" "quote'$(printf 'x%.0s' $(seq 1 40))" "back\\\\slash$(printf 'x%.0s' $(seq 1 40))"; do
  put_password "$bad"
  run_init
  rc=$?
  [ "$rc" -ne 0 ] && [ ! -s "$TMP/sql" ]
  ok=$?
  assert "a password that is too short or holds a quote, space or backslash is refused ($(printf '%s' "$bad" | head -c 8))" "$ok"
done
put_password "$PW"

run_init SECRETS_DIR=relative/dir
rc=$?
[ "$rc" -eq 2 ] && [ ! -s "$TMP/sql" ]
assert "a relative SECRETS_DIR is refused with status 2" $?

# --- a psql failure
run_init "STUB_PSQL_FAIL=ERROR:  syntax error
LINE 1: CREATE ROLE ms_monitor ... PASSWORD '$PW'"
rc=$?
[ "$rc" -ne 0 ] && grep -q 'could not set up ms_monitor' "$TMP/out"
assert "a psql failure fails the run" $?
! grep -qF -- "$PW" "$TMP/out" && grep -q 'PASSWORD .\*\*\*' "$TMP/out"
assert "the failure output is redacted: the quoted password becomes ***" $?

run_init "STUB_PSQL_FAIL=ERROR:  pg_stat_statements must be loaded via shared_preload_libraries"
rc=$?
[ "$rc" -ne 0 ] && grep -q 'recreate postgres' "$TMP/out"
assert "an extension that is not preloaded says how to fix it" $?

echo "1..$n"
exit "$failed"
