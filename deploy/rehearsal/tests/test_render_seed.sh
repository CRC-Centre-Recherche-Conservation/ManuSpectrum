#!/usr/bin/env bash
# Tests for render-seed.sh. Prints `ok N` / `not ok N`; exits non-zero on failure.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDER="$HERE/../render-seed.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

KEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExample0123 test@laptop'
# shellcheck disable=SC2016
HASH='$6$salt/ab.c$x&y/z.$Q1w2e3r4t5y6u7i8o9p0/AbCdEf.GhIjKl&MnOpQrStUvWxYz0123456789'
printf '%s\n' "$KEY" >"$TMP/key.pub"

n=0 failed=0
assert() { # assert DESCRIPTION CONDITION-EXIT-CODE
  n=$((n + 1))
  if [ "$2" -eq 0 ]; then echo "ok $n - $1"; else echo "not ok $n - $1"; failed=1; fi
}

# 1. nominal render
"$RENDER" --out "$TMP/o1" --pubkey "$TMP/key.pub" --password-hash "$HASH" >/dev/null 2>&1
ok=1
if [ -f "$TMP/o1/user-data" ] && ! grep -q '@@' "$TMP/o1/user-data" \
  && grep -qF "$KEY" "$TMP/o1/user-data" && grep -qF "$HASH" "$TMP/o1/user-data" \
  && grep -q 'username: admin1' "$TMP/o1/user-data" && [ -f "$TMP/o1/meta-data" ]; then ok=0; fi
assert "nominal render substitutes every marker" "$ok"

# 2. hash with / . $ & kept byte for byte
line="$(grep 'password:' "$TMP/o1/user-data")"
[ "$line" = "    password: \"$HASH\"" ]
assert "hash with special characters is copied verbatim" "$?"

# 3. invalid key
"$RENDER" --out "$TMP/o3" --pubkey <(echo not-a-key) --password-hash "$HASH" >/dev/null 2>&1
rc=$?
[ "$rc" -ne 0 ] && [ ! -e "$TMP/o3/user-data" ]
assert "invalid key is refused and nothing is written" "$?"

# 4. hash not $6$
"$RENDER" --out "$TMP/o4" --pubkey "$TMP/key.pub" --password-hash 'plaintext' >/dev/null 2>&1
rc=$?
[ "$rc" -ne 0 ] && [ ! -e "$TMP/o4/user-data" ]
assert "non SHA-512 hash is refused" "$?"

# 5. valid YAML
if python3 -c 'import yaml' 2>/dev/null; then
  head -n1 "$TMP/o1/user-data" | grep -qx '#cloud-config' \
    && python3 -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]))' "$TMP/o1/user-data"
  assert "rendered user-data is #cloud-config YAML" "$?"
else
  n=$((n + 1)); echo "ok $n # skip PyYAML not installed"
fi

# 6. admin user option and validation
"$RENDER" --out "$TMP/o6" --pubkey "$TMP/key.pub" --password-hash "$HASH" --admin-user ops_2 --hostname box >/dev/null 2>&1
grep -q 'username: ops_2' "$TMP/o6/user-data" && grep -q 'hostname: box' "$TMP/o6/user-data" \
  && grep -q '^local-hostname: box$' "$TMP/o6/meta-data"
assert "--admin-user and --hostname are applied" "$?"

"$RENDER" --out "$TMP/o7" --pubkey "$TMP/key.pub" --password-hash "$HASH" --admin-user 'Bad Name' >/dev/null 2>&1
rc=$?
[ "$rc" -ne 0 ] && [ ! -e "$TMP/o7/user-data" ]
assert "invalid admin user is refused" "$?"

# 8. locale, keyboard and root size options
"$RENDER" --out "$TMP/o8" --pubkey "$TMP/key.pub" --password-hash "$HASH" --locale de_DE.UTF-8 --keyboard de --root-size 70G >/dev/null 2>&1
grep -q 'locale: de_DE.UTF-8' "$TMP/o8/user-data" && grep -q 'layout: de}' "$TMP/o8/user-data" \
  && grep -q 'name: root, size: 70G' "$TMP/o8/user-data" && ! grep -q '@@' "$TMP/o8/user-data"
assert "--locale, --keyboard and --root-size are applied" "$?"

# 9. defaults are neutral
grep -q 'locale: en_US.UTF-8' "$TMP/o1/user-data" && grep -q 'layout: us}' "$TMP/o1/user-data" \
  && grep -q 'name: root, size: 50G' "$TMP/o1/user-data"
assert "defaults are en_US.UTF-8, us and 50G" "$?"

# 10. invalid values
for bad in "--locale xx" "--keyboard FR" "--root-size 50" "--root-size 5G;x"; do
  # shellcheck disable=SC2086
  "$RENDER" --out "$TMP/o10" --pubkey "$TMP/key.pub" --password-hash "$HASH" $bad >/dev/null 2>&1
  rc=$?
  [ "$rc" -ne 0 ] && [ ! -e "$TMP/o10/user-data" ]
  assert "invalid option is refused: $bad" "$?"
done

# 11. hash from a file
printf '%s\n' "$HASH" >"$TMP/hash.txt"
"$RENDER" --out "$TMP/o11" --pubkey "$TMP/key.pub" --password-hash-file "$TMP/hash.txt" >/dev/null 2>&1
grep -qF "password: \"$HASH\"" "$TMP/o11/user-data"
assert "--password-hash-file is read" "$?"

exit "$failed"
