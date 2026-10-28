#!/usr/bin/env bash
# deploy/scripts/tests/test_release_watch.sh
# Tests of release-watch.sh on throwaway git repositories (a bare origin with
# annotated tags and a clone as the checkout) with fake `docker`, `curl`, `make`
# and sendmail on PATH, and fake release-verify.sh / image-digest.sh in the
# library directory (the real lib-release.sh and release-managed.sh). Prints
# `ok N` / `not ok N`; exits non-zero on failure.
# shellcheck disable=SC2319,SC2015,SC2001,SC2030,SC2031,SC2016,SC2034,SC2012
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$HERE/.."
WATCH="${RELEASE_WATCH_UNDER_TEST:-$SCRIPTS/release-watch.sh}"
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

if [ ! -f "$WATCH" ]; then
  not_ok "release-watch.sh exists" "$WATCH is missing"
  echo "1..$N"
  exit 1
fi

GIT=(git -c user.name=t -c user.email=t@manuspectrum.test -c commit.gpgsign=false -c tag.gpgsign=false)
D1="sha256:$(printf '1%.0s' {1..64})"
D2="sha256:$(printf '2%.0s' {1..64})"
D3="sha256:$(printf '3%.0s' {1..64})"
REPO=ghcr.io/crc-centre-recherche-conservation/manuspectrum
OLD="2020-01-01T00:00:00Z"

# --- the origin: v1.0.0 and v1.1.0 tagged long ago; v1.2.0 (Security-Fix
# trailer, front changed) and v1.3.0-rc.1 tagged now
SRC="$TMP/src"
ORIGIN="$TMP/origin.git"
git init -q "$SRC" && git init -q --bare -b main "$ORIGIN"
(
  cd "$SRC" || exit 1
  mkdir -p deploy/compose deploy/sbin
  printf 'deploy/compose/.env\n' >.gitignore
  printf 'A_KEY=1\nRELEASE_CHANNEL=prod\n' >deploy/compose/.env.example
  printf 'front v1\n' >deploy/sbin/front
  "${GIT[@]}" add -A && "${GIT[@]}" commit -qm one && GIT_COMMITTER_DATE=$OLD "${GIT[@]}" tag -a -m v1.0.0 v1.0.0
  printf 'A_KEY=1\nRELEASE_CHANNEL=prod\nNEW_KEY=2\n' >deploy/compose/.env.example
  printf 'front v2\n' >deploy/sbin/front
  "${GIT[@]}" add -A && "${GIT[@]}" commit -qm two && GIT_COMMITTER_DATE=$OLD "${GIT[@]}" tag -a -m v1.1.0 v1.1.0
  printf 'front v3\n' >deploy/sbin/front
  "${GIT[@]}" add -A && "${GIT[@]}" commit -qm three
  "${GIT[@]}" tag -a -m "Release 1.2.0" -m "Fixes the export of spectra." -m "Security-Fix: yes" v1.2.0
  printf 'front v4\n' >deploy/sbin/front
  "${GIT[@]}" add -A && "${GIT[@]}" commit -qm four
  "${GIT[@]}" tag -a -m "Release 1.3.0-rc.1" -m "Second candidate." v1.3.0-rc.1
  git push -q "$ORIGIN" HEAD:refs/heads/main --tags
)
C1="$(git -C "$SRC" rev-parse "v1.0.0^{commit}")"
C11="$(git -C "$SRC" rev-parse "v1.1.0^{commit}")"
C12="$(git -C "$SRC" rev-parse "v1.2.0^{commit}")"
C13="$(git -C "$SRC" rev-parse "v1.3.0-rc.1^{commit}")"

# --- fakes
FAKE="$TMP/fake"
mkdir -p "$FAKE/bin" "$FAKE/lib"
cat >"$FAKE/bin/docker" <<'SH'
#!/bin/bash
echo "docker $*" >>"$FAKE_LOG"
[ ! -e "$FAKE_DIR/rm_fail" ] || { [ "$1 $2" != "image rm" ] || exit 1; }
exit 0
SH
cat >"$FAKE/bin/curl" <<'SH'
#!/bin/bash
echo "curl $*" >>"$FAKE_LOG"
url="${*: -1}"
case "$url" in
  *github.com*) name=git; ok=200 ;;
  *ghcr.io*) name=registry; ok=401 ;;
  *sigstore*) name=sigstore; ok=200 ;;
esac
if [ -e "$FAKE_DIR/probe_down_$name" ]; then echo "curl: (28) timed out" >&2; exit 28; fi
if [ -e "$FAKE_DIR/probe_wrong_$name" ]; then printf 200; exit 0; fi
printf '%s' "$ok"
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
echo "make $target :: $*" >>"$FAKE_LOG"
[ ! -e "$FAKE_DIR/notice_fail" ] || exit 1
exit 0
SH
cat >"$FAKE/bin/sendmail" <<'SH'
#!/bin/bash
[ ! -e "$FAKE_DIR/mail_fail" ] || { cat >/dev/null; exit 1; }
n=$(ls "$FAKE_MAIL" | wc -l)
cat >"$FAKE_MAIL/$((n + 1)).eml"
SH
cat >"$FAKE/lib/release-verify.sh" <<'SH'
#!/bin/bash
echo "verify cwd=$PWD :: $*" >>"$FAKE_LOG"
if [ -e "$FAKE_DIR/pull_fail" ]; then echo "release-verify: cannot pull $3" >&2; exit 1; fi
if [ -e "$FAKE_DIR/verify_fail" ]; then echo "release-verify: signature check failed" >&2; exit 1; fi
echo "${@: -3:1}"
SH
cat >"$FAKE/lib/image-digest.sh" <<'SH'
#!/bin/bash
echo "image-digest $*" >>"$FAKE_LOG"
tag="${1##*:}"
[ ! -e "$FAKE_DIR/nodigest_$tag" ] || { echo "image-digest.sh: cannot read the manifest of $1" >&2; exit 1; }
if [ -e "$FAKE_DIR/digest_$tag" ]; then cat "$FAKE_DIR/digest_$tag"; else echo "$FAKE_D2"; fi
SH
chmod +x "$FAKE"/bin/* "$FAKE"/lib/*
cp "$SCRIPTS/lib-release.sh" "$SCRIPTS/lib-metrics.sh" "$SCRIPTS/release-managed.sh" "$FAKE/lib/" 2>/dev/null

# --- one scenario: W/{app,state,metrics,mail,f}. setup CHANNEL CURRENT TAG...
# keeps only the listed tags in the origin; HEAD of the checkout is CURRENT.
setup() {
  local channel="$1" cur="$2" t
  shift 2
  W="$TMP/w$N-$RANDOM"
  mkdir -p "$W/state" "$W/metrics" "$W/mail" "$W/f"; : >"$W/state/lock"
  git clone -q --bare "$ORIGIN" "$W/origin.git"
  while IFS= read -r t; do
    case " $* " in *" $t "*) ;; *) git -C "$W/origin.git" tag -d "$t" >/dev/null ;; esac
  done < <(git -C "$W/origin.git" tag -l)
  git clone -q "$W/origin.git" "$W/app" && git -C "$W/app" checkout -q --detach "$cur"
  cat >"$W/app/deploy/compose/.env" <<EOF2
MANUSPECTRUM_IMAGE=$REPO@$D1
RELEASE_CHANNEL=$channel
A_KEY=1
NEW_KEY=2
PUBLIC_HOST=manuspectrum.test
ALERT_EMAILS=ops@manuspectrum.test
ALERT_EMAIL_FROM=noreply@manuspectrum.test
METRICS_TEXTFILE_DIR=$W/metrics
EOF2
  ENVF="$W/app/deploy/compose/.env"
  state_w current "TAG=$cur" "IMAGE=$REPO@$D1" "COMMIT=$(git -C "$W/app" rev-parse HEAD)" "APPLIED_AT=1700000000"
  managed_from "${!#}"
  LOG="$W/f/log"
  : >"$LOG"
}
state_w() { local name="$1"; shift; printf '%s\n' "$@" >"$W/state/$name"; }
managed_from() { bash "$FAKE/lib/release-managed.sh" --ref "refs/tags/$1" --repo "$W/app" >"$W/managed"; }
NOW="$(date +%s)"
arm() { # arm TAG COMMIT DIGEST NOTIFIED [SECURITY] [SINCE]
  state_w armed "TAG=$1" "IMAGE=$REPO@$3" "COMMIT=$2" ARMED_AT=$((NOW - 5000)) "SECURITY=${5:-0}" "NOTIFIED=$4" NEEDS_ANSIBLE=0
  state_w pending "SINCE=${6:-$((NOW - 5000))}" "SECURITY=${5:-0}"
}

watch() { # watch: runs the watch from an unrelated directory; sets RC, OUT
  OUT="$(cd "$TMP" && env -i PATH="$FAKE/bin:$PATH" HOME="$TMP" \
    APP_DIR="$W/app" STATE_DIR="$W/state" ENV_FILE="$ENVF" MANAGED_SOURCES="$W/managed" RELEASE_LIB_DIR="$FAKE/lib" \
    RELEASE_SENDMAIL="$FAKE/bin/sendmail" \
    FAKE_LOG="$LOG" FAKE_DIR="$W/f" FAKE_MAIL="$W/mail" FAKE_D2="$D2" ANSIBLE_MARKER="$W/ansible-running" \
    bash "$WATCH" 2>&1)"
  RC=$?
}

sget() { sed -n "s/^$2=//p" "$W/state/$1" 2>/dev/null; }
logline() { grep -n -m1 -- "$1" "$LOG" | cut -d: -f1; }
has() { grep -qE -- "$1" "$LOG"; }
mails() { cat "$W"/mail/*.eml 2>/dev/null; }
nmails() { ls "$W/mail" | wc -l; }
subjects() { grep -h '^Subject:' "$W"/mail/*.eml 2>/dev/null; }
prom() { echo "$W/metrics/manuspectrum_release.prom"; }
metric() { grep -qF -- "manuspectrum_release_$1" "$(prom)"; }
head_of() { git -C "$W/app" rev-parse HEAD; }
fingerprint() { echo "$(head_of) $(git -C "$W/app" status --porcelain | sha256sum) $(sha256sum <"$ENVF")"; }
state_hash() { cat "$W"/state/* 2>/dev/null | sha256sum; }

# --- the lock
setup rc v1.0.0 v1.0.0 v1.1.0
flock "$W/state/lock" sleep 6 & holder=$!
for _ in $(seq 1 50); do flock -n "$W/state/lock" true 2>/dev/null || break; sleep 0.1; done
watch
equals "lock held: exit 0" 0 "$RC"
grep -q 'update running' <<<"$OUT" && ok "lock held: says so" || not_ok "lock held: says so" "$OUT"
check "lock held: metrics untouched, nothing probed" test ! -e "$(prom)" -a ! -s "$LOG"
kill "$holder" 2>/dev/null; wait "$holder" 2>/dev/null

# --- Ansible is running: nothing is probed or armed
setup rc v1.1.0 v1.1.0 v1.2.0
touch "$W/ansible-running"
watch
equals "Ansible running: exit 0" 0 "$RC"
grep -q 'Ansible is running' <<<"$OUT" && ok "Ansible running: says so" || not_ok "Ansible running: says so" "$OUT"
check "Ansible running: nothing armed, nothing probed, no mail" test ! -e "$W/state/armed" -a ! -s "$LOG" -a "$(nmails)" = 0
grep -qE "watch_last_run_timestamp_seconds [0-9]{10}$" "$(prom)" && ok "Ansible running: metrics refreshed" || not_ok "Ansible running: metrics refreshed"
rm "$W/ansible-running"; watch
equals "Ansible done: the release is armed" v1.2.0 "$(sget armed TAG)"

# --- a marker older than 2 h means an Ansible run was interrupted
setup rc v1.1.0 v1.1.0 v1.2.0
touch -d '3 hours ago' "$W/ansible-running"
watch
equals "stale Ansible marker: exit 1" 1 "$RC"
grep -qF 'Ansible marker older than 2 h: a run was interrupted; remove it if no playbook is running' <<<"$OUT" && ok "stale Ansible marker: says so" || not_ok "stale Ansible marker: says so" "$OUT"
check "stale Ansible marker: nothing armed, nothing probed, no mail" test ! -e "$W/state/armed" -a ! -s "$LOG" -a "$(nmails)" = 0
grep -q '^manuspectrum_release_watch_failed{step="state"} 1$' "$(prom)" && ok "stale Ansible marker: the state failure is exported" || not_ok "stale Ansible marker: failure metric" "$(cat "$(prom)")"
touch -d '1 hour 50 minutes ago' "$W/ansible-running"; watch
equals "young Ansible marker: still a quiet exit 0" 0 "$RC"
grep -q '^manuspectrum_release_watch_failed{step="state"} 0$' "$(prom)" && ok "young Ansible marker: no failure exported" || not_ok "young Ansible marker: no failure" "$(cat "$(prom)")"

# --- fetch: a stray local tag is pruned, a moved tag is not taken
setup rc v1.1.0 v1.1.0 v1.2.0
"${GIT[@]}" -C "$W/app" tag stray-tag
watch
equals "fetch prunes a local tag the origin lacks" "" "$(git -C "$W/app" tag -l stray-tag)"
setup rc v1.1.0 v1.1.0 v1.2.0
git -C "$W/origin.git" -c user.name=t -c user.email=t@manuspectrum.test tag -f -a -m moved v1.1.0 "$C1" >/dev/null
watch
equals "a tag moved on the origin: exit 1, step git" "1" "$RC"
metric 'watch_failed{step="git"} 1' && ok "a tag moved on the origin: step git" || not_ok "a tag moved on the origin: step git" "$(cat "$(prom)")"
equals "a tag moved on the origin: the local tag is kept" "$C11" "$(git -C "$W/app" rev-parse "v1.1.0^{commit}")"

# --- nothing new
setup rc v1.0.0 v1.0.0
watch
equals "no newer release: exit 0" 0 "$RC"
check "no newer release: no armed, no pending, no mail" test ! -e "$W/state/armed" -a ! -e "$W/state/pending" -a "$(nmails)" = 0
metric 'armed 0' && metric 'verification_failed 0' && ok "no newer release: metrics written, not armed" || not_ok "no newer release: metrics" "$(cat "$(prom)" 2>&1)"
grep -qE "watch_last_run_timestamp_seconds [0-9]{10}$" "$(prom)" && ok "no newer release: watch_last_run is set" || not_ok "no newer release: watch_last_run"
has '^image-digest|^verify' && not_ok "no newer release: no digest, no verification" || ok "no newer release: no digest, no verification"
setup prod v1.2.0 v1.2.0 v1.3.0-rc.1
watch
check "prod channel ignores a release candidate" test "$RC" = 0 -a ! -e "$W/state/armed" -a "$(nmails)" = 0
setup prod v1.1.0 v1.1.0 v1.2.0 v1.3.0-rc.1
watch
equals "prod channel arms the final tag, not the newer rc" v1.2.0 "$(sget armed TAG)"

# --- arming: the whole chain
setup rc v1.1.0 v1.1.0 v1.2.0
fp0="$(fingerprint)"
watch
equals "arming: exit 0" 0 "$RC"
[ "$RC" = 0 ] || echo "$OUT" | sed 's/^/#   /'
equals "arming: armed TAG" v1.2.0 "$(sget armed TAG)"
equals "arming: armed IMAGE is the repository at the registry digest" "$REPO@$D2" "$(sget armed IMAGE)"
equals "arming: armed COMMIT" "$C12" "$(sget armed COMMIT)"
equals "arming: Security-Fix trailer read" 1 "$(sget armed SECURITY)"
equals "arming: NOTIFIED after the mail" 1 "$(sget armed NOTIFIED)"
equals "arming: NEEDS_ANSIBLE" 0 "$(sget armed NEEDS_ANSIBLE)"
[ "$(sget armed ARMED_AT)" -ge "$NOW" ] && ok "arming: ARMED_AT" || not_ok "arming: ARMED_AT"
equals "arming: pending SINCE is the arming time" "$(sget armed ARMED_AT)" "$(sget pending SINCE)"
equals "arming: pending SECURITY" 1 "$(sget pending SECURITY)"
equals "arming: HEAD, worktree and .env untouched" "$fp0" "$(fingerprint)"
d="$(logline '^image-digest')"; v="$(logline '^verify')"
{ [ -n "$d" ] && [ -n "$v" ] && [ "$d" -lt "$v" ]; } && ok "arming: digest read, then verification" || not_ok "arming: order" "$(cat "$LOG")"
grep -q "^image-digest $REPO:v1.2.0$" "$LOG" && ok "arming: digest of the tag in the channel's repository" || not_ok "arming: digest ref" "$(grep image-digest "$LOG")"
grep -q "^verify cwd=$W/app :: --policy rc $REPO@$D2 v1.2.0 --commit $C12 --repo-dir $W/app$" "$LOG" && ok "arming: release-verify from APP_DIR, channel policy, --commit, --repo-dir" || not_ok "arming: verify arguments" "$(grep '^verify' "$LOG")"
has '^docker (pull|run)' && not_ok "arming: the watch never pulls itself" || ok "arming: the watch never pulls itself"
for u in 'https://github.com/' 'https://ghcr.io/v2/' 'https://tuf-repo-cdn.sigstore.dev/'; do
  grep -qF "curl -sS -m 15 -o /dev/null -w %{http_code} $u" "$LOG" && ok "arming: probe $u" || not_ok "arming: probe $u" "$(grep '^curl' "$LOG")"
done
equals "arming: one mail" 1 "$(nmails)"
m="$(mails)"
grep -q "^Subject: \[ManuSpectrum\]\[Release\] v1.2.0 ready to install on manuspectrum.test (security fix)$" <<<"$m" && ok "arming: subject" || not_ok "arming: subject" "$m"
grep -q '^X-ManuSpectrum-Category: Release$' <<<"$m" && ok "arming: category header" || not_ok "arming: category header"
for want in 'Version: v1.2.0' 'Channel: rc' "Image digest: $D2" "Commit: $C12" 'https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum/releases/tag/v1.2.0' 'Fixes the export of spectra.' 'ssh -t <your account>@manuspectrum.test sudo manuspectrum-update --now v1.2.0' 'ssh -t <your account>@manuspectrum.test sudo manuspectrum-update --at "YYYY-MM-DD HH:MM" v1.2.0'; do
  grep -qF -- "$want" <<<"$m" && ok "arming: mail has '$want'" || not_ok "arming: mail has '$want'" "$m"
done
dl="$(date -u -d "@$(( $(sget pending SINCE) + 14 * 86400 ))" +%Y-%m-%d)"
grep -qF "Install by: $dl (14 days" <<<"$m" && ok "arming: security deadline is 14 days" || not_ok "arming: deadline" "$m"
grep -qi 're-run ansible first' <<<"$m" && not_ok "arming: no Ansible hint when compatible" || ok "arming: no Ansible hint when compatible"
metric 'armed 1' && metric 'pending_security 1' && metric 'verification_failed 0' && ok "arming: metrics" || not_ok "arming: metrics" "$(cat "$(prom)")"
for s in git registry sigstore pull mail state; do metric "watch_failed{step=\"$s\"} 0" || not_ok "arming: watch_failed $s is 0"; done
a0="$(sget armed ARMED_AT)"; : >"$LOG"
watch
equals "second run: exit 0" 0 "$RC"
{ equals "second run: still one mail" 1 "$(nmails)"; equals "second run: armed untouched" "$a0" "$(sget armed ARMED_AT)"; }
has '^verify' && not_ok "second run: no second verification" || ok "second run: no second verification"
has '^image-digest' && ok "second run: the digest is compared" || not_ok "second run: the digest is compared"

# --- a final tag without trailer, a rc channel picks the rc
setup rc v1.2.0 v1.2.0 v1.3.0-rc.1
watch
equals "rc channel arms the release candidate" v1.3.0-rc.1 "$(sget armed TAG)"
equals "no trailer: SECURITY 0" 0 "$(sget armed SECURITY)"
grep -q 'ready to install on manuspectrum.test$' <<<"$(subjects)" && ok "no trailer: plain subject" || not_ok "no trailer: plain subject" "$(subjects)"
grep -qF 'Install by:' <<<"$(mails)" && grep -q "14 days" <<<"$(mails)" && not_ok "no trailer: 30 day deadline" || ok "no trailer: 30 day deadline"

# --- a newer release: SINCE kept, SECURITY sticky, the older armed image dropped
setup rc v1.1.0 v1.1.0 v1.2.0 v1.3.0-rc.1
arm v1.2.0 "$C12" "$D2" 1 1 $((NOW - 90000))
printf '%s\n' "$D3" >"$W/f/digest_v1.3.0-rc.1"
watch
equals "newer release: armed replaced" v1.3.0-rc.1 "$(sget armed TAG)"
equals "newer release: armed digest" "$REPO@$D3" "$(sget armed IMAGE)"
equals "newer release: SINCE is the oldest unapplied arming" $((NOW - 90000)) "$(sget pending SINCE)"
equals "newer release: pending SECURITY is sticky" 1 "$(sget pending SECURITY)"
equals "newer release: armed SECURITY is its own" 0 "$(sget armed SECURITY)"
has "^docker image rm $REPO@$D2\$" && ok "newer release: the older armed image is removed" || not_ok "newer release: older image removed" "$(cat "$LOG")"
equals "newer release: mailed" 1 "$(nmails)"
grep -qF "Install by: $(date -u -d "@$((NOW - 90000 + 14 * 86400))" +%Y-%m-%d) (14 days" <<<"$(mails)" && ok "newer release: deadline from the oldest, security" || not_ok "newer release: deadline" "$(mails)"
setup rc v1.1.0 v1.1.0 v1.2.0 v1.3.0-rc.1
arm v1.2.0 "$C12" "$D2" 1; state_w previous "TAG=v1.0.0" "IMAGE=$REPO@$D2" "COMMIT=$C1"
printf '%s\n' "$D3" >"$W/f/digest_v1.3.0-rc.1"
watch
has 'docker image rm' && not_ok "the older armed image is kept when it is the previous one" || ok "the older armed image is kept when it is the previous one"
setup rc v1.1.0 v1.1.0 v1.2.0 v1.3.0-rc.1
arm v1.2.0 "$C12" "$D1" 1
printf '%s\n' "$D3" >"$W/f/digest_v1.3.0-rc.1"
watch
has 'docker image rm' && not_ok "the older armed image is kept when it is the current one" || ok "the older armed image is kept when it is the current one"
setup rc v1.1.0 v1.1.0 v1.2.0 v1.3.0-rc.1
arm v1.2.0 "$C12" "$D2" 1; touch "$W/f/rm_fail"; printf '%s\n' "$D3" >"$W/f/digest_v1.3.0-rc.1"
watch
equals "a failing image removal is only logged" "0 v1.3.0-rc.1" "$RC $(sget armed TAG)"

# --- armed already, digest unchanged: quiet; the mail still owed is retried
setup rc v1.1.0 v1.1.0 v1.2.0
arm v1.2.0 "$C12" "$D2" 1
s0="$(state_hash)"
watch
equals "armed and unchanged: exit 0" 0 "$RC"
equals "armed and unchanged: state untouched" "$s0" "$(state_hash)"
check "armed and unchanged: no verification, no mail" test "$(nmails)" = 0 && ! has '^verify'
metric 'armed 1' && ok "armed and unchanged: metrics refreshed" || not_ok "armed and unchanged: metrics"
# the armed release was not re-verified: a failure recorded earlier stays
setup rc v1.1.0 v1.1.0 v1.2.0
arm v1.2.0 "$C12" "$D2" 1
bash -c ". '$FAKE/lib/lib-release.sh'; release_metrics_write '$(prom)' verification_failed=1"
watch
grep -qx 'manuspectrum_release_verification_failed 1' "$(prom)" && ok "armed and unchanged: verification_failed is not cleared" || not_ok "armed and unchanged: verification_failed is not cleared" "$(cat "$(prom)")"
# NEEDS_ANSIBLE follows the host: rewritten when it changed, no new mail
setup rc v1.1.0 v1.1.0 v1.2.0
arm v1.2.0 "$C12" "$D2" 1
sed -i 's/NEEDS_ANSIBLE=0/NEEDS_ANSIBLE=1/' "$W/state/armed"
watch
equals "armed and unchanged: NEEDS_ANSIBLE cleared once the host is compatible" 0 "$(sget armed NEEDS_ANSIBLE)"
equals "armed and unchanged: no mail for it" 0 "$(nmails)"
setup rc v1.1.0 v1.1.0 v1.2.0
arm v1.2.0 "$C12" "$D2" 1
sed -i '/^NEW_KEY=/d' "$ENVF"
watch
equals "armed and unchanged: NEEDS_ANSIBLE set when the host lacks a key" 1 "$(sget armed NEEDS_ANSIBLE)"
equals "armed and unchanged: the other armed keys are kept" "v1.2.0 1" "$(sget armed TAG) $(sget armed NOTIFIED)"
setup rc v1.1.0 v1.1.0 v1.2.0
touch "$W/f/mail_fail"
watch
equals "mail failure: exit 1" 1 "$RC"
equals "mail failure: armed is written, NOTIFIED 0" "v1.2.0 0" "$(sget armed TAG) $(sget armed NOTIFIED)"
metric 'watch_failed{step="mail"} 1' && ok "mail failure: step mail" || not_ok "mail failure: step mail" "$(cat "$(prom)")"
rm "$W/f/mail_fail"; : >"$LOG"
watch
equals "mail retried: exit 0" 0 "$RC"
equals "mail retried: NOTIFIED 1, one mail" "1 1" "$(sget armed NOTIFIED) $(nmails)"
has '^verify' && not_ok "mail retried: no second verification" || ok "mail retried: no second verification"
metric 'watch_failed{step="mail"} 0' && ok "mail retried: step cleared" || not_ok "mail retried: step cleared"

# --- the tag was republished under another digest: checked again and re-armed
setup rc v1.1.0 v1.1.0 v1.2.0
arm v1.2.0 "$C12" "$D2" 1
printf '%s\n' "$D3" >"$W/f/digest_v1.2.0"
watch
equals "changed digest: re-armed" "$REPO@$D3" "$(sget armed IMAGE)"
has '^verify' && ok "changed digest: verified again" || not_ok "changed digest: verified again"
equals "changed digest: mailed again" 1 "$(nmails)"

# --- probes
for step in git registry sigstore; do
  setup rc v1.1.0 v1.1.0 v1.2.0
  touch "$W/f/probe_down_$step"
  watch
  equals "probe $step down: exit 1" 1 "$RC"
  check "probe $step down: nothing checked or armed" test ! -e "$W/state/armed" -a "$(nmails)" = 0 && ! has '^image-digest|^verify'
  metric "watch_failed{step=\"$step\"} 1" && ok "probe $step down: step $step failed" || not_ok "probe $step down: metric" "$(cat "$(prom)" 2>&1)"
  others=0; for s in git registry sigstore; do if [ "$s" != "$step" ] && metric "watch_failed{step=\"$s\"} 1"; then others=1; fi; done
  [ "$others" = 0 ] && ok "probe $step down: only $step failed" || not_ok "probe $step down: other steps"
done
setup rc v1.1.0 v1.1.0 v1.2.0
touch "$W/f/probe_wrong_registry"
watch
equals "registry answering 200 instead of 401: exit 1" 1 "$RC"
metric 'watch_failed{step="registry"} 1' && ok "registry answering 200: step registry" || not_ok "registry answering 200: step registry"
setup rc v1.1.0 v1.1.0 v1.2.0
git -C "$W/app" remote set-url origin "$TMP/nowhere.git"
watch
equals "git fetch fails: exit 1" 1 "$RC"
metric 'watch_failed{step="git"} 1' && ok "git fetch fails: step git" || not_ok "git fetch fails: step git"
check "git fetch fails: nothing armed" test ! -e "$W/state/armed"

# --- still publishing (tag younger than 6 h) and verification failures (older)
setup rc v1.1.0 v1.1.0 v1.2.0
touch "$W/f/nodigest_v1.2.0"
watch
equals "image missing, fresh tag: exit 0" 0 "$RC"
grep -q 'still publishing' <<<"$OUT" && ok "image missing, fresh tag: still publishing" || not_ok "image missing, fresh tag: message" "$OUT"
check "image missing, fresh tag: nothing recorded" test ! -e "$W/state/armed" -a ! -e "$W/state/pending" -a "$(nmails)" = 0
metric 'verification_failed 0' && ok "image missing, fresh tag: no failure recorded" || not_ok "image missing, fresh tag: metric"
setup rc v1.1.0 v1.1.0 v1.2.0
touch "$W/f/verify_fail"
watch
equals "unsigned, fresh tag: exit 0" 0 "$RC"
grep -q 'still publishing' <<<"$OUT" && ok "unsigned, fresh tag: still publishing" || not_ok "unsigned, fresh tag: message" "$OUT"
check "unsigned, fresh tag: nothing recorded" test ! -e "$W/state/armed" -a "$(nmails)" = 0
setup rc v1.0.0 v1.0.0 v1.1.0
touch "$W/f/nodigest_v1.1.0"
watch
equals "image missing, old tag: exit 1" 1 "$RC"
metric 'verification_failed 1' && ok "image missing, old tag: verification_failed=1" || not_ok "image missing, old tag: metric" "$(cat "$(prom)")"
check "image missing, old tag: nothing armed, no mail" test ! -e "$W/state/armed" -a "$(nmails)" = 0
setup rc v1.0.0 v1.0.0 v1.1.0
touch "$W/f/verify_fail"
watch
equals "verification failed, old tag: exit 1" 1 "$RC"
metric 'verification_failed 1' && ok "verification failed, old tag: verification_failed=1" || not_ok "verification failed, old tag: metric"
check "verification failed, old tag: nothing armed" test ! -e "$W/state/armed" -a "$(nmails)" = 0
rm "$W/f/verify_fail"
watch
equals "verification recovers: armed" "0 v1.1.0" "$RC $(sget armed TAG)"
metric 'verification_failed 0' && ok "verification recovers: verification_failed back to 0" || not_ok "verification recovers: metric"
setup rc v1.0.0 v1.0.0 v1.1.0
touch "$W/f/pull_fail"
watch
equals "pull failure: exit 1" 1 "$RC"
metric 'watch_failed{step="pull"} 1' && metric 'verification_failed 0' && ok "pull failure: step pull, not a verification failure" || not_ok "pull failure: metrics" "$(cat "$(prom)")"
check "pull failure: nothing armed" test ! -e "$W/state/armed"

# --- compatibility: Ansible must run first
setup rc v1.1.0 v1.1.0 v1.2.0
managed_from v1.1.0
watch
equals "managed files differ: NEEDS_ANSIBLE" "0 1" "$RC $(sget armed NEEDS_ANSIBLE)"
grep -q 'Re-run Ansible first' <<<"$(mails)" && ok "managed files differ: the mail says to re-run Ansible" || not_ok "managed files differ: mail" "$(mails)"
setup rc v1.1.0 v1.1.0 v1.2.0
sed -i '/^NEW_KEY=/d' "$ENVF"
watch
equals "env key missing: NEEDS_ANSIBLE" 1 "$(sget armed NEEDS_ANSIBLE)"
setup rc v1.1.0 v1.1.0 v1.2.0
rm "$W/managed"
watch
equals "no managed-sources file: NEEDS_ANSIBLE" 1 "$(sget armed NEEDS_ANSIBLE)"
equals "NEEDS_ANSIBLE does not stop the arming" v1.2.0 "$(sget armed TAG)"

# --- a scheduled update is never replaced
sched() { # sched TAG AT_OFFSET [extra KEY=value...]
  local tag="$1" off="$2"
  shift 2
  state_w scheduled "TAG=$tag" "AT_EPOCH=$((NOW + off))" 'AT_PARIS=2027-01-05 23:00' "WINDOW_END_EPOCH=$((NOW + off + 1800))" NOTICE_ID=7 BY=op "CREATED_AT=$((NOW - 7000))" OUTCOME= REASON= HELD_TAG= NOTIFIED=0
  for kv in "$@"; do sed -i "/^${kv%%=*}=/d" "$W/state/scheduled"; printf '%s\n' "$kv" >>"$W/state/scheduled"; done
}
setup rc v1.0.0 v1.0.0 v1.1.0 v1.2.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 3600
a0="$(cat "$W/state/armed" "$W/state/pending" | sha256sum)"
watch
equals "scheduled: exit 0" 0 "$RC"
equals "scheduled: armed and pending untouched" "$a0" "$(cat "$W/state/armed" "$W/state/pending" | sha256sum)"
equals "scheduled: HELD_TAG" v1.2.0 "$(sget scheduled HELD_TAG)"
equals "scheduled: one mail" "[ManuSpectrum][Release] v1.2.0 available while v1.1.0 is scheduled" "$(subjects | sed 's/^Subject: //')"
has '^image-digest|^verify|docker image rm' && not_ok "scheduled: no digest, no verification, no image removal" || ok "scheduled: no digest, no verification, no image removal"
watch
equals "scheduled, second run: no second mail" 1 "$(nmails)"
metric "scheduled_timestamp_seconds $((NOW + 3600))" && ok "scheduled: metric scheduled_timestamp" || not_ok "scheduled: metric" "$(cat "$(prom)")"
setup rc v1.0.0 v1.0.0 v1.1.0 v1.2.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 3600; touch "$W/f/mail_fail"
watch
equals "scheduled, mail fails: HELD_TAG not recorded, step mail" "1 " "$RC $(sget scheduled HELD_TAG)"
rm "$W/f/mail_fail"; watch
equals "scheduled, mail retried" "v1.2.0 1" "$(sget scheduled HELD_TAG) $(nmails)"
setup rc v1.0.0 v1.0.0 v1.1.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 3600
watch
check "scheduled for the candidate itself: left alone, no mail" test "$RC" = 0 -a "$(nmails)" = 0 -a -z "$(sget scheduled HELD_TAG)" && ! has '^verify'
setup rc v1.0.0 v1.0.0 v1.1.0 v1.2.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 -3600 'OUTCOME=refused' 'REASON=drift'
watch
equals "a refused schedule no longer holds: the newer release is armed" v1.2.0 "$(sget armed TAG)"

# --- a missed slot
history_line() { printf '%s\t%s\t%s\t%s\n' "$(date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ)" installed v1.0.0 "$2" >>"$W/state/history.log"; }
setup rc v1.0.0 v1.0.0 v1.1.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 -1000
watch
equals "missed: exit 0" 0 "$RC"
equals "missed: OUTCOME" missed "$(sget scheduled OUTCOME)"
equals "missed: NOTIFIED" 1 "$(sget scheduled NOTIFIED)"
has 'make site-notice :: .*ARGS=withdraw 7$' && ok "missed: the notice is withdrawn" || not_ok "missed: notice withdrawn" "$(cat "$LOG")"
equals "missed: one mail" "[ManuSpectrum][Release] scheduled update of v1.1.0 missed" "$(subjects | sed 's/^Subject: //')"
metric 'schedule_failed{reason="missed"} 1' && ok "missed: metric schedule_failed missed" || not_ok "missed: metric" "$(cat "$(prom)")"
equals "missed: armed is kept" v1.1.0 "$(sget armed TAG)"
watch
equals "missed, second run: no second mail" 1 "$(nmails)"
setup rc v1.0.0 v1.0.0 v1.1.0 v1.2.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 -1000
watch
equals "missed: a newer release is then armed" "v1.2.0 missed" "$(sget armed TAG) $(sget scheduled OUTCOME)"
setup rc v1.0.0 v1.0.0 v1.1.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 -1000 NOTICE_ID=; touch "$W/f/probe_down_git"
watch
equals "missed: detected even when a probe fails, no notice call without an id" "1 missed" "$RC $(sget scheduled OUTCOME)"
has 'site-notice' && not_ok "missed: no notice call without an id" || ok "missed: no notice call without an id"
setup rc v1.0.0 v1.0.0 v1.1.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 -1000; touch "$W/f/notice_fail"
watch
equals "missed: a failing notice command is only logged" "0 missed" "$RC $(sget scheduled OUTCOME)"
setup rc v1.0.0 v1.0.0 v1.1.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 -1000; touch "$W/f/mail_fail"
watch
equals "missed, mail fails: missed recorded, NOTIFIED 0, step mail" "1 missed 0" "$RC $(sget scheduled OUTCOME) $(sget scheduled NOTIFIED)"
rm "$W/f/mail_fail"; watch
equals "missed, mail retried once" "1 1" "$(sget scheduled NOTIFIED) $(nmails)"
setup rc v1.0.0 v1.0.0 v1.1.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 -600
watch
equals "slot passed by less than 15 minutes: not missed" "" "$(sget scheduled OUTCOME)"
setup rc v1.0.0 v1.0.0 v1.1.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 -1000; state_w inflight FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1
watch
equals "an update in flight: not missed" "" "$(sget scheduled OUTCOME)"
setup rc v1.0.0 v1.0.0 v1.1.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 -1000; history_line $((NOW - 900)) v1.1.0
watch
equals "history has the run after CREATED_AT: not missed" "" "$(sget scheduled OUTCOME)"
setup rc v1.0.0 v1.0.0 v1.1.0
arm v1.1.0 "$C11" "$D2" 1; sched v1.1.0 -1000; history_line $((NOW - 20000)) v1.1.0; history_line $((NOW - 900)) v1.0.5
watch
equals "history lines before CREATED_AT or for another tag do not count" missed "$(sget scheduled OUTCOME)"

echo "1..$N"
[ "$FAILED" -eq 0 ] || { echo "# FAILED"; exit 1; }
