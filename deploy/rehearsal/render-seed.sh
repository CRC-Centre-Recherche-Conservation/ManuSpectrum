#!/usr/bin/env bash
# Renders autoinstall/user-data.tmpl and autoinstall/meta-data into a seed
# directory. Placeholders: @@HOSTNAME@@ @@ADMIN_USER@@ @@PASSWORD_HASH@@
# @@SSH_PUBKEY@@ @@LOCALE@@ @@KEYBOARD@@ @@ROOT_SIZE@@. Values are inserted literally (no sed/awk escaping issues):
# each line holding a placeholder is split and rebuilt in bash.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<USAGE
Usage: $(basename "$0") --out DIR --pubkey FILE
          (--password-hash-file FILE | --password-hash HASH)
          [--admin-user admin1] [--hostname manuspectrum]
          [--locale en_US.UTF-8] [--keyboard us] [--root-size 50G]

Writes DIR/user-data and DIR/meta-data for the automatic installation.
  --out DIR             output directory (created if needed)
  --pubkey FILE         SSH public key (one line: ssh-ed25519, ssh-rsa, ecdsa-...)
  --password-hash-file FILE  file containing the SHA-512 hash (\$6\$...)
  --password-hash HASH  SHA-512 hash (\$6\$...) on the command line (tests)
  --admin-user NAME     administrator account (default: admin1)
  --hostname NAME       hostname (default: manuspectrum)
  --locale LOCALE       system locale (default: en_US.UTF-8; C.UTF-8 accepted)
  --keyboard LAYOUT     keyboard layout (default: us)
  --root-size SIZE      root logical volume, e.g. 50G (default: 50G)
USAGE
}

out="" pubkey_file="" hash="" hash_file="" admin_user="admin1" hostname="manuspectrum"
locale="en_US.UTF-8" keyboard="us" root_size="50G"
while [ $# -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --out) out="${2:?--out needs a value}"; shift 2 ;;
    --pubkey) pubkey_file="${2:?--pubkey needs a value}"; shift 2 ;;
    --password-hash) hash="${2:?--password-hash needs a value}"; shift 2 ;;
    --password-hash-file) hash_file="${2:?--password-hash-file needs a value}"; shift 2 ;;
    --locale) locale="${2:?--locale needs a value}"; shift 2 ;;
    --keyboard) keyboard="${2:?--keyboard needs a value}"; shift 2 ;;
    --root-size) root_size="${2:?--root-size needs a value}"; shift 2 ;;
    --admin-user) admin_user="${2:?--admin-user needs a value}"; shift 2 ;;
    --hostname) hostname="${2:?--hostname needs a value}"; shift 2 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [ -n "$hash_file" ]; then
  if [ ! -f "$hash_file" ]; then
    echo "Hash file not found: ${hash_file}" >&2
    exit 1
  fi
  hash="$(head -n1 "$hash_file")"
fi
if [ -z "$out" ] || [ -z "$pubkey_file" ] || [ -z "$hash" ]; then
  echo "Options --out, --pubkey and --password-hash-file (or --password-hash) are required." >&2
  usage >&2
  exit 2
fi

if ! [[ "$admin_user" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
  echo "Invalid account name: \"${admin_user}\"." >&2
  exit 1
fi
if ! [[ "$hostname" =~ ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$ ]]; then
  echo "Invalid hostname: \"${hostname}\"." >&2
  exit 1
fi
if ! [[ "$locale" =~ ^([a-z]{2,3}_[A-Z]{2}|C)\.UTF-8(@[a-z]+)?$ ]]; then
  echo "Invalid locale: \"${locale}\" (expected: C.UTF-8 or xx_YY.UTF-8[@modifier])." >&2
  exit 1
fi
if ! [[ "$keyboard" =~ ^[a-z]{2,3}$ ]]; then
  echo "Invalid keyboard layout: \"${keyboard}\"." >&2
  exit 1
fi
if ! [[ "$root_size" =~ ^[0-9]+G$ ]]; then
  echo "Invalid root volume size: \"${root_size}\" (expected: 50G)." >&2
  exit 1
fi
if [ ! -f "$pubkey_file" ]; then
  echo "Public key not found: ${pubkey_file}" >&2
  exit 1
fi
if [ "$(grep -c . "$pubkey_file")" -ne 1 ]; then
  echo "The key file must contain exactly one line." >&2
  exit 1
fi
pubkey="$(grep . "$pubkey_file")"
if ! [[ "$pubkey" =~ ^(ssh-(ed25519|rsa|dss)|ecdsa-sha2-nistp[0-9]+|sk-(ssh-ed25519|ecdsa-sha2-nistp256)@openssh\.com)\ [A-Za-z0-9+/=]+(\ [^\"\\]*)?$ ]]; then
  echo "The public key is not a valid SSH line." >&2
  exit 1
fi
if ! [[ "$hash" =~ ^\$6\$[^\"\\[:space:]]+$ ]]; then
  echo "The hash must be a SHA-512 hash (\$6\$...) with no quote or space." >&2
  exit 1
fi

# Replaces every occurrence of $2 by $3 in $1 (all literal).
replace_all() {
  local text="$1" token="$2" value="$3" result=""
  while [[ "$text" == *"$token"* ]]; do
    result+="${text%%"$token"*}${value}"
    text="${text#*"$token"}"
  done
  printf '%s' "${result}${text}"
}

template="$(cat "$HERE/autoinstall/user-data.tmpl"; printf x)"
template="${template%x}"
rendered="$(replace_all "$template" "@@HOSTNAME@@" "$hostname"; printf x)"
rendered="${rendered%x}"
rendered="$(replace_all "$rendered" "@@ADMIN_USER@@" "$admin_user"; printf x)"
rendered="${rendered%x}"
rendered="$(replace_all "$rendered" "@@PASSWORD_HASH@@" "$hash"; printf x)"
rendered="${rendered%x}"
rendered="$(replace_all "$rendered" "@@SSH_PUBKEY@@" "$pubkey"; printf x)"
rendered="${rendered%x}"
rendered="$(replace_all "$rendered" "@@LOCALE@@" "$locale"; printf x)"
rendered="${rendered%x}"
rendered="$(replace_all "$rendered" "@@KEYBOARD@@" "$keyboard"; printf x)"
rendered="${rendered%x}"
rendered="$(replace_all "$rendered" "@@ROOT_SIZE@@" "$root_size"; printf x)"
rendered="${rendered%x}"

# The check runs on the template without the inserted values.
leftover="$(replace_all "$template" "@@HOSTNAME@@" "" )"
leftover="$(replace_all "$leftover" "@@ADMIN_USER@@" "")"
leftover="$(replace_all "$leftover" "@@PASSWORD_HASH@@" "")"
leftover="$(replace_all "$leftover" "@@SSH_PUBKEY@@" "")"
leftover="$(replace_all "$leftover" "@@LOCALE@@" "")"
leftover="$(replace_all "$leftover" "@@KEYBOARD@@" "")"
leftover="$(replace_all "$leftover" "@@ROOT_SIZE@@" "")"
if [[ "$leftover" == *"@@"* ]]; then
  echo "A @@...@@ marker of the template was not substituted." >&2
  exit 1
fi

mkdir -p "$out"
printf '%s' "$rendered" >"$out/user-data"
sed "s/^local-hostname: .*/local-hostname: ${hostname}/" "$HERE/autoinstall/meta-data" >"$out/meta-data"
echo "Seed written to ${out} (user ${admin_user}, host ${hostname})."
