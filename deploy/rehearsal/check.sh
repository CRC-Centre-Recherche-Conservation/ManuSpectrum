#!/usr/bin/env bash
# Lints and tests the rehearsal kit: shellcheck, render tests, autoinstall
# schema validation, network.xml well-formedness, gitleaks. Stops at the
# first failure; a tool that is unavailable is announced as `skip`.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

SHELLCHECK_IMAGE="koalaman/shellcheck:v0.10.0"
GITLEAKS_IMAGE="zricethezav/gitleaks:v8.30.1"
# autoinstall-schema.json of canonical/subiquity, commit of 2026-03-03.
SCHEMA_COMMIT="48bade6d7bbcc7d72a72e74a92c220f76d9017f2"
SCHEMA_URL="https://raw.githubusercontent.com/canonical/subiquity/${SCHEMA_COMMIT}/autoinstall-schema.json"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [-h]

Checks the rehearsal kit: shellcheck, render tests, autoinstall schema,
network XML, gitleaks. Stops at the first failure; a missing tool is reported as "skip".
USAGE
}
case "${1:-}" in
  -h | --help) usage; exit 0 ;;
  "") ;;
  *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

step() { echo; echo "== $1"; }
skip() { echo "skip: $1"; }

step "shellcheck"
if command -v docker >/dev/null 2>&1; then
  scripts=()
  for f in "$HERE"/*.sh "$HERE"/tests/*.sh; do scripts+=("${f#"$ROOT"/}"); done
  docker run --rm -v "$ROOT:/mnt:ro" -w /mnt "$SHELLCHECK_IMAGE" "${scripts[@]}"
  echo "shellcheck: no warning"
else
  skip "docker missing"
fi

step "seed render tests"
bash "$HERE/tests/test_render_seed.sh"

step "autoinstall schema"
validator=()
if command -v uvx >/dev/null 2>&1; then
  validator=(uvx --from jsonschema jsonschema)
elif "$ROOT/../venv/bin/python" -c 'import jsonschema' >/dev/null 2>&1; then
  validator=("$ROOT/../venv/bin/python" -m jsonschema)
fi
yaml_python=""
for candidate in python3 "$ROOT/../venv/bin/python"; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import yaml' >/dev/null 2>&1; then
    yaml_python="$candidate"
    break
  fi
done
if [ "${#validator[@]}" -eq 0 ]; then
  skip "neither uvx nor jsonschema in ../venv"
elif [ -z "$yaml_python" ]; then
  skip "PyYAML not found"
elif ! curl -fsSL "$SCHEMA_URL" -o "$TMP/schema.json"; then
  skip "schema unreachable (${SCHEMA_URL})"
else
  printf '%s\n' 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeFakeFakeFakeFakeFakeFakeFakeFake0123 test@example' >"$TMP/key.pub"
  # shellcheck disable=SC2016
  "$HERE/render-seed.sh" --out "$TMP/seed" --pubkey "$TMP/key.pub" \
    --password-hash '$6$fakesalt$FakeHashFakeHashFakeHashFakeHashFakeHashFakeHashFakeHashFakeHash' >/dev/null
  "$yaml_python" - "$TMP/seed/user-data" "$TMP/autoinstall.json" <<'PY'
import json
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as src:
    document = yaml.safe_load(src)
with open(sys.argv[2], "w", encoding="utf-8") as out:
    json.dump(document["autoinstall"], out)
PY
  "${validator[@]}" --instance "$TMP/autoinstall.json" "$TMP/schema.json"
  echo "autoinstall schema: valid (subiquity ${SCHEMA_COMMIT:0:12})"
fi

step "network.xml"
if command -v xmllint >/dev/null 2>&1; then
  xmllint --noout "$HERE/network.xml"
  echo "network.xml: well-formed"
else
  skip "xmllint missing"
fi

step "gitleaks"
if command -v docker >/dev/null 2>&1; then
  docker run --rm -v "$ROOT:/repo:ro" "$GITLEAKS_IMAGE" dir /repo/deploy --no-banner
else
  skip "docker missing"
fi

echo
echo "check.sh: all green."
