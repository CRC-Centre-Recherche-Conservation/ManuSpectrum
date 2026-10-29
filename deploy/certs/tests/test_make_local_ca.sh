#!/usr/bin/env bash
# deploy/certs/tests/test_make_local_ca.sh
# Tests of make-local-ca.sh against the host's openssl. Prints `ok N` /
# `not ok N`; exits non-zero on failure.
# shellcheck disable=SC2317  # helpers are called through check
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../make-local-ca.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N=0
FAILED=0
check() { # check DESCRIPTION COMMAND...
  local desc="$1"
  shift
  N=$((N + 1))
  if "$@" >/dev/null 2>&1; then
    echo "ok $N - $desc"
  else
    echo "not ok $N - $desc"
    FAILED=1
  fi
}
mode_is() { [ "$(stat -c %a "$2")" = "$1" ]; }
fp() { openssl x509 -in "$1" -noout -fingerprint -sha256; }

D="$TMP/certs"
check "issues for two names" "$SCRIPT" "$D" manuspectrum.test www.manuspectrum.test
check "ca.crt exists" test -s "$D/ca.crt"
check "ca.key is 0600" mode_is 600 "$D/ca.key"
check "fullchain.pem exists" test -s "$D/fullchain.pem"
check "privkey.pem is 0640" mode_is 640 "$D/privkey.pem"
check "fullchain.pem is 0640" mode_is 640 "$D/fullchain.pem"
check "no serial file left in the directory" test ! -e "$D/ca.srl"
check "chain verifies against the CA" openssl verify -CAfile "$D/ca.crt" "$D/fullchain.pem"
san="$(openssl x509 -in "$D/fullchain.pem" -noout -ext subjectAltName 2>&1)"
check "SAN lists the first name" grep -q 'DNS:manuspectrum.test' <<<"$san"
check "SAN lists the second name" grep -q 'DNS:www.manuspectrum.test' <<<"$san"
check "CA is CA:TRUE critical" bash -c "openssl x509 -in '$D/ca.crt' -noout -ext basicConstraints | tr -d '\n' | grep -q 'critical.*CA:TRUE'"
check "server certificate is not a CA" bash -c "openssl x509 -in '$D/fullchain.pem' -noout -ext basicConstraints | grep -q 'CA:FALSE'"
check "server key is 2048 bits" bash -c "openssl pkey -in '$D/privkey.pem' -noout -text | grep -q 'Private-Key: (2048 bit'"
check "server key matches the certificate" bash -c "[ \"\$(openssl x509 -in '$D/fullchain.pem' -noout -pubkey)\" = \"\$(openssl pkey -in '$D/privkey.pem' -pubout)\" ]"
check "server validity is at most 397 days" openssl x509 -in "$D/fullchain.pem" -noout -checkend $((397 * 86400 - 3600))
check "server certificate does not outlive 398 days" bash -c "! openssl x509 -in '$D/fullchain.pem' -noout -checkend $((398 * 86400))"

ca_before="$(fp "$D/ca.crt")"
srv_before="$(fp "$D/fullchain.pem")"
check "second run succeeds" "$SCRIPT" "$D" manuspectrum.test
check "second run keeps the CA" test "$ca_before" = "$(fp "$D/ca.crt")"
check "second run re-issues the server certificate" test "$srv_before" != "$(fp "$D/fullchain.pem")"
check "re-issued certificate verifies" openssl verify -CAfile "$D/ca.crt" "$D/fullchain.pem"

check "no name is a usage error (exit 2)" bash -c "'$SCRIPT' '$TMP/x'; [ \$? -eq 2 ]"
check "no argument is a usage error (exit 2)" bash -c "'$SCRIPT'; [ \$? -eq 2 ]"
check "a name with a shell or SAN separator is refused (exit 2)" bash -c "'$SCRIPT' '$TMP/y' 'a.test,DNS:evil'; [ \$? -eq 2 ]"
check "usage error writes nothing" test ! -e "$TMP/x"

S="$TMP/selfsigned"
check "--self-signed succeeds" "$SCRIPT" --self-signed "$S" manuspectrum.test
check "--self-signed writes fullchain.pem and privkey.pem only" bash -c "[ \"\$(ls '$S' | sort | tr '\n' ' ')\" = 'fullchain.pem privkey.pem ' ]"
check "--self-signed privkey is 0640" mode_is 640 "$S/privkey.pem"
check "--self-signed carries the SAN" bash -c "openssl x509 -in '$S/fullchain.pem' -noout -ext subjectAltName | grep -q 'DNS:manuspectrum.test'"

L="$TMP/split"
check "CA_DIR keeps the CA apart from the served pair" env CA_DIR="$L/ca" "$SCRIPT" "$L/live" manuspectrum.test
check "split: live/ holds fullchain.pem and privkey.pem only" bash -c "[ \"\$(ls '$L/live' | sort | tr '\n' ' ')\" = 'fullchain.pem privkey.pem ' ]"
check "split: ca/ holds ca.crt and ca.key only" bash -c "[ \"\$(ls '$L/ca' | sort | tr '\n' ' ')\" = 'ca.crt ca.key ' ]"
check "split: the chain verifies against ca/ca.crt" openssl verify -CAfile "$L/ca/ca.crt" "$L/live/fullchain.pem"

echo "1..$N"
exit "$FAILED"
