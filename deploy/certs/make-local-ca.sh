#!/usr/bin/env bash
# deploy/certs/make-local-ca.sh
# Local certificate authority for the rehearsal domain (CERT_MODE=local), and
# the self-signed placeholder that lets nginx start before the first ACME run.
#
#   make-local-ca.sh DIR NAME [NAME...]
#       Keeps DIR/ca.crt and DIR/ca.key when they exist (CA: RSA 4096, 10
#       years), else creates them. Always issues a new server certificate for
#       every NAME (RSA 2048, 397 days, SAN = every NAME, CN = first NAME)
#       into DIR/fullchain.pem (server certificate then CA) and
#       DIR/privkey.pem.
#   make-local-ca.sh --self-signed DIR NAME [NAME...]
#       Writes only DIR/fullchain.pem and DIR/privkey.pem, self-signed, 30 days.
#
# Needs openssl >= 3.0 on the PATH (x509 -copy_extensions). Exit 2: usage.
set -euo pipefail

usage() {
  echo "usage: ${0##*/} [--self-signed] DIR NAME [NAME...]" >&2
  exit 2
}

SELF_SIGNED=0
if [ "${1:-}" = "--self-signed" ]; then
  SELF_SIGNED=1
  shift
fi
[ "$#" -ge 2 ] || usage
DIR="$1"
shift
[ -n "$DIR" ] || usage

NAME_RE='^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$'
SAN=""
for name in "$@"; do
  if ! [[ "$name" =~ $NAME_RE ]]; then
    echo "invalid host name: $name" >&2
    exit 2
  fi
  if [[ "$name" =~ ^[0-9]+(\.[0-9]+){3}$ ]]; then
    SAN="${SAN:+$SAN,}IP:$name"
  else
    SAN="${SAN:+$SAN,}DNS:$name"
  fi
done
CN="$1"

command -v openssl >/dev/null || {
  echo "openssl is required on the PATH" >&2
  exit 1
}
major="$(openssl version | awk '{split($2, v, "."); print v[1]}')"
if [ "$major" -lt 3 ] 2>/dev/null; then
  echo "openssl >= 3.0 is required (found $(openssl version))" >&2
  exit 1
fi

umask 077
mkdir -p "$DIR"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

SERVER_EXT="subjectAltName=$SAN
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth"

new_csr() { # new_csr KEYFILE CSRFILE
  openssl req -new -newkey rsa:2048 -nodes -keyout "$1" -out "$2" \
    -subj "/CN=$CN" -addext "$SERVER_EXT" 2>/dev/null
}

install_pair() { # install_pair FULLCHAIN KEY
  install -m 0640 "$1" "$DIR/fullchain.pem"
  install -m 0640 "$2" "$DIR/privkey.pem"
}

if [ "$SELF_SIGNED" -eq 1 ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -keyout "$WORK/key.pem" -out "$WORK/cert.pem" \
    -days 30 -subj "/CN=$CN" -addext "$SERVER_EXT" 2>/dev/null
  install_pair "$WORK/cert.pem" "$WORK/key.pem"
  exit 0
fi

if [ -s "$DIR/ca.crt" ] && [ -s "$DIR/ca.key" ]; then
  echo "keeping the existing CA in $DIR"
else
  openssl req -x509 -newkey rsa:4096 -nodes -keyout "$WORK/ca.key" -out "$WORK/ca.crt" \
    -days 3650 -subj "/CN=ManuSpectrum local CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" 2>/dev/null
  install -m 0600 "$WORK/ca.key" "$DIR/ca.key"
  install -m 0644 "$WORK/ca.crt" "$DIR/ca.crt"
fi

new_csr "$WORK/key.pem" "$WORK/server.csr"
openssl x509 -req -in "$WORK/server.csr" -CA "$DIR/ca.crt" -CAkey "$DIR/ca.key" \
  -CAcreateserial -CAserial "$WORK/ca.srl" -days 397 -copy_extensions copy \
  -out "$WORK/server.crt" 2>/dev/null
cat "$WORK/server.crt" "$DIR/ca.crt" >"$WORK/fullchain.pem"
openssl verify -CAfile "$DIR/ca.crt" "$WORK/server.crt" >/dev/null
install_pair "$WORK/fullchain.pem" "$WORK/key.pem"
echo "issued $DIR/fullchain.pem for: $*"
