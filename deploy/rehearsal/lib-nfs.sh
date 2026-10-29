#!/usr/bin/env bash
# NFS server settings shared by host-nfs.sh and its tests (sourced, not run).
# The production NFS server honours the client's supplementary groups; the
# rehearsal server must too, so mountd must not resolve groups itself
# (`manage-gids`, the default of Ubuntu's nfs-kernel-server).

# Sets `manage-gids=n` in the [mountd] section of FILE (created, with the
# section or the key, when absent; every other line is kept). Echoes
# "changed" or "unchanged".
nfs_conf_manage_gids_off() {
  local file="$1" tmp
  tmp="$(mktemp)"
  [ ! -f "$file" ] || cp -- "$file" "$tmp"
  awk '
    function flush() { if (in_mountd && !done) { print "manage-gids=n"; done = 1 } }
    /^[[:space:]]*\[[^]]*\]/ {
      flush()
      in_mountd = ($0 ~ /^[[:space:]]*\[mountd\]/)
      if (in_mountd) seen = 1
      print; next
    }
    in_mountd && /^[[:space:]]*manage-gids[[:space:]]*=/ {
      if (!done) { print "manage-gids=n"; done = 1 }
      next
    }
    { print }
    END {
      flush()
      if (!seen) { if (NR > 0) print ""; print "[mountd]"; print "manage-gids=n" }
    }
  ' "$tmp" >"$tmp.new"
  if [ -f "$file" ] && cmp -s "$file" "$tmp.new"; then
    echo unchanged
  else
    cat "$tmp.new" >"$file"
    echo changed
  fi
  rm -f "$tmp" "$tmp.new"
}

# Removes `--manage-gids` (or `-g`) from RPCMOUNTDOPTS in FILE when present.
# Echoes "changed" or "unchanged"; a missing file is unchanged.
nfs_defaults_manage_gids_off() {
  local file="$1" tmp
  [ -f "$file" ] || { echo unchanged; return 0; }
  tmp="$(mktemp)"
  sed -E '/^[[:space:]]*RPCMOUNTDOPTS=/{
    s/(["= ])(--manage-gids|-g)([ "]|$)/\1\3/g
    s/(["= ])(--manage-gids|-g)([ "]|$)/\1\3/g
    s/[[:space:]]+"/"/
  }' "$file" >"$tmp"
  if cmp -s "$file" "$tmp"; then
    echo unchanged
  else
    cat "$tmp" >"$file"
    echo changed
  fi
  rm -f "$tmp"
}
