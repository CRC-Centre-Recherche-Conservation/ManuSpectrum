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

from manuspectrum.views.explorer.values import rewrite_legacy_url, shape_of


def canvas_and_shape(feature, dims):
    """Canvas id and pixel ``Shape`` of one annotation feature; canvas empty and shape None when unresolved.

    *dims* is a ``canvas_index``: the stored name (canvas id or image service)
    becomes the manifest's canvas id. A canvas missing from it keeps its
    stored name and is not clamped to any size, so a zone has the same
    coordinates whether its canvas dimensions are known or not.
    """
    feature = feature or {}
    stored = rewrite_legacy_url((feature.get("properties") or {}).get("canvas") or "")
    canvas, width, height = dims.get(stored.rstrip("/")) or (
        stored,
        sys.maxsize,
        sys.maxsize,
    )
    shape = shape_of(feature.get("geometry"), width, height)
    return canvas, shape


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

    def features(self, resource_ids, dims):
        """``(resource id, feature id, canvas, shape)`` of every resolved feature of *resource_ids*, by feature id."""
        picked = sorted(
            row
            for rid in {str(r) for r in resource_ids}
            for row in self._by_resource.get(rid, ())
        )
        for _, rid, feature in picked:
            canvas, shape = canvas_and_shape(feature, dims)
            if canvas and shape:
                yield rid, _feature_id(feature), canvas, shape


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
