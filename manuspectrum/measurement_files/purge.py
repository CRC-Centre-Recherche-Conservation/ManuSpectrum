"""The daily purge of measurement-files staging.

``purge`` removes what a run no longer needs once it is older than
``MEASUREMENT_STAGING_DAYS`` (measured from ``updated_at``):

- a run that is not ``written`` or ``undone`` loses its staging directory and
  its rows, unless an item of it is ``written`` (its rows hold what an undo
  needs: only its staging goes);
- a ``written`` or ``undone`` run loses its staging directory only. Its rows
  stay: the undo of a written run reads them;
- a name under ``uploadedfiles/`` that starts with the id of an item of a known
  run, that no ``File`` row references and that is older than ``ORPHAN_GRACE``,
  is a leftover of a write that rolled back and is removed.

``apply=False`` only reports. An applied pass takes the ``single_pass`` lock
(a pass that finds it held does nothing) and sets the timestamp gauge once it
has completed.
"""

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from arches.app.models.models import File

from manuspectrum.accounts.embargo import single_pass
from manuspectrum.measurement_files import staging
from manuspectrum.models import MeasurementItem, MeasurementRun
from manuspectrum.observability import metrics

logger = logging.getLogger(__name__)

LOCK_KEY = "measurement-staging-purge-lock"
STORED_DIR = "uploadedfiles"
KEEP_ROWS = ("written", "undone")
ORPHAN_GRACE = timedelta(days=1)
ID_LENGTH = len(str(uuid.uuid4()))


@dataclass
class PurgeReport:
    """What a pass did, or with ``apply=False`` would do."""

    applied: bool = False
    locked: bool = False
    staging_removed: list = field(default_factory=list)
    runs_deleted: list = field(default_factory=list)
    orphans: list = field(default_factory=list)
    failed: list = field(default_factory=list)


def _staged(run_id):
    return (
        Path(settings.MEDIA_ROOT) / settings.MEASUREMENT_STAGING_DIR / str(run_id)
    ).is_dir()


def _old_runs(cutoff):
    return MeasurementRun.objects.filter(updated_at__lt=cutoff).order_by("updated_at")


def _holds_written(run):
    return run.items.filter(state="written").exists()


def _purge_run(run, report, apply):
    """Plan, and with *apply* do, the purge of one old run."""
    has_staging = _staged(run.id)
    drop_rows = run.state not in KEEP_ROWS and not _holds_written(run)
    if has_staging:
        report.staging_removed.append(str(run.id))
    if drop_rows:
        report.runs_deleted.append(str(run.id))
    if not apply:
        return
    staging.remove_run(run.id)
    if drop_rows:
        run.delete()
        metrics.measurement_run("purged")


def _is_item_name(name, item_ids):
    return (
        len(name) > ID_LENGTH
        and name[ID_LENGTH] == "-"
        and name[:ID_LENGTH] in item_ids
    )


def _orphans(item_ids, now):
    """The stored names of known items that no ``File`` row references."""
    directory = Path(settings.MEDIA_ROOT) / STORED_DIR
    if not directory.is_dir():
        return []
    limit = (now - ORPHAN_GRACE).timestamp()
    names = [
        entry.name
        for entry in os.scandir(directory)
        if entry.is_file()
        and _is_item_name(entry.name, item_ids)
        and entry.stat().st_mtime < limit
    ]
    if not names:
        return []
    held = set(
        File.objects.filter(
            path__in=[f"{STORED_DIR}/{name}" for name in names]
        ).values_list("path", flat=True)
    )
    return sorted(name for name in names if f"{STORED_DIR}/{name}" not in held)


def _run(now, report, apply):
    cutoff = now - timedelta(days=settings.MEASUREMENT_STAGING_DAYS)
    item_ids = {str(pk) for pk in MeasurementItem.objects.values_list("pk", flat=True)}
    for run in _old_runs(cutoff):
        try:
            _purge_run(run, report, apply)
        except Exception:
            logger.exception("measurement staging purge failed")
            report.failed.append(str(run.id))
    report.orphans = _orphans(item_ids, now)
    if apply:
        directory = Path(settings.MEDIA_ROOT) / STORED_DIR
        for name in report.orphans:
            try:
                (directory / name).unlink()
            except OSError:
                logger.exception("measurement orphan not removed")
                report.failed.append(name)


def purge(now=None, *, apply=True):
    """Run the purge and return its ``PurgeReport``.

    ``apply=False`` writes nothing, takes no lock and sets no gauge.
    """
    now = now or timezone.now()
    report = PurgeReport(applied=apply)
    if not apply:
        _run(now, report, apply=False)
        return report
    with single_pass(LOCK_KEY) as held:
        if not held:
            report.locked = True
            return report
        _run(now, report, apply=True)
        metrics.MEASUREMENT_PURGE_TIMESTAMP.set(timezone.now().timestamp())
    return report
