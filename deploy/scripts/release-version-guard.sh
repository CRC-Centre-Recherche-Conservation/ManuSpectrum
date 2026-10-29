#!/usr/bin/env bash
# Refuses a release tag whose base version differs from APP_VERSION. The tag
# vX.Y.Z or vX.Y.Z-rc.N must read X.Y.Z in manuspectrum/settings.py at the
# tagged commit (read with git, parsed with a regex: no Django import). An
# APP_VERSION that carries a prerelease never equals a release base version.
# Usage: release-version-guard.sh TAG [COMMIT]   (run in a clone that holds the
# commit; COMMIT defaults to the tag)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-release.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/lib-release.sh"

TAG="${1:?usage: release-version-guard.sh TAG [COMMIT]}"
COMMIT="${2:-refs/tags/$TAG^{commit}}"
SETTINGS="manuspectrum/settings.py"

fail() { echo "::error::$*" >&2; exit 1; }

if [[ "$TAG" =~ $RELEASE_TAG_FINAL_RE || "$TAG" =~ $RELEASE_TAG_RC_RE ]]; then
  tag_version="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.${BASH_REMATCH[3]}"
else
  fail "'$TAG' is not a release tag (vX.Y.Z or vX.Y.Z-rc.N)"
fi

source_text="$(git show "$COMMIT:$SETTINGS" 2>/dev/null)" \
  || fail "cannot read $SETTINGS at $COMMIT"
line="$(grep -E '^APP_VERSION[[:space:]]*=' <<<"$source_text" | head -n 1)"
re='major=([0-9]+),[[:space:]]*minor=([0-9]+),[[:space:]]*patch=([0-9]+)'
[[ "$line" =~ $re ]] || fail "no APP_VERSION (major=, minor=, patch=) found in $SETTINGS at $COMMIT"
app_version="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.${BASH_REMATCH[3]}"
pre_re='prerelease=\(([^)]*)\)'
if [[ "$line" =~ $pre_re ]]; then
  pre="${BASH_REMATCH[1]//[\"\' ,]/}"
  [ -z "$pre" ] || app_version="$app_version-$pre"
fi

[ "$tag_version" = "$app_version" ] \
  || fail "tag $TAG is version $tag_version but APP_VERSION in $SETTINGS is $app_version: set APP_VERSION to $tag_version, or tag $app_version"
echo "$app_version"
