#!/usr/bin/env bash
# Sourced by make-vm.sh and host-nfs.sh: checks a host directory chosen in
# rehearsal.env (IMAGES_DIR, NFS_EXPORT_DIR) before anything is created there.

# valid_storage_path NAME VALUE
# An absolute path of plain characters: it ends up in /etc/exports and in XML.
# A system directory itself (/, /etc, /usr, /var, /home, /root, /boot, /srv) is
# refused; its sub-directories are allowed.
valid_storage_path() {
  local trimmed="$2"
  while [ "${#trimmed}" -gt 1 ] && [ "${trimmed%/}" != "$trimmed" ]; do trimmed="${trimmed%/}"; done
  if ! [[ "$2" =~ ^/[A-Za-z0-9._/@+-]*$ ]] || [[ "$2" == *..* ]]; then
    echo "Invalid $1: \"$2\" (expected an absolute path of letters, digits and . _ / @ + -)." >&2
    return 1
  fi
  case "$trimmed" in
    / | /etc | /usr | /var | /home | /root | /boot | /srv)
      echo "Invalid $1: \"$2\" is a system directory; use a sub-directory (for example $trimmed/ms-rehearsal)." >&2
      return 1
      ;;
  esac
}

# check_storage_dir KIND DIR [QEMU_USER]
# KIND is "images" (the hypervisor user, QEMU_USER, must traverse every parent
# and read/write DIR) or "nfs" (exported by root, no ACL needed). Checks the
# nearest existing ancestor when DIR does not exist yet.
# A non-Unix filesystem (vfat, exfat, ntfs, fuseblk over ntfs/exfat) is refused
# for "nfs" and only warned about for "images". Returns 0 (fine, possibly with
# warnings), 1 (unusable filesystem) or 2 (a fix is needed: printed).
check_storage_dir() {
  local kind="$1" dir="$2" qemu_user="${3:-}" probe fs real="" mp rc=0 p fstab_type nonunix=0
  probe="$dir"
  while [ ! -e "$probe" ] && [ "$probe" != / ]; do probe="$(dirname "$probe")"; done

  # findmnt reports the kernel's name (vfat, exfat, ntfs3, fuseblk); older
  # coreutils print UNKNOWN (0x...) for exfat, so stat is only the fallback.
  fs="$(findmnt -no FSTYPE -T "$probe" 2>/dev/null || true)"
  [ -n "$fs" ] || fs="$(stat -f -c %T "$probe" 2>/dev/null || true)"
  if [ "$fs" = fuseblk ]; then
    # FUSE hides the real type: ask the block device behind the mount.
    real="$(lsblk -no FSTYPE "$(findmnt -no SOURCE -T "$probe" 2>/dev/null)" 2>/dev/null | head -n 1 || true)"
    case "$real" in
      ntfs | exfat) fs="$real" ;;
    esac
  fi
  case "$fs" in
    msdos | vfat | fat | exfat | ntfs | ntfs3)
      if [ "$kind" = nfs ]; then
        echo "${dir} is on a ${fs} filesystem: no Unix ownership, permissions or ACLs. Use a Linux filesystem (ext4, xfs, btrfs)." >&2
        return 1
      fi
      nonunix=1
      echo "Warning: ${dir} is on a ${fs} filesystem (FUSE/ntfs-3g or non-Unix). The disk image will work, but I/O is slower, so the timings measured in" >&2
      echo "  rehearsal (reindex duration, load-snapshot duration) are not comparable to production; memory figures are unaffected." >&2
      ;;
    fuseblk)
      echo "Warning: ${dir} is on a fuseblk filesystem (FUSE; device type: ${real:-unknown}): permissions and ACLs are unreliable, and NFS cannot export it without an fsid. A Linux filesystem is safer." >&2
      ;;
  esac

  mp="$(findmnt -no TARGET -T "$probe" 2>/dev/null || true)"
  if [ -n "$mp" ] && [ "$mp" != / ] && [ -z "$(findmnt --fstab -n -o TARGET "$mp" 2>/dev/null || true)" ]; then
    echo "Warning: ${mp} is mounted but not listed in /etc/fstab. A desktop automount (/media/<user>/<label>) appears only after a login: after a reboot the host would not find ${dir} until someone logs in." >&2
    echo "  To mount it at boot, add to /etc/fstab (then \"sudo mount -a\"):" >&2
    fstab_type="$fs"
    # fstab does not take fuseblk: it names the real filesystem.
    if [ "$fs" = fuseblk ]; then fstab_type="${real:-<filesystem type>}"; fi
    echo "  UUID=$(findmnt -no UUID -T "$probe" 2>/dev/null || echo '<uuid>')  ${mp}  ${fstab_type:-ext4}  defaults,nofail,x-systemd.device-timeout=10s  0  2" >&2
    if [ "$kind" = nfs ]; then
      echo "  Exporting a removable automount is fragile: the export fails whenever the disk is absent." >&2
    fi
  fi

  [ "$kind" = images ] || return 0

  if [ ! -d "$dir" ]; then
    echo "${dir} does not exist. Create it: sudo install -d -m 0755 ${dir}" >&2
    return 2
  fi
  # One probe tells "sudo is unavailable" apart from "the user has no access".
  if ! sudo -n -u "$qemu_user" true 2>/dev/null; then
    echo "Warning: sudo needs a password or is not allowed, so whether ${qemu_user} can use ${dir} was not checked. Check by hand: sudo -u ${qemu_user} test -w ${dir}" >&2
    return 0
  fi
  local no_x=()
  p="$dir"
  while [ "$p" != / ]; do
    p="$(dirname "$p")"
    sudo -n -u "$qemu_user" test -x "$p" 2>/dev/null || no_x+=("$p")
  done
  if [ "${#no_x[@]}" -gt 0 ] || ! sudo -n -u "$qemu_user" test -x "$dir" 2>/dev/null \
    || ! sudo -n -u "$qemu_user" test -w "$dir" 2>/dev/null; then
    if [ "$nonunix" = 1 ] || [ "$fs" = fuseblk ]; then
      echo "User ${qemu_user} cannot use ${dir}. setfacl does not work on ntfs-3g: access is usually granted by mount options (uid/gid/umask, or permissions)." >&2
      echo "  Check with: sudo -u ${qemu_user} test -r <file>" >&2
    else
      echo "User ${qemu_user} cannot use ${dir} (it must traverse every parent and read/write the directory). Fix:" >&2
      for p in "${no_x[@]}"; do echo "  sudo setfacl -m u:${qemu_user}:x ${p}" >&2; done
      echo "  sudo setfacl -m u:${qemu_user}:rwx ${dir}" >&2
    fi
    rc=2
  fi
  return "$rc"
}
