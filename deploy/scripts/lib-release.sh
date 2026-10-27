#!/usr/bin/env bash
# Shared parts of the release scripts (release-watch.sh, release-update.sh, the
# update front, release-ref-guard.sh). Sourced, never executed; it sets no shell
# option and leaves `set -euo pipefail` to the caller. Sources lib-metrics.sh
# from its own directory.
#
# Tags: a release tag is vX.Y.Z or vX.Y.Z-rc.N without leading zeros
# (RELEASE_TAG_FINAL_RE, RELEASE_TAG_RC_RE: the one definition, also used by
# release-ref-guard.sh). Components compare numerically up to 9 digits; a
# release candidate sorts below its final tag.
#
# State files: KEY=value lines in a state directory, never sourced or
# evaluated. Every line must match the pattern of its key (release_state_ok);
# an unknown key, a duplicate key or a malformed value refuses the whole file.
# Writes go through a temporary file in the same directory and a rename; an
# existing file keeps its mode, a new one is 0640.
#
# .env: the image line is rewritten by release_env_set_image, which accepts a
# digest reference only and replaces the last `MANUSPECTRUM_IMAGE=` line.
#
# Mail: release_mail reads ALERT_EMAILS and ALERT_EMAIL_FROM from ENV_FILE and
# pipes the message to RELEASE_SENDMAIL (default /usr/sbin/sendmail; set by
# tests only).
#
# Functions: release_tag_valid, release_tag_is_rc, release_semver_cmp,
# release_pick_candidate, release_state_ok, release_state_read,
# release_state_get, release_state_write, release_state_set, release_env_get,
# release_env_set_image, release_env_missing_keys, release_metrics_write,
# release_mail, release_slot_parse, release_metrics_from_state,
# release_compat_check.
# shellcheck disable=SC2034  # patterns read by the sourcing scripts

RELEASE_TAG_FINAL_RE='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
RELEASE_TAG_RC_RE='^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-rc\.(0|[1-9][0-9]*)$'

_RELEASE_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! declare -F metrics_open >/dev/null; then
  # shellcheck source=lib-metrics.sh
  # shellcheck source-path=SCRIPTDIR
  source "$_RELEASE_LIB_DIR/lib-metrics.sh"
fi

_release_err() { echo "lib-release: $*" >&2; }

release_tag_valid() { # release_tag_valid TAG
  [[ "${1-}" =~ $RELEASE_TAG_FINAL_RE || "${1-}" =~ $RELEASE_TAG_RC_RE ]]
}

release_tag_is_rc() { # release_tag_is_rc TAG
  [[ "${1-}" =~ $RELEASE_TAG_RC_RE ]]
}

# Prints major minor patch final(1|0) rc, space separated. Status 1 for a
# malformed tag or a component of more than 9 digits.
_release_semver_key() {
  local tag="$1" maj min pat rc=0 final=1
  if [[ "$tag" =~ $RELEASE_TAG_FINAL_RE ]]; then
    maj="${BASH_REMATCH[1]}" min="${BASH_REMATCH[2]}" pat="${BASH_REMATCH[3]}"
  elif [[ "$tag" =~ $RELEASE_TAG_RC_RE ]]; then
    maj="${BASH_REMATCH[1]}" min="${BASH_REMATCH[2]}" pat="${BASH_REMATCH[3]}" rc="${BASH_REMATCH[4]}" final=0
  else
    return 1
  fi
  [[ "$maj$min$pat$rc" != *[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]* ]] || return 1
  [ "${#maj}" -le 9 ] && [ "${#min}" -le 9 ] && [ "${#pat}" -le 9 ] && [ "${#rc}" -le 9 ] || return 1
  echo "$maj $min $pat $final $rc"
}

# Prints -1, 0 or 1 (A older than, equal to, newer than B).
release_semver_cmp() { # release_semver_cmp A B
  local ka kb a b i
  ka="$(_release_semver_key "${1-}")" || { _release_err "not a comparable release tag: '${1-}'"; return 1; }
  kb="$(_release_semver_key "${2-}")" || { _release_err "not a comparable release tag: '${2-}'"; return 1; }
  read -r -a a <<<"$ka"
  read -r -a b <<<"$kb"
  for i in 0 1 2 3 4; do
    if [ "$((10#${a[i]}))" -lt "$((10#${b[i]}))" ]; then echo -1; return 0; fi
    if [ "$((10#${a[i]}))" -gt "$((10#${b[i]}))" ]; then echo 1; return 0; fi
  done
  echo 0
}

# Reads tags on stdin (one per line) and prints the highest tag the CHANNEL
# allows that is strictly newer than CURRENT. `prod` takes final tags only,
# `rc` both kinds. Lines that are not release tags are ignored. Status 1 when
# there is none, 2 for an unknown channel or a malformed CURRENT.
release_pick_candidate() { # release_pick_candidate CHANNEL CURRENT < tags
  local channel="${1-}" current="${2-}" tag best=""
  case "$channel" in prod | rc) ;; *) _release_err "unknown channel '$channel'"; return 2 ;; esac
  _release_semver_key "$current" >/dev/null || { _release_err "malformed current tag '$current'"; return 2; }
  while IFS= read -r tag || [ -n "$tag" ]; do
    release_tag_valid "$tag" || continue
    _release_semver_key "$tag" >/dev/null || continue
    if [ "$channel" = prod ] && release_tag_is_rc "$tag"; then continue; fi
    [ "$(release_semver_cmp "$tag" "$current")" = 1 ] || continue
    if [ -z "$best" ] || [ "$(release_semver_cmp "$tag" "$best")" = 1 ]; then best="$tag"; fi
  done
  [ -n "$best" ] || return 1
  echo "$best"
}

# --- state files

_release_state_key_known() {
  [[ "${1-}" =~ ^(TAG|HELD_TAG|FROM_TAG|TO_TAG|IMAGE|COMMIT|ARMED_AT|CREATED_AT|SINCE|STARTED_AT|AT_EPOCH|WINDOW_END_EPOCH|NOTICE_ID|AT_PARIS|SECURITY|NOTIFIED|NEEDS_ANSIBLE|ROLLBACK_FAILED|COUNT|APPLIED_AT|REASON|OUTCOME|BY)$ ]]
}

# Status 0 when VALUE is acceptable for KEY. Keys and their patterns:
#   TAG HELD_TAG FROM_TAG TO_TAG   release tag (HELD_TAG may be empty)
#   IMAGE                          repository@sha256:<64 hex>
#   COMMIT                         40 lowercase hex
#   ARMED_AT CREATED_AT SINCE STARTED_AT AT_EPOCH WINDOW_END_EPOCH APPLIED_AT   epoch seconds
#   COUNT                          integer of at most 9 digits (rollbacks done)
#   NOTICE_ID                      integer (may be empty)
#   AT_PARIS                       YYYY-MM-DD HH:MM
#   SECURITY NOTIFIED NEEDS_ANSIBLE ROLLBACK_FAILED   0 or 1
#   REASON                         drift unarmed tag_moved env_keys managed_sources verify backup lock busy fetch (or empty)
#   OUTCOME                        refused or missed (or empty)
#   BY                             login [a-z_][a-z0-9_-]*
release_state_ok() { # release_state_ok KEY VALUE
  local key="${1-}" value="${2-}"
  _release_state_key_known "$key" || return 1
  case "$key" in
    TAG | FROM_TAG | TO_TAG) release_tag_valid "$value" ;;
    HELD_TAG) [ -z "$value" ] || release_tag_valid "$value" ;;
    IMAGE) [[ "$value" =~ ^[a-z0-9][a-z0-9._/-]*(:[0-9]+)?(/[a-z0-9._/-]+)?@sha256:[0-9a-f]{64}$ ]] ;;
    COMMIT) [[ "$value" =~ ^[0-9a-f]{40}$ ]] ;;
    ARMED_AT | CREATED_AT | SINCE | STARTED_AT | AT_EPOCH | WINDOW_END_EPOCH | APPLIED_AT) [[ "$value" =~ ^[0-9]{1,12}$ ]] ;;
    COUNT) [[ "$value" =~ ^[0-9]{1,9}$ ]] ;;
    NOTICE_ID) [[ "$value" =~ ^([0-9]{1,12})?$ ]] ;;
    AT_PARIS) [[ "$value" =~ ^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])\ ([01][0-9]|2[0-3]):[0-5][0-9]$ ]] ;;
    SECURITY | NOTIFIED | NEEDS_ANSIBLE | ROLLBACK_FAILED) [[ "$value" =~ ^[01]$ ]] ;;
    REASON) [[ "$value" =~ ^(drift|unarmed|tag_moved|env_keys|managed_sources|verify|backup|lock|busy|fetch)?$ ]] ;;
    OUTCOME) [[ "$value" =~ ^(refused|missed)?$ ]] ;;
    BY) [[ "$value" =~ ^[a-z_][a-z0-9_-]*$ ]] ;;
    *) return 1 ;;
  esac
}

# Validates FILE line by line and prints it as read. Status 1 (nothing
# printed) on any malformed line, unknown key or duplicate key.
release_state_read() { # release_state_read FILE
  local file="${1-}" line key value seen=" " out=""
  [ -f "$file" ] || { _release_err "no state file $file"; return 1; }
  while IFS= read -r line || [ -n "$line" ]; do
    if ! [[ "$line" =~ ^([A-Z_]+)=(.*)$ ]]; then
      _release_err "$file: malformed line"
      return 1
    fi
    key="${BASH_REMATCH[1]}" value="${BASH_REMATCH[2]}"
    release_state_ok "$key" "$value" || { _release_err "$file: refused value for $key"; return 1; }
    case "$seen" in *" $key "*) _release_err "$file: duplicate key $key"; return 1 ;; esac
    seen+="$key "
    out+="$line"$'\n'
  done <"$file"
  printf '%s' "$out"
}

release_state_get() { # release_state_get FILE KEY
  local content line key="${2-}"
  _release_state_key_known "$key" || { _release_err "unknown state key '$key'"; return 1; }
  content="$(release_state_read "${1-}")" || return 1
  while IFS= read -r line; do
    if [ "${line%%=*}" = "$key" ]; then
      printf '%s\n' "${line#*=}"
      return 0
    fi
  done <<<"$content"
  _release_err "${1-} has no $key"
  return 1
}

# Replaces FILE with exactly the given KEY=value pairs. Nothing is written
# when one is refused.
release_state_write() { # release_state_write FILE KEY=value ...
  local file="${1-}" arg key seen=" " tmp mode=640
  shift
  [ "$#" -gt 0 ] || { _release_err "no state to write"; return 1; }
  for arg in "$@"; do
    [[ "$arg" =~ ^([A-Z_]+)=(.*)$ ]] || { _release_err "malformed state pair"; return 1; }
    key="${BASH_REMATCH[1]}"
    release_state_ok "$key" "${BASH_REMATCH[2]}" || { _release_err "refused value for $key"; return 1; }
    case "$seen" in *" $key "*) _release_err "duplicate key $key"; return 1 ;; esac
    seen+="$key "
  done
  [ ! -e "$file" ] || mode="$(stat -c %a "$file")"
  tmp="$(mktemp "$(dirname "$file")/.state.XXXXXX")" || return 1
  if ! { printf '%s\n' "$@" >"$tmp" && chmod "$mode" "$tmp" && mv -f "$tmp" "$file"; }; then
    rm -f "$tmp"
    return 1
  fi
}

# Sets KEY to VALUE in FILE (created when absent) and keeps its other keys.
release_state_set() { # release_state_set FILE KEY VALUE [KEY VALUE ...]
  local file="${1-}" line i found content="" keys=() vals=() pairs=()
  shift
  { [ "$#" -gt 0 ] && [ "$(($# % 2))" = 0 ]; } || { _release_err "release_state_set needs KEY VALUE pairs"; return 1; }
  if [ -e "$file" ]; then
    content="$(release_state_read "$file")" || return 1
    while IFS= read -r line; do
      [ -z "$line" ] || { keys+=("${line%%=*}"); vals+=("${line#*=}"); }
    done <<<"$content"
  fi
  while [ "$#" -gt 0 ]; do
    found=""
    for i in "${!keys[@]}"; do
      if [ "${keys[i]}" = "$1" ]; then vals[i]="$2"; found=1; fi
    done
    [ -n "$found" ] || { keys+=("$1"); vals+=("$2"); }
    shift 2
  done
  for i in "${!keys[@]}"; do pairs+=("${keys[i]}=${vals[i]}"); done
  release_state_write "$file" "${pairs[@]}"
}

# --- .env

# Prints the value of the last `KEY=` line of FILE, one pair of surrounding
# quotes removed. Status 1 when the key is absent.
release_env_get() { # release_env_get FILE KEY
  local file="${1-}" key="${2-}" line value="" found=""
  [[ "$key" =~ ^[A-Z][A-Z0-9_]*$ ]] || { _release_err "bad key name"; return 1; }
  [ -f "$file" ] || { _release_err "no such file: $file"; return 1; }
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" == "$key="* ]]; then value="${line#*=}"; found=1; fi
  done <"$file"
  [ -n "$found" ] || return 1
  if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then value="${BASH_REMATCH[1]}"; fi
  printf '%s\n' "$value"
}

# Replaces the last `MANUSPECTRUM_IMAGE=` line of FILE with IMAGE, a digest
# reference. The new file is built beside the old one and renamed over it, with
# the same mode and owner.
release_env_set_image() { # release_env_set_image FILE IMAGE
  local file="${1-}" image="${2-}" last tmp
  [[ "$image" =~ ^[a-z0-9][a-z0-9._/:-]*@sha256:[0-9a-f]{64}$ ]] || { _release_err "not a digest reference: '$image'"; return 1; }
  [ -f "$file" ] || { _release_err "no such file: $file"; return 1; }
  last="$(grep -n '^MANUSPECTRUM_IMAGE=' "$file" | tail -n 1 | cut -d: -f1)"
  [ -n "$last" ] || { _release_err "$file has no MANUSPECTRUM_IMAGE line"; return 1; }
  tmp="$(mktemp "$(dirname "$file")/.env.XXXXXX")" || return 1
  if ! {
    awk -v n="$last" -v v="$image" 'NR == n { print "MANUSPECTRUM_IMAGE=" v; next } { print }' "$file" >"$tmp" \
      && chmod --reference="$file" "$tmp" \
      && { [ "$(stat -c %u:%g "$file")" = "$(stat -c %u:%g "$tmp")" ] || chown --reference="$file" "$tmp"; } \
      && mv -f "$tmp" "$file"
  }; then
    rm -f "$tmp"
    return 1
  fi
}

# Prints the keys of an .env.example text (FILE, or stdin when absent or `-`)
# that ENVFILE does not define, one per line, sorted. A key defined with an
# empty value is present. Always status 0 unless a file cannot be read.
release_env_missing_keys() { # release_env_missing_keys ENVFILE [EXAMPLE|-]
  local envfile="${1-}" example="${2:--}" line key
  [ -f "$envfile" ] || { _release_err "no such file: $envfile"; return 1; }
  if [ "$example" != - ] && [ ! -f "$example" ]; then _release_err "no such file: $example"; return 1; fi
  {
    if [ "$example" = - ]; then cat; else cat "$example"; fi
  } | while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^([A-Z][A-Z0-9_]*)= ]] || continue
    key="${BASH_REMATCH[1]}"
    grep -q "^$key=" "$envfile" || echo "$key"
  done | sort -u
}

# --- metrics

# Writes the release textfile FILE. Arguments are NAME=VALUE integers; every
# series is always emitted, 0 when not given. Names: watch_last_run (default
# now), verification_failed, armed, pending_since, pending_security, rollbacks,
# rollback_failed, update_last_success, scheduled, failed_git, failed_registry,
# failed_sigstore, failed_pull, failed_mail, failed_state,
# schedule_failed_refused, schedule_failed_missed.
release_metrics_write() { # release_metrics_write FILE [NAME=VALUE ...]
  local file="${1-}" arg name step reason
  local -A v=(
    [watch_last_run]="$(date +%s)" [verification_failed]=0 [armed]=0 [pending_since]=0 [pending_security]=0
    [rollbacks]=0 [rollback_failed]=0 [update_last_success]=0 [scheduled]=0
    [failed_git]=0 [failed_registry]=0 [failed_sigstore]=0 [failed_pull]=0 [failed_mail]=0 [failed_state]=0
    [schedule_failed_refused]=0 [schedule_failed_missed]=0
  )
  shift
  for arg in "$@"; do
    [[ "$arg" =~ ^([a-z_]+)=([0-9]+)$ ]] || { _release_err "bad metric argument '$arg'"; return 1; }
    name="${BASH_REMATCH[1]}"
    [ -n "${v[$name]+x}" ] || { _release_err "unknown metric '$name'"; return 1; }
    v[$name]="${BASH_REMATCH[2]}"
  done
  metrics_open "$file" || return 1
  {
    metric_family manuspectrum_release_watch_last_run_timestamp_seconds gauge "Unix time of the last release watch run" \
      && metric_sample manuspectrum_release_watch_last_run_timestamp_seconds "${v[watch_last_run]}" \
      && metric_family manuspectrum_release_watch_failed gauge "1 when a step of the last release watch failed" \
      && for step in git registry sigstore pull mail state; do
        metric_sample manuspectrum_release_watch_failed "${v[failed_$step]}" step "$step" || exit 1
      done \
      && metric_family manuspectrum_release_verification_failed gauge "1 when the signature or revision check of a release failed" \
      && metric_sample manuspectrum_release_verification_failed "${v[verification_failed]}" \
      && metric_family manuspectrum_release_armed gauge "1 when a release is armed and waits for an operator" \
      && metric_sample manuspectrum_release_armed "${v[armed]}" \
      && metric_family manuspectrum_release_pending_since_timestamp_seconds gauge "Unix time since which a release has been waiting, 0 when none" \
      && metric_sample manuspectrum_release_pending_since_timestamp_seconds "${v[pending_since]}" \
      && metric_family manuspectrum_release_pending_security gauge "1 when a waiting release carries a security fix" \
      && metric_sample manuspectrum_release_pending_security "${v[pending_security]}" \
      && metric_family manuspectrum_release_rollbacks_total counter "Updates rolled back since the state directory was created" \
      && metric_sample manuspectrum_release_rollbacks_total "${v[rollbacks]}" \
      && metric_family manuspectrum_release_rollback_failed gauge "1 when a rollback itself failed" \
      && metric_sample manuspectrum_release_rollback_failed "${v[rollback_failed]}" \
      && metric_family manuspectrum_release_update_last_success_timestamp_seconds gauge "Unix time of the last successful update, 0 when none" \
      && metric_sample manuspectrum_release_update_last_success_timestamp_seconds "${v[update_last_success]}" \
      && metric_family manuspectrum_release_scheduled_timestamp_seconds gauge "Unix time of the scheduled update slot, 0 when none" \
      && metric_sample manuspectrum_release_scheduled_timestamp_seconds "${v[scheduled]}" \
      && metric_family manuspectrum_release_schedule_failed gauge "1 when the scheduled update was refused or missed" \
      && for reason in refused missed; do
        metric_sample manuspectrum_release_schedule_failed "${v[schedule_failed_$reason]}" reason "$reason" || exit 1
      done
  } || { metrics_abort 2>/dev/null; return 1; }
  metrics_commit
}

# Rewrites the release textfile FILE from the state files of STATE_DIR: armed,
# pending (SINCE, SECURITY), rollbacks (COUNT, ROLLBACK_FAILED), current
# (APPLIED_AT) and scheduled (AT_EPOCH, OUTCOME). The series the watch owns
# (last run, failed steps, verification_failed) are carried over from the
# existing FILE (the last run is 0 when there is none: the engine never claims
# a watch ran); NAME=VALUE arguments, as for release_metrics_write, override
# anything. A state file that cannot be read counts as absent.
release_metrics_from_state() { # release_metrics_from_state STATE_DIR FILE [NAME=VALUE ...]
  local dir="${1-}" file="${2-}" line v outcome args=("watch_last_run=0")
  shift 2
  if [ -f "$file" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      if [[ "$line" =~ ^manuspectrum_release_watch_last_run_timestamp_seconds\ ([0-9]+)$ ]]; then args+=("watch_last_run=${BASH_REMATCH[1]}")
      elif [[ "$line" =~ ^manuspectrum_release_watch_failed\{step=\"(git|registry|sigstore|pull|mail|state)\"\}\ ([0-9]+)$ ]]; then args+=("failed_${BASH_REMATCH[1]}=${BASH_REMATCH[2]}")
      elif [[ "$line" =~ ^manuspectrum_release_verification_failed\ ([0-9]+)$ ]]; then args+=("verification_failed=${BASH_REMATCH[1]}")
      fi
    done <"$file"
  fi
  [ ! -f "$dir/armed" ] || { release_state_read "$dir/armed" >/dev/null 2>&1 && args+=("armed=1"); }
  v="$(release_state_get "$dir/pending" SINCE 2>/dev/null)" && args+=("pending_since=$v")
  v="$(release_state_get "$dir/pending" SECURITY 2>/dev/null)" && args+=("pending_security=$v")
  v="$(release_state_get "$dir/rollbacks" COUNT 2>/dev/null)" && args+=("rollbacks=$v")
  v="$(release_state_get "$dir/rollbacks" ROLLBACK_FAILED 2>/dev/null)" && args+=("rollback_failed=$v")
  v="$(release_state_get "$dir/current" APPLIED_AT 2>/dev/null)" && args+=("update_last_success=$v")
  v="$(release_state_get "$dir/scheduled" AT_EPOCH 2>/dev/null)" && args+=("scheduled=$v")
  outcome="$(release_state_get "$dir/scheduled" OUTCOME 2>/dev/null)" || outcome=""
  case "$outcome" in refused | missed) args+=("schedule_failed_$outcome=1") ;; esac
  release_metrics_write "$file" "${args[@]}" "$@"
}

# --- mail

# Sends one message to ALERT_EMAILS from ALERT_EMAIL_FROM (both read from
# ENV_FILE) with the subject `[ManuSpectrum][Release] SUFFIX`. The suffix is
# printable ASCII; the addresses are plain `local@domain`; any CR or LF in
# either refuses the message before sendmail runs.
release_mail() { # release_mail SUBJECT_SUFFIX BODY
  local suffix="${1-}" body="${2-}" to from addr sendmail="${RELEASE_SENDMAIL:-/usr/sbin/sendmail}" list=() part
  { [ -n "$suffix" ] && [[ "$suffix" != *[$'\r\n']* ]] && [ -z "$(printf '%s' "$suffix" | LC_ALL=C tr -d '\040-\176')" ]; } || { _release_err "mail subject must be non-empty printable ASCII on one line"; return 1; }
  to="$(release_env_get "${ENV_FILE:?ENV_FILE is not set}" ALERT_EMAILS)" || { _release_err "ALERT_EMAILS is not set"; return 1; }
  from="$(release_env_get "$ENV_FILE" ALERT_EMAIL_FROM)" || { _release_err "ALERT_EMAIL_FROM is not set"; return 1; }
  addr='^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$'
  [[ "$from" =~ $addr ]] || { _release_err "ALERT_EMAIL_FROM is not a plain address"; return 1; }
  [[ "$to" != ,* && "$to" != *, && "$to" != *,,* ]] || { _release_err "ALERT_EMAILS has an empty entry"; return 1; }
  IFS=',' read -r -a list <<<"$to"
  [ "${#list[@]}" -gt 0 ] || { _release_err "ALERT_EMAILS is empty"; return 1; }
  to=""
  for part in "${list[@]}"; do
    part="${part#"${part%%[![:space:]]*}"}"
    part="${part%"${part##*[![:space:]]}"}"
    [[ "$part" =~ $addr ]] || { _release_err "ALERT_EMAILS holds an address that is not plain"; return 1; }
    to+="${to:+, }$part"
  done
  {
    printf 'To: %s\n' "$to"
    printf 'From: %s\n' "$from"
    printf 'Subject: [ManuSpectrum][Release] %s\n' "$suffix"
    printf 'X-ManuSpectrum-Category: Release\n'
    printf 'MIME-Version: 1.0\nContent-Type: text/plain; charset=UTF-8\nContent-Transfer-Encoding: 8bit\n\n'
    printf '%s\n' "$body"
  } | "$sendmail" -oi -t
}

# --- deployment slot

# Parses "YYYY-MM-DD HH:MM" as Europe/Paris wall-clock time and prints one
# line, tab separated: UTC epoch, the UTC time "YYYY-MM-DD HH:MM", the Paris
# time as given. Refuses a time that does not exist or occurs twice (DST), a
# slot less than 10 minutes or more than 30 days ahead. "Now" is
# RELEASE_NOW_EPOCH when set (tests), else the clock.
release_slot_parse() { # release_slot_parse "YYYY-MM-DD HH:MM"
  python3 -I - "${1-}" "${RELEASE_NOW_EPOCH:-}" <<'PY'
import re
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

text, now_arg = sys.argv[1], sys.argv[2]
if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}", text):
    sys.exit("slot must be written YYYY-MM-DD HH:MM (Paris time)")
try:
    wall = datetime.strptime(text, "%Y-%m-%d %H:%M")
except ValueError:
    sys.exit("slot is not a valid date and time")
paris = ZoneInfo("Europe/Paris")
first = wall.replace(tzinfo=paris, fold=0)
second = wall.replace(tzinfo=paris, fold=1)
utc = first.astimezone(timezone.utc)
if utc.astimezone(paris).replace(tzinfo=None) != wall:
    sys.exit(f"{text} does not exist in Paris (clocks go forward): choose another time")
if second.astimezone(timezone.utc) != utc:
    sys.exit(f"{text} occurs twice in Paris (clocks go back): choose a time outside 02:00-03:00 that day")
epoch = int(utc.timestamp())
now = int(now_arg) if now_arg else int(time.time())
if epoch - now < 600:
    sys.exit("slot must be at least 10 minutes ahead")
if epoch - now > 30 * 86400:
    sys.exit("slot must be at most 30 days ahead")
print(f"{epoch}\t{utc.strftime('%Y-%m-%d %H:%M')}\t{text}")
PY
}

# --- compatibility of a tag with this host

# Checks that the host can take the release TAG of the checkout APP_DIR: every
# key of the tag's deploy/compose/.env.example is in ENVFILE, and the files
# Ansible installs at the tag (release-managed.sh, next to this library) equal
# MANAGED_SOURCES. Status 0 when both hold. Otherwise status 1, with
# RELEASE_COMPAT_REASON (env_keys or managed_sources) and
# RELEASE_COMPAT_MESSAGE set for the caller; nothing is printed.
release_compat_check() { # release_compat_check APP_DIR ENVFILE TAG MANAGED_SOURCES
  local app="${1-}" envfile="${2-}" tag="${3-}" sources="${4-}" missing managed diff_out differing
  RELEASE_COMPAT_REASON="" RELEASE_COMPAT_MESSAGE=""
  missing="$(git -C "$app" show "refs/tags/$tag:deploy/compose/.env.example" | release_env_missing_keys "$envfile" -)" || {
    RELEASE_COMPAT_REASON=env_keys RELEASE_COMPAT_MESSAGE="cannot read deploy/compose/.env.example at $tag"
    return 1
  }
  if [ -n "$missing" ]; then
    RELEASE_COMPAT_REASON=env_keys RELEASE_COMPAT_MESSAGE="$envfile lacks keys that $tag expects: $(tr '\n' ' ' <<<"$missing")"
    return 1
  fi
  if [ ! -f "$sources" ]; then
    RELEASE_COMPAT_REASON=managed_sources RELEASE_COMPAT_MESSAGE="$sources does not exist: run Ansible from a laptop checkout at $tag, then retry"
    return 1
  fi
  managed="$(cd "$app" && bash "$_RELEASE_LIB_DIR/release-managed.sh" --ref "refs/tags/$tag" --repo "$app")" || {
    RELEASE_COMPAT_REASON=managed_sources RELEASE_COMPAT_MESSAGE="cannot fingerprint the managed files at $tag"
    return 1
  }
  if ! diff_out="$(diff <(printf '%s\n' "$managed") "$sources")"; then
    differing="$(grep '^[<>]' <<<"$diff_out" | sed 's/^[<>] [0-9a-f]*  //' | sort -u)"
    RELEASE_COMPAT_REASON=managed_sources RELEASE_COMPAT_MESSAGE="files installed by Ansible differ between $tag and this host:
$differing
Re-run Ansible from a laptop checkout at $tag, then retry."
    return 1
  fi
}
