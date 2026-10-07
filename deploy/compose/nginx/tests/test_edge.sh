#!/usr/bin/env bash
# deploy/compose/nginx/tests/test_edge.sh
# Offline tests of the edge nginx: the pinned image, mounted as Compose mounts
# it, in front of two Python stubs (aliases `web` and `cantaloupe`) on a
# throwaway Docker network. Needs docker, curl, openssl >= 3 and python3 on the
# host; builds nothing, publishes ports on 127.0.0.1 only.
#
#   test_edge.sh            run every group
#   test_edge.sh tls static run the named groups
#
# Prints `ok N - ...` / `not ok N - ...`; exits non-zero on a failure.
# One function per case group, named group_<name>, listed in GROUPS: a new
# group is a new function plus its name in GROUPS.
# shellcheck disable=SC2317,SC2016  # group_* run by name; bash -c bodies are single-quoted on purpose
set -uo pipefail
exec </dev/null

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
NGINX_DIR="${NGINX_DIR:-$(cd "$HERE/.." && pwd)}" # a mutated copy of the configuration, to see a case fail

NGINX_IMAGE="nginxinc/nginx-unprivileged:1.30.5-alpine@sha256:15c994d10d6d78658721c3bcafff14cb281fba2a4bdf9d5ba92c416a472516e3"
PYTHON_IMAGE="python:3.13-slim-trixie@sha256:7c61056e61ac89e852de05f3dc6fa51a6dd2181797bceed46aa725dd7cb2cd3b"
HOST="manuspectrum.test"
FILE_A="00000000-0000-4000-8000-00000000000a"
FILE_B="00000000-0000-4000-8000-00000000000b"
FILE_C="00000000-0000-4000-8000-00000000000c"
FILE_D="00000000-0000-4000-8000-00000000000d"
FILE_E="00000000-0000-4000-8000-00000000000e"
STATIC_SWAP_WAIT="${STATIC_SWAP_WAIT:-32}"

GROUPS_ALL=(config tls default_servers redirect forwarded headers static log gzip loopback media iiifserver acl search_export timeout_config stream rate upstream_down)

RUN="msedge-$$"
NET="$RUN-net"
NGINX="$RUN-nginx"
TMP="$(mktemp -d)"
CERTS="$TMP/certs"
MEDIA="$TMP/media"
STATIC="$TMP/static"
LOGS="$TMP/logs"
WEBROOT="$TMP/acme"
USER_SPEC="$(id -u):$(id -g)"

n=0
failed=0

cleanup() {
  docker rm -f "$NGINX" "$RUN-web" "$RUN-cantaloupe" >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
  rm -rf "$TMP"
}
trap cleanup EXIT

assert() { # assert DESCRIPTION EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}
check() { # check DESCRIPTION CMD... : true when CMD succeeds
  local description="$1"
  shift
  "$@" >/dev/null 2>&1
  assert "$description" $?
}
equals() { # equals DESCRIPTION EXPECTED ACTUAL
  if [ "$2" = "$3" ]; then
    assert "$1" 0
  else
    assert "$1 (expected [$2], got [$3])" 1
  fi
}

# ---- helpers -----------------------------------------------------------

get() { # get PATH [curl args]
  curl -sS --max-time 20 --resolve "$HOST:$HTTPS_PORT:127.0.0.1" --cacert "$CERTS/ca.crt" \
    "https://$HOST:$HTTPS_PORT$1" "${@:2}"
}
code() { get "$1" -o /dev/null -w '%{http_code}' "${@:2}"; }
headers() { get "$1" -D - -o /dev/null "${@:2}" | tr -d '\r'; }
header_count() { # header_count NAME < headers
  grep -ic "^$1:" || true
}
header_value() { # header_value NAME < headers
  grep -i "^$1:" | head -1 | cut -d' ' -f2-
}
# jget KEY... : walk the JSON on stdin; `<absent>` when a key is missing.
jget() {
  python3 -I -c '
import json, sys
d = json.load(sys.stdin)
for key in sys.argv[1:]:
    if not isinstance(d, dict) or key not in d:
        d = "<absent>"
        break
    d = d[key]
print(d)' "$@"
}

start_stub() { # start_stub NAME PORT
  docker run -d --name "$RUN-$1" --network "$NET" --network-alias "$1" \
    --user "$USER_SPEC" --read-only --cap-drop ALL --security-opt no-new-privileges \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$HERE/stub_upstream.py:/stub_upstream.py:ro" \
    "$PYTHON_IMAGE" python /stub_upstream.py "$2" "$1" >/dev/null
}

# The mounts of the nginx service in compose.yaml.
nginx_run_args() {
  printf '%s\n' \
    --user "$USER_SPEC" --read-only --cap-drop ALL --security-opt no-new-privileges \
    --tmpfs /tmp:rw,size=16m,mode=1777 \
    --tmpfs /var/cache/nginx:rw,size=256m,mode=1777 \
    -v "$NGINX_DIR/nginx.conf:/etc/nginx/nginx.conf:ro" \
    -v "$NGINX_DIR/snippets:/etc/nginx/snippets:ro" \
    -v "$NGINX_DIR/templates:/etc/nginx/templates:ro" \
    -v "$NGINX_DIR/errors:/etc/nginx/errors:ro" \
    -v "$REPO/manuspectrum/templates/errors/500.htm:/etc/nginx/site-errors/500.htm:ro" \
    -v "$NGINX_DIR/ffdhe2048.pem:/etc/nginx/ffdhe2048.pem:ro" \
    -v "$CERTS:/etc/nginx/certs:ro" \
    -v "$WEBROOT:/var/www/acme:ro" \
    -v "$MEDIA:/srv/media:ro" \
    -v "$STATIC:/srv/static:ro" \
    -v "$LOGS:/var/log/manuspectrum" \
    -e NGINX_ENVSUBST_OUTPUT_DIR=/tmp \
    -e 'NGINX_ENVSUBST_FILTER=^(DOMAIN_NAMES|HSTS_MAX_AGE)$' \
    -e "DOMAIN_NAMES=$HOST" \
    -e HSTS_MAX_AGE=3600
}

start_nginx() {
  local args=()
  mapfile -t args < <(nginx_run_args)
  docker run -d --name "$NGINX" --network "$NET" \
    -p 127.0.0.1::8080 -p 127.0.0.1::8443 "${args[@]}" "$NGINX_IMAGE" >/dev/null
}

wait_for() { # wait_for SECONDS CMD... : true as soon as CMD succeeds
  local deadline=$((SECONDS + $1))
  shift
  until "$@" >/dev/null 2>&1; do
    [ "$SECONDS" -lt "$deadline" ] || return 1
    sleep 1
  done
}

stub_answers() { [ "$(code /ping)" = 200 ]; }

setup() {
  mkdir -p "$CERTS" "$LOGS" "$WEBROOT/.well-known/acme-challenge" \
    "$MEDIA/uploadedfiles" "$MEDIA/export_deliverables" "$MEDIA/archestemp" \
    "$STATIC/releases/aaaaaaaaaaaaaaaa" "$STATIC/releases/bbbbbbbbbbbbbbbb"
  chmod 0777 "$LOGS"
  bash "$REPO/deploy/certs/make-local-ca.sh" "$CERTS" "$HOST" >/dev/null || return 1
  chmod 0755 "$CERTS"
  chmod 0644 "$CERTS"/*.pem "$CERTS"/ca.crt

  echo "acme token" >"$WEBROOT/.well-known/acme-challenge/t"
  printf 'smoke,é\n' >"$MEDIA/uploadedfiles/smoke file é.csv"
  printf 'zip bytes\n' >"$MEDIA/export_deliverables/e.zip"
  printf 'staged\n' >"$MEDIA/archestemp/x.zip"
  printf 'image bytes\n' >"$MEDIA/uploadedfiles/pic.png"

  local release
  for release in aaaaaaaaaaaaaaaa bbbbbbbbbbbbbbbb; do
    printf 'body{color:red}/* %s */\n' "$release" >"$STATIC/releases/$release/app.0123456789abcdef0123.css"
    printf 'unhashed %s\n' "$release" >"$STATIC/releases/$release/plain.txt"
    printf 'id\n' >"$STATIC/releases/$release/.build-id"
    printf 'done\n' >"$STATIC/releases/$release/.complete"
  done
  ln -s releases/aaaaaaaaaaaaaaaa "$STATIC/current"

  docker network create "$NET" >/dev/null || return 1
  # nginx first, with no upstream yet: it must start and follow them when they appear.
  start_nginx || return 1
  wait_for 20 docker exec "$NGINX" wget -q -O /dev/null http://127.0.0.1:8081/nginx-health || return 1
  HTTP_PORT="$(docker port "$NGINX" 8080/tcp | head -1 | sed 's/.*://')"
  HTTPS_PORT="$(docker port "$NGINX" 8443/tcp | head -1 | sed 's/.*://')"
  check "nginx starts with web and cantaloupe unresolvable (upstream resolve)" \
    docker exec "$NGINX" wget -q -O /dev/null http://127.0.0.1:8081/nginx-health
  start_stub web 8000 && start_stub cantaloupe 8182 || return 1
  if ! wait_for 40 stub_answers; then
    echo "setup: nginx never reached the stub" >&2
    docker logs "$NGINX" >&2
    return 1
  fi
  assert "nginx follows an upstream that appears after it started" 0
}

# ---- groups -------------------------------------------------------------

group_config() {
  local args=() out
  mapfile -t args < <(nginx_run_args)
  out="$(docker run --rm --network none "${args[@]}" "$NGINX_IMAGE" nginx -t 2>&1)"
  assert "nginx -t passes" "$(grep -q 'test is successful' <<<"$out" && echo 0 || echo 1)"
  check "nginx -t prints no [warn], [emerg] or ERROR" bash -c '! grep -E "\[(warn|emerg|alert)\]|ERROR" <<<"$1"' _ "$out"
  out="$(docker exec "$NGINX" nginx -T 2>&1)"
  check "the template is rendered with DOMAIN_NAMES and HSTS_MAX_AGE" \
    bash -c 'grep -q "server_name manuspectrum.test;" <<<"$1" && grep -q "max-age=3600" <<<"$1" && ! grep -q "\${" <<<"$1"' _ "$out"
}

group_tls() {
  local out
  out="$(openssl s_client -tls1_1 -cipher 'ALL:@SECLEVEL=0' -connect "127.0.0.1:$HTTPS_PORT" -servername "$HOST" </dev/null 2>&1)"
  check "TLS 1.1 is refused by the server (protocol version alert)" \
    bash -c 'grep -qi "alert protocol version\|no protocols available\|wrong version number\|unsupported protocol" <<<"$1" && ! grep -q "Cipher is [A-Z]" <<<"$1"' _ "$out"
  out="$(openssl s_client -tls1_2 -CAfile "$CERTS/ca.crt" -verify_hostname "$HOST" -connect "127.0.0.1:$HTTPS_PORT" -servername "$HOST" </dev/null 2>&1)"
  check "TLS 1.2 is accepted and the certificate verifies" bash -c 'grep -q "New, TLSv1.2," <<<"$1" && grep -q "Verification: OK" <<<"$1"' _ "$out"
  out="$(openssl s_client -tls1_3 -CAfile "$CERTS/ca.crt" -verify_hostname "$HOST" -connect "127.0.0.1:$HTTPS_PORT" -servername "$HOST" </dev/null 2>&1)"
  check "TLS 1.3 is accepted" bash -c 'grep -q "New, TLSv1.3," <<<"$1"' _ "$out"
  out="$(docker exec "$NGINX" nginx -T 2>&1)"
  check "no ssl_stapling directive" bash -c '! grep -q "^[[:space:]]*ssl_stapling" <<<"$1"' _ "$out"
}

group_default_servers() {
  local status
  curl -sS --max-time 10 -o /dev/null -H 'Host: other.example' "http://127.0.0.1:$HTTP_PORT/" 2>/dev/null
  status=$?
  equals "unknown Host on port 80 gets an empty reply (curl exit 52)" 52 "$status"
  curl -sS --max-time 10 -o /dev/null --resolve "other.example:$HTTPS_PORT:127.0.0.1" -k "https://other.example:$HTTPS_PORT/" 2>/dev/null
  status=$?
  check "unknown SNI fails the handshake (no certificate)" test "$status" -ne 0
  check "unknown SNI is not answered with the site certificate" \
    bash -c '! openssl s_client -connect "127.0.0.1:$1" -servername other.example </dev/null 2>&1 | grep -q "BEGIN CERTIFICATE"' _ "$HTTPS_PORT"
}

group_redirect() {
  local out
  out="$(curl -sS --max-time 10 -D - -o /dev/null --resolve "$HOST:$HTTP_PORT:127.0.0.1" "http://$HOST:$HTTP_PORT/x?y=1" | tr -d '\r')"
  equals "port 80 answers 301" 301 "$(head -1 <<<"$out" | cut -d' ' -f2)"
  equals "the redirect keeps path and query on https" "https://$HOST/x?y=1" "$(header_value location <<<"$out")"
  out="$(curl -sS --max-time 10 -D - --resolve "$HOST:$HTTP_PORT:127.0.0.1" "http://$HOST:$HTTP_PORT/.well-known/acme-challenge/t" | tr -d '\r')"
  equals "acme challenge on port 80 is served, not redirected" 200 "$(head -1 <<<"$out" | cut -d' ' -f2)"
  check "acme challenge body comes from the webroot" grep -q '^acme token' <<<"$out"
  equals "an absent challenge on port 80 is 404, not a redirect" 404 \
    "$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' --resolve "$HOST:$HTTP_PORT:127.0.0.1" "http://$HOST:$HTTP_PORT/.well-known/acme-challenge/none")"
}

group_forwarded() {
  local out
  out="$(get /fwd \
    -H 'X-Forwarded-For: 6.6.6.6' -H 'X-Forwarded-Proto: http' -H 'X-Forwarded-Ssl: on' \
    -H 'X-Forwarded-Protocol: ssl' -H 'Forwarded: for=6.6.6.6;proto=http' \
    -H 'X-Forwarded-Host: evil.example' -H 'X-Forwarded-Port: 80' \
    -H 'X-Real-IP: 6.6.6.6' -H 'X-Request-ID: forged-id')"
  equals "the stub is web" web "$(jget name <<<"$out")"
  local real xff
  real="$(jget headers x-real-ip <<<"$out")"
  xff="$(jget headers x-forwarded-for <<<"$out")"
  check "X-Real-IP is a client address, not the forged value" bash -c '[[ "$1" =~ ^[0-9.]+$ && "$1" != 6.6.6.6 ]]' _ "$real"
  equals "X-Forwarded-For is the client address, not a chain" "$real" "$xff"
  equals "X-Forwarded-Proto is https" https "$(jget headers x-forwarded-proto <<<"$out")"
  local header
  for header in x-forwarded-ssl x-forwarded-protocol forwarded x-forwarded-host x-forwarded-port; do
    equals "forged $header is dropped" "<absent>" "$(jget headers $header <<<"$out")"
  done
  check "X-Request-ID is nginx's own 32 hex characters" \
    bash -c '[[ "$1" =~ ^[0-9a-f]{32}$ ]]' _ "$(jget headers x-request-id <<<"$out")"
  equals "Host is the public name" "$HOST" "$(jget headers host <<<"$out")"
}

# Each header nginx or Django owns appears exactly once, on every class of response.
assert_one_of_each() { # assert_one_of_each LABEL RESPONSE-HEADERS
  local label="$1" out="$2" header
  for header in Strict-Transport-Security Permissions-Policy Content-Security-Policy-Report-Only \
    X-Content-Type-Options X-Frame-Options Referrer-Policy; do
    equals "$label: exactly one $header" 1 "$(header_count "$header" <<<"$out")"
  done
  equals "$label: HSTS value" "max-age=3600" "$(header_value strict-transport-security <<<"$out")"
  equals "$label: no Server version" "nginx" "$(header_value server <<<"$out")"
}

group_headers() {
  assert_one_of_each "proxied page" "$(headers /page)"
  assert_one_of_each "static file" "$(headers /static/app.0123456789abcdef0123.css)"
  assert_one_of_each "the edge 404 (internal page asked directly)" "$(headers /_errors/404.html)"
}

group_static() {
  local out
  out="$(headers /static/app.0123456789abcdef0123.css)"
  equals "hashed file is immutable" "public, max-age=31536000, immutable" "$(header_value cache-control <<<"$out")"
  equals "hashed file is served" 200 "$(head -1 <<<"$out" | cut -d' ' -f2)"
  equals "unhashed file gets max-age=3600" "public, max-age=3600" "$(header_value cache-control <<<"$(headers /static/plain.txt)")"
  equals "/static/.build-id is 404" 404 "$(code /static/.build-id)"
  equals "/static/.complete is 404" 404 "$(code /static/.complete)"
  equals "an absent static file is 404" 404 "$(code /static/none.js)"
  check "static serves the first release" grep -q 'unhashed aaaa' <<<"$(get /static/plain.txt)"
  ln -sfn releases/bbbbbbbbbbbbbbbb "$STATIC/current.new" && mv -Tf "$STATIC/current.new" "$STATIC/current"
  sleep "$STATIC_SWAP_WAIT"
  check "after the symlink swap and open_file_cache_valid the new release is served" \
    grep -q 'unhashed bbbb' <<<"$(get /static/plain.txt)"
  ln -sfn releases/aaaaaaaaaaaaaaaa "$STATIC/current.new" && mv -Tf "$STATIC/current.new" "$STATIC/current"
}

group_log() {
  get '/en/reset/abc/def-123/?secret=1' -e 'https://elsewhere.example/page?token=zzz' >/dev/null
  get '/query?name=value' >/dev/null
  sleep 1
  local request_id seen
  seen="$(get '/rid?x=1')"
  request_id="$(jget headers x-request-id <<<"$seen")"
  sleep 1
  check "access.log is valid JSON per line" python3 -I -c '
import json, sys
lines = open(sys.argv[1]).read().splitlines()
assert lines
[json.loads(line) for line in lines]' "$LOGS/access.log"
  check "the logged request_id equals the id the stub saw" python3 -I -c '
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]).read().splitlines()]
assert any(r["request_id"] == sys.argv[2] for r in rows)' "$LOGS/access.log" "$request_id"
  check "uri is logged without its query string" python3 -I -c '
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]).read().splitlines()]
row = next(r for r in rows if r["uri"] == "/query")
assert "?" not in row["uri"] and row["status"] == 200 and row["remote_addr"]' "$LOGS/access.log"
  check "a password-reset link is logged as /en/reset/[redacted]" python3 -I -c '
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]).read().splitlines()]
assert any(r["uri"] == "/en/reset/[redacted]" for r in rows)
assert not any("def-123" in json.dumps(r) or "secret" in json.dumps(r) for r in rows)' "$LOGS/access.log"
  check "the referer keeps its path and drops its query" python3 -I -c '
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]).read().splitlines()]
assert any(r["referer"] == "https://elsewhere.example/page" for r in rows)
assert not any("zzz" in json.dumps(r) for r in rows)' "$LOGS/access.log"
  check "error.log exists in the same directory" test -f "$LOGS/error.log"
}

group_gzip() {
  local out
  out="$(headers /page -H 'Accept-Encoding: gzip' -H "X-Pad: $(printf 'x%.0s' {1..1500})")"
  equals "JSON is gzipped" gzip "$(header_value content-encoding <<<"$out")"
  out="$(headers /big.csv -H 'Accept-Encoding: gzip')"
  equals "text/csv is not gzipped" "" "$(header_value content-encoding <<<"$out")"
}

group_loopback() {
  local out
  out="$(docker exec "$NGINX" wget -S -q -O /dev/null 'http://127.0.0.1:8081/files/uploadedfiles/smoke%20file%20%C3%A9.csv' 2>&1)"
  check "the loopback server decodes the raw name and serves the file" grep -q 'HTTP/1.1 200' <<<"$out"
  check "uploaded bytes carry nosniff and a sandbox CSP" \
    bash -c 'grep -qi "X-Content-Type-Options: nosniff" <<<"$1" && grep -qi "sandbox" <<<"$1"' _ "$out"
  check "a CSV is an attachment" grep -qi 'Content-Disposition: attachment' <<<"$out"
  out="$(docker exec "$NGINX" wget -S -q -O /dev/null 'http://127.0.0.1:8081/files/uploadedfiles/pic.png' 2>&1)"
  check "a PNG is not an attachment" bash -c '! grep -qi "Content-Disposition" <<<"$1"' _ "$out"
  check "export deliverables are served" \
    docker exec "$NGINX" wget -q -O /dev/null http://127.0.0.1:8081/files/export_deliverables/e.zip
  check "archestemp is not served" bash -c '! docker exec "$1" wget -q -O /dev/null http://127.0.0.1:8081/files/archestemp/x.zip' _ "$NGINX"
  check "the loopback port is not published" bash -c '! docker port "$1" | grep -q 8081' _ "$NGINX"
}

# What a request reaches: the stub's name, or "-" when nginx answered itself
# (the stub echoes X-Request-ID, nginx's own answers carry none).
reaches() { # reaches PATH [curl args] : web, cantaloupe or -
  local out
  out="$(headers "$@")"
  if [ -n "$(header_value x-request-id <<<"$out")" ]; then echo web; else echo -; fi
}
codes() { # codes COUNT PATH [curl args] : the status of COUNT requests in a row
  local count="$1" i out=""
  shift
  for ((i = 0; i < count; i++)); do out+="$(code "$@") "; done
  echo "$out"
}
# location_block FILE-SECTION PATTERN < nginx -T : the text of one location
location_block() {
  python3 -I -c '
import sys
lines = sys.stdin.read().splitlines()
start = next(i for i, l in enumerate(lines) if l.startswith("location") and sys.argv[1] in l)
end = next(i for i in range(start, len(lines)) if lines[i] == "}")
print("\n".join(lines[start:end + 1]))' "$1"
}

group_media() {
  local out
  out="$(headers "/en/files/$FILE_A")"
  equals "files/<A>: 200" 200 "$(head -1 <<<"$out" | cut -d' ' -f2)"
  equals "files/<A>: the bytes of the stored file" "$(printf 'smoke,é\n')" "$(get "/en/files/$FILE_A")"
  check "files/<A>: attachment" grep -qi '^Content-Disposition: attachment' <<<"$out"
  check "files/<A>: sandbox CSP" grep -qi "^Content-Security-Policy: default-src 'none'; sandbox" <<<"$out"
  assert_one_of_each "files/<A>" "$out"
  equals "files/<A>: exactly one nosniff" 1 "$(header_count X-Content-Type-Options <<<"$out")"
  equals "files/<E> (export deliverable): 200" 200 "$(code "/fr/files/$FILE_E")"
  equals "files/<E>: the bytes of the export" "zip bytes" "$(get "/fr/files/$FILE_E")"
  equals "files/<B>: the 403 of Django passes through" 403 "$(code "/en/files/$FILE_B")"
  equals "files/<C> (archestemp): 404" 404 "$(code "/en/files/$FILE_C")"
  equals "files/<D> (encoded slashes): 404" 404 "$(code "/en/files/$FILE_D")"
  out="$(get '/files/uploadedfiles/smoke%20file%20%C3%A9.csv')"
  equals "a direct /files/uploadedfiles/<name> reaches Django, not the disk" web "$(jget name <<<"$out")"
  equals "an unprefixed /files/<uuid> reaches Django (its language redirect)" web "$(jget name <<<"$(get "/files/$FILE_A")")"
  equals "a non-uuid under files/ reaches Django" web "$(jget name <<<"$(get /en/files/not-a-uuid)")"
  check "127.0.0.1:8081 is not published" bash -c '! docker port "$1" | grep -q 8081' _ "$NGINX"
}

group_iiifserver() {
  local out
  out="$(get '/iiifserver/iiif/3/a%2Fb%20c%C3%A9.tif/info.json')"
  equals "iiifserver: the image server is reached" cantaloupe "$(jget name <<<"$out")"
  equals "iiifserver: %2F, %20 and %C3%A9 arrive byte for byte" \
    '/iiif/3/a%2Fb%20c%C3%A9.tif/info.json' "$(jget path <<<"$out")"
  out="$(get '/fr/iiifserver/iiif/2/x/info.json?a=b%20c')"
  equals "iiifserver: the language prefix is dropped, the query kept" \
    '/iiif/2/x/info.json?a=b%20c' "$(jget path <<<"$out")"
  equals "iiifserver: // after the mount point is 404" 404 "$(code '/iiifserver//iiif/3/x' --path-as-is)"
  equals "iiifserver: /admin is 404" 404 "$(code /iiifserver/admin)"
  equals "iiifserver: a path outside /iiif/2|3/ is 404" 404 "$(code /iiifserver/iiif/4/x)"
  equals "iiifserver: the bare mount point is 404" 404 "$(code /iiifserver/)"
  out="$(headers /iiifserver/iiif/3/x/info.json -H 'Origin: https://viewer.example')"
  equals "iiifserver: one Access-Control-Allow-Origin" 1 "$(header_count Access-Control-Allow-Origin <<<"$out")"
  equals "iiifserver: it is *" "*" "$(header_value access-control-allow-origin <<<"$out")"
  equals "iiifserver: one Access-Control-Allow-Methods" 1 "$(header_count Access-Control-Allow-Methods <<<"$out")"
  assert_one_of_each "iiifserver" "$out"
  out="$(headers /iiifserver/iiif/3/x/info.json -X OPTIONS -H 'Origin: https://viewer.example' -H 'Access-Control-Request-Method: GET')"
  equals "iiifserver: OPTIONS is 204" 204 "$(head -1 <<<"$out" | cut -d' ' -f2)"
  equals "iiifserver: OPTIONS lists the methods" "GET, HEAD, OPTIONS" "$(header_value access-control-allow-methods <<<"$out")"
  equals "iiifserver: OPTIONS carries one Access-Control-Allow-Origin" 1 "$(header_count Access-Control-Allow-Origin <<<"$out")"
  out="$(get /iiifserver/iiif/3/x/info.json -H 'X-Forwarded-For: 6.6.6.6' -H 'X-Real-IP: 6.6.6.6' \
    -H 'X-Forwarded-Proto: http' -H 'X-Forwarded-Host: evil.example' -H 'X-Forwarded-Port: 80' -H 'Forwarded: for=6.6.6.6')"
  local header
  for header in x-forwarded-for x-real-ip x-forwarded-proto x-forwarded-host x-forwarded-port forwarded; do
    equals "iiifserver: $header never reaches the image server" "<absent>" "$(jget headers $header <<<"$out")"
  done
  equals "no other route carries CORS (a proxied page)" 0 "$(header_count Access-Control-Allow-Origin <<<"$(headers /page -H 'Origin: https://viewer.example')")"
  equals "no other route carries CORS (the Explorer API)" 0 \
    "$(header_count Access-Control-Allow-Origin <<<"$(headers /fr/api/explorer/search -H 'Origin: https://viewer.example')")"
  equals "/iiif/ keeps the CORS header of Django (one)" 1 \
    "$(header_count Access-Control-Allow-Origin <<<"$(headers /iiif/v3/annotation/x -H 'Origin: https://viewer.example')")"
}

group_acl() {
  local lang path out
  for lang in en fr; do
    for path in api/resource/x api/tile/g/n "api/tile-list-create/g/n/$FILE_A" api/tile-new-resource/g/n; do
      equals "/$lang/$path: 404 from nginx" "404 -" "$(code "/$lang/$path") $(reaches "/$lang/$path")"
    done
  done
  equals "/en//api/resource/x: 404 from nginx" "404 -" "$(code /en//api/resource/x --path-as-is) $(reaches /en//api/resource/x --path-as-is)"
  equals "/en/api/%72esource/x: 404 from nginx" "404 -" "$(code /en/api/%72esource/x) $(reaches /en/api/%72esource/x)"
  equals "/fr/api/tiles/x (core, plural) reaches Django" web "$(jget name <<<"$(get /fr/api/tiles/x)")"
  equals "/en/api/relatable-resources/g/n reaches Django" web "$(jget name <<<"$(get /en/api/relatable-resources/g/n)")"
  equals "/fr/silk/ is 404 from nginx" "404 -" "$(code /fr/silk/) $(reaches /fr/silk/)"
  equals "/en/silk/requests/ is 404 from nginx" "404 -" "$(code /en/silk/requests/) $(reaches /en/silk/requests/)"
  equals "/metrics is 404 from nginx" "404 -" "$(code /metrics) $(reaches /metrics)"
  equals "/readyz is 404 from nginx" "404 -" "$(code /readyz) $(reaches /readyz)"
  equals "/metrics and /readyz have an empty body" "0 0" "$(get /metrics -o /dev/null -w '%{size_download}') $(get /readyz -o /dev/null -w '%{size_download}')"
  equals "/healthz reaches Django" web "$(jget name <<<"$(get /healthz)")"
  assert_one_of_each "the edge 404 of a denied route" "$(headers /en/api/resource/x)"
}

group_search_export() {
  local base=/fr/api/search/export_results
  equals "api export format=tilecsv: 404" 404 "$(code "$base?format=tilecsv")"
  equals "api export without a format: 404" 404 "$(code "$base")"
  equals "api export format=geojson&format=tilecsv: 404" 404 "$(code "$base?format=geojson&format=tilecsv")"
  equals "api export format=geojson&form%61t=shp: 404" 404 "$(code "$base?format=geojson&form%61t=shp")"
  equals "api export format=tilecsv&format=geojson: 404" 404 "$(code "$base?format=tilecsv&format=geojson")"
  equals "api export format=geojson: reaches Django" web "$(jget name <<<"$(get "$base?format=geojson")")"
  equals "POST /fr/temp_file: 404" 404 "$(code /fr/temp_file -X POST)"
  equals "GET /fr/temp_file/<uuid> reaches Django" web "$(jget name <<<"$(get "/fr/temp_file/$FILE_A")")"
  equals "GET /fr/temp_file reaches Django" web "$(jget name <<<"$(get /fr/temp_file)")"
  local out
  out="$(codes 12 '/fr/search/export_results?format=tilecsv&total=1')"
  check "12 rapid search exports: some answer 429" grep -q 429 <<<"$out"
  check "12 rapid search exports: the first ones pass" grep -q '^200' <<<"$out"
}

group_rate() {
  local out i
  out="$(codes 7 /en/auth/ -X POST)"
  equals "7 POSTs to /en/auth/: the first 6 pass, the 7th is 429" "200 200 200 200 200 200 429 " "$out"
  out="$(headers /en/auth/ -X POST)"
  equals "the 429 page carries Retry-After" 60 "$(header_value retry-after <<<"$out")"
  check "the 429 body is the nginx page" grep -q 'Too many requests' <<<"$(get /en/auth/ -X POST)"
  assert_one_of_each "the 429 page" "$out"
  out="$(codes 7 /en/auth/)"
  check "7 GETs to /en/auth/ are never limited" bash -c '! grep -q 429 <<<"$1"' _ "$out"
  out="$(codes 15 "/api/spectrum-preview/$FILE_A?n=full")"
  check "15 requests for ?n=full: some are 429" grep -q 429 <<<"$out"
  sleep 4
  out="$(codes 15 "/api/spectrum-preview/$FILE_A")"
  check "15 requests without n: none is 429" bash -c '! grep -q 429 <<<"$1"' _ "$out"
  sleep 4
  out="$(codes 12 "/api/spectrum-preview/$FILE_A?n=200")"
  check "12 requests with n=200 are not counted as full" bash -c '! grep -q 429 <<<"$1"' _ "$out"
  sleep 4
  out="$(codes 10 /en/api/explorer/share)"
  check "the share route is limited (heavy)" grep -q 429 <<<"$out"
}

group_timeout_config() {
  local dump block
  dump="$(docker exec "$NGINX" nginx -T 2>&1)"
  block="$(location_block 'create-(all|resource)' <<<"$dump")"
  check "create-all and create-resource: proxy_read_timeout 340s" grep -q 'proxy_read_timeout 340s;' <<<"$block"
  check "create-all and create-resource: proxy_next_upstream off" grep -q 'proxy_next_upstream off;' <<<"$block"
  block="$(location_block 'explorer/(export|series' <<<"$dump")"
  check "export and series.csv: proxy_buffering off" grep -q 'proxy_buffering off;' <<<"$block"
  check "export and series.csv: gzip off" grep -q 'gzip off;' <<<"$block"
  check "export and series.csv: proxy_read_timeout 300s" grep -q 'proxy_read_timeout 300s;' <<<"$block"
  block="$(location_block 'api/search/export_results' <<<"$dump")"
  check "search export: proxy_read_timeout 120s" grep -q 'proxy_read_timeout 120s;' <<<"$block"
  check "gzip_types holds application/ld+json and no csv or zip" \
    bash -c 'l="$(grep "gzip_types" -A2 <<<"$1")"; grep -q "application/ld+json" <<<"$l" && ! grep -Eq "text/csv|application/zip" <<<"$l"' _ "$dump"
}

group_stream() {
  local start first
  start="$(date +%s.%N)"
  first="$(get /api/explorer/series.csv -N 2>/dev/null | { read -r _; date +%s.%N; })"
  check "series.csv: the first chunk arrives within 1.5 s, not with the last one" \
    python3 -I -c 'import sys; start, first = map(float, sys.argv[1:]); sys.exit(0 if first - start < 1.5 else 1)' "$start" "$first"
  equals "series.csv: three chunks, in order" "chunk 0 chunk 1 chunk 2" "$(get /api/explorer/series.csv -N | tr '\n' ' ' | sed 's/ $//')"
  equals "series.csv: not gzipped" "" "$(header_value content-encoding <<<"$(headers /api/explorer/series.csv -H 'Accept-Encoding: gzip')")"
}

# Stops the web stub: keep this group last, it restores the stub when it is done.
group_upstream_down() {
  local out
  docker rm -f "$RUN-web" >/dev/null
  sleep 12
  out="$(headers /page)"
  check "web down: nginx answers 502 (504 while the stale address times out)" \
    grep -Eq '^HTTP/[0-9.]+ 50[24]' <<<"$out"
  check "the 50x is the bilingual error page" grep -q 'Instrument malfunction' <<<"$(get /page)"
  assert_one_of_each "the 50x page" "$out"
  start_stub web 8000
  check "web back: nginx follows the recreated upstream" wait_for 40 stub_answers
}

# ---- run ----------------------------------------------------------------

if ! setup; then
  echo "not ok - setup failed" >&2
  exit 1
fi

selected=("$@")
[ "${#selected[@]}" -gt 0 ] || selected=("${GROUPS_ALL[@]}")
for group in "${selected[@]}"; do
  if declare -F "group_$group" >/dev/null; then
    "group_$group"
  else
    echo "unknown group: $group" >&2
    failed=1
  fi
done

echo "1..$n"
exit "$failed"
