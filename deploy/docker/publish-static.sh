#!/usr/bin/env bash
# Publishes the collected static files of this image into the shared volume
# nginx serves. Usage: publish-static SOURCE DESTINATION
#
# SOURCE holds the files and `.build-id`, a digest of their content written at
# build time. DESTINATION receives releases/<build-id>/ and `current`, a
# symlink replaced by a rename, so a reader sees the old or the new release,
# never a mix. The release `current` pointed to before is kept for pages
# already loaded; every other release is removed. A complete release is not
# copied again.
set -euo pipefail

usage="usage: publish-static SOURCE DESTINATION"
src="${1:?$usage}"
dst="${2:?$usage}"

id="$(cat "$src/.build-id")"
if ! [[ "$id" =~ ^[0-9a-f]{16}$ ]]; then
  echo "publish-static: invalid build id in $src/.build-id" >&2
  exit 1
fi

release="releases/$id"
mkdir -p "$dst/releases"
if [ -f "$dst/$release/.complete" ]; then
  echo "publish-static: release $id already published"
else
  rm -rf "${dst:?}/$release.tmp" "${dst:?}/$release"
  mkdir "$dst/$release.tmp"
  cp -R "$src/." "$dst/$release.tmp/"
  touch "$dst/$release.tmp/.complete"
  mv -T "$dst/$release.tmp" "$dst/$release"
  echo "publish-static: copied release $id"
fi

previous="$(readlink "$dst/current" 2>/dev/null || true)"
ln -sfn "$release" "$dst/current.new"
mv -Tf "$dst/current.new" "$dst/current"

for path in "$dst"/releases/*; do
  name="releases/${path##*/}"
  if [ "$name" != "$release" ] && [ "$name" != "$previous" ]; then
    rm -rf "$path"
  fi
done
echo "publish-static: current -> $release"
