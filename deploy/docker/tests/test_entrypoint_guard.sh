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

allowed migrate --noinput
allowed packages -o load_package -s pkg -y
allowed packages -o export_graphs -d /tmp/out
allowed es reindex_database --batch_size 500
allowed shell -c "print('setup')"

# The escape hatch stays: anything that is not `manage` is executed as given.
out="$(PATH="$TMP:$PATH" bash "$ENTRYPOINT" python manage.py setup_db 2>&1)"
[ "$out" = "STUB python manage.py setup_db" ]
assert "escape hatch: a bare command runs as given" $?

exit "$failed"
