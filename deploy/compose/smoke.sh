#!/usr/bin/env bash
# Checks a running stack (CI runner, rehearsal VM). Usage: smoke.sh COMMAND
#   wait         wait until every service is healthy (or running, for beat)
#   check        read-only assertions on the stack (safe in production)
#   mark         write one marker per store: PostgreSQL, Elasticsearch,
#                redis-broker, media; remembered in SMOKE_STATE
#   survived     the markers written by `mark` are still there
#   static-swap  a stale `current` static release is replaced on web restart
#   init-guard   `init` and `manage setup_db` are refused on a live database
#   clean        remove the markers
# mark, static-swap, init-guard and clean are for CI and rehearsal only.
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
  in_web sh -c 'printf %s "$0" > /srv/media/.ms-smoke-marker' "$token"
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
}

cmd_clean() {
  psql_app "DROP TABLE IF EXISTS ms_smoke_marker" >/dev/null
  es DELETE /ms-smoke-marker >/dev/null || true
  redis redis-broker -n 5 DEL ms-smoke-marker >/dev/null
  in_web rm -f /srv/media/.ms-smoke-marker
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
  clean) cmd_clean ;;
  *) sed -n '2,11p' "$0" >&2; exit 2 ;;
esac
