#!/usr/bin/env bash
# Sets one secret file of SECRETS_DIR from a value that is never an argument.
# Used to restore a secret from the vault (deploy/SECRETS.md) and to install a
# rotated one. The value is read without echo from the terminal (asked twice),
# or from stdin when stdin is not a terminal; it lives in shell memory and in
# the file, nowhere else, and is never printed.
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $(basename "$0") --dir SECRETS_DIR --names "NAME NAME..." [--force] NAME

Writes SECRETS_DIR/NAME (mode 0444, directory 0700, no trailing newline).
  terminal  the value is typed twice, without echo
  stdin     one value; a single trailing newline is removed
An existing file with another value is replaced only with --force; the same
value is reported as kept. An empty value is refused except for email_password.
USAGE
}

DIR="" NAMES="" FORCE=0 NAME=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --dir) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; DIR="$2"; shift 2 ;;
    --names) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; NAMES="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -*) usage >&2; exit 2 ;;
    *) [ -z "$NAME" ] || { usage >&2; exit 2; }; NAME="$1"; shift ;;
  esac
done
{ [ -n "$DIR" ] && [ -n "$NAMES" ] && [ -n "$NAME" ]; } || { usage >&2; exit 2; }

known=0
for n in $NAMES; do [ "$n" = "$NAME" ] && known=1; done
[ "$known" = 1 ] || { echo "secret-set.sh: '$NAME' is not one of: $NAMES" >&2; exit 1; }

if [ -t 0 ]; then
  IFS= read -rsp "Value for $NAME: " VALUE
  echo >&2
  IFS= read -rsp "Again: " AGAIN
  echo >&2
  [ "$VALUE" = "$AGAIN" ] || { echo "secret-set.sh: the two entries differ; nothing written" >&2; exit 1; }
  unset AGAIN
else
  # The sentinel keeps trailing newlines through the command substitution.
  VALUE="$(cat; printf x)"
  VALUE="${VALUE%x}"
  VALUE="${VALUE%$'\n'}"
  case "$VALUE" in
    *$'\n'*) echo "secret-set.sh: stdin holds more than one line; nothing written" >&2; exit 1 ;;
  esac
fi

if [ -z "$VALUE" ] && [ "$NAME" != email_password ]; then
  echo "secret-set.sh: an empty value is refused for $NAME" >&2
  exit 1
fi

install -d -m 0700 "$DIR"
FILE="$DIR/$NAME"
TMPFILE="$FILE.tmp"
trap 'rm -f "$TMPFILE"' EXIT

action=written
if [ -e "$FILE" ]; then
  CURRENT="$(cat "$FILE"; printf x)"
  CURRENT="${CURRENT%x}"
  if [ "$CURRENT" = "$VALUE" ]; then
    echo "$NAME: kept (same value)"
    exit 0
  fi
  [ "$FORCE" = 1 ] || {
    echo "secret-set.sh: $NAME exists with another value; use FORCE=yes (--force) to replace it" >&2
    exit 1
  }
  action=replaced
fi

(umask 077 && printf '%s' "$VALUE" >"$TMPFILE")
chmod 0444 "$TMPFILE"
mv -f "$TMPFILE" "$FILE"
echo "$NAME: $action"
