#!/usr/bin/env bash
# Daily check of the hosting provider's TSM (IBM Storage Protect) backup, run as
# root by manuspectrum-tsm-check.timer from the root-owned copy Ansible installs
# in /usr/local/lib/manuspectrum/tsm-check (manual run: systemctl start
# manuspectrum-tsm-check.service). The provider's own daily job copies /var/log
# and /data; this script never calls dsmc, it only reads what that job leaves.
#
# Backup good: the provider's report was written today (local date of its
# modification time) and holds the line `Successful incremental backup of '<fs>'`
# for every required filespace. A report left from an earlier day, or one where a
# filespace did not finish, is not a success.
# Includes good: the include file binds every log directory to the log class,
# with one line `include <dir>/.../* <class>` each (the word in any case, blanks
# between the fields; a line starting with `*` is a comment).
#
# Metrics, in METRICS_TEXTFILE_DIR, written as the directory's owner:
#   manuspectrum_tsm_check.prom
#     manuspectrum_tsm_check_enabled     1 when dsmc is installed, 0 otherwise
#     manuspectrum_tsm_log_include_ok    1 when every include line is present
#   manuspectrum_tsm_backup_success.prom, written only when the backup is good
#     manuspectrum_tsm_backup_last_success_timestamp_seconds
#       modification time of the report
# Without dsmc (rehearsal VMs, CI) the run writes both gauges at 0 and exits 0.
#
# Environment (the unit reads /etc/manuspectrum/tsm-check.env):
#   METRICS_TEXTFILE_DIR     absolute, existing (required)
#   TSM_LOG_DIRS             space-separated absolute directories (default /var/log)
#   TSM_REQUIRED_FILESPACES  space-separated (default "/data /var/log")
#   TSM_LOG_CLASS            management class (default LOG_ROTATED_FILES_MG)
#   TSM_REPORT               provider's report (default
#                            /var/spool/tsm/log/dsmc.incremental.local.log)
#   TSM_INCLEXCL             include file (default /var/spool/tsm/etc/inclexcl.def)
#   TSM_CHECK_DSMC           program whose presence enables the check (default dsmc)
# Exit: 0 backup and includes good, 1 one of them is not, 2 wrong configuration.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-metrics.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/lib-metrics.sh"

log() { printf 'tsm-check: %s\n' "$*" >&2; }
usage_die() { log "FAIL: $*"; exit 2; }

LOG_DIRS="${TSM_LOG_DIRS:-/var/log}"
FILESPACES="${TSM_REQUIRED_FILESPACES:-/data /var/log}"
CLASS="${TSM_LOG_CLASS:-LOG_ROTATED_FILES_MG}"
REPORT="${TSM_REPORT:-/var/spool/tsm/log/dsmc.incremental.local.log}"
INCLEXCL="${TSM_INCLEXCL:-/var/spool/tsm/etc/inclexcl.def}"
DSMC="${TSM_CHECK_DSMC:-dsmc}"

out_dir="${METRICS_TEXTFILE_DIR:-}"
[[ "$out_dir" == /* && -d "$out_dir" ]] || usage_die "METRICS_TEXTFILE_DIR must be an existing absolute directory (got '$out_dir')"

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

# The textfile directory belongs to the service account: the files are built in
# root's own temporary directory and written there as the directory's owner.
publish() { # publish NAME
  # shellcheck disable=SC2016 # $1 expands in the inner shell.
  local owner write='cat >"$1.tmp" && chmod 0644 "$1.tmp" && mv -f "$1.tmp" "$1"'
  owner="$(stat -c %U "$out_dir")"
  if [ "$owner" = "$(id -un)" ]; then
    sh -c "$write" _ "$out_dir/$1" <"$stage/$1"
  else
    runuser -u "$owner" -- sh -c "$write" _ "$out_dir/$1" <"$stage/$1"
  fi || log "WARNING: $1 could not be written to $out_dir"
}

write_check_metrics() { # write_check_metrics ENABLED INCLUDE_OK
  metrics_open "$stage/manuspectrum_tsm_check.prom"
  metric_family manuspectrum_tsm_check_enabled gauge "1 when the TSM client is installed and the provider backup is checked"
  metric_sample manuspectrum_tsm_check_enabled "$1"
  metric_family manuspectrum_tsm_log_include_ok gauge "1 when every log directory is bound to the TSM log class"
  metric_sample manuspectrum_tsm_log_include_ok "$2"
  metrics_commit && publish manuspectrum_tsm_check.prom
}

if ! command -v "$DSMC" >/dev/null 2>&1; then
  log "dsmc not installed, nothing checked"
  write_check_metrics 0 0
  exit 0
fi

status=0

# Binary-safe: file names in the report may hold any byte.
backup_good() {
  local mtime fs
  [ -f "$REPORT" ] || { log "FAIL: the provider's report $REPORT is missing"; return 1; }
  mtime="$(stat -c %Y "$REPORT")"
  if [ "$(date -d "@$mtime" +%F)" != "$(date +%F)" ]; then
    log "FAIL: the provider's report is dated $(date -d "@$mtime" +%F), not today"
    return 1
  fi
  for fs in $FILESPACES; do
    if ! LC_ALL=C grep -aFxq -- "Successful incremental backup of '$fs'" "$REPORT"; then
      log "FAIL: the report has no successful incremental backup of '$fs'"
      return 1
    fi
  done
  REPORT_MTIME="$mtime"
}

includes_good() {
  local dir ok=0
  for dir in $LOG_DIRS; do
    if ! [ -f "$INCLEXCL" ] || ! LC_ALL=C awk -v want="$dir/.../*" -v class="$CLASS" '
        NF == 3 && tolower($1) == "include" && $2 == want && $3 == class { found = 1 }
        END { exit !found }' "$INCLEXCL"; then
      log "FAIL: $INCLEXCL has no 'include $dir/.../* $CLASS' line"
      ok=1
    fi
  done
  return "$ok"
}

REPORT_MTIME=""
if backup_good; then
  metrics_open "$stage/manuspectrum_tsm_backup_success.prom"
  metric_family manuspectrum_tsm_backup_last_success_timestamp_seconds gauge "Unix time of the last good provider backup report"
  metric_sample manuspectrum_tsm_backup_last_success_timestamp_seconds "$REPORT_MTIME"
  metrics_commit && publish manuspectrum_tsm_backup_success.prom
else
  status=1
fi

if includes_good; then
  write_check_metrics 1 1
else
  write_check_metrics 1 0
  status=1
fi

[ "$status" -ne 0 ] || log "backup and include lines are good"
exit "$status"
