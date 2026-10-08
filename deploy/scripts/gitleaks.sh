#!/usr/bin/env bash
# Secret scan of this repository with one pinned gitleaks image. The only
# caller of that image: the pre-commit hook, deploy/check-stack.sh, the
# rehearsal check.sh and the secret-scan workflow all go through it.
set -euo pipefail

GITLEAKS_IMAGE="${GITLEAKS_IMAGE:-zricethezav/gitleaks:v8.30.1@sha256:c00b6bd0aeb3071cbcb79009cb16a60dd9e0a7c60e2be9ab65d25e6bc8abbb7f}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") MODE [ARGS]

Modes:
  staged            added lines of the staged changes (pre-commit)
  range BASE HEAD   every commit in BASE..HEAD, so a secret added and removed
                    inside the range is still found
  history           every commit of the current history
  tree              every file Git tracks or would track; ignored files are skipped

Runs in the current repository (a linked worktree works) with .gitleaks.toml at
its top level. Findings are redacted. Exit 0 clean, 1 leaks, 2 usage or setup error.
USAGE
}

case "${1:-}" in
  -h | --help) usage; exit 0 ;;
  staged | history | tree) [ "$#" -eq 1 ] || { usage >&2; exit 2; } ;;
  range) [ "$#" -eq 3 ] || { usage >&2; exit 2; } ;;
  *) usage >&2; exit 2 ;;
esac
MODE="$1"

command -v docker >/dev/null 2>&1 || { echo "gitleaks.sh: docker is required" >&2; exit 2; }
TOP="$(git rev-parse --show-toplevel)"
COMMON="$(cd "$TOP" && git rev-parse --path-format=absolute --git-common-dir)"
CONFIG="$TOP/.gitleaks.toml"
[ -f "$CONFIG" ] || { echo "gitleaks.sh: $CONFIG not found" >&2; exit 2; }

COMMON_FLAGS=(--config "$CONFIG" --redact --verbose --no-banner)

# The top level and the Git directory are mounted at their own absolute paths:
# a linked worktree's .git file points at the common directory by absolute path.
git_scan() {
  local mounts=(-v "$TOP:$TOP:ro")
  case "$COMMON/" in "$TOP/"*) ;; *) mounts+=(-v "$COMMON:$COMMON:ro") ;; esac
  # `git commit -a` and `git commit <path>` hand the hook a temporary index.
  local env=()
  if [ -n "${GIT_INDEX_FILE:-}" ]; then
    case "$GIT_INDEX_FILE" in
      /*) env+=(-e "GIT_INDEX_FILE=$GIT_INDEX_FILE") ;;
      *) env+=(-e "GIT_INDEX_FILE=$PWD/$GIT_INDEX_FILE") ;;
    esac
    case "${env[1]#GIT_INDEX_FILE=}" in
      "$TOP/"* | "$COMMON/"*) ;;
      *) echo "gitleaks.sh: GIT_INDEX_FILE is outside the repository; cannot scan it" >&2; exit 2 ;;
    esac
  fi
  docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp ${env[@]+"${env[@]}"} "${mounts[@]}" -w "$TOP" \
    "$GITLEAKS_IMAGE" git "$@" "${COMMON_FLAGS[@]}" "$TOP"
}

case "$MODE" in
  staged) git_scan --pre-commit --staged ;;
  range) git_scan --log-opts="$2..$3" ;;
  history) git_scan ;;
  tree)
    cd "$TOP"
    # Deleted-but-listed files are skipped by --ignore-failed-read.
    git ls-files -z -co --exclude-standard --deduplicate |
      tar --null --no-recursion --ignore-failed-read -T - -cf - 2>/dev/null |
      docker run --rm -i -u "$(id -u):$(id -g)" -e HOME=/tmp \
        -v "$CONFIG:/config/gitleaks.toml:ro" --entrypoint sh "$GITLEAKS_IMAGE" -c '
          d=$(mktemp -d) && tar -x -C "$d" && exec gitleaks dir "$d" "$@"' sh \
        --config /config/gitleaks.toml --redact --verbose --no-banner
    ;;
esac
