#!/usr/bin/env bash
# Prints the manifest digest (sha256:<64 hex>) of a registry reference: the
# sha256 of the manifest bytes the registry serves, which is what a pull by
# digest checks. `buildx imagetools inspect --raw` is used instead of a
# format template, which older buildx releases ignore.
# Usage: image-digest.sh IMAGE[:TAG|@DIGEST]
set -euo pipefail

REF="${1:?usage: image-digest.sh IMAGE[:TAG|@DIGEST]}"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
docker buildx imagetools inspect --raw "$REF" >"$tmp" \
  || { echo "image-digest.sh: cannot read the manifest of $REF" >&2; exit 1; }
[ -s "$tmp" ] || { echo "image-digest.sh: empty manifest for $REF" >&2; exit 1; }
printf 'sha256:%s\n' "$(sha256sum "$tmp" | cut -d' ' -f1)"
