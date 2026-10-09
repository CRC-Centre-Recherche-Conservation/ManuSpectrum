#!/usr/bin/env bash
# Fails when the explorer's marker string reaches an initial file of any
# webpack entry, or is missing from the lazy analysis-explorer chunk.
# Usage: deploy/docker/check-explorer-bundle.sh [webpack/webpack-stats.json]
set -euo pipefail
STATS="${1:-webpack/webpack-stats.json}"
MARKER="__MS_EXPLORER_CHUNK__"
python3 - "$STATS" "$MARKER" <<'PY'
import json, pathlib, sys

stats = json.load(open(sys.argv[1]))
marker = sys.argv[2].encode()
assets = stats["assets"]
if stats.get("status") != "done":
    sys.exit(f"stats status is {stats.get('status')!r}")

def path(name):
    return pathlib.Path(assets[name]["path"])

leaks = []
for entry, files in stats["chunks"].items():
    for name in files:
        if name.endswith(".js") and marker in path(name).read_bytes():
            leaks.append((entry, name))
lazy = [
    name for name in assets
    if name.endswith(".js") and "analysis-explorer" in name and marker in path(name).read_bytes()
]
entries = len(stats["chunks"])
print(f"entries checked: {entries}; initial files carrying the marker: {len(leaks)}; lazy chunks carrying it: {len(lazy)}")
for entry, name in leaks:
    print(f"LEAK {entry}: {name}")
if leaks or not lazy:
    sys.exit(1)
PY
