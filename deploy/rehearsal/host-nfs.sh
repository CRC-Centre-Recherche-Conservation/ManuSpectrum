#!/usr/bin/env bash
# Exports NFS_EXPORT_DIR (default /srv/ms-rehearsal-data) to the rehearsal network through a dedicated
# file in /etc/exports.d, and opens NFS in the firewalld `libvirt` zone when
# firewalld is running. Must run as root. `--remove` drops the export only.
# The export options come from NFS_EXPORT_OPTIONS in rehearsal.env (next to
# the script, or --env FILE); the export is restricted to the VM address.
set -euo pipefail
export LC_ALL=C

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPORT_FILE="/etc/exports.d/ms-rehearsal.exports"
EXPORT_CLIENT="192.168.123.10/32"

usage() {
  cat <<USAGE
Usage: sudo $(basename "$0") [--remove] [--env FILE] [-h]

Exports NFS_EXPORT_DIR (rehearsal.env, default /srv/ms-rehearsal-data) over NFS to ${EXPORT_CLIENT} (dedicated file
${EXPORT_FILE}), with NFS_EXPORT_OPTIONS from rehearsal.env, enables the NFS server and, if firewalld runs, opens
the nfs, rpc-bind and mountd services in the "libvirt" zone.

  --remove         removes the export (data is not deleted).
  --env FILE       variables file (default: rehearsal.env next to the script).
  -h               this help.
USAGE
}

remove=0
env_file="$HERE/rehearsal.env"
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --remove) remove=1; shift ;;
    --env) env_file="${2:?--env needs a value}"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# A value given in the environment wins over the variables file.
declare -A caller_env=()
for v in NFS_EXPORT_OPTIONS NFS_EXPORT_DIR; do
  [ -z "${!v+x}" ] || caller_env[$v]="${!v}"
done
if [ -f "$env_file" ]; then
  # shellcheck disable=SC1090
  . "$env_file"
fi
for v in "${!caller_env[@]}"; do
  printf -v "$v" '%s' "${caller_env[$v]}"
done
EXPORT_DIR="${NFS_EXPORT_DIR:-/srv/ms-rehearsal-data}"
# shellcheck disable=SC1091
. "$HERE/lib-storage.sh"
valid_storage_path NFS_EXPORT_DIR "$EXPORT_DIR" || exit 1
NFS_EXPORT_OPTIONS="${NFS_EXPORT_OPTIONS:-rw,sync,root_squash,no_subtree_check}"
if ! [[ "$NFS_EXPORT_OPTIONS" =~ ^[a-z_,=0-9]+$ ]]; then
  echo "Invalid NFS_EXPORT_OPTIONS: \"${NFS_EXPORT_OPTIONS}\"." >&2
  exit 1
fi
EXPORT_LINE="${EXPORT_DIR} ${EXPORT_CLIENT}(${NFS_EXPORT_OPTIONS})"

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

if ! command -v exportfs >/dev/null 2>&1; then
  echo "exportfs not found: install nfs-kernel-server (Debian/Ubuntu) or nfs-utils (Fedora/openSUSE)." >&2
  exit 1
fi

if [ "$remove" -eq 1 ]; then
  if [ -f "$EXPORT_FILE" ]; then
    rm -f "$EXPORT_FILE"
    exportfs -ra
    echo "Export removed."
  else
    echo "Export: already done (nothing to remove)."
  fi
  echo "The firewalld services nfs, rpc-bind and mountd opened in the \"libvirt\" zone stay open."
  echo "The data in ${EXPORT_DIR} is kept; to delete it, type it yourself: rm -rf ${EXPORT_DIR}"
  exit 0
fi

rc=0
check_storage_dir nfs "$EXPORT_DIR" || rc=$?
[ "$rc" -eq 0 ] || exit 1

changed=0

if [ ! -d "$EXPORT_DIR" ]; then
  install -d -m 0755 -o root -g root "$EXPORT_DIR"
  echo "Directory ${EXPORT_DIR} created."
  changed=1
fi

mkdir -p "$(dirname "$EXPORT_FILE")"
if [ ! -f "$EXPORT_FILE" ] || [ "$(cat "$EXPORT_FILE")" != "$EXPORT_LINE" ]; then
  printf '%s\n' "$EXPORT_LINE" >"$EXPORT_FILE"
  echo "Export written to ${EXPORT_FILE}."
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
  echo "No nfs-server / nfs-kernel-server service found: install the NFS server." >&2
  exit 1
fi
if ! systemctl is-active --quiet "$service" || ! systemctl is-enabled --quiet "$service"; then
  systemctl enable --now "$service"
  echo "Service ${service} enabled and started."
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
    echo "firewalld detected: nfs, rpc-bind and mountd services opened in the \"libvirt\" zone (otherwise /data does not mount from the VM)."
    changed=1
  fi
fi

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
  echo "ufw is active on this host: allow NFS from the VM network, for example \"sudo ufw allow from 192.168.123.0/24 to any port nfs\"." >&2
fi

if [ "$changed" -eq 0 ]; then
  echo "NFS export of ${EXPORT_DIR}: already done."
fi
