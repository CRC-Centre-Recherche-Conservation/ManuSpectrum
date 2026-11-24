"""Staging directory of a measurement-files run.

Bytes of a run live in `MEDIA_ROOT / MEASUREMENT_STAGING_DIR / <run id>/`,
outside `uploadedfiles/` (never served) and excluded from backups. A stored
name starts with the item id, so a purge can find orphans.
"""

import os
import shutil
import tempfile
import unicodedata
from pathlib import Path

from django.conf import settings

NAME_MAX = 200


def _root() -> Path:
    return Path(settings.MEDIA_ROOT) / settings.MEASUREMENT_STAGING_DIR


def run_dir(run_id) -> Path:
    path = _root() / str(run_id)
    path.mkdir(mode=0o750, parents=True, exist_ok=True)
    return path


def safe_name(raw: str) -> str:
    """Base name only: NFC, control characters removed, 200 characters, never empty."""
    name = unicodedata.normalize("NFC", raw or "")
    name = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf"))
    name = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if name in ("", ".", ".."):
        return "file"
    return name[:NAME_MAX]


def _inside(directory: Path, name: str) -> Path:
    if not name or "/" in name or "\\" in name or "\x00" in name or ".." in name:
        raise ValueError("not a staged name")
    target = (directory / name).resolve()
    if target.parent != directory.resolve():
        raise ValueError("path leaves the staging directory")
    return target


def store(run_id, item_id, data: bytes, suffix: str) -> str:
    """Write `<item id>-<suffix>` atomically and return the name."""
    directory = run_dir(run_id)
    name = f"{item_id}-{suffix}"
    target = _inside(directory, name)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(tmp, 0o640)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return name


def read(run_id, name: str) -> bytes:
    return _inside(run_dir(run_id), name).read_bytes()


def remove_run(run_id) -> None:
    shutil.rmtree(_root() / str(run_id), ignore_errors=True)
