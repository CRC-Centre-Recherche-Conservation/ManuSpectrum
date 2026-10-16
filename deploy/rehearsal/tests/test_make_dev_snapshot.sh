#!/usr/bin/env bash
# Tests for make-dev-snapshot.sh. `python` answers manage.py with a fixed
# settings line and delegates everything else to python3; pg_dump and git are
# stubs. Prints `ok N` / `not ok N`; exits non-zero on failure.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SNAP="$HERE/../make-dev-snapshot.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

SECRET='s3cr3t-pa55w0rd-do-not-print'
mkdir -p "$TMP/bin" "$TMP/repo" "$TMP/media/uploadedfiles"
touch "$TMP/repo/manage.py"
echo data >"$TMP/media/uploadedfiles/a.txt"

cat >"$TMP/bin/python" <<STUB
#!/bin/sh
if [ "\$1" = - ] && [ -n "\$ENVDUMP" ]; then env >"\$ENVDUMP"; fi
if [ "\$1" = manage.py ]; then
  echo "noise from django"
  echo 'MSSNAP {"host": "localhost", "port": "5432", "name": "ms", "user": "u", "password": "$SECRET", "media_root": "$TMP/media", "uploads": "uploadedfiles", "arches": "8.1.4", "resources": 5, "tiles": 12, "migrations": {"arches": "0001", "manuspectrum": "0005"}}'
  exit 0
fi
exec python3 "\$@"
STUB
cat >"$TMP/bin/pg_dump" <<'STUB'
#!/bin/sh
if [ "$1" = --version ]; then echo "pg_dump (PostgreSQL) 17.0"; exit 0; fi
echo "pg_dump $* PGPASSWORD=${PGPASSWORD:+set}" >>"$CALLS"
while [ $# -gt 0 ]; do [ "$1" = --file ] && printf DUMP >"$2"; shift; done
STUB
cat >"$TMP/bin/git" <<'STUB'
#!/bin/sh
case "$*" in *abbrev-ref*) echo test-branch ;; *) echo 0123abc ;; esac
STUB
chmod +x "$TMP/bin/python" "$TMP/bin/pg_dump" "$TMP/bin/git"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

run_snap() { env PATH="$TMP/bin:$PATH" CALLS="$TMP/calls" ENVDUMP="$TMP/pyenv" bash "$SNAP" --python "$TMP/bin/python" --repo "$TMP/repo" "$@" >"$TMP/out" 2>&1; }

mkdir -p "$TMP/busy"
echo x >"$TMP/busy/file"
run_snap --out "$TMP/busy" && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q "not empty" "$TMP/out" && [ "$(ls "$TMP/busy")" = file ]
assert "refuses a non-empty out directory and leaves it alone" $?

: >"$TMP/calls"
run_snap --out "$TMP/snap" && status=0 || status=$?
assert "nominal run exits 0" "$status"

! grep -qF "$SECRET" "$TMP/out" && ! grep -rqF "$SECRET" "$TMP/snap" "$TMP/calls"
assert "the password is never printed, written or put on a command line" $?

[ -s "$TMP/pyenv" ] && ! grep -qF "$SECRET" "$TMP/pyenv" && ! grep -q '^PGPASSWORD=' "$TMP/pyenv"
assert "the password is in no later child's environment (the manifest writer sees none)" $?

grep -q 'PGPASSWORD=set' "$TMP/calls" && grep -q -- "--exclude-table=silk_\*" "$TMP/calls" \
  && grep -q -- "-Fc --no-owner --no-privileges" "$TMP/calls"
assert "pg_dump gets the password by environment and the expected flags" $?

[ "$(stat -c %a "$TMP/snap")" = 700 ] && [ "$(stat -c %a "$TMP/snap/db.dump")" = 600 ] \
  && [ "$(stat -c %a "$TMP/snap/media.tar")" = 600 ] && [ "$(stat -c %a "$TMP/snap/manifest.json")" = 600 ]
assert "directory 0700, files 0600" $?

tar -tf "$TMP/snap/media.tar" | grep -qx 'uploadedfiles/a.txt'
assert "media.tar holds relative uploadedfiles/ paths" $?

python3 - "$TMP/snap/manifest.json" <<'PY'
import hashlib, json, os, sys
m = json.load(open(sys.argv[1]))
d = os.path.dirname(sys.argv[1])
assert m["created_at"].endswith("Z")
assert m["git"] == {"commit": "0123abc", "branch": "test-branch"}
assert m["arches_version"] == "8.1.4"
assert "17.0" in m["pg_dump_version"]
assert m["counts"] == {"resource_instances": 5, "tiles": 12}
assert m["migrations"]["manuspectrum"] == "0005"
for name in ("db.dump", "media.tar"):
    data = open(os.path.join(d, name), "rb").read()
    assert m["files"][name]["sha256"] == hashlib.sha256(data).hexdigest()
    assert m["files"][name]["bytes"] == len(data)
PY
assert "manifest keys and checksums are right" $?

grep -q 'scp -r' "$TMP/out" && grep -qi 'user accounts and research data' "$TMP/out" && grep -q 'Never put it' "$TMP/out"
assert "final message gives the copy command and the data warning" $?

bash "$SNAP" -h | grep -q -- '--out DIR'
assert "-h prints the usage" $?

exit "$failed"
