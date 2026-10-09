#!/usr/bin/env bash
# deploy/docker/tests/test_publish_static.sh
# Tests for publish-static.sh. Prints `ok N` / `not ok N`; exits non-zero on failure.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLISH="$HERE/../publish-static.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

make_source() { # make_source DIR BUILD-ID CONTENT
  mkdir -p "$1/css"
  printf '%s' "$3" >"$1/css/site.css"
  printf '%s\n' "$2" >"$1/.build-id"
}

A=aaaaaaaaaaaaaaaa B=bbbbbbbbbbbbbbbb C=cccccccccccccccc
make_source "$TMP/a" "$A" "one"
make_source "$TMP/b" "$B" "two"
make_source "$TMP/c" "$C" "three"
D="$TMP/static"

# 1. first publication
bash "$PUBLISH" "$TMP/a" "$D" >/dev/null
[ -L "$D/current" ] && [ "$(readlink "$D/current")" = "releases/$A" ] \
  && [ "$(cat "$D/current/css/site.css")" = one ] && [ -f "$D/releases/$A/.complete" ]
# shellcheck disable=SC2319 # $? is the status of the whole && list above
assert "first publication copies the release and points current at it" "$?"

# 2. same image again: nothing is copied
inode="$(stat -c %i "$D/releases/$A/css/site.css")"
out="$(bash "$PUBLISH" "$TMP/a" "$D")"
[ "$(stat -c %i "$D/releases/$A/css/site.css")" = "$inode" ] && grep -q "already published" <<<"$out"
assert "an already published release is not copied again" "$?"

# 3. new image: current switches, the previous release is kept
bash "$PUBLISH" "$TMP/b" "$D" >/dev/null
[ "$(readlink "$D/current")" = "releases/$B" ] && [ "$(cat "$D/current/css/site.css")" = two ] \
  && [ -d "$D/releases/$A" ]
assert "a new release becomes current and the previous one is kept" "$?"

# 4. older releases are removed
bash "$PUBLISH" "$TMP/c" "$D" >/dev/null
[ ! -e "$D/releases/$A" ] && [ -d "$D/releases/$B" ] && [ -d "$D/releases/$C" ]
assert "releases older than the previous one are removed" "$?"

# 5. an interrupted copy is redone
rm -f "$D/releases/$C/.complete"
mkdir -p "$D/releases/$A.tmp"
bash "$PUBLISH" "$TMP/c" "$D" >/dev/null
[ -f "$D/releases/$C/.complete" ] && [ ! -e "$D/releases/$A.tmp" ] && [ ! -e "$D/releases/$C.tmp" ]
assert "an incomplete release is copied again and leftovers are removed" "$?"

# 6. invalid build id
printf 'not-hex\n' >"$TMP/a/.build-id"
bash "$PUBLISH" "$TMP/a" "$D" >/dev/null 2>&1
rc=$?
[ "$rc" -ne 0 ] && [ "$(readlink "$D/current")" = "releases/$C" ]
assert "an invalid build id is refused and current is untouched" "$?"

# 7. current is never a directory
[ -L "$D/current" ] && [ ! -e "$D/current.new" ]
assert "current stays a symlink and no temporary link is left" "$?"

exit "$failed"
