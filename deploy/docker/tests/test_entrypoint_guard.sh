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
if [ "$2" = check ]; then echo "CHECK $*" >>"${PYLOG:-/dev/null}"; exit "${CHECK_STATUS:-0}"; fi
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
[ "$(grep -c '^PYENV' "$TMP/pylog")" -ge 5 ] && ! grep '^PYENV' "$TMP/pylog" | grep -qv 'multiproc=unset'
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

# Django's deployment checks come first in web and init and stop the start.
out="$(CHECK_STATUS=1 run_web 0 0)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q "deployment checks failed" <<<"$out" \
  && ! grep -q 'PostgreSQL is up' <<<"$out" \
  && ! grep -q 'STUB python manage.py migrate' <<<"$out" && ! grep -q 'STUB gunicorn' <<<"$out"
assert "deploy-check-web-refuses: a failing check stops web before any wait" $?

out="$(CHECK_STATUS=1 PATH="$TMP:$PATH" PGHOST=h PGPORT=1 PGUSERNAME=u PGDBNAME=d \
  ESHOST=e ESPORT=1 bash "$ENTRYPOINT" init 2>&1)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q "deployment checks failed" <<<"$out" \
  && ! grep -q 'PostgreSQL is up' <<<"$out" && ! grep -q 'setup_db' <<<"$out"
assert "deploy-check-init-refuses: a failing check stops init before setup_db" $?

: >"$TMP/pylog"
PYLOG="$TMP/pylog" PROMETHEUS_MULTIPROC_DIR="$metrics" run_web 0 0 >/dev/null || true
[ "$(grep '^CHECK' "$TMP/pylog")" = "CHECK manage.py check --deploy --tag security --fail-level WARNING" ] \
  && [ "$(grep -c '^CHECK' "$TMP/pylog")" -eq 1 ] \
  && grep -q '^PYENV manage.py check .* multiproc=unset$' "$TMP/pylog"
assert "deploy-check-arguments: exact command, without PROMETHEUS_MULTIPROC_DIR" $?

out="$(CHECK_STATUS=0 run_web 0 0)" || true
grep -q 'STUB python manage.py migrate' <<<"$out"
assert "deploy-check-pass: a clean check goes on to migrate" $?

: >"$TMP/pylog"
out="$(PYLOG="$TMP/pylog" CHECK_STATUS=1 PATH="$TMP:$PATH" bash "$ENTRYPOINT" manage check 2>&1)" || true
grep -q '^CHECK manage.py check$' "$TMP/pylog" && ! grep -q 'deployment checks failed' <<<"$out"
assert "manage check: the guard does not run, the escape hatch stays" $?

# init: the package is loaded after setup_db and the admin password, in a fixed
# order, and the checks that protect the database run before setup_db drops it.
INIT_STUBS="$TMP/init-stubs"; mkdir -p "$INIT_STUBS"
cp "$TMP/pg_isready" "$TMP/curl" "$INIT_STUBS/"
cat >"$INIT_STUBS/python" <<'SH'
#!/bin/sh
if [ "$1" = - ]; then cat >/dev/null; exit "${DB_STATUS:-1}"; fi
echo "$*" >>"$INITLOG"
if [ "$2" = check ]; then exit 0; fi
for failing in $FAIL_ON; do
  case "$*" in *"$failing"*) exit 1 ;; esac
done
exit 0
SH
chmod +x "$INIT_STUBS/python"
PKG="$TMP/pkg"
mkdir -p "$PKG/graphs/resource_models"
: >"$PKG/graphs/resource_models/model.json"
: >"$PKG/expected-inventory.json"

run_init() { # run_init [VAR=value ...]
  : >"$TMP/initlog"
  env INITLOG="$TMP/initlog" PATH="$INIT_STUBS:$PATH" PGHOST=h PGPORT=1 PGUSERNAME=u PGDBNAME=d \
    ESHOST=e ESPORT=1 PKG_MOUNT="$PKG" PUBLIC_SERVER_ADDRESS=https://manuspectrum.test/ "$@" \
    bash "$ENTRYPOINT" init 2>&1
}

out="$(run_init)" && status=0 || status=$?
expected="$(printf '%s\n' \
  'manage.py check --deploy --tag security --fail-level WARNING' \
  'manage.py setup_db --force' \
  'manage.py set_admin_password' \
  "manage.py packages -o load_package -s $PKG -y" \
  'manage.py i18n synclanguages' \
  "manage.py check_pkg_inventory $PKG/expected-inventory.json")"
[ "$status" -eq 0 ] && [ "$(cat "$TMP/initlog")" = "$expected" ] && ok=0 || ok=1
assert "init: setup_db, admin password, load_package, synclanguages, inventory check, in that order" "$ok"

grep -q 'set_controlled_lists_searchable' "$TMP/initlog" && ok=1 || ok=0
assert "init: the lists are not made searchable by the entrypoint (the package's post SQL does it)" "$ok"

grep -q 'load_package.* -db\|--setup_db' "$TMP/initlog" && ok=1 || ok=0
assert "init: load_package runs without -db" "$ok"

mkdir -p "$TMP/empty-pkg"
out="$(run_init PKG_MOUNT="$TMP/empty-pkg")" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'holds no data package' <<<"$out" && grep -q 'git submodule update --init' <<<"$out" \
  && ! grep -q 'setup_db' "$TMP/initlog"
assert "init: an empty package directory is refused before setup_db" $?

out="$(run_init PKG_MOUNT="$TMP/no-such-dir")" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'holds no data package' <<<"$out" && ! grep -q 'setup_db' "$TMP/initlog"
assert "init: a missing package directory is refused before setup_db" $?

mkdir -p "$TMP/half-pkg/graphs/resource_models"
: >"$TMP/half-pkg/graphs/resource_models/model.json"
out="$(run_init PKG_MOUNT="$TMP/half-pkg")" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'holds no data package' <<<"$out" && ! grep -q 'setup_db' "$TMP/initlog"
assert "init: a package without its inventory is refused before setup_db" $?

# Inventory check and origin warning.
out="$(run_init)" && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q 'data package loaded' <<<"$out" && ok=0 || ok=1
assert "init: the inventory check runs last, on the package's own inventory" "$ok"

out="$(run_init FAIL_ON=check_pkg_inventory)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'the loaded database differs from the package inventory' <<<"$out" \
  && ! grep -q 'data package loaded' <<<"$out" && ok=0 || ok=1
assert "init: a failing inventory check fails init" "$ok"

printf '{\n  "public_origin": "https://manuspectrum.test/"\n}\n' >"$PKG/expected-inventory.json"
out="$(run_init)" && status=0 || status=$?
[ "$status" -eq 0 ] && ! grep -q 'WARNING' <<<"$out" && ok=0 || ok=1
assert "init: no warning when the package origin is PUBLIC_SERVER_ADDRESS" "$ok"

printf '{\n  "public_origin": "https://prod.example/"\n}\n' >"$PKG/expected-inventory.json"
out="$(run_init)" && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q 'WARNING: the package was written for https://prod.example/ but PUBLIC_SERVER_ADDRESS is https://manuspectrum.test/.*WITHOUT their sort order' <<<"$out" \
  && grep -q load_package "$TMP/initlog" && ok=0 || ok=1
assert "init: another origin warns loudly and still loads the package" "$ok"
: >"$PKG/expected-inventory.json"

out="$(run_init DB_STATUS=0 PKG_MOUNT="$TMP/empty-pkg")" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'database d exists and setup_db would drop it' <<<"$out"
assert "init: a live database is refused first, whatever the package" $?

out="$(run_init FAIL_ON=load_package)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'load_package failed' <<<"$out" \
  && ! grep -q synclanguages "$TMP/initlog"
assert "init: a failed load_package stops init" $?

out="$(run_init FAIL_ON=synclanguages)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'i18n synclanguages failed' <<<"$out"
assert "init: failed synclanguages stop init" $?

out="$(run_init FAIL_ON=set_admin_password)" && status=0 || status=$?
[ "$status" -eq 1 ] && grep -q 'admin password could not be set' <<<"$out" && ! grep -q load_package "$TMP/initlog"
assert "init: the package is not loaded when the admin password was not set" $?

# Local CA: an empty or missing file changes nothing; a non-empty one yields a
# bundle = certifi + that CA, exported for requests and ssl.
CA_STUBS="$TMP/ca-stubs"; mkdir -p "$CA_STUBS"
printf 'CERTIFI-BUNDLE\n' >"$TMP/certifi.pem"
cat >"$CA_STUBS/python" <<SH
#!/bin/sh
case "\$1" in
  -c) echo "$TMP/certifi.pem" ;;
  *) echo "ENV REQUESTS_CA_BUNDLE=\${REQUESTS_CA_BUNDLE:-unset} SSL_CERT_FILE=\${SSL_CERT_FILE:-unset}" ;;
esac
SH
chmod +x "$CA_STUBS/python"
run_ca() { # run_ca CA-FILE
  PATH="$CA_STUBS:$PATH" CA_CERT_FILE="$1" CA_BUNDLE_FILE="$TMP/bundle.pem" \
    bash "$ENTRYPOINT" manage check 2>&1
}
rm -f "$TMP/bundle.pem"
: >"$TMP/empty-ca.crt"
out="$(run_ca "$TMP/empty-ca.crt")"
[ "$out" = "ENV REQUESTS_CA_BUNDLE=unset SSL_CERT_FILE=unset" ] && [ ! -e "$TMP/bundle.pem" ] && ok=0 || ok=1
assert "local CA: an empty file adds nothing" "$ok"
out="$(run_ca "$TMP/missing-ca.crt")"
[ "$out" = "ENV REQUESTS_CA_BUNDLE=unset SSL_CERT_FILE=unset" ] && ok=0 || ok=1
assert "local CA: a missing file adds nothing" "$ok"
printf 'LOCAL-CA\n' >"$TMP/ca.crt"
out="$(run_ca "$TMP/ca.crt")"
grep -q "ENV REQUESTS_CA_BUNDLE=$TMP/bundle.pem SSL_CERT_FILE=$TMP/bundle.pem" <<<"$out"
assert "local CA: a file exports the bundle for requests and ssl" $?
grep -q CERTIFI-BUNDLE "$TMP/bundle.pem" && grep -q LOCAL-CA "$TMP/bundle.pem"
assert "local CA: the bundle is certifi plus the CA" $?

exit "$failed"
