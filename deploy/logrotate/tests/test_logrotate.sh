#!/usr/bin/env bash
# deploy/logrotate/tests/test_logrotate.sh
# Renders manuspectrum-nginx.in and runs it through logrotate in a pinned Debian
# container (network needed once for apt). Prints `ok N` / `not ok N`; exits
# non-zero on failure.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$HERE/../manuspectrum-nginx.in"
IMAGE="debian:12-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
LOGS="$TMP/logs" # same path inside the container
mkdir -p "$LOGS" "$TMP/bin"
chmod 0755 "$TMP"

sed -e "s|@NGINX_LOG_HOST_DIR@|$LOGS|g" -e 's|@APP_USER@|nobody|g' \
  -e 's|@APP_GROUP@|nogroup|g' "$TEMPLATE" >"$TMP/rendered.conf"
chmod 0644 "$TMP/rendered.conf"
printf 'a line\n' >"$LOGS/access.log"
printf 'an error\n' >"$LOGS/error.log"

cat >"$TMP/bin/docker" <<'STUB'
#!/bin/sh
echo "docker $*" >>"$CALLS"
[ "$1" = ps ] && echo abc123
exit 0
STUB
chmod +x "$TMP/bin/docker"
chmod 0750 "$LOGS"
chown 65534:65534 "$LOGS" 2>/dev/null || true

# shellcheck disable=SC2016 # expanded inside the container
INNER='
set -e
apt-get update -qq >/dev/null
apt-get install -y -qq logrotate >/dev/null 2>&1
chown -R nobody:nogroup "$LOGS"
chown root:root "$TMP/rendered.conf"
export CALLS="$TMP/calls" PATH="$TMP/bin:$PATH"
logrotate -d "$TMP/rendered.conf" >"$TMP/debug.out" 2>&1 && echo debug-ok >"$TMP/debug.status"
logrotate -f -s "$TMP/state" "$TMP/rendered.conf" >"$TMP/run.out" 2>&1 && echo run-ok >"$TMP/run.status"
stat -c "%a %U" "$LOGS/access.log" >"$TMP/mode"
chown -R "$HOST_UID:$HOST_GID" "$TMP"
'
docker run --rm -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" -e LOGS="$LOGS" -e TMP="$TMP" -v "$TMP:$TMP" "$IMAGE" bash -c "$INNER" >"$TMP/docker.out" 2>&1 || cat "$TMP/docker.out"

grep -q debug-ok "$TMP/debug.status" 2>/dev/null && grep -q "Handling 1 logs" "$TMP/debug.out"
assert "logrotate -d accepts the rendered file" "$?"

grep -q run-ok "$TMP/run.status" 2>/dev/null && ! grep -qi "^error" "$TMP/run.out"
assert "a forced rotation succeeds" "$?"

stamp="$(date +%Y%m%d)"
for f in access error; do
  [ -f "$LOGS/$f.log-$stamp" ] && [ ! -e "$LOGS/$f.log-$stamp.gz" ] && [ -f "$LOGS/$f.log" ] && [ ! -s "$LOGS/$f.log" ]
  # shellcheck disable=SC2319 # $? is the status of the whole && list above
  assert "$f.log is rotated to a dated, still uncompressed file and recreated empty" "$?"
done

[ "$(cat "$TMP/mode" 2>/dev/null)" = "640 nobody" ]
# shellcheck disable=SC2319 # $? is the status of the test above
assert "the new log is created 0640 for the service account" "$?"

[ "$(grep -c '^docker kill' "$TMP/calls" 2>/dev/null)" = 1 ] \
  && grep -qx 'docker kill --signal USR1 abc123' "$TMP/calls"
assert "postrotate runs once and sends USR1 to the selected container" "$?"

grep -q 'label=com.docker.compose.project=manuspectrum' "$TMP/calls" \
  && grep -q 'label=com.docker.compose.service=nginx' "$TMP/calls"
assert "the container is selected by the two Compose labels" "$?"

grep -qE '^rotate 30|^ +rotate 30' "$TEMPLATE" && grep -qE '^ +maxage 30' "$TEMPLATE"
assert "retention is 30 days" "$?"

exit "$failed"
