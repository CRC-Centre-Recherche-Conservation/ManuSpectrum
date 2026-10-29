#!/usr/bin/env bash
# deploy/scripts/tests/test_release_ruleset_check.sh
# Tests of release-ruleset-check.sh with a fake `gh` that serves canned
# rulesets. Prints `ok N` / `not ok N`; exits non-zero on failure.
# shellcheck disable=SC2319,SC2015,SC2001
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="$HERE/../release-ruleset-check.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }

mkdir -p "$TMP/bin" "$TMP/api"
cat >"$TMP/bin/gh" <<'SH'
#!/bin/sh
[ "$1" = api ] || exit 2
shift
[ "$1" = --paginate ] && shift
path="${1%%\?*}"
file="$FAKE_API/$(printf '%s' "$path" | tr '/' '_')"
[ -f "$file" ] || { echo "HTTP 403: Resource not accessible" >&2; exit 1; }
cat "$file"
SH
chmod +x "$TMP/bin/gh"

R=OWNER/REPO
serve() { printf '%s' "$2" >"$TMP/api/$(printf '%s' "$1" | tr '/' '_')"; }
reset() { rm -f "$TMP/api"/*; }
run() { OUT="$(PATH="$TMP/bin:$PATH" FAKE_API="$TMP/api" bash "$CHECK" "$R" 2>&1)"; RC=$?; }
accepts() { run; [ "$RC" -eq 0 ] && ok "$1" || not_ok "$1 (exit $RC)" "$OUT"; }
refuses() { run; if [ "$RC" -eq 0 ]; then not_ok "$1 (accepted)" "$OUT"; else ok "$1"; fi; }

ruleset() { # ruleset INCLUDE EXCLUDE RULES...
  inc="$1"; exc="$2"; shift 2
  rules=""
  for r in "$@"; do rules="$rules{\"type\":\"$r\"},"; done
  printf '{"id":7,"target":"tag","enforcement":"active","conditions":{"ref_name":{"include":[%s],"exclude":[%s]}},"current_user_can_bypass":"%s","rules":[%s{"type":"non_fast_forward"}]}' "$inc" "$exc" "${BYPASS:-never}" "$rules"
}
list() { serve "repos/$R/rulesets" "$1"; }

reset
list '[{"id":7,"target":"tag","enforcement":"active"}]'
serve "repos/$R/rulesets/7" "$(ruleset '"refs/tags/v*"' '' creation update deletion)"
accepts "a tag ruleset on v* with creation, update and deletion"

serve "repos/$R/rulesets/7" "$(ruleset '"~ALL"' '' creation update deletion)"
accepts "a ruleset on every tag"

serve "repos/$R/rulesets/7" "$(ruleset '"refs/tags/v*"' '' update deletion)"
refuses "a ruleset without the creation rule"

serve "repos/$R/rulesets/7" "$(ruleset '"refs/tags/v*"' '' creation update)"
refuses "a ruleset that lets tags be deleted"

serve "repos/$R/rulesets/7" "$(ruleset '"refs/tags/release-*"' '' creation update deletion)"
refuses "a ruleset on other tags"

serve "repos/$R/rulesets/7" "$(ruleset '"refs/tags/v*"' '"refs/tags/v*"' creation update deletion)"
refuses "a ruleset that excludes v*"

BYPASS=always; export BYPASS
serve "repos/$R/rulesets/7" "$(ruleset '"refs/tags/v*"' '' creation update deletion)"
refuses "a ruleset the caller can always bypass"
BYPASS=pull_requests_only
serve "repos/$R/rulesets/7" "$(ruleset '"refs/tags/v*"' '' creation update deletion)"
refuses "a ruleset the caller can bypass on pull requests"
unset BYPASS
serve "repos/$R/rulesets/7" '{"id":7,"target":"tag","enforcement":"active","conditions":{"ref_name":{"include":["refs/tags/v*"],"exclude":[]}},"rules":[{"type":"creation"},{"type":"update"},{"type":"deletion"}]}'
refuses "a ruleset without current_user_can_bypass (fails closed)"
serve "repos/$R/rulesets/7" "$(ruleset '"refs/tags/v*"' '' creation update deletion)"

list '[{"id":3,"target":"branch","enforcement":"active"}][{"id":7,"target":"tag","enforcement":"active"}]'
serve "repos/$R/rulesets/3" "$(ruleset '"refs/heads/main"' '' creation update deletion)"
accepts "the tag ruleset on the second page of the list"
list '[{"id":7,"target":"tag","enforcement":"active"}]'

list '[{"id":7,"target":"tag","enforcement":"evaluate"}]'
refuses "a ruleset that is not enforced"

list '[{"id":7,"target":"branch","enforcement":"active"}]'
refuses "a branch ruleset"

list '[]'
refuses "no ruleset at all"

reset
refuses "an unreadable API fails closed"

exit "$FAILED"
