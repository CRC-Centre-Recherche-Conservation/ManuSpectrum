#!/usr/bin/env bash
# Fails unless an active repository ruleset protects the release tags: it
# targets tags, includes refs/tags/v* (or every tag) without excluding them,
# and carries the rules `creation`, `update` and `deletion`, so a pushed tag
# can be neither moved nor deleted and only the ruleset's bypass actors can
# create one. The caller (the workflow token) must not be a bypass actor:
# `current_user_can_bypass` of the repository-level ruleset must be "never"
# (fail closed when absent). Who is in the bypass list is checked by hand
# (deploy/RELEASES.md). Reads the rulesets through the GitHub API (`gh`,
# GH_TOKEN), paginated.
# Usage: release-ruleset-check.sh OWNER/REPO
set -uo pipefail

REPO="${1:?usage: release-ruleset-check.sh OWNER/REPO}"

exec python3 -I - "$REPO" <<'PY'
import json
import subprocess
import sys

REQUIRED = {"creation", "update", "deletion"}
repo = sys.argv[1]


def api(path, paginate=False):
    command = ["gh", "api"] + (["--paginate"] if paginate else []) + [path]
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        print(
            f"release-ruleset-check: cannot read {path}: {done.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(1)
    # --paginate prints one JSON array per page, back to back.
    decoder = json.JSONDecoder()
    text, position, pages = done.stdout, 0, []
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        page, position = decoder.raw_decode(text, position)
        pages.append(page)
    if paginate:
        return [item for page in pages for item in page]
    return pages[0] if pages else {}


def protects(ruleset):
    condition = (ruleset.get("conditions") or {}).get("ref_name") or {}
    include = condition.get("include") or []
    exclude = condition.get("exclude") or []
    if not ({"refs/tags/v*", "~ALL"} & set(include)):
        return False
    if {"refs/tags/v*", "~ALL"} & set(exclude):
        return False
    if ruleset.get("current_user_can_bypass") != "never":
        return False
    rules = {rule.get("type") for rule in ruleset.get("rules") or []}
    return REQUIRED <= rules


listed = api(f"repos/{repo}/rulesets?per_page=100", paginate=True)
candidates = [
    r["id"]
    for r in listed
    if r.get("target") == "tag" and r.get("enforcement") == "active"
]
for ruleset_id in candidates:
    if protects(api(f"repos/{repo}/rulesets/{ruleset_id}")):
        print(f"release-ruleset-check: ruleset {ruleset_id} protects the v* tags")
        sys.exit(0)
print(
    "release-ruleset-check: no active tag ruleset includes refs/tags/v* with the "
    "rules creation, update and deletion and current_user_can_bypass \"never\"; set it up before pushing a release tag "
    "(deploy/RELEASES.md, Prerequisites)",
    file=sys.stderr,
)
sys.exit(1)
PY
