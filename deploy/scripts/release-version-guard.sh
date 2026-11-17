#!/usr/bin/env bash
# Refuses a release tag whose base version differs from one of the three
# places that state it. The tag vX.Y.Z or vX.Y.Z-rc.N must read X.Y.Z, at the
# tagged commit, in manuspectrum/settings.py (APP_VERSION, parsed with a regex:
# no Django import), pyproject.toml (`version`, repeated by uv.lock and carried
# by the image's package metadata) and package.json (`version`, repeated by
# package-lock.json). An APP_VERSION that carries a prerelease never equals a
# release base version.
# Usage: release-version-guard.sh TAG [COMMIT]   (run in a clone that holds the
# commit; COMMIT defaults to the tag)
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-release.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/lib-release.sh"

TAG="${1:?usage: release-version-guard.sh TAG [COMMIT]}"
if [ "$#" -ge 2 ]; then COMMIT="$2"; else COMMIT="refs/tags/$TAG^{commit}"; fi
SETTINGS="manuspectrum/settings.py"
PYPROJECT="pyproject.toml"
PACKAGE_JSON="package.json"

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
pyproject_text="$(git show "$COMMIT:$PYPROJECT" 2>/dev/null)" \
  || fail "cannot read $PYPROJECT at $COMMIT"
line="$(grep -E '^version[[:space:]]*=' <<<"$pyproject_text" | head -n 1)"
[[ "$line" =~ ^version[[:space:]]*=[[:space:]]*\"([^\"]*)\" ]] || fail "no version = \"…\" found in $PYPROJECT at $COMMIT"
[ "$tag_version" = "${BASH_REMATCH[1]}" ] \
  || fail "tag $TAG is version $tag_version but $PYPROJECT says ${BASH_REMATCH[1]}: set version = \"$tag_version\" there and run uv lock"
package_text="$(git show "$COMMIT:$PACKAGE_JSON" 2>/dev/null)" \
  || fail "cannot read $PACKAGE_JSON at $COMMIT"
package_version="$(python3 -c 'import json, sys; v = json.load(sys.stdin).get("version"); print(v if isinstance(v, str) else "")' <<<"$package_text")" \
  || fail "cannot parse $PACKAGE_JSON at $COMMIT"
[ "$tag_version" = "$package_version" ] \
  || fail "tag $TAG is version $tag_version but $PACKAGE_JSON says '${package_version}': set \"version\": \"$tag_version\" there and in package-lock.json"
