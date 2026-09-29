#!/usr/bin/env bash
# Applies the host baseline on a fresh Ubuntu: SSH, UFW, fail2ban, Docker CE,
# accounts, /data over NFS, unattended-upgrades, postfix. vm.max_map_count
# and /etc/docker/daemon.json are left untouched (Ansible's job). Runs as
# root inside the VM; reads rehearsal.env (next to the script, or --env FILE).
# Idempotent: each step reports "déjà fait" when nothing changes.
set -euo pipefail
export LC_ALL=C

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<USAGE
Usage : sudo $(basename "$0") [--env FICHIER] [-h]

Applique la baseline système. Relançable : ce qui est déjà en
place est signalé « déjà fait ».
  --env FICHIER  fichier de variables (défaut : rehearsal.env à côté du script)
Variables : ADMIN_USER, ADMIN2_USER, ADMIN2_PUBKEY, SSH_PASSWORD_AUTH,
UNATTENDED_REBOOT, UNATTENDED_REBOOT_TIME, ROOT_ALIAS, SMTP_RELAY,
NFS_SERVER, NFS_EXPORT, DOCKER_APT_CODENAME (voir rehearsal.env.example).
USAGE
}

env_file="$HERE/rehearsal.env"
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --env) env_file="${2:?--env attend une valeur}"; shift 2 ;;
    *) echo "Option inconnue : $1" >&2; usage >&2; exit 2 ;;
  esac
done

# Values given in the environment win over the variables file.
declare -A caller_env=()
for v in ADMIN_USER ADMIN2_USER ADMIN2_PUBKEY SSH_PASSWORD_AUTH UNATTENDED_REBOOT UNATTENDED_REBOOT_TIME ROOT_ALIAS SMTP_RELAY NFS_SERVER NFS_EXPORT DOCKER_APT_CODENAME NFS_VERS; do
  [ -z "${!v+x}" ] || caller_env[$v]="${!v}"
done
if [ -f "$env_file" ]; then
  # shellcheck disable=SC1090,SC1091
  . "$env_file"
else
  echo "Pas de rehearsal.env (${env_file}) : valeurs sûres par défaut."
fi
for v in "${!caller_env[@]}"; do
  printf -v "$v" '%s' "${caller_env[$v]}"
done
ADMIN_USER="${ADMIN_USER:-admin1}"
ADMIN2_USER="${ADMIN2_USER:-admin2}"
ADMIN2_PUBKEY="${ADMIN2_PUBKEY:-}"
SSH_PASSWORD_AUTH="${SSH_PASSWORD_AUTH:-no}"
UNATTENDED_REBOOT="${UNATTENDED_REBOOT:-false}"
UNATTENDED_REBOOT_TIME="${UNATTENDED_REBOOT_TIME:-03:30}"
ROOT_ALIAS="${ROOT_ALIAS:-}"
SMTP_RELAY="${SMTP_RELAY:-}"
NFS_SERVER="${NFS_SERVER:-192.168.123.1}"
NFS_EXPORT="${NFS_EXPORT:-/srv/ms-rehearsal-data}"
DOCKER_APT_CODENAME="${DOCKER_APT_CODENAME:-}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Ce script doit être lancé en root (sudo)." >&2
  exit 1
fi
case "$SSH_PASSWORD_AUTH" in yes | no) ;; *) echo "SSH_PASSWORD_AUTH doit valoir yes ou no." >&2; exit 1 ;; esac
case "$UNATTENDED_REBOOT" in true | false) ;; *) echo "UNATTENDED_REBOOT doit valoir true ou false." >&2; exit 1 ;; esac
if [ -n "$ROOT_ALIAS" ] && ! [[ "$ROOT_ALIAS" =~ ^[A-Za-z0-9._@+-]+$ ]]; then
  echo "ROOT_ALIAS doit être une adresse e-mail ou un compte local (sans | ni &)." >&2
  exit 1
fi
if ! id "$ADMIN_USER" >/dev/null 2>&1; then
  echo "Le compte ${ADMIN_USER} n'existe pas (ADMIN_USER)." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

# Writes stdin to $1 when the content differs; returns 0 when changed.
write_file() {
  local target="$1" tmp
  tmp="$(mktemp)"
  cat >"$tmp"
  if [ -f "$target" ] && cmp -s "$tmp" "$target"; then
    rm -f "$tmp"
    echo "déjà fait : ${target}"
    return 1
  fi
  install -D -m 0644 "$tmp" "$target"
  rm -f "$tmp"
  echo "écrit : ${target}"
}

echo "== Paquets"
apt-get update -qq
apt-get install -y -qq ufw fail2ban nfs-common ca-certificates curl gnupg unattended-upgrades >/dev/null

echo "== SSH"
sshd_dropin=/etc/ssh/sshd_config.d/10-baseline.conf
sshd_previous=""
[ ! -f "$sshd_dropin" ] || sshd_previous="$(cat "$sshd_dropin")"
if write_file "$sshd_dropin" <<SSHD; then
PermitRootLogin no
PasswordAuthentication ${SSH_PASSWORD_AUTH}
SSHD
  if ! sshd -t; then
    if [ -n "$sshd_previous" ]; then printf '%s\n' "$sshd_previous" >"$sshd_dropin"; else rm -f "$sshd_dropin"; fi
    echo "sshd -t refuse la configuration : drop-in ${sshd_dropin} annulé." >&2
    exit 1
  fi
  systemctl reload ssh
fi

echo "== UFW"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw limit 22/tcp >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
echo "UFW actif (règles idempotentes)."

echo "== fail2ban"
jail_changed=0
write_file /etc/fail2ban/jail.local <<'JAIL' && jail_changed=1
[sshd]
enabled = true
backend = systemd
JAIL
systemctl enable --now fail2ban >/dev/null || { echo "fail2ban ne démarre pas : journalctl -u fail2ban" >&2; exit 1; }
if [ "$jail_changed" -eq 1 ]; then
  systemctl restart fail2ban || { echo "fail2ban ne redémarre pas : journalctl -u fail2ban" >&2; exit 1; }
fi

echo "== Docker CE"
codename="$DOCKER_APT_CODENAME"
if [ -z "$codename" ]; then
  # shellcheck disable=SC1091
  codename="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")"
fi
http_code="$(curl -sSI -o /dev/null -w '%{http_code}' "https://download.docker.com/linux/ubuntu/dists/${codename}/Release" 2>/dev/null || true)"
case "$http_code" in
  200) ;;
  404)
    echo "Le dépôt Docker n'a pas de suite « ${codename} »." >&2
    echo "Relancez avec DOCKER_APT_CODENAME=noble dans rehearsal.env, puis notez la suite réellement utilisée en prod." >&2
    exit 1
    ;;
  *)
    echo "download.docker.com injoignable (réponse « ${http_code:-aucune} ») : vérifiez le DNS, le proxy et l'accès Internet de la VM." >&2
    exit 1
    ;;
esac
install -m 0755 -d /etc/apt/keyrings
if [ -s /etc/apt/keyrings/docker.asc ]; then
  echo "déjà fait : /etc/apt/keyrings/docker.asc"
else
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
fi
write_file /etc/apt/sources.list.d/docker.sources <<DOCKER || true
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${codename}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
DOCKER
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
usermod -aG docker "$ADMIN_USER"

echo "== Comptes"
if id "$ADMIN2_USER" >/dev/null 2>&1; then
  echo "déjà fait : compte ${ADMIN2_USER}"
else
  adduser --disabled-password --gecos "" "$ADMIN2_USER" >/dev/null
  echo "créé : ${ADMIN2_USER}"
fi
usermod -aG sudo "$ADMIN2_USER"
if [ -n "$ADMIN2_PUBKEY" ]; then
  install -d -m 0700 -o "$ADMIN2_USER" -g "$ADMIN2_USER" "/home/${ADMIN2_USER}/.ssh"
  touch "/home/${ADMIN2_USER}/.ssh/authorized_keys"
  if ! grep -qxF "$ADMIN2_PUBKEY" "/home/${ADMIN2_USER}/.ssh/authorized_keys"; then
    printf '%s\n' "$ADMIN2_PUBKEY" >>"/home/${ADMIN2_USER}/.ssh/authorized_keys"
  fi
  chown "$ADMIN2_USER:$ADMIN2_USER" "/home/${ADMIN2_USER}/.ssh/authorized_keys"
  chmod 0600 "/home/${ADMIN2_USER}/.ssh/authorized_keys"
fi
if id manuspectrum >/dev/null 2>&1; then
  echo "déjà fait : compte manuspectrum"
else
  adduser --disabled-password --gecos "" manuspectrum >/dev/null
  echo "créé : manuspectrum"
fi

echo "== /data (NFS)"
mkdir -p /data
fstab_line="${NFS_SERVER}:${NFS_EXPORT} /data nfs4 defaults,_netdev 0 0"
if grep -qxF "$fstab_line" /etc/fstab; then
  echo "déjà fait : ligne fstab de /data"
else
  # Replaces any other /data entry so a changed NFS_SERVER or NFS_EXPORT never leaves two.
  fstab_tmp="$(mktemp)"
  awk '$1 !~ /^#/ && $2 == "/data" {next} {print}' /etc/fstab >"$fstab_tmp"
  printf '%s\n' "$fstab_line" >>"$fstab_tmp"
  install -m 0644 "$fstab_tmp" /etc/fstab
  rm -f "$fstab_tmp"
  systemctl daemon-reload
  if findmnt -t nfs4 /data >/dev/null 2>&1; then umount /data; fi
fi
if findmnt -t nfs4 /data >/dev/null 2>&1; then
  echo "déjà fait : /data monté"
elif ! mount /data; then
  echo "Le montage de /data a échoué : vérifiez sur le portable « sudo ./host-nfs.sh » (export) et, avec firewalld, la zone « libvirt » (service nfs)." >&2
  exit 1
fi

echo "== Mises à jour automatiques"
write_file /etc/apt/apt.conf.d/50unattended-upgrades <<UU || true
Unattended-Upgrade::Allowed-Origins {
        "\${distro_id}:\${distro_codename}";
        "\${distro_id}:\${distro_codename}-security";
        "\${distro_id}ESMApps:\${distro_codename}-apps-security";
        "\${distro_id}ESM:\${distro_codename}-infra-security";
};
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-New-Unused-Dependencies "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "${UNATTENDED_REBOOT}";
Unattended-Upgrade::Automatic-Reboot-WithUsers "${UNATTENDED_REBOOT}";
Unattended-Upgrade::Automatic-Reboot-Time "${UNATTENDED_REBOOT_TIME}";
UU
write_file /etc/apt/apt.conf.d/20auto-upgrades <<'AU' || true
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::Download-Upgradeable-Packages "1";
APT::Periodic::AutocleanInterval "10";
AU

echo "== postfix"
if [ -n "$SMTP_RELAY" ]; then
  echo "postfix postfix/main_mailer_type select Satellite system" | debconf-set-selections
  echo "postfix postfix/relayhost string ${SMTP_RELAY}" | debconf-set-selections
else
  echo "postfix postfix/main_mailer_type select Local only" | debconf-set-selections
fi
echo "postfix postfix/mailname string $(hostname -f)" | debconf-set-selections
apt-get install -y -qq postfix >/dev/null
# debconf answers apply at first install only: re-apply the relay afterwards.
if [ "$(postconf -h relayhost)" != "$SMTP_RELAY" ]; then
  postconf -e "relayhost = ${SMTP_RELAY}"
  systemctl reload postfix 2>/dev/null || true
  echo "postfix : relayhost mis à jour."
fi
if [ -n "$ROOT_ALIAS" ]; then
  if grep -q '^root:' /etc/aliases; then
    sed -i "s|^root:.*|root: ${ROOT_ALIAS}|" /etc/aliases
  else
    printf 'root: %s\n' "$ROOT_ALIAS" >>/etc/aliases
  fi
  newaliases
fi
systemctl enable --now postfix >/dev/null || { echo "postfix ne démarre pas : journalctl -u postfix" >&2; exit 1; }

cat <<DONE

Baseline en place.
- vm.max_map_count et /etc/docker/daemon.json : laissés à Ansible, comme en prod.
- Mot de passe de ${ADMIN2_USER} : à poser à la main (sudo passwd ${ADMIN2_USER}).
- Déconnectez-vous puis reconnectez-vous pour que ${ADMIN_USER} prenne le groupe docker.
DONE
