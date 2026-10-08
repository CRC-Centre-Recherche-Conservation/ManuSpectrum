#!/usr/bin/env bash
# Checks the secret files of SECRETS_DIR without printing a value: one line per
# name, "ok" or the problem. Exit 1 on any problem.
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $(basename "$0") --dir SECRETS_DIR --names "NAME NAME..."

Per file: present, mode 0444, no trailing newline, not empty (email_password
may be), django_secret_key of at least 50 characters, admin_password of at
least 16, restic_password of at least 32. The directory must be 0700.
USAGE
}

DIR="" NAMES=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --dir) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; DIR="$2"; shift 2 ;;
    --names) [ "$#" -ge 2 ] || { usage >&2; exit 2; }; NAMES="$2"; shift 2 ;;
    *) usage >&2; exit 2 ;;
  esac
done
{ [ -n "$DIR" ] && [ -n "$NAMES" ]; } || { usage >&2; exit 2; }

BAD=0
problem() { echo "$1: $2"; BAD=1; }

if [ ! -d "$DIR" ]; then
  echo "directory: $DIR is missing"
  exit 1
fi
dir_mode="$(stat -c %a "$DIR")"
if [ "$dir_mode" = 700 ]; then echo "directory: ok"; else problem directory "mode is $dir_mode, expected 700"; fi

for name in $NAMES; do
  file="$DIR/$name"
  if [ ! -f "$file" ]; then
    problem "$name" "missing"
    continue
  fi
  issues=()
  mode="$(stat -c %a "$file")"
  [ "$mode" = 444 ] || issues+=("mode is $mode, expected 444")
  size="$(wc -c <"$file")"
  if [ "$size" -eq 0 ]; then
    [ "$name" = email_password ] || issues+=("empty")
  else
    [ "$(tail -c 1 "$file" | od -An -tx1 | tr -d ' \n')" != 0a ] || issues+=("ends with a newline")
  fi
  case "$name" in
    django_secret_key) [ "$size" -ge 50 ] || issues+=("shorter than 50 characters") ;;
    admin_password) [ "$size" -ge 16 ] || issues+=("shorter than 16 characters") ;;
    restic_password) [ "$size" -ge 32 ] || issues+=("shorter than 32 characters") ;;
  esac
  if [ "${#issues[@]}" -eq 0 ]; then
    echo "$name: ok"
  else
    problem "$name" "$(IFS=';'; joined="${issues[*]}"; echo "${joined//;/; }")"
  fi
done
exit "$BAD"
