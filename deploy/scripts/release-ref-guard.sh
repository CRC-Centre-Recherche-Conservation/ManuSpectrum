#!/usr/bin/env bash
# Decides whether a tag may be released. A final tag (vX.Y.Z) must be on the
# first-parent line of origin/main (the commits main itself reached, each one
# built by staging.yml on main; a commit brought in by a merge is an ancestor
# but not on that line); a release-candidate tag (vX.Y.Z-rc.N) an ancestor
# of the integration branch. Any other name is refused. Prints the tagged
# commit on stdout; the reason of a refusal goes to stderr.
# Usage: release-ref-guard.sh TAG   (run in a clone that holds the tag and the
# remote branches; MAIN_REF and INTEGRATION_REF override the two refs)
set -uo pipefail

TAG="${1:?usage: release-ref-guard.sh TAG}"
MAIN_REF="${MAIN_REF:-origin/main}"
INTEGRATION_REF="${INTEGRATION_REF:-origin/feat/production-platform}"

refuse() { echo "release-ref-guard: $*" >&2; exit 1; }

final='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
candidate='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-rc\.(0|[1-9][0-9]*)$'

if [[ "$TAG" =~ $final ]]; then
  branch="$MAIN_REF"
  branch_name="main"
  kind="final"
elif [[ "$TAG" =~ $candidate ]]; then
  branch="$INTEGRATION_REF"
  branch_name="feat/production-platform"
  kind="release-candidate"
else
  refuse "'$TAG' is not a release tag (vX.Y.Z or vX.Y.Z-rc.N)"
fi

commit="$(git rev-parse --verify --quiet "refs/tags/$TAG^{commit}")" \
  || refuse "no such tag in this clone: $TAG"
git rev-parse --verify --quiet "$branch^{commit}" >/dev/null \
  || refuse "the ref $branch is missing: fetch the full history"
git merge-base --is-ancestor "$commit" "$branch" \
  || refuse "$TAG is not on $branch_name: a $kind tag must be an ancestor of $branch"
if [ "$kind" = final ]; then
  line="$(git rev-list --first-parent "$branch")" \
    || refuse "cannot list the first-parent line of $branch"
  grep -qxF "$commit" <<<"$line" \
    || refuse "$TAG is not on the first-parent line of $branch_name: a final tag must sit on a commit main itself reached"
fi
echo "$commit"
