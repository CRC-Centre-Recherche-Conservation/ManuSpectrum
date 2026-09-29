#!/usr/bin/env bash
# Exports /srv/ms-rehearsal-data to the rehearsal network through a dedicated
# file in /etc/exports.d, and opens NFS in the firewalld `libvirt` zone when
# firewalld is running. Must run as root. `--remove` drops the export only.
# The export options come from NFS_EXPORT_OPTIONS in rehearsal.env (next to
# the script, or --env FILE); the export is restricted to the VM address.
set -euo pipefail
export LC_ALL=C

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPORT_DIR="/srv/ms-rehearsal-data"
EXPORT_FILE="/etc/exports.d/ms-rehearsal.exports"
EXPORT_CLIENT="192.168.123.10/32"

usage() {
  cat <<USAGE
Usage : sudo $(basename "$0") [--remove] [--env FICHIER] [-h]

Exporte ${EXPORT_DIR} en NFS vers ${EXPORT_CLIENT} (fichier dédié
${EXPORT_FILE}), avec NFS_EXPORT_OPTIONS de rehearsal.env, active le serveur NFS et, si firewalld tourne, ouvre
les services nfs, rpc-bind et mountd dans la zone « libvirt ».

  --remove         retire l'export (les données ne sont pas supprimées).
  --env FICHIER    fichier de variables (défaut : rehearsal.env à côté du script).
  -h         cette aide.
USAGE
}

remove=0
env_file="$HERE/rehearsal.env"
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --remove) remove=1; shift ;;
    --env) env_file="${2:?--env attend une valeur}"; shift 2 ;;
    *) echo "Option inconnue : $1" >&2; usage >&2; exit 2 ;;
  esac
done

# A value given in the environment wins over the variables file.
caller_options="${NFS_EXPORT_OPTIONS-}" caller_options_set="${NFS_EXPORT_OPTIONS+x}"
if [ -f "$env_file" ]; then
  # shellcheck disable=SC1090
  . "$env_file"
fi
[ -z "$caller_options_set" ] || NFS_EXPORT_OPTIONS="$caller_options"
NFS_EXPORT_OPTIONS="${NFS_EXPORT_OPTIONS:-rw,sync,root_squash,no_subtree_check}"
if ! [[ "$NFS_EXPORT_OPTIONS" =~ ^[a-z_,=0-9]+$ ]]; then
  echo "NFS_EXPORT_OPTIONS invalide : « ${NFS_EXPORT_OPTIONS} »." >&2
  exit 1
fi
EXPORT_LINE="${EXPORT_DIR} ${EXPORT_CLIENT}(${NFS_EXPORT_OPTIONS})"

if [ "$(id -u)" -ne 0 ]; then
  echo "Ce script doit être lancé en root (sudo)." >&2
  exit 1
fi

if ! command -v exportfs >/dev/null 2>&1; then
  echo "exportfs est introuvable : installez nfs-kernel-server (Debian/Ubuntu) ou nfs-utils (Fedora/openSUSE)." >&2
  exit 1
fi

if [ "$remove" -eq 1 ]; then
  if [ -f "$EXPORT_FILE" ]; then
    rm -f "$EXPORT_FILE"
    exportfs -ra
    echo "Export retiré."
  else
    echo "Export : déjà fait (rien à retirer)."
  fi
  echo "Les services firewalld nfs, rpc-bind et mountd ouverts dans la zone « libvirt » restent ouverts."
  echo "Les données de ${EXPORT_DIR} sont conservées ; pour les supprimer, tapez vous-même : rm -rf ${EXPORT_DIR}"
  exit 0
fi

changed=0

if [ ! -d "$EXPORT_DIR" ]; then
  install -d -m 0755 -o root -g root "$EXPORT_DIR"
  echo "Répertoire ${EXPORT_DIR} créé."
  changed=1
fi

mkdir -p "$(dirname "$EXPORT_FILE")"
if [ ! -f "$EXPORT_FILE" ] || [ "$(cat "$EXPORT_FILE")" != "$EXPORT_LINE" ]; then
  printf '%s\n' "$EXPORT_LINE" >"$EXPORT_FILE"
  echo "Export écrit dans ${EXPORT_FILE}."
  changed=1
fi
exportfs -ra

service=""
for candidate in nfs-server nfs-kernel-server; do
  if systemctl cat "${candidate}.service" >/dev/null 2>&1; then
    service="$candidate"
    break
  fi
done
if [ -z "$service" ]; then
  echo "Aucun service nfs-server / nfs-kernel-server trouvé : installez le serveur NFS." >&2
  exit 1
fi
if ! systemctl is-active --quiet "$service" || ! systemctl is-enabled --quiet "$service"; then
  systemctl enable --now "$service"
  echo "Service ${service} activé et démarré."
  changed=1
fi

if command -v firewall-cmd >/dev/null 2>&1 && [ "$(firewall-cmd --state 2>/dev/null || true)" = "running" ]; then
  fw_changed=0
  for svc in nfs rpc-bind mountd; do
    if ! firewall-cmd --permanent --zone=libvirt --query-service="$svc" >/dev/null 2>&1; then
      firewall-cmd --permanent --zone=libvirt --add-service="$svc" >/dev/null
      fw_changed=1
    fi
  done
  if [ "$fw_changed" -eq 1 ]; then
    firewall-cmd --reload >/dev/null
    echo "firewalld détecté : services nfs, rpc-bind et mountd ouverts dans la zone « libvirt » (sinon /data ne se monte pas depuis la VM)."
    changed=1
  fi
fi

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
  echo "ufw est actif sur ce portable : autorisez NFS depuis le réseau de la VM, par exemple « sudo ufw allow from 192.168.123.0/24 to any port nfs »." >&2
fi

if [ "$changed" -eq 0 ]; then
  echo "Export NFS de ${EXPORT_DIR} : déjà fait."
fi
