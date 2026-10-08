#!/usr/bin/env bash
# deploy/systemd/tests/test_units.sh
# Renders the backup and restore-test units and checks them with
# systemd-analyze (verify, calendar). Prints `ok N` / `not ok N`; exits
# non-zero on failure. Skips the checks when systemd-analyze is missing.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNITS="$HERE/.."
DEPLOY_DIR="$(cd "$HERE/../.." && pwd)"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

if ! command -v systemd-analyze >/dev/null 2>&1; then
  echo "skipped: systemd-analyze is not installed"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for name in backup restore-test; do
  for kind in service timer; do
    sed -e "s|@APP_USER@|$(id -un)|g" -e "s|@DEPLOY_DIR@|$DEPLOY_DIR|g" \
      "$UNITS/manuspectrum-$name.$kind.in" >"$TMP/manuspectrum-$name.$kind"
  done
  ! grep -q '@[A-Z_]*@' "$TMP"/manuspectrum-"$name".*
  assert "$name: every placeholder is substituted" $?
done

for name in backup restore-test; do
  # The make binary may be absent from the runner's path; verify reads it.
  out="$(systemd-analyze verify "$TMP/manuspectrum-$name.service" "$TMP/manuspectrum-$name.timer" 2>&1)"
  rc=$?
  [ $rc -eq 0 ] && ! grep -qE "manuspectrum-$name\.(service|timer):[0-9]+" <<<"$out"
  assert "$name: systemd-analyze verify accepts the pair" $?
  [ $rc -eq 0 ] || echo "$out" >&2
done

for spec in "*-*-* 02:00" "Sun *-*-* 05:30"; do
  systemd-analyze calendar "$spec" >/dev/null 2>&1
  assert "calendar '$spec' is valid" $?
done

[ "$failed" -eq 0 ]
