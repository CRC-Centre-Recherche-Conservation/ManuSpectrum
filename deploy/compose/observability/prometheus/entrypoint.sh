#!/bin/sh
# Entrypoint of the prometheus service: writes the file_sd target list of the
# edge probes from PUBLIC_HOST, then starts Prometheus with the arguments of
# the service. Prometheus cannot expand environment variables itself, and the
# container is read-only, so the list goes to the tmpfs /tmp.
#
# PUBLIC_HOST must be a host name (letters, digits, dots, hyphens). Each target
# carries the label rehearsal="true" when the name ends in `.test` (CI and
# rehearsal, whose certificate no public authority signs) and "false" otherwise;
# the CertificateInvalid alert reads it.
#
# PROMETHEUS_TARGETS_DIR and PROMETHEUS_BIN let the tests run the same script
# without Prometheus.
set -eu

DIR="${PROMETHEUS_TARGETS_DIR:-/tmp}"
HOST="${PUBLIC_HOST:-}"

fail() {
  echo "entrypoint.sh: $*" >&2
  exit 1
}

[ -n "$HOST" ] || fail "PUBLIC_HOST is empty: set the public host name in .env"
printf '%s\n' "$HOST" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$' \
  || fail "PUBLIC_HOST is not a host name"
[ "${#HOST}" -le 253 ] || fail "PUBLIC_HOST is longer than 253 characters"

case "$HOST" in
  *.test) rehearsal=true ;;
  *) rehearsal=false ;;
esac

printf '[{"targets": ["https://%s/healthz"], "labels": {"rehearsal": "%s"}}]\n' \
  "$HOST" "$rehearsal" >"$DIR/edge_targets.json.new"
mv "$DIR/edge_targets.json.new" "$DIR/edge_targets.json"

exec "${PROMETHEUS_BIN:-/bin/prometheus}" "$@"
