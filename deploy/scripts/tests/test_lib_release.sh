#!/usr/bin/env bash
# deploy/scripts/tests/test_lib_release.sh
# Tests of lib-release.sh: tag regex (shared with release-ref-guard.sh), semver
# order and channel selection, state files, the .env image rewrite, missing
# keys, the metrics file, the release mail and the slot parser. Prints
# `ok N` / `not ok N`; exits non-zero on failure.
# shellcheck disable=SC2319,SC2015,SC2001,SC2030,SC2031,SC2016
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HERE/../lib-release.sh"
GUARD="$HERE/../release-ref-guard.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }
check() { # check NAME COMMAND...: passes when the command succeeds
  local name="$1" out
  shift
  out="$("$@" 2>&1)" && ok "$name" || not_ok "$name" "$out"
}
refused() { # refused NAME COMMAND...: passes when the command fails
  local name="$1" out
  shift
  out="$("$@" 2>&1)" && not_ok "$name (accepted)" "$out" || ok "$name"
}
equals() { # equals NAME EXPECTED ACTUAL
  [ "$2" = "$3" ] && ok "$1" || not_ok "$1" "expected: $2
actual:   $3"
}

if [ ! -f "$LIB" ]; then
  not_ok "lib-release.sh exists" "$LIB is missing"
  exit 1
fi
# shellcheck source=../lib-release.sh
# shellcheck source-path=SCRIPTDIR
source "$LIB"

# --- tag regex, shared with the ref guard
for t in v1.2.3 v0.0.0 v10.20.30 v1.2.3-rc.0 v1.2.3-rc.12; do
  check "tag accepted: $t" release_tag_valid "$t"
done
for t in v1.2 v1.2.3-beta V1.0.0 v01.0.0 v1.2.3-rc v1.2.3-rc.01 "v1.2.3 " $'v1.2.3\n' 'v1.2.3$(id)' ""; do
  refused "tag refused: ${t//$'\n'/\\n}" release_tag_valid "$t"
done
check "rc detected" release_tag_is_rc v1.2.3-rc.1
refused "final is not rc" release_tag_is_rc v1.2.3

GREPO="$TMP/guard-repo"
git init -q "$GREPO"
(
  cd "$GREPO" || exit 1
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@manuspectrum.test GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@manuspectrum.test
  git commit -q --allow-empty -m a
  git update-ref refs/remotes/origin/main HEAD
  git update-ref refs/remotes/origin/dev HEAD
  for t in v1.2.3 v1.2.3-rc.1 v1.2 v1.2.3-beta V1.0.0 v01.0.0 v1.2.3-rc v1.2.3-rc.01; do git tag "$t" 2>/dev/null; done
  mismatch=""
  for t in v1.2.3 v1.2.3-rc.1 v1.2 v1.2.3-beta V1.0.0 v01.0.0 v1.2.3-rc v1.2.3-rc.01; do
    release_tag_valid "$t" && lib=1 || lib=0
    bash "$GUARD" "$t" >/dev/null 2>"$TMP/guard.err"
    if grep -q "is not a release tag" "$TMP/guard.err"; then guard=0; else guard=1; fi
    [ "$lib" = "$guard" ] || mismatch+="$t "
  done
  [ -z "$mismatch" ] || { echo "disagree: $mismatch"; exit 1; }
) && ok "ref guard and library accept and refuse the same names" || not_ok "ref guard and library disagree"
grep -q 'lib-release.sh' "$GUARD" && ok "ref guard sources the library" || not_ok "ref guard does not source the library"

# --- semver order
cmp_is() { equals "cmp $1 $2" "$3" "$(release_semver_cmp "$1" "$2")"; }
cmp_is v1.2.0-rc.3 v1.2.0 -1
cmp_is v1.2.0 v1.2.1-rc.1 -1
cmp_is v1.2.0-rc.10 v1.2.0-rc.9 1
cmp_is v1.2.0-rc.9 v1.2.0-rc.10 -1
cmp_is v1.2.0 v1.2.0 0
cmp_is v1.10.0 v1.9.9 1
cmp_is v2.0.0-rc.1 v1.99.99 1
refused "cmp refuses a malformed tag" release_semver_cmp v1.2 v1.2.0
refused "cmp refuses an oversized component" release_semver_cmp v1.2.0 v1.2.1234567890123

# --- channel candidate
TAGS=$'v1.1.0\nv1.2.0-rc.1\nv1.2.0-rc.2\nv1.2.0\nv1.3.0-rc.1\nbogus\nv1.2\nv1.0.0'
pick() { printf '%s\n' "$TAGS" | release_pick_candidate "$1" "$2"; }
equals "prod from v1.1.0 picks v1.2.0, not the rc" v1.2.0 "$(pick prod v1.1.0)"
equals "rc from v1.1.0 picks the highest incl. rc" v1.3.0-rc.1 "$(pick rc v1.1.0)"
equals "rc from v1.2.0-rc.1 picks the highest" v1.3.0-rc.1 "$(pick rc v1.2.0-rc.1)"
equals "prod from an rc current picks the final" v1.2.0 "$(pick prod v1.2.0-rc.1)"
equals "never a downgrade (prod, current newest)" "" "$(pick prod v1.2.0 || true)"
refused "no candidate exits non-zero" pick prod v1.2.0
equals "rc: current v1.3.0-rc.1 has nothing newer" "" "$(pick rc v1.3.0-rc.1 || true)"
equals "rc from v1.2.0 skips the older rc" v1.3.0-rc.1 "$(pick rc v1.2.0)"
refused "unknown channel refused" pick beta v1.1.0
refused "malformed current refused" pick prod v1.1

# --- state files
S="$TMP/state"
mkdir "$S"
IMG="ghcr.io/example/manuspectrum@sha256:$(printf 'ab%.0s' {1..32})"
COMMIT="$(printf 'cd%.0s' {1..20})"
check "write armed" release_state_write "$S/armed" TAG=v1.2.0 "IMAGE=$IMG" "COMMIT=$COMMIT" ARMED_AT=1790000000 SECURITY=1 NOTIFIED=0 NEEDS_ANSIBLE=0
equals "get TAG" v1.2.0 "$(release_state_get "$S/armed" TAG)"
equals "get IMAGE" "$IMG" "$(release_state_get "$S/armed" IMAGE)"
equals "get SECURITY" 1 "$(release_state_get "$S/armed" SECURITY)"
refused "get unknown key refused" release_state_get "$S/armed" NOPE
refused "get a key the file lacks" release_state_get "$S/armed" HELD_TAG
check "read validates and prints" release_state_read "$S/armed"
chmod 0640 "$S/armed"
check "set one key" release_state_set "$S/armed" NOTIFIED 1
equals "set kept the other keys" v1.2.0 "$(release_state_get "$S/armed" TAG)"
equals "set changed the key" 1 "$(release_state_get "$S/armed" NOTIFIED)"
equals "write keeps the mode" 640 "$(stat -c %a "$S/armed")"
check "no temp file left" test -z "$(find "$S" -name '*.tmp*' -o -name '.*.XXXX*' | head -1)"
equals "only the state file in the dir" armed "$(ls -A "$S")"
before="$(cat "$S/armed")"
for bad in 'TAG=$(id)' 'TAG=v1.2.0;id' 'TAG=v1.2' 'TAG=v1.2.0
EXTRA=1' 'TAG=`id`' 'TAG= v1.2.0' 'IMAGE=ghcr.io/x/y:latest' 'IMAGE=ghcr.io/x/y@sha256:abc' 'COMMIT=abc' 'COMMIT=ABCDEF0123456789ABCDEF0123456789ABCDEF01' \
  'SECURITY=2' 'NOTIFIED=yes' 'ARMED_AT=12ab' 'ARMED_AT=' 'REASON=other' 'OUTCOME=done' 'NOTICE_ID=1x' 'BY=Root' 'BY=a b' 'BY=$(id)' 'NOPE=1' 'tag=v1.2.0' 'AT_PARIS=2027-13-01 10:00' 'AT_PARIS=2027-01-01 10:00:00' 'INVOCATION_ID=abc' "INVOCATION_ID=$(printf 'A%.0s' {1..32})" "INVOCATION_ID=$(printf 'a%.0s' {1..33})"; do
  refused "write refuses: ${bad//$'\n'/\\n}" release_state_write "$S/armed" "$bad"
done
equals "refused writes left the file untouched" "$before" "$(cat "$S/armed")"
refused "write refuses a duplicate key" release_state_write "$S/dup" TAG=v1.0.0 TAG=v1.0.1
refused "set refuses a bad value" release_state_set "$S/armed" TAG '$(id)'
for r in drift unarmed tag_moved env_keys managed_sources verify backup lock busy fetch late; do
  check "REASON=$r" release_state_write "$S/sched" TAG=v1.2.0 "REASON=$r"
done
check "INVOCATION_ID: 32 hex" release_state_write "$S/inv" FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1 "INVOCATION_ID=$(printf 'ab%.0s' {1..16})"
check "INVOCATION_ID may be empty" release_state_write "$S/inv" FROM_TAG=v1.0.0 TO_TAG=v1.1.0 STARTED_AT=1 INVOCATION_ID=
check "COUNT and APPLIED_AT" release_state_write "$S/rb" COUNT=3 APPLIED_AT=1790000000 ROLLBACK_FAILED=1
for bad in COUNT=-1 COUNT=x COUNT= COUNT=1234567890 'APPLIED_AT=1x'; do
  refused "write refuses: $bad" release_state_write "$S/rb" "$bad"
done
check "OUTCOME empty and missed" release_state_write "$S/sched" OUTCOME= REASON=
check "OUTCOME=missed" release_state_write "$S/sched" OUTCOME=missed
check "scheduled record" release_state_write "$S/sched" TAG=v1.2.0-rc.1 AT_EPOCH=1790000000 "AT_PARIS=2027-01-05 23:00" WINDOW_END_EPOCH=1790001800 NOTICE_ID=12 BY=op_1-a CREATED_AT=1789990000 OUTCOME= REASON= HELD_TAG= NOTIFIED=0
equals "AT_PARIS round-trips with its space" "2027-01-05 23:00" "$(release_state_get "$S/sched" AT_PARIS)"
equals "empty value is read back empty" "" "$(release_state_get "$S/sched" HELD_TAG)"
# Malformed files on disk are refused, never sourced.
printf 'TAG=v1.2.0\n' >"$S/evil"
printf 'TAG=$(touch %s/pwned)\n' "$TMP" >"$S/evil2"
printf 'TAG=v1.2.0\nTAG=v1.2.1\n' >"$S/evil3"
printf 'TAG=v1.2.0\nthis is not a line\n' >"$S/evil4"
printf 'TAG=v1.2.0\r\n' >"$S/evil5"
check "reads a one-line file without a final newline" release_state_get "$S/evil" TAG
for f in evil2 evil3 evil4 evil5; do
  refused "read refuses malformed file $f" release_state_read "$S/$f"
done
check "no command ran" test ! -e "$TMP/pwned"
refused "get on a missing file" release_state_get "$S/absent" TAG

# --- .env image rewrite
E="$TMP/.env"
OLD="ghcr.io/example/manuspectrum@sha256:$(printf '11%.0s' {1..32})"
NEW="ghcr.io/example/manuspectrum@sha256:$(printf '22%.0s' {1..32})"
printf 'A=1\nMANUSPECTRUM_IMAGE=old:tag\n# MANUSPECTRUM_IMAGE=comment\nB=2\nMANUSPECTRUM_IMAGE=%s\nC=3 # MANUSPECTRUM_IMAGE=x\n' "$OLD" >"$E"
chmod 0640 "$E"
check "env image rewrite" release_env_set_image "$E" "$NEW"
equals "only the last image line changed" "A=1
MANUSPECTRUM_IMAGE=old:tag
# MANUSPECTRUM_IMAGE=comment
B=2
MANUSPECTRUM_IMAGE=$NEW
C=3 # MANUSPECTRUM_IMAGE=x" "$(cat "$E")"
equals "env mode kept" 640 "$(stat -c %a "$E")"
equals "env owner kept" "$(id -u)" "$(stat -c %u "$E")"
equals "env read gives the last line" "$NEW" "$(release_env_get "$E" MANUSPECTRUM_IMAGE)"
before="$(cat "$E")"
for bad in "ghcr.io/x/y:latest" "ghcr.io/x/y@sha256:abc" "" "$NEW
EVIL=1" 'ghcr.io/x/y@sha256:$(id)' "$NEW "; do
  refused "env rewrite refuses: ${bad//$'\n'/\\n}" release_env_set_image "$E" "$bad"
done
equals "refused rewrites left .env untouched" "$before" "$(cat "$E")"
printf 'A=1\n' >"$TMP/.env-noimage"
refused "env without an image line refused" release_env_set_image "$TMP/.env-noimage" "$NEW"
refused "env missing file refused" release_env_set_image "$TMP/absent" "$NEW"
strays="$(find "$TMP" -maxdepth 1 -name '.env.*' | wc -l)"
equals "no stray temp file next to .env" 0 "$strays"
printf 'K="quoted"\nQ='"'single'"'\nE=\n' >"$TMP/.env-q"
equals "env get strips matching quotes" quoted "$(release_env_get "$TMP/.env-q" K)"
equals "env get strips single quotes" single "$(release_env_get "$TMP/.env-q" Q)"
equals "env get empty value" "" "$(release_env_get "$TMP/.env-q" E)"
refused "env get absent key" release_env_get "$TMP/.env-q" ZZ
refused "env get bad key name" release_env_get "$TMP/.env-q" 'K;id'

# --- missing keys
printf '# comment\nA=1\nB=\n#C=3\nRELEASE_CHANNEL=prod\nRELEASE_READY_WAIT_SECONDS=600\n\nnot a key\n' >"$TMP/example"
printf 'A=1\nB=x\n' >"$TMP/env-m"
equals "missing keys from a file" "RELEASE_CHANNEL
RELEASE_READY_WAIT_SECONDS" "$(release_env_missing_keys "$TMP/env-m" "$TMP/example")"
equals "missing keys from stdin" "RELEASE_CHANNEL
RELEASE_READY_WAIT_SECONDS" "$(release_env_missing_keys "$TMP/env-m" <"$TMP/example")"
equals "missing keys from stdin with -" "RELEASE_CHANNEL
RELEASE_READY_WAIT_SECONDS" "$(release_env_missing_keys "$TMP/env-m" - <"$TMP/example")"
printf 'A=1\nB=\nRELEASE_CHANNEL=rc\nRELEASE_READY_WAIT_SECONDS=1\n' >"$TMP/env-full"
equals "no key missing" "" "$(release_env_missing_keys "$TMP/env-full" "$TMP/example")"
equals "a key present with an empty value is not missing" "" "$(release_env_missing_keys "$TMP/env-full" "$TMP/example")"

# --- metrics
M="$TMP/manuspectrum_release.prom"
check "metrics written" release_metrics_write "$M" watch_last_run=1790000100 armed=1 pending_since=1789000000 pending_security=1 rollbacks=2 failed_registry=1 scheduled=1790003000 schedule_failed_missed=1
body="$(cat "$M")"
for series in 'manuspectrum_release_watch_last_run_timestamp_seconds 1790000100' 'manuspectrum_release_verification_failed 0' 'manuspectrum_release_armed 1' \
  'manuspectrum_release_pending_since_timestamp_seconds 1789000000' 'manuspectrum_release_pending_security 1' 'manuspectrum_release_rollbacks_total 2' \
  'manuspectrum_release_rollback_failed 0' 'manuspectrum_release_inflight_since_timestamp_seconds 0' 'manuspectrum_release_update_last_success_timestamp_seconds 0' 'manuspectrum_release_scheduled_timestamp_seconds 1790003000' \
  'manuspectrum_release_watch_failed{step="git"} 0' 'manuspectrum_release_watch_failed{step="registry"} 1' 'manuspectrum_release_watch_failed{step="sigstore"} 0' \
  'manuspectrum_release_watch_failed{step="pull"} 0' 'manuspectrum_release_watch_failed{step="mail"} 0' 'manuspectrum_release_watch_failed{step="state"} 0' \
  'manuspectrum_release_schedule_failed{reason="refused"} 0' 'manuspectrum_release_schedule_failed{reason="missed"} 1'; do
  grep -qxF "$series" <<<"$body" && ok "series: $series" || not_ok "series: $series" "$body"
done
equals "mode 0644" 644 "$(stat -c %a "$M")"
equals "no temp file" 1 "$(find "$TMP" -maxdepth 1 -name 'manuspectrum_release.prom*' | wc -l)"
check "counter typed" grep -qx '# TYPE manuspectrum_release_rollbacks_total counter' "$M"
before="$(cat "$M")"
refused "metrics refuse an unknown name" release_metrics_write "$M" bogus=1
refused "metrics refuse a non-number" release_metrics_write "$M" armed=yes
equals "refused metrics left the file untouched" "$before" "$(cat "$M")"
check "no .tmp left" test ! -e "$M.tmp"
check "defaults: a bare call emits every series" release_metrics_write "$TMP/bare.prom"
equals "bare call emits 18 samples" 18 "$(grep -vc '^#' "$TMP/bare.prom")"

# --- mail
mkdir -p "$TMP/mailbin"
cat >"$TMP/mailbin/sendmail" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >"$MAIL_ARGS"
cat >"$MAIL_OUT"
[ -z "${MAIL_FAIL:-}" ]
SH
chmod +x "$TMP/mailbin/sendmail"
export MAIL_ARGS="$TMP/mail.args" MAIL_OUT="$TMP/mail.out"
export RELEASE_SENDMAIL="$TMP/mailbin/sendmail"
ENV_FILE="$TMP/.env-mail"
printf 'ALERT_EMAILS=ops@manuspectrum.test, team@manuspectrum.test\nALERT_EMAIL_FROM="noreply@manuspectrum.test"\n' >"$ENV_FILE"
check "mail sent" release_mail "v1.2.0 available (security)" $'Line one\nLine two\n.\nend'
equals "sendmail flags" "-oi -t" "$(cat "$MAIL_ARGS")"
mail="$(cat "$MAIL_OUT")"
for h in 'To: ops@manuspectrum.test, team@manuspectrum.test' 'From: noreply@manuspectrum.test' 'Subject: [ManuSpectrum][Release] v1.2.0 available (security)' 'X-ManuSpectrum-Category: Release'; do
  grep -qxF "$h" <<<"$mail" && ok "header: $h" || not_ok "header: $h" "$mail"
done
grep -qx 'Line two' <<<"$mail" && ok "body present" || not_ok "body present" "$mail"
equals "headers end with a blank line before the body" "" "$(awk 'NF==0{getline n; print ""; exit}' <<<"$mail")"
rm -f "$MAIL_OUT"
refused "mail refuses LF in subject" release_mail $'ready\nBcc: x@y.test' body
refused "mail refuses CR in subject" release_mail $'ready\rBcc: x@y.test' body
refused "mail refuses an empty subject" release_mail "" body
check "nothing was sent for refused subjects" test ! -e "$MAIL_OUT"
printf 'ALERT_EMAILS=ops@manuspectrum.test\nALERT_EMAIL_FROM=noreply@manuspectrum.test\nALERT_EMAILS=ops@manuspectrum.test\n' >"$ENV_FILE"
check "last duplicate wins, still valid" release_mail ok body
printf 'ALERT_EMAILS=ops@manuspectrum.test,\nALERT_EMAIL_FROM=noreply@manuspectrum.test\n' >"$ENV_FILE"
refused "mail refuses an empty recipient" release_mail ok body
printf 'ALERT_EMAILS=ops@manuspectrum.test\rBcc: x@y.test\nALERT_EMAIL_FROM=noreply@manuspectrum.test\n' >"$ENV_FILE"
refused "mail refuses CR in recipients" release_mail ok body
printf 'ALERT_EMAILS=ops@manuspectrum.test\nALERT_EMAIL_FROM=a@b.test, c@d.test\n' >"$ENV_FILE"
refused "mail refuses a list as sender" release_mail ok body
printf 'ALERT_EMAILS=\nALERT_EMAIL_FROM=noreply@manuspectrum.test\n' >"$ENV_FILE"
refused "mail refuses missing recipients" release_mail ok body
printf 'ALERT_EMAILS=ops@manuspectrum.test\nALERT_EMAIL_FROM=noreply@manuspectrum.test\n' >"$ENV_FILE"
MAIL_FAIL=1 refused "mail reports a sendmail failure" release_mail ok body

# --- slot parser
T=$'\t'
now() { date -u -d "$1" +%s; }
export RELEASE_NOW_EPOCH
RELEASE_NOW_EPOCH="$(now '2027-03-20 12:00:00')"
equals "winter slot: UTC epoch, UTC form, Paris form" "$(now '2027-03-22 22:00:00')${T}2027-03-22 22:00${T}2027-03-22 23:00" "$(release_slot_parse '2027-03-22 23:00')"
RELEASE_NOW_EPOCH="$(now '2027-06-01 08:00:00')"
equals "summer slot is UTC+2" "$(now '2027-06-05 21:00:00')${T}2027-06-05 21:00${T}2027-06-05 23:00" "$(release_slot_parse '2027-06-05 23:00')"
RELEASE_NOW_EPOCH="$(now '2027-03-20 12:00:00')"
refused "nonexistent wall-clock time (spring forward)" release_slot_parse '2027-03-28 02:30'
out="$(release_slot_parse '2027-03-28 02:30' 2>&1)"; grep -qi 'does not exist' <<<"$out" && ok "nonexistent hint" || not_ok "nonexistent hint" "$out"
RELEASE_NOW_EPOCH="$(now '2027-10-20 12:00:00')"
refused "ambiguous wall-clock time (fall back)" release_slot_parse '2027-10-31 02:30'
out="$(release_slot_parse '2027-10-31 02:30' 2>&1)"; grep -qi 'twice' <<<"$out" && ok "ambiguous hint" || not_ok "ambiguous hint" "$out"
check "the hour after the ambiguous one is fine" release_slot_parse '2027-10-31 03:30'
RELEASE_NOW_EPOCH="$(now '2027-06-01 21:00:00')"   # 23:00 Paris
refused "slot in the past" release_slot_parse '2027-06-01 22:00'
refused "slot 9 minutes ahead" release_slot_parse '2027-06-01 23:09'
check "slot 11 minutes ahead" release_slot_parse '2027-06-01 23:11'
check "slot 29 days ahead" release_slot_parse '2027-06-30 23:00'
refused "slot beyond 30 days" release_slot_parse '2027-07-02 23:00'
for bad in '2027-6-5 23:00' '2027-06-05T23:00' '2027-06-05 23:00:00' '2027-06-05 24:00' '2027-02-30 10:00' '2027-06-05 23:00;id' $'2027-06-05 23:00\nx' "" 'tomorrow'; do
  refused "slot refuses: ${bad//$'\n'/\\n}" release_slot_parse "$bad"
done

# --- metrics derived from the state files
D="$TMP/derive"; mkdir -p "$D"
mkdir -p "$TMP/refresh-prom"; printf 'METRICS_TEXTFILE_DIR=%s\n' "$TMP/refresh-prom" >"$TMP/refresh.env"
release_state_write "$D/rollbacks" COUNT=1 ROLLBACK_FAILED=0
check "refresh: writes the release textfile named by the .env" release_metrics_refresh "$D" "$TMP/refresh.env"
grep -q '^manuspectrum_release_rollbacks_total 1$' "$TMP/refresh-prom/manuspectrum_release.prom" && ok "refresh: the file holds the state" || not_ok "refresh: the file holds the state" "$(cat "$TMP/refresh-prom/manuspectrum_release.prom" 2>&1)"
printf 'METRICS_TEXTFILE_DIR=%s\n' "$TMP/missing-dir" >"$TMP/refresh.env"
refused "refresh: a missing directory is a status 1" release_metrics_refresh "$D" "$TMP/refresh.env"
rm -f "$D/rollbacks"
P="$TMP/derive.prom"
rm -f "$P"
check "derive: empty state dir" release_metrics_from_state "$D" "$P"
grep -qF 'watch_last_run_timestamp_seconds 0' "$P" && ok "derive: no watch run is claimed" || not_ok "derive: no watch run is claimed" "$(cat "$P")"
grep -q '^manuspectrum_release_armed 0$' "$P" && ok "derive: nothing armed" || not_ok "derive: nothing armed" "$(cat "$P")"
release_state_write "$D/armed" TAG=v1.2.0 IMAGE="ghcr.io/x/y@sha256:$(printf 'a%.0s' {1..64})" COMMIT=0123456789012345678901234567890123456789 ARMED_AT=1790000000 SECURITY=1 NOTIFIED=1 NEEDS_ANSIBLE=0
release_state_write "$D/pending" SINCE=1789000000 SECURITY=1
release_state_write "$D/rollbacks" COUNT=2 ROLLBACK_FAILED=1
release_state_write "$D/current" TAG=v1.1.0 IMAGE="ghcr.io/x/y@sha256:$(printf 'b%.0s' {1..64})" COMMIT=0123456789012345678901234567890123456788 APPLIED_AT=1788000000
release_state_write "$D/scheduled" TAG=v1.2.0 AT_EPOCH=1790003000 OUTCOME=refused REASON=drift
release_state_write "$D/inflight" FROM_TAG=v1.1.0 TO_TAG=v1.2.0 STARTED_AT=1790001000
check "derive: full state" release_metrics_from_state "$D" "$P"
for want in 'armed 1' 'pending_since_timestamp_seconds 1789000000' 'pending_security 1' 'rollbacks_total 2' 'rollback_failed 1' 'update_last_success_timestamp_seconds 1788000000' 'inflight_since_timestamp_seconds 1790001000' 'scheduled_timestamp_seconds 1790003000' 'schedule_failed{reason="refused"} 1' 'schedule_failed{reason="missed"} 0'; do
  grep -qF "manuspectrum_release_$want" "$P" && ok "derive: $want" || not_ok "derive: $want" "$(cat "$P")"
done
release_metrics_write "$P" watch_last_run=1790000100 failed_git=1 verification_failed=1
release_metrics_from_state "$D" "$P" rollbacks=9
grep -qF 'manuspectrum_release_watch_last_run_timestamp_seconds 1790000100' "$P" && grep -qF 'watch_failed{step="git"} 1' "$P" && grep -qF 'verification_failed 1' "$P" && ok "derive: carries the watch series" || not_ok "derive: carries the watch series" "$(cat "$P")"
grep -qF 'rollbacks_total 9' "$P" && ok "derive: an explicit value wins" || not_ok "derive: an explicit value wins" "$(cat "$P")"
printf 'garbage\n' >"$D/pending"
check "derive: an unreadable state file counts as absent" release_metrics_from_state "$D" "$P"
grep -qF 'pending_since_timestamp_seconds 0' "$P" && ok "derive: unreadable pending is 0" || not_ok "derive: unreadable pending is 0" "$(cat "$P")"

echo "1..$N"
[ "$FAILED" -eq 0 ] || { echo "# FAILED"; exit 1; }
