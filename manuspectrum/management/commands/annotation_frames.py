"""Check, stamp, verify and unstamp the image frame of the annotation zones already stored.

``check`` counts the zones per stamp state (the gauge's counts: ``data`` only,
provisional edits not counted) and lists the images of the unstamped zones of
``data``; it reads the database only. ``stamp`` gives each unstamped zone the
frame it was drawn in (``frames.STAMP_KEYS``). A feature of the Biblissima
import's location node (``COMP_LOCATION_DOC_NODE``) that is the whole-page
rectangle the import wrote before stamping existed, at any power-of-two unit
(32 before 1.0.3, the read or assumed unit since), gets ``import-legacy``; any
other zone gets ``frame_writes.frame_for_service`` of its image, one call per
distinct image service and manifest, the registered manifests loaded once per
run. Each image description is read at most once per pass, again over the
network unless this server read it within ``IIIF_IMAGE_INFO_STAMP_MAX_AGE``
seconds. An image that cannot be read is skipped and listed. A zone already
carrying a valid stamp is never touched.

One failed read marks its whole host down for ``IIIF_IMAGE_INFO_DOWN_TTL``
seconds, and every later image of that host is then skipped. With ``--apply``
the services left ``UNAVAILABLE`` (a failed read or a host marked down; never a
``REFUSED`` one or one without a registered size) are therefore planned again in
up to ``--retries`` further passes (default 2), each after waiting until the
marks have expired (``RETRY_WAIT_MAX`` bounds the wait). Only those services
are read again, and their zones are written through the same batches and
journal. The services still unavailable after the last pass are listed: run the
command again later, with a new journal. A dry run waits for nothing and only
reports what a retry would read. Ctrl-C during a wait stops the retrying, keeps
what is written, prints the summary and the reindex reminder, and exits non-zero.

``stamp`` is dry by default; the dry run reads image descriptions over the
network (and fills the image-info cache) but writes nothing. With ``--apply``
a ``--journal`` path is required and created (never overwritten) before
anything is read; the file is removed again when it is empty. The
writes go by batches of tiles under ``transaction.atomic()``: the tiles are
locked in primary-key order and re-read, and a zone is stamped only when it is
still unstamped, on the same canvas and with the geometry it had when it was
planned (a legacy zone is also still the whole-page rectangle). The write is an
``.update()`` of the tile's ``data`` and ``provisionaledits`` (the whole
value, as ``Tile.save`` writes it): no edit log, no per-tile indexing, one
``es reindex_database`` at the end. Every changed zone is appended to a JSONL
journal, ``{tile, node, provisional, feature, canvas, digest, before, after}``:
``before`` and ``after`` are the feature's ``properties``, ``digest`` its
``frames.geometry_digest`` and ``provisional`` the user id of a provisional
edit, or null for the tile's ``data``. The journal line is written and
fsynced inside the transaction, after the update, so a failed journal write
rolls the batch back. The lines of a batch whose COMMIT itself failed stay in
the journal: ``unstamp`` lists them « changed since » and leaves them alone.
The guarded ``.update()`` fires no ``Tile`` signal. A full ``Tile.save`` that
read the tile before a batch committed can write its own copy back over the
stamp; the zone then follows that save's own stamping rule
(``frames.stamp_collection``).

``verify`` compares the stamp of every stamped zone (``data`` and provisional
edits) with the live frame of its image service, one image-description read per
service and run (``Measures``): same, different, refused (a 403 or an answer
that is not an image description), unreadable (a failed read or a host marked
down; never a pass: the exit status is 1), or ``import-legacy`` (counted apart,
never different). A host that refuses this server is measured in a browser:
``--refused-out DIR`` writes one console script per such host
(``iiif/frame_check.js``), whose copied JSON ``--frames FILE`` reads
(``iiif.frame_scope``); the file answers only for a service the server could not
read. With ``--apply --journal PATH`` the only write is a requalification: an
``estimated`` stamp equal to the measured frame gets that frame's ``msFrame``
source, through the same locked, guarded batches and journal as ``stamp``.

``unstamp --journal PATH`` puts every ``before`` back, only where the zone's
canvas, geometry digest and properties still equal the journaled ones; a zone
changed since is listed and left alone. Restoring the whole ``properties``
object gives the stored ``data`` back value for value (jsonb keeps no key
order). A journal line may carry ``geometry_before`` (the feature's geometry
before a verb that moves zones): ``unstamp`` puts it back with ``before``. A
line whose feature, on the same canvas, already has the digest of
``geometry_before`` (a stale editor save puts the old geometry back and the
save's own stamping rule restamps it) is listed as « geometry reverted by a later save ». Dry by
default as well.
"""

import copy
import errno
import json
import logging
import os
import shlex
import time
import uuid
from datetime import datetime
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arches.app.models.models import EditLog, Node, TileModel

from manuspectrum.constants.biblissima import COMP_LOCATION_DOC_NODE
from manuspectrum.iiif import frame_scope, frame_writes, frames, units
from manuspectrum.iiif.units import Frame
from manuspectrum.observability import activity
from manuspectrum.views.explorer.values import rewrite_legacy_url

logger = logging.getLogger(__name__)

LEGACY_SIZE = (4000, 5000)
BATCH = 200
RETRIES = 2
RETRY_WAIT_MAX = 300
REFUSED_STATE = "refused"
UNREADABLE_STATE = "unreadable"
CHECK_SCRIPT = Path(frames.__file__).with_name("frame_check.js")
BUCKETS = (
    ("same", "same"),
    ("different", "different"),
    (REFUSED_STATE, "refused or not an image description"),
    (UNREADABLE_STATE, "unreadable"),
    ("legacy", "import-legacy"),
)


def annotation_nodes():
    """``{node id: nodegroup id}`` of the annotation nodes, ids as strings."""
    return {
        str(node_id): group
        for node_id, group in Node.objects.filter(datatype="annotation").values_list(
            "nodeid", "nodegroup_id"
        )
    }


def tiles_of(nodes, only=None):
    """``(tile id, data, provisionaledits)`` of every tile of the annotation nodegroups (those in *only* when given)."""
    rows = TileModel.objects.filter(nodegroup_id__in=set(nodes.values()))
    if only is not None:
        rows = rows.filter(pk__in=only)
    return rows.values_list("tileid", "data", "provisionaledits").iterator(
        chunk_size=500
    )


def collections_of(data, edits, nodes):
    """``[(provisional user id or None, node id, collection)]`` of the annotation collections of a tile."""
    found = []
    holder = SimpleNamespace(data=data, provisionaledits=edits)
    for user_id, values in frame_writes.holders(holder):
        for node_id, collection in values.items():
            if str(node_id) in nodes:
                found.append((user_id, str(node_id), collection))
    return found


@dataclass(frozen=True)
class StampedZone:
    """A feature carrying a valid stamp, with where it is stored."""

    tile_id: uuid.UUID
    node_id: str
    user_id: str | None
    feature_id: str
    canvas: str
    digest: str
    frame: Frame
    geometry: dict | None = field(default=None, compare=False, repr=False)


def stamped_zones(nodes, service=None, host=None, tiles=None):
    """Every feature with a valid stamp in the ``data`` and provisional edits of the annotation tiles (those in *tiles* when given).

    *service* keeps the zones of that canvas (``rewrite_legacy_url`` and no
    trailing slash); *host* those whose canvas host equals it, case folded.
    A feature without a usable id or canvas is never yielded.
    """
    if service is not None:
        service = rewrite_legacy_url(service).rstrip("/")
    if host is not None:
        host = host.lower()
    for tile_id, data, edits in tiles_of(nodes, tiles):
        for user_id, node_id, collection in collections_of(data, edits, nodes):
            features = collection.get("features")
            for feature in features if isinstance(features, list) else []:
                frame = frames.frame_of(feature)
                fid = feature.get("id") if isinstance(feature, dict) else None
                canvas = frames.canvas_of(feature)
                if frame is None or not canvas or not frames.valid_id(fid):
                    continue
                if service is not None and canvas != service:
                    continue
                if host is not None and (urlsplit(canvas).hostname or "") != host:
                    continue
                yield StampedZone(
                    tile_id,
                    node_id,
                    user_id,
                    fid,
                    canvas,
                    frames.geometry_digest(feature.get("geometry")),
                    frame,
                    feature.get("geometry"),
                )


def whole_page(frame):
    """The rectangle the Biblissima import wrote for a whole page of *frame*'s size."""
    w, h = frame.width / frame.unit, frame.height / frame.unit
    return {
        "type": "Polygon",
        "coordinates": [[[0, 0], [w, 0], [w, -h], [0, -h], [0, 0]]],
    }


def _legacy_frame(feature, node_id, plan):
    """The ``import-legacy`` frame of a whole-page zone the Biblissima import wrote, or None.

    The page is the registered canvas size, else the import's 4000 x 5000
    default, else the size of the image description (read once per image
    service); a size no ``Frame`` accepts is passed over. The unit is the
    power of two at which that page is exactly the stored rectangle
    (``whole_page``, compared by ``frames.same_geometry``).
    """
    if node_id != COMP_LOCATION_DOC_NODE:
        return None
    manifest = feature["properties"].get("manifest")
    canvas = frames.canvas_of(feature)
    registered = plan.size_of(manifest if isinstance(manifest, str) else None, canvas)
    sizes = ([tuple(registered)] if registered else []) + [LEGACY_SIZE]
    for width, height in sizes:
        frame = _page_frame(feature, width, height)
        if frame:
            return frame
    info = plan.info(canvas)
    return _page_frame(feature, info.width, info.height) if info else None


def _page_frame(feature, width, height):
    """The ``import-legacy`` frame of a *width* x *height* page whose whole-page rectangle at some unit is *feature*'s geometry, or None."""
    unit = 1
    while unit <= units.MAX_UNIT:
        try:
            frame = Frame(unit, width, height, "import-legacy")
        except ValueError:
            return None
        if frames.same_geometry(feature.get("geometry"), whole_page(frame)):
            return frame
        unit *= 2
    return None


class Plan:
    """What ``stamp`` would write, and what it could not resolve."""

    def __init__(self, service=None, only=None, size_of=None):
        self.service = service
        self.only = only
        self.tiles_of_skipped = defaultdict(set)
        self.last_failure = None
        self.entries = defaultdict(list)
        self.frames = {}
        self.size_of = size_of or frame_writes.size_lookup()
        self._reads = {}
        self.skipped = Counter()
        self.already = 0
        self.unusable = 0

    def read(self, service):
        """``frame_writes.fresh_info`` of *service*, once per pass."""
        if service not in self._reads:
            self._reads[service] = frame_writes.fresh_info(service)
            if self._reads[service] == units.UNAVAILABLE:
                self.last_failure = time.monotonic()
        return self._reads[service]

    def unavailable(self):
        """The skipped services whose read was ``UNAVAILABLE`` (a retry may resolve them)."""
        return {c for c in self.skipped if self._reads.get(c) == units.UNAVAILABLE}

    def info(self, service):
        """The ``ImageInfo`` of *service* (``read``), or None."""
        found = self.read(service)
        return found if isinstance(found, units.ImageInfo) else None

    def frame(self, service, manifest):
        key = (service, manifest)
        if key not in self.frames:
            self.frames[key] = frame_writes.frame_for_service(
                service, manifest, service, size_of=self.size_of, info_of=self.read
            )
        return self.frames[key]


def plan_stamps(nodes, service=None, only=None, size_of=None, tiles=None):
    """A ``Plan`` for every unstamped zone of the database; reads image descriptions, writes nothing.

    A retry pass names the image services *only* to plan, the *tiles* that
    held their skipped zones and the *size_of* lookup of the first pass.
    """
    plan = Plan(service, only, size_of)
    for tile_id, data, edits in tiles_of(nodes, tiles):
        for user_id, node_id, collection in collections_of(data, edits, nodes):
            for feature in collection["features"]:
                if not isinstance(feature, dict):
                    plan.unusable += 1
                    continue
                if frames.frame_of(feature):
                    plan.already += 1
                    continue
                props = feature.get("properties")
                fid = feature.get("id")
                canvas = frames.canvas_of(feature)
                if not (isinstance(props, dict) and frames.valid_id(fid) and canvas):
                    plan.unusable += 1
                    continue
                if plan.service and canvas != plan.service:
                    continue
                if plan.only is not None and canvas not in plan.only:
                    continue
                frame = _legacy_frame(feature, node_id, plan)
                legacy = frame is not None
                if frame is None:
                    manifest = props.get("manifest")
                    frame = plan.frame(
                        canvas, manifest if isinstance(manifest, str) else None
                    )
                if frame is None:
                    plan.skipped[canvas] += 1
                    plan.tiles_of_skipped[canvas].add(tile_id)
                    continue
                plan.entries[tile_id].append(
                    (
                        node_id,
                        user_id,
                        fid,
                        frames.geometry_digest(feature.get("geometry")),
                        canvas,
                        frame,
                        legacy,
                    )
                )
    return plan


def _matching(value, node_id, fid, digest, canvas, legacy_frame):
    """The still-unstamped features of *value*'s collection *node_id* the plan entry names.

    A legacy entry (*legacy_frame* set) also needs the import's node and the
    whole-page rectangle of that frame.
    """
    return [
        f
        for f in frame_writes._features_of(value, node_id, fid, digest)
        if frames.canvas_of(f) == canvas
        and (
            legacy_frame is None
            or (
                node_id == COMP_LOCATION_DOC_NODE
                and frames.same_geometry(f.get("geometry"), whole_page(legacy_frame))
            )
        )
    ]


def apply_batch(batch, journal):
    """Stamp the planned zones of the tiles of *batch* (``[(tile id, entries)]``); return how many were written.

    The tiles are locked and re-read; the journal lines are appended and
    fsynced before the batch commits, and cut off again if that fails.
    *journal* is the file descriptor of ``open_journal``.
    """
    written, all_lines = 0, []
    with transaction.atomic():
        rows = _locked_rows(tile_id for tile_id, _ in batch)
        for tile_id, entries in batch:
            if tile_id not in rows:
                continue
            data, edits = copy.deepcopy(rows[tile_id][1]), copy.deepcopy(
                rows[tile_id][2]
            )
            lines, changes = [], {}
            for node_id, user_id, fid, digest, canvas, frame, legacy in entries:
                value = frame_writes._value_of(data, edits, user_id)
                for feature in _matching(
                    value, node_id, fid, digest, canvas, frame if legacy else None
                ):
                    before = copy.deepcopy(feature["properties"])
                    feature["properties"].update(frame.stamp())
                    lines.append(
                        {
                            "tile": str(tile_id),
                            "node": node_id,
                            "provisional": user_id,
                            "feature": fid,
                            "canvas": canvas,
                            "digest": digest,
                            "before": before,
                            "after": copy.deepcopy(feature["properties"]),
                        }
                    )
                    changes["data" if user_id is None else "provisionaledits"] = (
                        data if user_id is None else edits
                    )
            if lines:
                TileModel.objects.filter(pk=tile_id).update(**changes)
                all_lines += lines
                written += len(lines)
        _append(journal, all_lines)
    return written


class Measures:
    """The live frame of each image service, read once per service and run.

    ``frame(service)`` is the ``read`` ``Frame`` when this server reads the
    image description; otherwise, when *frames_file* names the service, the
    ``browser`` ``Frame`` of its entry; otherwise ``"refused"`` (a refusal or an
    answer that is not an image description) or ``"unreadable"`` (a failed read
    or a host marked down).
    """

    def __init__(self, frames_file=None):
        self.frames_file = frames_file
        self._frames = {}

    def frame(self, service):
        if service not in self._frames:
            self._frames[service] = self._measure(service)
        return self._frames[service]

    def _measure(self, service):
        info = frame_writes.fresh_info(service)
        if isinstance(info, units.ImageInfo):
            try:
                return units.frame_from_info(info, "read")
            except ValueError:
                return REFUSED_STATE
        listed = self.frames_file.frames.get(service) if self.frames_file else None
        if listed is not None:
            try:
                return units.frame_from_info(listed, "browser")
            except ValueError:
                pass
        return UNREADABLE_STATE if info == units.UNAVAILABLE else REFUSED_STATE


def _size_of(frame):
    return f"{frame.unit}x{frame.width}x{frame.height}"


def _host_of(service):
    return urlsplit(service).hostname or ""


def _matching_stamped(value, node_id, fid, digest, canvas, frame):
    """The features of *value*'s collection *node_id* still carrying the planned *frame* on the planned canvas and geometry."""
    collection = value.get(node_id) if isinstance(value, dict) else None
    if not frame_writes._is_collection(collection):
        return []
    return [
        f
        for f in collection["features"]
        if isinstance(f, dict)
        and f.get("id") == fid
        and isinstance(f.get("properties"), dict)
        and frames.frame_of(f) == frame
        and frames.canvas_of(f) == canvas
        and frames.geometry_digest(f.get("geometry")) == digest
    ]


def _locked_rows(tile_ids):
    """``{tile id: (tile id, data, provisionaledits)}`` of *tile_ids*, locked in primary-key order."""
    return {
        row[0]: row
        for row in TileModel.objects.select_for_update()
        .filter(pk__in=list(tile_ids))
        .order_by("pk")
        .values_list("tileid", "data", "provisionaledits")
    }


def _guarded_batch(batch, journal, change):
    """Change the planned zones of the tiles of *batch* (``[(tile id, entries)]``) under lock; return ``(written, [(tile id, feature id)] changed since)``.

    An entry is ``(node id, user id, feature id, digest, canvas, stamped
    frame, payload)``. A feature is changed only while it still carries the
    stamped frame, canvas and geometry digest; ``change(feature, payload)``
    mutates it, or raises ValueError before touching it, which lists the zone
    as changed since. The journal lines (``digest`` is the digest after the
    change, ``geometry_before`` the geometry when the change moved it) are
    appended and fsynced before the batch commits.
    """
    written, changed, all_lines = 0, [], []
    with transaction.atomic():
        rows = _locked_rows(tile_id for tile_id, _ in batch)
        for tile_id, entries in batch:
            if tile_id not in rows:
                changed.extend((tile_id, entry[2]) for entry in entries)
                continue
            data, edits = copy.deepcopy(rows[tile_id][1]), copy.deepcopy(
                rows[tile_id][2]
            )
            lines, changes = [], {}
            for node_id, user_id, fid, digest, canvas, frame, payload in entries:
                value = frame_writes._value_of(data, edits, user_id)
                found = _matching_stamped(value, node_id, fid, digest, canvas, frame)
                if not found:
                    changed.append((tile_id, fid))
                for feature in found:
                    before = copy.deepcopy(feature["properties"])
                    geometry_before = copy.deepcopy(feature.get("geometry"))
                    try:
                        change(feature, payload)
                    except ValueError:
                        changed.append((tile_id, fid))
                        continue
                    line = {
                        "tile": str(tile_id),
                        "node": node_id,
                        "provisional": user_id,
                        "feature": fid,
                        "canvas": canvas,
                        "digest": frames.geometry_digest(feature.get("geometry")),
                        "before": before,
                        "after": copy.deepcopy(feature["properties"]),
                    }
                    if feature.get("geometry") != geometry_before:
                        line["geometry_before"] = geometry_before
                    lines.append(line)
                    changes["data" if user_id is None else "provisionaledits"] = (
                        data if user_id is None else edits
                    )
            if lines:
                TileModel.objects.filter(pk=tile_id).update(**changes)
                all_lines += lines
                written += len(lines)
        _append(journal, all_lines)
    return written, changed


def requalify_batch(batch, journal):
    """Give the planned zones of the tiles of *batch* the ``msFrame`` of their measure (the entry's payload); return ``(written, changed since)`` as ``_guarded_batch``."""

    def change(feature, source):
        feature["properties"]["msFrame"] = source

    return _guarded_batch(batch, journal, change)


def rebase_batch(batch, journal):
    """Carry the planned zones of the tiles of *batch* to the live frame; return ``(written, changed since)`` as ``_guarded_batch``.

    An entry's payload is ``(target frame, fx, fy)``: the geometry is scaled
    and the stamp replaced by the target's.
    """

    def change(feature, payload):
        target, fx, fy = payload
        geometry = frame_scope.scaled_geometry(feature.get("geometry"), fx, fy)
        feature["geometry"] = geometry
        feature["properties"].update(target.stamp())

    return _guarded_batch(batch, journal, change)


def relabel_batch(batch, journal):
    """Give the planned zones of the tiles of *batch* the stamp of their target frame (the entry's payload), geometry untouched; return ``(written, changed since)`` as ``_guarded_batch``."""

    def change(feature, target):
        feature["properties"].update(target.stamp())

    return _guarded_batch(batch, journal, change)


def _append(fd, lines):
    """Write *lines* to the journal *fd* and fsync it; on a failure the file is cut back to where it was and the error is raised.

    The descriptor is unbuffered (``os.write``), so a failed write leaves
    nothing in user space to flush again at the cut or at the close.
    """
    start = os.fstat(fd).st_size
    try:
        data = "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines)
        view = memoryview(data.encode("utf-8"))
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError(errno.ENOSPC, "the journal accepts no more bytes")
            view = view[count:]
        os.fsync(fd)
    except BaseException:
        try:
            os.ftruncate(fd, start)
            os.fsync(fd)
        except OSError:
            pass
        raise


def restore_batch(batch, lines_by_tile, apply_changes=True):
    """Put the journaled ``before`` back on the tiles of *batch*; return ``(restored, [(line, reason)])``.

    Without *apply_changes* nothing is locked or written: the count is what
    would be restored.
    """
    restored, changed = 0, []
    with transaction.atomic():
        rows = {
            row[0]: row
            for row in (
                TileModel.objects.select_for_update()
                if apply_changes
                else TileModel.objects
            )
            .filter(pk__in=batch)
            .order_by("pk")
            .values_list("tileid", "data", "provisionaledits")
        }
        for tile_id in batch:
            lines = lines_by_tile[tile_id]
            if tile_id not in rows:
                changed.extend((line, "tile gone") for line in lines)
                continue
            data, edits = copy.deepcopy(rows[tile_id][1]), copy.deepcopy(
                rows[tile_id][2]
            )
            changes = {}
            for line in lines:
                value = frame_writes._value_of(data, edits, line["provisional"])
                collection = (
                    value.get(line["node"]) if isinstance(value, dict) else None
                )
                target = next(
                    (
                        f
                        for f in (
                            collection["features"]
                            if frame_writes._is_collection(collection)
                            else []
                        )
                        if isinstance(f, dict)
                        and f.get("id") == line["feature"]
                        and f.get("properties") == line["after"]
                        and frames.canvas_of(f) == line["canvas"]
                        and frames.geometry_digest(f.get("geometry")) == line["digest"]
                    ),
                    None,
                )
                if target is None:
                    changed.append((line, _unmatched_reason(line, value)))
                    continue
                target["properties"] = line["before"]
                if "geometry_before" in line:
                    target["geometry"] = line["geometry_before"]
                restored += 1
                changes[
                    "data" if line["provisional"] is None else "provisionaledits"
                ] = (data if line["provisional"] is None else edits)
            if changes and apply_changes:
                TileModel.objects.filter(pk=tile_id).update(**changes)
    return restored, changed


def _unmatched_reason(line, value):
    """Why the zone of journal *line* is not restored: a later save put the geometry of ``geometry_before`` back (whatever stamp it then carries), or it changed since."""
    if "geometry_before" in line:
        collection = value.get(line["node"]) if isinstance(value, dict) else None
        features = (
            collection["features"] if frame_writes._is_collection(collection) else []
        )
        digest = frames.geometry_digest(line["geometry_before"])
        if any(
            isinstance(f, dict)
            and f.get("id") == line["feature"]
            and frames.canvas_of(f) == line["canvas"]
            and frames.geometry_digest(f.get("geometry")) == digest
            for f in features
        ):
            return "geometry reverted by a later save"
    return "changed since"


def _journal_line(text):
    """The decoded journal line *text*; ValueError when it lacks a field or has one of the wrong type."""
    line = json.loads(text)
    if not isinstance(line, dict):
        raise ValueError("not an object")
    for key in ("tile", "node", "canvas", "digest"):
        if not isinstance(line[key], str):
            raise ValueError(f"{key} is not a string")
    uuid.UUID(line["tile"])
    if not frames.valid_id(line["feature"]):
        raise ValueError("feature is not an id")
    if line["provisional"] is not None and not isinstance(line["provisional"], str):
        raise ValueError("provisional is neither null nor a string")
    for key in ("before", "after"):
        if not isinstance(line[key], dict):
            raise ValueError(f"{key} is not an object")
    if "geometry_before" in line and not isinstance(line["geometry_before"], dict):
        raise ValueError("geometry_before is not an object")
    return line


def read_journal(path, warn=logger.warning):
    """The lines of the JSONL journal *path*, grouped by tile id (as ``uuid.UUID``).

    A terminated line that is not valid raises ``CommandError`` naming its
    number. An unterminated last segment (a write cut short by a crash) belongs
    to a batch that never committed, as a committed batch ends with a newline
    fsynced before the commit: it is skipped and *warn* is called with a message
    naming its line, unless it parses as a journal line (an editor may have
    dropped the final newline of a complete journal), which is kept.
    """
    grouped = defaultdict(list)
    number = 0
    try:
        with open(path, encoding="utf-8", newline="\n") as handle:
            for number, text in enumerate(handle, 1):
                terminated = text.endswith("\n")
                if not text.strip():
                    continue
                try:
                    line = _journal_line(text)
                except (ValueError, KeyError, TypeError) as error:
                    if not terminated:
                        warn(
                            f"{path}: line {number} is cut short (an unfinished write); skipped"
                        )
                        continue
                    raise CommandError(
                        f"{path}: line {number} is not a journal line ({error})"
                    ) from error
                grouped[uuid.UUID(line["tile"])].append(line)
    except UnicodeDecodeError as error:
        raise CommandError(
            f"{path}: not UTF-8 text (at or after line {number + 1}); the journal is unreadable"
        ) from error
    except OSError as error:
        raise CommandError(f"cannot read the journal: {error}") from error
    return grouped


def open_journal(path):
    """The file descriptor of the new journal *path* (append-only, never an existing file); ``CommandError`` when it cannot be created.

    The parent directory is fsynced so the new file survives a crash.
    """
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o640)
    except OSError as error:
        raise CommandError(f"cannot create the journal {path}: {error}") from error
    try:
        directory = os.open(os.path.dirname(path) or ".", os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as error:
        os.close(fd)
        try:
            os.unlink(path)
        except OSError:
            pass
        raise CommandError(f"cannot create the journal {path}: {error}") from error
    return fd


def _close_journal(fd, path):
    """Close the journal *fd*, and remove the file when it is empty; never raises.

    A journal holding a line is kept whatever happened: a batch may have
    committed without the caller having seen it return. Returns True when the
    file was kept with content.
    """
    try:
        empty = os.fstat(fd).st_size == 0
    except OSError:
        empty = False
    try:
        os.close(fd)
    except OSError:
        pass
    if empty:
        try:
            os.unlink(path)
        except OSError:
            pass
    return not empty


def _since_of(text):
    """Midnight local time (naive Paris wall clock, as ``EditLog.timestamp``) of the day *text* (``YYYY-MM-DD``); ``CommandError`` otherwise."""
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError as error:
        raise CommandError("--since must be a date, YYYY-MM-DD") from error


def _zone_keys(value):
    """``{(node id, feature id, geometry digest)}`` of the annotation features of a tile value (a node id -> collection object)."""
    found = set()
    for node_id, collection in (value if isinstance(value, dict) else {}).items():
        if frame_writes._is_collection(collection):
            for feature in collection["features"]:
                fid = feature.get("id") if isinstance(feature, dict) else None
                if frames.valid_id(fid):
                    found.add(
                        (
                            str(node_id),
                            fid,
                            frames.geometry_digest(feature.get("geometry")),
                        )
                    )
    return found


def values_before(tile_ids, since):
    """``{(tile id, user id or None): zone keys}``: what each tile held before *since*, for the tiles an edit log row dates from *since* on.

    One ``EditLog`` query. The value before the date is the ``oldvalue`` of the
    earliest row of the tile at or after it (its ``data``), and, for a
    provisional edit, the ``oldprovisionalvalue`` of the earliest such row of
    that user (the edit's own value; none when the user's first edit is that
    row). A tile or user with no such row is absent: nothing changed since,
    the current value is the old one.
    """
    found = {}
    rows = (
        EditLog.objects.filter(
            tileinstanceid__in=[str(tile_id) for tile_id in tile_ids],
            timestamp__gte=since,
        )
        .order_by("timestamp")
        .values_list(
            "tileinstanceid", "provisional_userid", "oldvalue", "oldprovisionalvalue"
        )
        .iterator(chunk_size=200)
    )
    for tile_text, user, old, old_provisional in rows:
        tile_id = uuid.UUID(tile_text)
        found.setdefault((tile_id, None), _zone_keys(old))
        if user not in (None, ""):
            found.setdefault((tile_id, str(user)), _zone_keys(old_provisional))
    return found


def _script_name(host):
    """The file name of the console script of *host*."""
    return "".join(c if c.isalnum() or c in ".-" else "_" for c in host) + ".js"


class Command(BaseCommand):
    help = (
        "Check, stamp, verify, rebase, relabel (dry by default) or unstamp the image frame of "
        "stored annotation zones."
    )

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)
        sub.add_parser("check", help="Count the zones per stamp state (read-only).")
        stamp = sub.add_parser("stamp", help="Stamp the unstamped zones.")
        stamp.add_argument("--apply", action="store_true", help="Write the stamps.")
        stamp.add_argument(
            "--journal",
            help="New JSONL journal file, required with --apply (a path the process can write, e.g. under the media directory).",
        )
        stamp.add_argument("--service", help="Only the zones of this image service.")
        stamp.add_argument(
            "--batch", type=int, default=BATCH, help="Tiles per transaction."
        )
        stamp.add_argument(
            "--retries",
            type=int,
            default=RETRIES,
            help="Further passes over the services left unavailable, each after the host-down marks expired (0: none).",
        )
        verify = sub.add_parser(
            "verify", help="Compare the stored frames with the image hosts."
        )
        verify.add_argument("--service", help="Only the zones of this image service.")
        verify.add_argument("--host", help="Only the zones of this image host.")
        verify.add_argument(
            "--frames", help="Frames file measured in a browser (frame_check.js)."
        )
        verify.add_argument(
            "--refused-out",
            help="Directory receiving one console script per host that refuses this server.",
        )
        verify.add_argument(
            "--apply",
            action="store_true",
            help="Requalify the estimates equal to the measure.",
        )
        verify.add_argument(
            "--journal", help="New JSONL journal file, required with --apply."
        )
        verify.add_argument("--batch", type=int, default=BATCH)
        rebase = sub.add_parser(
            "rebase", help="Carry stored zones to their image host's new frame."
        )
        rebase.add_argument("--service", help="Only the zones of this image service.")
        rebase.add_argument("--host", help="Only the zones of this image host.")
        rebase.add_argument(
            "--frames", help="Frames file measured in a browser (frame_check.js)."
        )
        rebase.add_argument(
            "--resize",
            action="store_true",
            help="Also rebase zones whose image changed size, aspect kept.",
        )
        rebase.add_argument(
            "--since",
            help="YYYY-MM-DD: the host changed that day; only zones that existed unchanged before it move.",
        )
        rebase.add_argument("--apply", action="store_true", help="Write the zones.")
        rebase.add_argument(
            "--journal", help="New JSONL journal file, required with --apply."
        )
        rebase.add_argument("--batch", type=int, default=BATCH)
        relabel = sub.add_parser(
            "relabel",
            help="Give named zones their image host's measured frame, geometry untouched.",
        )
        relabel.add_argument(
            "--service", required=True, help="The image service of the zones."
        )
        relabel.add_argument(
            "--zone",
            action="append",
            required=True,
            metavar="TILE:FEATURE",
            help="A zone to relabel (repeatable).",
        )
        relabel.add_argument(
            "--frames", help="Frames file measured in a browser (frame_check.js)."
        )
        relabel.add_argument("--apply", action="store_true", help="Write the stamps.")
        relabel.add_argument(
            "--journal", help="New JSONL journal file, required with --apply."
        )
        relabel.add_argument("--batch", type=int, default=BATCH)
        unstamp = sub.add_parser("unstamp", help="Restore the journaled values.")
        unstamp.add_argument("--journal", required=True)
        unstamp.add_argument("--apply", action="store_true")
        unstamp.add_argument("--batch", type=int, default=BATCH)

    def handle(self, *args, **options):
        action = options["action"]
        if action != "check" and options["batch"] < 1:
            raise CommandError("--batch must be at least 1")
        if action == "stamp" and options["retries"] < 0:
            raise CommandError("--retries must be 0 or more")
        getattr(self, f"_{action}")(options)

    def _out(self, text=""):
        self.stdout.write(text)

    def _sleep(self, seconds):
        time.sleep(seconds)

    def _wait(self, plan, number, stamped, pending):
        """Say what pass *number* did, then sleep until the host-down marks set by *plan*'s failed reads have expired, at most ``RETRY_WAIT_MAX`` seconds."""
        ttl = units.down_ttl()
        elapsed = time.monotonic() - (plan.last_failure or time.monotonic())
        seconds = min(max(ttl - elapsed + 1, 0), RETRY_WAIT_MAX)
        note = (
            f" (the marks last {ttl} s and may still be live)"
            if ttl > RETRY_WAIT_MAX
            else ""
        )
        self._out(
            f"pass {number}: {stamped} zone(s) stamped; {len(pending)} service(s) "
            f"unavailable; waiting {seconds:.0f} s{note} (Ctrl-C stops retrying "
            "and keeps what is written)"
        )
        self._sleep(seconds)

    def _write(self, plan, journal, size):
        """Apply *plan* by batches of *size* tiles; return how many zones were written."""
        written = 0
        items = list(plan.entries.items())
        for start in range(0, len(items), size):
            try:
                written += apply_batch(items[start : start + size], journal)
            except OSError as error:
                raise CommandError(f"journal write failed: {error}") from error
        return written

    def _check(self, options):
        nodes = annotation_nodes()
        counts = activity.annotation_zone_counts()
        self._out(
            "Annotation zones by stamp state (data only, provisional edits not counted):"
        )
        for state, count in counts.items():
            self._out(f"  {state}: {count}")
        unresolved = Counter()
        for _tile, data, edits in tiles_of(nodes):
            for user, _node, collection in collections_of(data, edits, nodes):
                if user is not None:
                    continue
                for feature in collection["features"]:
                    if not isinstance(feature, dict):
                        unresolved["(not a feature)"] += 1
                    elif not frames.frame_of(feature):
                        unresolved[frames.canvas_of(feature) or "(no canvas)"] += 1
        self._out("")
        if unresolved:
            self._out("Images of unstamped zones (data only):")
            for canvas, count in unresolved.most_common():
                self._out(f"  {canvas}: {count}")
        else:
            self._out("No unstamped zone.")

    def _stamp(self, options):
        apply_changes = options["apply"]
        service = options["service"]
        if service:
            service = rewrite_legacy_url(service).rstrip("/")
        journal_path = options["journal"]
        if apply_changes and not journal_path:
            raise CommandError("--apply needs --journal PATH (a new file)")
        journal = open_journal(journal_path) if apply_changes else None
        written, failed, retry_left, interrupted = 0, False, set(), False
        try:
            nodes = annotation_nodes()
            current = plan_stamps(nodes, service)
            already, unusable = current.already, current.unusable
            size_of = current.size_of
            skipped = Counter(current.skipped)
            planned = {}
            passes = 0
            while True:
                for tile_id, entries in current.entries.items():
                    for node_id, user_id, fid, _d, _c, frame, _l in entries:
                        planned[(tile_id, node_id, user_id, fid)] = frame.source
                done = 0
                if apply_changes:
                    done = self._write(current, journal, options["batch"])
                    written += done
                pending = current.unavailable()
                if not pending:
                    break
                if not apply_changes or passes >= options["retries"]:
                    retry_left = pending
                    break
                try:
                    self._wait(current, passes + 1, done, pending)
                except KeyboardInterrupt:
                    retry_left, interrupted = pending, True
                    break
                passes += 1
                tiles = set().union(*(current.tiles_of_skipped[c] for c in pending))
                current = plan_stamps(
                    nodes, service, only=pending, size_of=size_of, tiles=tiles
                )
                for canvas in pending:
                    skipped.pop(canvas, None)
                skipped.update(current.skipped)
            stamped = Counter(planned.values())
            total = len(planned)
        except BaseException:
            failed = True
            raise
        finally:
            if journal is not None:
                kept = _close_journal(journal, journal_path)
                if kept and failed:
                    self._stopped_note(journal_path)
        self._out("")
        if service:
            self._out(f"Only the zones of {service}.")
        for source, count in sorted(stamped.items()):
            self._out(f"  {source}: {count} zone(s)")
        others = Counter({c: n for c, n in skipped.items() if c not in retry_left})
        if others:
            self._out(
                "Skipped, no frame known (refused without a registered size, or an unusable description):"
            )
            for canvas, count in others.most_common():
                self._out(f"  {canvas}: {count}")
        if retry_left:
            self._out("Unavailable services (read failed or host marked down):")
            for canvas in sorted(retry_left):
                self._out(f"  {canvas}: {skipped[canvas]}")
            if apply_changes:
                after = (
                    f" after {passes} retry pass(es)"
                    if passes and not interrupted
                    else ""
                )
                self._out(
                    f"{len(retry_left)} service(s) still unavailable{after}: "
                    "run the command again later, with a new journal."
                )
            elif options["retries"] > 0:
                self._out(
                    f"{len(retry_left)} unavailable service(s) would be read again "
                    "with --apply, after the host-down marks expire (no wait in a dry run)."
                )
        self._out(
            f"  already stamped: {already}; not stampable (no id, canvas or properties): {unusable}"
        )
        if apply_changes:
            self._out(
                self.style.SUCCESS(
                    f"{written} of {total} planned zone(s) stamped"
                    + (f"; journal: {journal_path}" if written else "")
                )
            )
            self._out("Now run:  python manage.py es reindex_database")
            if interrupted:
                raise CommandError(
                    "interrupted while waiting to retry; what was written is kept"
                )
        else:
            self._out(self.style.WARNING(f"{total} zone(s) would be stamped (dry run)"))
            self._out(
                "The dry run reads the info.json of each image service over the network "
                "and fills the image-info cache; it writes nothing else."
            )
            self._out("Pass --apply --journal PATH to write.")

    def _refused_scripts_check(self, directory, hosts):
        """``CommandError`` when *directory* is missing or already holds the script of one of *hosts*."""
        if not os.path.isdir(directory):
            raise CommandError(f"--refused-out {directory} is not a directory")
        for host in sorted(hosts):
            path = os.path.join(directory, _script_name(host))
            if os.path.lexists(path):
                raise CommandError(f"{path} exists; nothing was read or written")

    def _write_scripts(self, directory, refused):
        """Write ``DIR/<host>.js`` for each host of *refused* (``{host: [service]}``) and say how to use it."""
        for host, services in sorted(refused.items()):
            path = os.path.join(directory, _script_name(host))
            script = CHECK_SCRIPT.read_text(encoding="utf-8").replace(
                "__SERVICES__", json.dumps(sorted(services))
            )
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
            except OSError as error:
                raise CommandError(f"cannot create {path}: {error}") from error
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(script)
            parts = urlsplit(sorted(services)[0])
            self._out(
                f"{path}: {len(services)} service(s). Open a tab on {parts.scheme}://{parts.netloc}, "
                "paste the script in its console, save the copied JSON as a file, "
                "then run verify again with --frames FILE."
            )

    def _verify(self, options):
        apply_changes = options["apply"]
        journal_path = options["journal"]
        if apply_changes and not journal_path:
            raise CommandError("--apply needs --journal PATH (a new file)")
        frames_file = None
        if options["frames"]:
            try:
                frames_file = frame_scope.read_frames_file(options["frames"])
            except ValueError as error:
                raise CommandError(f"{options['frames']}: {error}") from error
        nodes = annotation_nodes()
        zones = list(stamped_zones(nodes, options["service"], options["host"]))
        by_service = defaultdict(list)
        for zone in zones:
            by_service[zone.canvas].append(zone)
        directory = options["refused_out"]
        if directory:
            self._refused_scripts_check(
                directory, {_host_of(canvas) for canvas in by_service}
            )
        journal = open_journal(journal_path) if apply_changes else None
        failed = False
        try:
            measures = Measures(frames_file)
            buckets = defaultdict(lambda: defaultdict(lambda: [set(), 0]))
            different, plan = Counter(), defaultdict(list)
            refused = defaultdict(list)
            for canvas in sorted(by_service):
                measured = measures.frame(canvas)
                host = _host_of(canvas)
                if measured == REFUSED_STATE:
                    refused[host].append(canvas)
                for zone in by_service[canvas]:
                    if isinstance(measured, str):
                        key = measured
                    elif zone.frame.unit == measured.unit and (
                        zone.frame.width,
                        zone.frame.height,
                    ) == (measured.width, measured.height):
                        key = "same"
                        if zone.frame.source == units.ESTIMATED:
                            plan[zone.tile_id].append(
                                (
                                    zone.node_id,
                                    zone.user_id,
                                    zone.feature_id,
                                    zone.digest,
                                    canvas,
                                    zone.frame,
                                    measured.source,
                                )
                            )
                    elif zone.frame.source == "import-legacy":
                        key = "legacy"
                    else:
                        key = "different"
                        different[
                            (canvas, _size_of(zone.frame), _size_of(measured))
                        ] += 1
                    cell = buckets[host][key]
                    cell[0].add(canvas)
                    cell[1] += 1
            written, changed = 0, []
            if apply_changes:
                items = list(plan.items())
                for start in range(0, len(items), options["batch"]):
                    try:
                        done, skipped = requalify_batch(
                            items[start : start + options["batch"]], journal
                        )
                    except OSError as error:
                        raise CommandError(f"journal write failed: {error}") from error
                    written += done
                    changed.extend(skipped)
        except BaseException:
            failed = True
            raise
        finally:
            if journal is not None:
                kept = _close_journal(journal, journal_path)
                if kept and failed:
                    self._stopped_note(journal_path)
        self._report(
            frames_file, zones, buckets, different, plan, written, changed, options
        )
        if directory and refused:
            self._write_scripts(directory, refused)
        count = lambda key: sum(b[key][1] for b in buckets.values() if key in b)
        if apply_changes:
            self._out(
                self.style.SUCCESS(
                    f"{written} zone(s) requalified"
                    + (f"; journal: {journal_path}" if written else "")
                )
            )
            self._out("Now run:  python manage.py es reindex_database")
        elif plan:
            self._out(
                self.style.WARNING(
                    f"{sum(len(e) for e in plan.values())} estimated zone(s) would be requalified (dry run)"
                )
            )
            self._out("Pass --apply --journal PATH to write.")
        problems = []
        if count("different"):
            problems.append(
                f"{count('different')} zone(s) differ from their image host"
            )
        if count(UNREADABLE_STATE):
            problems.append(
                f"not verified: {count(UNREADABLE_STATE)} zone(s) unreadable, run again"
            )
        if problems:
            raise CommandError("; ".join(problems))
        if count(REFUSED_STATE):
            self._out(
                self.style.WARNING(
                    f"{count(REFUSED_STATE)} zone(s) not verified: refused by their host; "
                    "measure them in a browser (--refused-out DIR, then --frames FILE)"
                )
            )

    def _report(
        self, frames_file, zones, buckets, different, plan, written, changed, options
    ):
        unstamped = activity.annotation_zone_counts()["unstamped"]
        self._out(
            f"Unstamped zones: {unstamped}"
            + ("; run stamp to stamp them" if unstamped else "")
        )
        if frames_file:
            self._out(
                f"Frames file: measured {frames_file.measured_at} from {frames_file.origin}"
            )
            tiles = defaultdict(set)
            for service, info in frames_file.frames.items():
                tiles[_host_of(service)].add(info.tile)
            for host, widths in sorted(tiles.items()):
                self._out(
                    f"  tile width measured on {host}: "
                    + ", ".join(str(w) for w in sorted(widths))
                )
        if not zones:
            self._out("No stamped zone to verify.")
        for host in sorted(buckets):
            self._out(f"{host}:")
            for key, label in BUCKETS:
                if key in buckets[host]:
                    services, count = buckets[host][key]
                    self._out(f"  {label}: {len(services)} service(s), {count} zone(s)")
        if different:
            self._out("Stored frame \u2192 live frame:")
        for (canvas, stamped, live), count in sorted(different.items()):
            self._out(f"  {canvas}: {stamped} \u2192 {live} ({count} zone(s))")
        for entry, reason in (frames_file.failed if frames_file else []):
            self._out(f"Frames file, not measured: {entry}: {reason}")
        for tile_id, fid in changed:
            self._out(f"  changed since: zone {fid} of tile {tile_id}")

    def _rebase_plan(self, by_service, measures, resize, since):
        """``(per, plan, canvas_of)``: for each service its target (a ``Frame`` or a state string), counts and listed zones; the entries for ``rebase_batch`` by tile; the service of each planned ``(tile id, feature id)``."""
        per = {}
        pending, tiles = [], set()
        for canvas in sorted(by_service):
            target = measures.frame(canvas)
            info = {"target": target, "rebased": 0, "unchanged": 0, "listed": []}
            per[canvas] = info
            for zone in by_service[canvas]:
                if isinstance(target, str):
                    continue
                f = zone.frame
                if (f.unit, f.width, f.height) == (
                    target.unit,
                    target.width,
                    target.height,
                ):
                    info["unchanged"] += 1
                    continue
                try:
                    frame_scope.scaled_geometry(zone.geometry, 1.0, 1.0)
                except ValueError:
                    info["listed"].append(("invalid geometry", zone))
                    continue
                factors = frame_scope.rebase_factors(f, target, resize)
                if factors is None:
                    info["listed"].append(
                        ("size changed: redraw, or relabel by hand", zone)
                    )
                elif since is None and f.source == units.ESTIMATED:
                    info["listed"].append(("estimated: give --since", zone))
                else:
                    pending.append((canvas, zone, target, factors))
                    tiles.add(zone.tile_id)
        before = values_before(tiles, since) if since and pending else {}
        plan, canvas_of, seen = defaultdict(list), {}, set()
        for canvas, zone, target, (fx, fy) in pending:
            key = (zone.tile_id, zone.user_id)
            if (
                since
                and key in before
                and ((zone.node_id, zone.feature_id, zone.digest) not in before[key])
            ):
                per[canvas]["listed"].append(
                    (
                        f"drawn or moved since {since:%Y-%m-%d}: review, then relabel",
                        zone,
                    )
                )
                continue
            once = (
                zone.tile_id,
                zone.node_id,
                zone.user_id,
                zone.feature_id,
                zone.digest,
            )
            if once in seen:
                continue
            seen.add(once)
            per[canvas]["rebased"] += 1
            canvas_of[(zone.tile_id, zone.feature_id)] = canvas
            plan[zone.tile_id].append(
                (
                    zone.node_id,
                    zone.user_id,
                    zone.feature_id,
                    zone.digest,
                    canvas,
                    zone.frame,
                    (target, fx, fy),
                )
            )
        return per, plan, canvas_of

    def _rebase(self, options):
        apply_changes = options["apply"]
        journal_path = options["journal"]
        if not (options["service"] or options["host"]):
            raise CommandError("--service or --host is required")
        if apply_changes and not journal_path:
            raise CommandError("--apply needs --journal PATH (a new file)")
        since = _since_of(options["since"]) if options["since"] else None
        frames_file = None
        if options["frames"]:
            try:
                frames_file = frame_scope.read_frames_file(options["frames"])
            except ValueError as error:
                raise CommandError(f"{options['frames']}: {error}") from error
        nodes = annotation_nodes()
        by_service = defaultdict(list)
        for zone in stamped_zones(nodes, options["service"], options["host"]):
            by_service[zone.canvas].append(zone)
        journal = open_journal(journal_path) if apply_changes else None
        failed = False
        try:
            per, plan, canvas_of = self._rebase_plan(
                by_service, Measures(frames_file), options["resize"], since
            )
            written, changed = 0, []
            if apply_changes:
                items = list(plan.items())
                for start in range(0, len(items), options["batch"]):
                    try:
                        done, skipped = rebase_batch(
                            items[start : start + options["batch"]], journal
                        )
                    except OSError as error:
                        raise CommandError(f"journal write failed: {error}") from error
                    written += done
                    changed.extend(skipped)
        except BaseException:
            failed = True
            raise
        finally:
            if journal is not None:
                kept = _close_journal(journal, journal_path)
                if kept and failed:
                    self._stopped_note(journal_path)
        self._rebase_report(per, changed, canvas_of, apply_changes)
        planned = sum(info["rebased"] for info in per.values())
        unreadable = sum(
            len(by_service[c])
            for c, i in per.items()
            if i["target"] == UNREADABLE_STATE
        )
        if apply_changes:
            self._out(
                self.style.SUCCESS(
                    f"{written} of {planned} planned zone(s) rebased"
                    + (f"; journal: {journal_path}" if written else "")
                )
            )
            self._out("Now run:  python manage.py es reindex_database")
            self._out(
                "Run with editing closed: an editor tab opened before the rebase saves "
                "the old geometry back. A few days later, dry-run `unstamp` of this "
                "journal: any \u00ab geometry reverted by a later save \u00bb is a zone "
                "to fix by `rebase --since` or `relabel`."
            )
        else:
            self._out(
                self.style.WARNING(f"{planned} zone(s) would be rebased (dry run)")
            )
            self._out("Pass --apply --journal PATH to write.")
        if unreadable:
            raise CommandError(
                f"not measured: {unreadable} zone(s) unreadable, run again"
            )

    def _rebase_report(self, per, changed, canvas_of, apply_changes):
        if not per:
            self._out("No stamped zone to rebase.")
        labels = dict(BUCKETS)
        late = defaultdict(list)
        for tile_id, fid in changed:
            late[canvas_of[(tile_id, fid)]].append((tile_id, fid))
        for canvas, info in per.items():
            target = info["target"]
            if isinstance(target, str):
                self._out(f"{canvas}: {labels[target]}: nothing planned")
                continue
            self._out(f"{canvas}: live frame {_size_of(target)}")
            done = info["rebased"] - len(late[canvas])
            verb = "rebased" if apply_changes else "would be rebased"
            self._out(f"  {verb}: {done if apply_changes else info['rebased']} zone(s)")
            self._out(f"  unchanged: {info['unchanged']} zone(s)")
            for reason, zone in info["listed"]:
                self._out(f"  {reason}: zone {zone.feature_id} of tile {zone.tile_id}")
            for tile_id, fid in late[canvas]:
                self._out(f"  changed since: zone {fid} of tile {tile_id}")

    def _zone_arguments(self, texts):
        """``{(tile id, feature id)}`` of the ``--zone TILE:FEATURE`` arguments."""
        named = set()
        for text in texts:
            tile_text, _, fid = text.partition(":")
            try:
                tile_id = uuid.UUID(tile_text)
            except ValueError:
                tile_id = None
            if tile_id is None or not fid:
                raise CommandError(f"--zone {text!r}: expected TILE-UUID:FEATURE-ID")
            named.add((tile_id, fid))
        return named

    def _relabel(self, options):
        apply_changes = options["apply"]
        journal_path = options["journal"]
        if apply_changes and not journal_path:
            raise CommandError("--apply needs --journal PATH (a new file)")
        service = rewrite_legacy_url(options["service"]).rstrip("/")
        named = self._zone_arguments(options["zone"])
        frames_file = None
        if options["frames"]:
            try:
                frames_file = frame_scope.read_frames_file(options["frames"])
            except ValueError as error:
                raise CommandError(f"{options['frames']}: {error}") from error
        zones = list(
            stamped_zones(annotation_nodes(), tiles={tile for tile, _ in named})
        )
        target = Measures(frames_file).frame(service)
        found, listed, plan, planned = set(), [], defaultdict(list), set()
        if isinstance(target, str):
            labels = dict(BUCKETS)
            self._out(f"{service}: {labels[target]}: nothing planned")
        else:
            self._out(f"{service}: live frame {_size_of(target)}")
            for zone in zones:
                key = (zone.tile_id, zone.feature_id)
                if key not in named:
                    continue
                found.add(key)
                if zone.canvas != service:
                    listed.append(("on another service", zone.tile_id, zone.feature_id))
                elif zone.frame == target:
                    listed.append(("already equal", zone.tile_id, zone.feature_id))
                else:
                    once = (zone.tile_id, zone.node_id, zone.user_id, zone.feature_id)
                    if (*once, zone.digest) in planned:
                        continue
                    planned.add((*once, zone.digest))
                    plan[zone.tile_id].append(
                        (
                            zone.node_id,
                            zone.user_id,
                            zone.feature_id,
                            zone.digest,
                            service,
                            zone.frame,
                            target,
                        )
                    )
            listed.extend(
                ("not found or not stamped", tile_id, fid)
                for tile_id, fid in sorted(named - found, key=str)
            )
        journal = open_journal(journal_path) if apply_changes and plan else None
        failed = False
        written, changed = 0, []
        try:
            if apply_changes:
                items = list(plan.items())
                for start in range(0, len(items), options["batch"]):
                    try:
                        done, skipped = relabel_batch(
                            items[start : start + options["batch"]], journal
                        )
                    except OSError as error:
                        raise CommandError(f"journal write failed: {error}") from error
                    written += done
                    changed.extend(skipped)
        except BaseException:
            failed = True
            raise
        finally:
            if journal is not None:
                kept = _close_journal(journal, journal_path)
                if kept and failed:
                    self._stopped_note(journal_path)
        for reason, tile_id, fid in listed:
            self._out(f"  {reason}: zone {fid} of tile {tile_id}")
        for tile_id, fid in changed:
            self._out(f"  changed since: zone {fid} of tile {tile_id}")
        count = len(planned)
        if apply_changes:
            self._out(
                self.style.SUCCESS(
                    f"{written} of {count} planned zone(s) relabeled"
                    + (f"; journal: {journal_path}" if written else "")
                )
            )
            self._out("Now run:  python manage.py es reindex_database")
        else:
            self._out(
                self.style.WARNING(f"{count} zone(s) would be relabeled (dry run)")
            )
            self._out("Pass --apply --journal PATH to write.")
        if target == UNREADABLE_STATE:
            raise CommandError(f"not measured: {service} is unreadable, run again")

    def _stopped_note(self, journal_path):
        """Tell where the journal of a stopped run is and how to undo it; never raises."""
        path = shlex.quote(journal_path)
        try:
            self.stderr.write(
                f"The run stopped; the journal {journal_path} was kept. To undo what it "
                f"records, first run: annotation_frames unstamp --journal {path} "
                "(dry run), then the same with --apply, then es reindex_database."
            )
        except Exception:
            logger.warning("journal kept at %s", journal_path, exc_info=True)

    def _unstamp(self, options):
        grouped = read_journal(options["journal"], self.stderr.write)
        tiles = list(grouped)
        total = sum(len(lines) for lines in grouped.values())
        restored, changed = 0, []
        size = options["batch"]
        for start in range(0, len(tiles), size):
            batch = tiles[start : start + size]
            done, skipped = restore_batch(batch, grouped, options["apply"])
            restored += done
            changed.extend(skipped)
        self._out("")
        for line, reason in changed:
            self._out(f"  {reason}: zone {line['feature']} of tile {line['tile']}")
        summary = f"{restored} of {total} journaled zone(s) " + (
            "restored" if options["apply"] else "would be restored"
        )
        if options["apply"]:
            self._out(self.style.SUCCESS(summary))
            self._out("Now run:  python manage.py es reindex_database")
        else:
            self._out(self.style.WARNING(summary + " (dry run)"))
            self._out("Pass --apply to write.")
