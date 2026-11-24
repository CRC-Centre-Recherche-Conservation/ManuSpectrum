"""« Supprimer »: undo exactly what a measurement-files run added.

``undo_run`` takes one chunk of ``written`` items, groups them by Analysis and
calls ``undo_analysis`` once per Analysis; the Celery task
``manuspectrum.measurement_undo`` calls it again while work remains. At the end
the run is ``undone`` and its staging directory is removed.

Only what the run created is ever touched, and only while it is still as the
writer left it:

- a recorded tile whose stored data no longer has the recorded digest was
  edited since: the whole item is kept, with its ``File`` rows
  (``kept_modified``);
- a recorded tile that is gone counts as ``already_gone``;
- a parent tile is deleted only when the run created it, it is unedited and no
  child tile is left under it;
- tiles and ``File`` rows the run did not record are never read for deletion.

One Analysis is undone in one transaction holding a lock on the run row, then on its row (the writer takes them in the same order). Arches
removes the bytes of a ``File`` in its ``post_delete`` signal, at once, and a
``File`` row follows its tile on delete: the rows are detached from their tiles
first, the tiles are deleted, and the rows are deleted on commit, so a rolled
back undo keeps tiles, rows and bytes. Tile deletions go under the undo
transaction id (``undo_transaction_id``, never the run's own, which Arches'
workflow reversal would replay), with no user, and the author is named on their
``tile delete`` rows afterwards.

``item.written["undone"]`` records the outcome of an item
(``{"outcome", "analysis", "label"}``) and ``report`` is read from it.
"""

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from arches.app.models.models import File, ResourceInstance, TileModel
from arches.app.models.tile import Tile
from arches.app.utils.permission_backend import user_can_edit_resource

from manuspectrum.measurement_files import decisions, prepare, staging
from manuspectrum.measurement_files.writer import _index_resource, digest
from manuspectrum.models import MeasurementItem, MeasurementRun
from manuspectrum.observability import metrics
from manuspectrum.utils.edit_log import attribute

logger = logging.getLogger(__name__)

UNDO_FAILED = "undo_failed"
OUTCOME_STATE = {
    "removed": "removed",
    "already_gone": "removed",
    "skipped": "removed",
    "kept_modified": "kept",
    "not_editable": "kept",
}


@dataclass
class UndoResult:
    item_id: str
    state: str
    outcome: str


def undo_transaction_id(run):
    """The edit-log transaction id of the run's undo, derived from the run's own."""
    return uuid.uuid5(run.transaction_id, "undo")


def _is_root(item):
    written = item.written or {}
    return "tiles" in written or "skipped" in written


def _labels(run):
    try:
        return {c.id: c.name for c in prepare.load_snapshot(run)[0]}
    except Exception:
        logger.exception("measurement undo: catalogue snapshot unreadable")
        return {}


def _recorded_tiles(written):
    return [t["id"] for t in written.get("tiles", [])]


def _outcome(written):
    """``(outcome, present tiles)`` of one item against the tiles that exist now."""
    ids = _recorded_tiles(written)
    if not ids:
        return "skipped", []
    present = {str(t.pk): t for t in Tile.objects.filter(pk__in=ids)}
    if not present:
        return "already_gone", []
    digests = written.get("digests", {})
    for tile_id, tile in present.items():
        if digests.get(tile_id) != digest(tile.data):
            return "kept_modified", []
    return "removed", list(present.values())


def _delete_tile(run, tile, tx):
    tile_id = tile.tileid
    tile.delete(index=False, transaction_id=tx)
    attribute(tx, tile_id, run.user, "tile delete")


def _drop_files(file_ids):
    for row in File.objects.filter(pk__in=file_ids):
        row.delete()


def _created_parents(run, analysis_id):
    """``{parent tile id: recorded digest}`` of the parents the run created in *analysis_id*."""
    recorded = {}
    for written in run.items.values_list("written", flat=True):
        parent = (written or {}).get("parent_tile") or {}
        if parent.get("created"):
            recorded[parent["id"]] = (written.get("digests") or {}).get(parent["id"])
    if not recorded:
        return {}
    ours = TileModel.objects.filter(
        pk__in=list(recorded), resourceinstance_id=analysis_id
    ).values_list("pk", flat=True)
    return {str(pk): recorded[str(pk)] for pk in ours}


def _drop_parents(run, analysis_id, tx):
    """Delete the unedited, childless parent tiles the run created; returns whether one went."""
    gone = False
    for parent_id, recorded in _created_parents(run, analysis_id).items():
        if TileModel.objects.filter(parenttile_id=parent_id).exists():
            continue
        parent = Tile.objects.filter(pk=parent_id).first()
        if parent is None or recorded != digest(parent.data):
            continue
        _delete_tile(run, parent, tx)
        gone = True
    return gone


def undo_analysis(run, analysis_id, items):
    """Undo the written *items* of one Analysis in one transaction; returns their ``UndoResult``.

    An item already undone, or no longer ``written``, is skipped. An Analysis
    the run's user can no longer edit keeps its items (``not_editable``).
    """
    analysis_id = str(analysis_id)
    tx = undo_transaction_id(run)
    labels = _labels(run)
    results, counted = [], []
    with transaction.atomic():
        MeasurementRun.objects.select_for_update().filter(pk=run.pk).first()
        row = (
            ResourceInstance.objects.select_for_update(of=("self",))
            .select_related("resource_instance_lifecycle_state")
            .filter(pk=analysis_id)
            .first()
        )
        editable = row is not None and user_can_edit_resource(run.user, resource=row)
        fresh = MeasurementItem.objects.select_for_update(of=("self",)).filter(
            pk__in=[i.pk for i in items], state="written"
        )
        touched = False
        for item in fresh:
            if not _is_root(item):
                continue
            written = item.written or {}
            if row is None:
                outcome, present = _outcome(written)[0], []
            elif not editable:
                outcome, present = "not_editable", []
            else:
                outcome, present = _outcome(written)
            if outcome == "removed":
                files = written.get("files", [])
                File.objects.filter(pk__in=files).update(tile=None)
                for tile in present:
                    _delete_tile(run, tile, tx)
                touched = True
                transaction.on_commit(lambda ids=files: _drop_files(ids))
            state = OUTCOME_STATE[outcome]
            written["undone"] = {
                "outcome": outcome,
                "analysis": analysis_id,
                "label": labels.get(analysis_id, ""),
            }
            item.state, item.written = state, written
            item.save()
            MeasurementItem.objects.filter(
                run=run, state="written", written__with=str(item.pk)
            ).update(state=state)
            results.append(UndoResult(str(item.pk), state, outcome))
            counted.append((item.detected_format, state))
        if row is not None and editable and _drop_parents(run, analysis_id, tx):
            touched = True
        if touched:
            transaction.on_commit(lambda: _index_resource(analysis_id))
    for format_name, state in counted:
        metrics.measurement_file(format_name, state)
    return results


def _analysis_of(item):
    analysis_id = decisions.effective_analysis(item)
    if analysis_id is None:
        for tile_id in _recorded_tiles(item.written or {}):
            tile = TileModel.objects.filter(pk=tile_id).first()
            if tile is not None:
                return tile.resourceinstance_id
    return analysis_id


def _settle_partners(run):
    """Move written partners whose root is gone to their root's state."""
    for partner in run.items.filter(state="written", written__has_key="with"):
        root = run.items.filter(pk=partner.written["with"]).first()
        state = root.state if root and root.state != "written" else "removed"
        MeasurementItem.objects.filter(pk=partner.pk).update(state=state)


def _finish(run):
    _settle_partners(run)
    staging.remove_run(run.id)
    moved = MeasurementRun.objects.filter(pk=run.pk, state="undoing").update(
        state="undone", finished_at=timezone.now()
    )
    if moved:
        metrics.measurement_run("undone")
    run.refresh_from_db()


def undo_run(run, *, chunk=None):
    """Undo one chunk of *run* synchronously; returns whether work remains.

    ``False`` when the run is not ``undoing`` or once nothing is left (the run
    is ``undone``, its staging removed). An Analysis that fails goes to
    ``failed`` with ``error="undo_failed"`` and keeps what it holds.
    """
    run.refresh_from_db()
    if run.state != "undoing":
        return False
    items = [
        i for i in run.items.filter(state="written").order_by("id") if _is_root(i)
    ][: chunk or settings.MEASUREMENT_WRITE_CHUNK]
    groups = defaultdict(list)
    for item in items:
        groups[_analysis_of(item)].append(item)
    for analysis_id, members in groups.items():
        try:
            if analysis_id is None:
                raise ValueError("no analysis")
            undo_analysis(run, analysis_id, members)
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            logger.exception("measurement analysis undo failed")
            ids = [m.pk for m in members]
            MeasurementItem.objects.filter(pk__in=ids, state="written").update(
                state="failed", error=UNDO_FAILED
            )
    if any(_is_root(i) for i in run.items.filter(state="written")):
        return True
    _finish(run)
    return False


def report(run):
    """What the undo did: ``removed`` and ``already_gone`` counts, the items kept and the ones that failed."""
    out = {
        "removed": 0,
        "already_gone": 0,
        "kept_modified": [],
        "not_editable": [],
        "failed": 0,
    }
    for item in run.items.order_by("source_name", "id"):
        undone = (item.written or {}).get("undone")
        if item.state == "failed" and item.error == UNDO_FAILED:
            out["failed"] += 1
        elif not undone:
            continue
        elif undone["outcome"] == "removed":
            out["removed"] += 1
        elif undone["outcome"] == "already_gone":
            out["already_gone"] += 1
        elif undone["outcome"] in ("kept_modified", "not_editable"):
            out[undone["outcome"]].append(
                {
                    "item": str(item.id),
                    "name": item.source_name,
                    "analysis": undone["analysis"],
                    "label": undone["label"],
                }
            )
    return out


def reset_failed(run):
    """Put the items whose undo failed back to ``written`` so a new undo retries them."""
    return run.items.filter(state="failed", error=UNDO_FAILED).update(
        state="written", error=""
    )
