#!/usr/bin/env bash
# Installs the rehearsal VM unattended with virt-install (Ubuntu autoinstall
# seed rendered by render-seed.sh), then takes the internal snapshot
# `installed`. Variables: ISO (required), VM_NAME, VCPUS, RAM_MB, DISK_GB,
# SSH_PUBKEY, NETWORK, MAC, VM_IP, DRY_RUN. ADMIN_USER, ROOT_LV_SIZE, LOCALE
# and KEYBOARD come from rehearsal.env when present. DRY_RUN=1 prints the
# commands and checks the generated XML without creating anything.
set -euo pipefail
export LC_ALL=C

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONNECT="qemu:///system"
IMAGES_DIR="/var/lib/libvirt/images"
BOOT_PART_GB=2
MARGIN_GB=1

usage() {
  cat <<USAGE
Usage: ISO=/path/ubuntu-26.04.1-live-server-amd64.iso $(basename "$0") [-h]

Installs the rehearsal VM unattended (about 10-15 min).

Variables (default value):
  ISO         installation image, required; SHA256SUMS next to it = verified
  VM_NAME     ms-rehearsal
  VCPUS       rehearsal.env, else 4
  RAM_MB      rehearsal.env, else 8192
  DISK_GB     rehearsal.env, else 60
  SSH_PUBKEY  ~/.ssh/id_ed25519.pub
  NETWORK     ms-rehearsal
  MAC         52:54:00:4d:53:10
  VM_IP       192.168.123.10
  DRY_RUN     1 = prints the commands and checks the XML, creates nothing

VCPUS, RAM_MB, DISK_GB, ADMIN_USER, ROOT_LV_SIZE (50G), LOCALE (en_US.UTF-8) and
KEYBOARD (us) come from rehearsal.env; an environment variable passed to the
command wins. ROOT_LV_SIZE + ${BOOT_PART_GB}G of /boot + ${MARGIN_GB}G of margin must fit in DISK_GB.
USAGE
}

case "${1:-}" in
  -h | --help) usage; exit 0 ;;
  "") ;;
  *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

# Values given in the environment win over the variables file.
declare -A caller_env=()
for v in VCPUS RAM_MB DISK_GB ADMIN_USER ROOT_LV_SIZE LOCALE KEYBOARD; do
  [ -z "${!v+x}" ] || caller_env[$v]="${!v}"
done
if [ -f "$HERE/rehearsal.env" ]; then
  # shellcheck disable=SC1090,SC1091
  . "$HERE/rehearsal.env"
fi
for v in "${!caller_env[@]}"; do
  printf -v "$v" '%s' "${caller_env[$v]}"
done
if [ -z "${VCPUS:-}" ] || [ -z "${RAM_MB:-}" ] || [ -z "${DISK_GB:-}" ]; then
  echo "Warning: VCPUS, RAM_MB or DISK_GB missing: generic values, the VM will not match production until rehearsal.env is filled in." >&2
fi
ADMIN_USER="${ADMIN_USER:-admin1}"
ISO="${ISO:-}"
VM_NAME="${VM_NAME:-ms-rehearsal}"
VCPUS="${VCPUS:-4}"
RAM_MB="${RAM_MB:-8192}"
DISK_GB="${DISK_GB:-60}"
ROOT_LV_SIZE="${ROOT_LV_SIZE:-50G}"
LOCALE="${LOCALE:-en_US.UTF-8}"
KEYBOARD="${KEYBOARD:-us}"
SSH_PUBKEY="${SSH_PUBKEY:-$HOME/.ssh/id_ed25519.pub}"
NETWORK="${NETWORK:-ms-rehearsal}"
MAC="${MAC:-52:54:00:4d:53:10}"
VM_IP="${VM_IP:-192.168.123.10}"
DRY_RUN="${DRY_RUN:-0}"

virsh_c() { virsh -c "$CONNECT" "$@"; }

# Runs the command, or only prints it in DRY_RUN mode.
run() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

if [ -z "$ISO" ]; then
  echo "The ISO variable is required (path of the ubuntu-26.04.1-live-server-amd64.iso image)." >&2
  usage >&2
  exit 2
fi

if ! [[ "$ROOT_LV_SIZE" =~ ^[0-9]+G$ ]]; then
  echo "Invalid ROOT_LV_SIZE: \"${ROOT_LV_SIZE}\" (expected: 50G)." >&2
  exit 1
fi
if ! [[ "$DISK_GB" =~ ^[0-9]+$ ]]; then
  echo "Invalid DISK_GB: \"${DISK_GB}\"." >&2
  exit 1
fi
if [ $((${ROOT_LV_SIZE%G} + BOOT_PART_GB + MARGIN_GB)) -gt "$DISK_GB" ]; then
  echo "ROOT_LV_SIZE (${ROOT_LV_SIZE}) + ${BOOT_PART_GB}G of /boot + ${MARGIN_GB}G of margin exceed DISK_GB (${DISK_GB} GiB): increase DISK_GB or reduce ROOT_LV_SIZE." >&2
  exit 1
fi

missing=()
for tool in virsh virt-install qemu-img cloud-localds mkpasswd; do
  command -v "$tool" >/dev/null 2>&1 || missing+=("$tool")
done
if [ "${#missing[@]}" -gt 0 ]; then
  {
    echo "Outils manquants : ${missing[*]}"
    echo "  Debian/Ubuntu : sudo apt install virtinst libvirt-clients qemu-utils cloud-image-utils whois"
    echo "  Fedora        : sudo dnf install virt-install libvirt-client qemu-img cloud-utils mkpasswd"
  } >&2
  if [ "$DRY_RUN" != 1 ]; then exit 1; fi
  echo "(dry-run: continuing without these tools)" >&2
fi
have() { ! printf '%s\n' "${missing[@]}" | grep -qx "$1"; }

if [ "$DRY_RUN" != 1 ] || have virsh; then
  if ! virsh_c uri >/dev/null 2>&1; then
    echo "Cannot connect to ${CONNECT}: add yourself to the libvirt group (sudo usermod -aG libvirt \$USER), log in again, and check that libvirt is running." >&2
    [ "$DRY_RUN" = 1 ] || exit 1
  else
    if virsh_c dominfo "$VM_NAME" >/dev/null 2>&1; then
      echo "The VM \"${VM_NAME}\" already exists: nothing changed." >&2
      echo "To start over: virsh -c ${CONNECT} undefine --remove-all-storage --snapshots-metadata ${VM_NAME}" >&2
      exit 1
    fi
    if ! virsh_c net-list --name | grep -qx "$NETWORK"; then
      echo "The libvirt network \"${NETWORK}\" is missing or inactive: run \"sudo ./host-network.sh\"." >&2
      [ "$DRY_RUN" = 1 ] || exit 1
    fi
  fi
fi

if [ ! -f "$ISO" ]; then
  echo "ISO introuvable : ${ISO}" >&2
  exit 1
fi
iso_dir="$(cd "$(dirname "$ISO")" && pwd)"
iso_name="$(basename "$ISO")"
if [ -f "$iso_dir/SHA256SUMS" ]; then
  iso_sum="$(grep -E " [* ]?${iso_name//./\\.}\$" "$iso_dir/SHA256SUMS" || true)"
  if [ -z "$iso_sum" ]; then
    echo "${iso_name} does not appear in SHA256SUMS: checksum cannot be verified." >&2
    exit 1
  fi
  if (cd "$iso_dir" && sha256sum -c - <<<"$iso_sum" >/dev/null 2>&1); then
    echo "ISO SHA256 checksum verified."
  else
    echo "The SHA256 checksum of ${iso_name} does not match SHA256SUMS." >&2
    exit 1
  fi
else
  echo "No SHA256SUMS next to the ISO: checksum not verified."
fi
if [ ! -f "$SSH_PUBKEY" ]; then
  echo "SSH public key not found: ${SSH_PUBKEY} (variable SSH_PUBKEY)." >&2
  exit 1
fi

# The hypervisor user must be able to open the ISO; a home directory is
# usually closed to it.
for qemu_user in libvirt-qemu qemu; do
  if id "$qemu_user" >/dev/null 2>&1; then
    if ! sudo -u "$qemu_user" test -r "$ISO"; then
      echo "User ${qemu_user} cannot read ${ISO}: copy the ISO into ${IMAGES_DIR}/ (sudo cp) and re-run with ISO=${IMAGES_DIR}/${iso_name}." >&2
      [ "$DRY_RUN" = 1 ] || exit 1
    fi
    break
  fi
done

mem_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
if [ $((RAM_MB * 1024 * 10)) -gt $((mem_kb * 9)) ]; then
  echo "Warning: ${RAM_MB} MiB exceeds 90 % of the host's RAM ($((mem_kb / 1024)) MiB)." >&2
  echo "Free enough memory on the host first: RAM_MB + 4 GB." >&2
  if [ "$DRY_RUN" != 1 ]; then
    read -r -p "Continue anyway? [y/N] " answer
    case "$answer" in y | Y | yes | YES) ;; *) echo "Aborted."; exit 1 ;; esac
  fi
fi

work="$(mktemp -d)"
seed_copy=""
cleanup() {
  rm -rf "$work"
  if [ -n "$seed_copy" ]; then sudo rm -f "$seed_copy"; fi
}
trap cleanup EXIT

if [ "$DRY_RUN" = 1 ]; then
  # shellcheck disable=SC2016
  printf '%s\n' '$6$dryrun$0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000' >"$work/hash"
else
  read -r -s -p "Password of account ${ADMIN_USER}: " pw1; echo
  read -r -s -p "Confirm the password: " pw2; echo
  if [ -z "$pw1" ] || [ "$pw1" != "$pw2" ]; then
    echo "Passwords empty or different." >&2
    exit 1
  fi
  printf '%s' "$pw1" | mkpasswd -m sha-512 -s >"$work/hash"
  unset pw1 pw2
fi
"$HERE/render-seed.sh" --out "$work" --pubkey "$SSH_PUBKEY" --password-hash-file "$work/hash" \
  --admin-user "$ADMIN_USER" --root-size "$ROOT_LV_SIZE" --locale "$LOCALE" --keyboard "$KEYBOARD"
rm -f "$work/hash"
if have cloud-localds; then
  cloud-localds "$work/seed.iso" "$work/user-data" "$work/meta-data"
else
  echo "[dry-run] cloud-localds absent : seed.iso non construit."
  : >"$work/seed.iso"
fi
if [ "$DRY_RUN" = 1 ]; then
  seed_disk="$work/seed.iso"
else
  seed_disk="$IMAGES_DIR/${VM_NAME}-seed.iso"
  seed_copy="$seed_disk"
  sudo install -m 0600 "$work/seed.iso" "$seed_copy"
fi

osinfo=""
if command -v osinfo-query >/dev/null 2>&1; then
  for candidate in ubuntu26.04 ubuntu24.04 linux2024; do
    if osinfo-query os short-id="$candidate" 2>/dev/null | grep -q "$candidate"; then
      osinfo="$candidate"
      break
    fi
  done
fi
if [ -z "$osinfo" ]; then
  echo "libosinfo knows none of the systems ubuntu26.04, ubuntu24.04, linux2024 (osinfo-query missing or database too old)." >&2
  echo "Last resort: update osinfo-db (osinfo-db-import --local), or edit --osinfo in make-vm.sh to \"generic\"." >&2
  [ "$DRY_RUN" = 1 ] || exit 1
  osinfo="linux2024"
fi
if [ "$osinfo" != "ubuntu26.04" ]; then
  echo "libosinfo does not know ubuntu26.04 yet: falling back to \"${osinfo}\"."
fi

# The autoinstall layout has no ESP: the guest must boot with BIOS. From
# virt-install 5, `--boot uefi=off` is honoured; earlier versions treat any
# `uefi` key as "UEFI on" and default to BIOS without it.
boot_args=()
if have virt-install; then
  vi_major="$(virt-install --version 2>/dev/null | head -n1 | cut -d. -f1)"
  if [[ "$vi_major" =~ ^[0-9]+$ ]] && [ "$vi_major" -ge 5 ]; then
    boot_args=(--boot uefi=off)
  fi
fi

disk_path="$IMAGES_DIR/$VM_NAME.qcow2"
vi_args=(
  --connect "$CONNECT" --name "$VM_NAME" --vcpus "$VCPUS" --memory "$RAM_MB"
  --cpu host-passthrough --osinfo "$osinfo"
  --disk "size=$DISK_GB,format=qcow2,bus=virtio,path=$disk_path"
  --disk "path=$seed_disk,device=cdrom"
  --location "$ISO,kernel=casper/vmlinuz,initrd=casper/initrd"
  --extra-args "autoinstall console=ttyS0,115200n8"
  --network "network=$NETWORK,mac=$MAC,model=virtio"
  --graphics none
  "${boot_args[@]}"
)

if have virt-install; then
  xml="$(virt-install "${vi_args[@]}" --print-xml --dry-run)" || {
    echo "virt-install --print-xml failed." >&2
    exit 1
  }
  if grep -Eq "firmware=['\"]efi['\"]|<loader[^>]*pflash" <<<"$xml"; then
    echo "The produced XML asks for UEFI (firmware=efi or loader pflash): the VM would not boot." >&2
    exit 1
  fi
  echo "XML checked: no UEFI boot."
fi

if [ "$DRY_RUN" = 1 ]; then
  printf '[dry-run] virt-install'
  printf ' %q' "${vi_args[@]}" --noautoconsole --noreboot --wait -1
  printf '\n'
  exit 0
fi

echo "Installation in progress. Follow it: virsh -c ${CONNECT} console ${VM_NAME} (exit: Ctrl+]). If the installer fails, virt-install waits forever: Ctrl+C, then \"virsh -c ${CONNECT} destroy ${VM_NAME}\"."
virt-install "${vi_args[@]}" --noautoconsole --noreboot --wait -1

virsh_c detach-disk "$VM_NAME" "$seed_disk" --config >/dev/null 2>&1 \
  || virsh_c change-media "$VM_NAME" sda --eject --config >/dev/null 2>&1 \
  || echo "The seed drive could not be removed automatically : virsh -c ${CONNECT} domblklist ${VM_NAME}." >&2
virsh_c start "$VM_NAME" >/dev/null

# Private key matching SSH_PUBKEY, offered to every probe when it exists.
ssh_identity=()
if [ -f "${SSH_PUBKEY%.pub}" ]; then ssh_identity=(-i "${SSH_PUBKEY%.pub}"); fi
# A rebuilt VM reuses the address: drop the host key of the previous one.
ssh-keygen -R "$VM_IP" >/dev/null 2>&1 || true

# Returns once the admin account logs in with its key and cloud-init has finished.
wait_first_boot() {
  local rc
  for _ in $(seq 1 60); do
    rc=0
    ssh "${ssh_identity[@]}" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 \
      "${ADMIN_USER}@${VM_IP}" cloud-init status --wait >/dev/null 2>&1 || rc=$?
    if [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]; then return 0; fi
    sleep 5
  done
  return 1
}
if ! wait_first_boot; then
  echo "SSH connection to ${ADMIN_USER}@${VM_IP} impossible after 5 minutes: the VM did not start, or the private key matching ${SSH_PUBKEY} is refused (ssh-agent, or file ${SSH_PUBKEY%.pub} missing)." >&2
  exit 1
fi

virsh_c shutdown "$VM_NAME" >/dev/null
for _ in $(seq 1 60); do
  if [ "$(virsh_c domstate "$VM_NAME")" = "shut off" ]; then break; fi
  sleep 3
done
if [ "$(virsh_c domstate "$VM_NAME")" != "shut off" ]; then
  echo "The VM did not shut down: no snapshot taken." >&2
  exit 1
fi
virsh_c snapshot-create-as "$VM_NAME" installed "Ubuntu installed, before baseline"
virsh_c start "$VM_NAME" >/dev/null
sudo rm -f "$seed_copy"
seed_copy=""

cat <<NEXT

VM installed, snapshot "installed" taken. Next:
  ssh-keygen -R ${VM_IP}   # if an earlier VM had this address
  scp host-baseline.sh verify-baseline.sh rehearsal.env ${ADMIN_USER}@${VM_IP}:
  ssh -t ${ADMIN_USER}@${VM_IP} 'sudo ./host-baseline.sh && sudo ./verify-baseline.sh'
NEXT
