"""Check, stamp and unstamp the image frame of the annotation zones already stored.

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

``unstamp --journal PATH`` puts every ``before`` back, only where the zone's
canvas, geometry digest and properties still equal the journaled ones; a zone
changed since is listed and left alone. Restoring the whole ``properties``
object gives the stored ``data`` back value for value (jsonb keeps no key
order). Dry by default as well.
"""

import copy
import errno
import json
import logging
import os
import shlex
import time
import uuid
from collections import Counter, defaultdict
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arches.app.models.models import Node, TileModel

from manuspectrum.constants.biblissima import COMP_LOCATION_DOC_NODE
from manuspectrum.iiif import frame_writes, frames, units
from manuspectrum.iiif.units import Frame
from manuspectrum.observability import activity
from manuspectrum.views.explorer.values import rewrite_legacy_url

logger = logging.getLogger(__name__)

LEGACY_SIZE = (4000, 5000)
BATCH = 200
RETRIES = 2
RETRY_WAIT_MAX = 300


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
        self.stamped = Counter()
        self.already = 0
        self.unusable = 0

    def read(self, service):
        """``frame_writes.fresh_info`` of *service*, once per run."""
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
                plan.stamped[frame.source] += 1
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
        rows = {
            row[0]: row
            for row in TileModel.objects.select_for_update()
            .filter(pk__in=[tile_id for tile_id, _ in batch])
            .order_by("pk")
            .values_list("tileid", "data", "provisionaledits")
        }
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
                    changed.append((line, "changed since"))
                    continue
                target["properties"] = line["before"]
                restored += 1
                changes[
                    "data" if line["provisional"] is None else "provisionaledits"
                ] = (data if line["provisional"] is None else edits)
            if changes and apply_changes:
                TileModel.objects.filter(pk=tile_id).update(**changes)
    return restored, changed


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


class Command(BaseCommand):
    help = (
        "Check, stamp (dry by default) or unstamp the image frame of stored "
        "annotation zones."
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
                self._out(
                    f"{len(retry_left)} service(s) still unavailable after {passes} "
                    "retry pass(es): run the command again later, with a new journal."
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
