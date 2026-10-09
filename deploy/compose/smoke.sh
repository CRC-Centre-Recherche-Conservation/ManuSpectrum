#!/usr/bin/env bash
# Checks a running stack (CI runner, rehearsal VM). Usage: smoke.sh COMMAND
#   wait         wait until every service is healthy (or running, for beat)
#   check        read-only assertions on the stack (safe in production)
#   mark         write one marker per store: PostgreSQL, Elasticsearch,
#                redis-broker, media; remembered in SMOKE_STATE
#   survived     the markers written by `mark` are still there
#   static-swap  a stale `current` static release is replaced on web restart
#   init-guard   `init`, `manage setup_db` and the `packages` forms that call it
#                are refused on a live database
#   observability /readyz, /metrics, JSON logs and the request id, the worker's
#                metrics after one prune task (CI and rehearsal)
#   edge         nginx over HTTPS: the only published ports, redirect, headers,
#                denied routes, uploaded files, IIIF image server, rate limit,
#                access log, and web reaching the public name (CI and
#                rehearsal: it writes one File row and one image, then removes them)
#   readiness    /readyz answers 503 while Elasticsearch is stopped, 200 after
#                (CI and rehearsal only)
#   lose         delete the PostgreSQL marker row and the uploads marker, as a
#                disaster would; `survived` must then fail until a restore
#                (CI and rehearsal only)
#   clean        remove the markers
# mark, lose, static-swap, init-guard, edge, readiness and clean are for CI and rehearsal only.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$HERE/.env}"
SMOKE_STATE="${SMOKE_STATE:-$HERE/.smoke-state}"

compose() {
  docker compose --project-directory "$HERE" --env-file "$ENV_FILE" \
    -f "$HERE/compose.yaml" -f "$HERE/compose.prod.yaml" "$@"
}
env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; }
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }
expect() { # expect DESCRIPTION EXPECTED ACTUAL
  [ "$3" = "$2" ] || fail "$1: expected '$2', got '$3'"
  ok "$1"
}

in_web() { compose exec -T web "$@"; }
# Requests reach gunicorn directly; `Host: web` is the only non-public name ALLOWED_HOSTS accepts.
http_code() { # http_code PATH [HOST]
  in_web curl -s -o /dev/null -w '%{http_code}' -H "Host: ${2:-web}" "http://127.0.0.1:8000$1"
}
psql_app() {
  compose exec -T postgres psql -qtA -U "$(env_value PGUSERNAME)" -d "$(env_value PGDBNAME)" -c "$1"
}
# The single-quoted script is expanded by the container's sh.
# shellcheck disable=SC2016
es() { # es METHOD PATH [BODY]
  compose exec -T elasticsearch sh -c \
    'curl -fsS -u "elastic:$(cat /run/secrets/elastic_password)" -X "$0" -H "Content-Type: application/json" "http://localhost:9200$1" ${2:+-d "$2"}' \
    "$1" "$2" "${3:-}"
}
redis() { local service="$1"; shift; compose exec -T "$service" redis-cli "$@"; }
build_id() { in_web cat /app/static/.build-id; }

cmd_wait() {
  local deadline=$((SECONDS + ${SMOKE_TIMEOUT:-900})) id status pending
  while :; do
    pending=0
    for id in $(compose ps -aq); do
      status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id")"
      case "$status" in healthy | running) ;; *) pending=1 ;; esac
    done
    if [ "$pending" = 0 ] && [ -n "$(compose ps -q web)" ]; then
      ok "every service is healthy"
      return 0
    fi
    [ "$SECONDS" -lt "$deadline" ] || { compose ps -a; fail "services not healthy in time"; }
    sleep 5
  done
}

cmd_check() {
  expect "/healthz" ok "$(in_web curl -fsS -H 'Host: web' http://127.0.0.1:8000/healthz)"
  expect "/healthz for the public name" 200 "$(http_code /healthz "$(env_value DOMAIN_NAMES | cut -d' ' -f1)")"
  expect "/healthz for Host localhost (not allowed)" 400 "$(http_code /healthz localhost)"
  expect "/en/auth/ status" 200 "$(http_code /en/auth/)"
  expect "unknown page status" 404 "$(http_code /en/smoke-no-such-page/)"
  if in_web curl -s -H 'Host: web' http://127.0.0.1:8000/en/smoke-no-such-page/ | grep -q "DEBUG = True"; then
    fail "the 404 page is Django's debug page"
  fi
  ok "the 404 page is the site page"
  expect "web uid" "$(env_value APP_UID)" "$(in_web id -u)"
  if in_web sh -c 'touch /app/.smoke-write' 2>/dev/null; then fail "web root filesystem is writable"; fi
  ok "web root filesystem is read-only"
  expect "static current" "releases/$(build_id)" "$(in_web readlink /srv/static/current)"

  expect "database collation and encoding" "en_US.utf8|UTF8" \
    "$(psql_app "SELECT datcollate || '|' || pg_encoding_to_char(encoding) FROM pg_database WHERE datname = current_database()")"
  expect "Arches system settings" 1 \
    "$(psql_app "SELECT count(*) FROM resource_instances WHERE resourceinstanceid = 'a106c400-260c-11e7-a604-14109fd34195'")"
  expect "template_postgis" "true|en_US.utf8" \
    "$(psql_app "SELECT datistemplate::text || '|' || datcollate FROM pg_database WHERE datname = 'template_postgis'")"
  expect "standard_conforming_strings" off "$(psql_app 'SHOW standard_conforming_strings')"
  expect "extensions" "btree_gist,plpgsql,postgis,unaccent,uuid-ossp" \
    "$(psql_app "SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension")"

  es GET '/_nodes/_local?filter_path=**.mlockall' | grep -q '"mlockall":true' \
    || fail "Elasticsearch memory is not locked"
  ok "Elasticsearch memory locked"

  expect "redis-broker policy" noeviction "$(redis redis-broker CONFIG GET maxmemory-policy | tail -n 1)"
  expect "redis-broker AOF" yes "$(redis redis-broker CONFIG GET appendonly | tail -n 1)"
  expect "redis-cache policy" allkeys-lru "$(redis redis-cache CONFIG GET maxmemory-policy | tail -n 1)"
  expect "redis-cache maxmemory" 536870912 "$(redis redis-cache CONFIG GET maxmemory | tail -n 1)"

  expect "Cantaloupe IIIF 3" 200 \
    "$(compose exec -T cantaloupe curl -s -o /dev/null -w '%{http_code}' http://localhost:8182/iiif/3)"
  [ "$(compose exec -T cantaloupe curl -s -o /dev/null -w '%{http_code}' http://localhost:8182/admin)" != 200 ] \
    || fail "Cantaloupe admin endpoint answers"
  ok "Cantaloupe admin endpoint closed"
  compose exec -T cantaloupe sh -c 'test -x /imageroot && ls -A /imageroot >/dev/null' \
    || fail "Cantaloupe cannot list /imageroot (on NFS the server must honour supplementary groups: no manage-gids in the mountd settings)"
  ok "Cantaloupe lists /imageroot"

  # The script is read from stdin and prints a verdict, never a hash or a password.
  expect "admin keeps Arches' default password" no \
    "$(in_web env -u PROMETHEUS_MULTIPROC_DIR python manage.py shell -c "
from django.contrib.auth import get_user_model
user = get_user_model().objects.filter(username='admin').first()
print('yes' if user is not None and user.check_password('admin') else 'no')
" | tail -n 1)"
}

cmd_mark() {
  local token migrations
  token="smoke-$(date +%s)-$RANDOM"
  psql_app "CREATE TABLE IF NOT EXISTS ms_smoke_marker (token text)" >/dev/null
  psql_app "INSERT INTO ms_smoke_marker VALUES ('$token')" >/dev/null
  migrations="$(psql_app 'SELECT count(*) FROM django_migrations')"
  es PUT "/ms-smoke-marker/_doc/1?refresh=true" "{\"token\":\"$token\"}" >/dev/null
  redis redis-broker -n 5 SET ms-smoke-marker "$token" >/dev/null
  # $0 is expanded by the container's sh.
  # shellcheck disable=SC2016
  in_web sh -c 'printf %s "$0" > /srv/media/.ms-smoke-marker; cp /srv/media/.ms-smoke-marker /srv/media/uploadedfiles/' "$token"
  sleep 2 # redis-broker fsyncs its append-only file every second
  printf 'TOKEN=%s\nMIGRATIONS=%s\n' "$token" "$migrations" >"$SMOKE_STATE"
  ok "markers written ($token)"
}

# TOKEN and MIGRATIONS come from the sourced state file.
# shellcheck disable=SC2153
cmd_survived() {
  [ -f "$SMOKE_STATE" ] || fail "no $SMOKE_STATE: run mark first"
  # shellcheck source=/dev/null
  . "$SMOKE_STATE"
  expect "PostgreSQL marker" 1 "$(psql_app "SELECT count(*) FROM ms_smoke_marker WHERE token = '$TOKEN'")"
  expect "PostgreSQL migrations" "$MIGRATIONS" "$(psql_app 'SELECT count(*) FROM django_migrations')"
  es GET /ms-smoke-marker/_doc/1 | grep -q "\"$TOKEN\"" || fail "Elasticsearch marker lost"
  ok "Elasticsearch marker"
  expect "redis-broker marker" "$TOKEN" "$(redis redis-broker -n 5 GET ms-smoke-marker)"
  expect "media marker" "$TOKEN" "$(in_web cat /srv/media/.ms-smoke-marker)"
  expect "Cantaloupe reads the uploaded files" "$TOKEN" \
    "$(compose exec -T cantaloupe cat /imageroot/.ms-smoke-marker)"
}

# Deletes what a restore must bring back: the PostgreSQL marker row of the
# remembered token and the copy of the marker in uploadedfiles/.
# TOKEN comes from the sourced state file.
# shellcheck disable=SC2153
cmd_lose() {
  [ -f "$SMOKE_STATE" ] || fail "no $SMOKE_STATE: run mark first"
  # shellcheck source=/dev/null
  . "$SMOKE_STATE"
  psql_app "DELETE FROM ms_smoke_marker WHERE token = '$TOKEN'" >/dev/null
  in_web rm -f /srv/media/uploadedfiles/.ms-smoke-marker
  ok "markers lost"
}

# A stylesheet of the current release, fetched through nginx (HTTPS).
static_through_nginx() {
  local css
  css="$(in_web sh -c "cd /srv/static/current && find . -name '*.css' -print -quit")"
  [ -n "$css" ] || fail "the current static release holds no stylesheet"
  edge_init
  expect "static file through nginx" 200 "$(edge_code "/static/${css#./}")"
}

cmd_static_swap() {
  in_web sh -c 'mkdir -p /srv/static/releases/smoke-stale && ln -sfn releases/smoke-stale /srv/static/current'
  compose restart web >/dev/null
  cmd_wait
  expect "static current after restart" "releases/$(build_id)" "$(in_web readlink /srv/static/current)"
  static_through_nginx
  in_web test -d /srv/static/releases/smoke-stale || fail "previous release removed too early"
  ok "previous release kept"
  compose restart web >/dev/null
  cmd_wait
  if in_web test -e /srv/static/releases/smoke-stale; then fail "stale release not pruned"; fi
  ok "stale release pruned"
  static_through_nginx
}

cmd_init_guard() {
  local out
  if out="$(compose run --rm --no-deps -T init 2>&1)"; then fail "init ran on a live database"; fi
  # Compose fails on the package bind mount (create_host_path: false) before the
  # entrypoint can refuse: say what is missing instead of a misleading failure.
  if grep -q "bind source path does not exist" <<<"$out"; then
    fail "init-guard needs the data package: PKG_DIR must name the pkg submodule (git submodule update --init), $out"
  fi
  grep -q "refusing" <<<"$out" || fail "init failed without refusing: $out"
  ok "init refused on a live database"
  if out="$(compose run --rm --no-deps -T web manage setup_db --force 2>&1)"; then fail "manage setup_db ran"; fi
  grep -q "refusing" <<<"$out" || fail "manage setup_db failed without refusing: $out"
  ok "manage setup_db refused"
  for args in "packages -o load_package -s pkg -db -y" "packages -o setup"; do
    # shellcheck disable=SC2086
    if out="$(compose run --rm --no-deps -T web manage $args 2>&1)"; then fail "manage $args ran"; fi
    grep -q "refusing" <<<"$out" || fail "manage $args failed without refusing: $out"
    ok "manage $args refused"
  done
}

json_field() { # json_field PYTHON-EXPRESSION-ON-r  (reads JSON on stdin)
  python3 -c 'import json, sys; r = json.load(sys.stdin); print(eval(sys.argv[1]))' "$1"
}

cmd_observability() {
  local body rid header line
  expect "/readyz" 200 "$(http_code /readyz)"
  body="$(in_web curl -s -H 'Host: web' http://127.0.0.1:8000/readyz)"
  expect "/readyz components" "cantaloupe,celery-broker,elasticsearch,postgres,redis-broker,redis-cache" \
    "$(json_field '",".join(sorted(r["components"]))' <<<"$body")"
  expect "/readyz all up" "True" \
    "$(json_field 'all(c["status"] == "up" for c in r["components"].values())' <<<"$body")"
  expect "/readyz relayed by a proxy" 404 \
    "$(in_web curl -s -o /dev/null -w '%{http_code}' -H 'Host: web' -H 'X-Forwarded-For: 203.0.113.9' http://127.0.0.1:8000/readyz)"
  expect "/en/metrics" 404 "$(http_code /en/metrics)"

  for _ in 1 2 3; do http_code /healthz >/dev/null; done
  body="$(in_web curl -fsS -H 'Host: web' http://127.0.0.1:8000/metrics)"
  grep -q '^django_http_requests_total_by_view_transport_method_total{.*view="healthz"' <<<"$body" \
    || fail "/metrics has no request count for healthz"
  grep -q '^manuspectrum_inflight_requests ' <<<"$body" || fail "/metrics has no manuspectrum_ metric"
  ok "/metrics exposes django and manuspectrum metrics"

  rid="smoke-$(date +%s)-$RANDOM"
  header="$(in_web curl -s -o /dev/null -D - -H 'Host: web' -H "X-Request-ID: $rid" \
    http://127.0.0.1:8000/en/smoke-no-such-page/ | tr -d '\r' | sed -n 's/^[Xx]-[Rr]equest-[Ii][Dd]: //p')"
  expect "X-Request-ID echoed" "$rid" "$header"
  sleep 2
  line="$(compose logs --no-log-prefix --since 5m web | grep -F "$rid" | grep '^{' | tail -n 1)"
  [ -n "$line" ] || fail "no JSON log line carries request id $rid"
  expect "JSON log fields" "manuspectrum||$rid|WARNING|True" \
    "$(json_field '"|".join([r["service"], r["trace_id"], r["request_id"], r["level"], str(r["timestamp"].endswith("+00:00") and bool(r["message"]))])' <<<"$line")"
  if compose logs --no-log-prefix --since 5m web | grep -q '"GET /healthz HTTP'; then
    fail "gunicorn still writes an access log"
  fi
  ok "no gunicorn access log"

  rid="smoke-task-$(date +%s)-$RANDOM"
  in_web env -u PROMETHEUS_MULTIPROC_DIR python manage.py shell -c "
from manuspectrum.observability.context import bound_request_id
from manuspectrum.tasks import prune_data_changes_task
with bound_request_id('$rid'):
    result = prune_data_changes_task.delay()
print(result.get(timeout=120))
" >/dev/null || fail "the prune task did not run"
  body="$(compose exec -T worker curl -fsS http://127.0.0.1:9808/metrics)"
  grep -Eq '^manuspectrum_celery_tasks_total\{[^}]*task="manuspectrum.prune_data_changes"' <<<"$body" \
    || fail "worker metrics have no prune task"
  grep -q '^manuspectrum_data_change_rows ' <<<"$body" || fail "worker metrics have no ledger size"
  ok "worker metrics on :9808"
  sleep 2
  compose logs --no-log-prefix --since 5m worker | grep '^{' | grep -F "$rid" | grep -q 'succeeded' \
    || fail "the worker's success line does not carry the publisher's request id"
  ok "request id followed the task into the worker"
}

# nginx over HTTPS, from the host: the published port, the CA of CERTS_DIR/ca when
# it holds one (CERT_MODE=local) and the public name pinned to 127.0.0.1.
edge_init() {
  PUBLIC="$(env_value DOMAIN_NAMES | cut -d' ' -f1)"
  HTTPS_PORT="$(env_value HTTPS_PORT)"; HTTPS_PORT="${HTTPS_PORT:-443}"
  HTTP_PORT="$(env_value HTTP_PORT)"; HTTP_PORT="${HTTP_PORT:-80}"
  [ -n "$PUBLIC" ] || fail "DOMAIN_NAMES is empty in $ENV_FILE"
  EDGE_CURL_OPTS=(--max-time 60 --resolve "$PUBLIC:$HTTPS_PORT:127.0.0.1" --resolve "$PUBLIC:$HTTP_PORT:127.0.0.1")
  local ca
  ca="$(env_value CERTS_DIR)/ca/ca.crt"
  if [ -f "$ca" ]; then EDGE_CURL_OPTS+=(--cacert "$ca"); fi
}
edge_url() { printf 'https://%s:%s%s' "$PUBLIC" "$HTTPS_PORT" "$1"; }
edge_get() { curl -sS "${EDGE_CURL_OPTS[@]}" "${@:2}" "$(edge_url "$1")"; } # edge_get PATH [curl args]
edge_code() { edge_get "$1" -o /dev/null -w '%{http_code}' "${@:2}"; }
edge_headers() { edge_get "$1" -o /dev/null -D - "${@:2}" | tr -d '\r'; }
header_count() { grep -ci "^$1:" <<<"$2" || true; } # header_count NAME HEADERS
header_value() { sed -n "s/^$1: *//Ip" <<<"$2" | head -n 1 | tr -d '\r' | sed 's/[[:space:]]*$//'; } # header_value NAME HEADERS
# The status line without CR or trailing blanks (HTTP/2 has an empty reason: "HTTP/2 200 ").
status_line() { head -n 1 <<<"$1" | tr -d '\r' | sed 's/[[:space:]]*$//'; }

# Writes one uploaded file, one image and the File row of the file; EDGE_FILE_ID
# is the row's id. cleanup_edge removes all three, also when a check fails.
EDGE_FILE_ID=
EDGE_IMAGE_NAME=smoke-iiif.png
edge_fixtures() {
  EDGE_FILE_ID="$(in_web env -u PROMETHEUS_MULTIPROC_DIR python manage.py shell -c '
import os
from django.conf import settings
from arches.app.models.models import File
from PIL import Image
folder = os.path.join(settings.MEDIA_ROOT, "uploadedfiles")
rel = "uploadedfiles/smoke file \u00e9.csv"
with open(os.path.join(settings.MEDIA_ROOT, rel), "wb") as handle:
    handle.write(b"edge,smoke\n1,2\n")
Image.new("RGB", (64, 48), "white").save(os.path.join(folder, "smoke-iiif.png"))
for name in (rel, "uploadedfiles/smoke-iiif.png"):
    os.chmod(os.path.join(settings.MEDIA_ROOT, name), 0o640)
File.objects.filter(path=rel).delete()
print(File.objects.bulk_create([File(path=rel)])[0].pk)
' | tail -n 1)"
  [ -n "$EDGE_FILE_ID" ] || fail "could not create the File row"
}
cleanup_edge() {
  trap - EXIT
  in_web env -u PROMETHEUS_MULTIPROC_DIR python manage.py shell -c '
import os
from django.conf import settings
from arches.app.models.models import File
rel = "uploadedfiles/smoke file \u00e9.csv"
File.objects.filter(path=rel).delete()
for name in (rel, "uploadedfiles/smoke-iiif.png"):
    try:
        os.remove(os.path.join(settings.MEDIA_ROOT, name))
    except FileNotFoundError:
        pass
' >/dev/null 2>&1 || true
}

cmd_edge() {
  local headers body name rid line uuid codes
  edge_init
  trap cleanup_edge EXIT

  expect "published ports" "nginx:443,nginx:80" "$(compose ps --format json | python3 -c '
import json, sys
text = sys.stdin.read().strip()
rows = json.loads(text) if text.startswith("[") else [json.loads(l) for l in text.splitlines() if l]
found = {r["Service"] + ":" + str(p["TargetPort"]) for r in rows for p in r.get("Publishers") or [] if p.get("PublishedPort")}
print(",".join(sorted(found)))
')"
  expect "http redirects to https" "301 https://$PUBLIC/en/" \
    "$(curl -s "${EDGE_CURL_OPTS[@]}" -o /dev/null -w '%{http_code} %{redirect_url}' "http://$PUBLIC:$HTTP_PORT/en/")"
  expect "unknown Host on port 80 is closed" 000 \
    "$(curl -s "${EDGE_CURL_OPTS[@]}" -H 'Host: unknown.invalid' -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HTTP_PORT/")"

  expect "/healthz through nginx" ok "$(edge_get /healthz)"
  expect "/metrics through nginx" 404 "$(edge_code /metrics)"
  expect "/readyz through nginx" 404 "$(edge_code /readyz)"

  headers="$(edge_headers /en/)"
  expect "/en/ through nginx" "HTTP/2 200" "$(status_line "$headers")"
  for name in strict-transport-security permissions-policy content-security-policy-report-only \
    x-content-type-options x-frame-options referrer-policy; do
    expect "header $name sent once" 1 "$(header_count "$name" "$headers")"
  done
  expect "HSTS max-age" "max-age=$(env_value HSTS_MAX_AGE)" "$(header_value strict-transport-security "$headers")"

  for name in /en/api/resource/x /en/api/tile/x/y /en/api/tile-list-create/x/y/z /en/api/tile-new-resource/x/y /en/silk/requests/; do
    headers="$(edge_headers "$name")"
    expect "$name denied by nginx" "404 0" \
      "$(status_line "$headers" | cut -d' ' -f2) $(header_count x-request-id "$headers")"
  done
  uuid="$(python3 -c 'import uuid; print(uuid.uuid4())')"
  headers="$(edge_headers "/en/api/tiles/$uuid")"
  expect "/en/api/tiles/<uuid> reaches Django" 1 "$(header_count x-request-id "$headers")"

  name=/fr/api/search/export_results
  for body in "?format=tilecsv" "" "?format=geojson&format=tilecsv" "?format=geojson&form%61t=shp" "?format=tilecsv&format=geojson"; do
    expect "search export $name$body denied" 404 "$(edge_code "$name$body")"
  done
  expect "POST /fr/temp_file denied" 404 "$(edge_code /fr/temp_file -X POST)"
  expect "/files/archestemp/x.zip" 404 "$(edge_code /files/archestemp/x.zip)"

  edge_fixtures
  body="$(edge_get "/en/files/$EDGE_FILE_ID"; echo x)"
  expect "uploaded file through FileView and nginx" $'edge,smoke\n1,2\nx' "$body"
  headers="$(edge_headers "/en/files/$EDGE_FILE_ID")"
  expect "uploaded file status" "HTTP/2 200" "$(status_line "$headers")"
  expect "the internal redirect is not exposed" 0 "$(header_count location "$headers")"
  expect "uploaded file direct path" 404 "$(edge_code '/files/uploadedfiles/smoke%20file%20%C3%A9.csv')"

  headers="$(edge_headers "/iiifserver/iiif/3/$EDGE_IMAGE_NAME/info.json" -H 'Origin: https://viewer.example')"
  expect "/iiifserver/ info.json" "HTTP/2 200" "$(status_line "$headers")"
  expect "one Access-Control-Allow-Origin on /iiifserver/" 1 "$(header_count access-control-allow-origin "$headers")"
  expect "Access-Control-Allow-Origin value" "*" "$(header_value access-control-allow-origin "$headers")"
  expect "/iiifserver/admin" 404 "$(edge_code /iiifserver/admin)"
  body="$(edge_get "/iiifserver/iiif/2/$EDGE_IMAGE_NAME/info.json")"
  expect "info.json carries https ids" "https://$PUBLIC/iiifserver/iiif/2/$EDGE_IMAGE_NAME" "$(json_field 'r["@id"]' <<<"$body")"
  expect "web reaches the public name through nginx" "200 https://$PUBLIC/iiifserver/iiif/2/$EDGE_IMAGE_NAME" \
    "$(web_public_info "$PUBLIC" | tail -n 1)"

  headers="$(edge_headers /en/auth/ -H 'X-Forwarded-Ssl: on' -H 'X-Forwarded-Protocol: ssl')"
  expect "forged scheme headers" "HTTP/2 200" "$(status_line "$headers")"

  rid="/en/smoke-edge-$RANDOM$RANDOM/"
  headers="$(edge_headers "$rid")"
  sleep 1
  line="$(grep -F "\"uri\":\"$rid\"" "$(env_value NGINX_LOG_HOST_DIR)/access.log" | tail -n 1)" \
    || fail "no access log line for $rid in $(env_value NGINX_LOG_HOST_DIR)/access.log"
  expect "access log request_id is the one Django echoed" "$(header_value x-request-id "$headers")" \
    "$(json_field 'r["request_id"]' <<<"$line")"
  expect "access log fields" "404|HTTP/2.0|$PUBLIC" \
    "$(json_field '"|".join([str(r["status"]), r["protocol"], r["host"]])' <<<"$line")"

  body="$(compose exec -T nginx nginx -T 2>&1)"
  grep -q 'proxy_read_timeout 340s' <<<"$body" || fail "nginx has no proxy_read_timeout 340s for create-all"
  ok "create-all read timeout"

  codes=""
  for _ in 1 2 3 4 5 6 7; do codes="$codes $(edge_code /en/auth/ -X POST -d username=smoke-edge)"; done
  case "$codes" in *429*) ok "7 POSTs to /en/auth/: one is 429 ($codes )" ;; *) fail "no 429 after 7 POSTs to /en/auth/:$codes" ;; esac
  cleanup_edge
}

# web fetches the public image-service URL, as Arches' manifest manager does:
# the name resolves to nginx on the internal network, and the local CA (when
# mounted) is in the bundle the entrypoint builds.
web_public_info() { # web_public_info HOST
  local ca=()
  if [ -n "$(env_value LOCAL_CA_CERT)" ]; then ca=(REQUESTS_CA_BUNDLE=/tmp/ca-bundle.pem); fi
  in_web env ${ca[@]+"${ca[@]}"} PUBLIC="$1" EDGE_IMAGE="$EDGE_IMAGE_NAME" python -c '
import os, requests
r = requests.get("https://%s/iiifserver/iiif/2/%s/info.json" % (os.environ["PUBLIC"], os.environ["EDGE_IMAGE"]), timeout=20)
print(r.status_code, r.json()["@id"])
'
}

cmd_readiness() {
  compose stop elasticsearch >/dev/null
  expect "/readyz with Elasticsearch stopped" 503 "$(http_code /readyz)"
  expect "/readyz names Elasticsearch" "True" \
    "$(in_web curl -s -H 'Host: web' http://127.0.0.1:8000/readyz \
      | json_field 'r["components"]["elasticsearch"]["status"] in ("down", "timeout")')"
  compose start elasticsearch >/dev/null
  cmd_wait
  expect "/readyz after Elasticsearch restarted" 200 "$(http_code /readyz)"
}

cmd_clean() {
  psql_app "DROP TABLE IF EXISTS ms_smoke_marker" >/dev/null
  es DELETE /ms-smoke-marker >/dev/null || true
  redis redis-broker -n 5 DEL ms-smoke-marker >/dev/null
  in_web rm -f /srv/media/.ms-smoke-marker /srv/media/uploadedfiles/.ms-smoke-marker
  rm -f "$SMOKE_STATE"
  ok "markers removed"
}

case "${1:-}" in
  wait) cmd_wait ;;
  check) cmd_check ;;
  mark) cmd_mark ;;
  survived) cmd_survived ;;
  lose) cmd_lose ;;
  static-swap) cmd_static_swap ;;
  init-guard) cmd_init_guard ;;
  observability) cmd_observability ;;
  edge) cmd_edge ;;
  readiness) cmd_readiness ;;
  clean) cmd_clean ;;
  *) sed -n '2,23p' "$0" >&2; exit 2 ;;
esac
