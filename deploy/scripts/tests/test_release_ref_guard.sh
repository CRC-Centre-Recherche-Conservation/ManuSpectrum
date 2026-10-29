#!/usr/bin/env bash
# deploy/scripts/tests/test_release_ref_guard.sh
# Tests of release-ref-guard.sh on a throwaway repository: a final tag must sit
# on the first-parent line of main, a release-candidate tag on the integration
# branch, and any other name is refused. Prints `ok N` / `not ok N`; exits non-zero on failure.
# shellcheck disable=SC2319,SC2015,SC2001
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="$HERE/../release-ref-guard.sh"
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
commit() { git commit -q --allow-empty -m "$1"; git rev-parse HEAD; }

# A <- C (integration only); A <- D (main only).
A="$(commit a)"
git checkout -q -b integration
C="$(commit c)"
git checkout -q -b mainline "$A"
D="$(commit d)"
# A <- E (side branch), merged into main by M (parents D, E): E is an
# ancestor of main but not on its first-parent line.
git checkout -q -b side "$A"
E="$(commit e)"
git checkout -q mainline
git merge -q --no-ff -m merge side
M="$(git rev-parse HEAD)"
git update-ref refs/remotes/origin/main "$M"
git update-ref refs/remotes/origin/dev "$C"
git tag v1.0.0 "$A"
git tag v1.0.1 "$C"
git tag v1.1.0 "$D"
git tag v1.0.0-rc.1 "$C"
git tag v1.0.0-rc.2 "$D"
git tag -a v1.2.0 -m annotated "$D"
git tag v1.2 "$A"
git tag v1.2.3-beta "$A"
git tag v1.2.3-rc "$A"
git tag V1.0.0 "$A"
git tag v01.0.0 "$A"
git tag v2.0.0 "$E"
git tag v2.0.1 "$M"
git tag v2.0.0-rc.1 "$E"

run() { OUT="$(bash "$GUARD" "$1" 2>&1)"; RC=$?; }
accepts() { run "$1"; [ "$RC" -eq 0 ] && ok "$2" || not_ok "$2 (exit $RC)" "$OUT"; }
refuses() { # refuses TAG NAME MESSAGE-FRAGMENT
  run "$1"
  if [ "$RC" -eq 0 ]; then not_ok "$2 (accepted)" "$OUT"
  elif ! grep -q -- "$3" <<<"$OUT"; then not_ok "$2 (no reason: $3)" "$OUT"
  else ok "$2"; fi
}

accepts v1.0.0 "a final tag on an ancestor of main"
accepts v1.1.0 "a final tag on the tip of main"
accepts v1.2.0 "an annotated final tag on main"
refuses v1.0.1 "a final tag outside main" "main"
refuses v2.0.0 "a final tag merged into main but not on its first-parent line" "first-parent"
accepts v2.0.1 "a final tag on the merge commit of main"
accepts v1.0.0-rc.1 "an rc tag on the integration branch"
refuses v2.0.0-rc.1 "an rc tag on a commit the integration branch does not hold" "dev"
refuses v1.0.0-rc.2 "an rc tag on a commit only main holds" "dev"
refuses v1.2 "v1.2" "not a release tag"
refuses v1.2.3-beta "v1.2.3-beta" "not a release tag"
refuses v1.2.3-rc "v1.2.3-rc" "not a release tag"
refuses V1.0.0 "an upper-case V" "not a release tag"
refuses v01.0.0 "a leading zero" "not a release tag"
refuses v9.9.9 "a tag that does not exist" "not a release tag\|no such tag"

OUT="$(bash "$GUARD" v1.0.0 2>/dev/null)"
[ "$OUT" = "$A" ] && ok "the commit is printed on stdout" || not_ok "the commit is printed on stdout" "$OUT"

OUT="$(MAIN_REF=refs/remotes/origin/absent bash "$GUARD" v1.0.0 2>&1)"; RC=$?
{ [ "$RC" -ne 0 ] && grep -q "refs/remotes/origin/absent" <<<"$OUT"; } && ok "a missing main ref is an error, not a pass" \
  || not_ok "a missing main ref is an error, not a pass (exit $RC)" "$OUT"

exit "$FAILED"
