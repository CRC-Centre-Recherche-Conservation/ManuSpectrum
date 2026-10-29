#!/usr/bin/env bash
# deploy/scripts/tests/test_release_ref_guard.sh
# Tests of release-ref-guard.sh on a throwaway repository: a final tag must sit
# on the first-parent line of main, a release-candidate tag on the integration
# branch dev/<its version> (dev/X.Y.Z, dev/X.Y.x or dev/X.x.x), and any other
# name is refused. Prints `ok N` / `not ok N`; exits non-zero on failure.
# shellcheck disable=SC2319,SC2015,SC2001
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="${GUARD:-$HERE/../release-ref-guard.sh}"
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
git update-ref refs/remotes/origin/dev/1.x.x "$C"
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
refuses v2.0.0-rc.1 "an rc tag on a commit the integration branch does not hold" "dev/2.0.0"
refuses v1.0.0-rc.2 "an rc tag on a commit only main holds" "dev/1.0.0"
refuses v1.2 "v1.2" "not a release tag"
refuses v1.2.3-beta "v1.2.3-beta" "not a release tag"
refuses v1.2.3-rc "v1.2.3-rc" "not a release tag"
refuses V1.0.0 "an upper-case V" "not a release tag"
refuses v01.0.0 "a leading zero" "not a release tag"
refuses v9.9.9 "a tag that does not exist" "not a release tag\|no such tag"

OUT="$(bash "$GUARD" v1.0.0 2>/dev/null | head -n 1)"
[ "$OUT" = "$A" ] && ok "the commit is printed first on stdout" || not_ok "the commit is printed first on stdout" "$OUT"

OUT="$(MAIN_REF=refs/remotes/origin/absent bash "$GUARD" v1.0.0 2>&1)"; RC=$?
{ [ "$RC" -ne 0 ] && grep -q "refs/remotes/origin/absent" <<<"$OUT"; } && ok "a missing main ref is an error, not a pass" \
  || not_ok "a missing main ref is an error, not a pass (exit $RC)" "$OUT"

OUT="$(bash "$GUARD" v1.0.0 2>/dev/null)"
[ "$OUT" = "$A"$'\n'main ] && ok "a final tag prints the commit then main" || not_ok "a final tag prints the commit then main" "$OUT"
OUT="$(bash "$GUARD" v1.0.0-rc.1 2>/dev/null)"
[ "$OUT" = "$C"$'\n'dev/1.x.x ] && ok "an rc tag prints the commit then its integration branch" || not_ok "an rc tag prints the commit then its integration branch" "$OUT"

# Other integration branch shapes. A <- C (dev/1.x.x); G on A (dev/2.x.x); H on A (dev/1.0.0, then plain dev)
git checkout -q -b other "$A"
G="$(commit g)"
git checkout -q -b plain "$A"
H="$(commit h)"
git update-ref refs/remotes/origin/dev/1.0.0 "$H"
git update-ref refs/remotes/origin/dev/2.x.x "$G"
git tag v1.0.0-rc.3 "$A"
git tag v2.0.0-rc.2 "$C"
git tag v2.1.0-rc.1 "$G"
git tag v1.0.0-rc.4 "$C"

OUT="$(bash "$GUARD" v1.0.0-rc.3 2>/dev/null)"
[ "$OUT" = "$A"$'\n'dev/1.0.0 ] && ok "the exact dev/X.Y.Z wins over dev/X.x.x" || not_ok "the exact dev/X.Y.Z wins over dev/X.x.x" "$OUT"
OUT="$(bash "$GUARD" v1.0.0-rc.4 2>/dev/null)"
[ "$OUT" = "$C"$'\n'dev/1.x.x ] && ok "dev/X.Y.Z that lacks the commit falls through to dev/X.x.x" || not_ok "dev/X.Y.Z that lacks the commit falls through to dev/X.x.x" "$OUT"
refuses v2.0.0-rc.2 "an rc tag whose version matches no branch holding the commit" "dev/2.0.0 dev/2.0.x dev/2.x.x"
accepts v2.1.0-rc.1 "an rc tag on dev/X.x.x of its major"
git update-ref refs/remotes/origin/dev/1.2.x "$G"
git tag v1.2.0-rc.1 "$G"
OUT="$(bash "$GUARD" v1.2.0-rc.1 2>/dev/null)"
[ "$OUT" = "$G"$'\n'dev/1.2.x ] && ok "dev/X.Y.x is a candidate" || not_ok "dev/X.Y.x is a candidate" "$OUT"

git update-ref -d refs/remotes/origin/dev/1.x.x
git update-ref -d refs/remotes/origin/dev/1.0.0
git update-ref -d refs/remotes/origin/dev/1.2.x
git update-ref -d refs/remotes/origin/dev/2.x.x
git update-ref refs/remotes/origin/dev "$H"
git tag v1.0.0-rc.5 "$H"
refuses v1.0.0-rc.5 "an rc tag on a plain dev branch" "dev/1.0.0 dev/1.0.x dev/1.x.x"

exit "$FAILED"
