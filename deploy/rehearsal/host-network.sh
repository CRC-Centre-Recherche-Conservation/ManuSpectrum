#!/usr/bin/env bash
# Defines, starts and autostarts the dedicated libvirt network `ms-rehearsal`
# (bridge virbr-msr, 192.168.123.0/24, NAT) on the system libvirt instance.
# Safe to re-run: an existing, active network is left untouched.
set -euo pipefail
export LC_ALL=C

NET_NAME="ms-rehearsal"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VIRSH=(virsh -c qemu:///system)

usage() {
  cat <<USAGE
Usage : $(basename "$0") [-h]

Crée (si besoin) et démarre le réseau libvirt « ${NET_NAME} » (192.168.123.0/24,
NAT, VM en 192.168.123.10) sur qemu:///system, avec démarrage automatique.
Le réseau « default » n'est jamais modifié. Relançable sans effet de bord.
USAGE
}

case "${1:-}" in
  -h | --help) usage; exit 0 ;;
  "") ;;
  *) echo "Option inconnue : $1" >&2; usage >&2; exit 2 ;;
esac

if ! command -v virsh >/dev/null 2>&1; then
  echo "virsh est introuvable : installez libvirt (libvirt-clients / libvirt-daemon-system)." >&2
  exit 1
fi

changed=0

if ! "${VIRSH[@]}" net-info "$NET_NAME" >/dev/null 2>&1; then
  "${VIRSH[@]}" net-define "$HERE/network.xml"
  echo "Réseau ${NET_NAME} défini."
  changed=1
fi

if [ "$("${VIRSH[@]}" net-info "$NET_NAME" | awk '/^Active:/ {print $2}')" != "yes" ]; then
  "${VIRSH[@]}" net-start "$NET_NAME"
  echo "Réseau ${NET_NAME} démarré."
  changed=1
fi

if [ "$("${VIRSH[@]}" net-info "$NET_NAME" | awk '/^Autostart:/ {print $2}')" != "yes" ]; then
  "${VIRSH[@]}" net-autostart "$NET_NAME"
  echo "Démarrage automatique du réseau ${NET_NAME} activé."
  changed=1
fi

if [ "$changed" -eq 0 ]; then
  echo "Réseau ${NET_NAME} : déjà fait."
fi
