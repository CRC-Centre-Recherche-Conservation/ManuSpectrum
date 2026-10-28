#!/usr/bin/env bash
# deploy/scripts/tests/test_release_update.sh
# Tests of release-update.sh on throwaway git repositories (a bare origin with
# annotated tags and a clone as the checkout) with fake `docker`, `make` and
# sendmail on PATH, and fake release-verify.sh / image-digest.sh in the library
# directory (the real lib-release.sh and release-managed.sh). The fake make logs
# the state it sees when it runs. Prints `ok N` / `not ok N`; exits non-zero on
# failure.
# shellcheck disable=SC2319,SC2015,SC2001,SC2030,SC2031,SC2016,SC2034
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$HERE/.."
ENGINE="${RELEASE_UPDATE_UNDER_TEST:-$SCRIPTS/release-update.sh}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }
check() { # check NAME COMMAND...
  local name="$1" out
  shift
  out="$("$@" 2>&1)" && ok "$name" || not_ok "$name" "$out"
}
equals() { [ "$2" = "$3" ] && ok "$1" || not_ok "$1" "expected: $2
actual:   $3"; }

GIT=(git -c user.name=t -c user.email=t@manuspectrum.test -c commit.gpgsign=false -c tag.gpgsign=false)
D1="sha256:$(printf '1%.0s' {1..64})"
D2="sha256:$(printf '2%.0s' {1..64})"
REPO=ghcr.io/crc-centre-recherche-conservation/manuspectrum

# --- the origin: v1.0.0 (a managed file, two env keys) and v1.1.0 (changes both)
SRC="$TMP/src"
ORIGIN="$TMP/origin.git"
git init -q "$SRC" && git init -q --bare -b main "$ORIGIN"
(
  cd "$SRC" || exit 1
  mkdir -p deploy/compose deploy/sbin
  printf 'deploy/compose/.env\n' >.gitignore
  printf 'A_KEY=1\nRELEASE_CHANNEL=prod\n' >deploy/compose/.env.example
  printf 'front v1\n' >deploy/sbin/front
  "${GIT[@]}" add -A && "${GIT[@]}" commit -qm one && "${GIT[@]}" tag -a -m v1.0.0 v1.0.0
  printf 'A_KEY=1\nRELEASE_CHANNEL=prod\nNEW_KEY=2\n' >deploy/compose/.env.example
  printf 'front v2\n' >deploy/sbin/front
  "${GIT[@]}" add -A && "${GIT[@]}" commit -qm two && "${GIT[@]}" tag -a -m v1.1.0 v1.1.0
  git push -q "$ORIGIN" HEAD:refs/heads/main --tags
)
C1="$(git -C "$SRC" rev-parse "v1.0.0^{commit}")"
C2="$(git -C "$SRC" rev-parse "v1.1.0^{commit}")"

# --- fakes
FAKE="$TMP/fake"
mkdir -p "$FAKE/bin" "$FAKE/lib"
cat >"$FAKE/bin/docker" <<'SH'
#!/bin/bash
echo "docker $*" >>"$FAKE_LOG"
case "$1 $2" in
  "image ls") [ ! -f "$FAKE_DIR/images" ] || cat "$FAKE_DIR/images"; exit 0 ;;
  "image rm") exit 0 ;;
esac
case "$1" in
  image) printf '%s\n' "${FAKE_LABEL-}"; exit 0 ;;
  compose)
    last="$(sed -n 's/^MANUSPECTRUM_IMAGE=.*sha256:\(.\).*/\1/p' "$FAKE_ENV" | tail -n 1)"
    if [ -f "$FAKE_DIR/ready_$last" ]; then cat "$FAKE_DIR/ready_$last"; else printf 200; fi
    exit 0 ;;
esac
exit 2
SH
cat >"$FAKE/bin/make" <<'SH'
#!/bin/bash
target=""
args=("$@")
i=0
while [ "$i" -lt "${#args[@]}" ]; do
  case "${args[i]}" in -C) i=$((i + 1)) ;; *=*) ;; *) [ -n "$target" ] || target="${args[i]}" ;; esac
  i=$((i + 1))
done
last="$(sed -n 's/^MANUSPECTRUM_IMAGE=.*sha256:\(.\).*/\1/p' "$FAKE_ENV" | tail -n 1)"
head_tag="$(git -C "$FAKE_APP" describe --tags --exact-match 2>/dev/null)"
if ( flock -n 9 ) 9>"$FAKE_DUMP/.lock"; then lock=free; else lock=held; fi
inflight=0; [ ! -e "$FAKE_STATE/inflight" ] || inflight=1
echo "make $target head=$head_tag env=$last lock=$lock inflight=$inflight :: $*" >>"$FAKE_LOG"
case "$target" in
  backup)
    [ ! -e "$FAKE_DIR/backup_fail" ] || exit 1
    [ ! -e "$FAKE_DIR/backup_closes_window" ] || sed -i 's/^WINDOW_END_EPOCH=.*/WINDOW_END_EPOCH=1790003050/' "$FAKE_STATE/scheduled" ;;
  up)
    if [ -e "$FAKE_DIR/up_slow_$last" ]; then touch "$FAKE_DIR/up_started"; sleep 2; touch "$FAKE_DIR/up_finished"; fi
    [ ! -e "$FAKE_DIR/up_fail_$last" ] || exit 1 ;;
  site-notice) [ ! -e "$FAKE_DIR/notice_fail" ] || exit 1 ;;
esac
exit 0
SH
cat >"$FAKE/bin/curl" <<'SH'
#!/bin/bash
echo "curl $*" >>"$FAKE_LOG"
if [ -e "$FAKE_DIR/probe_down_sigstore" ]; then echo "curl: (28) timed out" >&2; exit 28; fi
printf 200
SH
{
  printf '#!/bin/bash\nREAL_GIT=%q\n' "$(command -v git)"
  cat <<'SH'
for a in "$@"; do [ "$a" != submodule ] || sub=1; done
if [ -n "${sub-}" ] && [ -e "$FAKE_DIR/submodule_fail" ] && [ "$("$REAL_GIT" -C "$FAKE_APP" rev-parse HEAD)" = "$FAKE_C2" ]; then
  echo "fatal: could not update submodule" >&2
  exit 1
fi
exec "$REAL_GIT" "$@"
SH
} >"$FAKE/bin/git"
cat >"$FAKE/bin/sendmail" <<'SH'
#!/bin/bash
n=$(ls "$FAKE_MAIL" | wc -l)
cat >"$FAKE_MAIL/$((n + 1)).eml"
SH
cat >"$FAKE/lib/release-verify.sh" <<'SH'
#!/bin/bash
echo "verify cwd=$PWD :: $*" >>"$FAKE_LOG"
if [ -e "$FAKE_DIR/verify_fail" ]; then echo "release-verify: signature check failed" >&2; exit 1; fi
echo "${@: -1}"
SH
cat >"$FAKE/lib/image-digest.sh" <<'SH'
#!/bin/bash
echo "image-digest $*" >>"$FAKE_LOG"
if [ -e "$FAKE_DIR/digest_override" ]; then cat "$FAKE_DIR/digest_override"; else echo "$FAKE_D2"; fi
SH
chmod +x "$FAKE"/bin/* "$FAKE"/lib/*
cp "$SCRIPTS/lib-release.sh" "$SCRIPTS/lib-metrics.sh" "$SCRIPTS/release-managed.sh" "$FAKE/lib/" 2>/dev/null

RNOW=1790003100 # inside the window of sched() below

# --- one scenario: W/{app,state,dump,metrics,mail,fake}
setup() {
  W="$TMP/w$N-$RANDOM"
  mkdir -p "$W/state" "$W/dump" "$W/metrics" "$W/mail" "$W/f"; : >"$W/state/lock"
  git clone -q "$ORIGIN" "$W/app" && git -C "$W/app" checkout -q --detach v1.0.0
  cat >"$W/app/deploy/compose/.env" <<EOF
MANUSPECTRUM_IMAGE=$REPO@$D1
RELEASE_CHANNEL=rc
RELEASE_READY_WAIT_SECONDS=1
A_KEY=1
NEW_KEY=2
PUBLIC_HOST=manuspectrum.test
ALERT_EMAILS=ops@manuspectrum.test
ALERT_EMAIL_FROM=noreply@manuspectrum.test
BACKUP_DUMP_DIR=$W/dump
METRICS_TEXTFILE_DIR=$W/metrics
EOF
  ENVF="$W/app/deploy/compose/.env"
  release_state_w current "TAG=v1.0.0" "IMAGE=$REPO@$D1" "COMMIT=$C1" "APPLIED_AT=1700000000"
  release_state_w armed "TAG=v1.1.0" "IMAGE=$REPO@$D2" "COMMIT=$C2" ARMED_AT=1790000000 SECURITY=0 NOTIFIED=1 NEEDS_ANSIBLE=0
  release_state_w pending SINCE=1789999000 SECURITY=0
  git -C "$W/app" fetch -q --tags origin
  bash "$FAKE/lib/release-managed.sh" --ref v1.1.0 --repo "$W/app" >"$W/managed"
  LOG="$W/f/log"
  : >"$LOG"
}
release_state_w() { # release_state_w NAME KEY=value...: writes a state file without the library
  local name="$1"
  shift
  printf '%s\n' "$@" >"$W/state/$name"
}

engine() { # engine ARGS...: runs the engine from an unrelated directory; sets RC, OUT
  OUT="$(cd "$TMP" && env -i PATH="$FAKE/bin:$PATH" HOME="$TMP" \
    APP_DIR="$W/app" STATE_DIR="$W/state" ENV_FILE="$ENVF" MANAGED_SOURCES="$W/managed" RELEASE_LIB_DIR="$FAKE/lib" \
    RELEASE_SENDMAIL="$FAKE/bin/sendmail" RELEASE_READY_INTERVAL=0.1 UPDATE_LOCK_WAIT=1 BACKUP_LOCK_WAIT=1 \
    FAKE_LOG="$LOG" FAKE_DIR="$W/f" FAKE_ENV="$ENVF" FAKE_APP="$W/app" FAKE_STATE="$W/state" FAKE_DUMP="$W/dump" FAKE_MAIL="$W/mail" \
    FAKE_D2="$D2" FAKE_C2="$C2" FAKE_LABEL="${FAKE_LABEL-$C1}" ANSIBLE_MARKER="$W/ansible-running" \
    ${RNOW:+RELEASE_NOW_EPOCH=$RNOW} ${SERVICE_RESULT:+SERVICE_RESULT=$SERVICE_RESULT} ${EXIT_STATUS:+EXIT_STATUS=$EXIT_STATUS} ${EXIT_CODE:+EXIT_CODE=$EXIT_CODE} ${INVOCATION_ID:+INVOCATION_ID=$INVOCATION_ID} \
    bash "$ENGINE" "$@" 2>&1)"
  RC=$?
}

sget() { sed -n "s/^$2=//p" "$W/state/$1" 2>/dev/null; }
head_of() { git -C "$W/app" rev-parse HEAD; }
logline() { grep -n -m1 -- "$1" "$LOG" | cut -d: -f1; }
has() { grep -qE -- "$1" "$LOG"; }
mails() { cat "$W"/mail/*.eml 2>/dev/null; }
snapshot() { SNAP="$(sha256sum "$ENVF" | cut -d' ' -f1) $(head_of) $(find "$W/state" -type f -printf '%f ' | LC_ALL=C sort | tr -d '\n') $(cat "$W"/state/* | sha256sum | cut -d' ' -f1)"; }

# A refusal: exit 1, a REASON, .env, HEAD and the state untouched, no backup, no switch.
expect_refusal() { # expect_refusal NAME REASON [FRAGMENT-OF-OUTPUT]
  local name="$1" reason="$2" frag="${3-}"
  if [ "$RC" != 1 ]; then not_ok "$name: exit 1" "exit $RC: $OUT"; return; fi
  grep -q "^REASON=$reason$" <<<"$OUT" && ok "$name: REASON=$reason" || not_ok "$name: REASON=$reason" "$OUT"
  [ -z "$frag" ] || { grep -qF -- "$frag" <<<"$OUT" && ok "$name: says $frag" || not_ok "$name: says $frag" "$OUT"; }
  [ "$(sha256sum "$ENVF" | cut -d' ' -f1) $(head_of)" = "$ENV_BEFORE $HEAD_BEFORE" ] && ok "$name: .env and HEAD untouched" || not_ok "$name: .env and HEAD untouched"
  has '^make (up|backup) ' && not_ok "$name: no backup, no up" "$(cat "$LOG")" || ok "$name: no backup, no up"
}
before() { ENV_BEFORE="$(sha256sum "$ENVF" | cut -d' ' -f1)"; HEAD_BEFORE="$(head_of)"; }
refusal_case() { # refusal_case NAME REASON FRAGMENT  (the scenario was set up by the caller)
  before
  engine v1.1.0
  expect_refusal "$@"
}

if [ ! -f "$ENGINE" ]; then
  not_ok "release-update.sh exists" "$ENGINE is missing"
  echo "1..$N"
  exit 1
fi

# --- success: order, state, mail, metrics
setup
before
engine v1.1.0
equals "success: exit 0" 0 "$RC"
[ "$RC" = 0 ] || echo "$OUT" | sed 's/^/#   /'
b="$(logline '^make backup')"; u="$(logline '^make up')"; r="$(logline '^docker compose')"
{ [ -n "$b" ] && [ -n "$u" ] && [ -n "$r" ] && [ "$b" -lt "$u" ] && [ "$u" -lt "$r" ]; } && ok "success: backup, then up, then readiness" || not_ok "success: backup, then up, then readiness" "$(cat "$LOG")"
grep -q '^make backup head=v1.0.0 env=1 lock=free inflight=0 .*TAG=pre-update' "$LOG" && ok "success: backup runs on the old version, lock free, nothing in flight" || not_ok "success: backup on the old version" "$(cat "$LOG")"
grep -q '^make up head=v1.1.0 env=2 lock=held inflight=1 .*UP_WAIT_TIMEOUT=1' "$LOG" && ok "success: up sees the new tag, the new image, the held backup lock, inflight, the wait" || not_ok "success: up state" "$(cat "$LOG")"
grep -q 'exec -T web curl -s -m 15 -o /dev/null -w %{http_code} -H Host: web http://127.0.0.1:8000/readyz' "$LOG" && ok "success: readiness probes /readyz in web" || not_ok "success: readiness command" "$(cat "$LOG")"
grep -q "^verify cwd=$W/app :: --policy rc $REPO@$D2 v1.1.0 --commit $C2 --repo-dir $W/app$" "$LOG" && ok "success: release-verify from APP_DIR with --commit and --repo-dir" || not_ok "success: release-verify arguments" "$(grep '^verify' "$LOG")"
equals "success: HEAD is the tag commit" "$C2" "$(head_of)"
equals "success: .env has the new image" "MANUSPECTRUM_IMAGE=$REPO@$D2" "$(grep '^MANUSPECTRUM_IMAGE=' "$ENVF")"
equals "success: current is the armed release" "v1.1.0" "$(sget current TAG)"
equals "success: current has the armed commit" "$C2" "$(sget current COMMIT)"
[ -n "$(sget current APPLIED_AT)" ] && ok "success: current has APPLIED_AT" || not_ok "success: current has APPLIED_AT"
equals "success: previous is the old current" "v1.0.0" "$(sget previous TAG)"
check "success: armed, pending and inflight removed" test ! -e "$W/state/armed" -a ! -e "$W/state/pending" -a ! -e "$W/state/inflight"
grep -qP '^\S+\tinstalled\tv1.0.0\tv1.1.0$' "$W/state/history.log" && ok "success: history line" || not_ok "success: history line" "$(cat "$W/state/history.log" 2>&1)"
grep -q '^Subject: \[ManuSpectrum\]\[Release\] v1.1.0 installed on manuspectrum.test$' <<<"$(mails)" && ok "success: installed mail" || not_ok "success: installed mail" "$(mails)"
P="$W/metrics/manuspectrum_release.prom"
grep -q '^manuspectrum_release_armed 0$' "$P" && grep -qE '^manuspectrum_release_update_last_success_timestamp_seconds [1-9]' "$P" && ok "success: metrics (not armed, last success set)" || not_ok "success: metrics" "$(cat "$P" 2>&1)"
has '^make (restore|init|load-snapshot)' && not_ok "success: never restore, init or load-snapshot" || ok "success: never restore, init or load-snapshot"
check "success: the backup lock is free again" bash -c "( flock -n 9 ) 9>'$W/dump/.lock'"
check "success: no lock held by a child" bash -c "( flock -n 9 ) 9>'$W/state/lock'"

# --- refusals: nothing changes
setup; printf 'other\n' >"$W/app/stray.txt"; refusal_case "dirty worktree" drift "stray.txt"
setup; sed -i "s|^MANUSPECTRUM_IMAGE=.*|MANUSPECTRUM_IMAGE=$REPO@$D2|" "$ENVF"; refusal_case ".env image differs from current" drift
setup; release_state_w current "TAG=v1.0.0" "IMAGE=$REPO@$D1" "COMMIT=$C2" "APPLIED_AT=1"; refusal_case "HEAD differs from current" drift
setup; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1; refusal_case "an update in flight" busy
setup; rm "$W/state/armed"; refusal_case "nothing armed" unarmed
setup; release_state_w armed "TAG=v1.2.0" "IMAGE=$REPO@$D2" "COMMIT=$C2" ARMED_AT=1 SECURITY=0 NOTIFIED=1 NEEDS_ANSIBLE=0; refusal_case "another tag armed" unarmed
setup; release_state_w armed "TAG=v1.1.0" "IMAGE=$REPO@$D2" "COMMIT=$C1" ARMED_AT=1 SECURITY=0 NOTIFIED=1 NEEDS_ANSIBLE=0; refusal_case "tag names another commit than the armed one" tag_moved
setup; printf 'sha256:%s\n' "$(printf '3%.0s' {1..64})" >"$W/f/digest_override"; refusal_case "registry tag moved" tag_moved "armed digest"
setup; sed -i '/^NEW_KEY=/d' "$ENVF"; refusal_case ".env lacks a key of the tag" env_keys "NEW_KEY"
setup; sed -i '1s/^[0-9a-f]*/0000000000000000000000000000000000000000000000000000000000000000/' "$W/managed"; refusal_case "managed sources differ" managed_sources "Ansible"
grep -qF "deploy/sbin/front" <<<"$OUT" && ok "managed sources: the differing path is listed" || not_ok "managed sources: the differing path is listed" "$OUT"
setup; rm "$W/managed"; refusal_case "managed sources file missing" managed_sources
setup; touch "$W/f/verify_fail"; refusal_case "verification fails" verify "signature"
grep -q '^manuspectrum_release_verification_failed 1$' "$W/metrics/manuspectrum_release.prom" && ok "verify refusal: metric verification_failed" || not_ok "verify refusal: metric verification_failed"
setup; git -C "$W/app" remote set-url origin "$TMP/nowhere.git"; refusal_case "fetch fails" fetch
setup; before; engine v1.1; expect_refusal "malformed tag" unarmed
setup; sed -i 's/^RELEASE_CHANNEL=.*/RELEASE_CHANNEL=beta/' "$ENVF"; refusal_case "unknown channel" env_keys
setup; ( exec 7>"$W/state/lock"; flock 7; sleep 3 ) & holder=$!; sleep 0.3
before; engine v1.1.0; expect_refusal "lock held" lock; wait "$holder" 2>/dev/null

# a refused backup stops before the switch
setup; touch "$W/f/backup_fail"; before; engine v1.1.0
{ [ "$RC" = 1 ] && grep -q '^REASON=backup$' <<<"$OUT"; } && ok "backup failure: refused with REASON=backup" || not_ok "backup failure: refused" "$RC $OUT"
has '^make up' && not_ok "backup failure: no up" || ok "backup failure: no up"
[ "$(sha256sum "$ENVF" | cut -d' ' -f1) $(head_of)" = "$ENV_BEFORE $HEAD_BEFORE" ] && ok "backup failure: .env and HEAD untouched" || not_ok "backup failure: .env and HEAD untouched"
check "backup failure: no inflight" test ! -e "$W/state/inflight"

# --- rollback
setup; printf 500 >"$W/f/ready_2"; before; engine v1.1.0
equals "rollback: exit 3" 3 "$RC"
[ "$RC" = 3 ] || echo "$OUT" | sed 's/^/#   /'
mapfile -t ups < <(grep -n '^make up' "$LOG" | cut -d: -f1)
{ [ "${#ups[@]}" = 2 ] && grep -q '^make up head=v1.1.0 env=2' <<<"$(sed -n "${ups[0]}p" "$LOG")" && grep -q '^make up head=v1.0.0 env=1' <<<"$(sed -n "${ups[1]}p" "$LOG")"; } && ok "rollback: up on the new version, then up on the old one" || not_ok "rollback: two ups in order" "$(cat "$LOG")"
mid="$(sed -n "${ups[0]},${ups[1]}p" "$LOG" | grep -c '^docker compose')"
[ "$mid" -ge 2 ] && ok "rollback: readiness polled until the deadline before the rollback" || not_ok "rollback: readiness polled before the rollback ($mid)"
after="$(sed -n "${ups[1]},\$p" "$LOG" | grep -c '^docker compose')"
[ "$after" -ge 1 ] && ok "rollback: readiness checked after the rollback" || not_ok "rollback: readiness after the rollback"
equals "rollback: HEAD is back" "$HEAD_BEFORE" "$(head_of)"
equals "rollback: .env is back" "$ENV_BEFORE" "$(sha256sum "$ENVF" | cut -d' ' -f1)"
equals "rollback: rollbacks counter" 1 "$(sget rollbacks COUNT)"
equals "rollback: current unchanged" v1.0.0 "$(sget current TAG)"
check "rollback: armed kept, inflight gone" test -e "$W/state/armed" -a ! -e "$W/state/inflight"
grep -q '^Subject: \[ManuSpectrum\]\[Release\] v1.1.0 rolled back$' <<<"$(mails)" && ok "rollback: mail" || not_ok "rollback: mail" "$(mails)"
grep -q '^manuspectrum_release_rollbacks_total 1$' "$P" 2>/dev/null; grep -q '^manuspectrum_release_rollbacks_total 1$' "$W/metrics/manuspectrum_release.prom" && ok "rollback: metric rollbacks_total" || not_ok "rollback: metric rollbacks_total"
has '^make (restore|init|load-snapshot)' && not_ok "rollback: never restore, init or load-snapshot" || ok "rollback: never restore, init or load-snapshot"

setup; touch "$W/f/up_fail_2"; before; engine v1.1.0
equals "make up failing: exit 3" 3 "$RC"
equals "make up failing: HEAD back" "$HEAD_BEFORE" "$(head_of)"
has '^docker compose' && ok "make up failing: rollback waited for readiness" || not_ok "make up failing: rollback waited for readiness"

# --- rollback fails too
setup; printf 500 >"$W/f/ready_2"; printf 500 >"$W/f/ready_1"; engine v1.1.0
equals "rollback failed: exit 4" 4 "$RC"
equals "rollback failed: ROLLBACK_FAILED=1" 1 "$(sget rollbacks ROLLBACK_FAILED)"
check "rollback failed: inflight kept, armed kept" test -e "$W/state/inflight" -a -e "$W/state/armed"
m="$(mails)"
{ grep -q '^Subject: \[ManuSpectrum\]\[Release\] v1.1.0 ROLLBACK FAILED$' <<<"$m" && grep -qF 'make -C deploy restic ARGS="snapshots --tag pre-update"' <<<"$m" && grep -qF 'make -C deploy restore RESTIC_SNAPSHOT=<id> CONFIRM=yes ERASURES_CHECKED=yes' <<<"$m"; } && ok "rollback failed: mail names the restore commands" || not_ok "rollback failed: mail" "$m"
grep -q '^manuspectrum_release_rollback_failed 1$' "$W/metrics/manuspectrum_release.prom" && ok "rollback failed: metric" || not_ok "rollback failed: metric"
has '^make (restore|init|load-snapshot)' && not_ok "rollback failed: never restore, init or load-snapshot" || ok "rollback failed: never restore, init or load-snapshot"
before; engine v1.1.0
{ [ "$RC" = 1 ] && grep -q '^REASON=drift$\|^REASON=busy$' <<<"$OUT"; } && ok "after a failed rollback nothing runs until the operator clears it" || not_ok "after a failed rollback nothing runs" "$RC $OUT"

# --- SIGTERM during readiness
setup; printf 500 >"$W/f/ready_2"; sed -i 's/^RELEASE_READY_WAIT_SECONDS=.*/RELEASE_READY_WAIT_SECONDS=60/' "$ENVF"; before
( cd "$TMP" && exec env -i PATH="$FAKE/bin:$PATH" HOME="$TMP" APP_DIR="$W/app" STATE_DIR="$W/state" ENV_FILE="$ENVF" MANAGED_SOURCES="$W/managed" RELEASE_LIB_DIR="$FAKE/lib" \
  RELEASE_SENDMAIL="$FAKE/bin/sendmail" RELEASE_READY_INTERVAL=0.1 FAKE_LOG="$LOG" FAKE_DIR="$W/f" FAKE_ENV="$ENVF" FAKE_APP="$W/app" FAKE_STATE="$W/state" FAKE_DUMP="$W/dump" FAKE_MAIL="$W/mail" FAKE_D2="$D2" FAKE_C2="$C2" FAKE_LABEL="$C1" ANSIBLE_MARKER="$W/ansible-running" RELEASE_NOW_EPOCH=1790003100 \
  bash "$ENGINE" v1.1.0 >"$W/out" 2>&1 ) &
pid=$!
for _ in $(seq 1 100); do has '^docker compose' && break; sleep 0.1; done
kill -TERM "$pid" 2>/dev/null
wait "$pid"; RC=$?
equals "SIGTERM during readiness: exit 3" 3 "$RC"
equals "SIGTERM during readiness: HEAD back" "$HEAD_BEFORE" "$(head_of)"
equals "SIGTERM during readiness: .env back" "$ENV_BEFORE" "$(sha256sum "$ENVF" | cut -d' ' -f1)"
equals "SIGTERM during readiness: rollbacks counter" 1 "$(sget rollbacks COUNT)"
check "SIGTERM during readiness: armed kept" test -e "$W/state/armed"

# --- SIGTERM during `make up`: the trap defers, make up finishes, then the rollback
setup; touch "$W/f/up_slow_2"; sed -i 's/^RELEASE_READY_WAIT_SECONDS=.*/RELEASE_READY_WAIT_SECONDS=60/' "$ENVF"; before
( cd "$TMP" && exec env -i PATH="$FAKE/bin:$PATH" HOME="$TMP" APP_DIR="$W/app" STATE_DIR="$W/state" ENV_FILE="$ENVF" MANAGED_SOURCES="$W/managed" RELEASE_LIB_DIR="$FAKE/lib" \
  RELEASE_SENDMAIL="$FAKE/bin/sendmail" RELEASE_READY_INTERVAL=0.1 FAKE_LOG="$LOG" FAKE_DIR="$W/f" FAKE_ENV="$ENVF" FAKE_APP="$W/app" FAKE_STATE="$W/state" FAKE_DUMP="$W/dump" FAKE_MAIL="$W/mail" FAKE_D2="$D2" FAKE_C2="$C2" FAKE_LABEL="$C1" ANSIBLE_MARKER="$W/ansible-running" RELEASE_NOW_EPOCH=1790003100 \
  bash "$ENGINE" v1.1.0 >"$W/out" 2>&1 ) &
pid=$!
for _ in $(seq 1 100); do [ -e "$W/f/up_started" ] && break; sleep 0.1; done
kill -TERM "$pid" 2>/dev/null
wait "$pid"; RC=$?
equals "SIGTERM during make up: exit 3" 3 "$RC"
[ -e "$W/f/up_finished" ] && ok "SIGTERM during make up: make up was left to finish" || not_ok "SIGTERM during make up: make up was left to finish"
mapfile -t ups < <(grep -n '^make up' "$LOG" | cut -d: -f1)
equals "SIGTERM during make up: a second up put the old version back" 2 "${#ups[@]}"
equals "SIGTERM during make up: no readiness wait on the new version" 0 "$(sed -n "${ups[0]},${ups[1]}p" "$LOG" | grep -c '^docker compose')"
equals "SIGTERM during make up: HEAD back" "$HEAD_BEFORE" "$(head_of)"
equals "SIGTERM during make up: .env back" "$ENV_BEFORE" "$(sha256sum "$ENVF" | cut -d' ' -f1)"
equals "SIGTERM during make up: rollbacks counter" 1 "$(sget rollbacks COUNT)"

# --- git submodule update failing on the new version rolls back
setup; touch "$W/f/submodule_fail"; before; engine v1.1.0
equals "submodule update failing: exit 3" 3 "$RC"
equals "submodule update failing: HEAD back" "$HEAD_BEFORE" "$(head_of)"
equals "submodule update failing: .env back" "$ENV_BEFORE" "$(sha256sum "$ENVF" | cut -d' ' -f1)"
has '^make up head=v1.1.0' && not_ok "submodule update failing: the new version never started" || ok "submodule update failing: the new version never started"
has '^make up head=v1.0.0' && ok "submodule update failing: the old version was started again" || not_ok "submodule update failing: the old version was started again" "$(cat "$LOG")"
equals "submodule update failing: rollbacks counter" 1 "$(sget rollbacks COUNT)"

# --- bootstrap of a missing `current`
setup; rm "$W/state/current"; engine v1.1.0
equals "bootstrap: update goes through" 0 "$RC"
equals "bootstrap: previous is the bootstrapped version" "v1.0.0" "$(sget previous TAG)"
grep -q "^verify cwd=$W/app :: --policy rc $REPO@$D1 v1.0.0 --commit $C1 --repo-dir $W/app$" "$LOG" && ok "bootstrap: the running image is verified" || not_ok "bootstrap: the running image is verified" "$(grep '^verify' "$LOG")"
setup; rm "$W/state/current"; FAKE_LABEL=deadbeef; before; engine v1.1.0; unset FAKE_LABEL
expect_refusal "bootstrap with a wrong revision label" drift
check "bootstrap refused: no current written" test ! -e "$W/state/current"
setup; rm "$W/state/current"; sed -i "s|^MANUSPECTRUM_IMAGE=.*|MANUSPECTRUM_IMAGE=manuspectrum:local|" "$ENVF"; refusal_case "bootstrap with an image that is not a digest" drift
setup; rm "$W/state/current"; "${GIT[@]}" -C "$W/app" commit -q --allow-empty -m untagged; refusal_case "bootstrap with HEAD off a tag" drift
setup; rm "$W/state/current"; touch "$W/f/verify_fail"; refusal_case "bootstrap when the running image does not verify" drift

# --- --check-only
setup; before; snapshot; s0="$SNAP"; engine --check-only v1.1.0; snapshot
{ [ "$RC" = 0 ] && grep -q '^CHECK=ok$' <<<"$OUT"; } && ok "check-only: passes" || not_ok "check-only: passes" "$RC $OUT"
equals "check-only: .env, HEAD and state unchanged" "$s0" "$SNAP"
has '^make ' && not_ok "check-only: no make" || ok "check-only: no make"
check "check-only: no mail, no metrics" test -z "$(ls "$W/mail")" -a ! -e "$W/metrics/manuspectrum_release.prom"
has '^verify' && ok "check-only: verifies" || not_ok "check-only: verifies"
setup; sed -i '1s/^[0-9a-f]*/0000000000000000000000000000000000000000000000000000000000000000/' "$W/managed"; snapshot; s0="$SNAP"; engine --check-only v1.1.0; snapshot
{ [ "$RC" = 1 ] && grep -q '^REASON=managed_sources$' <<<"$OUT"; } && ok "check-only: refusal has a REASON" || not_ok "check-only: refusal" "$RC $OUT"
equals "check-only: refusal changes nothing" "$s0" "$SNAP"
setup; rm "$W/state/current"; snapshot; s0="$SNAP"; engine --check-only v1.1.0; snapshot
equals "check-only: a missing current is not created" "$s0" "$SNAP"
equals "check-only: bootstrap passes" 0 "$RC"

# --- scheduled context
sched() { release_state_w scheduled TAG=v1.1.0 AT_EPOCH=1790003000 'AT_PARIS=2027-01-05 23:00' WINDOW_END_EPOCH=1790004800 NOTICE_ID=7 BY=op CREATED_AT=1790000000 OUTCOME= REASON= HELD_TAG= NOTIFIED=0; }
setup; sched; sed -i '1s/^[0-9a-f]*/0000000000000000000000000000000000000000000000000000000000000000/' "$W/managed"; engine v1.1.0
equals "scheduled refusal: exit 1" 1 "$RC"
equals "scheduled refusal: OUTCOME" refused "$(sget scheduled OUTCOME)"
equals "scheduled refusal: REASON" managed_sources "$(sget scheduled REASON)"
has 'ARGS=withdraw 7$' && ok "scheduled refusal: notice withdrawn" || not_ok "scheduled refusal: notice withdrawn" "$(cat "$LOG")"
grep -q '^Subject: \[ManuSpectrum\]\[Release\] scheduled update of v1.1.0 refused: managed_sources$' <<<"$(mails)" && ok "scheduled refusal: mail" || not_ok "scheduled refusal: mail" "$(mails)"
grep -q '^manuspectrum_release_schedule_failed{reason="refused"} 1$' "$W/metrics/manuspectrum_release.prom" && ok "scheduled refusal: metric" || not_ok "scheduled refusal: metric"
setup; sed -i '1s/^[0-9a-f]*/0000000000000000000000000000000000000000000000000000000000000000/' "$W/managed"; engine v1.1.0
check "interactive refusal: no mail, no notice call" test -z "$(ls "$W/mail")" && ! has 'site-notice'
setup; sched; sed -i 's/^TAG=v1.1.0/TAG=v1.2.0/' "$W/state/scheduled"; rm "$W/state/armed"; engine v1.1.0
check "a schedule for another tag is left alone" test -z "$(ls "$W/mail")" -a "$(sget scheduled OUTCOME)" = "" && ! has 'site-notice'
setup; sched; engine v1.1.0
{ [ "$RC" = 0 ] && has 'ARGS=end 7 --at now$' && [ ! -e "$W/state/scheduled" ]; } && ok "scheduled success: notice ended, scheduled removed" || not_ok "scheduled success" "$RC $(grep site-notice "$LOG")"
setup; sched; printf 500 >"$W/f/ready_2"; engine v1.1.0
{ [ "$RC" = 3 ] && has 'ARGS=end 7 --at now$' && [ ! -e "$W/state/scheduled" ]; } && ok "scheduled exit 3: notice ended, scheduled removed" || not_ok "scheduled exit 3" "$RC $(grep site-notice "$LOG")"
setup; sched; printf 500 >"$W/f/ready_2"; printf 500 >"$W/f/ready_1"; engine v1.1.0
{ [ "$RC" = 4 ] && has 'ARGS=end 7 --at \+24h$' && [ ! -e "$W/state/scheduled" ]; } && ok "scheduled exit 4: notice extended 24 h, scheduled removed" || not_ok "scheduled exit 4" "$RC $(grep site-notice "$LOG")"
setup; sched; touch "$W/f/notice_fail"; engine v1.1.0
{ [ "$RC" = 0 ] && has 'site-notice'; } && ok "a failing notice command does not change the exit code" || not_ok "failing notice command" "$RC $OUT"
setup; sched; touch "$W/f/notice_fail"; sed -i '1s/^[0-9a-f]*/0000000000000000000000000000000000000000000000000000000000000000/' "$W/managed"; engine v1.1.0
equals "a failing notice command does not change a refusal" 1 "$RC"

# --- readiness wait is capped
setup; sed -i 's/^RELEASE_READY_WAIT_SECONDS=.*/RELEASE_READY_WAIT_SECONDS=1801/' "$ENVF"; refusal_case "wait above the maximum" env_keys "1800"
setup; sed -i 's/^RELEASE_READY_WAIT_SECONDS=.*/RELEASE_READY_WAIT_SECONDS=1800/' "$ENVF"; engine --check-only v1.1.0
equals "wait at the maximum is accepted" 0 "$RC"

# --- Ansible marker
setup; touch "$W/ansible-running"; refusal_case "Ansible is running" busy "Ansible is running on this host"
setup; sched; touch "$W/ansible-running"; engine v1.1.0
equals "scheduled slot while Ansible runs: recorded as busy" busy "$(sget scheduled REASON)"

# --- the window of a scheduled slot
setup; sched; RNOW=1790004801 engine v1.1.0
{ [ "$RC" = 1 ] && grep -q '^REASON=late$' <<<"$OUT"; } && ok "late at the start: REASON=late" || not_ok "late at the start" "$RC $OUT"
equals "late at the start: OUTCOME is missed, as --fire records it" missed "$(sget scheduled OUTCOME)"
equals "late at the start: REASON in the record" late "$(sget scheduled REASON)"
has 'ARGS=withdraw 7$' && ok "late at the start: notice withdrawn" || not_ok "late at the start: notice withdrawn"
has '^make (backup|up)' && not_ok "late at the start: no backup, no switch" || ok "late at the start: no backup, no switch"
grep -q '^Subject: \[ManuSpectrum\]\[Release\] scheduled update of v1.1.0 missed [(]past its window[)]$' <<<"$(mails)" && ok "late at the start: mail" || not_ok "late at the start: mail" "$(mails)"
setup; sched; touch "$W/f/backup_closes_window"; before; engine v1.1.0
{ [ "$RC" = 1 ] && grep -q '^REASON=late$' <<<"$OUT"; } && ok "late after the backup: REASON=late" || not_ok "late after the backup" "$RC $OUT"
has '^make backup' && ok "late after the backup: the backup did run" || not_ok "late after the backup: the backup did run"
has '^make up' && not_ok "late after the backup: no switch" || ok "late after the backup: no switch"
[ "$(sha256sum "$ENVF" | cut -d' ' -f1) $(head_of)" = "$ENV_BEFORE $HEAD_BEFORE" ] && ok "late after the backup: .env and HEAD untouched" || not_ok "late after the backup: .env and HEAD untouched"
check "late after the backup: no inflight" test ! -e "$W/state/inflight"
equals "late after the backup: OUTCOME is missed" missed "$(sget scheduled OUTCOME)"
setup; touch "$W/f/backup_closes_window"; engine v1.1.0
equals "an interactive run has no window" 0 "$RC"

# --- a scheduled refusal on the lock
setup; sched; ( exec 7>"$W/state/lock"; flock 7; sleep 3 ) & holder=$!; sleep 0.3
engine v1.1.0; wait "$holder" 2>/dev/null
{ [ "$RC" = 1 ] && grep -q '^REASON=lock$' <<<"$OUT"; } && ok "scheduled, lock held: REASON=lock" || not_ok "scheduled, lock held" "$RC $OUT"
equals "scheduled, lock held: OUTCOME recorded" refused "$(sget scheduled OUTCOME)"
equals "scheduled, lock held: REASON recorded" lock "$(sget scheduled REASON)"
has 'ARGS=withdraw 7$' && ok "scheduled, lock held: notice withdrawn" || not_ok "scheduled, lock held: notice withdrawn"

# --- signature services unreachable
setup; touch "$W/f/probe_down_sigstore"; refusal_case "sigstore unreachable" fetch "signature services"
has '^verify' && not_ok "sigstore unreachable: release-verify not run" || ok "sigstore unreachable: release-verify not run"
grep -q '^manuspectrum_release_verification_failed 0$' "$W/metrics/manuspectrum_release.prom" && ok "sigstore unreachable: not a verification failure" || not_ok "sigstore unreachable: not a verification failure"
setup; engine v1.1.0
grep -q '^curl .*https://tuf-repo-cdn.sigstore.dev/' "$LOG" && ok "the sigstore probe asks tuf-repo-cdn" || not_ok "the sigstore probe asks tuf-repo-cdn" "$(cat "$LOG")"

# --- fetch: a moved tag is refused, a stray local tag is pruned
setup; git clone -q --bare "$ORIGIN" "$W/o2.git"; git -C "$W/o2.git" -c user.name=t -c user.email=t@manuspectrum.test tag -f -a -m moved v1.1.0 "$C1" >/dev/null
git -C "$W/app" remote set-url origin "$W/o2.git"; refusal_case "origin moved the armed tag" fetch "clobber"
equals "origin moved the armed tag: the local tag is kept" "$C2" "$(git -C "$W/app" rev-parse "v1.1.0^{commit}")"
setup; "${GIT[@]}" -C "$W/app" tag stray-tag; engine --check-only v1.1.0
equals "fetch prunes a local tag the origin does not have" "" "$(git -C "$W/app" tag -l stray-tag)"
equals "fetch prune: the check still passes" 0 "$RC"

# --- images left over after a success
setup; printf '%s\n' "$REPO $D1" "$REPO $D2" "$REPO sha256:$(printf '3%.0s' {1..64})" "docker.io/library/nginx sha256:$(printf '4%.0s' {1..64})" >"$W/f/images"; engine v1.1.0
equals "images: a stale image of the repository is removed" 1 "$(grep -c "^docker image rm $REPO@sha256:$(printf '3%.0s' {1..64})$" "$LOG")"
equals "images: exactly one removal" 1 "$(grep -c '^docker image rm ' "$LOG")"
grep -q "docker image rm $REPO@$D1\|docker image rm $REPO@$D2\|nginx" "$LOG" && not_ok "images: current, previous and other repositories are kept" || ok "images: current, previous and other repositories are kept"
grep -q "^docker image ls .*$REPO\$" "$LOG" && ok "images: only the repository is listed" || not_ok "images: only the repository is listed" "$(grep 'image ls' "$LOG")"
setup; mkdir "$W/state/previous"; printf '%s\n' "$REPO $D1" "$REPO $D2" "$REPO sha256:$(printf '3%.0s' {1..64})" >"$W/f/images"; engine v1.1.0
equals "images: the old current is kept although previous could not be written" 0 "$(grep -c "^docker image rm $REPO@$D1$" "$LOG")"
equals "images: the new current is kept" 0 "$(grep -c "^docker image rm $REPO@$D2$" "$LOG")"
equals "images: a stale image is still removed then" 1 "$(grep -c "^docker image rm $REPO@sha256:$(printf '3%.0s' {1..64})$" "$LOG")"
setup; printf '%s\n' "$REPO sha256:$(printf '3%.0s' {1..64})" >"$W/f/images"; printf 500 >"$W/f/ready_2"; engine v1.1.0
has '^docker image rm ' && not_ok "images: nothing removed after a rollback" || ok "images: nothing removed after a rollback"

# --- --after-stop: an engine that ended without finishing
INV="$(printf 'ab%.0s' {1..16})"
FOREIGN_INV="$(printf 'cd%.0s' {1..16})"
after_stop() { # after_stop RESULT STATUS [TAG]: EC = EXIT_CODE of the unit, INVX = its invocation id
  SERVICE_RESULT="$1" EXIT_STATUS="$2" EXIT_CODE="${EC-exited}" INVOCATION_ID="${INVX-$INV}" engine --after-stop "${3:-v1.1.0}"
  unset SERVICE_RESULT EXIT_STATUS
}
setup; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1790001000 INVOCATION_ID="$INV"; snapshot; s0="$SNAP"
after_stop timeout TERM
equals "after-stop timeout: exit 0" 0 "$RC"
equals "after-stop timeout: ROLLBACK_FAILED=1" 1 "$(sget rollbacks ROLLBACK_FAILED)"
check "after-stop timeout: inflight kept" test -e "$W/state/inflight"
grep -q '^Subject: \[ManuSpectrum\]\[Release\] update of v1.1.0 interrupted$' <<<"$(mails)" && ok "after-stop timeout: mail" || not_ok "after-stop timeout: mail" "$(mails)"
grep -qF 'make -C deploy restore RESTIC_SNAPSHOT=<id> CONFIRM=yes ERASURES_CHECKED=yes' <<<"$(mails)" && ok "after-stop timeout: mail names the restore commands" || not_ok "after-stop timeout: restore commands"
grep -q '^manuspectrum_release_rollback_failed 1$' "$W/metrics/manuspectrum_release.prom" && grep -q '^manuspectrum_release_inflight_since_timestamp_seconds 1790001000$' "$W/metrics/manuspectrum_release.prom" && ok "after-stop timeout: metrics" || not_ok "after-stop timeout: metrics" "$(cat "$W/metrics/manuspectrum_release.prom" 2>&1)"
grep -qP '\tinterrupted\tv1.0.0\tv1.1.0$' "$W/state/history.log" && ok "after-stop timeout: history line" || not_ok "after-stop timeout: history line"
has '^make |^docker compose' && not_ok "after-stop timeout: the stack is not touched" || ok "after-stop timeout: the stack is not touched"
for case_ in "success 0" "exit-code 1" "exit-code 3"; do
  read -r res code <<<"$case_"
  setup; rm -f "$W/state/inflight"; after_stop "$res" "$code"
  { [ "$RC" = 0 ] && [ -z "$(ls "$W/mail")" ] && [ -z "$(sget rollbacks ROLLBACK_FAILED)" ]; } && ok "after-stop $res/$code without inflight: nothing happens" || not_ok "after-stop $res/$code without inflight" "$RC $OUT"
done
setup; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1790001000 INVOCATION_ID="$INV"; release_state_w rollbacks COUNT=0 ROLLBACK_FAILED=1; after_stop exit-code 4
{ [ "$RC" = 0 ] && [ -z "$(ls "$W/mail")" ]; } && ok "after-stop exit 4: already mailed, not mailed twice" || not_ok "after-stop exit 4" "$RC $(mails)"
setup; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1790001000 INVOCATION_ID="$INV"; after_stop success 0
{ [ "$RC" = 0 ] && [ -z "$(ls "$W/mail")" ]; } && ok "after-stop success with a stale inflight: left alone" || not_ok "after-stop success" "$RC $(mails)"
setup; sched; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1790001000 INVOCATION_ID="$INV"; after_stop timeout TERM
has 'ARGS=end 7 --at \+24h$' && [ ! -e "$W/state/scheduled" ] && ok "after-stop scheduled: notice extended 24 h, scheduled removed" || not_ok "after-stop scheduled" "$(grep site-notice "$LOG")"
setup; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1790001000 INVOCATION_ID="$INV"; after_stop timeout TERM v1.2
{ [ "$RC" = 0 ] && [ -z "$(ls "$W/mail")" ]; } && ok "after-stop with a bad tag: ignored" || not_ok "after-stop with a bad tag"

# an inflight that another invocation wrote is not this unit's to flag
setup; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1790001000 INVOCATION_ID="$FOREIGN_INV"; after_stop exit-code 1
{ [ "$RC" = 0 ] && [ -z "$(ls "$W/mail")" ] && [ -z "$(sget rollbacks ROLLBACK_FAILED)" ] && [ -e "$W/state/inflight" ]; } && ok "after-stop exit 1 with a foreign inflight: nothing flagged, nothing mailed" || not_ok "after-stop exit 1 with a foreign inflight" "$RC $(mails)"
setup; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1790001000 INVOCATION_ID="$FOREIGN_INV"; after_stop timeout TERM
{ [ -z "$(ls "$W/mail")" ] && [ -z "$(sget rollbacks ROLLBACK_FAILED)" ]; } && ok "after-stop timeout with a foreign inflight: nothing flagged" || not_ok "after-stop timeout with a foreign inflight" "$(mails)"
setup; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1790001000 INVOCATION_ID=; after_stop timeout TERM
{ [ -z "$(ls "$W/mail")" ] && [ -z "$(sget rollbacks ROLLBACK_FAILED)" ]; } && ok "after-stop with an inflight that carries no invocation id: nothing flagged" || not_ok "after-stop inflight without id" "$(mails)"
# the engine's own exit 4 is never mailed twice, whatever SERVICE_RESULT says
for exit_status in 0 3 4; do
  setup; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1790001000 INVOCATION_ID="$INV"; after_stop timeout "$exit_status"
  { [ -z "$(ls "$W/mail")" ] && [ -z "$(sget rollbacks ROLLBACK_FAILED)" ]; } && ok "after-stop timeout/$exit_status with exited code: engine already ended, nothing flagged" || not_ok "after-stop timeout/$exit_status" "$(mails)"
done
setup; release_state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1790001000 INVOCATION_ID="$INV"; EC=killed after_stop signal TERM
{ [ "$(sget rollbacks ROLLBACK_FAILED)" = 1 ] && grep -q 'interrupted' <<<"$(mails)"; } && ok "after-stop killed with the matching invocation id: flagged and mailed" || not_ok "after-stop killed" "$(mails)"

# the inflight records the invocation that wrote it
setup; printf 500 >"$W/f/ready_2"; printf 500 >"$W/f/ready_1"; INVOCATION_ID="$INV" engine v1.1.0
equals "inflight carries the INVOCATION_ID of the unit" "$INV" "$(sget inflight INVOCATION_ID)"
setup; printf 500 >"$W/f/ready_2"; printf 500 >"$W/f/ready_1"; INVOCATION_ID=not-an-id engine v1.1.0
equals "an invalid INVOCATION_ID is recorded empty" "" "$(sget inflight INVOCATION_ID)"
equals "an invalid INVOCATION_ID does not stop the update" 4 "$RC"

echo "1..$N"
[ "$FAILED" -eq 0 ] || { echo "# FAILED"; exit 1; }
