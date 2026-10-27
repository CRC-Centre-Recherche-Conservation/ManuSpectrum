#!/usr/bin/env bash
# deploy/scripts/tests/test_release_managed.sh
# Tests of release-managed.sh on throwaway repositories: both modes print the
# same fingerprints, any change to a managed file shows, a change elsewhere
# does not, and bad arguments are refused. Prints `ok N` / `not ok N`; exits
# non-zero on failure.
# shellcheck disable=SC2319,SC2015,SC2001,SC2016,SC2119,SC2120,SC2143
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$HERE/../release-managed.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }
check() { # check DESC CONDITION-COMMAND...
  local desc="$1"; shift
  if "$@"; then ok "$desc"; else not_ok "$desc"; fi
}

export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@manuspectrum.test GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@manuspectrum.test
REPO="$TMP/repo"
git init -q "$REPO"
cd "$REPO" || exit 1
git config commit.gpgsign false
git config tag.gpgsign false
mkdir -p deploy/ansible/roles/app/tasks deploy/ansible/roles/app/templates deploy/ansible/tests \
  deploy/ansible/inventories/example deploy/systemd deploy/logrotate deploy/sbin deploy/scripts/tests
echo play >deploy/ansible/site.yml
echo tasks >deploy/ansible/roles/app/tasks/main.yml
echo tpl >deploy/ansible/roles/app/templates/env.j2
echo t >deploy/ansible/tests/test_x.py
echo r >deploy/ansible/README.md
echo i >deploy/ansible/inventories/example/hosts.yml
echo unit >deploy/systemd/manuspectrum-backup.service.in
echo unit >deploy/systemd/manuspectrum-backup.timer.in
echo rot >deploy/logrotate/manuspectrum-nginx.in
echo front >deploy/sbin/manuspectrum-update
echo prog >deploy/scripts/release-verify.sh
echo prog >deploy/scripts/lib-metrics.sh
echo other >deploy/scripts/backup.sh
echo ci >deploy/scripts/release-ruleset-check.sh
echo t >deploy/scripts/tests/test_x.sh
echo mk >deploy/Makefile
git add -A && git commit -q -m base

run_wt() { "$SCRIPT" --worktree "${1:-$REPO}"; }
run_ref() { "$SCRIPT" --ref "${1:-HEAD}" --repo "$REPO"; }
BASE_WT="$(run_wt 2>&1)"; BASE_REF="$(run_ref 2>&1)"

check "worktree mode lists the managed files" \
  bash -c '[ "$(grep -c . <<<"$1")" = 9 ] && grep -q "  deploy/ansible/site.yml$" <<<"$1" && grep -q "  deploy/sbin/manuspectrum-update$" <<<"$1"' _ "$BASE_WT"
check "files outside the list are absent" \
  bash -c '! grep -E "backup.sh|Makefile|ansible/tests|README|inventories|ruleset|scripts/tests" <<<"$1"' _ "$BASE_WT"
check "sorted sha256sum format" \
  bash -c 'grep -qE "^[0-9a-f]{64}  deploy/" <<<"$1" && [ "$1" = "$(LC_ALL=C sort -k2 <<<"$1")" ]' _ "$BASE_WT"
check "ref mode equals worktree mode on a clean repo" test "$BASE_WT" = "$BASE_REF"

echo changed >deploy/systemd/manuspectrum-backup.timer.in
check "an uncommitted change shows in worktree mode only" \
  bash -c '[ "$("$1" --worktree "$2")" != "$3" ] && [ "$("$1" --ref HEAD --repo "$2")" = "$3" ]' _ "$SCRIPT" "$REPO" "$BASE_WT"
git commit -q -am "unit"
check "a modified unit differs in ref mode" test "$(run_ref)" != "$BASE_REF"
AFTER_UNIT="$(run_ref)"

echo new >deploy/ansible/roles/app/tasks/extra.yml
git add -A && git commit -q -m role
check "a new role file differs" test "$(run_ref)" != "$AFTER_UNIT"
AFTER_ROLE="$(run_ref)"

git rm -q deploy/scripts/lib-metrics.sh && git commit -q -m del
check "a deleted file differs" test "$(run_ref)" != "$AFTER_ROLE"
AFTER_DEL="$(run_ref)"
check "a file deleted from the worktree only is absent" \
  bash -c 'rm "$2/deploy/ansible/site.yml"; ! "$1" --worktree "$2" | grep -q ansible/site.yml' _ "$SCRIPT" "$REPO"
git checkout -q -- deploy/ansible/site.yml

echo changed >deploy/ansible/tests/test_x.py
echo changed >deploy/ansible/README.md
echo changed >deploy/scripts/backup.sh
git commit -q -am unmanaged
check "changes outside the list do not differ (ref)" test "$(run_ref)" = "$AFTER_DEL"
check "changes outside the list do not differ (worktree)" test "$(run_wt)" = "$AFTER_DEL"

git tag v1.0.0
check "a tag is accepted as REF" test "$(run_ref v1.0.0)" = "$AFTER_DEL"
git branch side
check "a branch name is accepted as REF" test "$(run_ref side)" = "$AFTER_DEL"

check "the repository may be the current directory" \
  bash -c 'cd "$2" && [ "$("$1" --ref HEAD)" = "$3" ]' _ "$SCRIPT" "$REPO" "$AFTER_DEL"

refused() { # refused DESC ARGS...
  local desc="$1"; shift
  local out rc
  out="$("$SCRIPT" "$@" 2>&1)"; rc=$?
  if { [ "$rc" -eq 1 ] || [ "$rc" -eq 2 ]; } && [ -z "$(grep -E '^[0-9a-f]{64}  ' <<<"$out")" ]; then ok "refused: $desc"; else not_ok "refused: $desc" "rc=$rc $out"; fi
}
refused "no argument"
refused "unknown option" --bogus
refused "both modes" --worktree "$REPO" --ref HEAD
refused "--worktree without a value" --worktree
refused "--worktree on a missing directory" --worktree "$TMP/nope"
refused "--worktree on a directory that is not a repository" --worktree "$TMP"
refused "--worktree with .." --worktree "$REPO/../repo"
refused "--ref unknown" --ref nosuchref --repo "$REPO"
refused "--ref starting with a dash" --ref --upload-pack=x --repo "$REPO"
refused "--ref with a space" --ref "HEAD HEAD" --repo "$REPO"
refused "--ref empty" --ref "" --repo "$REPO"
refused "--repo with --worktree" --worktree "$REPO" --repo "$REPO"
refused "--repo with .." --ref HEAD --repo "$REPO/../repo"

exit "$FAILED"
