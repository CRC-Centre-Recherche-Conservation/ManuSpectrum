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
METRICS_TEXTFILE_DIR=$TMP/metrics
EOF
mkdir -p "$TMP/metrics"
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
echo "env APP_DIR=${APP_DIR-} STATE_DIR=${STATE_DIR-} RELEASE_LIB_DIR=${RELEASE_LIB_DIR-} ENV_FILE=${ENV_FILE-}" >>"$FAKE_LOG"
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
      ExecMainCode) if [ -n "${FAKE_GONE-}" ]; then printf "ExecMainCode=0\nExecMainStatus=0\n"; else printf "ExecMainCode=%s\nExecMainStatus=%s\n" "${FAKE_CODE:-1}" "${FAKE_STATUS:-0}"; fi ;;
      Result) echo success ;;
      NextElapseUSecRealtime) echo "${FAKE_NEXT-}" ;;
    esac ;;
  daemon-reload) echo "dropin: $(cat "$FAKE_DROPIN/slot.conf" 2>/dev/null | tr "\n" "|")" >>"$FAKE_LOG" ;;
  start) case "$2" in
      *.timer) [ -z "${FAKE_TIMER_FAIL-}" ] || exit 1 ;;
      *) [ -z "${FAKE_UNIT_FAIL-}" ] || exit 1; [ -z "${FAKE_START_SLEEP-}" ] || exec sleep "$FAKE_START_SLEEP"
         [ "${FAKE_STATUS:-0}" = 0 ] && [ "${FAKE_CODE:-1}" = 1 ] || exit 1 ;;
    esac ;;
esac
exit 0'
stub journalctl 'echo "journalctl $*" >>"$FAKE_LOG"; exec sleep 30'
stub runuser 'u=$2; shift 3; echo "runuser -u $u -- $*" >>"$FAKE_LOG"
pass=(); for v in $(compgen -v FAKE_); do pass+=("$v=${!v}"); done
exec env -i PATH="$PATH" "${pass[@]}" "$@"'
stub timedatectl 'echo "${FAKE_TZ:-Europe/Paris}"'
stub make 'echo "make $*" >>"$FAKE_LOG"
case "$*" in *"ARGS=plan"*) [ -z "${FAKE_NOTICE_FAIL-}" ] || { echo "boom"; exit 1; }; echo "planned notice id=42" ;; esac
exit 0'
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
    -e "s|^LOCK_FILE=.*|LOCK_FILE=$TMP/update.lock|" \
    -e "s|^ANSIBLE_MARKER=.*|ANSIBLE_MARKER=$TMP/ansible-running|" \
    -e "s|^  read -r answer .*|&; RELEASE_NOW_EPOCH=\$((RELEASE_NOW_EPOCH + \${PROMPT_DELAY:-0}))|" \
    -e "s|^RELEASE_SENDMAIL=.*|RELEASE_SENDMAIL=$BIN/sendmail|" \
    -e "s|^RELEASE_NOW_EPOCH=.*|RELEASE_NOW_EPOCH=${1:-$NOW_SPRING}|" \
    -e "s|^FOLLOW_GRACE=.*|FOLLOW_GRACE=0|" \
    "$FRONT_SRC" >"$f"
  echo "$f"
}

reset() { # reset: fresh state, armed v1.2.0
  rm -rf "$STATE" "$DROP" "$MAILS" "$TMP/ansible-running"
  : >"$LOG"
  mkdir -p "$STATE"
  # shellcheck source=/dev/null
  source "$LIB/lib-release.sh"
  release_state_write "$STATE/current" TAG=v1.1.0 IMAGE="${IMG%@*}@sha256:$(printf 'c%.0s' {1..64})" COMMIT="$(printf 'd%.0s' {1..40})" APPLIED_AT=1
  release_state_write "$STATE/armed" TAG=v1.2.0 IMAGE="$IMG" COMMIT="$COMMIT" ARMED_AT=2 SECURITY=1 NOTIFIED=1 NEEDS_ANSIBLE=0
  local v
  for v in FAKE_ACTIVE FAKE_STATUS FAKE_NEXT FAKE_TIMER_FAIL FAKE_UNIT_FAIL FAKE_START_SLEEP FAKE_NOTICE_FAIL FAKE_CHECK_RC FAKE_CODE FAKE_GONE FAKE_TZ; do
    unset "$v"
    export "${v?}="
  done
}

# run ARGS...: stdin is "yes"; prints combined output, sets RC
run() { OUT="$(printf 'yes\n' | bash "$(mkfront "${NOW:-$NOW_SPRING}" "${TTY:-0}")" "$@" 2>&1)"; RC=$?; }
logtext() { grep -v "release_state_get" "$LOG" || true; }

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
contains "--now runs the check as the service user" "$LIB/release-update.sh --check-only v1.2.0" "$(grep '^runuser' "$LOG")"
contains "--now runs the check through runuser" "runuser -u $(id -un) -- env APP_DIR=$APP" "$(logtext)"

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

reset; FAKE_GONE=1; run --now v1.2.0
equals "--now: a successful start whose unit was already collected exits 0" 0 "$RC"
contains "--now: collected unit still reports the install" "is installed" "$OUT"
reset; FAKE_GONE=1; FAKE_STATUS=3; run --now v1.2.0
equals "--now: a failed start never reads a collected unit as installed" 1 "$RC"

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
n_state="$(line 'release_state_write')"; n_mail="$(line sendmail)"
if [ -n "$n_notice" ] && [ "$n_notice" -lt "${n_dropin:-0}" ] && [ "$n_dropin" -lt "${n_timer:-0}" ] && [ "${n_timer:-0}" -lt "${n_state:-0}" ] && [ "${n_state:-0}" -lt "${n_mail:-0}" ]; then ok "--at order: notice, drop-in, timer, state, mail"; else not_ok "--at order" "$L"; fi
contains "--at plans the notice in Paris time" 'ARGS=plan --start 2027-03-22T23:00 --end 2027-03-22T23:45' "$L"
contains "--at drop-in is UTC (22:00 in CET... 23:00 Paris on 22 March is CET+1=22:00)" 'dropin: [Timer]|OnCalendar=|OnCalendar=2027-03-22 22:00 UTC|' "$L"
equals "--at state tag" v1.2.0 "$(release_state_get "$STATE/scheduled" TAG)"
equals "--at state Paris slot" "2027-03-22 23:00" "$(release_state_get "$STATE/scheduled" AT_PARIS)"
equals "--at state epoch" "$(date -u -d '2027-03-22 22:00' +%s)" "$(release_state_get "$STATE/scheduled" AT_EPOCH)"
equals "--at state window end" "$(date -u -d '2027-03-22 22:45' +%s)" "$(release_state_get "$STATE/scheduled" WINDOW_END_EPOCH)"
equals "--at state notice id" 42 "$(release_state_get "$STATE/scheduled" NOTICE_ID)"
equals "--at state outcome empty" "" "$(release_state_get "$STATE/scheduled" OUTCOME)"
equals "--at state mode" 640 "$(stat -c %a "$STATE/scheduled")"
lacks "--at never chowns or chmods the service-owned state" "chown" "$L"
contains "--at writes the state as the service account" "runuser -u $(id -un) -- env APP_DIR=$APP STATE_DIR=$STATE RELEASE_LIB_DIR=$LIB ENV_FILE=$APP/deploy/compose/.env bash -c" "$L"
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
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH=1 AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH=9999999999 NOTICE_ID=7 BY=ops CREATED_AT=1 OUTCOME= REASON=
mkdir -p "$DROP"; printf '[Timer]\n' >"$DROP/slot.conf"
run --fire
equals "--fire exits 0" 0 "$RC"
L="$(logtext)"
contains "--fire starts the unit with --no-block" "systemctl start --no-block manuspectrum-update@v1.2.0.service" "$L"
equals "--fire removed the drop-in" no "$([ -e "$DROP/slot.conf" ] && echo yes || echo no)"
contains "--fire stops the timer" "systemctl stop manuspectrum-update-at.timer" "$L"
equals "--fire keeps the scheduled file for the engine" yes "$([ -e "$STATE/scheduled" ] && echo yes || echo no)"
reset
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH=1 AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH=9999999999 NOTICE_ID=7 BY=ops CREATED_AT=1 OUTCOME= REASON=
FAKE_ACTIVE=manuspectrum-update@v1.2.0.service
run --fire
equals "--fire with a running unit refused" 1 "$RC"
equals "--fire busy records the outcome" refused "$(release_state_get "$STATE/scheduled" OUTCOME)"
equals "--fire busy records the reason" busy "$(release_state_get "$STATE/scheduled" REASON)"
contains "--fire busy withdraws the notice" "ARGS=withdraw 7" "$(logtext)"
lacks "--fire busy starts nothing" "systemctl start" "$(logtext)"

reset
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH=1 AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH="$((NOW_SPRING - 60))" NOTICE_ID=7 BY=ops CREATED_AT=1 OUTCOME= REASON=
mkdir -p "$DROP"; printf '[Timer]\n' >"$DROP/slot.conf"
run --fire
equals "--fire past its window exits 1" 1 "$RC"
equals "--fire past its window records missed" missed "$(release_state_get "$STATE/scheduled" OUTCOME)"
equals "--fire past its window records the reason late" late "$(release_state_get "$STATE/scheduled" REASON)"
lacks "--fire past its window starts no unit" "systemctl start" "$(logtext)"
contains "--fire past its window withdraws the notice" "ARGS=withdraw 7" "$(logtext)"
contains "--fire past its window mails the miss" "scheduled update of v1.2.0 missed (past its window)" "$(cat "$MAILS")"
reset
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH=1 AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH="$NOW_SPRING" NOTICE_ID=7 BY=ops CREATED_AT=1 OUTCOME= REASON=
run --fire
equals "--fire exactly at the end of the window still starts" 0 "$RC"

reset
release_state_write "$STATE/scheduled" TAG=v1.2.0 AT_EPOCH=1 AT_PARIS="2027-03-22 23:00" WINDOW_END_EPOCH=9999999999 NOTICE_ID=7 BY=ops CREATED_AT=1 OUTCOME= REASON=
: >"$TMP/ansible-running"
run --fire
equals "--fire while Ansible runs is refused" 1 "$RC"
equals "--fire while Ansible runs records busy" busy "$(release_state_get "$STATE/scheduled" REASON)"
lacks "--fire while Ansible runs starts nothing" "systemctl start" "$(logtext)"

# --- --status
reset
run --status
equals "--status exits 0" 0 "$RC"
contains "--status current" "current:   v1.1.0" "$OUT"
contains "--status armed" "armed:    v1.2.0" "$OUT"
contains "--status armed flags" "security=1 needs_ansible=0" "$OUT"
contains "--status nothing scheduled" "scheduled: none" "$OUT"
contains "--status nothing in flight" "inflight: none" "$OUT"
rm -f "$STATE/current"
git -C "$APP" init -q
git -C "$APP" -c user.name=t -c user.email=t@manuspectrum.test -c commit.gpgsign=false commit -q --allow-empty -m probe
run --status
contains "--status without a recorded update and an untagged checkout" "current:   unknown" "$OUT"
git -C "$APP" -c tag.gpgsign=false tag v1.0.0-rc.1
HEAD_SHA="$(git -C "$APP" rev-parse HEAD)"
run --status
contains "--status without a recorded update reads the checkout" "current:   v1.0.0-rc.1 ($HEAD_SHA) (from the checkout)" "$OUT"
rm -rf "$APP/.git"
release_state_write "$STATE/current" TAG=v1.1.0 IMAGE="${IMG%@*}@sha256:$(printf 'c%.0s' {1..64})" COMMIT="$(printf 'd%.0s' {1..40})" APPLIED_AT=1
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
contains "--status rollback failed instructions" "sudo manuspectrum-update --resolved" "$OUT"
lacks "--status no longer tells to remove the file by hand" "remove $STATE/inflight" "$OUT"

# --- the service account gets its environment on the command line
reset
FAKE_STATUS=0
run --now v1.2.0
contains "the check receives APP_DIR, STATE_DIR, RELEASE_LIB_DIR and ENV_FILE explicitly" "env APP_DIR=$APP STATE_DIR=$STATE RELEASE_LIB_DIR=$LIB ENV_FILE=$APP/deploy/compose/.env" "$(logtext)"

# --- root never follows a state symlink
reset
printf 'TAG=v9.9.9\nAT_EPOCH=1\nAT_PARIS=2027-03-22 23:00\nWINDOW_END_EPOCH=9999999999\nNOTICE_ID=\nBY=ops\nCREATED_AT=1\nOUTCOME=\nREASON=\n' >"$TMP/outside"
ln -s "$TMP/outside" "$STATE/scheduled"
run --status
equals "--status refuses a symlinked state file" 1 "$RC"
lacks "--status does not print what the link points at" "v9.9.9" "$OUT"
run --cancel
equals "--cancel refuses a symlinked state file" 1 "$RC"
equals "--cancel leaves the link target alone" yes "$([ -e "$TMP/outside" ] && echo yes || echo no)"
reset
printf 'TAG=v1.2.0\n' >"$TMP/outside"
rm -f "$STATE/armed"; ln -s "$TMP/outside" "$STATE/armed"
run --now v1.2.0
equals "--now refuses a symlinked armed file" 1 "$RC"
lacks "--now with a symlinked armed file starts nothing" "systemctl start" "$(logtext)"
rm -f "$TMP/outside"
reset
run --status
contains "state reads run as the service account" "runuser -u $(id -un) -- env APP_DIR=$APP STATE_DIR=$STATE RELEASE_LIB_DIR=$LIB ENV_FILE=$APP/deploy/compose/.env bash -c" "$(cat "$LOG")"
run --at "2027-03-22 23:00" v1.2.0
run --cancel
contains "--cancel removes the state as the service account" "env APP_DIR=$APP STATE_DIR=$STATE RELEASE_LIB_DIR=$LIB ENV_FILE=$APP/deploy/compose/.env rm -f $STATE/scheduled" "$(cat "$LOG")"

# --- host time zone
reset
FAKE_TZ=UTC
run --at "2027-03-22 23:00" v1.2.0
equals "--at on a host that is not on Paris time refused" 1 "$RC"
contains "--at time zone message" "not Europe/Paris" "$OUT"
equals "--at time zone refusal touched no unit, notice or state" "" "$(grep -E 'make|daemon-reload|systemctl start' "$LOG")"
FAKE_TZ=
run --at "2027-03-22 23:00" v1.2.0
equals "--at on Paris time accepted" 0 "$RC"

# --- --now result: only an exited unit maps its status
for code in 2 3; do
  reset
  FAKE_CODE=$code FAKE_STATUS=9
  run --now v1.2.0
  equals "--now ExecMainCode $code (killed or dumped) exits 5" 5 "$RC"
  contains "--now ExecMainCode $code says interrupted" "was interrupted (signal 9)" "$OUT"
  contains "--now ExecMainCode $code points at --status and the runbook" "--status" "$OUT"
  contains "--now ExecMainCode $code points at the runbook" "deploy/runbooks/release.md" "$OUT"
done
reset; FAKE_CODE=3 FAKE_STATUS=3; run --now v1.2.0
equals "a killed unit is never read as a rollback" 5 "$RC"

# --- one mutating command at a time
reset
( exec 8>"$TMP/update.lock"; flock -n 8; exec sleep 20 ) &
holder=$!
sleep 0.3
for cmd in --now --at --cancel; do
  : >"$LOG"
  case "$cmd" in
    --now) run --now v1.2.0 ;;
    --at) run --at "2027-03-22 23:00" v1.2.0 ;;
    --cancel) run --cancel ;;
  esac
  equals "another command is running: $cmd refused" 1 "$RC"
  contains "lock message for $cmd" "another manuspectrum-update is running" "$OUT"
  equals "lock refusal for $cmd changed nothing" "" "$(logtext)"
done
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null
reset
run --status
equals "--status takes no lock" 0 "$RC"

# --- Ansible running
reset
: >"$TMP/ansible-running"
run --now v1.2.0
equals "--now while Ansible runs refused" 1 "$RC"
contains "--now Ansible message" "Ansible is running on this host" "$OUT"
run --at "2027-03-22 23:00" v1.2.0
equals "--at while Ansible runs refused" 1 "$RC"
contains "--at Ansible message" "Ansible is running on this host" "$OUT"
equals "Ansible refusals started nothing" "" "$(logtext)"
rm -f "$TMP/ansible-running"

# --- --resolved
failed_update() { # failed_update: an update that failed, its rollback too
  release_state_write "$STATE/inflight" FROM_TAG=v1.1.0 TO_TAG=v1.2.0 STARTED_AT="$NOW_SPRING" INVOCATION_ID=
  release_state_write "$STATE/rollbacks" COUNT=2 ROLLBACK_FAILED=1
}
has_file() { [ -e "$1" ] && echo yes || echo no; }
reset; failed_update
OUT="$(printf 'yes\n' | bash "$(mkfront "$NOW_SPRING" 1)" --resolved 2>&1)"; RC=$?
equals "--resolved without a terminal refused" 1 "$RC"
contains "--resolved no terminal message" "needs a terminal" "$OUT"
equals "--resolved without a terminal changed nothing" yes "$(has_file "$STATE/inflight")"
run --resolved extra; equals "--resolved takes no argument" 2 "$RC"
reset; failed_update; FAKE_ACTIVE=manuspectrum-update@v1.2.0.service
run --resolved
equals "--resolved while an update unit is active refused" 1 "$RC"
equals "--resolved while a unit is active kept inflight" yes "$(has_file "$STATE/inflight")"
equals "--resolved while a unit is active kept ROLLBACK_FAILED" 1 "$(release_state_get "$STATE/rollbacks" ROLLBACK_FAILED)"
reset; failed_update; : >"$TMP/ansible-running"
run --resolved
equals "--resolved while Ansible runs refused" 1 "$RC"
contains "--resolved Ansible message" "Ansible is running on this host" "$OUT"
equals "--resolved while Ansible runs kept inflight" yes "$(has_file "$STATE/inflight")"
rm -f "$TMP/ansible-running"
reset
run --resolved
equals "--resolved with nothing to resolve exits 0" 0 "$RC"
contains "--resolved nothing to resolve message" "Nothing to resolve" "$OUT"
lacks "--resolved with nothing to resolve mails nothing" "sendmail" "$(logtext)"
reset; failed_update
OUT="$(printf 'no\n' | bash "$(mkfront)" --resolved 2>&1)"; RC=$?
equals "--resolved not confirmed refused" 1 "$RC"
equals "--resolved not confirmed kept inflight" yes "$(has_file "$STATE/inflight")"
reset; failed_update
run --resolved
equals "--resolved exits 0" 0 "$RC"
equals "--resolved removes inflight" no "$(has_file "$STATE/inflight")"
equals "--resolved clears ROLLBACK_FAILED" 0 "$(release_state_get "$STATE/rollbacks" ROLLBACK_FAILED)"
equals "--resolved keeps the rollback count" 2 "$(release_state_get "$STATE/rollbacks" COUNT)"
contains "--resolved removes the file as the service account" "env APP_DIR=$APP STATE_DIR=$STATE RELEASE_LIB_DIR=$LIB ENV_FILE=$APP/deploy/compose/.env rm -f $STATE/inflight" "$(cat "$LOG")"
grep -q '^manuspectrum_release_rollback_failed 0$' "$TMP/metrics/manuspectrum_release.prom" && grep -q '^manuspectrum_release_inflight_since_timestamp_seconds 0$' "$TMP/metrics/manuspectrum_release.prom" && ok "--resolved rewrites the metrics" || not_ok "--resolved rewrites the metrics" "$(cat "$TMP/metrics/manuspectrum_release.prom" 2>&1)"
contains "--resolved mails who resolved it" "Subject: [ManuSpectrum][Release] manuspectrum.test: failed update marked as resolved by root" "$(cat "$MAILS")"
run --status
contains "--status after --resolved shows no inflight" "inflight: none" "$OUT"
lacks "--status after --resolved shows no failed rollback" "ROLLBACK FAILED" "$OUT"
reset; release_state_write "$STATE/inflight" FROM_TAG=v1.1.0 TO_TAG=v1.2.0 STARTED_AT="$NOW_SPRING" INVOCATION_ID=
run --resolved
equals "--resolved clears an interrupted inflight without a rollbacks file" 0 "$RC"
equals "--resolved without a rollbacks file creates none" no "$(has_file "$STATE/rollbacks")"
reset; release_state_write "$STATE/rollbacks" COUNT=1 ROLLBACK_FAILED=1
run --resolved
equals "--resolved clears ROLLBACK_FAILED when inflight is already gone" 0 "$(release_state_get "$STATE/rollbacks" ROLLBACK_FAILED)"
reset; failed_update
( exec 8>"$TMP/update.lock"; flock -n 8; exec sleep 20 ) &
holder=$!
sleep 0.3
run --resolved
equals "another command is running: --resolved refused" 1 "$RC"
contains "lock message for --resolved" "another manuspectrum-update is running" "$OUT"
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null
reset; failed_update; rm -f "$STATE/inflight"; ln -s "$TMP/outside-link" "$STATE/inflight"
run --resolved
equals "--resolved refuses a symlinked inflight" 1 "$RC"

# --- the slot is parsed again after the confirmation
reset
PROMPT_DELAY=259200 run --at "2027-03-22 23:00" v1.2.0
unset PROMPT_DELAY
equals "--at whose slot passed during the prompt refused" 1 "$RC"
contains "--at re-parse message" "no longer valid" "$OUT"
equals "--at re-parse refusal scheduled nothing" no "$([ -e "$STATE/scheduled" ] && echo yes || echo no)"
lacks "--at re-parse refusal touched no timer" "update-at.timer" "$(logtext)"

echo "# $N tests"
exit "$FAILED"
