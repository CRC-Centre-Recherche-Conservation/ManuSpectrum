#!/usr/bin/env bash
# deploy/scripts/tests/test_release_version_guard.sh
# Tests of release-version-guard.sh on a throwaway repository: the base version
# of a tag must equal APP_VERSION at the tagged commit.
# Prints `ok N` / `not ok N`; exits non-zero on failure.
# shellcheck disable=SC2319,SC2015,SC2001
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$HERE/../release-version-guard.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }

REPO="$TMP/repo"
git init -q "$REPO"
cd "$REPO" || exit 1
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@manuspectrum.test GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@manuspectrum.test
git config commit.gpgsign false
git config tag.gpgsign false
mkdir manuspectrum

at() { # at VERSION-ARGS TAG...: commit a settings file carrying VERSION-ARGS and tag it
  local args="$1" t
  shift
  printf 'APP_NAME = "manuspectrum"\nAPP_VERSION = semantic_version.Version(%s)\n' "$args" > manuspectrum/settings.py
  git add manuspectrum/settings.py
  git commit -q -m "$args"
  for t in "$@"; do git tag "$t"; done
}

at "major=1, minor=0, patch=0" v1.0.0 v1.0.0-rc.1 v1.0.1 v1.1.0-rc.1
at 'major=2, minor=0, patch=0, prerelease=("alpha",)' v2.0.0 v2.0.0-rc.1
printf 'APP_NAME = "x"\n' > manuspectrum/settings.py
git commit -qam none
git tag v3.0.0

run() { OUT="$(bash "$GUARD" "$1" 2>&1)"; RC=$?; }
accepts() { run "$1"; [ "$RC" -eq 0 ] && ok "$2" || not_ok "$2 (exit $RC)" "$OUT"; }
refuses() { # refuses TAG NAME MESSAGE-FRAGMENT
  run "$1"
  if [ "$RC" -eq 0 ]; then not_ok "$2 (accepted)" "$OUT"
  elif ! grep -q -- "$3" <<<"$OUT"; then not_ok "$2 (no reason: $3)" "$OUT"
  else ok "$2"; fi
}

accepts v1.0.0 "a final tag equal to APP_VERSION"
accepts v1.0.0-rc.1 "an rc tag whose base equals APP_VERSION"
refuses v1.0.1 "a final tag above APP_VERSION" "::error::.*1\.0\.1.*1\.0\.0"
refuses v1.1.0-rc.1 "an rc tag above APP_VERSION" "::error::.*1\.1\.0.*1\.0\.0"
refuses v2.0.0 "an APP_VERSION that still carries a prerelease" "2\.0\.0-alpha"
refuses v2.0.0-rc.1 "an rc tag on a prerelease APP_VERSION" "2\.0\.0-alpha"
refuses v3.0.0 "a settings file without APP_VERSION" "no APP_VERSION"
refuses v1.2 "a name that is not a release tag" "not a release tag"

# release.yml passes the commit the tag resolves to as the second argument.
OUT="$(bash "$GUARD" v1.0.0 "$(git rev-parse 'v1.0.0^{commit}')" 2>&1)"; RC=$?
[ "$RC" -eq 0 ] && ok "a final tag checked at its commit, as release.yml calls it" \
  || not_ok "a final tag checked at its commit (exit $RC)" "$OUT"

exit "$FAILED"
