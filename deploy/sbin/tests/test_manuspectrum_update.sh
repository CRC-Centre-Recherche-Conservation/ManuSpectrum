#!/usr/bin/env bash
# deploy/sbin/tests/test_manuspectrum_update.sh
# Tests of the manuspectrum-update front: a copy of the script whose path
# constants are rewritten to a temporary tree, fake systemctl, journalctl,
# runuser, make, chown and sendmail on PATH, the real lib-release.sh (real
# python3 slot parser) and a fake release-update.sh. Prints `ok N` / `not ok N`;
# exits non-zero on failure.
# shellcheck disable=SC2319,SC2015,SC2016,SC2034,SC2030,SC2031,SC2001
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONT_SRC="${FRONT_UNDER_TEST:-$HERE/../manuspectrum-update}"
SCRIPTS="$HERE/../../scripts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }
equals() { [ "$2" = "$3" ] && ok "$1" || not_ok "$1" "expected: $2
actual:   $3"; }
contains() { grep -qF -- "$2" <<<"$3" && ok "$1" || not_ok "$1" "missing: $2
in: $3"; }
lacks() { ! grep -qF -- "$2" <<<"$3" && ok "$1" || not_ok "$1" "unexpected: $2
in: $3"; }

# 2027-03-20 12:00 UTC and 2027-10-20 12:00 UTC
NOW_SPRING="$(date -u -d '2027-03-20 12:00' +%s)"
NOW_AUTUMN="$(date -u -d '2027-10-20 12:00' +%s)"
IMG="ghcr.io/crc-centre-recherche-conservation/manuspectrum@sha256:$(printf 'a%.0s' {1..64})"
COMMIT="$(printf 'b%.0s' {1..40})"

BIN="$TMP/bin" LIB="$TMP/lib" STATE="$TMP/state" DROP="$TMP/dropin" APP="$TMP/app"
LOG="$TMP/log" MAILS="$TMP/mails"
mkdir -p "$BIN" "$LIB" "$APP/deploy/compose"
cp "$SCRIPTS/lib-release.sh" "$SCRIPTS/lib-metrics.sh" "$LIB/"
cat >"$APP/deploy/compose/.env" <<EOF
ALERT_EMAILS=ops@manuspectrum.test
ALERT_EMAIL_FROM=noreply@manuspectrum.test
EOF
cat >"$TMP/release.conf" <<EOF
# written by Ansible
SERVICE_USER=$(id -un)
APP_DIR=$APP
PUBLIC_HOST=manuspectrum.test
EOF
chmod 644 "$TMP/release.conf"
printf 'Unattended-Upgrade::Automatic-Reboot "true";\nUnattended-Upgrade::Automatic-Reboot-Time "04:50";\n' >"$TMP/unattended"

cat >"$LIB/release-update.sh" <<'SH'
#!/bin/bash
echo "release-update $*" >>"$FAKE_LOG"
if [ "${FAKE_CHECK_RC:-0}" != 0 ]; then
  echo "release-update: REFUSED: files installed by Ansible differ"
  echo "REASON=managed_sources"
  exit "$FAKE_CHECK_RC"
fi
echo "CHECK=ok"
SH
chmod +x "$LIB/release-update.sh"

stub() { printf '#!/bin/bash\n%s\n' "$2" >"$BIN/$1"; chmod +x "$BIN/$1"; }
stub systemctl 'echo "systemctl $*" >>"$FAKE_LOG"
case "$1" in
  list-units) [ -z "${FAKE_ACTIVE-}" ] || echo "$FAKE_ACTIVE loaded active running" ;;
  show) case "$3" in
      ExecMainStatus) echo "${FAKE_STATUS:-0}" ;;
      Result) echo success ;;
      NextElapseUSecRealtime) echo "${FAKE_NEXT-}" ;;
    esac ;;
  daemon-reload) echo "dropin: $(cat "$FAKE_DROPIN/slot.conf" 2>/dev/null | tr "\n" "|")" >>"$FAKE_LOG" ;;
  start) case "$2" in
      *.timer) [ -z "${FAKE_TIMER_FAIL-}" ] || exit 1 ;;
      *) [ -z "${FAKE_UNIT_FAIL-}" ] || exit 1; [ -z "${FAKE_START_SLEEP-}" ] || exec sleep "$FAKE_START_SLEEP" ;;
    esac ;;
esac
exit 0'
stub journalctl 'echo "journalctl $*" >>"$FAKE_LOG"; exec sleep 30'
stub runuser 'u=$2; shift 3; echo "runuser -u $u -- $*" >>"$FAKE_LOG"; exec "$@"'
stub make 'echo "make $*" >>"$FAKE_LOG"
case "$*" in *"ARGS=plan"*) [ -z "${FAKE_NOTICE_FAIL-}" ] || { echo "boom"; exit 1; }; echo "planned notice id=42" ;; esac
exit 0'
stub chown 'echo "chown $*" >>"$FAKE_LOG"'
stub sendmail 'echo "sendmail" >>"$FAKE_LOG"; cat >>"$FAKE_MAILS"'
export FAKE_LOG="$LOG" FAKE_MAILS="$MAILS" FAKE_DROPIN="$DROP"
export PATH="$BIN:$PATH"

# mkfront NOW [REQUIRE_TTY]: writes the rewritten copy and prints its path
mkfront() {
  local f="$TMP/front"
  sed -E \
    -e "s|^CONF_FILE=.*|CONF_FILE=$TMP/release.conf|" \
    -e "s|^CONF_OWNER_UID=.*|CONF_OWNER_UID=$(id -u)|" \
    -e "s|^ROOT_UID=.*|ROOT_UID=$(id -u)|" \
    -e "s|^REQUIRE_TTY=.*|REQUIRE_TTY=${2:-0}|" \
    -e "s|^RELEASE_LIB_DIR=.*|RELEASE_LIB_DIR=$LIB|" \
    -e "s|^STATE_DIR=.*|STATE_DIR=$STATE|" \
    -e "s|^DROPIN_DIR=.*|DROPIN_DIR=$DROP|" \
    -e "s|^UNATTENDED_CONF=.*|UNATTENDED_CONF=$TMP/unattended|" \
    -e "s|^RELEASE_SENDMAIL=.*|RELEASE_SENDMAIL=$BIN/sendmail|" \
    -e "s|^RELEASE_NOW_EPOCH=.*|RELEASE_NOW_EPOCH=${1:-$NOW_SPRING}|" \
    -e "s|^FOLLOW_GRACE=.*|FOLLOW_GRACE=0|" \
    "$FRONT_SRC" >"$f"
  echo "$f"
}

reset() { # reset: fresh state, armed v1.2.0
  rm -rf "$STATE" "$DROP" "$MAILS"
  : >"$LOG"
  mkdir -p "$STATE"
  # shellcheck source=/dev/null
  source "$LIB/lib-release.sh"
  release_state_write "$STATE/current" TAG=v1.1.0 IMAGE="${IMG%@*}@sha256:$(printf 'c%.0s' {1..64})" COMMIT="$(printf 'd%.0s' {1..40})" APPLIED_AT=1
  release_state_write "$STATE/armed" TAG=v1.2.0 IMAGE="$IMG" COMMIT="$COMMIT" ARMED_AT=2 SECURITY=1 NOTIFIED=1 NEEDS_ANSIBLE=0
  local v
  for v in FAKE_ACTIVE FAKE_STATUS FAKE_NEXT FAKE_TIMER_FAIL FAKE_UNIT_FAIL FAKE_START_SLEEP FAKE_NOTICE_FAIL FAKE_CHECK_RC; do
    unset "$v"
    export "${v?}="
  done
}

# run ARGS...: stdin is "yes"; prints combined output, sets RC
run() { OUT="$(printf 'yes\n' | bash "$(mkfront "${NOW:-$NOW_SPRING}" "${TTY:-0}")" "$@" 2>&1)"; RC=$?; }
logtext() { cat "$LOG"; }

# --- arguments
reset
for bad in "" "--bogus" "--now" "--now v1.2.0 extra" "--now 1.2.0" "--now 'v1.2.0;id'" "--at" "--at 2027-03-22 v1.2.0" "--at 2027-03-22T23:00 v1.2.0" "--at \"2027-03-22 23:00\"" "--status x" "--cancel x" "--fire x" "--at 2027-03-22\ 23:00 --window" "--at 2027-03-22\ 23:00 --window 1d v1.2.0" "--at 2027-03-22\ 23:00 v1.2.0 v1.3.0"; do
  : >"$LOG"
  eval "run $bad"
  equals "usage exit 2 for: ${bad:-<none>}" 2 "$RC"
done
equals "bad args never reach systemctl" "" "$(logtext)"

# --- not root / no conf
OUT="$(bash "$(mkfront | xargs -I{} sh -c 'sed -i "s|^ROOT_UID=.*|ROOT_UID=99999|" {}; echo {}')" --status 2>&1)"; RC=$?
equals "refused when not root" 1 "$RC"
contains "not root message" "sudo manuspectrum-update" "$OUT"
cp "$TMP/release.conf" "$TMP/conf.bak"
printf 'SERVICE_USER=x\nAPP_DIR=/a\nPUBLIC_HOST=h\nEXTRA=1\n' >"$TMP/release.conf"
run --status; equals "unknown conf line refused" 1 "$RC"
printf 'SERVICE_USER=x\nAPP_DIR=/a/../b\nPUBLIC_HOST=h\n' >"$TMP/release.conf"
run --status; equals "APP_DIR with .. refused" 1 "$RC"
printf 'SERVICE_USER=x\nAPP_DIR=/a\n' >"$TMP/release.conf"
run --status; equals "missing conf key refused" 1 "$RC"
cp "$TMP/conf.bak" "$TMP/release.conf"; chmod 664 "$TMP/release.conf"
run --status; equals "group-writable conf refused" 1 "$RC"
chmod 644 "$TMP/release.conf"

# --- TTY and armed checks
reset
OUT="$(printf 'yes\n' | bash "$(mkfront "$NOW_SPRING" 1)" --now v1.2.0 2>&1)"; RC=$?
equals "--now without a terminal refused" 1 "$RC"
contains "--now no terminal message" "needs a terminal" "$OUT"
equals "--now without a terminal started nothing" "" "$(logtext)"
OUT="$(printf 'yes\n' | bash "$(mkfront "$NOW_SPRING" 1)" --at "2027-03-22 23:00" v1.2.0 2>&1)"; RC=$?
equals "--at without a terminal refused" 1 "$RC"

reset
run --now v1.3.0
equals "--now unarmed tag refused" 1 "$RC"
contains "--now unarmed message" "not the armed release" "$OUT"
equals "--now unarmed touched nothing" "" "$(logtext)"
run --at "2027-03-22 23:00" v1.3.0
equals "--at unarmed tag refused" 1 "$RC"
equals "--at unarmed touched nothing" "" "$(logtext)"
rm "$STATE/armed"
run --now v1.2.0
equals "--now with nothing armed refused" 1 "$RC"

# --- --now
reset
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH=9999999999 AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH=9999999999 NOTICE_ID=3 BY=ops CREATED_AT=1 OUTCOME= REASON=
run --now v1.2.0
equals "--now while scheduled refused" 1 "$RC"
contains "--now scheduled message" "cancel it first" "$OUT"
lacks "--now scheduled started nothing" "manuspectrum-update@" "$(logtext)"
reset
FAKE_ACTIVE=manuspectrum-update@v1.1.0.service
run --now v1.2.0
equals "--now with a running unit refused" 1 "$RC"
lacks "--now running unit: no start" "systemctl start" "$(logtext)"

reset
FAKE_CHECK_RC=1
run --now v1.2.0
equals "--now check refusal exits 1" 1 "$RC"
contains "--now shows the engine's refusal" "REASON=managed_sources" "$OUT"
lacks "--now check refusal starts nothing" "systemctl start" "$(logtext)"
contains "--now runs the check as the service user" "runuser -u $(id -un) -- $LIB/release-update.sh --check-only v1.2.0" "$(logtext)"

reset
OUT="$(printf 'no\n' | bash "$(mkfront)" --now v1.2.0 2>&1)"; RC=$?
equals "--now not confirmed refused" 1 "$RC"
lacks "--now not confirmed starts nothing" "systemctl start" "$(logtext)"

for pair in "0:0" "1:1" "3:3" "4:4" "9:1"; do
  reset
  FAKE_STATUS="${pair%%:*}"
  run --now v1.2.0
  equals "--now maps ExecMainStatus ${pair%%:*} to exit ${pair##*:}" "${pair##*:}" "$RC"
done
reset; FAKE_STATUS=0; run --now v1.2.0
contains "--now starts exactly the tag's unit" "systemctl start manuspectrum-update@v1.2.0.service" "$(logtext)"
contains "--now follows the journal" "journalctl -fu manuspectrum-update@v1.2.0.service" "$(logtext)"
contains "--now success message" "installed" "$OUT"
reset; FAKE_STATUS=3; run --now v1.2.0; contains "exit 3 says rolled back" "ROLLED BACK" "$OUT"
reset; FAKE_STATUS=4; run --now v1.2.0; contains "exit 4 says rollback failed" "ROLLBACK FAILED" "$OUT"
reset; FAKE_STATUS=1; run --now v1.2.0; contains "exit 1 points at the journal" "REASON=" "$OUT"

reset
FAKE_START_SLEEP=30
( printf 'yes\n' | bash "$(mkfront)" --now v1.2.0 >"$TMP/int.out" 2>&1; echo $? >"$TMP/int.rc" ) &
bg=$!
for _ in $(seq 50); do grep -q 'systemctl start manuspectrum-update@' "$LOG" && break; sleep 0.1; done
pkill -HUP -f "$TMP/front" 2>/dev/null
wait "$bg"
equals "interrupt exits 130" 130 "$(cat "$TMP/int.rc")"
contains "interrupt prints the resume command" "journalctl -fu manuspectrum-update@v1.2.0.service -o cat" "$(cat "$TMP/int.out")"
lacks "interrupt never stops the unit" "systemctl stop" "$(logtext)"
sleep 0.3
equals "interrupt leaves no follower running" "" "$(pgrep -xf 'sleep 30' || true)"

# --- --at refusals
reset
NOW="$NOW_SPRING" run --at "2027-03-28 02:30" v1.2.0
equals "--at nonexistent DST time refused" 1 "$RC"
contains "--at nonexistent message" "does not exist" "$OUT"
NOW="$NOW_AUTUMN" run --at "2027-10-31 02:30" v1.2.0
equals "--at ambiguous DST time refused" 1 "$RC"
contains "--at ambiguous message" "occurs twice" "$OUT"
run --at "2027-03-20 12:05" v1.2.0
equals "--at too soon refused" 1 "$RC"
run --at "2027-03-19 12:30" v1.2.0
equals "--at in the past refused" 1 "$RC"
run --at "2027-06-01 12:30" v1.2.0
equals "--at beyond 30 days refused" 1 "$RC"
run --at "2027-03-22 04:00" v1.2.0
equals "--at inside the reboot window refused" 1 "$RC"
contains "--at reboot message" "automatic reboot window" "$OUT"
run --at "2027-03-22 03:50" v1.2.0
equals "--at at reboot-60 refused" 1 "$RC"
run --at "2027-03-22 05:05" v1.2.0
equals "--at at reboot+15 refused" 1 "$RC"
run --at "2027-03-22 23:00" --window 3m v1.2.0
equals "--at window under 5m refused" 1 "$RC"
run --at "2027-03-22 23:00" --window 5h v1.2.0
equals "--at window over 4h refused" 1 "$RC"
equals "--at refusals touched no unit, notice or state" "" "$(grep -E 'make|daemon-reload|systemctl start' "$LOG")"
equals "--at refusals left no scheduled file" "no" "$([ -e "$STATE/scheduled" ] && echo yes || echo no)"
reset
FAKE_CHECK_RC=1
run --at "2027-03-22 23:00" v1.2.0
equals "--at check refusal exits 1" 1 "$RC"
lacks "--at check refusal plans no notice" "site-notice" "$(logtext)"
reset
printf 'Unattended-Upgrade::Automatic-Reboot "false";\n' >"$TMP/unattended"
run --at "2027-03-22 04:00" v1.2.0
equals "--at near 04:50 allowed when no automatic reboot" 0 "$RC"
printf 'Unattended-Upgrade::Automatic-Reboot "true";\nUnattended-Upgrade::Automatic-Reboot-Time "04:50";\n' >"$TMP/unattended"

# --- --at success
reset
run --at "2027-03-22 02:10" v1.2.0
equals "--at 02:10 accepted" 0 "$RC"
contains "--at 02:10 warns about the backup" "nightly backup" "$OUT"

reset
run --at "2027-03-22 23:00" --window 45m v1.2.0
equals "--at accepted" 0 "$RC"
L="$(logtext)"
line() { grep -n -m1 -- "$1" "$LOG" | cut -d: -f1; }
n_notice="$(line 'ARGS=plan')"; n_dropin="$(line 'dropin: ')"; n_timer="$(line 'systemctl start manuspectrum-update-at.timer')"
n_chown="$(line 'chown ')"; n_mail="$(line sendmail)"
if [ -n "$n_notice" ] && [ "$n_notice" -lt "${n_dropin:-0}" ] && [ "$n_dropin" -lt "${n_timer:-0}" ] && [ "${n_timer:-0}" -lt "${n_chown:-0}" ] && [ "${n_chown:-0}" -lt "${n_mail:-0}" ]; then ok "--at order: notice, drop-in, timer, state, mail"; else not_ok "--at order" "$L"; fi
contains "--at plans the notice in Paris time" 'ARGS=plan --start 2027-03-22T23:00 --end 2027-03-22T23:45' "$L"
contains "--at drop-in is UTC (22:00 in CET... 23:00 Paris on 22 March is CET+1=22:00)" 'dropin: [Timer]|OnCalendar=|OnCalendar=2027-03-22 22:00 UTC|' "$L"
equals "--at state tag" v1.2.0 "$(release_state_get "$STATE/scheduled" TAG)"
equals "--at state Paris slot" "2027-03-22 23:00" "$(release_state_get "$STATE/scheduled" AT_PARIS)"
equals "--at state epoch" "$(date -u -d '2027-03-22 22:00' +%s)" "$(release_state_get "$STATE/scheduled" AT_EPOCH)"
equals "--at state window end" "$(date -u -d '2027-03-22 22:45' +%s)" "$(release_state_get "$STATE/scheduled" WINDOW_END_EPOCH)"
equals "--at state notice id" 42 "$(release_state_get "$STATE/scheduled" NOTICE_ID)"
equals "--at state outcome empty" "" "$(release_state_get "$STATE/scheduled" OUTCOME)"
equals "--at state mode" 640 "$(stat -c %a "$STATE/scheduled")"
contains "--at chowns the state to root and the service group" "chown root:$(id -gn) $STATE/scheduled" "$L"
contains "--at mail subject" "Subject: [ManuSpectrum][Release] v1.2.0 scheduled for 2027-03-22 23:00 by root" "$(cat "$MAILS")"
run --now v1.2.0
equals "--now after --at refused" 1 "$RC"
run --at "2027-03-23 23:00" v1.2.0
equals "second --at refused while scheduled" 1 "$RC"

reset
run --at "2027-03-22 23:00" --no-notice v1.2.0
equals "--at --no-notice accepted" 0 "$RC"
lacks "--no-notice plans no notice" "site-notice" "$(logtext)"
equals "--no-notice state has an empty notice id" "" "$(release_state_get "$STATE/scheduled" NOTICE_ID)"

reset
FAKE_NOTICE_FAIL=1
run --at "2027-03-22 23:00" v1.2.0
equals "--at notice failure refuses" 1 "$RC"
lacks "notice failure: no timer touched" "update-at.timer" "$(logtext)"
equals "notice failure: nothing scheduled" no "$([ -e "$STATE/scheduled" ] && echo yes || echo no)"
run --at "2027-03-22 23:00" --no-notice v1.2.0
equals "notice failure is skipped by --no-notice" 0 "$RC"

reset
FAKE_TIMER_FAIL=1
run --at "2027-03-22 23:00" v1.2.0
equals "--at timer failure exits 1" 1 "$RC"
contains "timer failure withdraws the notice" "ARGS=withdraw 42" "$(logtext)"
equals "timer failure removes the drop-in" no "$([ -e "$DROP/slot.conf" ] && echo yes || echo no)"
equals "timer failure leaves no scheduled file" no "$([ -e "$STATE/scheduled" ] && echo yes || echo no)"
lacks "timer failure sends no mail" "sendmail" "$(logtext)"

# --- --cancel
reset
run --at "2027-03-22 23:00" v1.2.0
: >"$LOG"; rm -f "$MAILS"
run --cancel
equals "--cancel exits 0" 0 "$RC"
L="$(logtext)"
contains "--cancel stops the timer" "systemctl stop manuspectrum-update-at.timer" "$L"
contains "--cancel withdraws the notice" "ARGS=withdraw 42" "$L"
equals "--cancel removes the drop-in" no "$([ -e "$DROP/slot.conf" ] && echo yes || echo no)"
equals "--cancel removes scheduled" no "$([ -e "$STATE/scheduled" ] && echo yes || echo no)"
contains "--cancel mails" "schedule of v1.2.0 cancelled" "$(cat "$MAILS")"
: >"$LOG"
run --cancel
equals "--cancel twice exits 0" 0 "$RC"
contains "--cancel twice says nothing is scheduled" "Nothing is scheduled" "$OUT"
lacks "--cancel twice sends nothing" "sendmail" "$(logtext)"
reset
FAKE_ACTIVE=manuspectrum-update@v1.2.0.service
run --cancel
equals "--cancel refused while an update runs" 1 "$RC"
reset
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH=1 AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH=2 NOTICE_ID=7 BY=ops CREATED_AT=1 OUTCOME=refused REASON=drift
run --cancel
equals "--cancel acknowledges a refused schedule" 0 "$RC"
contains "acknowledgement message" "Acknowledged" "$OUT"
lacks "acknowledgement does not withdraw again" "withdraw" "$(logtext)"
lacks "acknowledgement sends no cancel mail" "sendmail" "$(logtext)"
equals "acknowledgement removes the file" no "$([ -e "$STATE/scheduled" ] && echo yes || echo no)"

# --- --fire
reset
run --fire
equals "--fire without scheduled file refused" 1 "$RC"
reset
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH=1 AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH=2 NOTICE_ID=7 BY=ops CREATED_AT=1 OUTCOME=missed REASON=
run --fire
equals "--fire with an OUTCOME refused" 1 "$RC"
lacks "--fire with an OUTCOME starts nothing" "systemctl start" "$(logtext)"
reset
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH=1 AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH=2 NOTICE_ID=7 BY=ops CREATED_AT=1 OUTCOME= REASON=
mkdir -p "$DROP"; printf '[Timer]\n' >"$DROP/slot.conf"
run --fire
equals "--fire exits 0" 0 "$RC"
L="$(logtext)"
contains "--fire starts the unit with --no-block" "systemctl start --no-block manuspectrum-update@v1.2.0.service" "$L"
equals "--fire removed the drop-in" no "$([ -e "$DROP/slot.conf" ] && echo yes || echo no)"
contains "--fire stops the timer" "systemctl stop manuspectrum-update-at.timer" "$L"
equals "--fire keeps the scheduled file for the engine" yes "$([ -e "$STATE/scheduled" ] && echo yes || echo no)"
reset
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH=1 AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH=2 NOTICE_ID=7 BY=ops CREATED_AT=1 OUTCOME= REASON=
FAKE_ACTIVE=manuspectrum-update@v1.2.0.service
run --fire
equals "--fire with a running unit refused" 1 "$RC"
equals "--fire busy records the outcome" refused "$(release_state_get "$STATE/scheduled" OUTCOME)"
equals "--fire busy records the reason" busy "$(release_state_get "$STATE/scheduled" REASON)"
contains "--fire busy withdraws the notice" "ARGS=withdraw 7" "$(logtext)"
lacks "--fire busy starts nothing" "systemctl start" "$(logtext)"

# --- --status
reset
run --status
equals "--status exits 0" 0 "$RC"
contains "--status current" "current:   v1.1.0" "$OUT"
contains "--status armed" "armed:    v1.2.0" "$OUT"
contains "--status armed flags" "security=1 needs_ansible=0" "$OUT"
contains "--status nothing scheduled" "scheduled: none" "$OUT"
contains "--status nothing in flight" "inflight: none" "$OUT"
release_state_write "$STATE/pending" SINCE="$NOW_SPRING" SECURITY=1
release_state_write "$STATE/rollbacks" COUNT=2 ROLLBACK_FAILED=1
release_state_write "$STATE/inflight" FROM_TAG=v1.1.0 TO_TAG=v1.2.0 STARTED_AT="$NOW_SPRING"
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH="$(date -u -d '2027-03-22 22:00' +%s)" AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH="$(date -u -d '2027-03-22 22:30' +%s)" NOTICE_ID=9 BY=ops CREATED_AT=1 OUTCOME=refused REASON=drift HELD_TAG=v1.3.0
FAKE_NEXT="Mon 2027-03-22 22:00:00 UTC"
run --status
contains "--status pending" "pending:  since 2027-03-20 13:00 Paris, security=1" "$OUT"
contains "--status security deadline" "14 days" "$OUT"
contains "--status scheduled slot" "scheduled: v1.2.0 at 2027-03-22 23:00 Paris / 2027-03-22 22:00 UTC" "$OUT"
contains "--status notice id" "notice id: 9" "$OUT"
contains "--status timer" "timer next elapse: Mon 2027-03-22 22:00:00 UTC" "$OUT"
contains "--status outcome" "OUTCOME=refused REASON=drift" "$OUT"
contains "--status held tag" "v1.3.0" "$OUT"
contains "--status inflight" "inflight: v1.1.0 -> v1.2.0" "$OUT"
contains "--status rollbacks" "rollbacks: 2" "$OUT"
contains "--status rollback failed instructions" "remove $STATE/inflight" "$OUT"

echo "# $N tests"
exit "$FAILED"
