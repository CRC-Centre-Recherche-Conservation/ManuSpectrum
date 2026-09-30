#!/usr/bin/env bash
# Offline checks of the image and Compose files: shellcheck, hadolint, the
# publish-static tests, the Compose rules, actionlint, uv.lock freshness and
# gitleaks. Builds nothing and starts no service: safe on the development VM.
# Stops at the first failure.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"

SHELLCHECK_IMAGE="koalaman/shellcheck:v0.10.0@sha256:2097951f02e735b613f4a34de20c40f937a6c8f18ecb170612c88c34517221fb"
HADOLINT_IMAGE="hadolint/hadolint:v2.15.1@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d"
ACTIONLINT_IMAGE="rhysd/actionlint:1.7.12@sha256:b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667"
UV_IMAGE="ghcr.io/astral-sh/uv:0.12.20-python3.13-trixie-slim@sha256:520ead6668d302a3d307d63e3b2b02a3205e69f503dfc1af836d609d3ff591e0"
GITLEAKS_IMAGE="zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f"

step() { echo; echo "== $1"; }
cd "$ROOT"

step "shellcheck"
docker run --rm -v "$ROOT:/mnt:ro" -w /mnt "$SHELLCHECK_IMAGE" \
  deploy/check-stack.sh deploy/docker/*.sh deploy/docker/tests/*.sh deploy/compose/*.sh
echo "shellcheck: no warning"

step "hadolint"
docker run --rm -i "$HADOLINT_IMAGE" <deploy/docker/Dockerfile
echo "hadolint: no warning"

step "publish-static tests"
bash deploy/docker/tests/test_publish_static.sh

step "Compose rules"
python3 -m unittest discover -s deploy/compose/tests -p 'test_*.py'

step "actionlint"
docker run --rm -v "$ROOT:/repo:ro" -w /repo "$ACTIONLINT_IMAGE" \
  .github/workflows/deploy-lint.yml .github/workflows/trivy-weekly.yml .github/workflows/pip-audit.yml
echo "actionlint: no warning"

step "uv.lock"
docker run --rm -v "$ROOT:/src:ro" -w /src -e UV_CACHE_DIR=/tmp/uv-cache \
  -e UV_PYTHON_DOWNLOADS=never "$UV_IMAGE" uv lock --check

step "gitleaks"
docker run --rm -v "$ROOT:/repo:ro" "$GITLEAKS_IMAGE" dir /repo/deploy --config /repo/.gitleaks.toml --no-banner

echo
echo "check-stack.sh: all green."
