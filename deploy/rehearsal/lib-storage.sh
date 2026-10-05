#!/usr/bin/env bash
# Sourced by make-vm.sh and host-nfs.sh: checks a host directory chosen in
# rehearsal.env (IMAGES_DIR, NFS_EXPORT_DIR) before anything is created there.

# valid_storage_path NAME VALUE
# An absolute path of plain characters: it ends up in /etc/exports and in XML.
valid_storage_path() {
  if ! [[ "$2" =~ ^/[A-Za-z0-9._/@+-]*$ ]] || [[ "$2" == *..* ]]; then
    echo "Invalid $1: \"$2\" (expected an absolute path of letters, digits and . _ / @ + -)." >&2
    return 1
  fi
}

# check_storage_dir KIND DIR [QEMU_USER]
# KIND is "images" (the hypervisor user, QEMU_USER, must traverse every parent
# and read/write DIR) or "nfs" (exported by root, no ACL needed). Checks the
# nearest existing ancestor when DIR does not exist yet.
# Returns 0 (fine, possibly with warnings), 1 (unusable filesystem) or 2 (a
# fix is needed: the exact commands are printed).
check_storage_dir() {
  local kind="$1" dir="$2" qemu_user="${3:-}" probe fs mp rc=0 p
  probe="$dir"
  while [ ! -e "$probe" ] && [ "$probe" != / ]; do probe="$(dirname "$probe")"; done

  fs="$(stat -f -c %T "$probe" 2>/dev/null || true)"
  [ -n "$fs" ] || fs="$(findmnt -no FSTYPE -T "$probe" 2>/dev/null || true)"
  case "$fs" in
    msdos | vfat | fat | exfat | ntfs | ntfs3)
      echo "${dir} is on a ${fs} filesystem: no Unix ownership, permissions or ACLs. Use a Linux filesystem (ext4, xfs, btrfs)." >&2
      return 1
      ;;
    fuseblk)
      echo "Warning: ${dir} is on a fuseblk filesystem (NTFS or exFAT through FUSE): permissions and ACLs are unreliable, and NFS cannot export it without an fsid. A Linux filesystem is safer." >&2
      ;;
  esac

  mp="$(findmnt -no TARGET -T "$probe" 2>/dev/null || true)"
  if [ -n "$mp" ] && [ "$mp" != / ] && [ -z "$(findmnt --fstab -n -o TARGET "$mp" 2>/dev/null || true)" ]; then
    echo "Warning: ${mp} is mounted but not listed in /etc/fstab. A desktop automount (/media/<user>/<label>) appears only after a login: after a reboot the host would not find ${dir} until someone logs in." >&2
    echo "  To mount it at boot, add to /etc/fstab (then \"sudo mount -a\"):" >&2
    echo "  UUID=$(findmnt -no UUID -T "$probe" 2>/dev/null || echo '<uuid>')  ${mp}  $(findmnt -no FSTYPE -T "$probe" 2>/dev/null || echo ext4)  defaults,nofail,x-systemd.device-timeout=10s  0  2" >&2
    if [ "$kind" = nfs ]; then
      echo "  Exporting a removable automount is fragile: the export fails whenever the disk is absent." >&2
    fi
  fi

  [ "$kind" = images ] || return 0

  if [ ! -d "$dir" ]; then
    echo "${dir} does not exist. Create it: sudo install -d -m 0755 ${dir}" >&2
    return 2
  fi
  local no_x=()
  p="$dir"
  while [ "$p" != / ]; do
    p="$(dirname "$p")"
    sudo -u "$qemu_user" test -x "$p" 2>/dev/null || no_x+=("$p")
  done
  if [ "${#no_x[@]}" -gt 0 ] || ! sudo -u "$qemu_user" test -x "$dir" 2>/dev/null \
    || ! sudo -u "$qemu_user" test -w "$dir" 2>/dev/null; then
    echo "User ${qemu_user} cannot use ${dir} (it must traverse every parent and read/write the directory). Fix:" >&2
    for p in "${no_x[@]}"; do echo "  sudo setfacl -m u:${qemu_user}:x ${p}" >&2; done
    echo "  sudo setfacl -m u:${qemu_user}:rwx ${dir}" >&2
    rc=2
  fi
  return "$rc"
}
