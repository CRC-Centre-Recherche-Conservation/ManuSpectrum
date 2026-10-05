#!/usr/bin/env bash
# deploy/docker/tests/test_entrypoint_guard.sh
# Tests of the `manage` guard of entrypoint.sh. `python` is a stub on PATH that
# only prints its arguments: nothing runs. Prints `ok N` / `not ok N`; exits
# non-zero on failure.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTRYPOINT="$HERE/../entrypoint.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf '#!/bin/sh\necho "STUB python $*"\n' >"$TMP/python"
chmod +x "$TMP/python"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

run_manage() { PATH="$TMP:$PATH" bash "$ENTRYPOINT" manage "$@" 2>&1; }

refused() { # refused ARGS...
  local out status
  out="$(run_manage "$@")" && status=0 || status=$?
  [ "$status" -eq 1 ] && grep -q '^entrypoint: refusing: .*make -C deploy init' <<<"$out" \
    && ! grep -q STUB <<<"$out"
  assert "refused: manage $*" $?
}

allowed() { # allowed ARGS...
  local out status
  out="$(run_manage "$@")" && status=0 || status=$?
  [ "$status" -eq 0 ] && [ "$out" = "STUB python manage.py $*" ]
  assert "allowed: manage $*" $?
}

refused setup_db
refused setup_db --force
refused --settings=x setup_db
refused packages -o load_package -s pkg -db -y
refused packages -o load_package -s pkg --setup_db -y
refused packages -o load_package --setup_db
refused packages -o setup
refused packages --operation setup
refused packages --operation=setup
refused packages -o=setup
refused packages -osetup
refused packages -y -o setup -s pkg
for abbreviation in --set --setu --setup --setup_ --setup_d --setup_db; do
  refused packages -o load_package "$abbreviation"
  refused packages -o load_package "${abbreviation}=x"
done

allowed migrate --noinput
allowed packages -o load_package -s pkg -y
allowed packages -o export_graphs -d /tmp/out
allowed es reindex_database --batch_size 500
allowed packages -o load_package -s pkg --settings=x
allowed packages -o load_package --se
allowed shell -c "print('setup')"

# The escape hatch stays: anything that is not `manage` is executed as given.
out="$(PATH="$TMP:$PATH" bash "$ENTRYPOINT" python manage.py setup_db 2>&1)"
[ "$out" = "STUB python manage.py setup_db" ] && ok=0 || ok=1
assert "escape hatch: a bare command runs as given" "$ok"

# `web` with a probe that cannot answer: its own message, never the advice to
# drop the database. The stubs answer pg_isready, curl and the two probes.
cat >"$TMP/pg_isready" <<'SH'
#!/bin/sh
exit 0
SH
cp "$TMP/pg_isready" "$TMP/curl"
cat >"$TMP/python" <<'SH'
#!/bin/sh
cat >/dev/null
if [ "$2" = database ]; then exit 0; fi
echo "entrypoint: OperationalError: connection lost" >&2
exit "$SETTINGS_STATUS"
SH
chmod +x "$TMP/pg_isready" "$TMP/curl" "$TMP/python"

run_web() { # run_web SETTINGS_STATUS
  SETTINGS_STATUS="$1" PATH="$TMP:$PATH" PGHOST=h PGPORT=1 PGUSERNAME=u PGDBNAME=d \
    ESHOST=e ESPORT=1 bash "$ENTRYPOINT" web 2>&1
}

out="$(run_web 2)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'cannot tell whether the Arches system settings exist: .*connection lost; not starting' <<<"$out" \
  && ! grep -qi 'drop the database' <<<"$out"
assert "web: an unanswered settings probe does not suggest dropping the database" $?

out="$(run_web 1)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'drop the database and run make -C deploy init again' <<<"$out"
assert "web: missing system settings suggests the recovery" $?

exit "$failed"
