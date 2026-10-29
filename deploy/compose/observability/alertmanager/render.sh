#!/bin/sh
# Entrypoint of the alertmanager service: renders alertmanager.yml.in from the
# environment, then starts Alertmanager with the arguments of the service.
# Alertmanager cannot expand environment variables itself.
#
# Reads EMAIL_HOST, EMAIL_PORT, EMAIL_USE_TLS (true|false), EMAIL_HOST_USER
# (optional: when set, EMAIL_HOST_PASSWORD_FILE is given to Alertmanager as
# smtp_auth_password_file; the password is never read or printed here),
# ALERT_EMAILS (comma-separated recipients), ALERT_EMAIL_FROM and PUBLIC_HOST
# (the host's own name, sent as the SMTP HELO name, which some relays check
# against the connecting address). Any missing
# or malformed value exits 1 with a message on stderr, so the container does
# not start with a configuration that would drop alerts.
#
# ALERTMANAGER_DIR (templates), ALERTMANAGER_OUT, ALERTMANAGER_BIN and
# ALERTMANAGER_RENDER_ONLY=1 (render, then exit 0) let the tests run the same
# script without Alertmanager. ALERTMANAGER_VALIDATE_ONLY=1 checks every value
# and exits 0 without creating any file; `make alert-recipients` uses it.
set -eu

DIR="${ALERTMANAGER_DIR:-$(cd "$(dirname "$0")" && pwd)}"
OUT="${ALERTMANAGER_OUT:-/tmp/alertmanager.yml}"

fail() {
  echo "render.sh: $*" >&2
  exit 1
}

# valid VALUE REGEX
valid() { printf '%s\n' "$1" | grep -Eq "$2"; }

EMAIL_HOST="${EMAIL_HOST:-}"
EMAIL_PORT="${EMAIL_PORT:-25}"
EMAIL_USE_TLS="${EMAIL_USE_TLS:-false}"
EMAIL_HOST_USER="${EMAIL_HOST_USER:-}"
EMAIL_HOST_PASSWORD_FILE="${EMAIL_HOST_PASSWORD_FILE:-/run/secrets/email_password}"
ALERT_EMAILS="${ALERT_EMAILS:-}"
ALERT_EMAIL_FROM="${ALERT_EMAIL_FROM:-}"
PUBLIC_HOST="${PUBLIC_HOST:-}"

ADDRESS='^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$'

[ -n "$EMAIL_HOST" ] || fail "EMAIL_HOST is empty: set the SMTP relay in .env"
valid "$EMAIL_HOST" '^[A-Za-z0-9.-]+$' || fail "EMAIL_HOST is not a host name"
valid "$EMAIL_PORT" '^[0-9]{1,5}$' || fail "EMAIL_PORT is not a number"
case "$EMAIL_USE_TLS" in
  true | false) ;;
  *) fail "EMAIL_USE_TLS must be true or false" ;;
esac
if [ -n "$EMAIL_HOST_USER" ]; then
  valid "$EMAIL_HOST_USER" '^[A-Za-z0-9._@+-]+$' || fail "EMAIL_HOST_USER has characters outside A-Za-z0-9._@+-"
  valid "$EMAIL_HOST_PASSWORD_FILE" '^/[A-Za-z0-9._/-]+$' || fail "EMAIL_HOST_PASSWORD_FILE is not an absolute path"
fi
[ -n "$ALERT_EMAIL_FROM" ] || fail "ALERT_EMAIL_FROM is empty: set the sender in .env"
valid "$ALERT_EMAIL_FROM" "$ADDRESS" || fail "ALERT_EMAIL_FROM is not an e-mail address"
[ -n "$PUBLIC_HOST" ] || fail "PUBLIC_HOST is empty: set the public host name in .env"
valid "$PUBLIC_HOST" '^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$' || fail "PUBLIC_HOST is not a host name"
[ "${#PUBLIC_HOST}" -le 253 ] || fail "PUBLIC_HOST is longer than 253 characters"
[ -n "$(printf '%s' "$ALERT_EMAILS" | tr -d '[:space:]')" ] || fail "ALERT_EMAILS is empty: set a comma-separated list of recipients in .env"

# Sets `recipients` to the validated list. The positional parameters it
# changes are its own, so the arguments of the service survive for `exec`.
build_recipients() {
  case "$ALERT_EMAILS" in
    *,) fail "ALERT_EMAILS ends with a comma" ;;
  esac
  recipients=""
  old_ifs="$IFS"
  IFS=','
  set -f
  # shellcheck disable=SC2086  # splitting on the commas is the point
  set -- $ALERT_EMAILS
  set +f
  IFS="$old_ifs"
  for entry in "$@"; do
    address="$(printf '%s' "$entry" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    valid "$address" "$ADDRESS" || fail "ALERT_EMAILS holds an entry that is not an e-mail address: '$address'"
    recipients="${recipients:+$recipients,}$address"
  done
}
build_recipients

[ "${ALERTMANAGER_VALIDATE_ONLY:-}" = 1 ] && exit 0

auth="$(mktemp)"
trap 'rm -f "$auth"' EXIT
if [ -n "$EMAIL_HOST_USER" ]; then
  {
    printf "  smtp_auth_username: '%s'\n" "$EMAIL_HOST_USER"
    printf "  smtp_auth_password_file: '%s'\n" "$EMAIL_HOST_PASSWORD_FILE"
  } >"$auth"
fi

sed \
  -e "s|@SMTP_SMARTHOST@|$EMAIL_HOST:$EMAIL_PORT|" \
  -e "s|@SMTP_REQUIRE_TLS@|$EMAIL_USE_TLS|" \
  -e "s|@ALERT_EMAIL_FROM@|$ALERT_EMAIL_FROM|" \
  -e "s|@SMTP_HELLO@|$PUBLIC_HOST|" \
  -e "s|@ALERT_EMAILS@|$recipients|g" \
  -e "/^@SMTP_AUTH@\$/{r $auth
d
}" \
  "$DIR/alertmanager.yml.in" >"$OUT.new"
mv "$OUT.new" "$OUT"

[ "${ALERTMANAGER_RENDER_ONLY:-}" = 1 ] && exit 0
exec "${ALERTMANAGER_BIN:-/bin/alertmanager}" "$@"
