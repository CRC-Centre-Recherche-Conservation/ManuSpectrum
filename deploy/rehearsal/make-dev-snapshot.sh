#!/usr/bin/env bash
# Writes a reusable snapshot of the development data: the PostgreSQL database
# (db.dump), the uploaded files (media.tar) and a manifest.json that describes
# them. Runs on the development machine, not in Docker. The snapshot is loaded
# on the rehearsal VM with `make -C deploy load-snapshot` (see README.md).
#
# Usage: make-dev-snapshot.sh [--out DIR] [--python PATH] [--repo DIR]
#   --out DIR      destination, created and refused when not empty
#                  (default ./ms-snapshot-<UTC date>)
#   --python PATH  python of the project environment (default <repo>/../venv/bin/python)
#   --repo DIR     repository root (default: the root of this checkout)
#
# The connection settings are read from the project's Django settings. The
# database password reaches pg_dump through PGPASSWORD only and is never
# printed. The snapshot holds user accounts and research data.
#
# Uploaded files: the rows of the `files` table whose file is not under
# MEDIA_ROOT/uploadedfiles are counted, recorded in manifest.json and printed.
# Above SNAPSHOT_MAX_MISSING_PERCENT (default 10) of the cited files the run
# stops before dumping: a rehearsal on such a snapshot shows broken images and
# downloads everywhere, and a high share usually means MEDIA_ROOT is the one of
# another checkout (it lives inside the Python package of each checkout).
# ALLOW_MISSING_FILES=yes writes the snapshot anyway.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT=""
PY=""

usage() { sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; }
log() { echo "make-dev-snapshot: $*" >&2; }
die() { log "$*"; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="${2:?--out needs a directory}"; shift 2 ;;
    --python) PY="${2:?--python needs a path}"; shift 2 ;;
    --repo) REPO="$(cd "${2:?--repo needs a directory}" && pwd)"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

[ -n "$OUT" ] || OUT="./ms-snapshot-$(date -u +%Y-%m-%d)"
[ -n "$PY" ] || PY="$REPO/../venv/bin/python"
[ -x "$PY" ] || die "python not found or not executable: $PY (use --python)"
[ -f "$REPO/manage.py" ] || die "no manage.py in $REPO (use --repo)"
command -v pg_dump >/dev/null || die "pg_dump is required"
command -v tar >/dev/null || die "tar is required"
command -v sha256sum >/dev/null || die "sha256sum is required"

if [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then
  die "$OUT exists and is not empty; choose another --out"
fi
umask 077
mkdir -p "$OUT"
chmod 0700 "$OUT"
OUT="$(cd "$OUT" && pwd)"

log "reading the settings and the counts through manage.py"
# One line `MSSNAP <json>`; anything else Django prints is ignored.
info_line="$(cd "$REPO" && "$PY" manage.py shell -c '
import json
import os
from importlib.metadata import version
from django.conf import settings
from django.db import connection
from django.db.migrations.loader import MigrationLoader

db = settings.DATABASES["default"]
with connection.cursor() as cursor:
    cursor.execute("SELECT count(*) FROM resource_instances")
    resources = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM tiles")
    tiles = cursor.fetchone()[0]
    cursor.execute("SELECT DISTINCT ON (app) app, name FROM django_migrations ORDER BY app, id DESC")
    migrations = dict(cursor.fetchall())
    cursor.execute("SELECT path FROM files")
    paths = [row[0] or "" for row in cursor.fetchall()]
missing = sum(
    1
    for path in paths
    if not path.startswith(settings.UPLOADED_FILES_DIR + "/")
    or not os.path.isfile(os.path.join(str(settings.MEDIA_ROOT), path))
)
loader = MigrationLoader(connection)
on_disk = set(loader.disk_migrations)
apps_on_disk = {app for app, _ in on_disk}
ahead = sorted(
    f"{app}.{name}"
    for app, name in loader.applied_migrations
    if app in apps_on_disk and (app, name) not in on_disk
)
print("MSSNAP " + json.dumps({
    "host": db.get("HOST") or "", "port": str(db.get("PORT") or ""),
    "name": db["NAME"], "user": db["USER"], "password": db.get("PASSWORD") or "",
    "media_root": str(settings.MEDIA_ROOT), "uploads": settings.UPLOADED_FILES_DIR,
    "arches": version("arches"), "resources": resources, "tiles": tiles,
    "migrations": migrations, "migrations_ahead_of_code": ahead,
    "files_cited": len(paths), "files_missing": missing,
}))
' | sed -n 's/^MSSNAP //p' | tail -n 1)"
[ -n "$info_line" ] || die "manage.py did not return the settings"

# The JSON stays in this variable; one field at a time reaches the shell.
field() { printf '%s' "$info_line" | "$PY" -c 'import json,sys; v=json.load(sys.stdin)[sys.argv[1]]; print(v if isinstance(v,(str,int)) else json.dumps(v))' "$1"; }
DB_HOST="$(field host)"
DB_PORT="$(field port)"
DB_NAME="$(field name)"
DB_USER="$(field user)"
DB_PASSWORD="$(field password)"
MEDIA_ROOT="$(field media_root)"
UPLOADS="$(field uploads)"
# The password leaves the JSON here: later child processes (the manifest
# writer) inherit INFO_LINE and must not see it.
info_line="$(printf '%s' "$info_line" | "$PY" -c 'import json,sys; v=json.load(sys.stdin); v.pop("password", None); print(json.dumps(v))')"

AHEAD="$(field migrations_ahead_of_code)"
if [ "$AHEAD" != "[]" ]; then
  log "WARNING: the database is ahead of the checked-out code: $(printf '%s' "$AHEAD" | "$PY" -c 'import json,sys; print(", ".join(json.load(sys.stdin)))'); the snapshot will be refused by an image built from this commit."
fi

[ -d "$MEDIA_ROOT/$UPLOADS" ] || die "no uploaded files directory: $MEDIA_ROOT/$UPLOADS"

FILES_CITED="$(field files_cited)"
FILES_MISSING="$(field files_missing)"
MAX_MISSING="${SNAPSHOT_MAX_MISSING_PERCENT:-10}"
if ! [[ "$MAX_MISSING" =~ ^[0-9]{1,3}$ ]] || [ "$MAX_MISSING" -gt 100 ]; then
  die "SNAPSHOT_MAX_MISSING_PERCENT must be a whole number from 0 to 100, not '$MAX_MISSING'"
fi
log "uploaded files: $FILES_CITED cited by the database, $FILES_MISSING missing on disk under $MEDIA_ROOT/$UPLOADS"
if [ "$FILES_MISSING" -gt 0 ]; then
  missing_msg="$FILES_MISSING of the $FILES_CITED files cited by the database are missing under $MEDIA_ROOT/$UPLOADS"
  if [ $((FILES_MISSING * 100)) -le $((FILES_CITED * MAX_MISSING)) ]; then
    log "WARNING: $missing_msg (at most $MAX_MISSING % allowed): the rehearsal shows them as broken"
  elif [ "${ALLOW_MISSING_FILES:-}" = yes ]; then
    log "WARNING: $missing_msg, above $MAX_MISSING %; written anyway (ALLOW_MISSING_FILES=yes)"
  else
    die "$missing_msg, above $MAX_MISSING %: nothing was written. MEDIA_ROOT may be the one of another checkout (each checkout has its own manuspectrum/uploadedfiles; run this script from the checkout the development server uses, or pass --repo). To write the snapshot anyway: ALLOW_MISSING_FILES=yes; to change the limit: SNAPSHOT_MAX_MISSING_PERCENT=<0-100>."
  fi
fi

pg_args=(--username "$DB_USER" --dbname "$DB_NAME")
[ -z "$DB_HOST" ] || pg_args+=(--host "$DB_HOST")
[ -z "$DB_PORT" ] || pg_args+=(--port "$DB_PORT")

log "dumping database $DB_NAME to db.dump"
PGPASSWORD="$DB_PASSWORD" pg_dump -Fc --no-owner --no-privileges --exclude-table='silk_*' \
  "${pg_args[@]}" --file "$OUT/db.dump"
unset DB_PASSWORD

log "archiving $MEDIA_ROOT/$UPLOADS to media.tar"
tar -C "$MEDIA_ROOT" -cf "$OUT/media.tar" "$UPLOADS"

log "writing manifest.json"
GIT_COMMIT="$(git -C "$REPO" rev-parse HEAD 2>/dev/null || echo unknown)"
GIT_BRANCH="$(git -C "$REPO" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
PG_DUMP_VERSION="$(pg_dump --version)"
DB_SHA="$(sha256sum "$OUT/db.dump" | cut -d' ' -f1)"
MEDIA_SHA="$(sha256sum "$OUT/media.tar" | cut -d' ' -f1)"
DB_SIZE="$(stat -c %s "$OUT/db.dump")"
MEDIA_SIZE="$(stat -c %s "$OUT/media.tar")"
export INFO_LINE="$info_line" OUT GIT_COMMIT GIT_BRANCH PG_DUMP_VERSION DB_SHA MEDIA_SHA DB_SIZE MEDIA_SIZE
"$PY" - <<'PY'
import datetime
import json
import os

info = json.loads(os.environ["INFO_LINE"])
manifest = {
    "created_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "git": {"commit": os.environ["GIT_COMMIT"], "branch": os.environ["GIT_BRANCH"]},
    "arches_version": info["arches"],
    "pg_dump_version": os.environ["PG_DUMP_VERSION"],
    "counts": {"resource_instances": info["resources"], "tiles": info["tiles"]},
    "uploaded_files": {"cited": info["files_cited"], "missing": info["files_missing"]},
    "migrations": info["migrations"],
    "migrations_ahead_of_code": info["migrations_ahead_of_code"],
    "files": {
        "db.dump": {"sha256": os.environ["DB_SHA"], "bytes": int(os.environ["DB_SIZE"])},
        "media.tar": {"sha256": os.environ["MEDIA_SHA"], "bytes": int(os.environ["MEDIA_SIZE"])},
    },
}
with open(os.path.join(os.environ["OUT"], "manifest.json"), "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2, sort_keys=True)
    handle.write("\n")
PY
chmod 0600 "$OUT/db.dump" "$OUT/media.tar" "$OUT/manifest.json"

cat >&2 <<MSG

Snapshot written to $OUT
  db.dump     $DB_SIZE bytes
  media.tar   $MEDIA_SIZE bytes ($FILES_CITED uploaded files cited, $FILES_MISSING missing)
  manifest.json

Copy it to the rehearsal VM:
  scp -r $OUT <admin>@<rehearsal-vm>:
then, on the VM, as the service account:
  make -C deploy load-snapshot SNAPSHOT=<path of the copy> CONFIRM=yes

WARNING: this snapshot contains user accounts and research data. Never put it
in Git and never in a public place; delete it from every machine once done.
MSG
