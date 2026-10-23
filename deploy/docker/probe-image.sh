#!/usr/bin/env bash
# Checks a built image without starting any service: it runs under an
# arbitrary uid on a read-only root, ships no build tool and no development
# file, and passes the Arches cache check of `check --deploy`.
# Usage: probe-image.sh IMAGE
set -euo pipefail

IMAGE="${1:?usage: probe-image.sh IMAGE}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; }
run() {
  docker run --rm --read-only --tmpfs /tmp:rw,nosuid,nodev --user 4242:4242 \
    --env-file "$HERE/placeholder.env" --entrypoint "" "$IMAGE" "$@"
}

[ "$(docker image inspect --format '{{.Config.User}}' "$IMAGE")" = "10001:10001" ] \
  || fail "default user is not 10001:10001"
ok "default user 10001:10001"

run python -c 'import django; django.setup()' || fail "django.setup() under uid 4242 on a read-only root"
ok "Django starts under an arbitrary uid on a read-only root"

out="$(run python manage.py check --deploy --tag security 2>&1 || true)"
if grep -Eq 'arches\.(W|E)001' <<<"$out"; then
  echo "$out" >&2
  fail "Arches reports a cache without rate limiting"
fi
ok "check --deploy: no arches.W001/E001"

# Arches' compatibility check reads /app/pyproject.toml; when it raises, every
# manage.py command of the running stack stops.
out="$(run python manage.py check --tag compatibility 2>&1)" \
  || { echo "$out" >&2; fail "manage.py check --tag compatibility"; }
ok "check --tag compatibility (Arches version against pyproject.toml)"

run sh -c 'test ! -e /app/manuspectrum/settings_local.py' || fail "settings_local.py in the image"
run sh -c '! command -v uv && ! command -v node && ! command -v npm && ! command -v gcc' >/dev/null \
  || fail "a build tool is in the runtime image"
run python -c 'import importlib.util, sys; sys.exit(importlib.util.find_spec("pip") is not None)' \
  || fail "pip is in the runtime image"
run python -c 'import importlib.util, sys; sys.exit(importlib.util.find_spec("silk") is not None)' \
  || fail "django-silk is installed"
ok "no development file, build tool, pip or silk"

run python -c 'import gunicorn; assert gunicorn.__version__.split(".")[0] == "26", gunicorn.__version__' \
  || fail "gunicorn 26 missing"
run python -c 'import redis' || fail "redis-py missing (Celery broker, Django RedisCache)"
run sh -c 'grep -Eq "^[0-9a-f]{16}$" /app/static/.build-id' || fail "static .build-id"
run python -c 'import json; assert json.load(open("/app/webpack/webpack-stats.json"))["status"] == "done"' \
  || fail "webpack-stats.json"
run sh -c 'test -L /app/frontend_configuration' || fail "frontend_configuration is not the /tmp symlink"
ok "gunicorn 26, redis-py, static build id, webpack stats, frontend_configuration symlink"

writable="$(run sh -c 'find /app /opt/venv -xdev -perm -o+w ! -type l -print -quit')"
[ -z "$writable" ] || fail "world-writable path in the image: $writable"
ok "code and static files are not writable"

echo "probe-image.sh: all green."
