#!/usr/bin/env bash
# deploy/scripts/tests/test_host_metrics.sh
# Tests of host-metrics.sh (containers, disk) and lib-metrics.sh. docker, du
# and findmnt are stubs on PATH; nothing real is measured. Prints `ok N` /
# `not ok N`; exits non-zero on failure.
# $? after a negated or compound test is the point of every assertion below.
# shellcheck disable=SC2319
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../host-metrics.sh"
LIB="$HERE/../lib-metrics.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/bin" "$TMP/out" "$TMP/data/media" "$TMP/data/restic" "$TMP/data/dumps" "$TMP/data/logs"
OUT="$TMP/out"

cat >"$TMP/bin/docker" <<'STUB'
#!/bin/sh
printf 'docker %s\n' "$*" >>"$CALLS"
[ "$1 $2" != "system df" ] || printf 'docker-nice %s\n' "$(nice)" >>"$CALLS"
[ -z "$STUB_DOCKER_HANG" ] || exec sleep 30
[ -z "$STUB_DOCKER_FAIL" ] || exit 1
[ -z "$STUB_DF_FAIL" ] || [ "$1" != system ] || exit 1
case "$1" in
  ps) cat "$STUB_PS" ;;
  inspect) cat "$STUB_INSPECT" ;;
  stats) cat "$STUB_STATS" ;;
  events) cat "${STUB_EVENTS:-/dev/null}" ;;
  system)
    cat "${STUB_DF_VERBOSE:-/dev/null}"
    ;;
esac
STUB
cat >"$TMP/bin/date" <<'STUB'
#!/bin/sh
if [ -n "$STUB_DATE_BY_DOCKER_CALLS" ] && [ "$1" = +%s ]; then grep -c '^docker ' "$CALLS" || true; else exec /bin/date "$@"; fi
STUB
cat >"$TMP/bin/du" <<'STUB'
#!/bin/sh
printf 'du %s\n' "$*" >>"$CALLS"
for last; do :; done
case "$last" in
  */media) [ -z "$STUB_DU_HANG" ] || exec sleep 30; printf '1000\t%s\n' "$last" ;;
  */restic) printf '2000\t%s\n' "$last" ;;
  */dumps) printf '3000\t%s\n' "$last" ;;
  */logs) printf '4000\t%s\n' "$last" ;;
  *) exit 1 ;;
esac
STUB
cat >"$TMP/bin/findmnt" <<'STUB'
#!/bin/sh
for last; do :; done
if [ "$last" = "$STUB_MOUNT_ROOT" ]; then printf '%s\n' "$last"; else printf '/\n'; fi
STUB
chmod +x "$TMP/bin/"*

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

IDA="$(printf 'a%.0s' $(seq 64))"
IDB="$(printf 'b%.0s' $(seq 64))"
IDC="$(printf 'c%.0s' $(seq 64))"
set_cgroup() { # set_cgroup ID COUNT [systemd|cgroupfs]
  local dir="$TMP/cgroup/system.slice/docker-$1.scope"
  [ "${3:-systemd}" = systemd ] || dir="$TMP/cgroup/docker/$1"
  mkdir -p "$dir"
  printf 'low 0\nhigh 0\nmax 0\noom 0\noom_kill %s\n' "$2" >"$dir/memory.events"
}
set_containers() {
  rm -rf "$TMP/cgroup" "$OUT/.manuspectrum-container-oom.state"
  set_cgroup "$IDA" 0
  set_cgroup "$IDB" 0
  printf '%s\n' "$IDA" "$IDB" >"$TMP/ps"
  printf '%s\n' \
    "$IDA|web|true|healthy|2|false|0001-01-01T00:00:00Z|1073741824" \
    "$IDB|redis-cache|true|none|0|false|0001-01-01T00:00:00Z|0" >"$TMP/inspect"
  printf '%s\n' 'aaaaaaaaaaaa|512MiB / 1GiB' 'bbbbbbbbbbbb|1.5KiB / 7.7GiB' >"$TMP/stats"
}

run() { # run MODE [VAR=value ...]; stdout in $TMP/stdout, stderr in $TMP/stderr
  local mode="$1"
  shift
  : >"$TMP/calls"
  env PATH="$TMP/bin:$PATH" CALLS="$TMP/calls" STUB_PS="$TMP/ps" STUB_INSPECT="$TMP/inspect" STUB_STATS="$TMP/stats" \
    STUB_DF_VERBOSE="$TMP/df_v" STUB_EVENTS="$TMP/events" HOST_METRICS_CGROUP_ROOT="$TMP/cgroup" \
    METRICS_TEXTFILE_DIR="$OUT" HOST_METRICS_DOCKER_TIMEOUT=2 HOST_METRICS_DU_TIMEOUT=2 \
    HOST_METRICS_DF_TIMEOUT=2 HOST_METRICS_DISK_BUDGET=60 \
    DISK_USAGE_AREAS="media=$TMP/data/media restic=$TMP/data/restic dumps=$TMP/data/dumps nginx_logs=$TMP/data/logs" \
    "$@" bash "$SCRIPT" "$mode" >"$TMP/stdout" 2>"$TMP/stderr"
}
sample() { grep -v '^#' "$OUT/$2" | grep -F -- "$1" | awk '{print $NF}'; }

# --- containers
set_containers
run containers
assert "containers: a run with two services succeeds" $?
F=manuspectrum_container.prom
[ "$(sample 'manuspectrum_container_up{container="web"}' $F)" = 1 ]
assert "containers: web is up" $?
[ "$(sample 'manuspectrum_container_restarts{container="web"}' $F)" = 2 ]
assert "containers: web restarts are read from docker inspect" $?
[ "$(sample 'manuspectrum_container_healthy{container="web"}' $F)" = 1 ]
assert "containers: a healthy container is healthy" $?
[ "$(sample 'manuspectrum_container_healthy{container="redis-cache"}' $F)" = 1 ]
assert "containers: a running container without a health check is healthy" $?
[ "$(sample 'manuspectrum_container_memory_working_set_bytes{container="web"}' $F)" = 536870912 ]
assert "containers: 512MiB becomes 536870912 bytes" $?
[ "$(sample 'manuspectrum_container_memory_working_set_bytes{container="redis-cache"}' $F)" = 1536 ]
assert "containers: 1.5KiB becomes 1536 bytes" $?
[ "$(sample 'manuspectrum_container_memory_limit_bytes{container="web"}' $F)" = 1073741824 ]
assert "containers: the memory limit is the HostConfig value" $?
[ "$(sample 'manuspectrum_container_memory_limit_bytes{container="redis-cache"}' $F)" = 0 ]
assert "containers: no limit is 0" $?
[ "$(sample 'manuspectrum_container_oom_kills{container="web"}' $F)" = 0 ]
assert "containers: no OOM kill is a zero counter" $?
grep -q '^manuspectrum_container_metrics_last_run_timestamp_seconds [0-9]\{10,\}$' "$OUT/$F"
assert "containers: the last run timestamp is written" $?
grep -q 'com.docker.compose.project=manuspectrum' "$TMP/calls" && grep -q 'com.docker.compose.oneoff=False' "$TMP/calls"
assert "containers: docker is asked for the project's non-one-off containers" $?
! grep -q "$TMP" "$OUT/$F"
assert "containers: no host path in the output" $?
compgen -G "$OUT/*.tmp" >/dev/null && r=1 || r=0
assert "containers: no temporary file is left" "$r"
[ "$(stat -c %a "$OUT/$F")" = 644 ]
assert "containers: the file is mode 0644" $?

# unhealthy, stopped
printf '%s\n' \
  "$IDA|web|true|unhealthy|0|false|0001-01-01T00:00:00Z|0" \
  "$IDB|worker|false|none|5|false|0001-01-01T00:00:00Z|0" >"$TMP/inspect"
run containers
[ "$(sample 'manuspectrum_container_healthy{container="web"}' $F)" = 0 ]
assert "containers: an unhealthy container is healthy 0" $?
[ "$(sample 'manuspectrum_container_up{container="worker"}' $F)" = 0 ]
assert "containers: a stopped container is up 0" $?
! grep -q 'memory_working_set_bytes{container="worker"}' "$OUT/$F"
assert "containers: a stopped container has no working set sample" $?

# OOM counter: the cgroup v2 memory.events oom_kill of each running container
oom() { sample "manuspectrum_container_oom_kills{container=\"$1\"}" $F; }
set_containers
set_cgroup "$IDA" 3
run containers
[ "$(oom web)" = 3 ] && [ "$(oom redis-cache)" = 0 ]
assert "oom: a first sight exports the cgroup counter" $?
[ "$(sample manuspectrum_container_oom_cgroup $F)" = 1 ]
assert "oom: the source is reported as the cgroup" $?
run containers
[ "$(oom web)" = 3 ]
assert "oom: an unchanged cgroup counter is not counted twice" $?
set_cgroup "$IDA" 4
run containers
[ "$(oom web)" = 4 ]
assert "oom: a child process killed while PID 1 lives increments the counter" $?
# the flag Docker sets on a child kill must not be counted on top
echo "$IDA|web|true|healthy|0|true|2026-10-09T01:00:00Z|0" >"$TMP/inspect"
echo "$IDA" >"$TMP/ps"
run containers
[ "$(oom web)" = 4 ]
assert "oom: State.OOMKilled is ignored while the cgroup counter is readable" $?

# restart of the same container: the cgroup is new, the counter drops, the total keeps
set_cgroup "$IDA" 0
echo "$IDA|web|true|healthy|1|false|0001-01-01T00:00:00Z|0" >"$TMP/inspect"
: >"$TMP/events"
run containers
[ "$(oom web)" = 4 ]
assert "oom: a restart resets the cgroup counter, not the exported total" $?
set_cgroup "$IDA" 2
echo "$IDA|web|true|healthy|1|false|0001-01-01T00:00:00Z|0" >"$TMP/inspect"
run containers
[ "$(oom web)" = 6 ]
assert "oom: kills of the new cgroup add to the total kept across the restart" $?

# PID 1 killed and restarted between two runs: the kill lives only in docker events
set_cgroup "$IDA" 0
echo "$IDA|web|true|healthy|2|false|0001-01-01T00:00:00Z|0" >"$TMP/inspect"
printf '%s\n' oom >"$TMP/events"
run containers
[ "$(oom web)" = 7 ] && grep -q 'docker events .*event=oom' "$TMP/calls" \
  && grep -q 'label=com.docker.compose.service=web' "$TMP/calls"
assert "oom: a restart adds the oom events docker saw since the previous run" $?
: >"$TMP/events"
echo "$IDA|web|true|healthy|3|false|0001-01-01T00:00:00Z|0" >"$TMP/inspect"
run containers
[ "$(oom web)" = 7 ]
assert "oom: a restart without oom events adds nothing" $?

# recreation: another container id, a new cgroup
rm -rf "$TMP/cgroup"
set_cgroup "$IDC" 1
echo "$IDC|web|true|healthy|0|false|0001-01-01T00:00:00Z|0" >"$TMP/inspect"
echo "$IDC" >"$TMP/ps"
: >"$TMP/events"
run containers
[ "$(oom web)" = 8 ]
assert "oom: a recreated container keeps the total and counts its own kills" $?

# the event window opens after the cgroup counters are read
set_containers
set_cgroup "$IDA" 1
run containers STUB_DATE_BY_DOCKER_CALLS=1
[ "$(awk '$1 == "web" {print $7}' "$OUT/.manuspectrum-container-oom.state")" -eq 3 ]
assert "oom: the next event window starts after docker and memory.events were read" $?

# cgroupfs driver layout
set_containers
rm -rf "$TMP/cgroup"
set_cgroup "$IDA" 5 cgroupfs
run containers
[ "$(oom web)" = 5 ] && [ "$(sample manuspectrum_container_oom_cgroup $F)" = 1 ]
assert "oom: the cgroupfs layout (docker/<id>) is read too" $?

# no memory.events at all: State.OOMKilled fallback, said so
rm -rf "$TMP/cgroup" "$OUT/.manuspectrum-container-oom.state"
echo "$IDA" >"$TMP/ps"
echo "$IDA|web|true|healthy|1|true|2026-10-09T01:00:00Z|1073741824" >"$TMP/inspect"
run containers
[ "$(oom web)" = 1 ] && [ "$(sample manuspectrum_container_oom_cgroup $F)" = 0 ] && grep -q 'memory.events' "$TMP/stderr"
assert "oom: without memory.events the exit flag counts once and the fallback is reported" $?
run containers
[ "$(oom web)" = 1 ]
assert "oom: the fallback does not count the same exit twice" $?
sed -i 's/2026-10-09T01:00:00Z/2026-10-09T02:00:00Z/' "$TMP/inspect"
run containers
[ "$(oom web)" = 2 ]
assert "oom: the fallback counts a new exit" $?

# a malformed id never reaches a path
set_containers
echo "../../x|web|true|healthy|0|false|0001-01-01T00:00:00Z|0" >"$TMP/inspect"
echo "../../x" >"$TMP/ps"
run containers
[ "$(sample manuspectrum_container_oom_cgroup $F)" = 0 ]
assert "oom: an id that is not 64 hex digits is not turned into a path" $?

# an odd name is refused
set_containers
printf '%s\n' \
  "$IDA|web|true|healthy|0|false|0001-01-01T00:00:00Z|0" \
  "$IDB|Odd Name;x|true|healthy|0|false|0001-01-01T00:00:00Z|0" >"$TMP/inspect"
run containers
assert "containers: an odd service name does not fail the run" $?
! grep -q 'Odd' "$OUT/$F"
assert "containers: an odd service name is kept out of the output" $?
[ "$(sample 'manuspectrum_container_metrics_errors' $F)" = 1 ]
assert "containers: a refused service is counted as an error" $?

# a service missing from docker stats: the rest is written
set_containers
echo 'bbbbbbbbbbbb|1KiB / 1GiB' >"$TMP/stats"
echo "$IDA|web|true|healthy|0|false|0001-01-01T00:00:00Z|0" >"$TMP/inspect"
run containers
! grep -q 'memory_working_set_bytes{container="web"}' "$OUT/$F" && grep -q 'container_up{container="web"} 1' "$OUT/$F"
assert "containers: a service missing from docker stats is skipped, the rest is written" $?
[ "$(sample 'manuspectrum_container_metrics_errors' $F)" = 1 ]
assert "containers: the missing working set counts an error" $?

# docker down: nothing rewritten, exit 1
before="$(cat "$OUT/$F")"
set_containers
run containers STUB_DOCKER_FAIL=1
rc=$?
[ "$rc" -eq 1 ] && [ "$(cat "$OUT/$F")" = "$before" ]
assert "containers: docker failing leaves the file untouched and exits 1" $?
start=$SECONDS
run containers STUB_DOCKER_HANG=1
rc=$?
[ "$rc" -eq 1 ] && [ $((SECONDS - start)) -lt 10 ] && [ "$(cat "$OUT/$F")" = "$before" ]
assert "containers: a hung docker is cut by the timeout" $?

# --- disk
printf '%s\n' \
  'I 3.5GB' 'I 307MB' 'C 1.4MB' 'C 1.5MB' 'B 500kB' 'B 12kB' \
  'V 1.405GB ms_pg_data' 'V 2.5GB ms_es_data' 'V 0B ms_prometheus_data' 'V 87.65MB ms_cantaloupe_cache' \
  'V 4kB manuspectrum_beat' 'V 9GB other_data' 'V N/A ms_unsized' 'V 1MB Bad_Name' 'V 1MB ms_bad.name' \
  'V 47.97MB 5e5038ad36bdc6357260df2fa3073a2801ceb848226341359f4235b233e4ed8d' >"$TMP/df_v"
G=manuspectrum_docker_disk.prom
D=manuspectrum_disk_usage.prom
S=manuspectrum_disk_usage_success.prom
run disk
assert "disk: a run succeeds" $?
for t in media:1000 restic:2000 dumps:3000 nginx_logs:4000; do
  [ "$(sample "manuspectrum_disk_usage_bytes{target=\"${t%%:*}\"}" $D)" = "${t##*:}" ]
  assert "disk: ${t%%:*} is measured" $?
done
[ "$(sample 'manuspectrum_disk_usage_failed' $D)" = 0 ]
assert "disk: no failure is failed 0" $?
grep -q '^manuspectrum_disk_usage_last_run_timestamp_seconds [0-9]\{10,\}$' "$OUT/$D"
assert "disk: the last run timestamp is written" $?
grep -q '^manuspectrum_disk_usage_last_success_timestamp_seconds [0-9]\{10,\}$' "$OUT/$S"
assert "disk: the success file is written" $?
grep -q -- 'du -sB1 -x' "$TMP/calls"
assert "disk: du stays on one filesystem and reports bytes" $?
! grep -q "$TMP" "$OUT/$D"
assert "disk: no host path in the output" $?
[ "$(grep -c '^du ' "$TMP/calls")" -eq 4 ]
assert "disk: only the four named directories are measured" $?
success_before="$(cat "$OUT/$S")"
sleep 1

[ "$(sample 'manuspectrum_docker_disk_bytes{kind="images"}' $G)" = 3807000000 ] \
  && [ "$(sample 'manuspectrum_docker_disk_bytes{kind="containers"}' $G)" = 2900000 ] \
  && [ "$(sample 'manuspectrum_docker_disk_bytes{kind="volumes"}' $G)" = 13042624000 ] \
  && [ "$(sample 'manuspectrum_docker_disk_bytes{kind="build_cache"}' $G)" = 512000 ]
assert "docker disk: images, containers, volumes and build cache are exported in bytes" $?
[ "$(sample 'manuspectrum_docker_volume_bytes{volume="ms_pg_data"}' $G)" = 1405000000 ] \
  && [ "$(sample 'manuspectrum_docker_volume_bytes{volume="ms_es_data"}' $G)" = 2500000000 ] \
  && [ "$(sample 'manuspectrum_docker_volume_bytes{volume="ms_prometheus_data"}' $G)" = 0 ] \
  && [ "$(sample 'manuspectrum_docker_volume_bytes{volume="ms_cantaloupe_cache"}' $G)" = 87650000 ] \
  && [ "$(sample 'manuspectrum_docker_volume_bytes{volume="manuspectrum_beat"}' $G)" = 4000 ]
assert "docker disk: named volumes are exported with their size (0B, decimal units, project prefix)" $?
[ "$(grep -c '^manuspectrum_docker_volume_bytes{' "$OUT/$G")" -eq 5 ]
assert "docker disk: anonymous, foreign, unsized and oddly named volumes are left out" $?
[ "$(grep -c '^docker system' "$TMP/calls")" -eq 1 ] && grep -q 'system df -v' "$TMP/calls"
assert "docker disk: one docker system df -v call gives the totals and the volumes" $?
[ "$(sed -n 's/^docker-nice //p' "$TMP/calls")" -gt "$(nice)" ]
assert "docker disk: the docker system df call runs at a lowered priority" $?
! grep -q "$TMP" "$OUT/$G"
assert "docker disk: no host path in the output" $?

docker_before="$(cat "$OUT/$G")"
run disk STUB_DF_FAIL=1
rc=$?
[ "$rc" -eq 1 ] && [ "$(cat "$OUT/$G")" = "$docker_before" ] && [ "$(sample 'manuspectrum_disk_usage_failed' $D)" = 1 ] \
  && [ "$(sample 'manuspectrum_disk_usage_bytes{target="media"}' $D)" = 1000 ]
assert "docker disk: a docker failure exits 1, keeps the old file, still measures the directories" $?
run disk
success_before="$(cat "$OUT/$S")"
sleep 1

start=$SECONDS
run disk STUB_DU_HANG=1 HOST_METRICS_DU_TIMEOUT=1
rc=$?
[ "$rc" -eq 1 ] && [ $((SECONDS - start)) -lt 10 ]
assert "disk: a du timeout exits 1 within the timeout" $?
[ "$(sample 'manuspectrum_disk_usage_failed' $D)" = 1 ]
assert "disk: a du timeout gives failed 1" $?
! grep -q 'target="media"' "$OUT/$D" && grep -q 'target="restic"' "$OUT/$D"
assert "disk: the timed-out target has no sample, the others do" $?
[ "$(cat "$OUT/$S")" = "$success_before" ]
assert "disk: the success file is unchanged after a failure" $?
grep -q '^manuspectrum_disk_usage_last_run_timestamp_seconds' "$OUT/$D"
assert "disk: a failed run still records its last run" $?

start=$SECONDS
run disk STUB_DU_HANG=1 HOST_METRICS_DU_TIMEOUT=300 HOST_METRICS_DISK_BUDGET=4
rc=$?
[ "$rc" -eq 1 ] && [ $((SECONDS - start)) -lt 10 ] && ! grep -q 'target="media"' "$OUT/$D"
assert "disk: the per-target timeout is cut to what is left of the run budget" $?
start=$SECONDS
run disk STUB_DU_HANG=1 HOST_METRICS_DU_TIMEOUT=300 HOST_METRICS_DISK_BUDGET=3
rc=$?
[ "$rc" -eq 1 ] && [ $((SECONDS - start)) -lt 10 ] && grep -q 'budget is spent' "$TMP/stderr" && ! grep -q 'target="restic"' "$OUT/$D"
assert "disk: a target left without time is skipped and counted as failed" $?
run disk HOST_METRICS_DISK_BUDGET=2
[ $? -eq 2 ]
assert "disk: a budget that cannot hold the docker call is refused" $?
grep -q 'HOST_METRICS_DU_TIMEOUT:-300' "$SCRIPT" && grep -q 'HOST_METRICS_DISK_BUDGET:-840' "$SCRIPT"
assert "disk: the defaults are 300 s per target and 840 s in all (unit limit 15 min)" $?

run disk STUB_MOUNT_ROOT="$TMP/data/restic"
rc=$?
[ "$rc" -eq 2 ] && grep -q 'mount' "$TMP/stderr"
assert "disk: a mountpoint root is refused (exit 2)" $?
! grep -q '^du ' "$TMP/calls"
assert "disk: nothing is measured when an area is refused" $?

run disk DISK_USAGE_AREAS="home=$TMP/data/media"
[ $? -eq 2 ]
assert "disk: an area outside the closed list is refused" $?
run disk DISK_USAGE_AREAS="media=relative/path"
[ $? -eq 2 ]
assert "disk: a relative path is refused" $?
run disk DISK_USAGE_AREAS="media=$TMP/data/missing"
[ $? -eq 2 ]
assert "disk: a missing directory is refused" $?
run disk DISK_USAGE_AREAS=""
[ $? -eq 2 ]
assert "disk: an empty area list is refused" $?

# --- arguments
run nonsense
[ $? -eq 2 ]
assert "an unknown mode is refused (exit 2)" $?
run containers METRICS_TEXTFILE_DIR=relative
[ $? -eq 2 ]
assert "a relative METRICS_TEXTFILE_DIR is refused" $?

# --- lib-metrics.sh
(
  # shellcheck source=lib-metrics.sh
  # shellcheck source-path=SCRIPTDIR/..
  source "$LIB"
  metrics_open "$TMP/lib.prom"
  ! metric_sample 'bad name' 1
)
assert "lib: a bad metric name is refused" $?
(
  # shellcheck source=lib-metrics.sh
  # shellcheck source-path=SCRIPTDIR/..
  source "$LIB"
  metrics_open "$TMP/lib2.prom"
  metric_family manuspectrum_x gauge "Help text"
  ! metric_sample manuspectrum_x 1 path "/etc/passwd"
)
assert "lib: a label value with a slash is refused" $?
[ ! -e "$TMP/lib2.prom" ] && [ ! -e "$TMP/lib2.prom.tmp" ]
assert "lib: a refused sample leaves no file" $?

[ "$failed" -eq 0 ]
