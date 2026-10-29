#!/usr/bin/env bash
# The hourly release watch: finds the newest release the channel allows, checks
# it (digest, signature, compatibility) and arms it for an operator. It never
# installs anything, never moves HEAD or the worktree of the checkout, and
# pulls only through release-verify.sh (signature first). Started by a systemd
# timer as the service account, from the root-owned copy in RELEASE_LIB_DIR;
# it is never run from the checkout (bash reads a script while it runs).
#
# Exit codes: 0 nothing wrong (including: another run holds the lock, nothing
# new, still publishing), 1 a step failed (the unit shows failed), 2 usage.
#
# Steps (one log line each):
#   0 lock STATE_DIR/lock without waiting: held -> "update running", exit 0,
#     metrics untouched
#   1 scheduled update: a slot that passed 15 minutes ago with no run recorded
#     in history.log becomes OUTCOME=missed (notice withdrawn, one mail)
#   1b Ansible running (ANSIBLE_MARKER exists): log, metrics refreshed, exit 0,
#     nothing probed or armed; a marker whose mtime is older than 2 h is an
#     interrupted run: the `state` failure is raised (exit 1) until it is removed
#   2 probes: github.com (git), ghcr.io/v2/ must answer 401 (registry),
#     tuf-repo-cdn.sigstore.dev (sigstore); a failure skips the rest
#   3 `git fetch --tags --prune --prune-tags origin` (refs only; git itself
#     refuses a tag that moved: « would clobber existing tag »; a local tag the
#     origin lacks is pruned); candidate = highest tag the
#     channel allows that is newer than `current`; none -> metrics, exit 0
#   4 a scheduled update with an empty OUTCOME is never replaced: a newer
#     candidate sets HELD_TAG and mails once; `armed` is not touched
#   5 armed for the candidate with the same registry digest -> NEEDS_ANSIBLE
#     recomputed (rewritten when it changed, no new mail), metrics
#     (verification_failed is kept: nothing was verified), a mail still owed,
#     exit 0
#   6 image digest of the tag, then release-verify with the channel policy.
#     A missing image or a failed check on a tag younger than
#     RELEASE_PUBLISH_GRACE (6 h) is "still publishing" and records nothing;
#     older, verification_failed=1 and exit 1. A pull failure is step `pull`
#   7 compatibility (release_compat_check) -> NEEDS_ANSIBLE
#   8 write `armed` and `pending` (SINCE = the oldest unapplied arming, SECURITY
#     sticky), the older armed image is removed unless it is current/previous.
#     SECURITY is the `Security-Fix: yes` trailer of the annotated tag
#   9 one mail per arming (NOTIFIED); a failed send is retried next run
# Every run after the lock writes the metrics (release_metrics_from_state).
#
# Configuration (environment, defaults for the host): APP_DIR, STATE_DIR,
# ENV_FILE (APP_DIR/deploy/compose/.env), MANAGED_SOURCES, RELEASE_LIB_DIR,
# RELEASE_IMAGE_REPO (ghcr.io/crc-centre-recherche-conservation/manuspectrum),
# RELEASE_REPO_URL (the GitHub repository, for the release link),
# RELEASE_PUBLISH_GRACE (21600), RELEASE_PROBE_GIT / _REGISTRY / _SIGSTORE
# (the three probe URLs), ANSIBLE_MARKER (/run/manuspectrum/ansible-running),
# RELEASE_NOW_EPOCH (tests). From .env:
# RELEASE_CHANNEL (prod|rc, default prod), METRICS_TEXTFILE_DIR, PUBLIC_HOST and
# the mail keys of release_mail.
set -uo pipefail

RELEASE_LIB_DIR="${RELEASE_LIB_DIR:-/usr/local/lib/manuspectrum/release}"
APP_DIR="${APP_DIR:-/home/manuspectrum/manuspectrum}"
STATE_DIR="${STATE_DIR:-/var/lib/manuspectrum/release}"
ENV_FILE="${ENV_FILE:-$APP_DIR/deploy/compose/.env}"
MANAGED_SOURCES="${MANAGED_SOURCES:-/etc/manuspectrum/managed-sources}"
IMAGE_REPO="${RELEASE_IMAGE_REPO:-ghcr.io/crc-centre-recherche-conservation/manuspectrum}"
REPO_URL="${RELEASE_REPO_URL:-https://github.com/CRC-Centre-Recherche-Conservation/ManuSpectrum}"
GRACE="${RELEASE_PUBLISH_GRACE:-21600}"
PROBE_GIT="${RELEASE_PROBE_GIT:-https://github.com/}"
PROBE_REGISTRY="${RELEASE_PROBE_REGISTRY:-https://ghcr.io/v2/}"
PROBE_SIGSTORE="${RELEASE_PROBE_SIGSTORE:-https://tuf-repo-cdn.sigstore.dev/}"
ANSIBLE_MARKER="${ANSIBLE_MARKER:-/run/manuspectrum/ansible-running}"

log() { echo "release-watch: $*"; }

# shellcheck source=lib-release.sh
# shellcheck source-path=SCRIPTDIR
source "$RELEASE_LIB_DIR/lib-release.sh" || { echo "release-watch: cannot read $RELEASE_LIB_DIR/lib-release.sh" >&2; exit 2; }

[ "$#" -eq 0 ] || { echo "usage: release-watch.sh" >&2; exit 2; }
[ -d "$APP_DIR/.git" ] || [ -f "$APP_DIR/.git" ] || { echo "release-watch: $APP_DIR is not a checkout" >&2; exit 2; }
[ -f "$ENV_FILE" ] || { echo "release-watch: no $ENV_FILE" >&2; exit 2; }

NOW="${RELEASE_NOW_EPOCH:-$(date +%s)}"
HOST_NAME="$(release_env_get "$ENV_FILE" PUBLIC_HOST 2>/dev/null || hostname)"
declare -A FAIL=([git]=0 [registry]=0 [sigstore]=0 [pull]=0 [mail]=0 [state]=0)
VERIFICATION=keep # keep | 0 | 1
CHANNEL=prod

exec 7>>"$STATE_DIR/lock" || { echo "release-watch: cannot open $STATE_DIR/lock" >&2; exit 2; }
flock -n 7 || { log "update running (or another watch): nothing to do"; exit 0; }

metrics_path() {
  local dir
  dir="$(release_env_get "$ENV_FILE" METRICS_TEXTFILE_DIR 2>/dev/null)" && [ -d "$dir" ] || return 1
  echo "$dir/manuspectrum_release.prom"
}

# Leaves after refreshing the release textfile; the exit code is 1 when a step failed.
finish() { # finish [CODE]
  local code="${1-0}" path step args=("watch_last_run=$NOW")
  for step in git registry sigstore pull mail state; do
    args+=("failed_$step=${FAIL[$step]}")
    [ "${FAIL[$step]}" = 0 ] || code=1
  done
  [ "$VERIFICATION" = keep ] || args+=("verification_failed=$VERIFICATION")
  if path="$(metrics_path)"; then
    release_metrics_from_state "$STATE_DIR" "$path" "${args[@]}" || log "metrics: could not write $path"
  else
    log "metrics: METRICS_TEXTFILE_DIR is not a directory, not written"
  fi
  exit "$code"
}

send_mail() { # send_mail SUBJECT BODY: status of the send, failures are logged
  release_mail "$1" "$2" || { log "mail: not sent ($1)"; FAIL[mail]=1; return 1; }
}

sget() { release_state_get "$STATE_DIR/$1" "$2" 2>/dev/null; }

# --- 1 scheduled update that was never run

SCHED_TAG="" SCHED_ACTIVE=0
if [ -f "$STATE_DIR/scheduled" ]; then
  if SCHED_TAG="$(sget scheduled TAG)"; then
    sched_outcome="$(sget scheduled OUTCOME)" || sched_outcome="?"
    sched_notified="$(sget scheduled NOTIFIED)" || sched_notified=0
    sched_at="$(sget scheduled AT_EPOCH)" || sched_at=""
    sched_created="$(sget scheduled CREATED_AT)" || sched_created=0
    if [ -z "$sched_outcome" ] && [ -n "$sched_at" ] && [ "$((sched_at + 900))" -lt "$NOW" ] && [ ! -e "$STATE_DIR/inflight" ]; then
      ran=0
      if [ -f "$STATE_DIR/history.log" ]; then
        while IFS=$'\t' read -r stamp _ _ to_tag; do
          [ "$to_tag" = "$SCHED_TAG" ] || continue
          when="$(date -u -d "$stamp" +%s 2>/dev/null)" || continue
          [ "$when" -ge "${sched_created:-0}" ] && ran=1
        done <"$STATE_DIR/history.log"
      fi
      if [ "$ran" = 0 ]; then
        log "scheduled update of $SCHED_TAG missed"
        if release_state_set "$STATE_DIR/scheduled" OUTCOME missed NOTIFIED 0; then
          sched_outcome=missed sched_notified=0
          notice_id="$(sget scheduled NOTICE_ID)" || notice_id=""
          if [ -n "$notice_id" ]; then
            make -C "$APP_DIR/deploy" site-notice ENV_FILE="$ENV_FILE" ARGS="withdraw $notice_id" || log "site notice: 'withdraw $notice_id' failed"
          fi
        else
          FAIL[state]=1
        fi
      fi
    fi
    if [ "$sched_outcome" = missed ] && [ "$sched_notified" != 1 ]; then
      if send_mail "scheduled update of $SCHED_TAG missed" "The update of $SCHED_TAG scheduled on $HOST_NAME did not run: the slot passed more than 15 minutes ago (the host was off, or busy) and nothing was changed.
An update is never run late. Schedule a new slot, or run it now:

  ssh -t <your account>@$HOST_NAME sudo manuspectrum-update --now $SCHED_TAG"; then
        release_state_set "$STATE_DIR/scheduled" NOTIFIED 1 || FAIL[state]=1
      fi
    fi
    [ -n "$sched_outcome" ] || SCHED_ACTIVE=1
  else
    log "scheduled: $STATE_DIR/scheduled is unreadable, ignored"
    SCHED_TAG=""
  fi
fi

# --- 1b Ansible running

if [ -e "$ANSIBLE_MARKER" ]; then
  log "Ansible is running on this host: nothing is armed this run"
  marker_age=$((NOW - $(stat -c %Y "$ANSIBLE_MARKER" 2>/dev/null || echo "$NOW")))
  if [ "$marker_age" -gt 7200 ]; then
    log "Ansible marker older than 2 h: a run was interrupted; remove it if no playbook is running"
    FAIL[state]=1
  fi
  finish 0
fi

# --- 2 probes

probe_code() { curl -sS -m 15 -o /dev/null -w '%{http_code}' "$1" 2>&1; }
code="$(probe_code "$PROBE_GIT")"
[[ "$code" =~ ^[23][0-9][0-9]$ ]] || { FAIL[git]=1; log "probe git: $PROBE_GIT unreachable (${code:-no answer})"; }
code="$(probe_code "$PROBE_REGISTRY")"
[ "$code" = 401 ] || { FAIL[registry]=1; log "probe registry: $PROBE_REGISTRY did not answer 401 (${code:-no answer})"; }
code="$(probe_code "$PROBE_SIGSTORE")"
[[ "$code" =~ ^[23][0-9][0-9]$ ]] || { FAIL[sigstore]=1; log "probe sigstore: $PROBE_SIGSTORE unreachable (${code:-no answer})"; }
if [ "${FAIL[git]}${FAIL[registry]}${FAIL[sigstore]}" != 000 ]; then
  log "a probe failed: verification skipped"
  finish 1
fi

# --- 3 candidate

CHANNEL="$(release_env_get "$ENV_FILE" RELEASE_CHANNEL 2>/dev/null || echo prod)"
case "$CHANNEL" in prod | rc) ;; *) log "RELEASE_CHANNEL in $ENV_FILE must be prod or rc"; FAIL[state]=1; finish 1 ;; esac

CUR_TAG="$(sget current TAG)" || CUR_TAG="$(git -C "$APP_DIR" describe --exact-match --tags HEAD 2>/dev/null)"
if ! release_tag_valid "$CUR_TAG"; then
  log "cannot tell the running version: no readable $STATE_DIR/current and HEAD is not at a release tag"
  FAIL[state]=1
  finish 1
fi
CUR_IMAGE="$(sget current IMAGE)" || CUR_IMAGE=""
PREV_IMAGE="$(sget previous IMAGE)" || PREV_IMAGE=""

log "step 3: fetch (running $CUR_TAG, channel $CHANNEL)"
if ! git -C "$APP_DIR" fetch --quiet --tags --prune --prune-tags origin; then
  log "git fetch --tags --prune --prune-tags origin failed (a rejected tag means the origin moved it: see the runbook)"
  FAIL[git]=1
  finish 1
fi
CANDIDATE="$(git -C "$APP_DIR" tag -l | release_pick_candidate "$CHANNEL" "$CUR_TAG")"
if [ -z "$CANDIDATE" ]; then
  log "no release newer than $CUR_TAG"
  VERIFICATION=0
  finish 0
fi
log "candidate: $CANDIDATE"

# --- 4 a scheduled update holds the armed release in place

if [ "$SCHED_ACTIVE" = 1 ]; then
  if [ "$(release_semver_cmp "$CANDIDATE" "$SCHED_TAG")" = 1 ]; then
    held="$(sget scheduled HELD_TAG)" || held=""
    if [ "$held" != "$CANDIDATE" ]; then
      log "$CANDIDATE is available while $SCHED_TAG is scheduled"
      if send_mail "$CANDIDATE available while $SCHED_TAG is scheduled" "$CANDIDATE is available on $HOST_NAME (channel $CHANNEL), but the update of $SCHED_TAG is scheduled and stays as it is: the armed release is not replaced.
After $SCHED_TAG is installed (or the schedule is cancelled), this host arms $CANDIDATE on its next hourly check and mails again."; then
        release_state_set "$STATE_DIR/scheduled" HELD_TAG "$CANDIDATE" || FAIL[state]=1
      fi
    fi
  else
    log "an update of $SCHED_TAG is scheduled: the armed release is left alone"
  fi
  finish 0
fi

# --- 5 already armed

tag_commit="$(git -C "$APP_DIR" rev-parse --verify --quiet "refs/tags/$CANDIDATE^{commit}")" || { log "cannot resolve $CANDIDATE"; FAIL[git]=1; finish 1; }
tag_epoch="$(git -C "$APP_DIR" for-each-ref --format='%(creatordate:unix)' "refs/tags/$CANDIDATE")"
REF="$IMAGE_REPO:$CANDIDATE"

armed_tag="$(sget armed TAG)" || armed_tag=""
armed_image="$(sget armed IMAGE)" || armed_image=""
digest=""

# Mail text and sending (step 9); needs the armed and pending state.
announce() { # announce: mails the armed release when NOTIFIED is not 1
  local tag image commit security needs since days deadline notes msg subject
  [ "$(sget armed NOTIFIED)" != 1 ] || return 0
  tag="$(sget armed TAG)" image="$(sget armed IMAGE)" commit="$(sget armed COMMIT)" security="$(sget armed SECURITY)" needs="$(sget armed NEEDS_ANSIBLE)"
  since="$(sget pending SINCE)" || since="$NOW"
  if [ "$(sget pending SECURITY)" = 1 ] || [ "$security" = 1 ]; then days=14; else days=30; fi
  deadline="$(date -u -d "@$((since + days * 86400))" +%Y-%m-%d)"
  notes="$(git -C "$APP_DIR" tag -l --format='%(contents:body)' "$tag")"
  subject="$tag ready to install on $HOST_NAME"
  [ "$security" != 1 ] || subject+=" (security fix)"
  msg="Version: $tag
Channel: $CHANNEL
Image digest: ${image#*@}
Commit: $commit
Release: $REPO_URL/releases/tag/$tag
Install by: $deadline ($days days after the oldest release waiting)
"
  [ "$security" != 1 ] || msg+="This release carries a security fix.
"
  if [ "$needs" = 1 ]; then
    msg+="
Re-run Ansible first: files managed by Ansible or keys of .env differ at $tag, so the update would be refused until Ansible has run from a laptop checkout at $tag.
"
  fi
  [ -z "$notes" ] || msg+="
Release notes:
$notes
"
  msg+="
Install it now:

  ssh -t <your account>@$HOST_NAME sudo manuspectrum-update --now $tag

or choose a time (Paris time):

  ssh -t <your account>@$HOST_NAME sudo manuspectrum-update --at \"YYYY-MM-DD HH:MM\" $tag"
  if send_mail "$subject" "$msg"; then
    release_state_set "$STATE_DIR/armed" NOTIFIED 1 || FAIL[state]=1
  fi
}

if [ "$armed_tag" = "$CANDIDATE" ] && [ -n "$armed_image" ]; then
  if digest="$(bash "$RELEASE_LIB_DIR/image-digest.sh" "$REF" 2>/dev/null)" && [ "$digest" = "${armed_image#*@}" ]; then
    log "$CANDIDATE is armed and unchanged"
    needs_now=0
    release_compat_check "$APP_DIR" "$ENV_FILE" "$CANDIDATE" "$MANAGED_SOURCES" || needs_now=1
    if [ "$needs_now" != "$(sget armed NEEDS_ANSIBLE)" ]; then
      log "$CANDIDATE: needs_ansible is now $needs_now"
      release_state_set "$STATE_DIR/armed" NEEDS_ANSIBLE "$needs_now" || FAIL[state]=1
    fi
    announce
    finish 0
  fi
  log "$CANDIDATE is armed, but the registry answers ${digest:-nothing}: checking again"
fi

# --- 6 digest and verification

# A release is published in steps (image, signature): a tag younger than
# GRACE that is not complete yet is waited for, an older one is a failure.
unfinished() { # unfinished WHY: leaves the run; the caller has logged the cause
  local age=$((NOW - ${tag_epoch:-0}))
  if [ "$age" -lt "$GRACE" ]; then
    log "$CANDIDATE: $1 - still publishing (tagged ${age}s ago), nothing recorded"
    finish 0
  fi
  log "$CANDIDATE: $1 (tagged ${age}s ago): verification failed"
  VERIFICATION=1
  finish 1
}

log "step 6: digest and verification of $REF"
if ! digest="$(bash "$RELEASE_LIB_DIR/image-digest.sh" "$REF" 2>&1)" || ! [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  unfinished "no image for $REF"
fi
image="$IMAGE_REPO@$digest"
verify_out="$(cd "$APP_DIR" && bash "$RELEASE_LIB_DIR/release-verify.sh" --policy "$CHANNEL" "$image" "$CANDIDATE" --commit "$tag_commit" --repo-dir "$APP_DIR" 2>&1)" || {
  case "$verify_out" in
    *"cannot pull"*) log "$CANDIDATE: $(tail -n 1 <<<"$verify_out")"; FAIL[pull]=1; finish 1 ;;
  esac
  unfinished "release-verify refused $image: $(tail -n 2 <<<"$verify_out" | tr '\n' ' ')"
}
VERIFICATION=0

# --- 7 compatibility, 8 state

needs=0
if ! release_compat_check "$APP_DIR" "$ENV_FILE" "$CANDIDATE" "$MANAGED_SOURCES"; then
  needs=1
  log "$CANDIDATE needs Ansible first ($RELEASE_COMPAT_REASON): $RELEASE_COMPAT_MESSAGE"
fi

security=0
if git -C "$APP_DIR" tag -l --format='%(contents:body)' "$CANDIDATE" | git interpret-trailers --parse 2>/dev/null | grep -qx 'Security-Fix: yes'; then
  security=1
fi

since="$(sget pending SINCE)" || since="$NOW"
pend_security="$security"
[ "$(sget pending SECURITY)" != 1 ] || pend_security=1
old_image="$armed_image"

if ! { release_state_write "$STATE_DIR/armed" "TAG=$CANDIDATE" "IMAGE=$image" "COMMIT=$tag_commit" "ARMED_AT=$NOW" "SECURITY=$security" "NOTIFIED=0" "NEEDS_ANSIBLE=$needs" \
  && release_state_write "$STATE_DIR/pending" "SINCE=$since" "SECURITY=$pend_security"; }; then
  log "cannot write the armed state"
  FAIL[state]=1
  finish 1
fi
log "armed $CANDIDATE ($digest), needs_ansible=$needs, security=$security"

if [ -n "$old_image" ] && [ "$old_image" != "$image" ] && [ "$old_image" != "$CUR_IMAGE" ] && [ "$old_image" != "$PREV_IMAGE" ]; then
  docker image rm "$old_image" >/dev/null 2>&1 || log "older armed image $old_image not removed"
fi

# --- 9 mail

announce
finish 0
