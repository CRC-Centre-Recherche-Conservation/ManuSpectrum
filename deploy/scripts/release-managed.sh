#!/usr/bin/env bash
# Prints `sha256  path` for every file Ansible renders or installs on the host,
# sorted by path, so the update can compare what a tag would install with what
# the host holds. Paths that do not exist are left out.
# Usage: release-managed.sh --worktree DIR           tracked files, worktree content
#        release-managed.sh --ref REF [--repo DIR]   blobs at REF (default repo: cwd)
# The managed list is_managed() is the only one; this script is itself installed.
set -uo pipefail

usage() { echo "usage: release-managed.sh --worktree DIR | --ref REF [--repo DIR]" >&2; exit 2; }
refuse() { echo "release-managed: $*" >&2; exit 1; }

is_managed() {
  case "$1" in
    deploy/ansible/site.yml | deploy/ansible/roles/*) return 0 ;;
    deploy/systemd/*.in | deploy/logrotate/*.in) return 0 ;;
    deploy/sbin/*) return 0 ;;
    deploy/scripts/release-update.sh | deploy/scripts/release-watch.sh | deploy/scripts/release-managed.sh) return 0 ;;
    deploy/scripts/release-verify.sh | deploy/scripts/release-ref-guard.sh) return 0 ;;
    deploy/scripts/lib-release.sh | deploy/scripts/lib-metrics.sh | deploy/scripts/image-digest.sh) return 0 ;;
  esac
  return 1
}

no_dotdot() { # a path with a `..` component is refused
  case "/$1/" in */../*) refuse "'$1' contains '..'" ;; esac
}

mode="" dir="" ref="" repo=""
while [ $# -gt 0 ]; do
  case "$1" in
    --worktree) [ $# -ge 2 ] || usage; [ -z "$mode" ] || usage; mode=worktree; dir="$2"; shift 2 ;;
    --ref) [ $# -ge 2 ] || usage; [ -z "$mode" ] || usage; mode=ref; ref="$2"; shift 2 ;;
    --repo) [ $# -ge 2 ] || usage; repo="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$mode" ] || usage
[ -z "$repo" ] || [ "$mode" = ref ] || usage

emit() { LC_ALL=C sort -k2; }

if [ "$mode" = worktree ]; then
  [ -n "$dir" ] || usage
  no_dotdot "$dir"
  [ -d "$dir" ] || refuse "'$dir' is not a directory"
  git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 || refuse "'$dir' is not a git work tree"
  top="$(git -C "$dir" rev-parse --show-toplevel)" || refuse "cannot resolve '$dir'"
  while IFS= read -r -d '' path; do
    is_managed "$path" || continue
    if [ ! -f "$top/$path" ] || [ -L "$top/$path" ]; then continue; fi
    printf '%s  %s\n' "$(sha256sum <"$top/$path" | cut -d' ' -f1)" "$path"
  done < <(git -C "$top" ls-files -z) | emit
else
  [[ "$ref" =~ ^[A-Za-z0-9][A-Za-z0-9._/@-]*$ ]] || refuse "'$ref' is not a valid ref name"
  case "$ref" in *..*) refuse "'$ref' is not a valid ref name" ;; esac
  if [ -n "$repo" ]; then
    no_dotdot "$repo"
    [ -d "$repo" ] || refuse "'$repo' is not a directory"
  else
    repo="."
  fi
  commit="$(git -C "$repo" rev-parse --verify --quiet "$ref^{commit}")" || refuse "'$ref' is not a commit of '$repo'"
  while IFS= read -r -d '' entry; do
    mode_bits="${entry%% *}"
    path="${entry#*$'\t'}"
    case "$mode_bits" in 100644 | 100755) ;; *) continue ;; esac
    is_managed "$path" || continue
    printf '%s  %s\n' "$(git -C "$repo" cat-file blob "$commit:$path" | sha256sum | cut -d' ' -f1)" "$path"
  done < <(git -C "$repo" ls-tree -r -z "$commit") | emit
fi
