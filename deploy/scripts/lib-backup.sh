#!/usr/bin/env bash
# Shared parts of the backup scripts (backup.sh today). Sourced, never
# executed; `set -euo pipefail` is the caller's. Needs log, die, compose and
# as_app from lib-replace-data.sh (sourced first by the caller).
#
# Constants: the retention of the restic repository and the paths restic does
# not back up, in one place for the script, its tests and deploy/BACKUP.md.
# Functions: usage_die, backup_config, restic_run, restic_run_with, take_lock,
# write_metrics.
# shellcheck disable=SC2154,SC2034  # inputs assigned by the sourcing script; constants it reads
#
# Inputs set by the caller before calling a function:
#   compose_cmd     array: the Compose invocation
#   BACKUP_DUMP_DIR (set by backup_config) holds the lock file

RETENTION_KEEP_DAILY=7
RETENTION_KEEP_WEEKLY=4
RETENTION_KEEP_MONTHLY=6

# Paths of the restic container (see the restic service in compose.yaml).
RESTIC_EXCLUDES=(
  '/backup/media/previous-*'
  '/backup/media/.restore-*'
  '/backup/media/archestemp'
  '/backup/media/export_deliverables'
  '/backup/secrets/*.new'
  '/backup/secrets/aside'
)

# A wrong invocation or configuration, found before anything ran: exit 2.
usage_die() { log "FAIL: $*"; exit 2; }

# Reads what Compose resolves from .env (the `backup` profile included) and
# sets PGDBNAME, PGUSERNAME, APP_UID, APP_GID, MEDIA_HOST_DIR, MANUSPECTRUM_IMAGE,
# RESTIC_REPOSITORY_DIR (source of /repo), BACKUP_DUMP_DIR (source of /backup/db
# without its `latest` directory) and SECRETS_DIR (source of /backup/secrets).
backup_config() {
  local json key value
  json="$(compose --profile backup config --format json)" || die "compose config failed"
  while IFS=$'\t' read -r key value; do
    [[ "$key" =~ ^[A-Z_]+$ ]] || continue
    printf -v "$key" '%s' "$value"
  done < <(printf '%s' "$json" | python3 -c '
import json
import sys

services = json.load(sys.stdin)["services"]
web, postgres, restic = services["web"], services["postgres"], services["restic"]


def source(service, target):
    return next((v["source"] for v in service.get("volumes", []) if v.get("target") == target), "")


user = web.get("user", "")
dump_dir = source(restic, "/backup/db")
if dump_dir.endswith("/latest"):
    dump_dir = dump_dir[: -len("/latest")]
values = {
    "PGDBNAME": web.get("environment", {}).get("PGDBNAME") or "",
    "PGUSERNAME": postgres.get("environment", {}).get("POSTGRES_USER") or "",
    "APP_UID": user.split(":")[0],
    "APP_GID": user.split(":")[-1] if ":" in user else "",
    "MEDIA_HOST_DIR": source(web, "/srv/media"),
    "MANUSPECTRUM_IMAGE": web.get("image", ""),
    "RESTIC_REPOSITORY_DIR": source(restic, "/repo"),
    "BACKUP_DUMP_DIR": dump_dir,
    "SECRETS_DIR": source(restic, "/backup/secrets"),
}
for key, value in values.items():
    print(f"{key}\t{value}")
')
  [[ "${PGDBNAME:-}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "PGDBNAME '${PGDBNAME:-}' is not a plain identifier"
  [ -n "${PGUSERNAME:-}" ] || die "PGUSERNAME is empty in the Compose configuration"
  if ! [[ "${APP_UID:-}" =~ ^[1-9][0-9]*$ && "${APP_GID:-}" =~ ^[1-9][0-9]*$ ]]; then
    die "APP_UID and APP_GID must be numeric and not 0 (got '${APP_UID:-}' and '${APP_GID:-}')"
  fi
  local name
  for name in MEDIA_HOST_DIR RESTIC_REPOSITORY_DIR BACKUP_DUMP_DIR SECRETS_DIR; do
    [[ "${!name:-}" == /* ]] || die "$name is empty or not an absolute path in the Compose configuration (set it in $ENV_FILE)"
  done
  [ -n "${MANUSPECTRUM_IMAGE:-}" ] || die "the web service has no image in the Compose configuration"
}

# One run of the restic service: no local cache, a held repository lock is
# retried. RESTIC_INTERACTIVE=1 keeps the terminal attached (make restic).
restic_run() {
  local tty_flag=(-T)
  [ "${RESTIC_INTERACTIVE:-}" != 1 ] || tty_flag=()
  compose --profile backup run --rm --no-deps "${tty_flag[@]}" restic --no-cache --retry-lock 30m "$@"
}

restic_run_with() { # restic_run_with HOSTDIR:CONTAINERDIR ARGS...: restic_run with one more mount
  local mount="$1"
  shift
  compose --profile backup run --rm --no-deps -T -v "$mount" restic --no-cache --retry-lock 30m "$@"
}

# Holds the lock of BACKUP_DUMP_DIR on fd 9 for the life of the process; a
# wait of 0 refuses at once.
take_lock() { # take_lock WAIT_SECONDS
  local wait="$1" flags=(-n)
  [ "$wait" = 0 ] || flags=(-w "$wait")
  exec 9>"$BACKUP_DUMP_DIR/.lock" || die "cannot open $BACKUP_DUMP_DIR/.lock"
  flock "${flags[@]}" 9 || die "another backup or restore is running (lock $BACKUP_DUMP_DIR/.lock)"
}

# Writes a Prometheus textfile of gauges for the node_exporter textfile
# collector: temporary name, then rename, so a reader never sees half a file.
write_metrics() { # write_metrics FILE NAME VALUE [NAME VALUE ...]
  local file="$1" name value
  shift
  { [ "$(($# % 2))" = 0 ] && [ "$#" -gt 0 ]; } || return 1
  : >"$file.tmp" || return 1
  while [ "$#" -gt 0 ]; do
    name="$1" value="$2"
    shift 2
    [[ "$name" =~ ^manuspectrum_[a-z_]+$ ]] || { rm -f "$file.tmp"; return 1; }
    [[ "$value" =~ ^[0-9]+(\.[0-9]+)?$ ]] || { rm -f "$file.tmp"; return 1; }
    printf '# HELP %s ManuSpectrum backup job: %s\n# TYPE %s gauge\n%s %s\n' \
      "$name" "${name#manuspectrum_}" "$name" "$name" "$value" >>"$file.tmp" || return 1
  done
  chmod 0644 "$file.tmp" && mv -f "$file.tmp" "$file"
}
