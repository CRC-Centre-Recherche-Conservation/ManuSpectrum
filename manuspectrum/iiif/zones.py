"""Zones of annotation nodes, read off the tiles, as canvas pixel shapes.

A zone is stored under a canvas id or under the image service Arches' viewer
drew; a ``canvas_index`` of the source manifest maps both to the canvas id.
"""

import sys
import uuid
from collections import defaultdict

from django.db.models import JSONField
from django.db.models.expressions import RawSQL

from arches.app.models.models import TileModel

from manuspectrum.iiif.units import UNKNOWN_UNIT
from manuspectrum.views.explorer.values import rewrite_legacy_url, shape_of


def _unit_of(dims, stored):
    unit = getattr(dims, "unit", None)
    return unit(stored) if unit else UNKNOWN_UNIT


def canvas_and_convert(feature, dims):
    """Canvas id of one annotation feature and the function giving its pixel ``Shape``; ``("", None)`` when unresolved.

    *dims* is a ``canvas_index``: the stored name (canvas id or image service)
    becomes the manifest's canvas id. The shape is converted with the unit of
    that canvas (``CanvasIndex.unit``), which is read when the function is
    called: a zone whose shape is never asked costs no request. A shape is
    brought inside its canvas when the unit was read from the image's
    description. With an assumed unit, or on a canvas missing from the index
    (which keeps its stored name), it is not clamped: its coordinates are the
    stored ones times the unit.
    """
    feature = feature or {}
    stored = rewrite_legacy_url((feature.get("properties") or {}).get("canvas") or "")
    geometry = feature.get("geometry")
    name = stored.rstrip("/")
    canvas = (dims.get(name) or (stored,))[0]
    if not canvas or shape_of(geometry, sys.maxsize, sys.maxsize) is None:
        return "", None

    def convert():
        unit = _unit_of(dims, name)
        return shape_of(
            geometry,
            unit.width or sys.maxsize,
            unit.height or sys.maxsize,
            (unit.x, unit.y),
        )

    return canvas, convert


def canvas_and_shape(feature, dims):
    """Canvas id and pixel ``Shape`` of one annotation feature (``canvas_and_convert``); canvas empty and shape None when unresolved."""
    canvas, convert = canvas_and_convert(feature, dims)
    return (canvas, convert()) if convert else ("", None)


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
                    "jsonb_array_elements(tiles.tiledata -> %s -> 'features')",
                    [str(node.nodeid)],
                    JSONField(),
                )
            )
            .values_list("resourceinstance_id", "feature")
        )
        for order, (rid, feature) in enumerate(sorted(rows, key=_by_feature_id)):
            self._by_resource[str(rid)].append((order, str(rid), feature))

    def located(self, resource_ids, dims):
        """``(resource id, feature id, canvas, convert)`` of every resolved feature of *resource_ids*, by feature id; ``convert()`` gives the shape (``canvas_and_convert``)."""
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
            yield rid, feature, canvas, convert()


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


def _feature_id(feature):
    found = feature.get("id") if isinstance(feature, dict) else None
    return uuid.UUID(found) if found else None


def _by_feature_id(row):
    """Sort key of PostgreSQL's ``ORDER BY (feature ->> 'id')::uuid``: nulls last."""
    found = _feature_id(row[1])
    return (found is None, found or 0)


def first_zone(node, resource_ids, dims, readable):
    """``{resource id: {"canvas", "shape"}}`` from the first annotation feature of *node*; ``{}`` when its nodegroup is not in *readable*."""
    zones = {}
    for rid, _, canvas, shape in annotation_features(
        node, resource_ids, dims, readable
    ):
        zones.setdefault(rid, {"canvas": canvas, "shape": shape})
    return zones
