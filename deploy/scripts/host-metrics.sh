#!/usr/bin/env bash
# Host-side metrics for the node_exporter textfile collector. Run by the
# systemd timers (make -C deploy container-metrics | disk-usage):
#   host-metrics.sh containers   containers of the Compose project, every 30 s
#   host-metrics.sh disk         size of the named data directories, hourly
#
# containers: `docker ps -a`, `docker inspect` and `docker stats --no-stream`,
# one series per Compose service, label container=<service>
#   manuspectrum_container_up                        1 running, 0 not
#   manuspectrum_container_healthy                   0 only when the health check says unhealthy
#   manuspectrum_container_restarts                  Docker's RestartCount
#   manuspectrum_container_oom_kills                 counter of kernel OOM kills (see below)
#   manuspectrum_container_oom_cgroup                1 when oom_kills comes from the cgroup counter,
#                                                    0 when it falls back to State.OOMKilled
#   manuspectrum_container_memory_working_set_bytes  docker stats (usage minus inactive file cache)
#   manuspectrum_container_memory_limit_bytes        HostConfig.Memory, 0 = no limit
#   manuspectrum_container_metrics_errors            services skipped or without a working set
#   manuspectrum_container_metrics_last_run_timestamp_seconds
# OOM kills: the `oom_kill` line of each running container's cgroup v2
# memory.events (readable without privileges, counts every process of the
# container, not only PID 1), under HOST_METRICS_CGROUP_ROOT (default
# /sys/fs/cgroup): system.slice/docker-<id>.scope (systemd driver) or
# docker/<id> (cgroupfs driver). The cgroup counter restarts at 0 whenever the
# container is restarted or recreated, so a per-service total is kept in a
# state file next to the output (.manuspectrum-container-oom.state): the delta
# of the cgroup counter is added while the container lives on; after a restart
# (restart count up, other container id or a lower counter) the kills the
# counter could not report, those that ended the old cgroup, are the `oom`
# events of `docker events` since the previous run, and the larger of that
# number and the new counter is added. When no running container exposes
# memory.events (cgroup v1, another layout) the counter falls back to
# State.OOMKilled with a changed FinishedAt, which misses most kills (Docker
# clears the flag on restart and a child kill never changes FinishedAt):
# manuspectrum_container_oom_cgroup is then 0.
# A service name outside ^[a-z0-9_-]+$ is skipped. When docker does not answer
# within HOST_METRICS_DOCKER_TIMEOUT nothing is written (exit 1) and the
# last-run timestamp ages.
#
# disk: `du` of the directories in DISK_USAGE_AREAS ("name=/absolute/path ..."),
# names from the closed list media, restic, dumps, nginx_logs; label target=<name>
#   manuspectrum_disk_usage_bytes{target}            omitted for a target that failed
#   manuspectrum_disk_usage_failed                   1 when any target failed
#   manuspectrum_disk_usage_last_run_timestamp_seconds
#   manuspectrum_disk_usage_last_success_timestamp_seconds   own file, written only
#                                                    when every target was measured
# Only the named directories are measured. A path that is itself a mountpoint
# is refused (exit 2): `du` of an NFS mount root counts the .snapshot
# directory. Each `du` runs under nice, ionice and the smaller of
# HOST_METRICS_DU_TIMEOUT (default 300 s) and what is left of the budget.
# The whole run is bounded: HOST_METRICS_DISK_BUDGET (default 840 s) must stay
# under the unit's TimeoutStartSec (15 min); the `docker system df -v` call of
# HOST_METRICS_DF_TIMEOUT (default 120 s) is reserved inside it, the `du`
# runs share the rest, and a target left without time counts as failed.
# `[ -d ]`, `realpath` and `findmnt` stat the path before any timeout: on a
# hard-hung NFS mount they block until systemd stops the unit.
#
# Docker disk use, same run, own file manuspectrum_docker_disk.prom (left as it
# was when `docker system df` fails, which also gives failed 1):
#   manuspectrum_docker_disk_bytes{kind}   kind images|build_cache|containers|volumes
#   manuspectrum_docker_volume_bytes{volume}  volumes named ms_* or
#                                          <COMPOSE_PROJECT>_* only
# Both come from ONE `docker system df -v` call (one walk of the volumes by
# dockerd, run under nice and ionice): each kind is the sum of its entries.
# The images figure is the sum of the images' unique sizes, so layers shared
# by several images are left out (about 0.3 % under `docker system df`).
# Docker prints decimal units with four significant digits (1.405GB, 512kB,
# 0B): sizes are accurate to about 0.1 %, and a volume it cannot size
# (N/A) is left out.
#
# Environment: METRICS_TEXTFILE_DIR (absolute, existing), DISK_USAGE_AREAS,
# COMPOSE_PROJECT (default manuspectrum), HOST_METRICS_DOCKER_TIMEOUT
# (default 20 s), HOST_METRICS_DU_TIMEOUT, HOST_METRICS_DISK_BUDGET,
# HOST_METRICS_DF_TIMEOUT, HOST_METRICS_CGROUP_ROOT. Exit: 0 ok, 1 a measurement failed,
# 2 wrong invocation or configuration.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib-metrics.sh
# shellcheck source-path=SCRIPTDIR
source "$HERE/lib-metrics.sh"

log() { printf 'host-metrics: %s\n' "$*" >&2; }
usage_die() { log "FAIL: $*"; exit 2; }

PROJECT="${COMPOSE_PROJECT:-manuspectrum}"
DOCKER_TIMEOUT="${HOST_METRICS_DOCKER_TIMEOUT:-20}"
DU_TIMEOUT="${HOST_METRICS_DU_TIMEOUT:-300}"
DISK_BUDGET="${HOST_METRICS_DISK_BUDGET:-840}"
DF_TIMEOUT="${HOST_METRICS_DF_TIMEOUT:-120}"
CGROUP_ROOT="${HOST_METRICS_CGROUP_ROOT:-/sys/fs/cgroup}"
AREA_NAMES=(media restic dumps nginx_logs)

case "${1:-}" in
  containers | disk) mode="$1" ;;
  -h | --help) sed -n '2,/^set -euo/p' "$0" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
  *) usage_die "usage: host-metrics.sh containers|disk (see --help)" ;;
esac
out_dir="${METRICS_TEXTFILE_DIR:-}"
[[ "$out_dir" == /* && -d "$out_dir" ]] || usage_die "METRICS_TEXTFILE_DIR must be an existing absolute directory (got '$out_dir')"
[[ "$DOCKER_TIMEOUT" =~ ^[0-9]+$ && "$DU_TIMEOUT" =~ ^[0-9]+$ && "$DISK_BUDGET" =~ ^[0-9]+$ && "$DF_TIMEOUT" =~ ^[0-9]+$ ]] || usage_die "timeouts must be whole seconds"

# Docker's "512MiB", "1.5KiB", "3GB" into whole bytes.
to_bytes() { # to_bytes TEXT
  awk -v s="$1" 'BEGIN {
    if (match(s, /^[0-9]+(\.[0-9]+)?/) == 0) exit 1
    num = substr(s, 1, RLENGTH); unit = substr(s, RLENGTH + 1)
    m["B"] = 1; m["kB"] = 1e3; m["KB"] = 1e3; m["MB"] = 1e6; m["GB"] = 1e9; m["TB"] = 1e12; m["PB"] = 1e15
    m["KiB"] = 1024; m["MiB"] = 1048576; m["GiB"] = 1073741824; m["TiB"] = 1099511627776
    if (!(unit in m)) exit 1
    printf "%.0f\n", num * m[unit]
  }'
}

# cgroup_oom_kills ID: the oom_kill counter of a running container, empty when
# no memory.events file is readable.
cgroup_oom_kills() {
  local id="$1" dir value
  [[ "$id" =~ ^[0-9a-f]{64}$ ]] || return 0
  for dir in "$CGROUP_ROOT/system.slice/docker-$id.scope" "$CGROUP_ROOT/docker/$id"; do
    if [ -r "$dir/memory.events" ]; then
      value="$(awk '$1 == "oom_kill" && $2 ~ /^[0-9]+$/ {print $2; exit}' "$dir/memory.events")"
      [ -z "$value" ] || { printf '%s\n' "$value"; return 0; }
    fi
  done
}

# oom_events_since SERVICE EPOCH RUN_START: `oom` events of the service's
# containers in [EPOCH, RUN_START]; empty when docker cannot say.
oom_events_since() {
  local lines
  lines="$(timeout "$DOCKER_TIMEOUT" docker events --since "$2" --until "$3" \
    --filter type=container --filter event=oom \
    --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.service=$1" --format '{{.Status}}')" || return 0
  printf '%s\n' "$lines" | grep -c . || true
}

containers() {
  local ids inspect stats errors=0 id svc running health restarts oom finished limit short mem now run_start
  local state="$out_dir/.manuspectrum-container-oom.state"
  local raw delta ev cgroup_ok=0 reset s_total s_raw s_id s_restarts s_finished s_epoch
  declare -A mem_used raw_of
  declare -A st_total st_raw st_id st_restarts st_finished st_epoch
  ids="$(timeout "$DOCKER_TIMEOUT" docker ps -a -q --no-trunc \
    --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.oneoff=False")" || { log "docker ps failed or timed out"; return 1; }
  [ -n "$ids" ] || { log "no container found for project $PROJECT"; return 1; }
  # shellcheck disable=SC2086  # one argument per container id
  inspect="$(timeout "$DOCKER_TIMEOUT" docker inspect --format \
    '{{.Id}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Running}}|{{with index .State "Health"}}{{.Status}}{{else}}none{{end}}|{{.RestartCount}}|{{.State.OOMKilled}}|{{.State.FinishedAt}}|{{.HostConfig.Memory}}' \
    $ids)" || { log "docker inspect failed or timed out"; return 1; }
  # shellcheck disable=SC2086
  stats="$(timeout "$DOCKER_TIMEOUT" docker stats --no-stream --format '{{.ID}}|{{.MemUsage}}' $ids)" || { stats=""; errors=$((errors + 1)); log "docker stats failed or timed out"; }

  while IFS='|' read -r id mem; do
    [ -n "$id" ] || continue
    mem="${mem%% /*}"
    mem_used["${id:0:12}"]="$(to_bytes "${mem// /}")" || true
  done <<<"$stats"

  if [ -f "$state" ]; then
    while read -r svc s_total s_raw s_id s_restarts s_finished s_epoch; do
      [[ "$svc" =~ ^[a-z0-9_-]+$ && "$s_total" =~ ^[0-9]+$ && "$s_raw" =~ ^[0-9]+$ && "$s_epoch" =~ ^[0-9]+$ ]] || continue
      st_total["$svc"]="$s_total"
      st_raw["$svc"]="$s_raw"
      st_id["$svc"]="$s_id"
      st_restarts["$svc"]="${s_restarts:-0}"
      st_finished["$svc"]="$s_finished"
      st_epoch["$svc"]="$s_epoch"
    done <"$state"
  fi

  while IFS='|' read -r id svc running health restarts oom finished limit; do
    [[ "$running" == true && "$svc" =~ ^[a-z0-9_-]+$ ]] || continue
    raw="$(cgroup_oom_kills "$id")"
    if [ -n "$raw" ]; then raw_of["$svc"]="$raw"; cgroup_ok=1; fi
  done <<<"$inspect"
  # The event window of the next run opens here: a kill is counted by the
  # counters read above or by the events after this instant, never by both.
  run_start="$(date +%s)"

  metrics_open "$out_dir/manuspectrum_container.prom"
  metric_family manuspectrum_container_up gauge "1 when the container is running"
  local lines_up="" lines_healthy="" lines_restarts="" lines_oom="" lines_mem="" lines_limit=""
  while IFS='|' read -r id svc running health restarts oom finished limit; do
    [ -n "$id" ] || continue
    if ! [[ "$svc" =~ ^[a-z0-9_-]+$ && "$restarts" =~ ^[0-9]+$ && "$limit" =~ ^[0-9]+$ ]]; then
      errors=$((errors + 1))
      log "skipping a container with an unusable service name or numbers"
      continue
    fi
    short="${id:0:12}"
    if [ "$running" = true ]; then
      lines_up+="$svc 1"$'\n'
      if [ -n "${mem_used[$short]:-}" ]; then lines_mem+="$svc ${mem_used[$short]}"$'\n'; else errors=$((errors + 1)); fi
    else
      lines_up+="$svc 0"$'\n'
    fi
    if [ "$health" = unhealthy ]; then lines_healthy+="$svc 0"$'\n'; else lines_healthy+="$svc 1"$'\n'; fi
    lines_restarts+="$svc $restarts"$'\n'
    lines_limit+="$svc $limit"$'\n'

    if [ "$cgroup_ok" = 1 ]; then
      raw="${raw_of[$svc]:-}"
      if [ -n "$raw" ]; then
        if [ -z "${st_total[$svc]:-}" ]; then
          st_total["$svc"]="$raw"
        else
          reset=0
          if [ "${st_id[$svc]}" != "$id" ] || [ "$restarts" -gt "${st_restarts[$svc]}" ] || [ "$raw" -lt "${st_raw[$svc]}" ]; then reset=1; fi
          if [ "$reset" = 0 ]; then
            delta=$((raw - st_raw[$svc]))
          else
            delta="$raw"
            ev="$(oom_events_since "$svc" "${st_epoch[$svc]}" "$run_start")"
            [[ "$ev" =~ ^[0-9]+$ && "$ev" -gt "$delta" ]] && delta="$ev"
          fi
          st_total["$svc"]=$((st_total[$svc] + delta))
        fi
        st_raw["$svc"]="$raw"
        st_id["$svc"]="$id"
        st_restarts["$svc"]="$restarts"
        st_epoch["$svc"]="$run_start"
      fi
    else
      if [ -z "${st_total[$svc]:-}" ]; then st_total["$svc"]=0; st_raw["$svc"]=0; fi
      if [ "$oom" = true ] && [ "${st_finished[$svc]:-}" != "$finished" ]; then
        st_total["$svc"]=$((st_total[$svc] + 1))
      fi
      st_finished["$svc"]="$finished"
      st_id["$svc"]="$id"
      st_restarts["$svc"]="$restarts"
      st_epoch["$svc"]="$run_start"
    fi
    lines_oom+="$svc ${st_total[$svc]:-0}"$'\n'
  done <<<"$inspect"

  emit() { # emit NAME TYPE HELP LINES   (LINES: "service value" per line)
    local name="$1" type="$2" help="$3" lines="$4" s v
    [ "$name" = manuspectrum_container_up ] || metric_family "$name" "$type" "$help"
    while read -r s v; do
      [ -z "$s" ] || metric_sample "$name" "$v" container "$s"
    done <<<"$lines"
  }
  emit manuspectrum_container_up gauge "" "$lines_up"
  emit manuspectrum_container_healthy gauge "0 when the health check fails" "$lines_healthy"
  emit manuspectrum_container_restarts gauge "Docker restart count" "$lines_restarts"
  emit manuspectrum_container_oom_kills counter "Kernel OOM kills in the container, kept across restarts" "$lines_oom"
  emit manuspectrum_container_memory_working_set_bytes gauge "Working set in bytes" "$lines_mem"
  emit manuspectrum_container_memory_limit_bytes gauge "Memory limit in bytes, 0 for none" "$lines_limit"
  metric_family manuspectrum_container_oom_cgroup gauge "1 when OOM kills come from the cgroup counter, 0 for the State.OOMKilled fallback"
  metric_sample manuspectrum_container_oom_cgroup "$cgroup_ok"
  metric_family manuspectrum_container_metrics_errors gauge "Services skipped or without a working set"
  metric_sample manuspectrum_container_metrics_errors "$errors"
  now="$(date +%s)"
  metric_family manuspectrum_container_metrics_last_run_timestamp_seconds gauge "Unix time of the last run"
  metric_sample manuspectrum_container_metrics_last_run_timestamp_seconds "$now"
  metrics_commit
  [ "$cgroup_ok" = 1 ] || log "no readable memory.events under $CGROUP_ROOT: OOM kills fall back to State.OOMKilled"

  : >"$state.tmp"
  for svc in "${!st_total[@]}"; do
    printf '%s %s %s %s %s %s %s\n' "$svc" "${st_total[$svc]}" "${st_raw[$svc]:-0}" "${st_id[$svc]:-none}" \
      "${st_restarts[$svc]:-0}" "${st_finished[$svc]:-none}" "${st_epoch[$svc]:-$run_start}" >>"$state.tmp"
  done
  mv -f "$state.tmp" "$state"
}

# docker_disk: write manuspectrum_docker_disk.prom from `docker system df`;
# returns 1 when docker did not answer or a size could not be read (the file
# is then left as it was, or written without that sample).
docker_disk() {
  local report tag size bytes kind rc=0 name
  local -a ionice_cmd=()
  command -v ionice >/dev/null 2>&1 && ionice_cmd=(ionice -c3)
  local -A kind_total=([images]=0 [containers]=0 [volumes]=0 [build_cache]=0)
  local -a vol_names=() vol_bytes=()
  report="$(nice -n 19 "${ionice_cmd[@]}" timeout "$DF_TIMEOUT" docker system df -v --format \
    '{{range .Images}}{{println "I" .UniqueSize}}{{end}}{{range .Containers}}{{println "C" .Size}}{{end}}{{range .Volumes}}{{println "V" .Size .Name}}{{end}}{{range .BuildCache}}{{println "B" .Size}}{{end}}')" \
    || { log "docker system df -v failed or timed out"; return 1; }
  while read -r tag size name; do
    case "$tag" in
      I) kind=images ;;
      C) kind=containers ;;
      V) kind=volumes ;;
      B) kind=build_cache ;;
      *) continue ;;
    esac
    if bytes="$(to_bytes "$size")"; then
      kind_total[$kind]=$((kind_total[$kind] + bytes))
      if [ "$tag" = V ] && [[ "$name" =~ ^(ms|${PROJECT//[^a-z0-9_-]/})_[a-z0-9_-]+$ ]]; then vol_names+=("$name") vol_bytes+=("$bytes"); fi
    elif [ "$tag" = V ]; then
      log "docker system df -v: no size for a volume"
    else
      rc=1
      log "docker system df -v: unreadable size for $kind"
    fi
  done <<<"$report"

  local i
  metrics_open "$out_dir/manuspectrum_docker_disk.prom"
  metric_family manuspectrum_docker_disk_bytes gauge "Docker disk use by kind, from docker system df"
  for kind in images build_cache containers volumes; do
    metric_sample manuspectrum_docker_disk_bytes "${kind_total[$kind]}" kind "$kind"
  done
  metric_family manuspectrum_docker_volume_bytes gauge "Size of a Compose volume, from docker system df -v"
  for i in "${!vol_names[@]}"; do
    metric_sample manuspectrum_docker_volume_bytes "${vol_bytes[$i]}" volume "${vol_names[$i]}"
  done
  metrics_commit
  return "$rc"
}

disk() {
  local pair name path failed=0 size now start remaining limit
  local -a names=() paths=()
  start=$SECONDS
  [ -n "${DISK_USAGE_AREAS:-}" ] || usage_die "DISK_USAGE_AREAS is empty"
  [ "$DISK_BUDGET" -gt "$DF_TIMEOUT" ] || usage_die "HOST_METRICS_DISK_BUDGET must exceed HOST_METRICS_DF_TIMEOUT"
  for pair in $DISK_USAGE_AREAS; do
    name="${pair%%=*}" path="${pair#*=}"
    [[ " ${AREA_NAMES[*]} " == *" $name "* ]] || usage_die "unknown area '$name' (allowed: ${AREA_NAMES[*]})"
    [[ "$path" == /* && "$path" =~ ^[A-Za-z0-9_./-]+$ ]] || usage_die "area $name: the path must be absolute and plain"
    [ -d "$path" ] || usage_die "area $name: not a directory"
    path="$(realpath "$path")"
    [ "$(findmnt -n -o TARGET --target "$path")" != "$path" ] || usage_die "area $name is a mountpoint: measure a named subdirectory, never a mount root"
    names+=("$name") paths+=("$path")
  done

  local -a ionice_cmd=()
  command -v ionice >/dev/null 2>&1 && ionice_cmd=(ionice -c3)
  local -a lines=()
  local i
  for i in "${!names[@]}"; do
    remaining=$((DISK_BUDGET - DF_TIMEOUT - (SECONDS - start)))
    limit="$DU_TIMEOUT"
    [ "$remaining" -ge "$limit" ] || limit="$remaining"
    if [ "$limit" -le 0 ]; then
      failed=1
      log "du of area ${names[$i]} skipped: the run budget is spent"
    elif size="$(nice -n 19 "${ionice_cmd[@]}" timeout "$limit" du -sB1 -x -- "${paths[$i]}" | awk '{print $1}')" && [[ "$size" =~ ^[0-9]+$ ]]; then
      lines+=("${names[$i]} $size")
    else
      failed=1
      log "du of area ${names[$i]} failed or timed out"
    fi
  done
  docker_disk || failed=1

  now="$(date +%s)"
  metrics_open "$out_dir/manuspectrum_disk_usage.prom"
  metric_family manuspectrum_disk_usage_bytes gauge "Size of a data directory in bytes"
  local line
  for line in "${lines[@]}"; do
    metric_sample manuspectrum_disk_usage_bytes "${line#* }" target "${line%% *}"
  done
  metric_family manuspectrum_disk_usage_failed gauge "1 when a directory could not be measured"
  metric_sample manuspectrum_disk_usage_failed "$failed"
  metric_family manuspectrum_disk_usage_last_run_timestamp_seconds gauge "Unix time of the last run"
  metric_sample manuspectrum_disk_usage_last_run_timestamp_seconds "$now"
  metrics_commit
  if [ "$failed" = 0 ]; then
    metrics_open "$out_dir/manuspectrum_disk_usage_success.prom"
    metric_family manuspectrum_disk_usage_last_success_timestamp_seconds gauge "Unix time of the last run that measured every directory"
    metric_sample manuspectrum_disk_usage_last_success_timestamp_seconds "$now"
    metrics_commit
  fi
  return "$failed"
}

"$mode"
