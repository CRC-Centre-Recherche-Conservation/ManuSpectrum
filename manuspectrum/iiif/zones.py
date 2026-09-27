"""Zones of annotation nodes, read off ``VwAnnotation``, as canvas pixel shapes.

A zone is stored under a canvas id or under the image service Arches' viewer
drew; a ``canvas_index`` of the source manifest maps both to the canvas id.
"""

import sys

from arches.app.models.models import VwAnnotation

from manuspectrum.views.explorer.values import rewrite_legacy_url, shape_of


def canvas_and_shape(vw, dims):
    """Canvas id and pixel ``Shape`` of one ``VwAnnotation`` row; canvas empty and shape None when unresolved.

    *dims* is a ``canvas_index``: the stored name (canvas id or image service)
    becomes the manifest's canvas id. A canvas missing from it keeps its
    stored name and is not clamped to any size, so a zone has the same
    coordinates whether its canvas dimensions are known or not.
    """
    feature = vw.feature or {}
    stored = rewrite_legacy_url(
        vw.canvas or (feature.get("properties") or {}).get("canvas") or ""
    )
    canvas, width, height = dims.get(stored.rstrip("/")) or (
        stored,
        sys.maxsize,
        sys.maxsize,
    )
    shape = shape_of(feature.get("geometry"), width, height)
    return canvas, shape


def annotation_features(node, resource_ids, dims, readable):
    """``(resource id, feature id, canvas, shape)`` of every resolved annotation feature of *node*, by feature id.

    Nothing when the node is unresolved or its nodegroup is not in *readable*.
    """
    if node is None or node.nodegroup_id not in readable:
        return
    for vw in VwAnnotation.objects.filter(
        resourceinstance_id__in=list(resource_ids), node_id=node.nodeid
    ).order_by("feature_id"):
        canvas, shape = canvas_and_shape(vw, dims)
        if canvas and shape:
            yield str(vw.resourceinstance_id), vw.feature_id, canvas, shape


def first_zone(node, resource_ids, dims, readable):
    """``{resource id: {"canvas", "shape"}}`` from the first annotation feature of *node*; ``{}`` when its nodegroup is not in *readable*."""
    zones = {}
    for rid, _, canvas, shape in annotation_features(
        node, resource_ids, dims, readable
    ):
        zones.setdefault(rid, {"canvas": canvas, "shape": shape})
    return zones
