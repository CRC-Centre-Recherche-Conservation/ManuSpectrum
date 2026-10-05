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

grep -q "MS_REHEARSAL_MARKER:-$MARKER" "$KIT/../scripts/load-snapshot.sh"
assert "load-snapshot.sh requires the same path by default" $?

exit "$failed"
