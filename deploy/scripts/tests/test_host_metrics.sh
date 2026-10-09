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
[ -z "$STUB_DOCKER_HANG" ] || exec sleep 30
[ -z "$STUB_DOCKER_FAIL" ] || exit 1
case "$1" in
  ps) cat "$STUB_PS" ;;
  inspect) cat "$STUB_INSPECT" ;;
  stats) cat "$STUB_STATS" ;;
esac
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

set_containers() {
  printf '%s\n' aaaaaaaaaaaa1111 bbbbbbbbbbbb2222 >"$TMP/ps"
  printf '%s\n' \
    'aaaaaaaaaaaa1111|web|true|healthy|2|false|0001-01-01T00:00:00Z|1073741824' \
    'bbbbbbbbbbbb2222|redis-cache|true|none|0|false|0001-01-01T00:00:00Z|0' >"$TMP/inspect"
  printf '%s\n' 'aaaaaaaaaaaa|512MiB / 1GiB' 'bbbbbbbbbbbb|1.5KiB / 7.7GiB' >"$TMP/stats"
}

run() { # run MODE [VAR=value ...]; stdout in $TMP/stdout, stderr in $TMP/stderr
  local mode="$1"
  shift
  : >"$TMP/calls"
  env PATH="$TMP/bin:$PATH" CALLS="$TMP/calls" STUB_PS="$TMP/ps" STUB_INSPECT="$TMP/inspect" STUB_STATS="$TMP/stats" \
    METRICS_TEXTFILE_DIR="$OUT" HOST_METRICS_DOCKER_TIMEOUT=2 HOST_METRICS_DU_TIMEOUT=2 \
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
  'aaaaaaaaaaaa1111|web|true|unhealthy|0|false|0001-01-01T00:00:00Z|0' \
  'bbbbbbbbbbbb2222|worker|false|none|5|false|0001-01-01T00:00:00Z|0' >"$TMP/inspect"
run containers
[ "$(sample 'manuspectrum_container_healthy{container="web"}' $F)" = 0 ]
assert "containers: an unhealthy container is healthy 0" $?
[ "$(sample 'manuspectrum_container_up{container="worker"}' $F)" = 0 ]
assert "containers: a stopped container is up 0" $?
! grep -q 'memory_working_set_bytes{container="worker"}' "$OUT/$F"
assert "containers: a stopped container has no working set sample" $?

# OOM counter: counted once per finish time
echo aaaaaaaaaaaa1111 >"$TMP/ps"
echo 'aaaaaaaaaaaa1111|web|true|healthy|1|true|2026-10-09T01:00:00Z|1073741824' >"$TMP/inspect"
run containers
[ "$(sample 'manuspectrum_container_oom_kills{container="web"}' $F)" = 1 ]
assert "containers: an OOM-killed container counts one" $?
run containers
[ "$(sample 'manuspectrum_container_oom_kills{container="web"}' $F)" = 1 ]
assert "containers: the same OOM kill is not counted twice" $?
sed -i 's/2026-10-09T01:00:00Z/2026-10-09T02:00:00Z/' "$TMP/inspect"
run containers
[ "$(sample 'manuspectrum_container_oom_kills{container="web"}' $F)" = 2 ]
assert "containers: a new OOM kill increments the counter" $?

# an odd name is refused
set_containers
printf '%s\n' \
  'aaaaaaaaaaaa1111|web|true|healthy|0|false|0001-01-01T00:00:00Z|0' \
  'bbbbbbbbbbbb2222|Odd Name;x|true|healthy|0|false|0001-01-01T00:00:00Z|0' >"$TMP/inspect"
run containers
assert "containers: an odd service name does not fail the run" $?
! grep -q 'Odd' "$OUT/$F"
assert "containers: an odd service name is kept out of the output" $?
[ "$(sample 'manuspectrum_container_metrics_errors' $F)" = 1 ]
assert "containers: a refused service is counted as an error" $?

# a service missing from docker stats: the rest is written
set_containers
echo 'bbbbbbbbbbbb|1KiB / 1GiB' >"$TMP/stats"
echo 'aaaaaaaaaaaa1111|web|true|healthy|0|false|0001-01-01T00:00:00Z|0' >"$TMP/inspect"
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
