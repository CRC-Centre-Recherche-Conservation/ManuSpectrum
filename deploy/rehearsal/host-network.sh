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
Usage: $(basename "$0") [-h]

Creates (if needed) and starts the libvirt network "${NET_NAME}" (192.168.123.0/24,
NAT, VM at 192.168.123.10) on qemu:///system, with autostart.
The "default" network is never modified. Safe to re-run.
USAGE
}

case "${1:-}" in
  -h | --help) usage; exit 0 ;;
  "") ;;
  *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
esac

if ! command -v virsh >/dev/null 2>&1; then
  echo "virsh not found: install libvirt (libvirt-clients / libvirt-daemon-system)." >&2
  exit 1
fi

changed=0

if ! "${VIRSH[@]}" net-info "$NET_NAME" >/dev/null 2>&1; then
  "${VIRSH[@]}" net-define "$HERE/network.xml"
  echo "Network ${NET_NAME} defined."
  changed=1
fi

if [ "$("${VIRSH[@]}" net-info "$NET_NAME" | awk '/^Active:/ {print $2}')" != "yes" ]; then
  "${VIRSH[@]}" net-start "$NET_NAME"
  echo "Network ${NET_NAME} started."
  changed=1
fi

if [ "$("${VIRSH[@]}" net-info "$NET_NAME" | awk '/^Autostart:/ {print $2}')" != "yes" ]; then
  "${VIRSH[@]}" net-autostart "$NET_NAME"
  echo "Autostart of network ${NET_NAME} enabled."
  changed=1
fi

if [ "$changed" -eq 0 ]; then
  echo "Network ${NET_NAME}: already done."
fi
