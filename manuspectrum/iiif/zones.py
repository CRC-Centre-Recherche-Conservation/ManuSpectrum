"""Zones of annotation nodes, read off the tiles, as canvas pixel shapes.

A zone is stored under a canvas id or under the image service Arches' viewer
drew; a ``canvas_index`` of the source manifest maps both to the canvas id.
"""

import sys
import uuid
from collections import defaultdict, namedtuple

from django.db.models import JSONField
from django.db.models.expressions import RawSQL

from arches.app.models.models import TileModel

from manuspectrum.iiif.frames import frame_of
from manuspectrum.iiif.units import unit_of_frame
from manuspectrum.views.explorer.values import rewrite_legacy_url, shape_of


def canvas_and_convert(feature, dims):
    """Canvas id of one annotation feature and the function giving its pixel shape and unit; ``("", None)`` when unresolved.

    *dims* is a ``CanvasIndex``: the stored name (canvas id or image service)
    becomes the manifest's canvas id. ``convert()`` returns ``(Shape,
    ZoneUnit)``. A feature carrying a valid frame stamp (``frames.frame_of``)
    is converted from it, with the canvas size, and no image description is
    read; the unit is noted on the canvas (``CanvasIndex.note_unit``). An
    unstamped feature takes the unit of its canvas (``CanvasIndex.unit``),
    read when the function is called: a zone whose shape is never asked costs
    no request. A shape is brought inside its canvas when the unit was
    measured, or stamped with a measured frame. With an assumed unit or an
    ``estimated`` stamp it is not clamped: its coordinates are the stored ones
    times the unit, negatives brought to 0. On a canvas missing from the index
    (which keeps its stored name) an unstamped zone is not clamped either, and
    a zone stamped with a measured frame is clamped to the frame's size.
    """
    if not isinstance(feature, dict):
        return "", None
    props = feature.get("properties")
    canvas_name = props.get("canvas") if isinstance(props, dict) else None
    stored = rewrite_legacy_url(canvas_name if isinstance(canvas_name, str) else "")
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return "", None
    name = stored.rstrip("/")
    canvas = (dims.get(name) or (stored,))[0]
    if not canvas or shape_of(geometry, sys.maxsize, sys.maxsize) is None:
        return "", None
    frame = frame_of(feature)

    def convert():
        if frame:
            unit = unit_of_frame(frame, *(dims.size(name) or (0, 0)))
            dims.note_unit(canvas, unit)
        else:
            unit = dims.unit(name)
        shape = shape_of(
            geometry,
            unit.width or sys.maxsize,
            unit.height or sys.maxsize,
            (unit.x, unit.y),
        )
        return shape, unit

    return canvas, convert


def assumed_unit_payload(unit):
    """The ``ZoneUnit`` payload of *unit* when its shape was not measured, else None."""
    return unit.payload() if unit is not None and not unit.read else None


def canvas_and_shape(feature, dims):
    """Canvas id and pixel ``Shape`` of one annotation feature (``canvas_and_convert``); canvas empty and shape None when unresolved."""
    canvas, convert = canvas_and_convert(feature, dims)
    return (canvas, convert()[0]) if convert else ("", None)


class FeatureRows:
    """The annotation features of *node* on *resource_ids*, read in one query and resolved per manifest.

    Nothing is read when the node is unresolved or its nodegroup is not in
    *readable*. ``features`` resolves a subset against one manifest's
    ``canvas_index``, in the order ``annotation_features`` gives.
    """

    def __init__(self, node, resource_ids, readable):
        self._by_resource = defaultdict(list)
        if node is None or node.nodegroup_id not in readable:
            return
        rows = (
            TileModel.objects.filter(
                nodegroup_id=node.nodegroup_id,
                resourceinstance_id__in=list(resource_ids),
            )
            .annotate(
                feature=RawSQL(
                    "jsonb_array_elements(CASE WHEN"
                    " jsonb_typeof(tiles.tiledata -> %s -> 'features') = 'array'"
                    " THEN tiles.tiledata -> %s -> 'features' ELSE '[]'::jsonb END)",
                    [str(node.nodeid)] * 2,
                    JSONField(),
                )
            )
            .values_list("resourceinstance_id", "feature")
        )
        usable = [row for row in rows if _usable(row[1])]
        for order, (rid, feature) in enumerate(sorted(usable, key=_by_feature_id)):
            self._by_resource[str(rid)].append((order, str(rid), feature))

    def zones(self, resource_id):
        """The usable features of *resource_id*, by feature id."""
        return [row[2] for row in self._by_resource.get(str(resource_id), ())]

    def located(self, resource_ids, dims):
        """``(resource id, feature id, canvas, convert)`` of every resolved feature of *resource_ids*, by feature id; ``convert()`` gives ``(shape, unit)`` (``canvas_and_convert``)."""
        picked = sorted(
            row
            for rid in {str(r) for r in resource_ids}
            for row in self._by_resource.get(rid, ())
        )
        for _, rid, feature in picked:
            canvas, convert = canvas_and_convert(feature, dims)
            if canvas and convert:
                yield rid, _feature_id(feature), canvas, convert

    def features(self, resource_ids, dims):
        """``(resource id, feature id, canvas, shape)`` of every resolved feature of *resource_ids*, by feature id."""
        for rid, feature, canvas, convert in self.located(resource_ids, dims):
            yield rid, feature, canvas, convert()[0]


Zone = namedtuple("Zone", "feature canvas")


def annotation_zones(nodes, resource_id):
    """``Zone(feature, canvas name)`` of every usable annotation feature of *resource_id* on *nodes*, by feature id.

    The canvas name is the stored ``properties.canvas`` when it is a string,
    else None. Unusable features (not an object, an id that is not a UUID) are
    left out, as ``FeatureRows`` leaves them.
    """
    rows = []
    for node in nodes:
        rows += FeatureRows(node, [resource_id], {node.nodegroup_id}).zones(resource_id)
    rows.sort(key=lambda feature: _by_feature_id((None, feature)))
    zones = []
    for feature in rows:
        props = feature.get("properties")
        canvas = props.get("canvas") if isinstance(props, dict) else None
        zones.append(Zone(feature, canvas if isinstance(canvas, str) else None))
    return zones


def located_features(node, resource_ids, dims, readable):
    """``FeatureRows.located`` of *node* on *resource_ids*: the shapes are converted on demand."""
    resource_ids = [str(r) for r in resource_ids]
    yield from FeatureRows(node, resource_ids, readable).located(resource_ids, dims)


def annotation_features(node, resource_ids, dims, readable):
    """``(resource id, feature id, canvas, shape)`` of every resolved annotation feature of *node*, by feature id.

    Nothing when the node is unresolved or its nodegroup is not in *readable*.
    """
    resource_ids = [str(r) for r in resource_ids]
    yield from FeatureRows(node, resource_ids, readable).features(resource_ids, dims)


def _usable(feature):
    """True for a feature object whose id is absent or a UUID string: what ``_feature_id`` can sort."""
    if not isinstance(feature, dict):
        return False
    found = feature.get("id")
    if found is None or (isinstance(found, str) and not found):
        return True
    try:
        uuid.UUID(found)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _feature_id(feature):
    found = feature.get("id") if isinstance(feature, dict) else None
    return uuid.UUID(found) if found else None


def _by_feature_id(row):
    """Sort key of PostgreSQL's ``ORDER BY (feature ->> 'id')::uuid``: nulls last."""
    found = _feature_id(row[1])
    return (found is None, found or 0)


def first_zone(node, resource_ids, dims, readable):
    """``{resource id: {"canvas", "shape", "unit"}}`` from the first annotation feature of *node*; ``{}`` when its nodegroup is not in *readable*.

    ``unit`` is the ``ZoneUnit`` payload when the shape was not measured, else
    None. Only the kept feature is converted: a discarded one reads no image
    description.
    """
    zones = {}
    for rid, _, canvas, convert in located_features(node, resource_ids, dims, readable):
        if rid not in zones:
            shape, unit = convert()
            zones[rid] = {
                "canvas": canvas,
                "shape": shape,
                "unit": assumed_unit_payload(unit),
            }
    return zones
