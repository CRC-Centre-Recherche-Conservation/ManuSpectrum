#!/usr/bin/env bash
# deploy/docker/tests/test_probe_revision.sh
# probe-image.sh compares the revision label with the expected commit when one
# is given. A fake `docker` answers the label; no image is touched.
# shellcheck disable=SC2319,SC2015,SC2001
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE="$HERE/../probe-image.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin"
cat >"$TMP/bin/docker" <<'SH'
#!/bin/sh
# docker image inspect --format '<template>' IMAGE
case "$*" in
  *org.opencontainers.image.revision*) printf '%s\n' "$FAKE_REVISION" ;;
  *Config.User*) printf '10001:10001\n' ;;
  *) exit 1 ;;
esac
SH
chmod +x "$TMP/bin/docker"

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }

sha=0123456789abcdef0123456789abcdef01234567

OUT="$(PATH="$TMP/bin:$PATH" FAKE_REVISION="$sha" bash "$PROBE" img "$sha" 2>&1)"
grep -q "ok: revision label $sha" <<<"$OUT" && ok "a matching revision label is accepted" \
  || not_ok "a matching revision label is accepted" "$OUT"

OUT="$(PATH="$TMP/bin:$PATH" FAKE_REVISION="unknown" bash "$PROBE" img "$sha" 2>&1)"
RC=$?
{ [ "$RC" -ne 0 ] && grep -q "FAIL: revision label" <<<"$OUT"; } && ok "a different revision label fails" \
  || not_ok "a different revision label fails (exit $RC)" "$OUT"

OUT="$(PATH="$TMP/bin:$PATH" FAKE_REVISION="" bash "$PROBE" img "$sha" 2>&1)"
RC=$?
{ [ "$RC" -ne 0 ] && grep -q "FAIL: revision label" <<<"$OUT"; } && ok "a missing revision label fails" \
  || not_ok "a missing revision label fails (exit $RC)" "$OUT"

exit "$FAILED"
