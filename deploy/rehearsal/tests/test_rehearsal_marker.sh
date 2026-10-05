#!/usr/bin/env bash
# Tests that the rehearsal host marker has one path in the script that creates
# it (host-baseline.sh), the one that checks it (verify-baseline.sh) and the
# one that requires it (load-snapshot.sh). Prints `ok N` / `not ok N`; exits
# non-zero on failure.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$HERE/.."
MARKER=/etc/manuspectrum/rehearsal-host

n=0 failed=0
assert() {
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

grep -q "write_file $MARKER" "$KIT/host-baseline.sh"
assert "host-baseline.sh writes the marker" $?

grep -q "$MARKER" "$KIT/verify-baseline.sh" && grep -q 'root:644' "$KIT/verify-baseline.sh"
assert "verify-baseline.sh checks the marker, root-owned 0644" $?

grep -q "^REHEARSAL_MARKER=$MARKER\$" "$KIT/../scripts/load-snapshot.sh"
assert "load-snapshot.sh requires the same path by default" $?

# The marker block of host-baseline.sh, run with a stub write_file.
block="$(sed -n '/^echo "== Rehearsal host marker"/,/^echo "== Automatic updates"/p' "$KIT/host-baseline.sh" | sed '$d')"
run_block() { # run_block REHEARSAL_HOST-VALUE
  REHEARSAL_HOST="$1" bash -c 'write_file() { echo "WROTE $1"; cat >/dev/null; }; '"$block" 2>&1
}
out="$(run_block yes)"
grep -q "WROTE $MARKER" <<<"$out"
assert "host-baseline.sh writes the marker when REHEARSAL_HOST=yes" $?
for value in no ""; do
  out="$(run_block "$value")"
  ! grep -q WROTE <<<"$out" && grep -q "No marker written" <<<"$out"
  assert "host-baseline.sh writes no marker and says so when REHEARSAL_HOST='$value'" $?
done

grep -q '^REHEARSAL_HOST=yes$' "$KIT/rehearsal.env.example" && grep -q 'Never set on a production host' "$KIT/rehearsal.env.example"
assert "rehearsal.env.example sets REHEARSAL_HOST=yes with the production warning" $?

check_marker_line() { # check_marker_line REHEARSAL_HOST-VALUE: runs the gated block of verify-baseline.sh
  local vblock
  # shellcheck disable=SC2016
  vblock="$(sed -n '/^if \[ "\${REHEARSAL_HOST:-no}" = yes \]/,/^fi$/p' "$KIT/verify-baseline.sh")"
  REHEARSAL_HOST="$1" bash -c 'check() { echo "CHECK $1"; }; '"$vblock" 2>&1
}
check_marker_line yes | grep -q "CHECK rehearsal host marker"
assert "verify-baseline.sh checks the marker when REHEARSAL_HOST=yes" $?
out="$(check_marker_line no)"
! grep -q CHECK <<<"$out" && grep -q "not checked" <<<"$out"
assert "verify-baseline.sh does not check the marker otherwise" $?

exit "$failed"
