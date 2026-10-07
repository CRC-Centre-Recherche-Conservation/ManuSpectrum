# Certificates

nginx always reads `CERTS_DIR/fullchain.pem` and `CERTS_DIR/privkey.pem`
(mounted read-only at `/etc/nginx/certs`). `CERT_MODE` in `.env` chooses how
those two files are produced.

| Mode | Who writes the files | Use |
|---|---|---|
| `local` | `make-local-ca.sh` | rehearsal and CI, domain `manuspectrum.test` |
| `acme` | certbot (Let's Encrypt) and its deploy hook | production default |
| `provided` | the operator | a certificate from the institution's own CA |

## local

```bash
deploy/certs/make-local-ca.sh "$CERTS_DIR" manuspectrum.test www.manuspectrum.test
```

Needs `openssl` 3.0 or later on the host. Files written in `CERTS_DIR`:

| File | Mode | Content |
|---|---|---|
| `ca.crt` | 0644 | the local CA (RSA 4096, 10 years, `CA:TRUE` critical) |
| `ca.key` | 0600 | the CA key |
| `fullchain.pem` | 0640 | server certificate, then the CA |
| `privkey.pem` | 0640 | server key (RSA 2048) |

The server certificate lists every name in its SAN (the first name is also the
CN) and is valid 397 days. A second run keeps the existing CA and issues a new
server certificate: run it again before the 397 days end, or to change the
names. Names are host names or IPv4 addresses; anything else is refused.

**`ca.key` never leaves the rehearsal host.** Anyone holding it can issue a
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
make cert-renew   # certbot renew, reload only when the deploy hook ran
```

`cert-init` first writes a short-lived self-signed placeholder so nginx can
start and answer the HTTP-01 challenge:

```bash
deploy/certs/make-local-ca.sh --self-signed "$CERTS_DIR" manuspectrum.test
```

This writes only `fullchain.pem` and `privkey.pem` (0640), valid 30 days. The
deploy hook of the certbot service then replaces them with the issued
certificate, also at mode 0640.

## provided

Copy the certificate chain (server certificate first) to
`CERTS_DIR/fullchain.pem` and the key to `CERTS_DIR/privkey.pem`, mode 0640,
readable by the service account. Reload nginx
(`docker compose exec nginx nginx -s reload`) after each renewal.

## Tests

```bash
deploy/certs/tests/test_make_local_ca.sh
```
