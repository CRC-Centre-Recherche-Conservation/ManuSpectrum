#!/usr/bin/env bash
# deploy/certs/tests/test_acme_pebble.sh
# The ACME flow of CERT_MODE=acme against Pebble, Let's Encrypt's test server,
# never against a real CA: the certbot image and flags of the `certbot`
# service, a throwaway nginx (the stack's pinned image, its own minimal
# configuration) serving the webroot and the certificate, and the real deploy
# hook. Pebble validates HTTP-01 for real, nginx answers on port 5002.
# Needs docker and network access to pull the images; about two minutes.
# Prints `ok N` / `not ok N`; exits non-zero on failure.
# shellcheck disable=SC2317,SC2319 # the trap function; assert reads the status of the check above
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY="$HERE/../.."
COMPOSE_FILE="$DEPLOY/compose/compose.yaml"
HOOK="$DEPLOY/compose/certbot/deploy-hook.sh"
NAME=manuspectrum.test
RUN_ID="msacme-$$"

image_of() { # image_of SERVICE-COMMENT-FREE-PATTERN
  grep -oE "image: $1[^ ]*@sha256:[0-9a-f]{64}" "$COMPOSE_FILE" | head -n 1 | sed 's/^image: //'
}
CERTBOT_IMAGE="$(image_of certbot/certbot)"
NGINX_IMAGE="$(image_of nginxinc/nginx-unprivileged)"
PEBBLE_IMAGE="ghcr.io/letsencrypt/pebble@sha256:68cf1ec8a8db96f64244d5f559c448bc8e54f2934e0dd53a414eabffda7a6f22" # 2.10.0
DEBIAN_IMAGE="debian:12-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

TMP="$(mktemp -d)"
CERTS="$TMP/certs"
mkdir -p "$CERTS/live" "$CERTS/letsencrypt" "$CERTS/acme-webroot"
cleanup() {
  docker rm -f "$RUN_ID-nginx" "$RUN_ID-pebble" >/dev/null 2>&1
  docker network rm "$RUN_ID" >/dev/null 2>&1
  rm -rf "$TMP"
}
trap cleanup EXIT

[ -n "$CERTBOT_IMAGE" ] && [ -n "$NGINX_IMAGE" ]
assert "compose.yaml pins the certbot and nginx images" $?

issuer_served() { # issuer_served -> issuer of what nginx serves on 8443
  ip="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$RUN_ID-nginx")"
  openssl s_client -connect "$ip:8443" -servername "$NAME" </dev/null 2>/dev/null |
    openssl x509 -noout -issuer 2>/dev/null
}
certbot() { # certbot ARGS... : the `certbot` service, pointed at Pebble
  docker run --rm --network "$RUN_ID" --user "$(id -u):$(id -g)" --read-only \
    --cap-drop ALL --security-opt no-new-privileges:true --tmpfs /tmp:rw,size=16m,mode=1777 \
    -e HOME=/tmp -e REQUESTS_CA_BUNDLE=/pebble-ca.pem \
    -v "$CERTS/live:/certs/live" -v "$CERTS/letsencrypt:/certs/letsencrypt" \
    -v "$CERTS/acme-webroot:/certs/acme-webroot" -v "$HOOK:/hooks/deploy-hook.sh:ro" \
    -v "$TMP/pebble-ca.pem:/pebble-ca.pem:ro" \
    --entrypoint certbot "$CERTBOT_IMAGE" \
    --config-dir=/certs/letsencrypt --logs-dir=/certs/letsencrypt/logs --work-dir=/tmp/certbot "$@"
}

docker network create "$RUN_ID" >/dev/null
pebble_container="$(docker create --name "$RUN_ID-pebble" --network "$RUN_ID" \
  --network-alias pebble -e PEBBLE_VA_NOSLEEP=1 "$PEBBLE_IMAGE")"
docker cp "$pebble_container:/test/certs/pebble.minica.pem" "$TMP/pebble-ca.pem"
docker start "$RUN_ID-pebble" >/dev/null
assert "Pebble started" $?

# Placeholder certificate, as `make cert-init` writes it.
"$HERE/../make-local-ca.sh" --self-signed "$CERTS/live" "$NAME" >/dev/null
placeholder_sum="$(cksum <"$CERTS/live/fullchain.pem")"

cat >"$TMP/nginx.conf" <<'CONF'
pid /tmp/nginx.pid;
events {}
http {
  access_log off;
  error_log /dev/stderr warn;
  client_body_temp_path /tmp/b;
  proxy_temp_path /tmp/p;
  fastcgi_temp_path /tmp/f;
  uwsgi_temp_path /tmp/u;
  scgi_temp_path /tmp/s;
  server {
    listen 5002;
    location /.well-known/acme-challenge/ { root /var/www/acme; }
    location / { return 404; }
  }
  server {
    listen 8443 ssl;
    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    location / { return 200 "ok\n"; }
  }
}
CONF
docker run -d --name "$RUN_ID-nginx" --network "$RUN_ID" --network-alias "$NAME" \
  --user "$(id -u):$(id -g)" --read-only --cap-drop ALL --tmpfs /tmp:rw,size=16m,mode=1777 \
  -v "$TMP/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$CERTS/live:/etc/nginx/certs:ro" \
  -v "$CERTS/acme-webroot:/var/www/acme:ro" "$NGINX_IMAGE" >/dev/null
assert "nginx started with the placeholder certificate" $?
[ "$(docker exec "$RUN_ID-nginx" ls /etc/nginx/certs | sort | tr '\n' ' ')" = 'fullchain.pem privkey.pem ' ] &&
  ! docker exec "$RUN_ID-nginx" test -e /etc/nginx/certs/letsencrypt
assert "nginx sees the served pair and nothing of the certbot state" $?
sleep 2
[[ "$(issuer_served)" == *"CN = $NAME"* || "$(issuer_served)" == *"CN=$NAME"* ]]
assert "the placeholder is served before issuance" $?

out="$(certbot certonly --webroot -w /certs/acme-webroot --cert-name manuspectrum -d "$NAME" \
  --email ops@manuspectrum.test --agree-tos --no-eff-email --non-interactive \
  --server https://pebble:14000/dir --deploy-hook /hooks/deploy-hook.sh 2>&1)"
rc=$?
[ "$rc" -eq 0 ] || echo "$out" >&2
assert "certbot certonly --webroot issues a certificate from Pebble" "$rc"
[[ "$out" == *"installed /certs/letsencrypt/live/manuspectrum into /certs/live"* ]]
assert "the deploy hook ran on issuance" $?

[ "$(cksum <"$CERTS/live/fullchain.pem")" != "$placeholder_sum" ]
assert "fullchain.pem was replaced by the hook" $?
[ "$(stat -c %a "$CERTS/live/fullchain.pem" "$CERTS/live/privkey.pem" | sort -u)" = 640 ]
assert "fullchain.pem and privkey.pem are mode 0640" $?
[ "$(openssl x509 -in "$CERTS/live/fullchain.pem" -noout -pubkey)" = \
  "$(openssl pkey -in "$CERTS/live/privkey.pem" -pubout)" ]
assert "the installed key matches the installed certificate" $?
[ -z "$(find "$CERTS/live" -maxdepth 1 -name '.*.new')" ]
assert "the hook leaves no temporary file" $?

docker exec "$RUN_ID-nginx" nginx -s reload 2>/dev/null
assert "nginx reloads" $?
sleep 1
[[ "$(issuer_served)" == *Pebble* ]]
assert "after the reload nginx serves the certificate issued by Pebble" $?

issued_sum="$(cksum <"$CERTS/live/fullchain.pem")"
out="$(certbot renew --non-interactive 2>&1)"
[ "$(cksum <"$CERTS/live/fullchain.pem")" = "$issued_sum" ] && [[ "$out" != *"installed /certs/letsencrypt"* ]]
assert "certbot renew leaves a certificate that is not due alone, hook not run" $?

out="$(certbot renew --non-interactive --force-renewal 2>&1)"
rc=$?
[ "$rc" -eq 0 ] || echo "$out" >&2
[[ "$out" == *"installed /certs/letsencrypt/live/manuspectrum into /certs/live"* ]] && [ "$(cksum <"$CERTS/live/fullchain.pem")" != "$issued_sum" ]
assert "certbot renew --force-renewal runs the hook again and replaces the files" $?

# systemd units, placeholders substituted, checked by systemd-analyze.
mkdir -p "$TMP/units"
for unit in service timer; do
  sed -e "s|@DEPLOY_DIR@|/opt/manuspectrum/deploy|g" -e 's|@APP_USER@|root|g' \
    "$DEPLOY/systemd/manuspectrum-cert-renew.$unit.in" >"$TMP/units/manuspectrum-cert-renew.$unit"
done
chmod 0644 "$TMP/units/"*
verify="$(docker run --rm -v "$TMP/units:/units:ro" "$DEBIAN_IMAGE" sh -c '
  apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends systemd make >/dev/null 2>&1 &&
  mkdir -p /opt/manuspectrum/deploy &&
  systemd-analyze verify --man=no /units/manuspectrum-cert-renew.service /units/manuspectrum-cert-renew.timer 2>&1
  echo "exit=$?"' 2>&1)"
echo "$verify" | grep -v '^exit=' | grep -iv 'docker.service\|network-online' >&2
[[ "$verify" == *"exit=0"* ]]
assert "systemd-analyze verify accepts the service and timer units" $?

echo "1..$n"
exit "$failed"
