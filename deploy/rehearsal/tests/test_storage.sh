#!/usr/bin/env bash
# Tests for the storage-directory settings (IMAGES_DIR, NFS_EXPORT_DIR) of
# make-vm.sh (DRY_RUN) and host-nfs.sh. sudo, findmnt, stat, id and exportfs
# are stubs on PATH, driven by environment variables. Prints `ok N` /
# `not ok N`; exits non-zero on failure.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$HERE/.."
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/images" "$TMP/export"
echo iso >"$TMP/ubuntu.iso"
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeFakeFakeFakeFakeFakeFakeFakeFake0123 t@example' >"$TMP/key.pub"

# STUB_DENY_X: space-separated paths the qemu user cannot traverse.
cat >"$TMP/bin/sudo" <<'STUB'
#!/bin/sh
[ "$1" != -n ] || shift
[ -z "$STUB_SUDO_FAIL" ] || exit 1
if [ "$1" = -u ] && [ "$3" = test ]; then
  for denied in $STUB_DENY_X; do
    [ "$4" = -x ] && [ "$5" = "$denied" ] && exit 1
  done
  exit 0
fi
exit 0
STUB
# STUB_FS: what stat reports; STUB_FS_MNT: what findmnt reports (the kernel's
# name); STUB_LSBLK_FS: the type of the device behind a fuseblk mount; STUB_MOUNT: mount point; STUB_IN_FSTAB: 1 or 0.
cat >"$TMP/bin/stat" <<'STUB'
#!/bin/sh
echo "${STUB_FS:-ext2/ext3}"
STUB
cat >"$TMP/bin/findmnt" <<'STUB'
#!/bin/sh
case "$*" in
  *--fstab*) [ "${STUB_IN_FSTAB:-1}" = 1 ] && echo "${STUB_MOUNT:-/}" ;;
  *"-no TARGET"*) echo "${STUB_MOUNT:-/}" ;;
  *"-no UUID"*) echo 1111-2222 ;;
  *"-no FSTYPE"*) echo "${STUB_FS_MNT:-ext4}" ;;
  *"-no SOURCE"*) echo /dev/stub1 ;;
esac
exit 0
STUB
cat >"$TMP/bin/lsblk" <<'STUB'
#!/bin/sh
echo "${STUB_LSBLK_FS:-}"
STUB
cat >"$TMP/bin/id" <<'STUB'
#!/bin/sh
case "$1" in
  libvirt-qemu) exit 0 ;;
  -u) echo 0 ;;
  *) exec /usr/bin/id "$@" ;;
esac
STUB
# host-nfs.sh runs after its checks: mkdir fails so nothing is written under /etc.
cat >"$TMP/bin/mkdir" <<'STUB'
#!/bin/sh
[ -z "$STUB_MKDIR_FAIL" ] || exit 1
exec /bin/mkdir "$@"
STUB
printf '#!/bin/sh\nexit 0\n' >"$TMP/bin/exportfs"
chmod +x "$TMP/bin"/*

n=0 failed=0
assert() {
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

: >"$TMP/empty.env"
vm() { # vm ENV_FILE [VAR=value...]; DRY_RUN make-vm.sh, output in $TMP/out
  local envf="$1"
  shift
  env PATH="$TMP/bin:$PATH" DRY_RUN=1 ISO="$TMP/ubuntu.iso" SSH_PUBKEY="$TMP/key.pub" "$@" \
    bash "$KIT/make-vm.sh" --env "$envf" >"$TMP/out" 2>&1
}
nfs() { # nfs ENV_FILE [VAR=value...]
  local envf="$1"
  shift
  env PATH="$TMP/bin:$PATH" STUB_MKDIR_FAIL=1 "$@" bash "$KIT/host-nfs.sh" --env "$envf" >"$TMP/out" 2>&1
}

echo "IMAGES_DIR=$TMP/images" >"$TMP/images.env"

vm "$TMP/empty.env" IMAGES_DIR= STUB_FS=ext2/ext3 || true
grep -q '/var/lib/libvirt/images/ms-rehearsal.qcow2' "$TMP/out"
assert "IMAGES_DIR defaults to /var/lib/libvirt/images" $?

vm "$TMP/images.env"
grep -q "$TMP/images/ms-rehearsal.qcow2" "$TMP/out"
assert "IMAGES_DIR from rehearsal.env places the VM disk" $?

mkdir -p "$TMP/other"
vm "$TMP/images.env" IMAGES_DIR="$TMP/other"
grep -q "$TMP/other/ms-rehearsal.qcow2" "$TMP/out" && ! grep -q "$TMP/images/ms-rehearsal.qcow2" "$TMP/out"
assert "an IMAGES_DIR given in the environment wins over rehearsal.env" $?

vm "$TMP/images.env" STUB_FS_MNT=vfat && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q 'vfat filesystem' "$TMP/out" && grep -q 'Warning' "$TMP/out" && grep -q 'ms-rehearsal.qcow2' "$TMP/out"
assert "make-vm warns on a vfat IMAGES_DIR and continues" $?

vm "$TMP/images.env" STUB_FS_MNT=ntfs && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q 'Warning: .*ntfs filesystem' "$TMP/out" && grep -q 'not comparable' "$TMP/out" && grep -q 'ms-rehearsal.qcow2' "$TMP/out"
assert "make-vm warns on an ntfs IMAGES_DIR and continues" $?

vm "$TMP/images.env" STUB_FS_MNT=exfat STUB_FS="UNKNOWN (0x2011bab0)" && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q 'Warning: .*exfat filesystem' "$TMP/out"
assert "make-vm warns on exfat that an old stat reports as UNKNOWN" $?

vm "$TMP/images.env" STUB_FS_MNT=fuseblk STUB_LSBLK_FS=ntfs && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q 'Warning: .*ntfs filesystem' "$TMP/out" && grep -q 'not comparable' "$TMP/out"
assert "make-vm warns on fuseblk whose device is ntfs and continues" $?

vm "$TMP/images.env" STUB_FS_MNT=fuseblk STUB_LSBLK_FS=ntfs STUB_DENY_X="$TMP" && status=0 || status=$?
grep -q 'mount options' "$TMP/out" && grep -q 'test -r' "$TMP/out" && ! grep -q 'setfacl -m' "$TMP/out"
assert "on ntfs the access fix names mount options, not setfacl, and the checks still run" $?

vm "$TMP/images.env" STUB_FS_MNT=fuseblk STUB_LSBLK_FS=ext4 STUB_MOUNT=/media/someone/disk STUB_IN_FSTAB=0 && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q 'fuseblk' "$TMP/out" && ! grep -q ' fuseblk  defaults' "$TMP/out"
assert "make-vm warns on fuseblk, continues, and never suggests fuseblk as the fstab type" $?

vm "$TMP/images.env" STUB_DENY_X="$TMP" && status=0 || status=$?
grep -q "sudo setfacl -m u:libvirt-qemu:x $TMP\$" "$TMP/out" \
  && grep -q "sudo setfacl -m u:libvirt-qemu:rwx $TMP/images\$" "$TMP/out" \
  && ! grep -q 'setfacl -m u:libvirt-qemu:x /$' "$TMP/out"
assert "a parent without traverse permission prints the exact setfacl commands" $?

vm "$TMP/images.env" STUB_SUDO_FAIL=1 && status=0 || status=$?
[ "$status" -eq 0 ] && [ "$(grep -c 'sudo needs a password' "$TMP/out")" -eq 1 ] && ! grep -q 'setfacl' "$TMP/out"
assert "without sudo the ACL probe says so once and reports no failing parent" $?

echo "IMAGES_DIR=$TMP/absent" >"$TMP/absent.env"
vm "$TMP/absent.env" || true
grep -q "sudo install -d -m 0755 $TMP/absent" "$TMP/out"
assert "a missing IMAGES_DIR prints the install command" $?

vm "$TMP/images.env" STUB_MOUNT=/media/someone/disk STUB_IN_FSTAB=0 && status=0 || status=$?
[ "$status" -eq 0 ] && grep -q 'not listed in /etc/fstab' "$TMP/out" \
  && grep -q 'UUID=1111-2222  /media/someone/disk  ext4  defaults,nofail,x-systemd.device-timeout=10s' "$TMP/out" \
  && grep -q 'ms-rehearsal.qcow2' "$TMP/out"
assert "a mount absent from fstab warns with the fstab line and continues" $?

vm "$TMP/images.env" STUB_MOUNT=/media/someone/disk STUB_IN_FSTAB=1
! grep -q 'not listed in /etc/fstab' "$TMP/out"
assert "a mount listed in fstab raises no warning" $?

echo "NFS_EXPORT_DIR=$TMP/export" >"$TMP/export.env"
nfs "$TMP/export.env" STUB_FS_MNT=exfat && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q 'exfat filesystem' "$TMP/out"
assert "host-nfs refuses an exfat NFS_EXPORT_DIR" $?

nfs "$TMP/export.env" STUB_FS_MNT=ntfs && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q 'ntfs filesystem' "$TMP/out" && ! grep -q 'Warning: .*ntfs filesystem' "$TMP/out"
assert "host-nfs refuses an ntfs NFS_EXPORT_DIR" $?

nfs "$TMP/export.env" STUB_FS_MNT=fuseblk STUB_LSBLK_FS=ntfs && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q 'ntfs filesystem' "$TMP/out"
assert "host-nfs refuses fuseblk whose device is ntfs" $?

nfs "$TMP/export.env" STUB_MOUNT=/media/someone/disk STUB_IN_FSTAB=0 && status=0 || status=$?
grep -q 'not listed in /etc/fstab' "$TMP/out" && grep -q 'removable automount is fragile' "$TMP/out"
assert "host-nfs warns on an export under an unlisted mount" $?

nfs "$TMP/empty.env" NFS_EXPORT_DIR=/tmp/with" "space && status=0 || status=$?
[ "$status" -ne 0 ] && grep -q 'Invalid NFS_EXPORT_DIR' "$TMP/out"
assert "host-nfs rejects an unsafe NFS_EXPORT_DIR" $?

for bad in / /etc /usr /var /home /root /boot /srv /srv/ ; do
  nfs "$TMP/empty.env" NFS_EXPORT_DIR="$bad" && status=0 || status=$?
  [ "$status" -ne 0 ] && grep -q 'Invalid NFS_EXPORT_DIR' "$TMP/out"
  assert "host-nfs refuses the system directory $bad itself" $?
done

nfs "$TMP/empty.env" NFS_EXPORT_DIR=/srv/ms-rehearsal-data && status=0 || status=$?
! grep -q 'Invalid NFS_EXPORT_DIR' "$TMP/out"
assert "host-nfs accepts a sub-directory of /srv" $?

exit "$failed"
