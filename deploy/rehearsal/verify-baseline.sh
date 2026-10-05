#!/usr/bin/env bash
# Checks the host baseline applied by host-baseline.sh. Prints one
# `OK <point>` or `MISMATCH <point>` line per check; exits 0 only when every
# check is OK. Before Ansible, /etc/docker/daemon.json must be absent and
# vm.max_map_count is only printed; `--after-ansible` requires
# vm.max_map_count >= 262144 and /etc/docker/daemon.json present. Runs as
# root inside the VM.
set -uo pipefail
export LC_ALL=C

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<USAGE
Usage: sudo $(basename "$0") [--after-ansible] [--env FILE] [-h]

Checks the baseline; one "OK" or "MISMATCH" line per point, exit code 0 when everything is OK.
  --after-ansible  requires vm.max_map_count >= 262144 and /etc/docker/daemon.json present
  --env FILE       variables file (default: rehearsal.env next to the script)
USAGE
}

env_file="$HERE/rehearsal.env"
after=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --after-ansible) after=1; shift ;;
    --env) env_file="${2:?--env needs a value}"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# Values given in the environment win over the variables file.
declare -A caller_env=()
for v in ADMIN_USER ADMIN2_USER ADMIN2_PUBKEY SSH_PASSWORD_AUTH UNATTENDED_REBOOT UNATTENDED_REBOOT_TIME ROOT_ALIAS SMTP_RELAY NFS_SERVER NFS_EXPORT NFS_EXPORT_DIR DOCKER_APT_CODENAME NFS_VERS; do
  [ -z "${!v+x}" ] || caller_env[$v]="${!v}"
done
if [ -f "$env_file" ]; then
  # shellcheck disable=SC1090,SC1091
  . "$env_file"
fi
for v in "${!caller_env[@]}"; do
  printf -v "$v" '%s' "${caller_env[$v]}"
done
ADMIN_USER="${ADMIN_USER:-admin1}"
ADMIN2_USER="${ADMIN2_USER:-admin2}"
SSH_PASSWORD_AUTH="${SSH_PASSWORD_AUTH:-no}"
UNATTENDED_REBOOT="${UNATTENDED_REBOOT:-false}"
UNATTENDED_REBOOT_TIME="${UNATTENDED_REBOOT_TIME:-03:30}"
NFS_VERS="${NFS_VERS:-4}"
NFS_SERVER="${NFS_SERVER:-192.168.123.1}"
NFS_EXPORT_DIR="${NFS_EXPORT_DIR:-/srv/ms-rehearsal-data}"
NFS_EXPORT="${NFS_EXPORT:-$NFS_EXPORT_DIR}"
if [ "$NFS_EXPORT" != "$NFS_EXPORT_DIR" ]; then
  echo "NFS_EXPORT (${NFS_EXPORT}) must equal NFS_EXPORT_DIR (${NFS_EXPORT_DIR}), the directory the host exports: drop NFS_EXPORT from rehearsal.env." >&2
  exit 1
fi
SMTP_RELAY="${SMTP_RELAY:-}"
ADMIN2_PUBKEY="${ADMIN2_PUBKEY:-}"

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (sudo)." >&2
  exit 1
fi

failed=0
check() { # check POINT EXIT-CODE
  if [ "$2" -eq 0 ]; then echo "OK $1"; else echo "MISMATCH $1"; failed=1; fi
}

sshd_t="$(sshd -T 2>/dev/null)"
grep -qx 'permitrootlogin no' <<<"$sshd_t"
check "sshd : PermitRootLogin no" "$?"
grep -qx "passwordauthentication ${SSH_PASSWORD_AUTH}" <<<"$sshd_t"
check "sshd : PasswordAuthentication ${SSH_PASSWORD_AUTH}" "$?"

ufw_out="$(ufw status verbose 2>/dev/null)"
grep -q '^Status: active' <<<"$ufw_out" && grep -q 'Default: deny (incoming), allow (outgoing)' <<<"$ufw_out"
check "ufw : actif, deny in / allow out" "$?"
grep -Eq '^22/tcp +LIMIT IN' <<<"$ufw_out"
check "ufw : limit 22/tcp" "$?"
grep -Eq '^80/tcp +ALLOW IN' <<<"$ufw_out"
check "ufw : allow 80/tcp" "$?"
grep -Eq '^443/tcp +ALLOW IN' <<<"$ufw_out"
check "ufw : allow 443/tcp" "$?"
rc=0; [ "$(grep -v '(v6)' <<<"$ufw_out" | grep -Ec ' (ALLOW|LIMIT|DENY|REJECT) IN')" -eq 3 ] || rc=1
check "ufw: no other inbound rule" "$rc"

fail2ban-client status sshd >/dev/null 2>&1
check "fail2ban : jail sshd" "$?"

docker version --format '{{.Server.Version}}' >/dev/null 2>&1
check "docker: server present" "$?"
dpkg-query -W docker-ce containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null 2>&1
check "docker: packages docker-ce, containerd.io, buildx and compose" "$?"
[ -f /etc/apt/sources.list.d/docker.sources ] && grep -q 'download.docker.com' /etc/apt/sources.list.d/docker.sources
check "docker: apt repository download.docker.com" "$?"
docker compose version >/dev/null 2>&1
check "docker: compose plugin" "$?"
docker buildx version >/dev/null 2>&1
check "docker: buildx plugin" "$?"
id -nG "$ADMIN_USER" 2>/dev/null | tr ' ' '\n' | grep -qx docker
check "${ADMIN_USER} in the docker group" "$?"

id -nG "$ADMIN_USER" 2>/dev/null | tr ' ' '\n' | grep -qx sudo
check "${ADMIN_USER} in the sudo group" "$?"
getent passwd "$ADMIN2_USER" >/dev/null
check "account ${ADMIN2_USER}" "$?"
id -nG "$ADMIN2_USER" 2>/dev/null | tr ' ' '\n' | grep -qx sudo
check "${ADMIN2_USER} in the sudo group" "$?"
getent passwd manuspectrum >/dev/null
check "account manuspectrum" "$?"
id -nG manuspectrum 2>/dev/null | tr ' ' '\n' | grep -qx docker
check "manuspectrum in the docker group" "$?"
! sudo -n -l -U manuspectrum true >/dev/null 2>&1
check "manuspectrum without sudo rights" "$?"
rc=0; [ "$(passwd -S manuspectrum 2>/dev/null | awk '{print $2}')" = "L" ] || rc=1
check "manuspectrum without password (locked)" "$rc"
if [ -n "$ADMIN2_PUBKEY" ]; then
  grep -qxF "$ADMIN2_PUBKEY" "/home/${ADMIN2_USER}/.ssh/authorized_keys" 2>/dev/null
  check "SSH key of ${ADMIN2_USER}" "$?"
fi
rc=0; [ -e /home/manuspectrum/.ssh/authorized_keys ] && rc=1
check "manuspectrum without authorized_keys" "$rc"

mount_opts="$(findmnt -n -t nfs4 -o OPTIONS /data 2>/dev/null)"
[ -n "$mount_opts" ] && grep -Eq "(^|,)vers=${NFS_VERS//./\\.}(\\.[0-9]+)?(,|$)" <<<"$mount_opts"
check "/data mounted over NFS ${NFS_VERS}" "$?"
findmnt --fstab -n -o SOURCE,FSTYPE /data 2>/dev/null | grep -q "^${NFS_SERVER}:${NFS_EXPORT} nfs4$"
check "/data in /etc/fstab" "$?"

uu="$(cat /etc/apt/apt.conf.d/50unattended-upgrades 2>/dev/null)"
grep -q "Automatic-Reboot \"${UNATTENDED_REBOOT}\"" <<<"$uu"
check "unattended-upgrades : Automatic-Reboot ${UNATTENDED_REBOOT}" "$?"
grep -q "Automatic-Reboot-Time \"${UNATTENDED_REBOOT_TIME}\"" <<<"$uu"
check "unattended-upgrades: time ${UNATTENDED_REBOOT_TIME}" "$?"
grep -q "Automatic-Reboot-WithUsers \"${UNATTENDED_REBOOT}\"" <<<"$uu"
check "unattended-upgrades : Automatic-Reboot-WithUsers ${UNATTENDED_REBOOT}" "$?"
grep -q 'Remove-Unused-Kernel-Packages "true"' <<<"$uu" && grep -q 'Remove-Unused-Dependencies "true"' <<<"$uu"
check "unattended-upgrades : options Remove-*" "$?"
rc=0; [ "$(grep -c 'distro_codename}' <<<"$uu")" -ge 4 ] || rc=1
check "unattended-upgrades: four origins" "$rc"
rc=0; [ "$(grep -c '^APT::Periodic' /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null)" -eq 4 ] || rc=1
check "20auto-upgrades: four APT::Periodic lines" "$rc"

systemctl is-active --quiet postfix
check "postfix active" "$?"
rc=0; [ "$(postconf -h relayhost 2>/dev/null)" = "$SMTP_RELAY" ] || rc=1
check "postfix: relayhost" "$rc"

max_map="$(sysctl -n vm.max_map_count 2>/dev/null)"
if [ "$after" -eq 0 ]; then
  echo "INFO vm.max_map_count = ${max_map} (not checked before Ansible)"
  [ ! -e /etc/docker/daemon.json ]
  check "/etc/docker/daemon.json absent (before Ansible)" "$?"
else
  [ "${max_map:-0}" -ge 262144 ]
  check "vm.max_map_count >= 262144 (after Ansible, value ${max_map})" "$?"
  [ -e /etc/docker/daemon.json ]
  check "/etc/docker/daemon.json present (after Ansible)" "$?"
fi

exit "$failed"
