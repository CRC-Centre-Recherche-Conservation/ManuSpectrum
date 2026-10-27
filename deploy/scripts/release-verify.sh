#!/usr/bin/env bash
# The policy under which a host accepts an application image, and the same
# check CI runs on the image it has just signed (release.yml).
#
# Usage: release-verify.sh --policy prod|rc IMAGE@sha256:<digest> TAG
#                          [--commit SHA] [--repo-dir CLONE]
#
#   prod  the tag must be final (vX.Y.Z)
#   rc    the tag may be final or a release candidate (vX.Y.Z-rc.N)
#
# The image is checked in this order, nothing is pulled before the signature:
#   1. the reference is a digest (a tag, `sha-*` included, is refused);
#   2. with --repo-dir and the prod policy, the commit of TAG in that clone
#      (fetched: tags and origin/main) is on the first-parent line of
#      origin/main (release-ref-guard.sh) and is the commit given;
#   3. the signature was made by .github/workflows/release.yml of this
#      repository at refs/tags/TAG on a push, for that commit, through
#      GitHub's OIDC issuer (cosign, keyless; its transparency-log check is
#      part of `cosign verify`);
#   4. the image label org.opencontainers.image.revision equals the commit of
#      TAG (--commit, else the tag in the current clone).
# Prints the commit on success; a refusal says why on stderr and exits 1.
#
# cosign runs from a pinned image, so the host needs only Docker. For a
# private registry, DOCKER_CONFIG_DIR names a directory holding the
# config.json of `docker login`; it is mounted read-only into that container.
set -uo pipefail

COSIGN_IMAGE="ghcr.io/sigstore/cosign/cosign:v3.1.3@sha256:9e5c2f2edc34351160407ca3416c61855bdf9403c3c5936e0f0be7fc261611b8"
REPOSITORY="CRC-Centre-Recherche-Conservation/ManuSpectrum"
ISSUER="https://token.actions.githubusercontent.com"
LABEL="org.opencontainers.image.revision"

refuse() { echo "release-verify: $*" >&2; exit 1; }
usage() { echo "usage: release-verify.sh --policy prod|rc IMAGE@sha256:<digest> TAG [--commit SHA] [--repo-dir CLONE]" >&2; exit 2; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

policy="" commit="" repo_dir="" positional=()
while [ $# -gt 0 ]; do
  case "$1" in
    --policy) [ $# -ge 2 ] || usage; policy="$2"; shift 2 ;;
    --commit) [ $# -ge 2 ] || usage; commit="$2"; shift 2 ;;
    --repo-dir) [ $# -ge 2 ] || usage; repo_dir="$2"; shift 2 ;;
    -*) usage ;;
    *) positional+=("$1"); shift ;;
  esac
done
[ "${#positional[@]}" -eq 2 ] || usage
image="${positional[0]}"
tag="${positional[1]}"

final='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
candidate='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-rc\.(0|[1-9][0-9]*)$'

case "$policy" in
  prod) [[ "$tag" =~ $final ]] || {
          [[ "$tag" =~ $candidate ]] && refuse "policy prod accepts final tags only: $tag is a release candidate"
          refuse "$tag is not a release tag (vX.Y.Z or vX.Y.Z-rc.N)"; } ;;
  rc) [[ "$tag" =~ $final || "$tag" =~ $candidate ]] || refuse "$tag is not a release tag (vX.Y.Z or vX.Y.Z-rc.N)" ;;
  *) refuse "unknown policy '$policy' (prod or rc)" ;;
esac

[[ "$image" =~ ^[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}$ ]] \
  || refuse "the image must be given by digest (NAME@sha256:...), not by tag: $image"

if [ "$policy" = prod ] && [ -n "$repo_dir" ]; then
  tagged="$(cd "$repo_dir" && bash "$HERE/release-ref-guard.sh" "$tag")" \
    || refuse "the clone $repo_dir does not hold $tag on the first-parent line of origin/main"
  [ -z "$commit" ] || [ "$commit" = "$tagged" ] \
    || refuse "the commit given ($commit) is not the commit of $tag in $repo_dir ($tagged)"
  commit="$tagged"
fi

if [ -z "$commit" ]; then
  commit="$(git rev-parse --verify --quiet "refs/tags/$tag^{commit}")" \
    || refuse "cannot find the commit of $tag in this clone: fetch the tag or pass --commit"
fi

identity="https://github.com/$REPOSITORY/.github/workflows/release.yml@refs/tags/$tag"
cosign=(docker run --rm)
if [ -n "${DOCKER_CONFIG_DIR:-}" ]; then
  cosign+=(-v "$DOCKER_CONFIG_DIR:/cosign-docker-config:ro" -e DOCKER_CONFIG=/cosign-docker-config)
fi
cosign+=("$COSIGN_IMAGE" verify --certificate-identity "$identity" --certificate-oidc-issuer "$ISSUER" --certificate-github-workflow-sha "$commit" --certificate-github-workflow-trigger push "$image")
"${cosign[@]}" >/dev/null || refuse "signature check failed for $image: expected identity $identity on a push of $commit"

docker pull --quiet "$image" >/dev/null || refuse "cannot pull $image"
revision="$(docker image inspect --format "{{index .Config.Labels \"$LABEL\"}}" "$image")" \
  || refuse "cannot read the labels of $image"
[ "$revision" = "$commit" ] \
  || refuse "revision label of $image is '$revision', the commit of $tag is $commit"

echo "$commit"
