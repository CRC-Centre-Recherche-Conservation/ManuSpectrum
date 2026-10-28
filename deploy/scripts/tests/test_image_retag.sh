#!/usr/bin/env bash
# deploy/scripts/tests/test_image_retag.sh
# Tests of image-retag.sh with a fake `curl` serving a canned registry: the
# bytes PUT under the tag are the bytes read by digest, the bearer flow keeps
# credentials and token out of argv, and every refusal happens before a PUT.
# Prints `ok N` / `not ok N`; exits non-zero on failure.
# shellcheck disable=SC2319,SC2015,SC2001,SC2030,SC2031
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RETAG="$HERE/../image-retag.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }

mkdir -p "$TMP/bin"
cat >"$TMP/bin/curl" <<'SH'
#!/usr/bin/env bash
# Records argv, the stdin config and the PUT body; answers like a registry.
printf '%s\n' "$*" >>"$FAKE_DIR/argv.log"
out="" hdrs="" method=GET ctype="" url=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[i]}" in
    -o) out="${args[i + 1]}" ;;
    -D) hdrs="${args[i + 1]}" ;;
    -X) method="${args[i + 1]}" ;;
    -H) case "${args[i + 1]}" in Content-Type:*) ctype="${args[i + 1]#Content-Type: }" ;; esac ;;
    --data-binary) cp "${args[i + 1]#@}" "$FAKE_DIR/put.body" ;;
  esac
  url="${args[i]}"
done
stdin="$(cat)"
printf '%s\n' "$stdin" >>"$FAKE_DIR/stdin.log"
printf '%s %s\n' "$method" "$url" >>"$FAKE_DIR/calls.log"
reply() { printf '%b' "$2" >"$hdrs"; printf '%s' "$3" >"$out"; printf '%s' "$1"; exit 0; }
case "$method $url" in
  "GET "*/v2/)
    if [ -n "${FAKE_AUTH:-}" ] && [[ "$stdin" != *"Bearer "* ]]; then
      reply 401 'HTTP/2 401\r\nWww-Authenticate: Bearer realm="https://auth.example/token",service="reg.example"\r\n\r\n' ''
    fi
    reply 200 'HTTP/2 200\r\n\r\n' '{}' ;;
  "GET https://auth.example/token?"*)
    [[ "$stdin" == *'user = "bot:s3cret"'* ]] || reply 401 'HTTP/2 401\r\n\r\n' ''
    printf '%s\n' "$url" >"$FAKE_DIR/token.url"
    reply 200 'HTTP/2 200\r\n\r\n' '{"token":"tok-abc123","expires_in":300}' ;;
  "GET "*/manifests/sha256:*)
    cp "$FAKE_DIR/served" "$out"
    printf 'HTTP/2 200\r\nContent-Type: %s\r\n\r\n' "$FAKE_CTYPE" >"$hdrs"
    printf 200; exit 0 ;;
  "PUT "*/manifests/*)
    [ "$ctype" = "$FAKE_CTYPE" ] || reply 400 'HTTP/2 400\r\n\r\n' 'wrong content type'
    reply "${FAKE_PUT_CODE:-201}" "HTTP/2 201\r\nDocker-Content-Digest: ${FAKE_PUT_DIGEST-$FAKE_DIGEST}\r\n\r\n" '' ;;
esac
reply 404 'HTTP/2 404\r\n\r\n' ''
SH
chmod +x "$TMP/bin/curl"

printf '{"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json","layers":[]}' >"$TMP/manifest"
DIGEST="sha256:$(sha256sum "$TMP/manifest" | cut -d' ' -f1)"
CTYPE=application/vnd.oci.image.manifest.v1+json
REF="reg.example/org/app@$DIGEST"

retag() { # retag REF TAG [ENV=VALUE...]: runs with the fake curl
  local ref="$1" tag="$2"
  shift 2
  rm -rf "$TMP/state"
  mkdir -p "$TMP/state"
  cp "$TMP/manifest" "$TMP/state/served"
  case " $* " in *" FAKE_SERVED_BAD=1 "*) printf '{"tampered":true}' >"$TMP/state/served" ;; esac
  OUT="$(env PATH="$TMP/bin:$PATH" FAKE_DIR="$TMP/state" FAKE_CTYPE="$CTYPE" FAKE_DIGEST="$DIGEST" "$@" \
    bash "$RETAG" "$ref" "$tag" 2>"$TMP/err")"
  RC=$?
  ERR="$(cat "$TMP/err")"
}
refused_late() { # refused_late NAME FRAGMENT: non-zero exit, FRAGMENT in the message
  if [ "$RC" -eq 0 ]; then not_ok "$1 (accepted)" "$OUT"
  elif ! grep -q -- "$2" <<<"$ERR"; then not_ok "$1 (no reason: $2)" "$ERR"
  else ok "$1"; fi
}
refused() { # refused NAME FRAGMENT: as refused_late, and nothing was PUT
  if grep -qs '^PUT ' "$TMP/state/calls.log"; then not_ok "$1 (a PUT was sent)"; else refused_late "$1" "$2"; fi
}

retag "$REF" v1.0.0
if [ "$RC" -eq 0 ] && cmp -s "$TMP/manifest" "$TMP/state/put.body" \
  && grep -q '^PUT https://reg.example/v2/org/app/manifests/v1.0.0$' "$TMP/state/calls.log"; then
  ok "PUTs the very bytes read by digest, under the tag, with the same Content-Type"
else
  not_ok "PUTs the very bytes read by digest (exit $RC)" "$ERR"
fi

retag "$REF" v1.0.0 FAKE_AUTH=1 REGISTRY_USER=bot REGISTRY_TOKEN=s3cret
if [ "$RC" -eq 0 ] && grep -q 'header = "Authorization: Bearer tok-abc123"' "$TMP/state/stdin.log" \
  && grep -q 'scope=repository%3Aorg/app%3Apull%2Cpush' "$TMP/state/token.url" \
  && grep -q 'service=reg.example' "$TMP/state/token.url"; then
  ok "bearer flow: token fetched for pull,push and sent on the requests"
else
  not_ok "bearer flow (exit $RC)" "$ERR"
fi
if grep -Eq 'tok-abc123|s3cret|bot' "$TMP/state/argv.log" || grep -Eq 'tok-abc123|s3cret' <<<"$OUT$ERR"; then
  not_ok "credentials and token stay out of argv and output"
else
  ok "credentials and token stay out of argv and output"
fi

retag "$REF" v1.0.0 FAKE_AUTH=1
refused "401 without credentials is refused" "REGISTRY_USER"

retag "$REF" v1.0.0 FAKE_AUTH=1 REGISTRY_USER=bot REGISTRY_TOKEN=wrong
refused "a refused token request is reported" "token request refused"

retag "$REF" v1.0.0 FAKE_SERVED_BAD=1
refused "bytes that do not hash to the digest are refused, nothing PUT" "registry served"

retag "$REF" v1.0.0 "FAKE_PUT_DIGEST=sha256:$(printf 'f%.0s' {1..64})"
refused_late "a different Docker-Content-Digest is refused" "expected $DIGEST"

retag "$REF" v1.0.0 FAKE_PUT_CODE=403
refused_late "a non-201 PUT is refused" "HTTP 403"

retag "reg.example/org/app:latest" v1
refused "a reference without a digest is refused" "not a HOST/NAME@sha256"
retag "reg.example/org/app@sha256:abc" v1
refused "a short digest is refused" "not a HOST/NAME@sha256"
retag "reg.example/Org/App@$DIGEST" v1
refused "an uppercase repository is refused" "not a HOST/NAME@sha256"
for bad in "-v1" ".v1" "v1/2" "v 1" "$(printf 'a%.0s' {1..129})"; do
  retag "$REF" "$bad"
  refused "tag '${bad:0:12}' is refused" "not a valid tag"
done

retag "localhost:5000/t@$DIGEST" v1
if grep -q '^GET https://localhost:5000/v2/$' "$TMP/state/calls.log"; then
  ok "localhost is https without REGISTRY_INSECURE_LOCALHOST"
else
  not_ok "localhost is https without REGISTRY_INSECURE_LOCALHOST" "$(cat "$TMP/state/calls.log")"
fi
retag "reg.example/t@$DIGEST" v1 REGISTRY_INSECURE_LOCALHOST=1
if grep -q '^GET https://reg.example/v2/$' "$TMP/state/calls.log" && ! grep -q 'http://' "$TMP/state/calls.log"; then
  ok "http is never used for a non-localhost host"
else
  not_ok "http is never used for a non-localhost host" "$(cat "$TMP/state/calls.log")"
fi
retag "localhost:5000/t@$DIGEST" v1 REGISTRY_INSECURE_LOCALHOST=1
if [ "$RC" -eq 0 ] && grep -q '^PUT http://localhost:5000/v2/t/manifests/v1$' "$TMP/state/calls.log" \
  && grep -q -- "--proto =http,https" "$TMP/state/argv.log"; then
  ok "REGISTRY_INSECURE_LOCALHOST=1 allows http for localhost"
else
  not_ok "REGISTRY_INSECURE_LOCALHOST=1 allows http for localhost (exit $RC)" "$ERR"
fi
grep -q -- "--proto =https" <<<"$(retag "$REF" v1 >/dev/null; cat "$TMP/state/argv.log")" \
  && ok "remote registries are pinned to https" || not_ok "remote registries are pinned to https"

echo "1..$N"
exit "$FAILED"
