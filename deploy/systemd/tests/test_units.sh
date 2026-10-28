#!/usr/bin/env bash
# deploy/systemd/tests/test_units.sh
# Renders the backup, restore-test, container-metrics, disk-usage, monthly-report, watch,
# update@ and update-at units and checks them with
# systemd-analyze (verify, calendar). Prints `ok N` / `not ok N`; exits
# non-zero on failure. Skips the checks when systemd-analyze is missing.
# RENDERED_UNITS_DIR (deploy/ansible/render.yml output) checks those files instead
# of rendering the templates.
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
PAIRS="backup restore-test container-metrics disk-usage monthly-report watch update-at"
FILES=""
for name in $PAIRS; do FILES="$FILES manuspectrum-$name.service manuspectrum-$name.timer"; done
FILES="$FILES manuspectrum-update@.service"

for file in $FILES; do
  if [ -n "${RENDERED_UNITS_DIR:-}" ]; then
    cp "$RENDERED_UNITS_DIR/$file" "$TMP/$file"
  else
    sed -e "s|@APP_USER@|$(id -un)|g" -e "s|@DEPLOY_DIR@|$DEPLOY_DIR|g" \
      "$UNITS/$file.in" >"$TMP/$file"
  fi
  ! grep -q '@[A-Z_]*@' "$TMP/$file"
  assert "$file: every placeholder is substituted" $?
done

# The account and deploy directory the units were rendered with, read off the
# nightly backup unit, so the checks hold for this script's rendering and for
# Ansible's.
APP_USER_RENDERED="$(sed -n 's/^User=//p' "$TMP/manuspectrum-backup.service")"
DEPLOY_DIR_RENDERED="$(sed -n 's|^ExecStart=/usr/bin/make -C \([^ ]*\) backup.*|\1|p' "$TMP/manuspectrum-backup.service")"

# The slot of the -at timer comes from a root drop-in written by the front.
mkdir "$TMP/manuspectrum-update-at.timer.d"
printf '[Timer]\nOnCalendar=\nOnCalendar=2030-01-01 22:00:00 UTC\n' >"$TMP/manuspectrum-update-at.timer.d/slot.conf"

for name in $PAIRS; do
  # The make binary may be absent from the runner's path; verify reads it.
  out="$(systemd-analyze verify "$TMP/manuspectrum-$name.service" "$TMP/manuspectrum-$name.timer" 2>&1)"
  rc=$?
  # The release programs live under /usr/local, absent on a runner: that is the one complaint accepted.
  if [ $rc -ne 0 ] && ! { grep -E "manuspectrum-$name\.(service|timer)" <<<"$out" | grep -qv 'is not executable: No such file or directory'; }; then rc=0; fi
  [ $rc -eq 0 ] && ! grep -qE "manuspectrum-$name\.(service|timer):[0-9]+" <<<"$out"
  assert "$name: systemd-analyze verify accepts the pair" $?
  [ $rc -eq 0 ] || echo "$out" >&2
done
out="$(systemd-analyze verify "$TMP/manuspectrum-update@.service" 2>&1)"
! grep -qE 'manuspectrum-update@\.service:[0-9]+' <<<"$out"
assert "update@: systemd-analyze verify accepts the template" $?
echo "$out" | grep -E 'update@\.service:[0-9]+' >&2

for spec in "*-*-* 02:00" "Sun *-*-* 05:30" "*-*-* *:17" "*-*-01 08:00"; do
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
grep -q '^OnCalendar=\*-\*-01 08:00$' "$TMP/manuspectrum-monthly-report.timer" && grep -q '^Persistent=true' "$TMP/manuspectrum-monthly-report.timer"
assert "monthly-report: the timer fires on the 1st at 08:00 and is persistent" $?
grep -q '^OnUnitActiveSec=30s' "$TMP/manuspectrum-container-metrics.timer"
assert "container-metrics: the timer fires every 30 seconds" $?
grep -q '^Type=oneshot' "$TMP/manuspectrum-container-metrics.service"
assert "container-metrics: the service is a oneshot" $?

WS="$TMP/manuspectrum-watch.service"
WT="$TMP/manuspectrum-watch.timer"
US="$TMP/manuspectrum-update@.service"
AS="$TMP/manuspectrum-update-at.service"
AT="$TMP/manuspectrum-update-at.timer"
grep -q '^OnCalendar=hourly$' "$WT" && grep -q '^Persistent=true' "$WT" && grep -q '^RandomizedDelaySec=10m$' "$WT" \
  && grep -q '^WantedBy=timers.target' "$WT"
assert "watch: the timer is hourly, spread over 10 minutes, persistent and enabled with timers.target" $?
grep -q '^Type=oneshot' "$WS" && grep -q "^User=$APP_USER_RENDERED$" "$WS" \
  && grep -q '^ExecStart=/usr/local/lib/manuspectrum/release/release-watch.sh$' "$WS"
assert "watch: a oneshot of the service account running the root-owned script" $?
grep -q '^Environment=STATE_DIR=/var/lib/manuspectrum/release$' "$WS" \
  && grep -q '^Environment=RELEASE_LIB_DIR=/usr/local/lib/manuspectrum/release$' "$WS" \
  && grep -q "^Environment=APP_DIR=$DEPLOY_DIR_RENDERED/\.\.$" "$WS"
assert "watch: APP_DIR, STATE_DIR and RELEASE_LIB_DIR are set" $?
! grep -q '^\[Install\]' "$US"
assert "update@: no [Install] section" $?
grep -q '^Type=oneshot' "$US" && grep -q "^User=$APP_USER_RENDERED$" "$US" \
  && grep -q '^ExecStart=/usr/local/lib/manuspectrum/release/release-update.sh %i$' "$US"
assert "update@: a oneshot of the service account running the engine on its instance" $?
grep -q '^TimeoutStartSec=4h$' "$US" && grep -q '^TimeoutStopSec=4520s$' "$US"
assert "update@: TimeoutStartSec=4h, TimeoutStopSec=4520s (2 x (310 + 1800) + 300)" $?
grep -q '^ExecStopPost=/usr/local/lib/manuspectrum/release/release-update.sh --after-stop %i$' "$US"
assert "update@: ExecStopPost runs the engine in --after-stop mode" $?
grep -q '^KillMode=mixed$' "$US"
assert "update@: SIGTERM reaches the engine alone (KillMode=mixed)" $?
[ ! -e "$TMP/manuspectrum-update@.timer" ]
assert "update@: no timer of its own" $?
grep -q '^Persistent=false' "$AT" && ! grep -q '^OnCalendar' "$AT" && ! grep -q '^\[Install\]' "$AT"
assert "update-at: the timer has no calendar, is not persistent and is not installable" $?
grep -q '^AccuracySec=1s' "$AT"
assert "update-at: the slot is accurate to the second" $?
grep -q '^ExecStart=/usr/local/sbin/manuspectrum-update --fire$' "$AS" && grep -q '^Type=oneshot' "$AS" \
  && ! grep -q '^User=' "$AS" && ! grep -q '^\[Install\]' "$AS"
assert "update-at: the service is root, runs --fire and is not installable" $?
systemd-analyze calendar "2030-01-01 22:00:00 UTC" >/dev/null 2>&1
assert "update-at: the slot syntax written by the front is valid" $?

[ "$failed" -eq 0 ]
