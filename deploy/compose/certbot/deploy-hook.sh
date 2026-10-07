#!/bin/sh
# deploy/compose/certbot/deploy-hook.sh
# certbot deploy hook: runs after an issuance or a renewal that succeeded,
# with RENEWED_LINEAGE set to the lineage directory. Installs the new chain
# and key where nginx reads them (CERTS_DIR/fullchain.pem and privkey.pem, mode
# 0640), each through a temporary name and a rename so nginx never reads a
# half-written file. nginx is reloaded by the Makefile, not here.
set -eu

lineage="${RENEWED_LINEAGE:?RENEWED_LINEAGE is not set}"
dest="${CERTS_INSTALL_DIR:-/certs}"

for name in fullchain privkey; do
  install -m 0640 "$lineage/$name.pem" "$dest/.$name.pem.new"
  mv -f "$dest/.$name.pem.new" "$dest/$name.pem"
done
echo "installed $lineage into $dest"
