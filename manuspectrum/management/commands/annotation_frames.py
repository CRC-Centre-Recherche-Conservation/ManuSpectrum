"""Check, stamp and unstamp the image frame of the annotation zones already stored.

``check`` counts the zones per stamp state and lists the images of the
unstamped ones; it reads the database only. ``stamp`` gives each unstamped
zone the frame it was drawn in (``frames.STAMP_KEYS``): whole-page zones the
Biblissima import wrote before stamping existed get ``import-legacy``; any
other zone gets ``frame_writes.frame_for_service`` of its image, one read per
distinct image service and manifest. An image that cannot be read is skipped
and listed. A zone already carrying a valid stamp is never touched.

``stamp`` is dry by default. With ``--apply`` it writes by batches of tiles
under ``transaction.atomic()``: the tiles are locked and re-read, and a zone is
stamped only when it is still unstamped, on the same canvas and with the
geometry it had when it was planned. The write is an ``.update()``: no edit
log, no per-tile indexing, one ``es reindex_database`` at the end. Every
changed zone is appended to a JSONL journal, ``{tile, node, provisional,
feature, before, after}`` where ``before`` and ``after`` are the feature's
``properties`` (``provisional`` is the user id of a provisional edit, or null
for the tile's ``data``). The journal line is written inside the transaction,
after the update, so a failed journal write rolls the batch back.

``unstamp --journal PATH`` puts every ``before`` back, only where the zone's
current properties still equal the journaled ``after``; a zone changed since is
listed and left alone. Restoring the whole ``properties`` object gives the
stored ``data`` back byte for byte. Dry by default as well.
"""

import copy
import json
import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from types import SimpleNamespace

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from arches.app.models.models import Node, TileModel

from manuspectrum.constants.biblissima import COMP_LOCATION_DOC_NODE
from manuspectrum.iiif import frame_writes, frames
from manuspectrum.iiif.units import Frame
from manuspectrum.observability import activity
from manuspectrum.views.explorer.values import rewrite_legacy_url

LEGACY_SIZE = (4000, 5000)
LEGACY_UNIT = 32
BATCH = 200


def annotation_nodes():
    """``{node id: nodegroup id}`` of the annotation nodes, ids as strings."""
    return {
        str(node_id): group
        for node_id, group in Node.objects.filter(datatype="annotation").values_list(
            "nodeid", "nodegroup_id"
        )
    }


def tiles_of(nodes):
    """``(tile id, data, provisionaledits)`` of every tile of the annotation nodegroups."""
    rows = TileModel.objects.filter(nodegroup_id__in=set(nodes.values()))
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


def _legacy_frame(feature, collection, node_id):
    """The ``import-legacy`` frame of a whole-page zone the Biblissima import wrote, or None."""
    if node_id != COMP_LOCATION_DOC_NODE or len(collection["features"]) != 1:
        return None
    props = feature["properties"]
    manifest = props.get("manifest")
    canvas = frames.canvas_of(feature)
    sizes = []
    registered = frame_writes._registered_canvas_size(
        manifest if isinstance(manifest, str) else None, canvas
    )
    if registered:
        sizes.append(tuple(registered))
    sizes.append(LEGACY_SIZE)
    for width, height in sizes:
        w, h = width / LEGACY_UNIT, height / LEGACY_UNIT
        whole_page = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [w, 0], [w, -h], [0, -h], [0, 0]]],
        }
        if frames.same_geometry(feature.get("geometry"), whole_page):
            try:
                return Frame(LEGACY_UNIT, width, height, "import-legacy")
            except ValueError:
                return None
    return None


class Plan:
    """What ``stamp`` would write, and what it could not resolve."""

    def __init__(self, service=None):
        self.service = service
        self.entries = defaultdict(list)
        self.frames = {}
        self.skipped = Counter()
        self.stamped = Counter()
        self.already = 0
        self.unusable = 0

    def frame(self, service, manifest):
        key = (service, manifest)
        if key not in self.frames:
            self.frames[key] = frame_writes.frame_for_service(
                service, manifest, service
            )
        return self.frames[key]


def plan_stamps(nodes, service=None):
    """A ``Plan`` for every unstamped zone of the database; reads image descriptions, writes nothing."""
    plan = Plan(service)
    for tile_id, data, edits in tiles_of(nodes):
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
                frame = _legacy_frame(feature, collection, node_id)
                if frame is None:
                    manifest = props.get("manifest")
                    frame = plan.frame(
                        canvas, manifest if isinstance(manifest, str) else None
                    )
                if frame is None:
                    plan.skipped[canvas] += 1
                    continue
                plan.entries[tile_id].append(
                    (
                        node_id,
                        user_id,
                        fid,
                        frames.geometry_digest(feature.get("geometry")),
                        canvas,
                        frame,
                    )
                )
                plan.stamped[frame.source] += 1
    return plan


def _matching(value, node_id, fid, digest, canvas):
    """The still-unstamped features of *value*'s collection *node_id* the plan entry names."""
    return [
        f
        for f in frame_writes._features_of(value, node_id, fid, digest)
        if frames.canvas_of(f) == canvas
    ]


def apply_batch(batch, journal):
    """Stamp the planned zones of the tiles of *batch* (``[(tile id, entries)]``); return how many were written.

    The tiles are locked and re-read; each journal line is flushed to disk
    before the batch commits.
    """
    written = 0
    with transaction.atomic():
        rows = {
            row[0]: row
            for row in TileModel.objects.select_for_update()
            .filter(pk__in=[tile_id for tile_id, _ in batch])
            .values_list("tileid", "data", "provisionaledits")
        }
        for tile_id, entries in batch:
            if tile_id not in rows:
                continue
            data, edits = copy.deepcopy(rows[tile_id][1]), copy.deepcopy(
                rows[tile_id][2]
            )
            lines, changes = [], {}
            for node_id, user_id, fid, digest, canvas, frame in entries:
                value = frame_writes._value_of(data, edits, user_id)
                for feature in _matching(value, node_id, fid, digest, canvas):
                    before = copy.deepcopy(feature["properties"])
                    feature["properties"].update(frame.stamp())
                    lines.append(
                        {
                            "tile": str(tile_id),
                            "node": node_id,
                            "provisional": user_id,
                            "feature": fid,
                            "before": before,
                            "after": copy.deepcopy(feature["properties"]),
                        }
                    )
                    changes["data" if user_id is None else "provisionaledits"] = (
                        data if user_id is None else edits
                    )
            if lines:
                TileModel.objects.filter(pk=tile_id).update(**changes)
                for line in lines:
                    journal.write(json.dumps(line, sort_keys=True) + "\n")
                written += len(lines)
        journal.flush()
        os.fsync(journal.fileno())
    return written


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


def read_journal(path):
    """The lines of the JSONL journal *path*, grouped by tile id (as ``uuid.UUID``)."""
    grouped = defaultdict(list)
    try:
        with open(path, encoding="utf-8") as handle:
            for number, text in enumerate(handle, 1):
                if not text.strip():
                    continue
                try:
                    line = json.loads(text)
                    grouped[uuid.UUID(line["tile"])].append(line)
                    line["feature"], line["node"], line["before"], line["after"]
                    line["provisional"]
                except (ValueError, KeyError, TypeError) as error:
                    raise CommandError(
                        f"{path}:{number}: not a journal line"
                    ) from error
    except OSError as error:
        raise CommandError(f"cannot read the journal: {error}") from error
    return grouped


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
            "--journal", help="JSONL journal path (default: a new file)."
        )
        stamp.add_argument("--service", help="Only the zones of this image service.")
        stamp.add_argument(
            "--batch", type=int, default=BATCH, help="Tiles per transaction."
        )
        unstamp = sub.add_parser("unstamp", help="Restore the journaled values.")
        unstamp.add_argument("--journal", required=True)
        unstamp.add_argument("--apply", action="store_true")
        unstamp.add_argument("--batch", type=int, default=BATCH)

    def handle(self, *args, **options):
        action = options["action"]
        if action != "check" and options["batch"] < 1:
            raise CommandError("--batch must be at least 1")
        getattr(self, f"_{action}")(options)

    def _out(self, text=""):
        self.stdout.write(text)

    def _check(self, options):
        nodes = annotation_nodes()
        counts = activity.annotation_zone_counts()
        self._out("Annotation zones by stamp state:")
        for state, count in counts.items():
            self._out(f"  {state}: {count}")
        unresolved = Counter()
        for _tile, data, edits in tiles_of(nodes):
            for _user, _node, collection in collections_of(data, edits, nodes):
                for feature in collection["features"]:
                    if isinstance(feature, dict) and not frames.frame_of(feature):
                        unresolved[frames.canvas_of(feature) or "(no canvas)"] += 1
        self._out("")
        if unresolved:
            self._out("Images of unstamped zones:")
            for canvas, count in unresolved.most_common():
                self._out(f"  {canvas}: {count}")
        else:
            self._out("No unstamped zone.")

    def _stamp(self, options):
        apply_changes = options["apply"]
        service = options["service"]
        if service:
            service = rewrite_legacy_url(service).rstrip("/")
        journal_path = options["journal"] or datetime.now().strftime(
            "annotation-frames-%Y%m%d-%H%M%S.jsonl"
        )
        if apply_changes and os.path.exists(journal_path):
            raise CommandError(f"the journal {journal_path} already exists")
        nodes = annotation_nodes()
        plan = plan_stamps(nodes, service)
        total = sum(plan.stamped.values())
        written = 0
        if apply_changes and plan.entries:
            batch_size = options["batch"]
            items = list(plan.entries.items())
            with (
                frames.trusted_writes(),
                open(journal_path, "x", encoding="utf-8") as journal,
            ):
                for start in range(0, len(items), batch_size):
                    written += apply_batch(items[start : start + batch_size], journal)
        self._out("")
        for source, count in sorted(plan.stamped.items()):
            self._out(f"  {source}: {count} zone(s)")
        if plan.skipped:
            self._out(
                "Skipped, no frame known (unavailable or refused without a registered size):"
            )
            for canvas, count in plan.skipped.most_common():
                self._out(f"  {canvas}: {count}")
        self._out(
            f"  already stamped: {plan.already}; not stampable (no id, canvas or properties): {plan.unusable}"
        )
        if apply_changes:
            self._out(
                self.style.SUCCESS(
                    f"{written} of {total} planned zone(s) stamped; journal: {journal_path}"
                )
            )
            self._out("Now run:  python manage.py es reindex_database")
        else:
            self._out(self.style.WARNING(f"{total} zone(s) would be stamped (dry run)"))
            self._out("Pass --apply to write.")

    def _unstamp(self, options):
        grouped = read_journal(options["journal"])
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
