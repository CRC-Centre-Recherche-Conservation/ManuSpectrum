"""Write path of a measurement-files run: it only adds.

``write_run`` takes one chunk of ``prepared`` + ``ready`` items, groups them by
Analysis and calls ``write_analysis`` once per Analysis; the Celery task
``manuspectrum.measurement_write`` and the management command both call it.

Nothing that existed is saved, changed or deleted: the writer creates new
``File`` rows, new tiles (a new ``Data resource`` parent tile when the Analysis
has none) and the ``tile create`` edit-log rows of those tiles, never a
``create`` row and never a ``save`` of an existing tile. Tiles are saved
without user or request (so a Resource Editor who is not a reviewer is not
turned into a provisional edit), under the run's transaction id, validated by
the writer itself, and the author is named on their ``tile create`` rows
afterwards (``utils.edit_log.attribute``).

``write_analysis`` is one transaction holding a lock on the Analysis row. The
Analysis is read again under that lock (still there, still editable) and an
item whose bytes the Analysis already carries (``msSourceSha256`` of a CSV, or
the hash of a stored file) is marked written without writing anything, so two
runs adding the same file to the same Analysis add it once. Each item runs in
its own savepoint: a failure deletes the ``File`` rows it created (Arches'
``post_delete`` removes the bytes), rolls back its tiles and leaves the item
``failed`` with a short ``error`` code, and the other items go on. Each
Analysis that received a tile is indexed once, on commit.

``item.written`` records what an item added, for the undo:
``{"tiles": [{"id", "role"}], "files": [id], "parent_tile": {"id", "created"},
"digests": {tile id: sha1 of the canonical JSON of the stored tile data}}``.
"""

import hashlib
import json
import logging
import mimetypes
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone, translation
from django.utils.translation import gettext

from arches.app.models.models import File, NodeGroup, ResourceInstance, TileModel
from arches.app.models.tile import Tile
from arches.app.utils.permission_backend import user_can_edit_resource

from manuspectrum.constants.licenses import LICENSE_KEY, default_license
from manuspectrum.constants.xy_presets import (
    CONFIG_SOURCE_KEY,
    CONFIG_SOURCE_MANUAL,
    XY_RENDERER_ID,
)
from manuspectrum.measurement_files import catalogue, decisions, prepare, staging
from manuspectrum.measurement_files.converters import csv_name
from manuspectrum.models import MeasurementItem, MeasurementRun
from manuspectrum.utils.edit_log import attribute
from manuspectrum.utils.file_entries import (
    blank_localized_string,
    build_file_entry,
    configured_languages,
)
from manuspectrum.utils.role_links import role_node
from manuspectrum.utils.roles import ROLES

logger = logging.getLogger(__name__)

ALREADY_WRITTEN = "already_written"
UNCONVERTED = prepare.UNCONVERTED
WRITE_ERRORS = (
    "analysis_missing",
    "not_editable",
    "no_analysis",
    "nothing_to_write",
    "pair_incomplete",
    "too_large",
    "bytes_missing",
    "write_failed",
)
"""``error`` codes of an item the writer refused or could not write; the ones
``retry`` puts back. ``prepare`` and ``missing`` belong to the preparation."""


class _Refused(Exception):
    """The item cannot be written; *code* is its ``error``."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass
class ItemResult:
    item_id: str
    state: str
    error: str = ""
    files: int = 0


@dataclass
class _Scope:
    """What one Analysis holds, read under its lock."""

    resource_id: str
    node_id: str
    file_group: str
    parent_group: str | None
    languages: list = field(default_factory=configured_languages)


def digest(data) -> str:
    """SHA-1 of the canonical JSON of a tile's data."""
    return hashlib.sha1(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _index_resource(resource_id):
    from arches.app.models.resource import Resource

    try:
        Resource.objects.get(pk=resource_id).index()
    except Exception:
        logger.exception("measurement write: indexing failed")


def _scope(analysis_id):
    node = role_node(*ROLES["files"])
    parent_group = (
        NodeGroup.objects.filter(pk=node.nodegroup_id)
        .values_list("parentnodegroup_id", flat=True)
        .first()
    )
    return _Scope(
        resource_id=analysis_id,
        node_id=str(node.nodeid),
        file_group=str(node.nodegroup_id),
        parent_group=str(parent_group) if parent_group else None,
    )


def _entries(scope):
    tiles = TileModel.objects.filter(
        resourceinstance_id=scope.resource_id, nodegroup_id=scope.file_group
    )
    return [
        entry
        for tile in tiles
        for entry in ((tile.data or {}).get(scope.node_id) or [])
        if isinstance(entry, dict)
    ]


def _already_there(item, entries, *, own_bytes):
    """Whether the Analysis already holds the bytes of *item*.

    A CSV converted from the same source says so in ``msSourceSha256``;
    *own_bytes* (a raw file kept alone, a lab CSV) is looked up by the hash of
    the stored files.
    """
    if any(e.get("msSourceSha256") == item.sha256 for e in entries):
        return True
    if not own_bytes:
        return False
    return any(
        e.get("file_id") and catalogue.stored_sha256(e["file_id"]) == item.sha256
        for e in entries
    )


def _stored(created, name, data):
    row = File(fileid=uuid.uuid4(), path=ContentFile(data, name=name))
    created.append(row)
    row.save()
    return row


def _description(text_by_language, languages):
    description = {}
    for code in languages:
        slot = blank_localized_string(code)[code]
        slot["value"] = (text_by_language or {}).get(code, "")
        description[code] = slot
    return description


def _display_keys(item):
    if item.display_source in ("chosen", "converter") and item.display_config_id:
        return {
            "rendererConfig": str(item.display_config_id),
            CONFIG_SOURCE_KEY: CONFIG_SOURCE_MANUAL,
            "renderer": XY_RENDERER_ID,
        }
    if item.display_source == "none":
        return {CONFIG_SOURCE_KEY: CONFIG_SOURCE_MANUAL}
    return {}


def _save_tile(run, tile, written, role):
    tile.validate([])
    tile.save(index=False, transaction_id=run.transaction_id)
    attribute(run.transaction_id, tile.tileid, run.user, "tile create")
    stored = TileModel.objects.get(pk=tile.tileid).data
    written["digests"][str(tile.tileid)] = digest(stored)
    if role != "parent":
        written["tiles"].append({"id": str(tile.tileid), "role": role})


def _parent(run, scope, written):
    """The id of the Data resource tile, created once when the Analysis has none.

    Looked up at each call: a parent created by an item whose savepoint was
    rolled back must not be named by the next one.
    """
    if scope.parent_group is None:
        return None
    existing = (
        TileModel.objects.filter(
            resourceinstance_id=scope.resource_id, nodegroup_id=scope.parent_group
        )
        .order_by("sortorder", "tileid")
        .first()
    )
    if existing is not None:
        parent = written.setdefault(
            "parent_tile", {"id": str(existing.tileid), "created": False}
        )
        return parent["id"]
    tile = Tile(
        tileid=uuid.uuid4(),
        resourceinstance_id=scope.resource_id,
        nodegroup_id=scope.parent_group,
        data={},
        sortorder=0,
    )
    _save_tile(run, tile, written, "parent")
    written["parent_tile"] = {"id": str(tile.tileid), "created": True}
    return str(tile.tileid)


def _add_file_tile(
    run, scope, created, written, role, stem, name, data, content_type, **extra
):
    """Store *data* as a new ``File`` and a new file-list tile; returns the entry."""
    row = _stored(created, f"{stem}-{staging.safe_name(name)}", data)
    written["files"].append(str(row.fileid))
    entry = build_file_entry(
        file_id=row.fileid,
        name=name,
        path=row.path.name,
        size=len(data),
        content_type=content_type,
        last_modified=int(time.time() * 1000),
        **extra,
    )
    tile = Tile(
        tileid=uuid.uuid4(),
        resourceinstance_id=scope.resource_id,
        nodegroup_id=scope.file_group,
        parenttile_id=_parent(run, scope, written),
        data={scope.node_id: [entry]},
        sortorder=0,
    )
    _save_tile(run, tile, written, role)
    return entry


def _raw_type(name):
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _is_lone_csv(item):
    return item.origin == "upload" and prepare._is_csv_name(item.source_name)


def _plan(run, item, lab_csv):
    """What an item adds: ``(raw bytes or None, csv spec or None)``.

    The CSV spec is ``(name, bytes, description or None, linked)``; *linked*
    says the CSV names its raw file. A converted CSV over the viewer limit
    leaves the raw file alone (``raw_only``, ``too_large``); any other CSV
    over it is refused.
    """
    read = staging.read
    raw = read(run.id, item.staged_name) if item.origin == "upload" else None
    if lab_csv is not None:
        spec = (lab_csv.source_name, read(run.id, lab_csv.staged_name), None, True)
    elif item.outcome == "csv" and _is_lone_csv(item):
        raw, spec = None, (item.source_name, raw, None, False)
    elif item.outcome == "csv":
        description = json.loads(
            read(run.id, f"{item.id}-{prepare.DESCRIPTION_SUFFIX}").decode("utf-8")
        )
        converted = read(run.id, f"{item.id}-{prepare.CONVERTED_SUFFIX}")
        spec = (csv_name(item.source_name), converted, description, True)
        if len(converted) > settings.SPECTRUM_PREVIEW_MAX_BYTES:
            if raw is None:
                raise _Refused("too_large")
            item.outcome, item.reason = "raw_only", "too_large"
            return raw, None
    elif item.outcome == "raw_only":
        return raw, None
    else:
        raise _Refused("nothing_to_write")
    if len(spec[1]) > settings.SPECTRUM_PREVIEW_MAX_BYTES:
        raise _Refused("too_large")
    return raw, spec


def _raw_license(entries, file_id):
    for entry in entries:
        if str(entry.get("file_id")) == str(file_id) and isinstance(
            entry.get(LICENSE_KEY), dict
        ):
            return dict(entry[LICENSE_KEY]) or None
    return None


def _write_item(run, scope, item, lab_csv):
    """Write one item (and the lab CSV of its pair) in a savepoint; returns its ``written`` record."""
    created = []
    written = {"tiles": [], "files": [], "digests": {}}
    try:
        with transaction.atomic():
            entries = _entries(scope)
            raw, spec = _plan(run, item, lab_csv)
            own = item.origin == "upload" and (spec is None or not spec[3])
            if _already_there(item, entries, own_bytes=own):
                return {"skipped": ALREADY_WRITTEN}
            raw_id = item.source_file_id if item.origin == "stored" else None
            licence = _raw_license(entries, raw_id) if raw_id else None
            stem = str(item.id)
            if raw is not None:
                entry = _add_file_tile(
                    run,
                    scope,
                    created,
                    written,
                    "raw",
                    stem,
                    item.source_name,
                    raw,
                    _raw_type(item.source_name),
                )
                raw_id = entry["file_id"]
            if spec is not None:
                name, data, description, linked = spec
                extra = _display_keys(item)
                if description is not None:
                    extra["description"] = _description(description, scope.languages)
                if linked:
                    extra["msSourceFileId"] = str(raw_id)
                    extra["msSourceSha256"] = item.sha256
                extra[LICENSE_KEY] = licence or default_license()
                _add_file_tile(
                    run,
                    scope,
                    created,
                    written,
                    "csv",
                    stem,
                    name,
                    data,
                    "text/csv",
                    **extra,
                )
            return written
    except BaseException:
        for row in created:
            if File.objects.filter(pk=row.pk).exists():
                row.delete()
            elif row.path and row.path.name:
                row.path.storage.delete(row.path.name)
        raise


def _pair(item):
    """``(raw item, lab CSV item or None)``: a pair is written from its raw item."""
    partner = item.paired_item
    if partner is not None:
        if item.outcome == "csv" and partner.outcome in UNCONVERTED:
            return partner, item
        if item.outcome in UNCONVERTED and partner.outcome == "csv":
            return item, partner
    return item, None


def _fail(ids, error):
    MeasurementItem.objects.filter(pk__in=ids).update(
        state="failed", error=error, claimed_at=None
    )


OPEN = ("claimed", "prepared")


def _write_group(run, scope, item):
    """Write *item* and its pair partner; returns the results and whether a tile was added."""
    root, lab = _pair(item)
    locked = {
        m.pk: m
        for m in MeasurementItem.objects.select_for_update().filter(
            pk__in=[m.pk for m in (root, lab) if m is not None]
        )
    }
    root = locked[root.pk]
    lab = locked[lab.pk] if lab is not None else None
    members = [m for m in (root, lab) if m is not None]
    if root.state == "written":
        return [], False
    if any(m.state not in OPEN for m in members):
        _fail([m.pk for m in members], "pair_incomplete")
        return [
            ItemResult(str(m.pk), "failed", "pair_incomplete") for m in members
        ], False
    try:
        written = _write_item(run, scope, root, lab)
    except _Refused as refused:
        _fail([m.pk for m in members], refused.code)
        return [ItemResult(str(m.pk), "failed", refused.code) for m in members], False
    except SoftTimeLimitExceeded:
        raise
    except Exception:
        logger.exception("measurement item write failed")
        _fail([m.pk for m in members], "write_failed")
        return [ItemResult(str(m.pk), "failed", "write_failed") for m in members], False
    results = []
    for member in members:
        member.state, member.error, member.claimed_at = "written", "", None
        member.written = written if member is root else {"with": str(root.pk)}
        member.save()
        results.append(
            ItemResult(
                str(member.pk), "written", files=len(member.written.get("files", []))
            )
        )
    return results, bool(written.get("tiles"))


def write_analysis(run, analysis_id, items):
    """Add the files of *items* to the Analysis *analysis_id* in one transaction; returns their ``ItemResult``.

    The run row is locked first (the undo takes the same locks in the same
    order: run, then Analysis); when the run is no longer ``writing`` nothing is
    written and the claimed items go back to ``prepared``. An item refused or
    failed is ``failed`` with its ``error``; the others are ``written``. The Analysis is indexed once on commit when it received a tile.
    """
    analysis_id = str(analysis_id)
    ids = [i.pk for i in items]
    results, touched = [], False
    with transaction.atomic():
        state = (
            MeasurementRun.objects.select_for_update()
            .filter(pk=run.pk)
            .values_list("state", flat=True)
            .first()
        )
        if state != "writing":
            _release(items)
            return []
        row = (
            ResourceInstance.objects.select_for_update(of=("self",))
            .select_related("resource_instance_lifecycle_state")
            .filter(pk=analysis_id)
            .first()
        )
        if row is None:
            error = "analysis_missing"
        elif not user_can_edit_resource(run.user, resource=row):
            error = "not_editable"
        else:
            error = ""
        if error:
            _fail(ids, error)
            return [ItemResult(str(i), "failed", error) for i in ids]
        scope = _scope(analysis_id)
        fresh = {
            i.pk: i
            for i in MeasurementItem.objects.select_for_update(of=("self",))
            .select_related("paired_item")
            .filter(pk__in=ids)
        }
        for item_id in ids:
            item = fresh.get(item_id)
            if item is not None and item.state in OPEN:
                found, added = _write_group(run, scope, item)
                results += found
                touched = touched or added
        if touched:
            transaction.on_commit(lambda: _index_resource(analysis_id))
    return results


def _release(items):
    MeasurementItem.objects.filter(
        pk__in=[i.pk for i in items], state="claimed"
    ).update(state="prepared", claimed_at=None)


def _remaining(run):
    return run.items.filter(
        Q(state="claimed") | Q(state="prepared", decision="ready")
    ).exists()


def _stop_requested(run):
    return MeasurementRun.objects.filter(pk=run.pk, stop_requested=True).exists()


def _message(run):
    items = run.items.filter(state="written")
    files = analyses = 0
    touched = set()
    for item in items:
        files += len((item.written or {}).get("files", []))
        if (item.written or {}).get("tiles"):
            touched.add(decisions.effective_analysis(item))
    analyses = len(touched)
    failed = run.items.filter(state="failed").count()
    with translation.override(run.language):
        return gettext(
            "Measurement files - added: %(files)d, analyses: %(analyses)d, failed: %(failed)d."
        ) % {"files": files, "analyses": analyses, "failed": failed}


def _finish(run):
    from arches.app.tasks import notify_completion

    message = _message(run)
    MeasurementRun.objects.filter(pk=run.pk, state="writing").update(
        state="written", finished_at=timezone.now(), stop_requested=False
    )
    run.refresh_from_db()
    notify_completion(message, run.user)


def write_run(run, *, chunk=None):
    """Write one chunk of *run* synchronously; returns whether items remain.

    ``False`` when the run is not ``writing``, when a stop was requested (the
    run goes back to ``review``, written items kept) or once nothing is left
    (the run is ``written`` and its owner gets a bell notice). The stop is
    read between Analyses; the items of the Analyses not reached go back to
    ``prepared``.
    """
    run.refresh_from_db()
    if run.state != "writing":
        return False
    if _stop_requested(run):
        return _pause(run)
    items = prepare.claim(
        run, ("prepared",), chunk or settings.MEASUREMENT_WRITE_CHUNK, decision="ready"
    )
    groups = defaultdict(list)
    for item in items:
        groups[decisions.effective_analysis(item)].append(item)
    pending = list(groups.items())
    for index, (analysis_id, members) in enumerate(pending):
        if index and _stop_requested(run):
            _release([item for _, rest in pending[index:] for item in rest])
            return _pause(run)
        try:
            if analysis_id is None:
                _fail([m.pk for m in members], "no_analysis")
            else:
                write_analysis(run, analysis_id, members)
        except SoftTimeLimitExceeded:
            _release([item for _, rest in pending[index:] for item in rest])
            raise
        except Exception:
            logger.exception("measurement analysis write failed")
            _fail([m.pk for m in members], "write_failed")
    if _remaining(run):
        return True
    _finish(run)
    return False


def _pause(run):
    MeasurementRun.objects.filter(pk=run.pk, state="writing").update(
        state="review", stop_requested=False
    )
    run.refresh_from_db()
    return False
