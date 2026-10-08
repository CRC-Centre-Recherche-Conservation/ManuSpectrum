#!/usr/bin/env bash
# Offline checks of the image and Compose files: shellcheck, hadolint, the
# publish-static, entrypoint guard, load-snapshot, backup, restore-test, restic round trip,
# secret-set, local CA, nginx edge and logrotate tests, the Compose rules, actionlint, uv.lock freshness and
# gitleaks (its tests, then a scan of the whole tree). Builds no image and
# starts no stack (the tests run small stub containers; logrotate needs the
# network once): safe on the development VM.
# The ACME flow against Pebble (deploy/certs/tests/test_acme_pebble.sh) runs in CI only.
# Stops at the first failure.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

SHELLCHECK_IMAGE="koalaman/shellcheck:v0.10.0@sha256:2097951f02e735b613f4a34de20c40f937a6c8f18ecb170612c88c34517221fb"
HADOLINT_IMAGE="hadolint/hadolint:v2.15.1@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d"
ACTIONLINT_IMAGE="rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"
UV_IMAGE="ghcr.io/astral-sh/uv:0.12.20-python3.13-trixie-slim@sha256:520ead6668d302a3d307d63e3b2b02a3205e69f503dfc1af836d609d3ff591e0"

step() { echo; echo "== $1"; }
cd "$ROOT"

step "shellcheck"
docker run --rm -v "$ROOT:/mnt:ro" -w /mnt "$SHELLCHECK_IMAGE" -x \
  deploy/check-stack.sh deploy/docker/*.sh deploy/docker/tests/*.sh deploy/compose/*.sh \
  deploy/compose/certbot/*.sh deploy/compose/nginx/tests/*.sh \
  deploy/scripts/*.sh deploy/scripts/tests/*.sh \
  deploy/certs/*.sh deploy/certs/tests/*.sh deploy/logrotate/tests/*.sh
echo "shellcheck: no warning"

step "hadolint"
docker run --rm -i "$HADOLINT_IMAGE" <deploy/docker/Dockerfile
echo "hadolint: no warning"

step "publish-static tests"
bash deploy/docker/tests/test_publish_static.sh

step "entrypoint guard tests"
bash deploy/docker/tests/test_entrypoint_guard.sh

step "load-snapshot tests"
bash deploy/scripts/tests/test_load_snapshot.sh

step "backup tests"
bash deploy/scripts/tests/test_backup.sh

step "restore-test tests"
bash deploy/scripts/tests/test_restore_test.sh

step "restic round trip"
bash deploy/scripts/tests/test_restic_roundtrip.sh

step "secret-set tests"
bash deploy/scripts/tests/test_secret_set.sh

step "local CA tests"
bash deploy/certs/tests/test_make_local_ca.sh

step "nginx edge tests"
bash deploy/compose/nginx/tests/test_edge.sh

step "logrotate tests"
bash deploy/logrotate/tests/test_logrotate.sh

step "Compose rules"
python3 -m unittest discover -s deploy/compose/tests -p 'test_*.py'

step "actionlint"
docker run --rm -v "$ROOT:/repo:ro" -w /repo "$ACTIONLINT_IMAGE" \
  .github/workflows/deploy-lint.yml .github/workflows/trivy-weekly.yml .github/workflows/pip-audit.yml \
  .github/workflows/cache-cleanup.yml .github/workflows/secret-scan.yml
echo "actionlint: no warning"

step "uv.lock"
docker run --rm -v "$ROOT:/src:ro" -w /src -e UV_CACHE_DIR=/tmp/uv-cache \
  -e UV_PYTHON_DOWNLOADS=never "$UV_IMAGE" uv lock --check

step "gitleaks tests"
bash deploy/scripts/tests/test_gitleaks.sh

step "gitleaks"
bash deploy/scripts/gitleaks.sh tree

echo
echo "check-stack.sh: all green."
