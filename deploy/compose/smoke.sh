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
#   readiness    /readyz answers 503 while Elasticsearch is stopped, 200 after
#                (CI and rehearsal only)
#   clean        remove the markers
# mark, static-swap, init-guard, readiness and clean are for CI and rehearsal only.
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
    || fail "Cantaloupe cannot list /imageroot"
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

cmd_static_swap() {
  in_web sh -c 'mkdir -p /srv/static/releases/smoke-stale && ln -sfn releases/smoke-stale /srv/static/current'
  compose restart web >/dev/null
  cmd_wait
  expect "static current after restart" "releases/$(build_id)" "$(in_web readlink /srv/static/current)"
  in_web test -d /srv/static/releases/smoke-stale || fail "previous release removed too early"
  ok "previous release kept"
  compose restart web >/dev/null
  cmd_wait
  if in_web test -e /srv/static/releases/smoke-stale; then fail "stale release not pruned"; fi
  ok "stale release pruned"
}

cmd_init_guard() {
  local out
  if out="$(compose run --rm --no-deps -T web init 2>&1)"; then fail "init ran on a live database"; fi
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
  static-swap) cmd_static_swap ;;
  init-guard) cmd_init_guard ;;
  observability) cmd_observability ;;
  readiness) cmd_readiness ;;
  clean) cmd_clean ;;
  *) sed -n '2,16p' "$0" >&2; exit 2 ;;
esac
