#!/usr/bin/env bash
# Turns a `trivy image --format json` report into a table in the job summary
# and one warning annotation per finding, vulnerabilities and secrets alike
# (a secret is reported by rule, file and line, never by its content). Exits 0,
# or 1 with --fail when the report holds any finding (the weekly scan).
# Usage: trivy-report.sh REPORT.json [--fail]
set -euo pipefail

REPORT="${1:?usage: trivy-report.sh REPORT.json [--fail]}"
FAIL="${2:-}"
SUMMARY="${GITHUB_STEP_SUMMARY:-/dev/stdout}"

rows="$(jq -r '
  [.Results[]? | .Target as $t | .Vulnerabilities[]?
    | [.Severity, .VulnerabilityID, .PkgName, .InstalledVersion,
       (.FixedVersion // ""), (.PkgPath // $t)]]
  | unique | sort_by(.[0] != "CRITICAL", .[2], .[1])[] | @tsv' "$REPORT")"

secrets="$(jq -r '
  [.Results[]? | .Target as $t | .Secrets[]?
    | [.Severity, .RuleID, .Title, ($t + ":" + ((.StartLine // 0) | tostring))]]
  | unique | sort_by(.[0] != "CRITICAL", .[1], .[3])[] | @tsv' "$REPORT")"

if [ -z "$rows" ] && [ -z "$secrets" ]; then
  echo "### Trivy: no HIGH or CRITICAL finding with a fix, no secret" >>"$SUMMARY"
  exit 0
fi

count=0
if [ -n "$rows" ]; then
  count="$(wc -l <<<"$rows")"
  {
    echo "### Trivy: $count HIGH or CRITICAL findings with a fix"
    echo
    echo "Fix it (base image digest, a floor in pyproject.toml, a bump in"
    echo "package.json) or accept it in .trivyignore with its reason and an expiry."
    echo
    echo "| Severity | Vulnerability | Package | Installed | Fixed | Path |"
    echo "|---|---|---|---|---|---|"
    while IFS=$'\t' read -r sev id pkg installed fixed path; do
      echo "| $sev | $id | $pkg | $installed | $fixed | \`$path\` |"
    done <<<"$rows"
  } >>"$SUMMARY"

  while IFS=$'\t' read -r sev id pkg installed fixed _; do
    echo "::warning title=Trivy $sev::$pkg $installed: $id (fixed in $fixed)"
  done <<<"$rows"
fi

if [ -n "$secrets" ]; then
  secret_count="$(wc -l <<<"$secrets")"
  count=$((count + secret_count))
  {
    echo "### Trivy: $secret_count secrets in the image"
    echo
    echo "Remove the file from the image, or accept a false positive by its rule id in .trivyignore."
    echo
    echo "| Severity | Rule | Title | Location |"
    echo "|---|---|---|---|"
    while IFS=$'\t' read -r sev rule title where; do
      echo "| $sev | $rule | $title | \`$where\` |"
    done <<<"$secrets"
  } >>"$SUMMARY"

  while IFS=$'\t' read -r sev rule title where; do
    echo "::warning title=Trivy secret $sev::$rule ($title) in $where"
  done <<<"$secrets"
fi

[ "$FAIL" != "--fail" ] || { echo "::error::$count Trivy findings"; exit 1; }
