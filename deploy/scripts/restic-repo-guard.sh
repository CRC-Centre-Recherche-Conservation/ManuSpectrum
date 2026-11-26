#!/usr/bin/env bash
# Integrity guard of the restic repository, run as root just before the hosting
# provider's nightly TSM copy (the host role adds one line to the provider's job:
# this script runs first, and the job stops before `dsmc` when it exits 1, so an
# altered repository is not copied over the good versions TSM still holds).
# Installed by Ansible in /usr/local/lib/manuspectrum/repo-guard, next to
# lib-metrics.sh; it needs no restic password and no Docker: only sha256sum, find
# and stat.
#
# A restic file never changes once written: its name is the SHA-256 of its
# content (data/, index/, snapshots/, keys/), and restic only creates or deletes
# files. A file whose content no longer matches its name has been altered, and so
# is a name of that shape that is not a regular file (symlink, FIFO, directory,
# device; such an entry is never opened), and so is one of data, index, snapshots
# and keys replaced by a symlink. Only base names of exactly 64
# lowercase hex characters are checked; temporary names and locks/ are ignored.
# `config` has a fixed name: its SHA-256 is recorded at the first run in
# STATE_DIR/config.sha256 (written atomically) and compared at every run. A
# missing `config` while at least one hash-named entry remains is an alteration,
# whether or not a reference was recorded; a directory with no `config` and no
# hash-named entry is not a repository: the run logs it, exits 0 and leaves the
# metric files as the last real pass wrote them.
#
# Exit status. Exit 1 means an alteration was found, and nothing else: the
# provider's job stops before its copy on exit 1 only. The verdict never depends
# on the metrics directory, which belongs to the unprivileged service account: a
# missing directory or a failed write is logged as a WARNING and publication is
# skipped. Once an alteration is counted, the marker is written first, the metrics
# are published, and the run exits 1 whatever happens after.
#   0  intact, or nothing to check
#   1  an alteration was found; or the guard cannot judge the repository (an
#      unexpected error, a file that exists but cannot be read, a directory that
#      cannot be listed, a garbled config reference) while the last verdict was
#      "altered": STATE_DIR/altered, written by a pass that exits 1 and removed
#      only by a pass that finds the repository intact, keeps the verdict; while
#      the marker exists every pass is a full pass
#   2  wrong configuration, or the guard cannot judge the repository and the
#      last verdict was not "altered"
# An alteration already counted by the run, or a missing `config` already known,
# stands when the run then cannot judge the rest: it still exits 1 and writes the
# marker. The gauges are published after the state (marker, stamps) is updated.
# Every unexpected failure is caught by an ERR trap, logged as `FAIL: unexpected
# error (status N, line L)` and leaves through the same two statuses.
#
# Passes. A daily pass hashes the files whose ctime is newer than
# STATE_DIR/pass.stamp. The stamp holds the start time of the last successful
# pass minus PASS_MARGIN_SECONDS (1 hour): the network filesystem's ctimes come
# from the storage server's clock, not from this machine's, so a file changed
# shortly before or during a pass is hashed again by the next one. Writing a file
# in place always moves its ctime, which user tools cannot set back. A full pass
# hashes every file: it runs when STATE_DIR/full.stamp is missing or 3 days old
# or more (less PASS_MARGIN_SECONDS, so that a run starting a few seconds
# earlier than the day before still hashes everything), or when
# RESTIC_GUARD_FULL=1; the provider keeps the previous versions
# of an overwritten file about 7 days, so a weekly backstop would come too late.
# A stamp dated in the future (a clock that stepped back, or a tampered stamp)
# counts as missing and is logged. `config` is checked at every pass. Files are
# hashed by few sha256sum processes, not one per file; a file removed between
# the listing and the hashing (a prune) is not an alteration, one that still
# exists but cannot be hashed makes the pass unable to judge.
#
# Metrics, in METRICS_TEXTFILE_DIR, written as the directory's owner, once a
# repository is found:
#   manuspectrum_restic_repo_guard.prom
#     manuspectrum_restic_repo_guard_mismatches      altered files found (config included)
#     manuspectrum_restic_repo_guard_files_checked   named files hashed (config excluded)
#   manuspectrum_restic_repo_guard_success.prom, written only by a pass without mismatch
#     manuspectrum_restic_repo_guard_last_success_timestamp_seconds
#       start time of the pass
# A mismatch logs `restic-repo-guard: ALTERED: <path>` (the first 100, then one
# line with the total), writes STATE_DIR/altered and leaves the stamps and the
# success file untouched.
# Every message also goes to the system log under the tag restic-repo-guard
# (journalctl -t restic-repo-guard), where the provider's job, which discards
# stderr, leaves it readable; a missing or failing logger changes nothing.
#
# Environment:
#   METRICS_TEXTFILE_DIR   absolute (required; it need not exist)
#   RESTIC_REPOSITORY_DIR  absolute, the repository directory (required)
#   RESTIC_GUARD_STATE_DIR state directory (default /var/lib/manuspectrum/repo-guard)
#   RESTIC_GUARD_FULL      1 forces a full pass
set -Eeuo pipefail

log() {
  printf 'restic-repo-guard: %s\n' "$*" >&2 || true
  if command -v logger >/dev/null 2>&1; then logger -t restic-repo-guard -- "$*" || true; fi
}
usage_die() { log "FAIL: $*"; exit 2; }

state=""
mismatches=0
checked=0
config_missing=0

# The exit of an alteration: the marker first, then the metrics, then exit 1;
# nothing in between may turn the verdict into another status.
alteration_exit() {
  trap - ERR
  set +e
  : >"$state/altered" || log "WARNING: $state/altered could not be written"
  if [ "$mismatches" -gt "$ALTERED_LOG_MAX" ]; then
    log "$mismatches altered files in total, the first $ALTERED_LOG_MAX are listed above"
  fi
  if [ -d "${stage:-}" ]; then
    write_guard_metrics "$mismatches" "$checked" || log "WARNING: the metrics could not be published"
  fi
  log "FAIL: $mismatches altered file(s)"
  exit 1
}

# The one exit of every "cannot judge" case. What this run already found stands,
# and the verdict "altered" of an earlier pass is sticky.
cannot_judge() { # cannot_judge MESSAGE
  trap - ERR
  set +e
  log "FAIL: $*"
  if [ "$config_missing" -eq 1 ]; then
    config_missing=0
    report_altered "$repo/config (missing)"
  fi
  if [ "$mismatches" -gt 0 ]; then alteration_exit; fi
  if [ -n "$state" ] && [ -e "$state/altered" ]; then
    log "the last verdict was altered and no pass found the repository intact since"
    exit 1
  fi
  exit 2
}
trap 'cannot_judge "unexpected error (status $?, line $LINENO)"' ERR

FULL_INTERVAL_SECONDS=$((3 * 86400))
PASS_MARGIN_SECONDS=3600
ALTERED_LOG_MAX=100
HEX64='[0-9a-f]{64}'

out_dir="${METRICS_TEXTFILE_DIR:-}"
repo="${RESTIC_REPOSITORY_DIR:-}"
state_dir="${RESTIC_GUARD_STATE_DIR:-/var/lib/manuspectrum/repo-guard}"
[[ "$out_dir" == /* ]] || usage_die "METRICS_TEXTFILE_DIR must be an absolute directory (got '$out_dir')"
[[ "$repo" == /* ]] || usage_die "RESTIC_REPOSITORY_DIR must be an absolute directory (got '$repo')"
[[ "$state_dir" == /* ]] || usage_die "RESTIC_GUARD_STATE_DIR must be absolute (got '$state_dir')"
state="$state_dir"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -r "$HERE/lib-metrics.sh" ] || cannot_judge "$HERE/lib-metrics.sh is missing"
# shellcheck source=lib-metrics.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/lib-metrics.sh"

start="$(date +%s)"
stage="$(mktemp -d)"
trap 'rm -rf "${stage:-}"' EXIT

# The textfile directory belongs to the service account: the files are built in
# root's own temporary directory and written there as the directory's owner.
publish() { # publish NAME
  # shellcheck disable=SC2016 # $1 expands in the inner shell.
  local owner write='cat >"$1.tmp" && chmod 0644 "$1.tmp" && mv -f "$1.tmp" "$1"'
  if [ ! -d "$out_dir" ]; then
    log "WARNING: $out_dir is not a directory, $1 not written"
    return 0
  fi
  owner="$(stat -c %U "$out_dir")" || return 1
  if [ "$owner" = "$(id -un)" ]; then
    sh -c "$write" _ "$out_dir/$1" <"$stage/$1"
  else
    runuser -u "$owner" -- sh -c "$write" _ "$out_dir/$1" <"$stage/$1"
  fi || log "WARNING: $1 could not be written to $out_dir"
}

write_guard_metrics() { # write_guard_metrics MISMATCHES FILES_CHECKED
  metrics_open "$stage/manuspectrum_restic_repo_guard.prom" \
    && metric_family manuspectrum_restic_repo_guard_mismatches gauge "Restic repository files whose content no longer matches their name" \
    && metric_sample manuspectrum_restic_repo_guard_mismatches "$1" \
    && metric_family manuspectrum_restic_repo_guard_files_checked gauge "Restic repository files hashed by the last guard pass" \
    && metric_sample manuspectrum_restic_repo_guard_files_checked "$2" \
    && metrics_commit && publish manuspectrum_restic_repo_guard.prom
}

write_success_metrics() {
  metrics_open "$stage/manuspectrum_restic_repo_guard_success.prom" \
    && metric_family manuspectrum_restic_repo_guard_last_success_timestamp_seconds gauge "Unix time of the last guard pass without alteration" \
    && metric_sample manuspectrum_restic_repo_guard_last_success_timestamp_seconds "$start" \
    && metrics_commit && publish manuspectrum_restic_repo_guard_success.prom
}

report_altered() { # report_altered TEXT: counts it, logs the first ALTERED_LOG_MAX
  mismatches=$((mismatches + 1))
  if [ "$mismatches" -le "$ALTERED_LOG_MAX" ]; then log "ALTERED: $1"; fi
}

if [ ! -d "$repo" ]; then
  log "no restic repository at $repo, nothing checked"
  exit 0
fi

mkdir -p "$state"
chmod 0700 "$state"

cd "$repo"
dirs=()
for d in data index snapshots keys; do
  if [ -L "$d" ]; then
    report_altered "$repo/$d (not a directory)"
  elif [ -d "$d" ]; then
    dirs+=("$d")
  fi
done
find_names() { # find_names TEST...: hash-named entries of the four directories
  find "${dirs[@]}" -ignore_readdir_race -regextype posix-extended -regex ".*/$HEX64" "$@"
}

config_missing=0
if [ ! -f config ]; then
  first_named=""
  if [ "${#dirs[@]}" -gt 0 ]; then
    first_named="$(find_names -print -quit)" || cannot_judge "the repository could not be listed completely"
  fi
  if [ -n "$first_named" ]; then
    config_missing=1
  else
    log "no restic repository at $repo, nothing checked"
    exit 0
  fi
fi

record_reference() { # record_reference SUM: atomic, so a reference is never half written
  printf '%s\n' "$1" >"$state/config.sha256.tmp"
  mv -f "$state/config.sha256.tmp" "$state/config.sha256"
  log "recorded the reference of config"
}

stamp_ok() { # stamp_ok FILE: present and not dated in the future
  [ -f "$1" ] || return 1
  if [ "$(stat -c %Y "$1")" -gt "$start" ]; then
    log "$1 is dated in the future, treated as missing"
    return 1
  fi
}
full=0
if [ -e "$state/altered" ]; then
  log "the last verdict was altered: full pass"
  full=1
elif [ "${RESTIC_GUARD_FULL:-}" = 1 ] || ! stamp_ok "$state/pass.stamp" || ! stamp_ok "$state/full.stamp" \
  || [ $((start - $(stat -c %Y "$state/full.stamp"))) -ge $((FULL_INTERVAL_SECONDS - PASS_MARGIN_SECONDS)) ]; then
  full=1
fi

if [ "${#dirs[@]}" -gt 0 ]; then
  newer=()
  if [ "$full" -eq 0 ]; then newer=(-cnewer "$state/pass.stamp"); fi
  find_names -type f "${newer[@]}" -print0 >"$stage/list" \
    || cannot_judge "the repository could not be listed completely"
  find_names -not -type f "${newer[@]}" -print0 >"$stage/odd" \
    || cannot_judge "the repository could not be listed completely"
  while IFS= read -r -d '' path; do
    report_altered "$repo/$path (not a regular file)"
    checked=$((checked + 1))
  done <"$stage/odd"
  # A file removed by a prune between the listing and the hashing is not an
  # alteration; one that still exists but could not be hashed is: the pass
  # cannot judge the repository, after judging the sums it did compute.
  # sha256sum starts a line with a backslash when the path holds a backslash or a
  # newline; the hash then begins one character later.
  hash_rc=0
  xargs -0 -r sha256sum <"$stage/list" >"$stage/sums" 2>/dev/null || hash_rc=$?
  awk '{
      off = (substr($0, 1, 1) == "\\") ? 1 : 0
      path = substr($0, 67 + off); n = split(path, parts, "/")
      print ((parts[n] == substr($0, 1 + off, 64)) ? "OK" : "BAD:" path)
    }' "$stage/sums" >"$stage/verdicts"
  while IFS= read -r line; do
    case "$line" in
      BAD:*) report_altered "$repo/${line#BAD:}" ;;
    esac
    checked=$((checked + 1))
  done <"$stage/verdicts"
  if [ "$hash_rc" -ne 0 ]; then
    tr '\0' '\n' <"$stage/list" | LC_ALL=C sort >"$stage/listed"
    awk '{
        off = (substr($0, 1, 1) == "\\") ? 1 : 0
        path = substr($0, 67 + off)
        if (off) gsub(/\\\\/, "\\", path)
        print path
      }' "$stage/sums" | LC_ALL=C sort >"$stage/hashed"
    LC_ALL=C comm -23 "$stage/listed" "$stage/hashed" >"$stage/missing"
    while IFS= read -r path; do
      if [ -e "$path" ]; then cannot_judge "$repo/$path could not be read"; fi
    done <"$stage/missing"
  fi
fi

if [ "$config_missing" -eq 1 ]; then
  report_altered "$repo/config (missing)"
else
  config_sum="$(sha256sum config | cut -d' ' -f1)"
  if [ ! -f "$state/config.sha256" ]; then
    record_reference "$config_sum"
  else
    reference="$(cat "$state/config.sha256")"
    [[ "$reference" =~ ^[0-9a-f]{64}$ ]] || cannot_judge "$state/config.sha256 is not a SHA-256"
    if [ "$reference" != "$config_sum" ]; then report_altered "$repo/config"; fi
  fi
fi

if [ "$mismatches" -gt 0 ]; then alteration_exit; fi

rm -f "$state/altered"
touch -d "@$((start - PASS_MARGIN_SECONDS))" "$state/pass.stamp"
if [ "$full" -eq 1 ]; then touch -d "@$start" "$state/full.stamp"; fi
write_guard_metrics "$mismatches" "$checked" || log "WARNING: the metrics could not be published"
write_success_metrics || log "WARNING: the success metric could not be published"
log "$checked file(s) checked, repository intact ($([ "$full" -eq 1 ] && echo full || echo daily) pass)"
exit 0
