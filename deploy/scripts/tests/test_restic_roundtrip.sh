#!/usr/bin/env bash
# deploy/scripts/tests/test_restic_roundtrip.sh
# Runs the pinned restic image (read from compose.yaml) the way the restic
# service runs it (no network, read-only root, tmpfs /tmp, non-root user,
# HOME=/tmp, password file) against a fixture tree laid out like /backup, with
# the excludes and the retention of lib-backup.sh. No database. Prints
# `ok N` / `not ok N`; exits non-zero on failure.
# $? after a negated or compound test is the point of every assertion below.
# shellcheck disable=SC2319
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_YAML="$HERE/../../compose/compose.yaml"
# shellcheck source=../lib-backup.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/../lib-backup.sh"

IMAGE="$(sed -n 's/^ *image: \(restic\/restic:[^ ]*\)$/\1/p' "$COMPOSE_YAML")"
[ -n "$IMAGE" ] || { echo "no restic image in compose.yaml" >&2; exit 1; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || docker pull -q "$IMAGE" >/dev/null || { echo "cannot pull $IMAGE" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/repo" "$TMP/out" "$TMP/src/db" "$TMP/src/media/uploadedfiles" "$TMP/src/media/archestemp" \
  "$TMP/src/media/export_deliverables" "$TMP/src/media/previous-1-abc" "$TMP/src/media/.restore-1" \
  "$TMP/src/secrets/aside"
printf 'dump-bytes' >"$TMP/src/db/db.dump"
printf '{"kind": "backup"}' >"$TMP/src/db/manifest.json"
printf 'upload' >"$TMP/src/media/uploadedfiles/u.txt"
printf 'x' >"$TMP/src/media/archestemp/t.tmp"
printf 'x' >"$TMP/src/media/export_deliverables/e.zip"
printf 'x' >"$TMP/src/media/previous-1-abc/old.txt"
printf 'x' >"$TMP/src/media/.restore-1/staged.txt"
printf 'x' >"$TMP/src/secrets/aside/old_secret"
printf 'x' >"$TMP/src/secrets/pg_password.new"
printf 'secret' >"$TMP/src/secrets/pg_password"
head -c 36 /dev/urandom | base64 | tr -d '\n=+/' >"$TMP/pw"
head -c 36 /dev/urandom | base64 | tr -d '\n=+/' >"$TMP/pw-wrong"
chmod 0644 "$TMP/pw" "$TMP/pw-wrong"

restic() { # restic PASSWORD-FILE ARGS...: one run of the image as the restic service runs it
  local pw="$1"
  shift
  docker run --rm --network none --read-only --user "$(id -u):$(id -g)" \
    --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev,size=64m,mode=1777 \
    -e HOME=/tmp -e RESTIC_REPOSITORY=/repo -e RESTIC_PASSWORD_FILE=/pw -e RESTIC_HOST=manuspectrum \
    -v "$TMP/repo:/repo" -v "$pw:/pw:ro" -v "$TMP/src:/backup:ro" -v "$TMP/out:/out" \
    "$IMAGE" --no-cache "$@"
}

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

exclude_args=()
for pattern in "${RESTIC_EXCLUDES[@]}"; do exclude_args+=(--exclude "$pattern"); done

restic "$TMP/pw" init >/dev/null 2>&1
assert "init creates the repository as an arbitrary non-root user on a read-only root" $?

backup() { restic "$TMP/pw" backup --tag nightly --time "$1" "${exclude_args[@]}" /backup >/dev/null 2>&1; }
backup "2026-03-01 02:00:00"
assert "backup of the fixture tree with the script's excludes" $?

restic "$TMP/pw" snapshots --json 2>/dev/null | python3 -c '
import json
import sys

snaps = json.load(sys.stdin)
assert len(snaps) == 1, snaps
assert snaps[0]["hostname"] == "manuspectrum", snaps[0]["hostname"]
assert snaps[0]["tags"] == ["nightly"], snaps[0]["tags"]
'
assert "snapshot carries the fixed host manuspectrum and the tag" $?

listing="$(restic "$TMP/pw" ls latest --recursive 2>/dev/null)"
grep -q '/backup/db/db.dump$' <<<"$listing" && grep -q '/backup/media/uploadedfiles/u.txt$' <<<"$listing" \
  && grep -q '/backup/secrets/pg_password$' <<<"$listing" \
  && ! grep -qE 'previous-1-abc|\.restore-1|archestemp|export_deliverables|pg_password\.new|secrets/aside' <<<"$listing"
assert "ls latest holds db, uploads and secrets and none of the excluded paths" $?

backup "2026-03-02 02:00:00"
backup "2026-03-02 03:00:00"
restic "$TMP/pw" forget --keep-daily "$RETENTION_KEEP_DAILY" --keep-weekly "$RETENTION_KEEP_WEEKLY" \
  --keep-monthly "$RETENTION_KEEP_MONTHLY" --prune >/dev/null 2>&1 \
  && [ "$(restic "$TMP/pw" snapshots --json 2>/dev/null | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')" = 2 ]
assert "forget with the retention constants keeps one snapshot per day (3 snapshots over 2 days leave 2)" $?

restic "$TMP/pw" check --read-data-subset=10% >/dev/null 2>&1
assert "check --read-data-subset=10% exits 0" $?

restic "$TMP/pw" restore latest --target /out --include /backup/db --verify >/dev/null 2>&1 \
  && cmp "$TMP/src/db/db.dump" "$TMP/out/backup/db/db.dump" && cmp "$TMP/src/db/manifest.json" "$TMP/out/backup/db/manifest.json" \
  && [ ! -e "$TMP/out/backup/media" ]
assert "restore --include /backup/db --verify gives byte-identical files and nothing else" $?

[ "$(stat -c %u "$TMP/out/backup/db/db.dump")" = "$(id -u)" ]
assert "restored files are owned by the run uid" $?

! restic "$TMP/pw-wrong" snapshots >/dev/null 2>&1
assert "a wrong password is refused" $?

exit "$failed"
