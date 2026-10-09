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
#   manuspectrum_container_oom_kills                 counter kept in a state file next to the
#                                                    output: +1 per OOM-killed exit seen
#   manuspectrum_container_memory_working_set_bytes  docker stats (usage minus inactive file cache)
#   manuspectrum_container_memory_limit_bytes        HostConfig.Memory, 0 = no limit
#   manuspectrum_container_metrics_errors            services skipped or without a working set
#   manuspectrum_container_metrics_last_run_timestamp_seconds
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
# directory. Each `du` runs under nice, ionice and
# HOST_METRICS_DU_TIMEOUT (default 600 s).
#
# Environment: METRICS_TEXTFILE_DIR (absolute, existing), DISK_USAGE_AREAS,
# COMPOSE_PROJECT (default manuspectrum), HOST_METRICS_DOCKER_TIMEOUT
# (default 20 s), HOST_METRICS_DU_TIMEOUT. Exit: 0 ok, 1 a measurement failed,
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
DU_TIMEOUT="${HOST_METRICS_DU_TIMEOUT:-600}"
AREA_NAMES=(media restic dumps nginx_logs)

case "${1:-}" in
  containers | disk) mode="$1" ;;
  -h | --help) sed -n '2,/^set -euo/p' "$0" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
  *) usage_die "usage: host-metrics.sh containers|disk (see --help)" ;;
esac
out_dir="${METRICS_TEXTFILE_DIR:-}"
[[ "$out_dir" == /* && -d "$out_dir" ]] || usage_die "METRICS_TEXTFILE_DIR must be an existing absolute directory (got '$out_dir')"
[[ "$DOCKER_TIMEOUT" =~ ^[0-9]+$ && "$DU_TIMEOUT" =~ ^[0-9]+$ ]] || usage_die "timeouts must be whole seconds"

# Docker's "512MiB", "1.5KiB", "3GB" into whole bytes.
to_bytes() { # to_bytes TEXT
  awk -v s="$1" 'BEGIN {
    if (match(s, /^[0-9]+(\.[0-9]+)?/) == 0) exit 1
    num = substr(s, 1, RLENGTH); unit = substr(s, RLENGTH + 1)
    m["B"] = 1; m["kB"] = 1e3; m["KB"] = 1e3; m["MB"] = 1e6; m["GB"] = 1e9; m["TB"] = 1e12
    m["KiB"] = 1024; m["MiB"] = 1048576; m["GiB"] = 1073741824; m["TiB"] = 1099511627776
    if (!(unit in m)) exit 1
    printf "%.0f\n", num * m[unit]
  }'
}

containers() {
  local ids inspect stats errors=0 id svc running health restarts oom finished limit short mem now
  local state="$out_dir/.manuspectrum-container-oom.state"
  declare -A oom_count oom_finished mem_used
  ids="$(timeout "$DOCKER_TIMEOUT" docker ps -a -q --no-trunc \
    --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.oneoff=False")" || { log "docker ps failed or timed out"; return 1; }
  [ -n "$ids" ] || { log "no container found for project $PROJECT"; return 1; }
  # shellcheck disable=SC2086  # one argument per container id
  inspect="$(timeout "$DOCKER_TIMEOUT" docker inspect --format \
    '{{.Id}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}|{{.RestartCount}}|{{.State.OOMKilled}}|{{.State.FinishedAt}}|{{.HostConfig.Memory}}' \
    $ids)" || { log "docker inspect failed or timed out"; return 1; }
  # shellcheck disable=SC2086
  stats="$(timeout "$DOCKER_TIMEOUT" docker stats --no-stream --format '{{.ID}}|{{.MemUsage}}' $ids)" || { stats=""; errors=$((errors + 1)); log "docker stats failed or timed out"; }

  while IFS='|' read -r id mem; do
    [ -n "$id" ] || continue
    mem="${mem%% /*}"
    mem_used["${id:0:12}"]="$(to_bytes "${mem// /}")" || true
  done <<<"$stats"

  if [ -f "$state" ]; then
    while read -r svc id finished; do
      [[ "$svc" =~ ^[a-z0-9_-]+$ && "$id" =~ ^[0-9]+$ ]] || continue
      oom_count["$svc"]="$id"
      oom_finished["$svc"]="$finished"
    done <"$state"
  fi

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
    if [ "$oom" = true ] && [ "${oom_finished[$svc]:-}" != "$finished" ]; then
      oom_count["$svc"]=$(("${oom_count[$svc]:-0}" + 1))
      oom_finished["$svc"]="$finished"
    fi
    lines_oom+="$svc ${oom_count[$svc]:-0}"$'\n'
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
  emit manuspectrum_container_oom_kills counter "OOM-killed exits seen" "$lines_oom"
  emit manuspectrum_container_memory_working_set_bytes gauge "Working set in bytes" "$lines_mem"
  emit manuspectrum_container_memory_limit_bytes gauge "Memory limit in bytes, 0 for none" "$lines_limit"
  metric_family manuspectrum_container_metrics_errors gauge "Services skipped or without a working set"
  metric_sample manuspectrum_container_metrics_errors "$errors"
  now="$(date +%s)"
  metric_family manuspectrum_container_metrics_last_run_timestamp_seconds gauge "Unix time of the last run"
  metric_sample manuspectrum_container_metrics_last_run_timestamp_seconds "$now"
  metrics_commit

  : >"$state.tmp"
  for svc in "${!oom_count[@]}"; do printf '%s %s %s\n' "$svc" "${oom_count[$svc]}" "${oom_finished[$svc]:-none}" >>"$state.tmp"; done
  mv -f "$state.tmp" "$state"
}

disk() {
  local pair name path failed=0 size now
  local -a names=() paths=()
  [ -n "${DISK_USAGE_AREAS:-}" ] || usage_die "DISK_USAGE_AREAS is empty"
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
    if size="$(nice -n 19 "${ionice_cmd[@]}" timeout "$DU_TIMEOUT" du -sB1 -x -- "${paths[$i]}" | awk '{print $1}')" && [[ "$size" =~ ^[0-9]+$ ]]; then
      lines+=("${names[$i]} $size")
    else
      failed=1
      log "du of area ${names[$i]} failed or timed out"
    fi
  done

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
