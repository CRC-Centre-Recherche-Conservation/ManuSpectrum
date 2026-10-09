#!/usr/bin/env bash
# deploy/compose/observability/check.sh
# Checks the Prometheus and blackbox exporter configuration with the pinned
# images (read from compose.yaml): `promtool check config` on a temporary tree
# that holds the files at their container paths plus a placeholder edge target,
# `promtool test rules` on the unit tests of the alert rules,
# `blackbox_exporter --config.check`, and, with the pinned Alertmanager image,
# `amtool check-config` on alertmanager.yml.in rendered by render.sh (with and
# without relay authentication), `amtool config routes test` on the severity
# routes and `amtool template render` on the e-mail templates. The time
# windows are checked by tests/test_alertmanager.py (amtool does not evaluate
# them). Mounts are read-only, nothing is written to the repository. PROMETHEUS_CONFIG / BLACKBOX_CONFIG / RULES_DIR /
# RULE_TESTS_DIR override the files to check.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_YAML="$HERE/../compose.yaml"
PROMETHEUS_CONFIG="${PROMETHEUS_CONFIG:-$HERE/prometheus/prometheus.yml}"
BLACKBOX_CONFIG="${BLACKBOX_CONFIG:-$HERE/blackbox/blackbox.yml}"
RULES_DIR="${RULES_DIR:-$HERE/prometheus/rules}"
RULE_TESTS_DIR="${RULE_TESTS_DIR:-$HERE/prometheus/rule-tests}"

pin() { # pin REGEX: the image reference of compose.yaml matching REGEX
  local ref
  ref="$(sed -n "s/^ *image: \\($1[^ ]*\\)\$/\\1/p" "$COMPOSE_YAML" | head -n 1)"
  [ -n "$ref" ] || { echo "no $1 image in compose.yaml" >&2; exit 1; }
  docker image inspect "$ref" >/dev/null 2>&1 || docker pull -q "$ref" >/dev/null \
    || { echo "cannot pull $ref" >&2; exit 1; }
  printf '%s' "$ref"
}

PROMETHEUS_IMAGE="$(pin 'prom\/prometheus:')"
BLACKBOX_IMAGE="$(pin 'quay\.io\/prometheus\/blackbox-exporter:')"
ALERTMANAGER_IMAGE="$(pin 'prom\/alertmanager:')"
ALERTMANAGER_DIR="${ALERTMANAGER_DIR:-$HERE/alertmanager}"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
chmod 755 "$TMP"
mkdir -p "$TMP/rules" "$TMP/rule-tests"
cp "$PROMETHEUS_CONFIG" "$TMP/prometheus.yml"
cp "$BLACKBOX_CONFIG" "$TMP/blackbox.yml"
cp "$RULES_DIR"/*.yml "$TMP/rules/"
cp "$RULE_TESTS_DIR"/*.yml "$TMP/rule-tests/"
printf '[{"targets": ["https://manuspectrum.test/healthz"]}]\n' >"$TMP/edge_targets.json"
chmod -R a+rX "$TMP"

docker run --rm --network none --user 65534:65534 --read-only \
  -v "$TMP/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$TMP/rules:/etc/prometheus/rules:ro" \
  -v "$TMP/edge_targets.json:/tmp/edge_targets.json:ro" \
  --entrypoint /bin/promtool "$PROMETHEUS_IMAGE" \
  check config /etc/prometheus/prometheus.yml

# The service as compose runs it: read-only root, tmpfs /tmp, entrypoint.sh
# writing the edge target from PUBLIC_HOST. The target must be discovered.
cp "$HERE/prometheus/entrypoint.sh" "$TMP/entrypoint.sh"
chmod a+r "$TMP/entrypoint.sh"
PROM_CONTAINER="$(docker run -d --rm --network none --user 65534:65534 --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777 \
  -e PUBLIC_HOST=manuspectrum.test \
  -v "$TMP/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$TMP/rules:/etc/prometheus/rules:ro" \
  -v "$TMP/entrypoint.sh:/etc/prometheus/entrypoint.sh:ro" \
  --entrypoint /bin/sh "$PROMETHEUS_IMAGE" /etc/prometheus/entrypoint.sh \
  --config.file=/etc/prometheus/prometheus.yml --storage.tsdb.path=/tmp/tsdb)"
trap 'docker rm -f "$PROM_CONTAINER" >/dev/null 2>&1 || true; rm -rf "$TMP"' EXIT
found=""
for _ in $(seq 1 30); do
  found="$(docker exec "$PROM_CONTAINER" wget -q -O - http://127.0.0.1:9090/api/v1/targets 2>/dev/null || true)"
  case "$found" in *'"https://manuspectrum.test/healthz"'*'"rehearsal":"true"'*) break ;; esac
  found=""
  sleep 1
done
[ -n "$found" ] || {
  echo "prometheus (read-only, entrypoint.sh) did not discover the edge target" >&2
  docker logs "$PROM_CONTAINER" >&2 || true
  exit 1
}
docker rm -f "$PROM_CONTAINER" >/dev/null
trap 'rm -rf "$TMP"' EXIT
echo "SUCCESS: prometheus starts read-only and discovers the edge target"

# The test files name their rules as ../rules/<file>.yml.
unit_tests=()
for file in "$TMP"/rule-tests/*.yml; do unit_tests+=("/work/rule-tests/$(basename "$file")"); done
docker run --rm --network none --user 65534:65534 --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -v "$TMP/rules:/work/rules:ro" \
  -v "$TMP/rule-tests:/work/rule-tests:ro" \
  --entrypoint /bin/promtool "$PROMETHEUS_IMAGE" \
  test rules "${unit_tests[@]}"
echo "SUCCESS: prometheus rules and unit tests"

docker run --rm --network none --user 65534:65534 --read-only \
  -v "$TMP/blackbox.yml:/etc/blackbox_exporter/config.yml:ro" \
  "$BLACKBOX_IMAGE" --config.check --config.file=/etc/blackbox_exporter/config.yml
echo "SUCCESS: prometheus and blackbox configuration"

# Alertmanager: render with sample values, then the pinned amtool.
amtool() { # amtool ARGS...: the pinned amtool, config tree at /am, no network
  docker run --rm --network none --user 65534:65534 --read-only \
    -v "$TMP/am:/am:ro" \
    -v "$TMP/am/templates:/etc/alertmanager/templates:ro" \
    --entrypoint /bin/amtool "$ALERTMANAGER_IMAGE" "$@"
}
render_am() { # render_am OUTFILE [VAR=value...]
  local out="$1"
  shift
  env EMAIL_HOST=smtp.manuspectrum.test EMAIL_PORT=25 EMAIL_USE_TLS=false \
    EMAIL_HOST_USER= EMAIL_HOST_PASSWORD_FILE=/am/email_password \
    ALERT_EMAILS='alerts@manuspectrum.test, ops@manuspectrum.test' \
    ALERT_EMAIL_FROM=manuspectrum@manuspectrum.test \
    "$@" ALERTMANAGER_DIR="$ALERTMANAGER_DIR" ALERTMANAGER_OUT="$out" \
    ALERTMANAGER_RENDER_ONLY=1 sh "$ALERTMANAGER_DIR/render.sh"
}
mkdir -p "$TMP/am/templates"
cp "$ALERTMANAGER_DIR"/templates/*.tmpl "$TMP/am/templates/"
printf 'not-a-real-password' >"$TMP/am/email_password"
render_am "$TMP/am/alertmanager.yml"
render_am "$TMP/am/alertmanager-auth.yml" EMAIL_HOST_USER=relay-user EMAIL_USE_TLS=true
chmod -R a+rX "$TMP/am"
amtool check-config /am/alertmanager.yml /am/alertmanager-auth.yml

route_to() { # route_to RECEIVER LABEL=value...: the labels resolve to RECEIVER only
  local want="$1" got
  shift
  got="$(amtool config routes test --config.file=/am/alertmanager.yml "$@")"
  [ "$got" = "$want" ] || { echo "routes: $* -> '$got', expected '$want'" >&2; exit 1; }
}
route_to email-now alertname=SiteDown severity=critical service=site
route_to email-now alertname=BackupFailed severity=critical service=backup
route_to email-working-hours alertname=DiskUsageHigh severity=warning service=storage
route_to heartbeat alertname=Watchdog severity=none service=monitoring
route_to blackhole alertname=RecentlyRebooted severity=none service=host
route_to blackhole alertname=Anything severity=info service=host
route_to blackhole alertname=Unlabelled

cat >"$TMP/am/data.json" <<'JSON'
{
  "receiver": "email-now", "status": "firing",
  "alerts": [{
    "status": "firing",
    "labels": {"alertname": "SiteDown", "severity": "critical", "service": "site"},
    "annotations": {"summary": "The site is down", "description": "No answer for 2 minutes.",
                    "runbook_url": "https://example.test/runbooks/site.md#sitedown"},
    "startsAt": "2026-10-09T10:00:00Z"
  }],
  "groupLabels": {"alertname": "SiteDown", "service": "site"},
  "commonLabels": {"alertname": "SiteDown", "severity": "critical", "service": "site"},
  "commonAnnotations": {}, "externalURL": "http://alertmanager:9093"
}
JSON
chmod a+r "$TMP/am/data.json"
sed -e 's/"firing"/"resolved"/g' "$TMP/am/data.json" >"$TMP/am/resolved.json"
cat >"$TMP/am/group.json" <<'JSON'
{
  "receiver": "email-working-hours", "status": "firing",
  "alerts": [
    {"status": "firing", "labels": {"alertname": "DiskUsageHigh", "severity": "warning", "service": "storage"},
     "annotations": {"summary": "Disk above 80 %", "description": "d", "runbook_url": "https://example.test/r"},
     "startsAt": "2026-10-09T10:00:00Z"},
    {"status": "firing", "labels": {"alertname": "DiskFillingUp", "severity": "warning", "service": "storage"},
     "annotations": {"summary": "Disk fills in 24 h", "description": "d", "runbook_url": "https://example.test/r"},
     "startsAt": "2026-10-09T10:00:00Z"}
  ],
  "groupLabels": {"service": "storage"},
  "commonLabels": {"severity": "warning", "service": "storage"},
  "commonAnnotations": {}, "externalURL": "http://alertmanager:9093"
}
JSON
chmod a+r "$TMP/am"/*.json

render_tmpl() { # render_tmpl DATA TEMPLATE-NAME
  amtool template render --template.glob='/etc/alertmanager/templates/*.tmpl' \
    --template.data="/am/$1" --template.text="{{ template \"$2\" . }}"
}
expect() { # expect WHAT GOT WANT
  [ "$2" = "$3" ] || { echo "template $1 is '$2', expected '$3'" >&2; exit 1; }
}
expect "firing subject" "$(render_tmpl data.json ms.subject)" "[ManuSpectrum][Alert] CRITICAL SiteDown - The site is down"
expect "resolved subject" "$(render_tmpl resolved.json ms.subject)" "[ManuSpectrum][Alert] RESOLVED SiteDown - The site is down"
expect "grouped subject" "$(render_tmpl group.json ms.subject)" "[ManuSpectrum][Alert] WARNING 2 alerts: DiskUsageHigh, DiskFillingUp"
for data in data.json resolved.json group.json; do
  for name in ms.subject ms.body ms.heartbeat; do
    rendered="$(render_tmpl "$data" "$name")"
    case "$rendered" in *"<no value>"* | "") echo "template $name renders '<no value>' or nothing" >&2; exit 1 ;; esac
  done
done
case "$(render_tmpl data.json ms.body)" in
  *"https://example.test/runbooks/site.md#sitedown"*) ;;
  *) echo "body lacks the runbook link" >&2; exit 1 ;;
esac

# The category headers and the heartbeat subject are in the rendered config.
for want in "X-ManuSpectrum-Category: alert" "X-ManuSpectrum-Category: heartbeat" \
  "Subject: '[ManuSpectrum][Heartbeat] Alerting chain OK'"; do
  grep -qF -- "$want" "$TMP/am/alertmanager.yml" || { echo "rendered config lacks: $want" >&2; exit 1; }
done
echo "SUCCESS: alertmanager configuration, routes and templates"
