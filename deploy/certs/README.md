# Certificates

nginx always reads `CERTS_DIR/live/fullchain.pem` and `CERTS_DIR/live/privkey.pem`
(`live/` is mounted read-only at `/etc/nginx/certs`). `CERT_MODE` in `.env`
chooses how those two files are produced. `CERTS_DIR` holds four directories,
and a container sees only the ones it needs:

| Directory | Content | Mounted by |
|---|---|---|
| `live/` | `fullchain.pem`, `privkey.pem` | nginx (read-only), certbot (writes the pair) |
| `acme-webroot/` | HTTP-01 challenge files | nginx (read-only), certbot |
| `letsencrypt/` | certbot account, lineages, logs | certbot only |
| `ca/` | `ca.crt`, `ca.key` (local mode) | nothing; `LOCAL_CA_CERT` points at `ca/ca.crt`, mounted read-only into web and worker |

| Mode | Who writes the files | Use |
|---|---|---|
| `local` | `make-local-ca.sh` | rehearsal and CI, domain `manuspectrum.test` |
| `acme` | certbot (Let's Encrypt) and its deploy hook | production default |
| `provided` | the operator | a certificate from the institution's own CA |

## local

```bash
CA_DIR="$CERTS_DIR/ca" deploy/certs/make-local-ca.sh "$CERTS_DIR/live" manuspectrum.test www.manuspectrum.test
```

`make certs-local` runs exactly this. Without `CA_DIR` the script keeps the CA
next to the pair (its first argument). Needs `openssl` 3.0 or later on the
host. Files written:

| File | Mode | Content |
|---|---|---|
| `ca/ca.crt` | 0644 | the local CA (RSA 4096, 10 years, `CA:TRUE` critical) |
| `ca/ca.key` | 0600 | the CA key |
| `live/fullchain.pem` | 0640 | server certificate, then the CA |
| `live/privkey.pem` | 0640 | server key (RSA 2048) |

The server certificate lists every name in its SAN (the first name is also the
CN) and is valid 397 days. A second run keeps the existing CA and issues a new
server certificate: run it again before the 397 days end, or to change the
names. Names are host names or IPv4 addresses; anything else is refused.

**`ca/ca.key` never leaves the rehearsal host.** Anyone holding it can issue a
certificate that every workstation trusting `ca.crt` accepts. Copy only
`ca.crt` to workstations.

### Trusting the CA on a workstation

Debian and Ubuntu:

```bash
sudo cp ca.crt /usr/local/share/ca-certificates/manuspectrum-local-ca.crt
sudo update-ca-certificates
```

Firefox keeps its own store: Settings, Privacy and Security, Certificates, View
Certificates, Authorities, Import `ca.crt`, tick « Trust this CA to identify
websites ». Chromium-based browsers on Linux use the NSS store of the user:
`certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n manuspectrum-local -i ca.crt`.

Add `manuspectrum.test` to the workstation's `/etc/hosts`, pointing at the host
running the stack.

## acme

```bash
make cert-init    # placeholder certificate, nginx up, certonly --webroot, reload
make cert-renew   # certbot renew, nginx reloaded only when the certificate changed
```

Needs `CERT_MODE=acme`, `ACME_EMAIL` (refused when empty) and `ACME_SERVER` in
`.env`. `ACME_SERVER` defaults to the Let's Encrypt **staging** directory:
run `make cert-init` against staging first, and only then switch to the
production directory and run `make cert-init CERTBOT_ARGS=--force-renewal` to
replace the staging certificate.

`cert-init` first writes a short-lived self-signed placeholder (unless a
`live/fullchain.pem` already exists) so nginx can start and serve
`/.well-known/acme-challenge/` from `CERTS_DIR/acme-webroot`:

```bash
deploy/certs/make-local-ca.sh --self-signed "$CERTS_DIR/live" manuspectrum.test
```

This writes only `fullchain.pem` and `privkey.pem` (0640), valid 30 days. The
`certbot` service (Compose profile `acme`, never started by `make up`) then
orders a certificate for every name of `DOMAIN_NAMES` under the lineage
`manuspectrum`. It runs as the service account on a read-only root with no
capability and publishes no port. Its account, lineages and logs live in
`CERTS_DIR/letsencrypt/`. Its deploy hook
(`deploy/compose/certbot/deploy-hook.sh`) copies the lineage to
`CERTS_DIR/live/fullchain.pem` and `privkey.pem` (0640, through a rename inside `live/`), where
nginx reads them; the Makefile then reloads nginx.

### Renewal

`deploy/systemd/manuspectrum-cert-renew.{service,timer}.in` run
`make -C <deploy dir> cert-renew` twice a day (`00:00` and `12:00`, up to one
hour of random delay, `Persistent=true`). certbot renews a certificate only in
its last 30 days; the deploy hook then rewrites the files and `cert-renew`
reloads nginx whenever the file changed and then exits with certbot's own status. PP-8 substitutes `@DEPLOY_DIR@` and `@APP_USER@` (an account
in the `docker` group), installs both units and enables the timer when
`CERT_MODE=acme`.

## provided

Copy the certificate chain (server certificate first) to
`CERTS_DIR/live/fullchain.pem` and the key to `CERTS_DIR/live/privkey.pem`, mode 0640,
readable by the service account. Reload nginx
(`docker compose exec nginx nginx -s reload`) after each renewal.

## Tests

```bash
deploy/certs/tests/test_make_local_ca.sh
deploy/certs/tests/test_acme_pebble.sh   # docker and network; about one minute
```

`test_acme_pebble.sh` runs the whole ACME flow against Pebble (Let's Encrypt's
test server, HTTP-01 validated for real), with the certbot image and flags of
the Compose service, a throwaway nginx and the real deploy hook, then checks
the units with `systemd-analyze verify`. It never contacts a real CA and
removes its containers and network.
