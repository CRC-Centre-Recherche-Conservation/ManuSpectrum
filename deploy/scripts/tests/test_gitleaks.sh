#!/usr/bin/env bash
# deploy/scripts/tests/test_gitleaks.sh
# Tests of gitleaks.sh and of the pre-commit hook over the real pinned image.
# Every repository is temporary and every fake secret is generated at run time:
# no key-shaped literal is committed. Prints `ok N` / `not ok N`; exits non-zero
# on failure. REQUIRE_PRE_COMMIT=1 turns a missing pre-commit into a failure.
# $? after a negated or compound test is the point of every assertion below.
# The `A && ok || not_ok` lines are safe: ok never fails.
# shellcheck disable=SC2319,SC2015,SC2016,SC2001
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
GL="$ROOT/deploy/scripts/gitleaks.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

N=0
FAILED=0
ok() { N=$((N + 1)); echo "ok $N - $1"; }
not_ok() { N=$((N + 1)); FAILED=1; echo "not ok $N - $1"; [ -z "${2:-}" ] || sed 's/^/#   /' <<<"$2"; }
check() { # check NAME RC-EXPECTATION(zero|nonzero) RC OUTPUT [FORBIDDEN-VALUE]
  local name="$1" want="$2" rc="$3" out="$4" secret="${5:-}"
  if { [ "$want" = zero ] && [ "$rc" -ne 0 ]; } || { [ "$want" = nonzero ] && [ "$rc" -eq 0 ]; }; then
    not_ok "$name (exit $rc)" "$out"
  elif [ -n "$secret" ] && grep -qF -- "$secret" <<<"$out"; then
    not_ok "$name: the secret value reached the output"
  else
    ok "$name"
  fi
}

rand() { # rand CHARSET LENGTH
  python3 -c 'import secrets, sys; print("".join(secrets.choice(sys.argv[1]) for _ in range(int(sys.argv[2]))))' "$1" "$2"
}
ALNUM="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
fake_token() { echo "ghp_$(rand "$ALNUM" 36)"; }
fake_age_key() { echo "AGE-SECRET-KEY-1$(rand QPZRY9X8GF2TVDW0S3JN54KHCE6MUA7L 58)"; }
fake_sops_line() { echo "pg_password: ENC[AES256_GCM,data:$(rand "$ALNUM" 24),iv:$(rand "$ALNUM" 44)=,tag:$(rand "$ALNUM" 22)==,type:str]"; }

GIT=(git -c user.name=t -c user.email=t@example.org -c commit.gpgsign=false)
new_repo() { # new_repo DIR: a repository holding the project's gitleaks config
  mkdir -p "$1"
  git init -q "$1"
  cp "$ROOT/.gitleaks.toml" "$1/"
  (cd "$1" && git add .gitleaks.toml && "${GIT[@]}" commit -q -m init)
}
run_gl() { # run_gl DIR ARGS...: sets RC and OUT
  local dir="$1"
  shift
  OUT="$(cd "$dir" && bash "$GL" "$@" 2>&1)"
  RC=$?
}

if ! command -v docker >/dev/null 2>&1; then
  echo "1..0 # SKIP docker missing"
  exit 0
fi

# --- staged
TOKEN="$(fake_token)"
new_repo "$TMP/r1"
echo "token = \"$TOKEN\"" >"$TMP/r1/conf.txt"
(cd "$TMP/r1" && git add conf.txt)
run_gl "$TMP/r1" staged
check "staged-blocks: a staged token is refused" nonzero "$RC" "$OUT" "$TOKEN"
grep -q 'github-pat' <<<"$OUT" && ok "staged-blocks: the rule id is reported" || not_ok "staged-blocks: the rule id is reported" "$OUT"

new_repo "$TMP/r2"
echo "an ordinary line" >"$TMP/r2/readme.txt"
(cd "$TMP/r2" && git add readme.txt)
run_gl "$TMP/r2" staged
check "staged-clean: an ordinary change passes" zero "$RC" "$OUT"

(cd "$TMP/r1" && "${GIT[@]}" commit -q --no-verify -m "with token" && git rm -q --cached conf.txt && rm conf.txt && "${GIT[@]}" commit -q -m "drop")
(cd "$TMP/r1" && git worktree add -q "$TMP/wt" -b side)
echo "token = \"$TOKEN\"" >"$TMP/wt/again.txt"
(cd "$TMP/wt" && git add again.txt)
run_gl "$TMP/wt" staged
check "staged-worktree: a token staged in a linked worktree is refused" nonzero "$RC" "$OUT" "$TOKEN"

AGE_KEY="$(fake_age_key)"
new_repo "$TMP/r3"
echo "$AGE_KEY" >"$TMP/r3/key.txt"
(cd "$TMP/r3" && git add key.txt)
run_gl "$TMP/r3" staged
check "staged-age-key: an age secret key is refused" nonzero "$RC" "$OUT" "$AGE_KEY"

SOPS_LINE="$(fake_sops_line)"
new_repo "$TMP/r4"
echo "$SOPS_LINE" >"$TMP/r4/escrow.yaml"
(cd "$TMP/r4" && git add -f escrow.yaml)
run_gl "$TMP/r4" staged
check "staged-sops: sops ciphertext is refused" nonzero "$RC" "$OUT" "$SOPS_LINE"
grep -q 'sops-encrypted-value' <<<"$OUT" && ok "staged-sops: the rule id is reported" || not_ok "staged-sops: the rule id is reported" "$OUT"

new_repo "$TMP/r5"
echo 'PGPASSWORD="$(cat /run/secrets/pg_password)" psql' >"$TMP/r5/run.sh"
(cd "$TMP/r5" && git add run.sh)
run_gl "$TMP/r5" staged
check "allowlist: the /run/secrets idiom passes" zero "$RC" "$OUT"

# --- range and tree
new_repo "$TMP/r6"
BASE="$(cd "$TMP/r6" && git rev-parse HEAD)"
echo "x = \"$TOKEN\"" >"$TMP/r6/a.txt"
(cd "$TMP/r6" && git add a.txt && "${GIT[@]}" commit -q --no-verify -m add)
(cd "$TMP/r6" && git rm -q a.txt && "${GIT[@]}" commit -q -m remove)
HEAD_SHA="$(cd "$TMP/r6" && git rev-parse HEAD)"
run_gl "$TMP/r6" range "$BASE" "$HEAD_SHA"
check "range: a token added then removed inside the range is found" nonzero "$RC" "$OUT" "$TOKEN"
run_gl "$TMP/r6" tree
check "range: tree on the final state is clean" zero "$RC" "$OUT"
run_gl "$TMP/r6" history
check "history: the whole history is scanned" nonzero "$RC" "$OUT" "$TOKEN"

new_repo "$TMP/r7"
mkdir -p "$TMP/r7/docs/deep"
echo "x = \"$TOKEN\"" >"$TMP/r7/docs/deep/outside-deploy.txt"
run_gl "$TMP/r7" tree
check "tree-scope: an untracked token outside deploy/ is found" nonzero "$RC" "$OUT" "$TOKEN"
rm "$TMP/r7/docs/deep/outside-deploy.txt"
echo "ignored.txt" >"$TMP/r7/.gitignore"
echo "x = \"$TOKEN\"" >"$TMP/r7/ignored.txt"
run_gl "$TMP/r7" tree
check "tree-scope: a gitignored file is skipped" zero "$RC" "$OUT"

# --- pre-commit
if command -v pre-commit >/dev/null 2>&1; then
  new_repo "$TMP/r8"
  mkdir -p "$TMP/r8/deploy/scripts"
  cp -p "$GL" "$TMP/r8/deploy/scripts/"
  cp "$ROOT/.pre-commit-config.yaml" "$TMP/r8/"
  (cd "$TMP/r8" && git add -A && "${GIT[@]}" commit -q -m hook)
  echo "token = \"$TOKEN\"" >"$TMP/r8/conf.txt"
  (cd "$TMP/r8" && git add conf.txt)
  OUT="$(cd "$TMP/r8" && pre-commit run gitleaks 2>&1)"
  RC=$?
  check "pre-commit: the hook refuses a staged token" nonzero "$RC" "$OUT" "$TOKEN"
  grep -q 'github-pat' <<<"$OUT" && ok "pre-commit: the finding comes from gitleaks" || not_ok "pre-commit: the finding comes from gitleaks" "$OUT"
  (cd "$TMP/r8" && git reset -q conf.txt && rm conf.txt && echo clean >ok.txt && git add ok.txt)
  OUT="$(cd "$TMP/r8" && pre-commit run gitleaks 2>&1)"
  RC=$?
  check "pre-commit: the hook passes a clean change" zero "$RC" "$OUT"
  # git hands the hook its index through GIT_INDEX_FILE for `commit -a` and `commit <path>`.
  new_repo "$TMP/r10"
  mkdir -p "$TMP/r10/deploy/scripts"
  cp -p "$GL" "$TMP/r10/deploy/scripts/"
  cat >"$TMP/r10/.pre-commit-config.yaml" <<'CFG'
repos:
  - repo: local
    hooks:
      - id: gitleaks
        name: gitleaks
        entry: deploy/scripts/gitleaks.sh staged
        language: system
        pass_filenames: false
CFG
  echo base >"$TMP/r10/tracked.txt"
  (cd "$TMP/r10" && git add -A && "${GIT[@]}" commit -q -m base --no-verify && pre-commit install >/dev/null 2>&1)
  BEFORE="$(cd "$TMP/r10" && git rev-parse HEAD)"
  echo "token = \"$TOKEN\"" >"$TMP/r10/tracked.txt"
  OUT="$(cd "$TMP/r10" && "${GIT[@]}" commit -q -a -m leak 2>&1)"
  RC=$?
  check "pre-commit: commit -a with a token in a modified file is refused" nonzero "$RC" "$OUT" "$TOKEN"
  [ "$(cd "$TMP/r10" && git rev-parse HEAD)" = "$BEFORE" ] && ok "pre-commit: commit -a made no commit" || not_ok "pre-commit: commit -a made no commit"
  (cd "$TMP/r10" && git reset -q --hard "$BEFORE" && echo "token = \"$TOKEN\"" >tracked.txt)
  OUT="$(cd "$TMP/r10" && "${GIT[@]}" commit -q -m leak tracked.txt 2>&1)"
  RC=$?
  check "pre-commit: commit <path> with a token in a modified file is refused" nonzero "$RC" "$OUT" "$TOKEN"
  [ "$(cd "$TMP/r10" && git rev-parse HEAD)" = "$BEFORE" ] && ok "pre-commit: commit <path> made no commit" || not_ok "pre-commit: commit <path> made no commit"
elif [ "${REQUIRE_PRE_COMMIT:-}" = 1 ]; then
  not_ok "pre-commit: pre-commit is required and missing"
else
  echo "ok - pre-commit: skipped, pre-commit missing"
fi

# --- no docker
mkdir "$TMP/empty-path"
OUT="$(cd "$TMP/r2" && env PATH="$TMP/empty-path" /bin/bash "$GL" tree 2>&1)"
RC=$?
check "no-docker: refuses to run" nonzero "$RC" "$OUT"
grep -q 'docker is required' <<<"$OUT" && ok "no-docker: the message says what is missing" || not_ok "no-docker: the message says what is missing" "$OUT"

# --- usage and ignore patterns
OUT="$(bash "$GL" bogus 2>&1)"
RC=$?
[ "$RC" -eq 2 ] && ok "usage: an unknown mode exits 2" || not_ok "usage: an unknown mode exits 2 (exit $RC)" "$OUT"

OUT="$(cd "$TMP/r2" && GIT_INDEX_FILE="$TMP/outside-index" bash "$GL" staged 2>&1)"
RC=$?
[ "$RC" -eq 2 ] && ok "staged: an index outside the repository is refused" || not_ok "staged: an index outside the repository is refused (exit $RC)" "$OUT"

new_repo "$TMP/r9"
rm -f "$TMP/r9/.gitignore"
cp "$ROOT/.gitignore" "$TMP/r9/.gitignore"
all_ignored=1
for f in a.sops.yaml b.sops.json prod.enc.env c.age age-recipients.txt sops/age/keys.txt home/.config/sops/age/keys.txt; do
  mkdir -p "$TMP/r9/$(dirname "$f")"
  : >"$TMP/r9/$f"
  (cd "$TMP/r9" && git check-ignore -q "$f") || { all_ignored=0; echo "# not ignored: $f"; }
done
[ "$all_ignored" = 1 ] && ok "gitignore: escrow and age key files are ignored" || not_ok "gitignore: escrow and age key files are ignored"

echo "1..$N"
exit "$FAILED"
