"""Stamping the image frame on annotation zones as their tile is saved.

``stamp_instance`` runs in the tile's ``pre_save`` (``signals.stamp_annotation_frames``):
it applies ``frames.stamp_collection`` to the annotation collections of the
tile's data and of every provisional value, with the frames already known
(``units.known_info``: the cache, no request). The features a non-trusted
writer drew on an image not known yet are listed, and ``resolve_pending``
stamps them once the save commits: the image description is read outside any
transaction, then the tile is locked and only the features still unstamped
and unchanged are written. The write is a guarded ``.update()``: no edit log
and no indexing, so a stamp reaches Elasticsearch at the tile's next save or at
the next reindex.

``frame_for_service`` is the one rule that gives the frame of an image service.
"""

import copy
import logging
import uuid

from django.db import transaction

from arches.app.models.models import Node, TileModel

from manuspectrum.iiif import frames, units
from manuspectrum.iiif.sources import canvas_index, canvases_of
from manuspectrum.utils.budget import current_budget, upstream_budget
from manuspectrum.utils.manifest_registry import find_registered

logger = logging.getLogger(__name__)

RESOLVE_BUDGET = 30


def known_frame(service):
    """The ``read`` ``Frame`` of *service* from the kept image description, or None."""
    info = units.known_info(service)
    if info is None:
        return None
    try:
        return units.frame_from_info(info)
    except ValueError:
        return None


def _registered_canvas_size(manifest_url, stored_name):
    """``(width, height)`` of the canvas *stored_name* names in the registered manifest *manifest_url*, or None.

    Reads the database only: a manifest that is not registered is not fetched.
    """
    if not isinstance(manifest_url, str) or not manifest_url:
        return None
    row, _outcome = find_registered(manifest_url)
    manifest = getattr(row, "manifest", None)
    if not isinstance(manifest, dict):
        return None
    try:
        return canvas_index(canvases_of(manifest)).size((stored_name or "").rstrip("/"))
    except Exception:
        logger.warning(
            "registered manifest unreadable: %s", manifest_url, exc_info=True
        )
        return None


def frame_for_service(service, manifest_url, stored_name):
    """The ``Frame`` of the image *service* a zone was stored under *stored_name* in the manifest *manifest_url*, or None.

    A readable info.json gives a ``read`` frame. A host that refuses this
    server gives an ``estimated`` frame from the canvas size of the registered
    manifest row (never fetched); no such size, or a failed read, gives None.
    An info.json or a size no ``Frame`` accepts gives None. Reads the image
    description over the network when it is not kept: never call it inside a
    transaction.
    """
    info = units.image_info(service)
    try:
        if isinstance(info, units.ImageInfo):
            return units.frame_from_info(info)
        if info == units.REFUSED:
            size = _registered_canvas_size(manifest_url, stored_name)
            return units.frame_assumed(service, *size) if size else None
    except ValueError as exc:
        logger.debug("no frame for %s: %s", service, exc)
    return None


def _is_collection(value):
    """True for a dict whose ``features`` is a list: what the readers (``zones.FeatureRows``, the thumbnails) take as a collection, whatever its ``type``."""
    return isinstance(value, dict) and isinstance(value.get("features"), list)


def holders(instance):
    """``[(user id or None, {node id: collection})]``: the values of the tile that hold a FeatureCollection.

    ``None`` is the tile's ``data``, a user id one of its provisional edits.
    """
    found = []
    data = instance.data
    if isinstance(data, dict):
        nodes = {k: v for k, v in data.items() if _is_collection(v)}
        if nodes:
            found.append((None, nodes))
    edits = instance.provisionaledits
    if isinstance(edits, dict):
        for user_id, edit in edits.items():
            value = edit.get("value") if isinstance(edit, dict) else None
            if isinstance(value, dict):
                nodes = {k: v for k, v in value.items() if _is_collection(v)}
                if nodes:
                    found.append((user_id, nodes))
    return found


def _node_ids(nodes):
    found = set()
    for key in nodes:
        try:
            found.add(str(uuid.UUID(str(key))))
        except ValueError:
            continue
    return found


def annotation_nodes(instance, holders):
    """The ids of the annotation nodes among the keys of *holders*, one query.

    Kept on *instance* for the post-save receiver.
    """
    wanted = set()
    for _user, nodes in holders:
        wanted |= _node_ids(nodes)
    found = frozenset(
        str(node_id)
        for node_id in Node.objects.filter(
            nodeid__in=wanted, datatype="annotation"
        ).values_list("nodeid", flat=True)
    )
    instance._ms_annotation_nodes = found
    return found


def _without_stamps(collection):
    """*collection* with the stamp keys removed from every feature that has properties; cannot raise on a FeatureCollection."""
    features = []
    for feature in collection["features"]:
        props = feature.get("properties") if isinstance(feature, dict) else None
        if isinstance(props, dict):
            feature = {
                **feature,
                "properties": {
                    k: v for k, v in props.items() if k not in frames.STAMP_KEYS
                },
            }
        features.append(feature)
    return {**collection, "features": features}


def _pending_digests(stamped, unresolved):
    """``{feature id: geometry digest}`` of the *unresolved* features of *stamped*, left out when the geometry is invalid."""
    digests = {}
    for feature in stamped["features"]:
        fid = feature.get("id") if isinstance(feature, dict) else None
        if not frames.valid_id(fid) or fid not in unresolved or fid in digests:
            continue
        geometry = feature.get("geometry")
        if frames.same_geometry(geometry, geometry):
            digests[fid] = frames.geometry_digest(geometry)
    return digests


def stamp_instance(instance, holders):
    """Stamp the zones of *instance* in place; return ``{(node id, user id or None, feature id): geometry digest}`` to resolve on commit.

    *holders* is ``holders(instance)``. The previous row is read once. A value
    of an unexpected shape is skipped; a database error is not caught.
    """
    nodes = annotation_nodes(instance, holders)
    if not nodes:
        return {}
    row = (
        TileModel.objects.filter(pk=instance.pk)
        .values_list("data", "provisionaledits")
        .first()
    )
    previous = frames.PreviousFeatures(*(row if row else ({}, None)))
    trusted = frames.is_trusted()
    data, edits, pending = instance.data, instance.provisionaledits, {}
    for user_id, values in holders:
        for node_id, collection in values.items():
            if str(node_id) not in nodes:
                continue
            try:
                stamped, unresolved = frames.stamp_collection(
                    collection, previous, node_id, known_frame, trusted
                )
                digests = _pending_digests(stamped, unresolved)
            except Exception:
                digests = {}
                stamped = collection if trusted else _without_stamps(collection)
                logger.warning(
                    "zones of %s not stamped%s",
                    node_id,
                    "" if trusted else ", stamp keys dropped",
                    exc_info=True,
                )
            if user_id is None:
                data = {**data, node_id: stamped}
            else:
                edit = edits[user_id]
                edits = {
                    **edits,
                    user_id: {**edit, "value": {**edit["value"], node_id: stamped}},
                }
            pending.update({(node_id, user_id, fid): d for fid, d in digests.items()})
    instance.data, instance.provisionaledits = data, edits
    return pending


def _value_of(data, edits, user_id):
    if user_id is None:
        return data
    edit = (edits or {}).get(user_id)
    return edit.get("value") if isinstance(edit, dict) else None


def _features_of(value, node_id, fid, digest):
    """The features of *value*'s collection *node_id* with the id *fid*, still unstamped, whose geometry digest is *digest*."""
    collection = value.get(node_id) if isinstance(value, dict) else None
    if not _is_collection(collection):
        return []
    return [
        f
        for f in collection["features"]
        if isinstance(f, dict)
        and f.get("id") == fid
        and isinstance(f.get("properties"), dict)
        and frames.frame_of(f) is None
        and frames.geometry_digest(f.get("geometry")) == digest
    ]


def _context(feature):
    props = feature["properties"]
    manifest = props.get("manifest")
    return (
        frames.canvas_of(feature),
        manifest if isinstance(manifest, str) else None,
    )


def resolve_pending(tile_id, pending):
    """Stamp the zones listed in *pending* of the tile *tile_id*; return how many were written.

    *pending* maps ``(node id, provisional user id or None, feature id)`` to
    the geometry digest (``frames.geometry_digest``) the feature had when it
    was listed. The image of each feature is resolved first, under one
    ``upstream_budget`` and no transaction (``frame_for_service``). The tile is
    then locked and re-read: a feature is stamped only when it is still there,
    still unstamped and still has that geometry; a feature edited meanwhile is
    left to its own save. The stamp reaches Elasticsearch at the tile's next
    save or reindex.

    A full-row ``Tile.save`` that read the tile before this job committed
    writes its own copy back and can overwrite the stamp; the zone then stays
    unstamped until the command stamps it.
    """
    if not pending:
        return 0
    row = (
        TileModel.objects.filter(pk=tile_id)
        .values_list("data", "provisionaledits")
        .first()
    )
    if row is None:
        return 0
    data, edits = row
    resolved = {}
    ambient = current_budget()
    seconds = RESOLVE_BUDGET if ambient is None else min(RESOLVE_BUDGET, ambient.left())
    with upstream_budget(seconds, kind="write"):
        for (node_id, user_id, fid), digest in pending.items():
            value = _value_of(data, edits, user_id)
            for feature in _features_of(value, node_id, fid, digest):
                context = _context(feature)
                if context[0] and context not in resolved:
                    resolved[context] = frame_for_service(
                        context[0], context[1], context[0]
                    )
    if not any(resolved.values()):
        return 0
    with transaction.atomic():
        row = (
            TileModel.objects.select_for_update()
            .filter(pk=tile_id)
            .values_list("data", "provisionaledits")
            .first()
        )
        if row is None:
            return 0
        data, edits = copy.deepcopy(row[0]), copy.deepcopy(row[1])
        written, touched = 0, set()
        for (node_id, user_id, fid), digest in pending.items():
            value = _value_of(data, edits, user_id)
            for feature in _features_of(value, node_id, fid, digest):
                frame = resolved.get(_context(feature))
                if frame:
                    feature["properties"].update(frame.stamp())
                    written += 1
                    touched.add("data" if user_id is None else "provisionaledits")
        if written:
            changes = {}
            if "data" in touched:
                changes["data"] = data
            if "provisionaledits" in touched:
                changes["provisionaledits"] = edits
            TileModel.objects.filter(pk=tile_id).update(**changes)
    return written
