#!/usr/bin/env bash
# Daily archive of the closed server logs into TSM (IBM Storage Protect), run
# as root by manuspectrum-log-archive.timer, from the root-owned copy Ansible
# installs in /usr/local/lib/manuspectrum/log-archive (manual run: systemctl start
# manuspectrum-log-archive.service).
#
# Candidates, closed files only: the rotated nginx logs (NGINX_LOG_HOST_DIR/*.gz),
# every *.gz under /var/log, and the archived journal files
# (/var/log/journal/*/*@*.journal; the active system.journal and user-*.journal
# have no `@` in their name). Each file is archived once, identified by its
# sha256, since rsyslog renumbers rotated names (auth.log.2.gz becomes
# auth.log.3.gz). The state, one line `<sha256> <YYYY-MM-DD>` per archived file,
# is STATE_DIR/archived.sha256; lines older than 400 days are dropped.
#
# The new files go to one `dsmc archive -filelist` call. dsmc exit 0 and 8
# (warnings) count as success and record the files; any other code fails the
# run and records nothing, so the next run offers the same files again. Without
# dsmc (rehearsal VMs, CI) the run writes manuspectrum_log_archive_enabled 0
# and exits 0.
#
# Metrics, in METRICS_TEXTFILE_DIR (manuspectrum_log_archive.prom):
#   manuspectrum_log_archive_enabled   1 when dsmc is installed, 0 otherwise
#   manuspectrum_log_archive_files     files archived by the last run
# and, own file written only by a successful run
# (manuspectrum_log_archive_success.prom):
#   manuspectrum_log_archive_last_success_timestamp_seconds
#
# Environment (the unit reads /etc/manuspectrum/log-archive.env): METRICS_TEXTFILE_DIR
# (absolute, existing), NGINX_LOG_HOST_DIR
# (optional), LOG_ARCHIVE_STATE_DIR (default /var/lib/manuspectrum/log-archive),
# LOG_ARCHIVE_VAR_LOG (default /var/log), LOG_ARCHIVE_DSMC (default dsmc).
# Exit: 0 ok, 1 the archive failed, 2 wrong configuration.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-metrics.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/lib-metrics.sh"

log() { printf 'log-archive: %s\n' "$*" >&2; }
usage_die() { log "FAIL: $*"; exit 2; }

STATE_DIR="${LOG_ARCHIVE_STATE_DIR:-/var/lib/manuspectrum/log-archive}"
VAR_LOG="${LOG_ARCHIVE_VAR_LOG:-/var/log}"
DSMC="${LOG_ARCHIVE_DSMC:-dsmc}"
NGINX_LOGS="${NGINX_LOG_HOST_DIR:-}"
KEEP_DAYS=400

out_dir="${METRICS_TEXTFILE_DIR:-}"
[[ "$out_dir" == /* && -d "$out_dir" ]] || usage_die "METRICS_TEXTFILE_DIR must be an existing absolute directory (got '$out_dir')"

write_metrics() { # write_metrics ENABLED FILES
  metrics_open "$out_dir/manuspectrum_log_archive.prom"
  metric_family manuspectrum_log_archive_enabled gauge "1 when dsmc is installed and the closed logs are archived"
  metric_sample manuspectrum_log_archive_enabled "$1"
  metric_family manuspectrum_log_archive_files gauge "Files archived by the last run"
  metric_sample manuspectrum_log_archive_files "$2"
  metrics_commit || log "WARNING: the metric file could not be written to $out_dir"
}

if ! command -v "$DSMC" >/dev/null 2>&1; then
  log "dsmc not installed, nothing archived"
  write_metrics 0 0
  exit 0
fi

mkdir -p -m 0700 "$STATE_DIR"
exec 9>"$STATE_DIR/lock"
flock -n 9 || { log "another run holds the lock"; exit 0; }
state="$STATE_DIR/archived.sha256"
touch "$state"
today="$(date +%F)"
cutoff="$(date -d "$KEEP_DAYS days ago" +%F)"

declare -A known=()
while read -r sum day; do
  [[ "$sum" =~ ^[0-9a-f]{64}$ && "$day" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue
  known["$sum"]="$day"
done <"$state"

roots=("$VAR_LOG")
[ -z "$NGINX_LOGS" ] || [ ! -d "$NGINX_LOGS" ] || roots+=("$NGINX_LOGS")
declare -A new_files=() seen=()
listing="$(mktemp)"
trap 'rm -f "$listing" "${listing}.state"' EXIT
{
  find "${roots[@]}" -type f -name '*.gz' -print0 2>/dev/null || true
  find "$VAR_LOG/journal" -mindepth 2 -maxdepth 2 -type f -name '*@*.journal' -print0 2>/dev/null || true
} | while IFS= read -r -d '' path; do
  [[ "$path" != *$'\n'* ]] && printf '%s\n' "$path"
done | sort -u >"$listing"

while IFS= read -r path; do
  sum="$(sha256sum -- "$path" 2>/dev/null | cut -d' ' -f1)" || sum=""
  [[ "$sum" =~ ^[0-9a-f]{64}$ ]] || { log "WARNING: cannot read a candidate, skipped"; continue; }
  [ -z "${known[$sum]:-}" ] || continue
  [ -z "${seen[$sum]:-}" ] || continue
  seen["$sum"]=1
  new_files["$sum"]="$path"
done <"$listing"

count="${#new_files[@]}"
if [ "$count" -gt 0 ]; then
  filelist="$(mktemp)"
  trap 'rm -f "$listing" "${listing}.state" "$filelist"' EXIT
  for sum in "${!new_files[@]}"; do
    path="${new_files[$sum]}"
    if [[ "$path" == *" "* ]]; then printf '"%s"\n' "$path"; else printf '%s\n' "$path"; fi
  done >"$filelist"
  rc=0
  "$DSMC" archive -filelist="$filelist" -description="manuspectrum logs $today" || rc=$?
  case "$rc" in
    0) ;;
    8) log "dsmc finished with warnings (exit 8), the files count as archived" ;;
    *)
      log "FAIL: dsmc archive exited $rc, nothing recorded"
      write_metrics 1 0
      exit 1
      ;;
  esac
  for sum in "${!new_files[@]}"; do known["$sum"]="$today"; done
fi

for sum in "${!known[@]}"; do
  [[ "${known[$sum]}" < "$cutoff" ]] || printf '%s %s\n' "$sum" "${known[$sum]}"
done | sort >"${listing}.state"
cat "${listing}.state" >"$state.tmp" && mv -f "$state.tmp" "$state"

write_metrics 1 "$count"
metrics_open "$out_dir/manuspectrum_log_archive_success.prom"
metric_family manuspectrum_log_archive_last_success_timestamp_seconds gauge "Unix time of the last successful archive run"
metric_sample manuspectrum_log_archive_last_success_timestamp_seconds "$(date +%s)"
metrics_commit || log "WARNING: the success metric file could not be written to $out_dir"
log "archived $count file(s)"
