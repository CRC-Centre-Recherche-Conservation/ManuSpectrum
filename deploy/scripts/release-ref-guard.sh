#!/usr/bin/env bash
# Decides whether a tag may be released. A final tag (vX.Y.Z) must be on the
# first-parent line of origin/main (the commits main itself reached, each one
# built by staging.yml on main; a commit brought in by a merge is an ancestor
# but not on that line); a release-candidate tag (vX.Y.Z-rc.N) an ancestor
# of an integration branch whose name matches its version: dev/X.Y.Z,
# dev/X.Y.x or dev/X.x.x (an integration branch is dev/<major>.<minor|x>.<patch|x>);
# the first of these that exists on the remote and holds the commit is the
# one. Any other name is refused. Prints the tagged commit on the first line
# of stdout and the branch (without the remote) on the second; the reason of
# a refusal goes to stderr.
# Usage: release-ref-guard.sh TAG   (run in a clone that holds the tag and the
# remote branches; MAIN_REF overrides the main ref, REMOTE the remote name)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-release.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/lib-release.sh"

TAG="${1:?usage: release-ref-guard.sh TAG}"
MAIN_REF="${MAIN_REF:-origin/main}"
REMOTE="${REMOTE:-origin}"

refuse() { echo "release-ref-guard: $*" >&2; exit 1; }

final="$RELEASE_TAG_FINAL_RE"
candidate="$RELEASE_TAG_RC_RE"

if [[ "$TAG" =~ $final ]]; then
  kind="final"
elif [[ "$TAG" =~ $candidate ]]; then
  major="${BASH_REMATCH[1]}" minor="${BASH_REMATCH[2]}" patch="${BASH_REMATCH[3]}"
  candidates=("dev/$major.$minor.$patch" "dev/$major.$minor.x" "dev/$major.x.x")
  kind="release-candidate"
else
  refuse "'$TAG' is not a release tag (vX.Y.Z or vX.Y.Z-rc.N)"
fi

commit="$(git rev-parse --verify --quiet "refs/tags/$TAG^{commit}")" \
  || refuse "no such tag in this clone: $TAG"

if [ "$kind" = final ]; then
  branch="$MAIN_REF"
  branch_name="main"
  git rev-parse --verify --quiet "$branch^{commit}" >/dev/null \
    || refuse "the ref $branch is missing: fetch the full history"
  git merge-base --is-ancestor "$commit" "$branch" \
    || refuse "$TAG is not on $branch_name: a $kind tag must be an ancestor of $branch"
  line="$(git rev-list --first-parent "$branch")" \
    || refuse "cannot list the first-parent line of $branch"
  grep -qxF "$commit" <<<"$line" \
    || refuse "$TAG is not on the first-parent line of $branch_name: a final tag must sit on a commit main itself reached"
else
  branch_name=""
  for name in "${candidates[@]}"; do
    ref="$REMOTE/$name"
    git rev-parse --verify --quiet "$ref^{commit}" >/dev/null || continue
    if git merge-base --is-ancestor "$commit" "$ref"; then
      branch_name="$name"
      break
    fi
  done
  [ -n "$branch_name" ] \
    || refuse "$TAG is not on an integration branch of its version: a $kind tag must be an ancestor of one of ${candidates[*]} on $REMOTE (the first that exists and holds the commit)"
fi
echo "$commit"
echo "$branch_name"
