#!/usr/bin/env bash
# deploy/scripts/tests/test_restic_repo_guard.sh
# Tests of restic-repo-guard.sh against a repository fixture the test builds:
# files named after the SHA-256 of their content, a config, a locks/ entry.
# `settle` moves pass.stamp to the present (the guard stores it an hour back) and
# a one-second sleep separates it from the next change, so that "changed after
# the last pass" is a real ctime difference. Prints `ok N` /
# `not ok N`; exits non-zero on failure.
# $? after a compound test is the point of every assertion below.
# shellcheck disable=SC2319
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="${GUARD:-$HERE/../restic-repo-guard.sh}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

OUT="$TMP/metrics"
REPO="$TMP/repo"
STATE="$TMP/state"

LOGSTUB="$TMP/logstub"
LOGCALLS="$TMP/logger.calls"
mkdir -p "$LOGSTUB"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >>"%s"\n' "$LOGCALLS" >"$LOGSTUB/logger"
chmod +x "$LOGSTUB/logger"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

put() { # put DIR CONTENT: a file named after the SHA-256 of its content; prints its path
  local sum
  sum="$(printf '%s' "$2" | sha256sum | cut -d' ' -f1)"
  mkdir -p "$REPO/$1"
  printf '%s' "$2" >"$REPO/$1/$sum"
  echo "$REPO/$1/$sum"
}

reset() { # fresh repository (5 named files), metrics and state directories
  rm -rf "${TMP:?}/metrics" "$REPO" "$STATE" && mkdir -p "$OUT" "$REPO/locks"
  printf 'restic-config' >"$REPO/config"
  PACK="$(put data/ab pack-one)"
  put data/cd pack-two >/dev/null
  put index index-one >/dev/null
  SNAP="$(put snapshots snapshot-one)"
  put keys key-one >/dev/null
  printf 'any' >"$REPO/locks/$(printf 'lock' | sha256sum | cut -d' ' -f1)"
  sleep 1
}

settle() { # settle: pass.stamp = now, after everything written so far
  sleep 1
  touch -d "@$(date +%s)" "$STATE/pass.stamp"
  sleep 1
}

run() { # run [VAR=value ...]; stderr in $TMP/stderr
  timeout 60 env PATH="$LOGSTUB:$PATH" METRICS_TEXTFILE_DIR="$OUT" RESTIC_REPOSITORY_DIR="$REPO" RESTIC_GUARD_STATE_DIR="$STATE" \
    "$@" bash "$GUARD" 2>"$TMP/stderr"
}

sample() { # sample FILE METRIC: the value, empty when absent
  sed -n "s/^$2 //p" "$OUT/$1" 2>/dev/null
}
guard_sample() { sample manuspectrum_restic_repo_guard.prom "manuspectrum_restic_repo_guard_$1"; }

hex() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }
success_file="$OUT/manuspectrum_restic_repo_guard_success.prom"

reset
run
rc=$?
[ "$rc" -eq 0 ] && [ "$(cat "$STATE/config.sha256")" = "$(sha256sum "$REPO/config" | cut -d' ' -f1)" ] \
  && [ -f "$success_file" ] \
  && [ "$(guard_sample files_checked)" = 5 ] && [ "$(guard_sample mismatches)" = 0 ] \
  && [ "$(sample manuspectrum_restic_repo_guard_success.prom manuspectrum_restic_repo_guard_last_success_timestamp_seconds)" = "$(($(stat -c %Y "$STATE/pass.stamp") + 3600))" ] \
  && [ ! -e "$STATE/altered" ]
assert "intact repository, first run: exit 0, config reference recorded, success file written, files_checked equals the 5 repository files, pass.stamp an hour behind the start time" $?

run
rc=$?
[ "$rc" -eq 0 ] && [ "$(guard_sample files_checked)" = 5 ]
assert "a second run right after: the files written within the margin are hashed again" $?

settle
run
rc=$?
[ "$rc" -eq 0 ] && [ "$(guard_sample files_checked)" = 0 ] && [ "$(guard_sample mismatches)" = 0 ]
assert "run after the stamp moved past every file: daily pass checks 0 files, exit 0" $?

reset
run
settle
printf 'X' >>"$PACK"
rm -f "$success_file"
stamp_before="$(stat -c %Y "$STATE/pass.stamp")"
run
rc=$?
[ "$rc" -eq 1 ] && [ "$(guard_sample mismatches)" = 1 ] && [ "$(guard_sample files_checked)" = 1 ] \
  && grep -qF "restic-repo-guard: ALTERED: $PACK" "$TMP/stderr" \
  && [ "$(stat -c %Y "$STATE/pass.stamp")" = "$stamp_before" ] \
  && [ ! -e "$success_file" ] && [ -e "$STATE/altered" ]
assert "a pack overwritten after the last pass: exit 1, mismatches 1, the path logged, stamps and success file unchanged, marker written" $?

reset
run
settle
printf 'tampered' >"$SNAP"
touch -d "@$(($(date +%s) - 3600))" "$SNAP"
run
rc=$?
[ "$rc" -eq 1 ] && grep -qF "ALTERED: $SNAP" "$TMP/stderr"
assert "an overwritten snapshot file with its mtime set back: exit 1 (the ctime moved)" $?

reset
run
printf 'changed' >"$REPO/config"
run
rc=$?
[ "$rc" -eq 1 ] && grep -qF "ALTERED: $REPO/config" "$TMP/stderr" && [ "$(guard_sample mismatches)" = 1 ]
assert "config changed: exit 1" $?

reset
run
settle
printf 'junk' >"$REPO/data/ab/$(hex x).tmp"
printf 'junk' >"$REPO/data/ab/tmp-pack-in-progress"
printf 'junk' >"$REPO/data/ab/$(hex AB | tr a-f A-F)"
printf 'changed' >"$REPO/locks/$(hex lock)"
run
rc=$?
[ "$rc" -eq 0 ] && [ "$(guard_sample files_checked)" = 0 ] && ! grep -q ALTERED "$TMP/stderr"
assert "temporary and upper-case names and a locks/ entry with any content: exit 0, none checked" $?

reset
run
settle
touch -d "@$(($(date +%s) - 4 * 86400))" "$STATE/full.stamp"
run
rc=$?
[ "$rc" -eq 0 ] && [ "$(guard_sample files_checked)" = 5 ] \
  && [ "$(stat -c %Y "$STATE/full.stamp")" -gt "$(($(date +%s) - 60))" ]
assert "full.stamp four days old: every file is checked again, full.stamp renewed" $?

reset
run
settle
touch -d "@$(($(date +%s) - 2 * 86400))" "$STATE/full.stamp"
run
rc=$?
[ "$rc" -eq 0 ] && [ "$(guard_sample files_checked)" = 0 ]
assert "full.stamp two days old: still a daily pass" $?

reset
run
settle
run RESTIC_GUARD_FULL=1
rc=$?
[ "$rc" -eq 0 ] && [ "$(guard_sample files_checked)" = 5 ]
assert "RESTIC_GUARD_FULL=1: every file is checked" $?

reset
rm -rf "$REPO"
run
rc=$?
[ "$rc" -eq 0 ] && [ ! -e "$success_file" ] && [ ! -e "$STATE/pass.stamp" ]
assert "repository directory missing: exit 0, no success file" $?

reset
env PATH="$LOGSTUB:$PATH" RESTIC_REPOSITORY_DIR="$REPO" RESTIC_GUARD_STATE_DIR="$STATE" bash "$GUARD" 2>/dev/null
rc1=$?
env PATH="$LOGSTUB:$PATH" METRICS_TEXTFILE_DIR="$OUT" RESTIC_GUARD_STATE_DIR="$STATE" bash "$GUARD" 2>/dev/null
rc2=$?
[ "$rc1" -eq 2 ] && [ "$rc2" -eq 2 ]
assert "METRICS_TEXTFILE_DIR or RESTIC_REPOSITORY_DIR unset: exit 2" $?

reset
run
settle
late="$REPO/data/ab/$(hex late)"
printf 'late' >"$late"
chmod 000 "$late"
rm -f "$success_file"
stamp_before="$(stat -c %Y "$STATE/pass.stamp")"
run
rc=$?
if [ "$(id -u)" -eq 0 ]; then
  n=$((n + 1)); echo "ok $n - a file that cannot be read: exit 2, no success file, stamps unchanged # SKIP running as root"
else
  [ "$rc" -eq 2 ] && [ ! -e "$success_file" ] \
    && [ "$(stat -c %Y "$STATE/pass.stamp")" = "$stamp_before" ] && grep -q 'could not be read' "$TMP/stderr"
  assert "a file that cannot be read: exit 2, no success file, stamps unchanged" $?
fi

reset
run
settle
unreadable_dir="$REPO/data/ef"
mkdir -p "$unreadable_dir"
printf 'x' >"$unreadable_dir/$(hex x)"
chmod 000 "$unreadable_dir"
rm -f "$success_file"
run
rc=$?
chmod 755 "$unreadable_dir"
if [ "$(id -u)" -eq 0 ]; then
  n=$((n + 1)); echo "ok $n - an unreadable directory under data/: exit 2, no success file # SKIP running as root"
else
  [ "$rc" -eq 2 ] && [ ! -e "$success_file" ]
  assert "an unreadable directory under data/: exit 2, no success file" $?
fi

reset
mkdir -p "$TMP/stub"
victim="$REPO/data/cd/$(hex pack-two)"
real_sha="$(command -v sha256sum)"
printf '#!/bin/sh\nrm -f "%s"\nexec "%s" "$@"\n' "$victim" "$real_sha" >"$TMP/stub/sha256sum"
chmod +x "$TMP/stub/sha256sum"
run PATH="$TMP/stub:$LOGSTUB:$PATH"
rc=$?
[ "$rc" -eq 0 ] && [ -f "$success_file" ] && ! grep -q ALTERED "$TMP/stderr"
assert "a file that vanishes between the listing and the hashing is not an alteration" $?

reset
run
settle
: >"$LOGCALLS"
printf 'X' >>"$PACK"
run
rc=$?
[ "$rc" -eq 1 ] && [ "$(grep -c -- '^-t restic-repo-guard -- ' "$LOGCALLS")" -ge 1 ] && grep -qF "ALTERED: $PACK" "$LOGCALLS"
assert "an altered pack: the system log gets a logger -t restic-repo-guard call naming the file" $?

reset
mkdir -p "$TMP/badlogger"
printf '#!/bin/sh\nexit 1\n' >"$TMP/badlogger/logger"
chmod +x "$TMP/badlogger/logger"
run PATH="$TMP/badlogger:$PATH"
rc=$?
[ "$rc" -eq 0 ] && [ -f "$success_file" ] && grep -q 'repository intact' "$TMP/stderr"
assert "a logger that exits 1: an intact repository still exits 0 and stderr keeps the messages" $?

reset
run TMPDIR="$TMP/no-such-directory"
rc=$?
[ "$rc" -eq 2 ] && grep -q 'FAIL: unexpected error' "$TMP/stderr" && [ ! -e "$success_file" ]
assert "an unexpected failure (TMPDIR missing): exit 2, FAIL: unexpected error logged, no success file" $?

reset
run
settle
printf 'X' >>"$PACK"
run
rc1=$?
run TMPDIR="$TMP/no-such-directory"
rc2=$?
[ "$rc1" -eq 1 ] && [ "$rc2" -eq 1 ] && grep -q 'FAIL: unexpected error' "$TMP/stderr" && grep -q 'last verdict was altered' "$TMP/stderr"
assert "the same unexpected failure after a pass that found an alteration: exit 1" $?

reset
run
settle
printf 'X' >>"$PACK"
run
printf '%s' pack-one >"$PACK"
run
rc=$?
[ "$rc" -eq 0 ] && [ "$(guard_sample mismatches)" = 0 ] && [ ! -e "$STATE/altered" ] && [ -f "$success_file" ]
assert "a clean pass after the repository was repaired: exit 0, mismatch gauge back to 0, marker gone, success file written" $?

reset
run
settle
rm -f "$REPO/config"
run
rc=$?
[ "$rc" -eq 1 ] && grep -qF "ALTERED: $REPO/config (missing)" "$TMP/stderr" && [ "$(guard_sample mismatches)" = 1 ]
assert "config deleted with packs still there, after a first clean run: exit 1" $?

reset
run
settle
rm -rf "${REPO:?}"/{config,data,index,snapshots,keys}
before="$(cksum "$OUT"/*.prom)"
run
rc=$?
[ "$rc" -eq 0 ] && [ "$(cksum "$OUT"/*.prom)" = "$before" ]
assert "a directory with no config and no hash-named file: exit 0, the existing metric files untouched" $?

reset
run
settle
printf 'not-a-sum\n' >"$STATE/config.sha256"
run
rc=$?
[ "$rc" -eq 2 ] && grep -q 'is not a SHA-256' "$TMP/stderr"
assert "a garbled config.sha256: exit 2" $?

reset
run
settle
printf 'X' >>"$PACK"
future="$(($(date +%s) + 86400))"
touch -d "@$future" "$STATE/pass.stamp" "$STATE/full.stamp"
run
rc=$?
[ "$rc" -eq 1 ] && grep -q 'dated in the future' "$TMP/stderr" && grep -qF "ALTERED: $PACK" "$TMP/stderr"
assert "both stamps in the future plus an altered pack: full pass, exit 1" $?

reset
other="$REPO/data/cd/$(hex pack-two)"
# shellcheck disable=SC2016 # the stub's $ expand when it runs.
printf '#!/bin/sh\nout="$("%s" "$@")"\nrc=$?\nprintf X >>"%s"\nprintf "%%s\\n" "$out"\nexit "$rc"\n' "$real_sha" "$other" >"$TMP/stub/sha256sum"
run PATH="$TMP/stub:$LOGSTUB:$PATH"
rc1=$?
run
rc2=$?
[ "$rc1" -eq 0 ] && [ "$rc2" -eq 1 ] && grep -qF "ALTERED: $other" "$TMP/stderr"
assert "a pack overwritten while a pass runs is caught by the next pass" $?
rm -f "$TMP/stub/sha256sum"

reset
run
settle
mkfifo "$TMP/fifo-target"
ln -s "$TMP/fifo-target" "$REPO/data/ab/$(hex link)"
run
rc=$?
[ "$rc" -eq 1 ] && grep -qF "(not a regular file)" "$TMP/stderr"
assert "a hash-named symlink in data/: exit 1, and its target (a FIFO that would block a read) is never opened" $?

reset
for i in $(seq 1 150); do put data/ab "bulk-$i" >/dev/null; done
run
settle
for f in "$REPO"/data/ab/*; do printf 'X' >>"$f"; done
: >"$LOGCALLS"
run
rc=$?
[ "$rc" -eq 1 ] && [ "$(grep -c -- 'ALTERED: ' "$LOGCALLS")" = 100 ] && [ "$(grep -c -- '151 altered files in total' "$LOGCALLS")" = 1 ]
assert "151 altered packs: the system log gets 100 ALTERED lines and one total line" $?

reset
run
settle
printf 'X' >>"$PACK"
rm -rf "$OUT"
run
rc=$?
[ "$rc" -eq 1 ] && [ -e "$STATE/altered" ] && grep -q 'WARNING' "$TMP/stderr"
assert "an altered pack with the metrics directory absent: exit 1, marker written, a WARNING" $?

reset
run
settle
printf 'X' >>"$PACK"
printf '#!/bin/sh\nmv "%s" "%s.gone" 2>/dev/null\nexec "%s" "$@"\n' "$OUT" "$OUT" "$real_sha" >"$TMP/stub/sha256sum"
chmod +x "$TMP/stub/sha256sum"
run PATH="$TMP/stub:$LOGSTUB:$PATH"
rc=$?
rm -rf "$OUT.gone" "$TMP/stub/sha256sum"
[ "$rc" -eq 1 ] && [ -e "$STATE/altered" ]
assert "an altered pack with the metrics directory removed after the listing started: exit 1, marker written" $?

reset
rm -rf "$OUT"
run
rc=$?
[ "$rc" -eq 0 ] && grep -q 'WARNING' "$TMP/stderr" && [ -f "$STATE/pass.stamp" ] && [ -f "$STATE/full.stamp" ]
assert "an intact repository with the metrics directory absent: exit 0, a WARNING, stamps moved" $?

reset
run
settle
printf 'X' >>"$PACK"
mkdir -p "$TMP/awkstub"
printf '#!/bin/sh\nexit 1\n' >"$TMP/awkstub/awk"
chmod +x "$TMP/awkstub/awk"
rm -f "$success_file"
run PATH="$TMP/awkstub:$LOGSTUB:$PATH"
rc=$?
[ "$rc" -eq 2 ] && [ ! -e "$success_file" ] && ! grep -q 'repository intact' "$TMP/stderr"
assert "a failing awk with an altered pack: not intact, exit 2, no success file" $?

reset
run
settle
printf 'X' >>"$PACK"
run
settle
run
rc=$?
[ "$rc" -eq 1 ] && [ -e "$STATE/altered" ] && grep -qF "ALTERED: $PACK" "$TMP/stderr"
assert "marker present and the alteration older than pass.stamp: the next run is a full pass and still exits 1" $?

reset
rm -f "$REPO/config"
run
rc=$?
[ "$rc" -eq 1 ] && grep -qF "ALTERED: $REPO/config (missing)" "$TMP/stderr" && [ "$(guard_sample mismatches)" = 1 ]
assert "config missing with packs there and no reference recorded yet: exit 1" $?

reset
rm -rf "${REPO:?}"/{config,data,index,snapshots,keys}
mkdir -p "$REPO/data/aa"
chmod 000 "$REPO/data/aa"
run
rc=$?
chmod 755 "$REPO/data/aa"
if [ "$(id -u)" -eq 0 ]; then
  n=$((n + 1)); echo "ok $n - no config and a directory that cannot be listed: exit 2, not no repository # SKIP running as root"
else
  [ "$rc" -eq 2 ] && ! grep -q 'no restic repository' "$TMP/stderr"
  assert "no config and a directory that cannot be listed: exit 2, not no repository" $?
fi

reset
run
settle
touch -d "@$(($(date +%s) - 3 * 86400 + 10))" "$STATE/full.stamp"
run
rc=$?
[ "$rc" -eq 0 ] && [ "$(guard_sample files_checked)" = 5 ]
assert "full.stamp three days minus ten seconds old: a full pass" $?

reset
mkdir -p "$STATE/config.sha256.tmp"
run
rc=$?
[ "$rc" -eq 2 ] && grep -q 'FAIL: unexpected error' "$TMP/stderr" && [ ! -e "$STATE/config.sha256" ] && [ ! -e "$success_file" ]
assert "a command failing inside a function (the reference write): exit 2, unexpected error logged, no partial reference" $?

exit "$failed"
