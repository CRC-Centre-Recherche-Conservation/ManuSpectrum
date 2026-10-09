#!/usr/bin/env bash
# deploy/systemd/tests/test_units.sh
# Renders the backup, restore-test, container-metrics and disk-usage units and checks them with
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
for name in backup restore-test container-metrics disk-usage; do
  for kind in service timer; do
    sed -e "s|@APP_USER@|$(id -un)|g" -e "s|@DEPLOY_DIR@|$DEPLOY_DIR|g" \
      "$UNITS/manuspectrum-$name.$kind.in" >"$TMP/manuspectrum-$name.$kind"
  done
  ! grep -q '@[A-Z_]*@' "$TMP"/manuspectrum-"$name".*
  assert "$name: every placeholder is substituted" $?
done

for name in backup restore-test container-metrics disk-usage; do
  # The make binary may be absent from the runner's path; verify reads it.
  out="$(systemd-analyze verify "$TMP/manuspectrum-$name.service" "$TMP/manuspectrum-$name.timer" 2>&1)"
  rc=$?
  [ $rc -eq 0 ] && ! grep -qE "manuspectrum-$name\.(service|timer):[0-9]+" <<<"$out"
  assert "$name: systemd-analyze verify accepts the pair" $?
  [ $rc -eq 0 ] || echo "$out" >&2
done

for spec in "*-*-* 02:00" "Sun *-*-* 05:30" "*-*-* *:17"; do
  systemd-analyze calendar "$spec" >/dev/null 2>&1
  assert "calendar '$spec' is valid" $?
done

# The disk job must stay out of the way of the site: lowest CPU and idle I/O.
grep -q '^Nice=19' "$TMP/manuspectrum-disk-usage.service" && grep -q '^IOSchedulingClass=idle' "$TMP/manuspectrum-disk-usage.service"
assert "disk-usage: runs at Nice=19 with idle I/O" $?
grep -q '^TimeoutStartSec=15min' "$TMP/manuspectrum-disk-usage.service"
assert "disk-usage: a hung du is cut after 15 minutes" $?
grep -q '^OnCalendar=\*-\*-\* \*:17$' "$TMP/manuspectrum-disk-usage.timer"
assert "disk-usage: the timer is hourly at minute 17" $?
grep -q '^OnUnitActiveSec=30s' "$TMP/manuspectrum-container-metrics.timer"
assert "container-metrics: the timer fires every 30 seconds" $?
grep -q '^Type=oneshot' "$TMP/manuspectrum-container-metrics.service"
assert "container-metrics: the service is a oneshot" $?

[ "$failed" -eq 0 ]
