"""Intake of a measurement-files run: uploads, ZIP expansion, stored files.

Every function acts on a run in the ``collecting`` state and never touches an
existing tile. Uploaded bytes go to the run's staging directory
(``staging.store``) with their SHA-256 computed while they are copied; a file
over ``max_file_bytes()`` is refused without being stored. A ZIP is checked
from its central directory (entries, total size, ratio) before anything is
extracted, then again while each member streams; it is never kept, and the
folders of its members become ``relative_dir``.
"""

import hashlib
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import timedelta

from celery import current_app
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from arches.app.models.models import CardXNodeXWidget, File

from manuspectrum.constants.xy_presets import DATA_FILE_NODE_ID
from manuspectrum.measurement_files import catalogue, staging
from manuspectrum.models import MeasurementItem, MeasurementRun

CHUNK = 1 << 20
RELATIVE_DIR_MAX = 400
PREPARE_TASK = "manuspectrum.measurement_prepare"
WRITE_TASK = "manuspectrum.measurement_write"
UNDO_TASK = "manuspectrum.measurement_undo"
CLAIM_STALE = timedelta(minutes=10)
RESUME_THROTTLE = 120
IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


@dataclass(frozen=True)
class Rejection:
    name: str
    reason: str


class ZipRefused(Exception):
    """The whole ZIP is refused; ``reason`` is the code returned to the client."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def max_file_bytes() -> int:
    """Per-file limit: ``maxFilesize`` (MB) of the file widget of the Analysis card.

    Read from the database at each call. A missing, non-numeric or non-positive
    value falls back to ``MEASUREMENT_DEFAULT_MAX_FILE_MB``.
    """
    config = (
        CardXNodeXWidget.objects.filter(node_id=DATA_FILE_NODE_ID)
        .values_list("config", flat=True)
        .first()
    )
    config = getattr(config, "raw_value", config)
    megabytes = None
    if isinstance(config, dict):
        try:
            megabytes = float(config.get("maxFilesize"))
        except (TypeError, ValueError):
            megabytes = None
    if megabytes is None or megabytes <= 0 or megabytes != megabytes:
        megabytes = settings.MEASUREMENT_DEFAULT_MAX_FILE_MB
    return int(megabytes * 1024 * 1024)


def clean_relative_dir(raw) -> str:
    """Folder of a file: NFC, control characters removed, no empty, ``.`` or ``..`` segment."""
    text = unicodedata.normalize("NFC", str(raw or ""))
    text = "".join(c for c in text if unicodedata.category(c) not in ("Cc", "Cf"))
    parts = [p.strip() for p in text.replace("\\", "/").split("/")]
    parts = [p for p in parts if p not in ("", ".", "..")]
    return "/".join(parts)[:RELATIVE_DIR_MAX]


def _not_measure(name, relative_dir) -> bool:
    segments = [s.lower() for s in relative_dir.split("/")]
    return (
        name.lower() in IGNORED_NAMES or name.startswith("._") or "__macosx" in segments
    )


def _run_usage(run):
    totals = run.items.aggregate(size=Sum("size"))
    return run.items.count(), totals["size"] or 0


def _suffix(name):
    return name.replace("..", ".")


def accept_upload(run, name, relative_dir, stream, *, declared_size=None):
    """Store one uploaded file of *run*; returns the item or a ``Rejection``.

    Reasons: ``not_measure``, ``too_large``, ``run_full``, ``duplicate``.
    ``declared_size`` (a ZIP member's central-directory size) refuses an
    oversized file before any byte is read.
    """
    relative_dir = clean_relative_dir(relative_dir)
    name = staging.safe_name(name)
    if _not_measure(name, relative_dir):
        return Rejection(name, "not_measure")
    limit = max_file_bytes()
    if declared_size is not None and declared_size > limit:
        return Rejection(name, "too_large")
    count, used = _run_usage(run)
    if count >= settings.MEASUREMENT_MAX_RUN_FILES:
        return Rejection(name, "run_full")
    digest = hashlib.sha256()
    chunks = []
    size = 0
    while True:
        chunk = stream.read(CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            return Rejection(name, "too_large")
        digest.update(chunk)
        chunks.append(chunk)
    if used + size > settings.MEASUREMENT_MAX_RUN_BYTES:
        return Rejection(name, "run_full")
    sha = digest.hexdigest()
    if run.items.filter(origin="upload", sha256=sha).exists():
        return Rejection(name, "duplicate")
    item = MeasurementItem(
        run=run,
        origin="upload",
        source_name=name,
        relative_dir=relative_dir,
        sha256=sha,
        size=size,
    )
    item.staged_name = f"{item.id}-{_suffix(name)}"
    try:
        with transaction.atomic():
            item.save(force_insert=True)
    except IntegrityError:
        return Rejection(name, "duplicate")
    try:
        staging.store(run.id, item.id, b"".join(chunks), _suffix(name))
    except BaseException:
        item.delete()
        raise
    return item


class _Member:
    """A ZIP member's stream that refuses to yield more than its declared size or the shared budget."""

    def __init__(self, handle, declared, budget):
        self.handle, self.declared, self.budget, self.read_bytes = (
            handle,
            declared,
            budget,
            0,
        )

    def read(self, size=-1):
        data = self.handle.read(size)
        self.read_bytes += len(data)
        self.budget["left"] -= len(data)
        if self.read_bytes > self.declared or self.budget["left"] < 0:
            raise ZipRefused("size_mismatch")
        return data


def check_zip(archive):
    """Check a ZIP's central directory; returns its file entries or raises ``ZipRefused``."""
    entries = [i for i in archive.infolist() if not i.is_dir()]
    if len(entries) > settings.MEASUREMENT_ZIP_MAX_ENTRIES:
        raise ZipRefused("too_many_entries")
    total = sum(i.file_size for i in entries)
    if total > settings.MEASUREMENT_MAX_RUN_BYTES:
        raise ZipRefused("too_large_uncompressed")
    packed = sum(i.compress_size for i in entries)
    if total > settings.MEASUREMENT_ZIP_MAX_RATIO * max(packed, 1):
        raise ZipRefused("ratio")
    for info in entries:
        if info.compress_size and (
            info.file_size > settings.MEASUREMENT_ZIP_MAX_RATIO * info.compress_size
        ):
            raise ZipRefused("ratio")
    return entries


def expand_zip(run, stream):
    """Accept the members of a ZIP uploaded as one part; returns items and rejections.

    Raises ``ZipRefused`` when the archive is unreadable or exceeds an entry,
    size or ratio cap. Members' paths count only as ``relative_dir``;
    encrypted members are rejected one by one.
    """
    try:
        archive = zipfile.ZipFile(stream)
    except (zipfile.BadZipFile, OSError, ValueError):
        raise ZipRefused("bad_zip")
    results = []
    with archive:
        entries = check_zip(archive)
        budget = {"left": settings.MEASUREMENT_MAX_RUN_BYTES}
        for info in entries:
            directory, _, base = info.filename.replace("\\", "/").rpartition("/")
            if info.flag_bits & 0x1:
                results.append(Rejection(staging.safe_name(base), "encrypted"))
                continue
            try:
                with archive.open(info) as handle:
                    results.append(
                        accept_upload(
                            run,
                            base,
                            directory,
                            _Member(handle, info.file_size, budget),
                            declared_size=info.file_size,
                        )
                    )
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError):
                results.append(Rejection(staging.safe_name(base), "unreadable"))
    return results


def stored_candidates(run, user):
    """Raw files of the run's Analyses without a CSV twin: ``[(card, StoredFile)]``.

    One ``document_analyses`` call: call it once per request.
    """
    cards = catalogue.document_analyses(run.document_id, user, run.project_id)
    return [
        (card, stored)
        for card in cards
        for stored in card.files
        if stored.is_raw and not stored.has_csv_twin
    ]


def select_stored(run, user, file_ids):
    """Add stored raw files to *run*; returns ``(items, rejections)``.

    Reasons: ``not_in_document`` (not a raw file without twin of an Analysis
    of the run's Document), ``not_editable``, ``duplicate``, ``missing`` (the
    bytes cannot be read), ``run_full``.
    """
    candidates = {
        stored.file_id: (card, stored) for card, stored in stored_candidates(run, user)
    }
    count, used = _run_usage(run)
    taken = {
        str(f)
        for f in run.items.filter(origin="stored").values_list(
            "source_file_id", flat=True
        )
    }
    accepted, rejected = [], []
    for file_id in file_ids:
        file_id = str(file_id)
        found = candidates.get(file_id)
        if found is None:
            rejected.append(Rejection(file_id, "not_in_document"))
            continue
        card, stored = found
        if not card.editable:
            rejected.append(Rejection(stored.name, "not_editable"))
        elif file_id in taken:
            rejected.append(Rejection(stored.name, "duplicate"))
        elif count + len(accepted) >= settings.MEASUREMENT_MAX_RUN_FILES:
            rejected.append(Rejection(stored.name, "run_full"))
        else:
            sha = catalogue.stored_sha256(file_id)
            row = File.objects.filter(pk=file_id).first()
            if sha is None or row is None:
                rejected.append(Rejection(stored.name, "missing"))
                continue
            try:
                size = row.path.size
            except OSError:
                rejected.append(Rejection(stored.name, "missing"))
                continue
            try:
                with transaction.atomic():
                    accepted.append(
                        MeasurementItem.objects.create(
                            run=run,
                            origin="stored",
                            source_name=staging.safe_name(stored.name),
                            sha256=sha,
                            size=size,
                            source_file_id=file_id,
                            source_analysis_id=card.id,
                        )
                    )
            except IntegrityError:
                rejected.append(Rejection(stored.name, "duplicate"))
                continue
            taken.add(file_id)
    return accepted, rejected


def start_preparation(run):
    """Move a collecting run to ``preparing`` and enqueue its task after commit.

    Returns ``"started"``, ``"already"`` (already preparing) or ``"refused"``
    (another state).
    """
    with transaction.atomic():
        changed = MeasurementRun.objects.filter(pk=run.pk, state="collecting").update(
            state="preparing"
        )
        if changed:
            transaction.on_commit(
                lambda: current_app.send_task(PREPARE_TASK, args=[str(run.id)])
            )
            return "started"
    run.refresh_from_db(fields=["state"])
    return "already" if run.state == "preparing" else "refused"


PHASES = {
    "preparing": (PREPARE_TASK, Q(state="queued")),
    "writing": (WRITE_TASK, Q(state="prepared", decision="ready")),
    "undoing": (UNDO_TASK, Q(state="written")),
}


def send(task, run_id, countdown=None):
    """Send the task *task* for a run through the Celery app."""
    options = {} if countdown is None else {"countdown": countdown}
    current_app.send_task(task, args=[str(run_id)], **options)


def resume_if_stalled(run):
    """Re-send the task of a ``preparing``, ``writing`` or ``undoing`` run that nobody is working on.

    The run is stalled when items wait for a worker (free for its phase, or
    ``claimed`` for more than ``CLAIM_STALE``) and no claim is younger than
    that. At most one re-send per ``RESUME_THROTTLE`` seconds, whoever polls.
    Returns whether the task was sent.
    """
    phase = PHASES.get(run.state)
    if phase is None:
        return False
    task, free = phase
    if run.items.filter(
        state="claimed", claimed_at__gte=timezone.now() - CLAIM_STALE
    ).exists():
        return False
    if not run.items.filter(free | Q(state="claimed")).exists():
        return False
    if not cache.add(f"ms-measurement-resume-{run.id}", 1, RESUME_THROTTLE):
        return False
    send(task, run.id)
    return True
