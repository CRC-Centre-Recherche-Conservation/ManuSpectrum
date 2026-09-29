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
Usage : ISO=/chemin/ubuntu-26.04.1-live-server-amd64.iso $(basename "$0") [-h]

Installe la VM de répétition sans intervention (≈ 10-15 min).

Variables (valeur par défaut) :
  ISO         image d'installation, obligatoire ; SHA256SUMS à côté = vérifié
  VM_NAME     ms-rehearsal
  VCPUS       rehearsal.env, sinon 4
  RAM_MB      rehearsal.env, sinon 8192
  DISK_GB     rehearsal.env, sinon 60
  SSH_PUBKEY  ~/.ssh/id_ed25519.pub
  NETWORK     ms-rehearsal
  MAC         52:54:00:4d:53:10
  VM_IP       192.168.123.10
  DRY_RUN     1 = affiche les commandes et contrôle le XML, ne crée rien

VCPUS, RAM_MB, DISK_GB, ADMIN_USER, ROOT_LV_SIZE (50G), LOCALE (en_US.UTF-8) et
KEYBOARD (us) viennent de rehearsal.env ; une variable d'environnement passée
à la commande l'emporte. ROOT_LV_SIZE + ${BOOT_PART_GB}G de /boot + ${MARGIN_GB}G de marge doivent tenir dans DISK_GB.
USAGE
}

case "${1:-}" in
  -h | --help) usage; exit 0 ;;
  "") ;;
  *) echo "Option inconnue : $1" >&2; usage >&2; exit 2 ;;
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
  echo "Attention : VCPUS, RAM_MB ou DISK_GB absents : valeurs génériques, la VM ne sera pas conforme à la production tant que rehearsal.env n'est pas rempli." >&2
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
  echo "La variable ISO est obligatoire (chemin de l'image ubuntu-26.04.1-live-server-amd64.iso)." >&2
  usage >&2
  exit 2
fi

if ! [[ "$ROOT_LV_SIZE" =~ ^[0-9]+G$ ]]; then
  echo "ROOT_LV_SIZE invalide : « ${ROOT_LV_SIZE} » (attendu : 50G)." >&2
  exit 1
fi
if ! [[ "$DISK_GB" =~ ^[0-9]+$ ]]; then
  echo "DISK_GB invalide : « ${DISK_GB} »." >&2
  exit 1
fi
if [ $((${ROOT_LV_SIZE%G} + BOOT_PART_GB + MARGIN_GB)) -gt "$DISK_GB" ]; then
  echo "ROOT_LV_SIZE (${ROOT_LV_SIZE}) + ${BOOT_PART_GB}G de /boot + ${MARGIN_GB}G de marge dépassent DISK_GB (${DISK_GB} Gio) : agrandissez DISK_GB ou réduisez ROOT_LV_SIZE." >&2
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
  echo "(dry-run : on continue sans ces outils)" >&2
fi
have() { ! printf '%s\n' "${missing[@]}" | grep -qx "$1"; }

if [ "$DRY_RUN" != 1 ] || have virsh; then
  if ! virsh_c uri >/dev/null 2>&1; then
    echo "Connexion à ${CONNECT} impossible : ajoutez-vous au groupe libvirt (sudo usermod -aG libvirt \$USER), reconnectez-vous, et vérifiez que libvirt tourne." >&2
    [ "$DRY_RUN" = 1 ] || exit 1
  else
    if virsh_c dominfo "$VM_NAME" >/dev/null 2>&1; then
      echo "La VM « ${VM_NAME} » existe déjà : aucune modification." >&2
      echo "Pour repartir de zéro : virsh -c ${CONNECT} undefine --remove-all-storage --snapshots-metadata ${VM_NAME}" >&2
      exit 1
    fi
    if ! virsh_c net-list --name | grep -qx "$NETWORK"; then
      echo "Le réseau libvirt « ${NETWORK} » est absent ou inactif : lancez « sudo ./host-network.sh »." >&2
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
    echo "${iso_name} n'apparaît pas dans SHA256SUMS : somme non vérifiable." >&2
    exit 1
  fi
  if (cd "$iso_dir" && sha256sum -c - <<<"$iso_sum" >/dev/null 2>&1); then
    echo "Somme SHA256 de l'ISO vérifiée."
  else
    echo "La somme SHA256 de ${iso_name} ne correspond pas à SHA256SUMS." >&2
    exit 1
  fi
else
  echo "Pas de SHA256SUMS à côté de l'ISO : somme non vérifiée."
fi
if [ ! -f "$SSH_PUBKEY" ]; then
  echo "Clé publique SSH introuvable : ${SSH_PUBKEY} (variable SSH_PUBKEY)." >&2
  exit 1
fi

# The hypervisor user must be able to open the ISO; a home directory is
# usually closed to it.
for qemu_user in libvirt-qemu qemu; do
  if id "$qemu_user" >/dev/null 2>&1; then
    if ! sudo -u "$qemu_user" test -r "$ISO"; then
      echo "L'utilisateur ${qemu_user} ne peut pas lire ${ISO} : copiez l'ISO dans ${IMAGES_DIR}/ (sudo cp) et relancez avec ISO=${IMAGES_DIR}/${iso_name}." >&2
      [ "$DRY_RUN" = 1 ] || exit 1
    fi
    break
  fi
done

mem_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
if [ $((RAM_MB * 1024 * 10)) -gt $((mem_kb * 9)) ]; then
  echo "Attention : ${RAM_MB} Mio dépassent 90 % de la RAM du portable ($((mem_kb / 1024)) Mio)." >&2
  echo "La VM de dev doit être arrêtée (virsh shutdown …)." >&2
  if [ "$DRY_RUN" != 1 ]; then
    read -r -p "Continuer quand même ? [o/N] " answer
    case "$answer" in o | O | oui | OUI) ;; *) echo "Abandon."; exit 1 ;; esac
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
  read -r -s -p "Mot de passe du compte ${ADMIN_USER} : " pw1; echo
  read -r -s -p "Confirmez le mot de passe : " pw2; echo
  if [ -z "$pw1" ] || [ "$pw1" != "$pw2" ]; then
    echo "Mots de passe vides ou différents." >&2
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
  echo "libosinfo ne connaît aucun des systèmes ubuntu26.04, ubuntu24.04, linux2024 (osinfo-query absent ou base trop ancienne)." >&2
  echo "Dernier recours : mettez à jour osinfo-db (osinfo-db-import --local), ou éditez --osinfo dans make-vm.sh pour « generic »." >&2
  [ "$DRY_RUN" = 1 ] || exit 1
  osinfo="linux2024"
fi
if [ "$osinfo" != "ubuntu26.04" ]; then
  echo "libosinfo ne connaît pas encore ubuntu26.04 : repli sur « ${osinfo} »."
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
    echo "virt-install --print-xml a échoué." >&2
    exit 1
  }
  if grep -Eq "firmware=['\"]efi['\"]|<loader[^>]*pflash" <<<"$xml"; then
    echo "Le XML produit demande l'UEFI (firmware=efi ou loader pflash) : la VM ne démarrerait pas." >&2
    exit 1
  fi
  echo "XML contrôlé : aucun démarrage UEFI."
fi

if [ "$DRY_RUN" = 1 ]; then
  printf '[dry-run] virt-install'
  printf ' %q' "${vi_args[@]}" --noautoconsole --noreboot --wait -1
  printf '\n'
  exit 0
fi

echo "Installation en cours. Suivre : virsh -c ${CONNECT} console ${VM_NAME} (sortie : Ctrl+]). Si l'installeur échoue, virt-install attend sans fin : Ctrl+C, puis « virsh -c ${CONNECT} destroy ${VM_NAME} »."
virt-install "${vi_args[@]}" --noautoconsole --noreboot --wait -1

virsh_c detach-disk "$VM_NAME" "$seed_disk" --config >/dev/null 2>&1 \
  || virsh_c change-media "$VM_NAME" sda --eject --config >/dev/null 2>&1 \
  || echo "Le lecteur du seed n'a pas pu être retiré automatiquement : virsh -c ${CONNECT} domblklist ${VM_NAME}." >&2
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
  echo "Connexion SSH impossible sur ${ADMIN_USER}@${VM_IP} après 5 minutes : la VM n'a pas démarré, ou la clé privée correspondant à ${SSH_PUBKEY} est refusée (ssh-agent, ou fichier ${SSH_PUBKEY%.pub} absent)." >&2
  exit 1
fi

virsh_c shutdown "$VM_NAME" >/dev/null
for _ in $(seq 1 60); do
  if [ "$(virsh_c domstate "$VM_NAME")" = "shut off" ]; then break; fi
  sleep 3
done
if [ "$(virsh_c domstate "$VM_NAME")" != "shut off" ]; then
  echo "La VM ne s'est pas éteinte : pas de snapshot pris." >&2
  exit 1
fi
virsh_c snapshot-create-as "$VM_NAME" installed "Ubuntu installé, avant baseline"
virsh_c start "$VM_NAME" >/dev/null
sudo rm -f "$seed_copy"
seed_copy=""

cat <<NEXT

VM installée, snapshot « installed » pris. Suite :
  ssh-keygen -R ${VM_IP}   # si une ancienne VM avait cette adresse
  scp host-baseline.sh verify-baseline.sh rehearsal.env ${ADMIN_USER}@${VM_IP}:
  ssh -t ${ADMIN_USER}@${VM_IP} 'sudo ./host-baseline.sh && sudo ./verify-baseline.sh'
NEXT
