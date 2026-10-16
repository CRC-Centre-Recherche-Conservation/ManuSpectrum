#!/usr/bin/env bash
# deploy/docker/tests/test_entrypoint_guard.sh
# Tests of the `manage` guard of entrypoint.sh. `python` is a stub on PATH that
# only prints its arguments: nothing runs. Prints `ok N` / `not ok N`; exits
# non-zero on failure.
set -uo pipefail
# The python stub drains stdin: an inherited open stdin (a terminal, a background
# job) would block it. Calls that feed a script redirect stdin themselves.
exec </dev/null

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
echo "PYENV $* multiproc=${PROMETHEUS_MULTIPROC_DIR:-unset}" >>"${PYLOG:-/dev/null}"
if [ "$2" = set_admin_password ]; then exit "${ADMIN_STATUS:-0}"; fi
cat >/dev/null
if [ "$2" = database ]; then exit 0; fi
if [ "$2" = settings ] && [ "$SETTINGS_STATUS" -ne 0 ]; then
  echo "entrypoint: OperationalError: connection lost" >&2
  exit "$SETTINGS_STATUS"
fi
echo "STUB python $*"
SH
chmod +x "$TMP/pg_isready" "$TMP/curl" "$TMP/python"

run_web() { # run_web SETTINGS_STATUS [ADMIN_STATUS]
  SETTINGS_STATUS="$1" ADMIN_STATUS="${2:-0}" PATH="$TMP:$PATH" PGHOST=h PGPORT=1 PGUSERNAME=u PGDBNAME=d \
    ESHOST=e ESPORT=1 bash "$ENTRYPOINT" web 2>&1
}

out="$(run_web 2)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'cannot tell whether the Arches system settings exist: .*connection lost; not starting' <<<"$out" \
  && ! grep -qi 'drop the database' <<<"$out"
assert "web: an unanswered settings probe does not suggest dropping the database" $?

out="$(run_web 1)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'drop the database and run make -C deploy init again' <<<"$out"
assert "web: missing system settings suggests the recovery" $?

# The settings exist: web refuses while admin still accepts Arches' default
# password, and does not reach migrate or gunicorn.
out="$(run_web 0 3)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q "the admin account still has Arches' default password: run make -C deploy admin-password" <<<"$out" \
  && ! grep -q 'STUB python manage.py migrate' <<<"$out"
assert "web: refuses to start on the default admin password" $?

out="$(run_web 0 1)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'cannot tell whether the admin account' <<<"$out"
assert "web: refuses when the admin check itself fails" $?

out="$(run_web 0 0)" || true
grep -q 'STUB python manage.py migrate' <<<"$out"
assert "web: a changed or missing admin goes on to migrate" $?

# The Prometheus multiprocess directory is emptied right before gunicorn and the
# Celery worker start, and a missing or read-only one stops the start.
printf '#!/bin/sh\nexit 0\n' >"$TMP/publish-static"
cat >"$TMP/gunicorn" <<'SH'
#!/bin/sh
echo "STUB $(basename "$0") files=$(find "$PROMETHEUS_MULTIPROC_DIR" -mindepth 1 | wc -l | tr -d ' ')"
echo "SERVER $(basename "$0") multiproc=${PROMETHEUS_MULTIPROC_DIR:-unset}" >>"${PYLOG:-/dev/null}"
SH
cp "$TMP/gunicorn" "$TMP/celery"
chmod +x "$TMP/publish-static" "$TMP/gunicorn" "$TMP/celery"
metrics="$TMP/metrics"
mkdir -p "$metrics"

touch "$metrics/counter_1.db" "$metrics/gauge_livesum_2.db"
out="$(PROMETHEUS_MULTIPROC_DIR="$metrics" run_web 0 0)" || true
grep -q 'STUB gunicorn files=0' <<<"$out"
assert "web: the metrics directory is emptied before gunicorn" $?

touch "$metrics/counter_3.db"
out="$(PROMETHEUS_MULTIPROC_DIR="$metrics" PATH="$TMP:$PATH" PGHOST=h PGPORT=1 PGUSERNAME=u \
  ESHOST=e ESPORT=1 bash "$ENTRYPOINT" worker 2>&1)" || true
grep -q 'STUB celery files=0' <<<"$out"
assert "worker: the metrics directory is emptied before celery" $?

# Pre-start Python processes never see the directory; the server does.
: >"$TMP/pylog"
PYLOG="$TMP/pylog" PROMETHEUS_MULTIPROC_DIR="$metrics" run_web 0 0 >/dev/null || true
PYLOG="$TMP/pylog" PROMETHEUS_MULTIPROC_DIR="$metrics" PATH="$TMP:$PATH" PGHOST=h PGPORT=1 PGUSERNAME=u \
  ESHOST=e ESPORT=1 bash "$ENTRYPOINT" worker >/dev/null 2>&1 || true
[ "$(grep -c '^PYENV' "$TMP/pylog")" -ge 4 ] && ! grep '^PYENV' "$TMP/pylog" | grep -qv 'multiproc=unset'
assert "web: every pre-start python call runs without PROMETHEUS_MULTIPROC_DIR" $?
servers="$(grep -c "^SERVER .* multiproc=$metrics\$" "$TMP/pylog")"
[ "$servers" -eq 2 ] && ok=0 || ok=1
assert "web and worker: the server exec keeps PROMETHEUS_MULTIPROC_DIR" "$ok"

# Files the wipe cannot remove do not stop the start.
mkdir -p "$TMP/locked/sub"; touch "$TMP/locked/sub/f"; chmod 555 "$TMP/locked/sub"
if [ "$(id -u)" -ne 0 ]; then
  out="$(PROMETHEUS_MULTIPROC_DIR="$TMP/locked" run_web 0 0)" || true
  grep -q 'STUB gunicorn' <<<"$out" && grep -q 'could not be removed; continuing' <<<"$out"
  assert "web: a file the wipe cannot remove is logged, not fatal" $?
fi
chmod 755 "$TMP/locked/sub"

out="$(PROMETHEUS_MULTIPROC_DIR="$TMP/missing" run_web 0 0)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'PROMETHEUS_MULTIPROC_DIR .* is not a writable directory' <<<"$out" \
  && ! grep -q 'STUB gunicorn' <<<"$out"
assert "web: a missing metrics directory stops the start" $?

exit "$failed"
