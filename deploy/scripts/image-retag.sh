#!/usr/bin/env bash
# Puts a tag on an existing manifest without changing it: GETs the manifest by
# digest and PUTs the same bytes under the tag, through the OCI distribution
# API. `buildx imagetools create` wraps a single-platform manifest in a new
# index, which changes the digest the later jobs sign and the hosts pull.
# Credentials: REGISTRY_USER and REGISTRY_TOKEN (needed when the registry
# answers 401). They reach curl through its config on stdin, never argv.
# REGISTRY_INSECURE_LOCALHOST=1 allows plain http for localhost/127.0.0.1
# (tests only); every other registry is https.
# Usage: image-retag.sh HOST/NAME@sha256:<64 hex> TAG
set -euo pipefail

me=image-retag.sh
die() { echo "$me: $*" >&2; exit 1; }

REF="${1:?usage: image-retag.sh HOST/NAME@sha256:DIGEST TAG}"
TAG="${2:?usage: image-retag.sh HOST/NAME@sha256:DIGEST TAG}"

[[ "$REF" =~ ^([A-Za-z0-9.-]+(:[0-9]+)?)/([a-z0-9]+([._-][a-z0-9]+)*(/[a-z0-9]+([._-][a-z0-9]+)*)*)@(sha256:[0-9a-f]{64})$ ]] \
  || die "not a HOST/NAME@sha256:<64 hex> reference: $REF"
host="${BASH_REMATCH[1]}"
name="${BASH_REMATCH[3]}"
digest="${BASH_REMATCH[7]}"
[[ "$TAG" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]] || die "not a valid tag: $TAG"

scheme=https
proto=(--proto '=https' --proto-redir '=https')
if [ "${REGISTRY_INSECURE_LOCALHOST:-}" = 1 ] && [[ "$host" =~ ^(localhost|127\.0\.0\.1)(:[0-9]+)?$ ]]; then
  scheme=http
  proto=(--proto '=http,https')
fi
base="$scheme://$host/v2"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# req OUT HDRS URL [curl args...]: prints the HTTP status; the curl config
# (credentials) comes from $cfg on stdin.
cfg=""
req() {
  local out="$1" hdrs="$2" url="$3"
  shift 3
  printf '%s\n' "$cfg" | curl -sS -K - "${proto[@]}" --connect-timeout 10 --max-time 120 \
    -o "$out" -D "$hdrs" -w '%{http_code}' "$@" "$url" \
    || die "cannot reach $url"
}
header() { # header FILE NAME: last value of a response header
  tr -d '\r' <"$1" | sed -n "s/^$2:[[:space:]]*//Ip" | tail -n 1
}

code="$(req "$work/probe.body" "$work/probe.hdr" "$base/")"
case "$code" in
  200) ;;
  401)
    [ -n "${REGISTRY_USER:-}" ] && [ -n "${REGISTRY_TOKEN:-}" ] \
      || die "$host asks for credentials: set REGISTRY_USER and REGISTRY_TOKEN"
    challenge="$(header "$work/probe.hdr" www-authenticate)"
    [[ "$challenge" =~ ^[Bb]earer[[:space:]] ]] || die "$host sent no Bearer challenge"
    realm="$(sed -n 's/.*realm="\([^"]*\)".*/\1/p' <<<"$challenge")"
    service="$(sed -n 's/.*service="\([^"]*\)".*/\1/p' <<<"$challenge")"
    [[ "$realm" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._/-]*$ ]] \
      || { [ "$scheme" = http ] && [[ "$realm" =~ ^http://(localhost|127\.0\.0\.1)(:[0-9]+)?/ ]]; } \
      || die "unusable token realm in the challenge from $host"
    [[ "$service" =~ ^[A-Za-z0-9._:-]*$ ]] || die "unusable token service in the challenge from $host"
    cfg="user = \"$REGISTRY_USER:$REGISTRY_TOKEN\""
    tcode="$(req "$work/token.json" "$work/token.hdr" \
      "$realm?service=$service&scope=repository%3A${name}%3Apull%2Cpush")"
    [ "$tcode" = 200 ] || die "token request refused by $host (HTTP $tcode)"
    token="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$work/token.json")"
    [ -n "$token" ] || token="$(sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$work/token.json")"
    [ -n "$token" ] || die "no token in the answer from $host"
    cfg="header = \"Authorization: Bearer $token\""
    ;;
  *) die "$host answered HTTP $code to GET /v2/" ;;
esac

accept='application/vnd.oci.image.manifest.v1+json, application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json'
code="$(req "$work/manifest" "$work/manifest.hdr" "$base/$name/manifests/$digest" -H "Accept: $accept")"
[ "$code" = 200 ] || die "cannot read $name@$digest (HTTP $code)"
[ -s "$work/manifest" ] || die "empty manifest for $name@$digest"
ctype="$(header "$work/manifest.hdr" content-type)"
[ -n "$ctype" ] || die "no Content-Type on the manifest of $name@$digest"
got="sha256:$(sha256sum "$work/manifest" | cut -d' ' -f1)"
[ "$got" = "$digest" ] || die "the registry served $got for $digest"

code="$(req "$work/put.body" "$work/put.hdr" "$base/$name/manifests/$TAG" \
  -X PUT -H "Content-Type: $ctype" --data-binary "@$work/manifest")"
[ "$code" = 201 ] || die "cannot tag $name:$TAG (HTTP $code)"
pushed="$(header "$work/put.hdr" docker-content-digest)"
[ -z "$pushed" ] || [ "$pushed" = "$digest" ] || die "$name:$TAG is $pushed, expected $digest"
echo "$me: $host/$name:$TAG -> $digest"
