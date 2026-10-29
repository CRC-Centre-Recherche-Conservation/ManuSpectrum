#!/usr/bin/env bash
# Tests for the manage-gids editing of lib-nfs.sh, on temporary copies of
# /etc/nfs.conf and /etc/default/nfs-kernel-server (no root needed). Prints
# `ok N` / `not ok N`; exits non-zero on failure.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# shellcheck disable=SC1091
. "$HERE/../lib-nfs.sh"

n=0 failed=0
assert() {
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}
mountd_has_n() { awk '/^\[/ {s=$0} s=="[mountd]" && /^manage-gids=n$/ {f=1} END {exit !f}' "$1"; }

printf '[general]\npid-file=/x\n\n[mountd]\nmanage-gids=y\nport=1\n\n[nfsd]\nthreads=8\n' >"$TMP/a.conf"
[ "$(nfs_conf_manage_gids_off "$TMP/a.conf")" = changed ] && mountd_has_n "$TMP/a.conf" \
  && ! grep -q 'manage-gids=y' "$TMP/a.conf" && grep -q '^port=1$' "$TMP/a.conf" && grep -q '^threads=8$' "$TMP/a.conf"
assert "manage-gids=y becomes n, other keys and sections kept" $?

cp "$TMP/a.conf" "$TMP/a.before"
[ "$(nfs_conf_manage_gids_off "$TMP/a.conf")" = unchanged ] && cmp -s "$TMP/a.conf" "$TMP/a.before"
assert "a second run changes nothing" $?

printf '[mountd]\n# manage-gids=y\nport=1\n[nfsd]\nthreads=8\n' >"$TMP/b.conf"
[ "$(nfs_conf_manage_gids_off "$TMP/b.conf")" = changed ] && mountd_has_n "$TMP/b.conf" \
  && grep -q '^# manage-gids=y$' "$TMP/b.conf" && [ "$(grep -c '^manage-gids=n$' "$TMP/b.conf")" -eq 1 ]
assert "a missing key is added inside [mountd] only (a comment is not the key)" $?

printf '[general]\npid-file=/x\n' >"$TMP/c.conf"
[ "$(nfs_conf_manage_gids_off "$TMP/c.conf")" = changed ] && mountd_has_n "$TMP/c.conf" && grep -q '^pid-file=/x$' "$TMP/c.conf"
assert "a missing [mountd] section is appended" $?

[ "$(nfs_conf_manage_gids_off "$TMP/new.conf")" = changed ] && mountd_has_n "$TMP/new.conf"
assert "a missing file is created" $?

printf '[nfsd]\nmanage-gids=y\n[mountd]\nmanage-gids = y\n' >"$TMP/d.conf"
nfs_conf_manage_gids_off "$TMP/d.conf" >/dev/null
mountd_has_n "$TMP/d.conf" && grep -q '^\[nfsd\]$' "$TMP/d.conf" && awk '/^\[nfsd\]/ {s=1} s && /^manage-gids=y$/ {f=1} END {exit !f}' "$TMP/d.conf"
assert "only the [mountd] key is edited, a spaced assignment included" $?

printf 'RPCNFSDCOUNT=8\nRPCMOUNTDOPTS="--manage-gids"\n' >"$TMP/e"
[ "$(nfs_defaults_manage_gids_off "$TMP/e")" = changed ] && grep -qx 'RPCMOUNTDOPTS=""' "$TMP/e" && grep -qx 'RPCNFSDCOUNT=8' "$TMP/e"
assert "--manage-gids alone is removed from RPCMOUNTDOPTS" $?

printf 'RPCMOUNTDOPTS="--port 4002 --manage-gids"\n' >"$TMP/f"
nfs_defaults_manage_gids_off "$TMP/f" >/dev/null
grep -qx 'RPCMOUNTDOPTS="--port 4002"' "$TMP/f"
assert "--manage-gids is removed next to other options" $?

printf 'RPCMOUNTDOPTS="-g"\n' >"$TMP/g"
nfs_defaults_manage_gids_off "$TMP/g" >/dev/null
grep -qx 'RPCMOUNTDOPTS=""' "$TMP/g"
assert "the short form -g is removed too" $?

[ "$(nfs_defaults_manage_gids_off "$TMP/f")" = unchanged ] && [ "$(nfs_defaults_manage_gids_off "$TMP/absent")" = unchanged ]
assert "defaults: already clean or absent file is unchanged" $?

exit "$failed"
