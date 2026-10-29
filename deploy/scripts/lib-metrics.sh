#!/usr/bin/env bash
# Prometheus textfile writer for the host scripts (host-metrics.sh). Sourced,
# never executed; `set -euo pipefail` is the caller's.
#
# One file is built at a time: metrics_open FILE, then metric_family and
# metric_sample calls, then metrics_commit, which sets mode 0644 and renames
# the temporary file over FILE so the node_exporter textfile collector never
# reads half a file. Metric names match ^manuspectrum_[a-z_]+$, label names
# ^[a-z_]+$ and label values ^[a-z0-9_-]+$ (a closed vocabulary chosen by the
# caller: never a path, an id or free text), values are plain numbers.
# Any violation returns 1 and leaves FILE untouched.

METRICS_FILE=""

metrics_open() { # metrics_open FILE
  METRICS_FILE="$1"
  : >"$METRICS_FILE.tmp"
}

metrics_abort() {
  rm -f "${METRICS_FILE:?}.tmp"
  return 1
}

metric_family() { # metric_family NAME TYPE HELP
  local name="$1" type="$2" help="$3"
  [[ "$name" =~ ^manuspectrum_[a-z_]+$ ]] || { metrics_abort; return 1; }
  [[ "$type" =~ ^(gauge|counter)$ ]] || { metrics_abort; return 1; }
  [[ "$help" =~ ^[A-Za-z0-9\ ,.:/()_-]*$ ]] || { metrics_abort; return 1; }
  printf '# HELP %s %s\n# TYPE %s %s\n' "$name" "$help" "$name" "$type" >>"$METRICS_FILE.tmp"
}

metric_sample() { # metric_sample NAME VALUE [LABEL VALUE ...]
  local name="$1" value="$2" labels="" key val
  shift 2
  [[ "$name" =~ ^manuspectrum_[a-z_]+$ ]] || { metrics_abort; return 1; }
  [[ "$value" =~ ^[0-9]+(\.[0-9]+)?$ ]] || { metrics_abort; return 1; }
  [ "$(($# % 2))" = 0 ] || { metrics_abort; return 1; }
  while [ "$#" -gt 0 ]; do
    key="$1" val="$2"
    shift 2
    [[ "$key" =~ ^[a-z_]+$ && "$val" =~ ^[a-z0-9_-]+$ ]] || { metrics_abort; return 1; }
    labels+="${labels:+,}$key=\"$val\""
  done
  [ -z "$labels" ] || labels="{$labels}"
  printf '%s%s %s\n' "$name" "$labels" "$value" >>"$METRICS_FILE.tmp"
}

metrics_commit() {
  chmod 0644 "$METRICS_FILE.tmp" && mv -f "$METRICS_FILE.tmp" "$METRICS_FILE"
}
