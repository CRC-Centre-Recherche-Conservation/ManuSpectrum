#!/usr/bin/env bash
# Tests that the rehearsal host marker has one path in the script that creates
# it (host-baseline.sh and the Ansible baseline role), the one that checks it
# (the Ansible baseline verification) and the one that requires it (load-snapshot.sh). Prints `ok N` / `not ok N`; exits
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

ROLE="$KIT/../ansible/roles/baseline/tasks"
grep -q "$MARKER" "$ROLE/verify.yml" && grep -q "pw_name == 'root'" "$ROLE/verify.yml" && grep -q "mode == '0644'" "$ROLE/verify.yml"
assert "the Ansible baseline verification checks the marker, root-owned 0644" $?
grep -q "$MARKER" "$ROLE/apply.yml"
assert "the Ansible baseline apply writes the marker" $?

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

# Every task that touches the marker or its directory carries the guard, in both files.
guarded() { # guarded FILE EXPECTED: tasks naming /etc/manuspectrum and `when: rehearsal_host | bool` count the same
  python3 - "$1" "$2" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
tasks = re.split(r"(?m)^(?=- name: )", text)
touching = [t for t in tasks if "/etc/manuspectrum" in t]
guarded = [t for t in touching if re.search(r"(?m)^  when: rehearsal_host \| bool$", t)]
sys.exit(0 if len(touching) == int(sys.argv[2]) and len(guarded) == len(touching) else 1)
PY
}
guarded "$ROLE/apply.yml" 2
assert "every apply task touching /etc/manuspectrum is guarded by rehearsal_host (the directory and the marker)" $?
guarded "$ROLE/verify.yml" 2
assert "every verify task touching /etc/manuspectrum is guarded by rehearsal_host (the look and the assertion)" $?

exit "$failed"
