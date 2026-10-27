#!/usr/bin/env bash
# deploy/scripts/tests/test_release_verify.sh
# Tests of release-verify.sh with a fake `docker` (cosign runs through it): the
# policy by tag, the digest-only reference, the signature identity, and the
# revision label. Prints `ok N` / `not ok N`; exits non-zero on failure.
# shellcheck disable=SC2319,SC2015,SC2001,SC2030,SC2031
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY="$HERE/../release-verify.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }

mkdir -p "$TMP/bin"
LOG="$TMP/docker.log"
cat >"$TMP/bin/docker" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >>"$FAKE_LOG"
case "$1" in
  run) [ -n "${FAKE_COSIGN_FAIL:-}" ] && { echo "cosign: no matching signatures" >&2; exit 1; }
       echo '[{"critical":{}}]'; exit 0 ;;
  pull) echo pulled; exit 0 ;;
  image) printf '%s\n' "${FAKE_LABEL-}"; exit 0 ;;
esac
exit 2
SH
chmod +x "$TMP/bin/docker"

IMAGE=ghcr.io/crc-centre-recherche-conservation/manuspectrum
DIGEST=sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
COMMIT=89abcdef0123456789abcdef0123456789abcdef
REF="$IMAGE@$DIGEST"

verify() { # verify ARGS...: runs with the fake docker, label = COMMIT unless FAKE_LABEL is set
  : >"$LOG"
  OUT="$(PATH="$TMP/bin:$PATH" FAKE_LOG="$LOG" FAKE_LABEL="${FAKE_LABEL-$COMMIT}" bash "$VERIFY" "$@" 2>"$TMP/err")"
  RC=$?
  ERR="$(cat "$TMP/err")"
}
accepted() { [ "$RC" -eq 0 ] && [ "$OUT" = "$COMMIT" ] && ok "$1" || not_ok "$1 (exit $RC)" "$OUT $ERR"; }
refused() { # refused NAME FRAGMENT-OF-REASON
  if [ "$RC" -eq 0 ]; then not_ok "$1 (accepted)" "$OUT"
  elif ! grep -q -- "$2" <<<"$ERR"; then not_ok "$1 (no reason: $2)" "$ERR"
  else ok "$1"; fi
}
called() { grep -q -- "$1" "$LOG"; }

verify --policy prod "$REF" v1.2.3 --commit "$COMMIT"
accepted "prod accepts a final tag and prints the commit"

verify --policy prod "$REF" v1.2.3-rc.1 --commit "$COMMIT"
refused "prod refuses an rc tag" "prod"
called "run" && not_ok "prod refuses an rc tag before any signature check" || ok "prod refuses an rc tag before any signature check"

verify --policy rc "$REF" v1.2.3-rc.1 --commit "$COMMIT"
accepted "rc accepts an rc tag"
verify --policy rc "$REF" v1.2.3 --commit "$COMMIT"
accepted "rc accepts a final tag"

verify --policy rc "$REF" "sha-$COMMIT" --commit "$COMMIT"
refused "a sha-* tag is not a release" "not a release tag"
verify --policy prod "$REF" v1.2 --commit "$COMMIT"
refused "a malformed tag is not a release" "not a release tag"

verify --policy prod "$IMAGE:v1.2.3" v1.2.3 --commit "$COMMIT"
refused "an image given by tag is refused" "digest"
verify --policy prod "$IMAGE:sha-$COMMIT" v1.2.3 --commit "$COMMIT"
refused "an image given by sha-* tag is refused" "digest"

verify --policy staging "$REF" v1.2.3 --commit "$COMMIT"
refused "an unknown policy is refused" "policy"

FAKE_COSIGN_FAIL=1 verify --policy rc "$REF" v1.2.3 --commit "$COMMIT"
refused "a failed signature check is refused" "signature"
called "pull" && not_ok "nothing is pulled when the signature fails" || ok "nothing is pulled when the signature fails"

FAKE_LABEL=ffffffffffffffffffffffffffffffffffffffff verify --policy rc "$REF" v1.2.3 --commit "$COMMIT"
refused "a revision label that differs from the tag's commit is refused" "revision"
FAKE_LABEL=unknown verify --policy rc "$REF" v1.2.3 --commit "$COMMIT"
refused "an unlabelled image is refused" "revision"
FAKE_LABEL='' verify --policy rc "$REF" v1.2.3 --commit "$COMMIT"
refused "an empty label is refused" "revision"

verify --policy prod "$REF" v1.2.3 --commit "$COMMIT"
cosign_line="$(grep '^run ' "$LOG")"
want="https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum/.github/workflows/release.yml@refs/tags/v1.2.3"
{ grep -qF -- "--certificate-identity $want" <<<"$cosign_line" \
  && grep -qF -- "--certificate-oidc-issuer https://token.actions.githubusercontent.com" <<<"$cosign_line" \
  && grep -qF -- "--certificate-github-workflow-sha $COMMIT" <<<"$cosign_line" \
  && grep -qF -- "--certificate-github-workflow-trigger push" <<<"$cosign_line" \
  && grep -qE 'ghcr.io/sigstore/cosign/cosign(:[^@ ]+)?@sha256:[0-9a-f]{64} verify' <<<"$cosign_line" \
  && grep -qF -- "$REF" <<<"$cosign_line"; } \
  && ok "cosign runs from a pinned image with the workflow identity of the tag, the commit, the push trigger and the GitHub issuer" \
  || not_ok "cosign arguments" "$cosign_line"
grep -qE -- "^pull .*${REF//./\\.}$" "$LOG" && ok "the image is pulled by digest" || not_ok "the image is pulled by digest" "$(cat "$LOG")"

DOCKER_CONFIG_DIR="$TMP/dockercfg" verify --policy prod "$REF" v1.2.3 --commit "$COMMIT"
grep '^run ' "$LOG" | grep -qF -- "$TMP/dockercfg:/cosign-docker-config:ro" \
  && ok "a docker config directory is mounted read-only for cosign" || not_ok "docker config mount" "$(cat "$LOG")"

REPO="$TMP/repo"
git init -q "$REPO"
(
  cd "$REPO" || exit 1
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@manuspectrum.test GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@manuspectrum.test
  git config commit.gpgsign false
  git config tag.gpgsign false
  git commit -q --allow-empty -m one
  git tag v1.2.3
  git rev-parse HEAD >"$TMP/head"
)
HEAD_SHA="$(cat "$TMP/head")"
: >"$LOG"
OUT="$(cd "$REPO" && PATH="$TMP/bin:$PATH" FAKE_LOG="$LOG" FAKE_LABEL="$HEAD_SHA" bash "$VERIFY" --policy prod "$REF" v1.2.3 2>"$TMP/err")"; RC=$?
[ "$RC" -eq 0 ] && [ "$OUT" = "$HEAD_SHA" ] && ok "the commit defaults to the tag's commit in the clone" \
  || not_ok "the commit defaults to the tag's commit (exit $RC)" "$OUT $(cat "$TMP/err")"
OUT="$(cd "$REPO" && PATH="$TMP/bin:$PATH" FAKE_LOG="$LOG" FAKE_LABEL="$HEAD_SHA" bash "$VERIFY" --policy rc "$REF" v9.9.9 2>"$TMP/err")"; RC=$?
ERR="$(cat "$TMP/err")"
refused "a tag the clone does not hold is refused" "commit"


# --repo-dir: under the prod policy the tag's commit must be on the first-parent
# line of origin/main in that clone.
GUARDED="$TMP/guarded"
git init -q "$GUARDED"
(
  cd "$GUARDED" || exit 1
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@manuspectrum.test GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@manuspectrum.test
  git config commit.gpgsign false
  git config tag.gpgsign false
  git commit -q --allow-empty -m one
  git tag v1.2.3
  git rev-parse HEAD >"$TMP/guarded-head"
  git update-ref refs/remotes/origin/main HEAD
  git checkout -q -b stray
  git commit -q --allow-empty -m two
  git tag v1.2.4
  git rev-parse HEAD >"$TMP/stray-head"
  git tag v1.2.5-rc.1
)
G_HEAD="$(cat "$TMP/guarded-head")"
S_HEAD="$(cat "$TMP/stray-head")"
FAKE_LABEL="$G_HEAD" verify --policy prod --repo-dir "$GUARDED" "$REF" v1.2.3 --commit "$G_HEAD"
[ "$RC" -eq 0 ] && ok "prod with --repo-dir accepts a tag on main" || not_ok "prod with --repo-dir accepts a tag on main (exit $RC)" "$OUT $ERR"
FAKE_LABEL="$S_HEAD" verify --policy prod --repo-dir "$GUARDED" "$REF" v1.2.4 --commit "$S_HEAD"
refused "prod with --repo-dir refuses a tag that is not on main" "main"
called "run" && not_ok "the clone is judged before any signature check" || ok "the clone is judged before any signature check"
FAKE_LABEL="$G_HEAD" verify --policy prod --repo-dir "$GUARDED" "$REF" v1.2.3 --commit "$S_HEAD"
refused "--commit that differs from the tag in the clone is refused" "commit"
FAKE_LABEL="$S_HEAD" verify --policy rc --repo-dir "$GUARDED" "$REF" v1.2.5-rc.1 --commit "$S_HEAD"
[ "$RC" -eq 0 ] && ok "the rc policy does not judge the clone against main" || not_ok "rc policy with --repo-dir (exit $RC)" "$OUT $ERR"

exit "$FAILED"
