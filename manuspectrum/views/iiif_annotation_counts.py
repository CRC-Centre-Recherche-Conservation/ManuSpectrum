"""Annotation counts per canvas of one annotation node, for the IIIF viewer.

``GET /api/iiif-annotation-counts?nodeid=<uuid>`` answers
``{"<canvas>": <number of features>, ...}`` for every canvas carrying at least
one feature of that node. The core viewer shows one such number under each
thumbnail and, with Arches 8.1.5, gets them by asking ``iiifannotations`` once
per canvas; the project viewer (``media/js/views/components/iiif-viewer.js``)
asks this route once per node instead.

The keys are the ``properties.canvas`` values stored in the tiles, the string
the core viewer passes as the ``canvas`` parameter of ``iiifannotations``
(``getCanvasService``), so a count equals the length of that route's feature
list for the same canvas, except for the resources the reader cannot read
(below). The scope is the node, not the manifest: the answer covers every
manuscript carrying the node (about 78 kB, 1 118 canvases, for the largest node
of the dev database), so the counts equal the core's whatever manifest the
viewer shows, and no canvas list travels in the query string.

The features are counted off the node's own tiles (``jsonb_array_elements`` on
``tiledata -> <nodeid> -> features``, grouped by canvas). The SQL view the core
route reads (``vw_annotations``) unfolds the features of every annotation node
before its caller filters; on the dev database the same grouping costs about
240 ms through the view and about 30 ms on the tiles, with identical counts.

A reader gets the features of a nodegroup ``readable_nodegroup_ids`` lets
through, minus those of resources they cannot read (``hidden_resource_ids``,
the project's gate for object grants). The counts are therefore stricter than
the core list: ``iiifannotations`` does not filter by resource, so a reader
under a resource restriction can see fewer in the thumbnail count than shapes
drawn on the canvas. An unknown node, a node that is not an annotation node and an
unreadable nodegroup answer the same bodyless 404. The payload depends on the
reader and is never stored nor shared: ``private, no-store``.
"""

import uuid

from django.db import connection
from django.http import HttpResponseBadRequest, HttpResponseNotFound, JsonResponse
from django.utils.cache import patch_cache_control
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.gzip import gzip_page

from arches.app.models.models import Node

from manuspectrum.utils.public_visibility import (
    hidden_resource_ids,
    readable_nodegroup_ids,
)

COUNTS_SQL = """
    SELECT feature -> 'properties' ->> 'canvas' AS canvas, count(*)
    FROM tiles t
    CROSS JOIN LATERAL jsonb_array_elements(t.tiledata -> %(node)s -> 'features')
        AS feature
    WHERE t.nodegroupid = %(nodegroup)s
      AND jsonb_typeof(t.tiledata -> %(node)s -> 'features') = 'array'
      AND NOT (t.resourceinstanceid = ANY(%(hidden)s::uuid[]))
    GROUP BY 1
"""


def annotation_counts(node_id, nodegroup_id, hidden):
    """``{canvas: count}`` of the features of *node_id* outside the *hidden* resources."""
    with connection.cursor() as cursor:
        cursor.execute(
            COUNTS_SQL,
            {
                "node": str(node_id),
                "nodegroup": str(nodegroup_id),
                "hidden": sorted(hidden),
            },
        )
        return {canvas: count for canvas, count in cursor.fetchall() if canvas}


@method_decorator(gzip_page, name="dispatch")
class IIIFAnnotationCountsView(View):
    http_method_names = ["get", "head"]

    def get(self, request):
        try:
            node_id = uuid.UUID(request.GET.get("nodeid", ""))
        except ValueError:
            return HttpResponseBadRequest()
        nodegroup_id = (
            Node.objects.filter(pk=node_id, datatype="annotation")
            .values_list("nodegroup_id", flat=True)
            .first()
        )
        if nodegroup_id is None or str(nodegroup_id) not in readable_nodegroup_ids(
            request.user
        ):
            return HttpResponseNotFound()
        counts = annotation_counts(
            node_id, nodegroup_id, hidden_resource_ids(request.user)
        )
        response = JsonResponse(counts)
        patch_cache_control(response, private=True, no_store=True)
        return response
