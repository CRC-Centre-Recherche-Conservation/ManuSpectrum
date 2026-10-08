#!/usr/bin/env bash
# deploy/scripts/tests/test_secret_set.sh
# Tests of secret-set.sh and secrets-check.sh. Every secret value is random and
# generated at run time. The value must reach neither an argv (external
# commands run through logging shims), nor stdout or stderr, nor a file outside
# the secrets directory. Prints `ok N` / `not ok N`; exits non-zero on failure.
# $? after a negated or compound test is the point of every assertion below.
# The `A && ok || not_ok` lines are safe: ok never fails.
# shellcheck disable=SC2319,SC2015,SC2001
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SET="$HERE/../secret-set.sh"
CHECK="$HERE/../secrets-check.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

NAMES="pg_password elastic_password django_secret_key email_password admin_password"

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }
expect() { # expect NAME WANT(zero|nonzero) [FORBIDDEN-VALUE]: judges $RC and $OUT
  local name="$1" want="$2" secret="${3:-}"
  if { [ "$want" = zero ] && [ "$RC" -ne 0 ]; } || { [ "$want" = nonzero ] && [ "$RC" -eq 0 ]; }; then
    not_ok "$name (exit $RC)" "$OUT"
  elif [ -n "$secret" ] && grep -qF -- "$secret" <<<"$OUT"; then
    not_ok "$name: the value reached the output"
  else
    ok "$name"
  fi
}
rand() { # rand LENGTH: random alphanumerics
  python3 -c 'import secrets, string, sys; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(int(sys.argv[1]))))' "$1"
}
mode() { stat -c %a "$1"; }

# Logging shims for the external commands the scripts may call: every argv is
# recorded, then the real command runs.
SHIMS="$TMP/shims"
ARGV_LOG="$TMP/argv.log"
mkdir -p "$SHIMS"
: >"$ARGV_LOG"
for cmd in install chmod mv rm mktemp stat cat tr od tail head wc dd cmp tee printf sed grep ls sleep; do
  real="$(command -v "$cmd" 2>/dev/null || true)"
  case "$real" in /*) ;; *) continue ;; esac
  printf '#!/bin/sh\nprintf "%%s\\n" "%s $*" >>"%s"\nexec %s "$@"\n' "$cmd" "$ARGV_LOG" "$real" >"$SHIMS/$cmd"
  chmod +x "$SHIMS/$cmd"
done

run_set() { # run_set DIR VALUE-ON-STDIN ARGS...: sets RC and OUT (stdout and stderr)
  local dir="$1" input="$2"
  shift 2
  OUT="$(printf '%s' "$input" | TMPDIR="$TMP/tmpdir" PATH="$SHIMS:$PATH" bash "$SET" --dir "$dir" --names "$NAMES" "$@" 2>&1)"
  RC=$?
}
mkdir -p "$TMP/tmpdir"

# --- stdin path
D="$TMP/s1"
V1="$(rand 40)"
run_set "$D" "$V1"$'\n' pg_password
expect "stdin: a value is written" zero "$V1"
[ "$(cat "$D/pg_password")" = "$V1" ] && [ "$(wc -c <"$D/pg_password")" -eq 40 ] && ok "stdin: the file holds the value without its newline" || not_ok "stdin: the file holds the value without its newline"
[ "$(mode "$D/pg_password")" = 444 ] && [ "$(mode "$D")" = 700 ] && ok "stdin: file 0444, directory 0700" || not_ok "stdin: file 0444, directory 0700 ($(mode "$D/pg_password") $(mode "$D"))"
grep -q 'pg_password.*written' <<<"$OUT" && ok "stdin: the output names the secret and the action" || not_ok "stdin: the output names the secret and the action" "$OUT"
[ "$(ls -A "$D")" = pg_password ] && ok "stdin: no temporary file is left in the directory" || not_ok "stdin: no temporary file is left in the directory"

V2="$(rand 30)"
run_set "$D" "$V2" elastic_password
[ "$(wc -c <"$D/elastic_password")" -eq 30 ] && ok "stdin: a value without a newline is stored as is" || not_ok "stdin: a value without a newline is stored as is"

# --- existing files
run_set "$D" "$V1" pg_password
grep -q 'kept' <<<"$OUT" && [ "$RC" -eq 0 ] && ok "existing: an identical value is kept" || not_ok "existing: an identical value is kept" "$OUT"
V3="$(rand 40)"
run_set "$D" "$V3" pg_password
expect "existing: a differing value is refused" nonzero "$V3"
[ "$(cat "$D/pg_password")" = "$V1" ] && ok "existing: the refused file is untouched" || not_ok "existing: the refused file is untouched"
grep -q -- '--force\|FORCE' <<<"$OUT" && ok "existing: the refusal says how to force" || not_ok "existing: the refusal says how to force" "$OUT"
run_set "$D" "$V3" --force pg_password
expect "force: a differing value is replaced" zero "$V3"
[ "$(cat "$D/pg_password")" = "$V3" ] && [ "$(mode "$D/pg_password")" = 444 ] && grep -q replaced <<<"$OUT" && ok "force: the file holds the new value and says replaced" || not_ok "force: the file holds the new value and says replaced" "$OUT"

# --- refusals
run_set "$D" "$(rand 20)" bogus_password
expect "name: a name outside the list is refused" nonzero
[ ! -e "$D/bogus_password" ] && ok "name: nothing is written for it" || not_ok "name: nothing is written for it"
run_set "$D" "$(rand 20)" ../escape
expect "name: a path is refused" nonzero
[ ! -e "$TMP/escape" ] && ok "name: nothing is written outside the directory" || not_ok "name: nothing is written outside the directory"
run_set "$D" "" admin_password
expect "empty: an empty value is refused" nonzero
[ ! -e "$D/admin_password" ] && ok "empty: no file is created" || not_ok "empty: no file is created"
run_set "$D" $'\n' admin_password
expect "empty: a lone newline is refused" nonzero
run_set "$D" "" email_password
expect "empty: email_password may be empty" zero
[ -e "$D/email_password" ] && [ ! -s "$D/email_password" ] && ok "empty: email_password is an empty file" || not_ok "empty: email_password is an empty file"
run_set "$D" $'first\nsecond\n' admin_password
expect "multiline: two lines are refused" nonzero "second"
[ ! -e "$D/admin_password" ] && ok "multiline: no file is created" || not_ok "multiline: no file is created"
OUT="$(bash "$SET" --dir "$D" --names "$NAMES" </dev/null 2>&1)"
RC=$?
expect "usage: no name is refused" nonzero

# --- a value with spaces, quotes and a dollar sign is kept byte for byte
D2="$TMP/s2"
ODD="a b'c\"d\$e\\f*g"
run_set "$D2" "$ODD" admin_password
[ "$(cat "$D2/admin_password")" = "$ODD" ] && ok "odd: spaces, quotes, dollar, backslash and star are kept" || not_ok "odd: spaces, quotes, dollar, backslash and star are kept"

# --- the value leaks nowhere
LEAKS=0
for v in "$V1" "$V2" "$V3"; do
  grep -qF -- "$v" "$ARGV_LOG" && LEAKS=1 && echo "# a value is in an argv"
  grep -rqF -- "$v" "$TMP/tmpdir" && LEAKS=1 && echo "# a value is in TMPDIR"
done
[ "$LEAKS" = 0 ] && ok "no-leak: no value in an argv or in TMPDIR" || not_ok "no-leak: no value in an argv or in TMPDIR"
[ -s "$ARGV_LOG" ] && ok "no-leak: the shims did record calls (the check is live)" || not_ok "no-leak: the shims did record calls (the check is live)"
[ -z "$(ls -A "$TMP/tmpdir")" ] && ok "no-leak: TMPDIR is empty" || not_ok "no-leak: TMPDIR is empty"

# --- terminal path: a pty from script(1), the value typed twice after the prompt
if command -v script >/dev/null 2>&1 && script --version 2>&1 | grep -q util-linux; then
  D3="$TMP/s3"
  VT="$(rand 24)"
  type_value() { # type_value FIRST SECOND ARGS...: sets RC and OUT (what the terminal showed)
    local first="$1" second="$2"
    shift 2
    OUT="$({ sleep 1; printf '%s\n' "$first"; sleep 1; printf '%s\n' "$second"; sleep 1; } |
      script -qec "bash $SET --dir $D3 --names '$NAMES' $*" /dev/null 2>&1)"
    RC=$?
  }
  type_value "$VT" "$VT" pg_password
  expect "terminal: the value typed twice is written" zero "$VT"
  [ "$(cat "$D3/pg_password" 2>/dev/null)" = "$VT" ] && ok "terminal: the file holds the typed value" || not_ok "terminal: the file holds the typed value" "$OUT"
  VM="$(rand 24)"
  type_value "$VM" "$(rand 24)" --force pg_password
  expect "terminal: two different entries are refused" nonzero "$VM"
  [ "$(cat "$D3/pg_password")" = "$VT" ] && ok "terminal: the file is untouched after a mismatch" || not_ok "terminal: the file is untouched after a mismatch"
  VS="  $(rand 12)  "
  type_value "$VS" "$VS" --force pg_password
  expect "terminal: a value with leading and trailing spaces is written" zero
  [ "$(cat "$D3/pg_password"; printf x)" = "${VS}x" ] && ok "terminal: the spaces are kept byte for byte" || not_ok "terminal: the spaces are kept byte for byte" "$(od -c "$D3/pg_password" | head -3)"
else
  echo "ok - terminal: skipped, script(1) from util-linux missing (stdin path only)"
fi

# --- secrets-check
C="$TMP/c1"
install -d -m 0700 "$C"
put() { # put NAME VALUE [MODE]
  rm -f "$C/$1"
  printf '%s' "$2" >"$C/$1"
  chmod "${3:-444}" "$C/$1"
}
run_check() {
  OUT="$(bash "$CHECK" --dir "$C" --names "$NAMES" 2>&1)"
  RC=$?
}
KEY="$(rand 64)"
ADM="$(rand 24)"
PGV="$(rand 40)"
ESV="$(rand 40)"
put pg_password "$PGV"
put elastic_password "$ESV"
put django_secret_key "$KEY"
put email_password ""
put admin_password "$ADM"
run_check
expect "check-ok: a complete directory passes" zero
for v in "$KEY" "$ADM" "$PGV" "$ESV"; do
  grep -qF -- "$v" <<<"$OUT" && { not_ok "check-ok: a value reached the output"; break; }
done
[ "$(grep -v '^directory' <<<"$OUT" | grep -c ': ok')" -eq 5 ] && ok "check-ok: one ok line per name" || not_ok "check-ok: one ok line per name" "$OUT"

rm "$C/pg_password"
run_check
expect "check-missing: a missing file fails" nonzero
grep -q 'pg_password.*missing' <<<"$OUT" && ok "check-missing: the line says missing" || not_ok "check-missing: the line says missing" "$OUT"
put pg_password "$PGV" 600
run_check
expect "check-mode: a file that is not 0444 fails" nonzero "$PGV"
grep -q 'pg_password.*600' <<<"$OUT" && ok "check-mode: the line gives the mode" || not_ok "check-mode: the line gives the mode" "$OUT"
put pg_password "$PGV"$'\n'
run_check
expect "check-newline: a trailing newline fails" nonzero "$PGV"
grep -q 'pg_password.*newline' <<<"$OUT" && ok "check-newline: the line says newline" || not_ok "check-newline: the line says newline" "$OUT"
put pg_password ""
run_check
expect "check-empty: an empty secret fails" nonzero
put pg_password "$PGV"
put django_secret_key "$(rand 49)"
run_check
expect "check-key: a short Django key fails" nonzero
grep -q 'django_secret_key.*50' <<<"$OUT" && ok "check-key: the line gives the minimum" || not_ok "check-key: the line gives the minimum" "$OUT"
put django_secret_key "$KEY"
put admin_password "$(rand 15)"
run_check
expect "check-admin: a short admin password fails" nonzero
grep -q 'admin_password.*16' <<<"$OUT" && ok "check-admin: the line gives the minimum" || not_ok "check-admin: the line gives the minimum" "$OUT"
put admin_password "$ADM"
chmod 755 "$C"
run_check
expect "check-dir: a directory that is not 0700 fails" nonzero
chmod 700 "$C"
run_check
expect "check-recovered: fixing everything passes again" zero
OUT="$(bash "$CHECK" --dir "$TMP/nowhere" --names "$NAMES" 2>&1)"
RC=$?
expect "check-nodir: a missing directory fails" nonzero

# --- Make targets
if command -v make >/dev/null 2>&1; then
  OUT="$(make -C "$HERE/../.." secret-set 2>&1 </dev/null)"
  RC=$?
  expect "make: secret-set without NAME fails" nonzero
  grep -q 'NAME' <<<"$OUT" && ok "make: the message names NAME" || not_ok "make: the message names NAME" "$OUT"
  VM2="$(rand 30)"
  OUT="$(printf '%s' "$VM2" | make -C "$HERE/../.." secret-set NAME=pg_password SECRETS_DIR="$TMP/m1" 2>&1)"
  RC=$?
  expect "make: secret-set NAME=pg_password writes through stdin" zero "$VM2"
  [ "$(cat "$TMP/m1/pg_password")" = "$VM2" ] && ok "make: the file holds the value" || not_ok "make: the file holds the value" "$OUT"
  OUT="$(printf '%s' "$(rand 30)" | make -C "$HERE/../.." secret-set NAME=pg_password SECRETS_DIR="$TMP/m1" 2>&1)"
  RC=$?
  expect "make: a differing value is refused without FORCE" nonzero
  VM3="$(rand 30)"
  OUT="$(printf '%s' "$VM3" | make -C "$HERE/../.." secret-set NAME=pg_password FORCE=yes SECRETS_DIR="$TMP/m1" 2>&1)"
  RC=$?
  expect "make: FORCE=yes replaces" zero "$VM3"
  OUT="$(make -C "$HERE/../.." secrets-check SECRETS_DIR="$TMP/m1" 2>&1)"
  RC=$?
  expect "make: secrets-check reports the other names missing" nonzero
else
  echo "ok - make: skipped, make missing"
fi

echo "1..$N"
exit "$FAILED"
