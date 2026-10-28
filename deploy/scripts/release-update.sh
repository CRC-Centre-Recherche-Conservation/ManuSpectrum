#!/usr/bin/env bash
# The update engine: installs the armed release on this host, or puts the
# previous one back. Started by systemd as manuspectrum-update@<tag>.service
# under the service account, from the root-owned copy in RELEASE_LIB_DIR; it is
# never run from the checkout it modifies (bash reads a script while it runs)
# and does not depend on where it lives.
#
# Usage: release-update.sh TAG
#        release-update.sh --check-only TAG    steps 1-4 without any change
#        release-update.sh --after-stop TAG    ExecStopPost of the unit (below)
#
# Exit codes: 0 installed (or the check passed), 1 refused with nothing
# changed, 3 rolled back to the previous version, 4 the rollback failed.
# A refusal prints `REASON=<word>` (REASON in lib-release.sh) as its last line.
#
# Steps (one log line each):
#   1 lock STATE_DIR/lock; create `current` from the running version if absent
#   2 preflight: .env image and HEAD agree with `current`, clean worktree, no
#     update in flight, no Ansible run (ANSIBLE_MARKER exists), TAG is armed,
#     a scheduled slot still inside its window
#   3 fetch; the tag still names the armed commit; the registry tag still names
#     the armed digest; the keys of the tag's .env.example are in .env; the
#     files Ansible manages at the tag equal MANAGED_SOURCES
#   4 the signature services answer (a failed probe is REASON=fetch), then
#     release-verify on the armed digest
#   5 `make backup TAG=pre-update` from the current version
#   6 take the lock of the backup on our own descriptor and hold it; a
#     scheduled slot past its window after the backup is REASON=late
#   7 write `inflight`, check out the tag, rewrite the .env image, `make up`
#   8 poll /readyz until one deadline (start of step 7 + RELEASE_READY_WAIT_SECONDS)
#   9 success: previous <- current <- armed, clear armed, pending, inflight;
#     local images of the repository that are neither current, previous nor
#     armed (by digest) are removed
#  10 any failure of 7-8, SIGTERM or SIGINT included: check out the previous
#     commit, put its image back, `make up`, wait again; `rollbacks` counts it
# The data are never restored, `init` and `load-snapshot` never run: a failed
# rollback only mails the restore commands.
#
# --after-stop (ExecStopPost of manuspectrum-update@.service, reads
# SERVICE_RESULT, EXIT_CODE, EXIT_STATUS and INVOCATION_ID): an engine that
# exited 0, 3 or 4 has finished (4 mailed already, whatever SERVICE_RESULT
# says); any other end (timeout, kill, crash) with an `inflight` still there
# sets ROLLBACK_FAILED=1, writes the metrics and mails the restore commands
# once. Step 7 records the unit's INVOCATION_ID in `inflight`, and --after-stop
# acts only on an `inflight` carrying its own id: one left by an earlier
# invocation is not this unit's. It never touches the stack.
#
# Scheduled context: STATE_DIR/scheduled names TAG with an empty OUTCOME. A
# refusal sets OUTCOME=refused and REASON (the file stays); a slot past its
# window (REASON=late) is OUTCOME=missed, as manuspectrum-update --fire records it and withdraws the
# site notice; success and exit 3 end the notice and remove the file; exit 4
# extends the notice by 24 hours and removes the file. Mail goes out only in
# that context (and for the result of a run), through release_mail. A failing
# notice or mail command is logged and never changes the exit code.
#
# Configuration (environment, defaults for the host): APP_DIR, STATE_DIR,
# ENV_FILE (APP_DIR/deploy/compose/.env), MANAGED_SOURCES, RELEASE_LIB_DIR,
# UPDATE_LOCK_WAIT (900), BACKUP_LOCK_WAIT (600), RELEASE_READY_INTERVAL (10),
# ANSIBLE_MARKER (/run/manuspectrum/ansible-running), RELEASE_PROBE_SIGSTORE,
# RELEASE_NOW_EPOCH (tests).
# From .env: MANUSPECTRUM_IMAGE, RELEASE_CHANNEL (prod|rc, default prod),
# RELEASE_READY_WAIT_SECONDS (default 600, at most RELEASE_READY_WAIT_MAX =
# 1800: the unit's TimeoutStopSec is sized on it), BACKUP_DUMP_DIR (the backup lock is
# BACKUP_DUMP_DIR/.lock, as in lib-backup.sh), METRICS_TEXTFILE_DIR, PUBLIC_HOST
# and the mail keys of release_mail.
set -uo pipefail

RELEASE_LIB_DIR="${RELEASE_LIB_DIR:-/usr/local/lib/manuspectrum/release}"
APP_DIR="${APP_DIR:-/home/manuspectrum/manuspectrum}"
STATE_DIR="${STATE_DIR:-/var/lib/manuspectrum/release}"
ENV_FILE="${ENV_FILE:-$APP_DIR/deploy/compose/.env}"
MANAGED_SOURCES="${MANAGED_SOURCES:-/etc/manuspectrum/managed-sources}"
UPDATE_LOCK_WAIT="${UPDATE_LOCK_WAIT:-900}"
BACKUP_LOCK_WAIT="${BACKUP_LOCK_WAIT:-600}"
READY_INTERVAL="${RELEASE_READY_INTERVAL:-10}"
ANSIBLE_MARKER="${ANSIBLE_MARKER:-/run/manuspectrum/ansible-running}"
PROBE_SIGSTORE="${RELEASE_PROBE_SIGSTORE:-https://tuf-repo-cdn.sigstore.dev/}"
RELEASE_READY_WAIT_MAX=1800

log() { echo "release-update: $*"; }
now_epoch() { echo "${RELEASE_NOW_EPOCH:-$(date +%s)}"; }

# shellcheck source=lib-release.sh
# shellcheck source-path=SCRIPTDIR
source "$RELEASE_LIB_DIR/lib-release.sh" || { echo "release-update: cannot read $RELEASE_LIB_DIR/lib-release.sh" >&2; exit 2; }

CHECK_ONLY=0 AFTER_STOP=0
TAG=""
case "${1-}" in
  --check-only) CHECK_ONLY=1; TAG="${2-}"; [ "$#" -eq 2 ] || { echo "usage: release-update.sh [--check-only|--after-stop] TAG" >&2; exit 2; } ;;
  --after-stop) AFTER_STOP=1; TAG="${2-}"; [ "$#" -eq 2 ] || { echo "usage: release-update.sh [--check-only|--after-stop] TAG" >&2; exit 2; } ;;
  *) TAG="${1-}"; [ "$#" -eq 1 ] || { echo "usage: release-update.sh [--check-only|--after-stop] TAG" >&2; exit 2; } ;;
esac

SCHED=0 NOTICE_ID="" HAVE_LOCK=0 LOCK_REFUSAL=0 TERMINATED=0
CUR_TAG="" CUR_IMAGE="" CUR_COMMIT=""
ARMED_IMAGE="" ARMED_COMMIT=""
CHANNEL=prod WAIT=600
HOST_NAME=""

metrics_path() {
  local dir
  dir="$(release_env_get "$ENV_FILE" METRICS_TEXTFILE_DIR 2>/dev/null)" && [ -d "$dir" ] || return 1
  echo "$dir/manuspectrum_release.prom"
}

# Every exit that follows step 1 refreshes the release textfile from the state.
write_metrics() { # write_metrics [NAME=VALUE ...]
  local path
  path="$(metrics_path)" || { log "metrics: METRICS_TEXTFILE_DIR is not a directory, not written"; return 0; }
  release_metrics_from_state "$STATE_DIR" "$path" "$@" || log "metrics: could not write $path"
}

send_mail() { # send_mail SUBJECT BODY
  release_mail "$1" "$2" || log "mail: not sent ($1)"
}

notice() { # notice ARGS...: one site-notice command, failures are logged
  [ "$SCHED" = 1 ] && [ -n "$NOTICE_ID" ] || return 0
  make -C "$APP_DIR/deploy" site-notice ENV_FILE="$ENV_FILE" ARGS="$*" || log "site notice: 'site-notice $*' failed"
}

scheduled_done() { # scheduled_done end-args...: end the notice, drop the scheduled record
  [ "$SCHED" = 1 ] || return 0
  notice "$@"
  rm -f "$STATE_DIR/scheduled"
}

history() { # history OUTCOME FROM TO
  printf '%s\t%s\t%s\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2" "$3" >>"$STATE_DIR/history.log" || log "history: not written"
}

# A refusal changes nothing on the host. --check-only stops at the message.
refuse() { # refuse REASON MESSAGE
  local reason="$1" outcome subject
  shift
  log "REFUSED: $*"
  if [ "$CHECK_ONLY" = 0 ] && { [ "$HAVE_LOCK" = 1 ] || [ "$LOCK_REFUSAL" = 1 ]; }; then
    if [ "$SCHED" = 1 ]; then
      if [ "$reason" = late ]; then outcome=missed subject="scheduled update of $TAG missed (past its window)"; else outcome=refused subject="scheduled update of $TAG refused: $reason"; fi
      release_state_set "$STATE_DIR/scheduled" OUTCOME "$outcome" REASON "$reason" || log "scheduled: state not updated"
      notice withdraw "$NOTICE_ID"
      send_mail "$subject" "The scheduled update of $TAG on ${HOST_NAME:-this host} was $outcome ($reason) and nothing was changed.

$*

Details: journalctl -u manuspectrum-update@$TAG.service"
    fi
    if [ "$reason" = verify ]; then write_metrics verification_failed=1; else write_metrics; fi
  fi
  echo "REASON=$reason"
  exit 1
}

finish() { # finish CODE: refresh the metrics and leave
  write_metrics
  exit "$1"
}

# A scheduled run is bound to its window: past WINDOW_END_EPOCH it is refused.
check_window() { # check_window WHEN
  local end
  [ "$SCHED" = 1 ] || return 0
  end="$(release_state_get "$STATE_DIR/scheduled" WINDOW_END_EPOCH 2>/dev/null)" || return 0
  [ "$(now_epoch)" -le "$end" ] || refuse late "the window of the scheduled update closed at $(date -u -d "@$end" '+%Y-%m-%d %H:%M UTC') ($1)"
}

run_verify() { # run_verify IMAGE TAG COMMIT
  (cd "$APP_DIR" && bash "$RELEASE_LIB_DIR/release-verify.sh" --policy "$CHANNEL" "$1" "$2" --commit "$3" --repo-dir "$APP_DIR") 2>&1
}

# --- after-stop (ExecStopPost)

if [ "$AFTER_STOP" = 1 ]; then
  release_tag_valid "$TAG" || { log "after-stop: '$TAG' is not a release tag"; exit 0; }
  HOST_NAME="$(release_env_get "$ENV_FILE" PUBLIC_HOST 2>/dev/null || hostname)"
  if [ "${SERVICE_RESULT:-}" = success ] || [ ! -e "$STATE_DIR/inflight" ]; then exit 0; fi
  if [ "${EXIT_CODE:-}" = exited ]; then case "${EXIT_STATUS:-}" in 0 | 3 | 4) exit 0 ;; esac; fi
  own_id="$(release_state_get "$STATE_DIR/inflight" INVOCATION_ID 2>/dev/null)" || own_id=""
  if ! [[ "${INVOCATION_ID:-}" =~ ^[0-9a-f]{32}$ ]] || [ "$own_id" != "$INVOCATION_ID" ]; then
    log "after-stop: $STATE_DIR/inflight was not written by this invocation: left alone"
    exit 0
  fi
  exec 7>>"$STATE_DIR/lock" && { flock -w 30 7 || log "after-stop: lock not taken, going on"; }
  log "after-stop: the engine ended with ${SERVICE_RESULT:-unknown} (${EXIT_STATUS:-?}) and left $STATE_DIR/inflight"
  from_tag="$(release_state_get "$STATE_DIR/inflight" FROM_TAG 2>/dev/null || echo "the previous version")"
  release_state_set "$STATE_DIR/rollbacks" ROLLBACK_FAILED 1 || log "state: ROLLBACK_FAILED not written"
  history interrupted "$from_tag" "$TAG"
  if [ -f "$STATE_DIR/scheduled" ] && [ "$(release_state_get "$STATE_DIR/scheduled" TAG 2>/dev/null)" = "$TAG" ] \
    && [ -z "$(release_state_get "$STATE_DIR/scheduled" OUTCOME 2>/dev/null)" ]; then
    SCHED=1
    NOTICE_ID="$(release_state_get "$STATE_DIR/scheduled" NOTICE_ID 2>/dev/null || true)"
    scheduled_done end "$NOTICE_ID" --at +24h
  fi
  write_metrics
  send_mail "update of $TAG interrupted" "The update to $TAG on $HOST_NAME ended without finishing (${SERVICE_RESULT:-unknown}, exit ${EXIT_STATUS:-unknown}); it was neither completed nor rolled back by the engine.
The site may be down or half switched. Nothing was restored automatically and $STATE_DIR/inflight is kept: no update runs until it is removed.

Check the site first (sudo manuspectrum-update --status, make -C deploy status). If it must be repaired, restore the backup taken just before the update:

  make -C deploy restic ARGS=\"snapshots --tag pre-update\"
  make -C deploy restore RESTIC_SNAPSHOT=<id> CONFIRM=yes ERASURES_CHECKED=yes

Read deploy/BACKUP.md (\"Restore the stack\", \"Personal data\") before the restore: it replaces the database and the uploads. Then follow deploy/runbooks/release.md (UpdateInterrupted).

Details: journalctl -u manuspectrum-update@$TAG.service"
  exit 0
fi

# --- arguments and configuration

release_tag_valid "$TAG" || { log "REFUSED: '$TAG' is not a release tag"; echo "REASON=unarmed"; exit 1; }
[ -d "$APP_DIR/.git" ] || [ -f "$APP_DIR/.git" ] || { log "REFUSED: $APP_DIR is not a checkout"; echo "REASON=drift"; exit 1; }
[ -f "$ENV_FILE" ] || { log "REFUSED: no $ENV_FILE"; echo "REASON=drift"; exit 1; }
HOST_NAME="$(release_env_get "$ENV_FILE" PUBLIC_HOST 2>/dev/null || hostname)"

if [ "$CHECK_ONLY" = 0 ] && [ -f "$STATE_DIR/scheduled" ] \
  && [ "$(release_state_get "$STATE_DIR/scheduled" TAG 2>/dev/null)" = "$TAG" ] \
  && [ -z "$(release_state_get "$STATE_DIR/scheduled" OUTCOME 2>/dev/null)" ]; then
  SCHED=1
  NOTICE_ID="$(release_state_get "$STATE_DIR/scheduled" NOTICE_ID 2>/dev/null || true)"
fi

# --- 1 lock, bootstrap

log "step 1: lock and current version"
exec 7>>"$STATE_DIR/lock" || { log "REFUSED: cannot open $STATE_DIR/lock"; echo "REASON=lock"; exit 1; }
if ! flock -w "$UPDATE_LOCK_WAIT" 7; then
  LOCK_REFUSAL=1 # a scheduled run records its refusal without the lock (release_state_set renames atomically)
  refuse lock "another update or watch holds $STATE_DIR/lock"
fi
HAVE_LOCK=1

CHANNEL="$(release_env_get "$ENV_FILE" RELEASE_CHANNEL 2>/dev/null || echo prod)"
case "$CHANNEL" in prod | rc) ;; *) refuse env_keys "RELEASE_CHANNEL in $ENV_FILE must be prod or rc" ;; esac
WAIT="$(release_env_get "$ENV_FILE" RELEASE_READY_WAIT_SECONDS 2>/dev/null || echo 600)"
if ! [[ "$WAIT" =~ ^[0-9]{1,5}$ ]] || [ "$WAIT" -le 0 ] || [ "$WAIT" -gt "$RELEASE_READY_WAIT_MAX" ]; then
  refuse env_keys "RELEASE_READY_WAIT_SECONDS in $ENV_FILE must be between 1 and $RELEASE_READY_WAIT_MAX seconds"
fi

ENV_IMAGE="$(release_env_get "$ENV_FILE" MANUSPECTRUM_IMAGE 2>/dev/null)" || ENV_IMAGE=""
HEAD_COMMIT="$(git -C "$APP_DIR" rev-parse HEAD 2>/dev/null)" || refuse drift "cannot read HEAD of $APP_DIR"

if [ -f "$STATE_DIR/current" ]; then
  if ! { CUR_TAG="$(release_state_get "$STATE_DIR/current" TAG 2>/dev/null)" \
    && CUR_IMAGE="$(release_state_get "$STATE_DIR/current" IMAGE 2>/dev/null)" \
    && CUR_COMMIT="$(release_state_get "$STATE_DIR/current" COMMIT 2>/dev/null)"; }; then
    refuse drift "$STATE_DIR/current is unreadable"
  fi
else
  log "no current version recorded: reading it from the running checkout"
  release_state_ok IMAGE "$ENV_IMAGE" || refuse drift "MANUSPECTRUM_IMAGE in $ENV_FILE is not a digest reference"
  CUR_TAG="$(git -C "$APP_DIR" describe --exact-match --tags HEAD 2>/dev/null)"
  release_tag_valid "$CUR_TAG" || refuse drift "HEAD of $APP_DIR is not at a release tag"
  CUR_IMAGE="$ENV_IMAGE" CUR_COMMIT="$HEAD_COMMIT"
  label="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$CUR_IMAGE" 2>/dev/null)"
  [ "$label" = "$CUR_COMMIT" ] || refuse drift "the running image does not carry the revision label of HEAD"
  run_verify "$CUR_IMAGE" "$CUR_TAG" "$CUR_COMMIT" >/dev/null || refuse drift "the running image $CUR_TAG does not verify"
  if [ "$CHECK_ONLY" = 0 ]; then
    release_state_write "$STATE_DIR/current" "TAG=$CUR_TAG" "IMAGE=$CUR_IMAGE" "COMMIT=$CUR_COMMIT" || refuse drift "cannot write $STATE_DIR/current"
    log "current version recorded: $CUR_TAG"
  fi
fi

# --- 2 preflight

log "step 2: preflight (running $CUR_TAG)"
[ "$ENV_IMAGE" = "$CUR_IMAGE" ] || refuse drift "MANUSPECTRUM_IMAGE in $ENV_FILE is not the image of $CUR_TAG"
[ "$HEAD_COMMIT" = "$CUR_COMMIT" ] || refuse drift "HEAD of $APP_DIR is $HEAD_COMMIT, not the commit of $CUR_TAG"
dirty="$(git -C "$APP_DIR" status --porcelain 2>&1)" || refuse drift "git status failed in $APP_DIR"
[ -z "$dirty" ] || refuse drift "$APP_DIR has local changes:
$(head -n 10 <<<"$dirty")"
check_window "before the start"
[ ! -e "$ANSIBLE_MARKER" ] || refuse busy "Ansible is running on this host"
[ ! -e "$STATE_DIR/inflight" ] || refuse busy "an update is in flight or was interrupted ($STATE_DIR/inflight)"
[ -f "$STATE_DIR/armed" ] || refuse unarmed "no release is armed"
[ "$(release_state_get "$STATE_DIR/armed" TAG 2>/dev/null)" = "$TAG" ] || refuse unarmed "$TAG is not the armed release"
if ! { ARMED_IMAGE="$(release_state_get "$STATE_DIR/armed" IMAGE 2>/dev/null)" \
  && ARMED_COMMIT="$(release_state_get "$STATE_DIR/armed" COMMIT 2>/dev/null)"; }; then
  refuse unarmed "$STATE_DIR/armed is unreadable"
fi

# --- 3 what the tag brings

log "step 3: fetch and compare $TAG with what is armed"
git -C "$APP_DIR" fetch --tags --prune --prune-tags origin || refuse fetch "git fetch --tags --prune --prune-tags origin failed (a tag that moved is refused by git itself: would clobber existing tag)"
tag_commit="$(git -C "$APP_DIR" rev-parse --verify --quiet "refs/tags/$TAG^{commit}")" || refuse tag_moved "$TAG is not in $APP_DIR after the fetch"
[ "$tag_commit" = "$ARMED_COMMIT" ] || refuse tag_moved "$TAG names $tag_commit, the armed commit is $ARMED_COMMIT"
registry_ref="${ARMED_IMAGE%@*}:$TAG"
registry_digest="$(bash "$RELEASE_LIB_DIR/image-digest.sh" "$registry_ref")" || refuse fetch "cannot read the manifest of $registry_ref"
[ "$registry_digest" = "${ARMED_IMAGE#*@}" ] || refuse tag_moved "$registry_ref is now $registry_digest, the armed digest is ${ARMED_IMAGE#*@}"
release_compat_check "$APP_DIR" "$ENV_FILE" "$TAG" "$MANAGED_SOURCES" || refuse "$RELEASE_COMPAT_REASON" "$RELEASE_COMPAT_MESSAGE"

# --- 4 verification

log "step 4: signature and revision of the armed image"
sig_code="$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "$PROBE_SIGSTORE" 2>&1)"
[[ "$sig_code" =~ ^[23][0-9][0-9]$ ]] || refuse fetch "the signature services ($PROBE_SIGSTORE) do not answer (${sig_code:-no answer}): verification cannot run"
verify_out="$(run_verify "$ARMED_IMAGE" "$TAG" "$ARMED_COMMIT")" || { refuse verify "release-verify refused $ARMED_IMAGE: $(tail -n 3 <<<"$verify_out")"; }

if [ "$CHECK_ONLY" = 1 ]; then
  log "check passed for $TAG"
  echo "CHECK=ok"
  exit 0
fi

# --- 5 backup, 6 backup lock

backup_dir="$(release_env_get "$ENV_FILE" BACKUP_DUMP_DIR 2>/dev/null)" || refuse backup "BACKUP_DUMP_DIR is not set in $ENV_FILE"
log "step 5: backup (pre-update)"
make -C "$APP_DIR/deploy" backup ENV_FILE="$ENV_FILE" TAG=pre-update || refuse backup "the pre-update backup failed: nothing was changed"
log "step 6: backup lock"
exec 8>"$backup_dir/.lock" || refuse lock "cannot open $backup_dir/.lock"
flock -w "$BACKUP_LOCK_WAIT" 8 || refuse lock "another backup or restore holds $backup_dir/.lock"

# --- 7 switch, 8 readiness

check_window "after the backup"

# shellcheck disable=SC2317  # run by the trap
on_signal() { TERMINATED=1; }

probe() { # prints the HTTP status of /readyz inside the web container, or nothing
  local compose_dir="$APP_DIR/deploy/compose"
  timeout 60 docker compose --project-directory "$compose_dir" --env-file "$ENV_FILE" \
    -f "$compose_dir/compose.yaml" -f "$compose_dir/compose.prod.yaml" \
    exec -T web curl -s -m 15 -o /dev/null -w '%{http_code}' -H 'Host: web' http://127.0.0.1:8000/readyz 2>/dev/null
}

wait_ready() { # wait_ready DEADLINE (value of SECONDS): 0 ready, 1 deadline, 2 signal
  local deadline="$1" code last=""
  while :; do
    [ "$TERMINATED" = 0 ] || return 2
    code="$(probe)" || code=""
    [ "$code" = "$last" ] || { log "readiness: ${code:-no answer}"; last="$code"; }
    [ "$code" != 200 ] || return 0
    [ "$SECONDS" -lt "$deadline" ] || return 1
    sleep "$READY_INTERVAL" &
    wait $! || true
    kill $! 2>/dev/null || true
  done
}

# Puts COMMIT and IMAGE on the host and starts the stack; then waits for readiness.
switch_to() { # switch_to LABEL COMMIT IMAGE
  local label="$1" commit="$2" image="$3" deadline=$((SECONDS + WAIT + 1))  # SECONDS counts whole seconds: never stop early
  log "switching to $label"
  git -C "$APP_DIR" checkout --quiet --detach "$commit" || return 1
  git -C "$APP_DIR" submodule update --init || return 1
  release_env_set_image "$ENV_FILE" "$image" || return 1
  [ "$TERMINATED" = 0 ] || return 2
  make -C "$APP_DIR/deploy" up ENV_FILE="$ENV_FILE" UP_WAIT_TIMEOUT="$WAIT" || return 1
  [ "$TERMINATED" = 0 ] || return 2
  wait_ready "$deadline"
}

# Removes the local images of the release repository that `current`, `previous`
# and `armed` do not name (by digest). The version just replaced and the one
# just installed are kept from memory, whatever the state files say. Images of other repositories are never
# listed. Failures are logged.
prune_images() {
  local repo="${ARMED_IMAGE%@*}" keep=" ${CUR_IMAGE#*@}  ${ARMED_IMAGE#*@} " f img repository digest
  for f in current previous armed; do
    img="$(release_state_get "$STATE_DIR/$f" IMAGE 2>/dev/null)" && keep+=" ${img#*@} "
  done
  while read -r repository digest; do
    [ "$repository" = "$repo" ] || continue
    [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || continue
    case "$keep" in *" $digest "*) continue ;; esac
    log "removing the unused image $repo@$digest"
    docker image rm "$repo@$digest" >/dev/null 2>&1 || log "image $repo@$digest not removed"
  done < <(docker image ls --digests --no-trunc --format '{{.Repository}} {{.Digest}}' "$repo" 2>/dev/null)
}

trap on_signal TERM INT
log "step 7: switching $CUR_TAG -> $TAG (wait ${WAIT}s)"
inflight_id=""
[[ "${INVOCATION_ID:-}" =~ ^[0-9a-f]{32}$ ]] && inflight_id="$INVOCATION_ID"
release_state_write "$STATE_DIR/inflight" "FROM_TAG=$CUR_TAG" "TO_TAG=$TAG" "STARTED_AT=$(date +%s)" "INVOCATION_ID=$inflight_id" || refuse busy "cannot write $STATE_DIR/inflight"
write_metrics
switch_to "$TAG" "$ARMED_COMMIT" "$ARMED_IMAGE"
switched=$?

if [ "$switched" = 0 ]; then
  # --- 9 success
  log "step 9: $TAG is ready; recording it"
  now="$(date +%s)"
  if cp -p "$STATE_DIR/current" "$STATE_DIR/previous.new" 2>/dev/null; then mv -f "$STATE_DIR/previous.new" "$STATE_DIR/previous"; else log "state: previous not written"; fi
  release_state_write "$STATE_DIR/current" "TAG=$TAG" "IMAGE=$ARMED_IMAGE" "COMMIT=$ARMED_COMMIT" "APPLIED_AT=$now" || log "state: current not written"
  rm -f "$STATE_DIR/armed" "$STATE_DIR/pending" "$STATE_DIR/inflight"
  if [ -f "$STATE_DIR/rollbacks" ]; then release_state_set "$STATE_DIR/rollbacks" ROLLBACK_FAILED 0 || true; fi
  history installed "$CUR_TAG" "$TAG"
  prune_images
  scheduled_done end "$NOTICE_ID" --at now
  send_mail "$TAG installed on $HOST_NAME" "$TAG is installed on $HOST_NAME (it was $CUR_TAG) and the application answers /readyz."
  finish 0
fi

# --- 10 rollback

trap '' TERM INT
if [ "$switched" = 2 ]; then reason="interrupted by a signal"; else reason="the application was not ready within ${WAIT}s"; fi
log "step 10: $TAG failed ($reason); rolling back to $CUR_TAG"
TERMINATED=0
switch_to "$CUR_TAG" "$CUR_COMMIT" "$CUR_IMAGE"
rolled=$?

if [ "$rolled" = 0 ]; then
  count="$(release_state_get "$STATE_DIR/rollbacks" COUNT 2>/dev/null || echo 0)"
  release_state_set "$STATE_DIR/rollbacks" COUNT "$((count + 1))" || log "state: rollbacks not written"
  rm -f "$STATE_DIR/inflight"
  history rolled_back "$CUR_TAG" "$TAG"
  scheduled_done end "$NOTICE_ID" --at now
  send_mail "$TAG rolled back" "The update to $TAG on $HOST_NAME was rolled back to $CUR_TAG ($reason).
$TAG stays armed. Nothing was restored: the data are as the update left them.

Details: journalctl -u manuspectrum-update@$TAG.service"
  finish 3
fi

release_state_set "$STATE_DIR/rollbacks" ROLLBACK_FAILED 1 || log "state: ROLLBACK_FAILED not written"
history rollback_failed "$CUR_TAG" "$TAG"
scheduled_done end "$NOTICE_ID" --at +24h
send_mail "$TAG ROLLBACK FAILED" "The update to $TAG on $HOST_NAME failed ($reason) and $CUR_TAG could not be brought back.
The site may be down. Nothing was restored automatically and $STATE_DIR/inflight is kept: no update runs until it is removed.

Repair by hand from the checkout, or restore the backup taken just before the update:

  make -C deploy restic ARGS=\"snapshots --tag pre-update\"
  make -C deploy restore RESTIC_SNAPSHOT=<id> CONFIRM=yes ERASURES_CHECKED=yes

Read deploy/BACKUP.md (\"Restore the stack\", \"Personal data\") before the restore: it replaces the database and the uploads.

Details: journalctl -u manuspectrum-update@$TAG.service"
finish 4
