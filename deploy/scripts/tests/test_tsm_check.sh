#!/usr/bin/env bash
# deploy/scripts/tests/test_tsm_check.sh
# Tests of tsm-check.sh. The provider's options file, report and include file
# are fixtures in a scratch directory. Prints `ok N` / `not ok N`; exits non-zero on failure.
# $? after a compound test is the point of every assertion below.
# shellcheck disable=SC2319
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHECK="$HERE/../tsm-check.sh"
FIXTURE="$HERE/fixtures/tsm/report-ok.txt"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

OUT="$TMP/metrics"
REPORT="$TMP/report.log"
INCLEXCL="$TMP/inclexcl.def"
OPTIONS="$TMP/dsm.sys"
mkdir -p "$OUT"
n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

GOOD_INCLUDES='include /var/log/.../* LOG_ROTATED_FILES_MG
include /data/app/nginx-logs/.../* LOG_ROTATED_FILES_MG'

reset() { # fresh metrics directory, fixture report dated now, both include lines
  rm -rf "${OUT:?}" && mkdir -p "$OUT"
  cp "$FIXTURE" "$REPORT"
  touch "$REPORT"
  printf '%s\n' "$GOOD_INCLUDES" >"$INCLEXCL"
  : >"$OPTIONS"
}

run() { # run [VAR=value ...]; stderr in $TMP/stderr
  env METRICS_TEXTFILE_DIR="$OUT" TSM_OPTIONS="$OPTIONS" \
    TSM_LOG_DIRS="/var/log /data/app/nginx-logs" TSM_REPORT="$REPORT" TSM_INCLEXCL="$INCLEXCL" \
    "$@" bash "$CHECK" 2>"$TMP/stderr"
}

sample() { # sample FILE METRIC: the value, empty when absent
  sed -n "s/^$2 //p" "$OUT/$1" 2>/dev/null
}

reset
rm -f "$OPTIONS"
run
rc=$?
[ "$rc" -eq 0 ] && [ "$(sample manuspectrum_tsm_check.prom manuspectrum_tsm_check_enabled)" = 0 ] \
  && [ "$(sample manuspectrum_tsm_check.prom manuspectrum_tsm_log_include_ok)" = 0 ] \
  && [ ! -e "$OUT/manuspectrum_tsm_backup_success.prom" ] \
  && grep -q 'not configured' "$TMP/stderr"
assert "options file absent: enabled 0, no success file, exit 0" $?

reset
run
rc=$?
mtime="$(stat -c %Y "$REPORT")"
[ "$rc" -eq 0 ] \
  && [ "$(sample manuspectrum_tsm_backup_success.prom manuspectrum_tsm_backup_last_success_timestamp_seconds)" = "$mtime" ] \
  && [ "$(sample manuspectrum_tsm_check.prom manuspectrum_tsm_log_include_ok)" = 1 ] \
  && [ "$(sample manuspectrum_tsm_check.prom manuspectrum_tsm_check_enabled)" = 1 ]
assert "today's report with both filespaces and both include lines: success file holds the report's mtime, include_ok 1, exit 0" $?

reset
touch -d "yesterday 06:25" "$REPORT"
run
rc=$?
[ "$rc" -eq 1 ] && [ ! -e "$OUT/manuspectrum_tsm_backup_success.prom" ] && grep -q 'tsm-check: FAIL' "$TMP/stderr"
assert "report dated yesterday: exit 1, no success file" $?

reset
grep -v "backup of '/var/log'" "$FIXTURE" >"$REPORT"
touch "$REPORT"
run
rc=$?
[ "$rc" -eq 1 ] && [ ! -e "$OUT/manuspectrum_tsm_backup_success.prom" ]
assert "no Successful line for /var/log: exit 1, no success file" $?

reset
sed "s|Successful incremental backup of '/var/log'|Successful incremental backup of '/var/log/old'|" "$FIXTURE" >"$REPORT"
touch "$REPORT"
run
rc=$?
[ "$rc" -eq 1 ] && [ ! -e "$OUT/manuspectrum_tsm_backup_success.prom" ]
assert "a Successful line for another filespace name does not count" $?

reset
rm -f "$REPORT"
run
rc=$?
[ "$rc" -eq 1 ] && [ ! -e "$OUT/manuspectrum_tsm_backup_success.prom" ]
assert "report missing: exit 1" $?

reset
run
sleep 1
earlier="$(cat "$OUT/manuspectrum_tsm_backup_success.prom")"
touch -d "yesterday 06:25" "$REPORT"
run
rc=$?
[ "$rc" -eq 1 ] && [ "$(cat "$OUT/manuspectrum_tsm_backup_success.prom")" = "$earlier" ]
assert "a failing run leaves an earlier success file unchanged" $?

reset
printf 'include /var/log/.../* LOG_ROTATED_FILES_MG\n' >"$INCLEXCL"
run
rc=$?
[ "$rc" -eq 1 ] && [ "$(sample manuspectrum_tsm_check.prom manuspectrum_tsm_log_include_ok)" = 0 ] \
  && [ -s "$OUT/manuspectrum_tsm_backup_success.prom" ]
assert "include line missing for one directory: include_ok 0, exit 1, backup success still written" $?

for bad in '* include /var/log/.../* LOG_ROTATED_FILES_MG' '*include /var/log/.../* LOG_ROTATED_FILES_MG' \
  'include /var/log/.../* LOG_FILES_MG' 'include /var/log/.../* LOG_ROTATED_FILES_MG_X'; do
  reset
  printf '%s\ninclude /data/app/nginx-logs/.../* LOG_ROTATED_FILES_MG\n' "$bad" >"$INCLEXCL"
  run
  rc=$?
  [ "$rc" -eq 1 ] && [ "$(sample manuspectrum_tsm_check.prom manuspectrum_tsm_log_include_ok)" = 0 ]
  assert "include line '$bad' does not count" $?
done

reset
printf '* comment\n   INCLUDE   /var/log/.../*\t LOG_ROTATED_FILES_MG  \ninclude /data/app/nginx-logs/.../* LOG_ROTATED_FILES_MG\n' >"$INCLEXCL"
run
rc=$?
[ "$rc" -eq 0 ] && [ "$(sample manuspectrum_tsm_check.prom manuspectrum_tsm_log_include_ok)" = 1 ]
assert "include word in any case, blank runs and leading blanks are accepted" $?

reset
{ printf 'Normal File-->  1 /var/log/caf\351\377\n'; cat "$FIXTURE"; } >"$REPORT"
touch "$REPORT"
run
rc=$?
[ "$rc" -eq 0 ] && [ -s "$OUT/manuspectrum_tsm_backup_success.prom" ]
assert "a report holding non-UTF-8 bytes in a file name is still read" $?

reset
run TSM_REQUIRED_FILESPACES="/data /var/log /srv"
rc=$?
[ "$rc" -eq 1 ] && [ ! -e "$OUT/manuspectrum_tsm_backup_success.prom" ]
assert "TSM_REQUIRED_FILESPACES adds a filespace that must have finished" $?

reset
mkdir -p "$TMP/logs/[ab]" "$TMP/logs/a"
printf 'include %s/logs/[ab]/.../* LOG_ROTATED_FILES_MG\n' "$TMP" >"$INCLEXCL"
run TSM_LOG_DIRS="$TMP/logs/[ab]"
rc=$?
[ "$rc" -eq 0 ] && [ "$(sample manuspectrum_tsm_check.prom manuspectrum_tsm_log_include_ok)" = 1 ]
assert "a log directory name holding glob characters is taken literally" $?

reset
run METRICS_TEXTFILE_DIR=""
rc=$?
[ "$rc" -eq 2 ] && [ -z "$(ls -A "$OUT")" ]
assert "METRICS_TEXTFILE_DIR unset: exit 2, nothing written" $?

reset
run METRICS_TEXTFILE_DIR="$TMP/absent"
rc=$?
[ "$rc" -eq 2 ] && [ -z "$(ls -A "$OUT")" ] && [ ! -e "$TMP/absent" ]
assert "METRICS_TEXTFILE_DIR missing: exit 2, nothing written" $?

exit "$failed"
