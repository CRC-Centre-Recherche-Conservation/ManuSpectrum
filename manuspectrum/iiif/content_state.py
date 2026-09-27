"""The published IIIF Content State of one zone (Content State 1.0 §2.2, §6.2).

A state is an ``Annotation`` with motivation ``contentState``, its id the
route answering it (``ids.content_state``). Its target is the zone on its
canvas, the canvas ``partOf`` the Explorer manifest of the Selection holding
that analysis (or identified material) alone: the manifest a viewer loads to
show the zone. A point is ``[PointSelector, SvgSelector]``, a rectangle an
``xywh`` fragment, a polygon ``[SvgSelector, FragmentSelector]``
(``selectors``); a zone without a shape targets the canvas. The state is
plain JSON-LD under the Presentation 3 context, never content-state-encoded.
"""

from manuspectrum.iiif import ids, selectors
from manuspectrum.iiif.constants import PRESENTATION_3


def content_state(kind, resource_id, zone):
    """The Content State of *zone* of the analysis (or, *kind* ``characterization``, identified material) *resource_id*."""
    manifest = ids.selection_manifest(kind, resource_id)
    if zone.shape is None:
        target = {
            "id": zone.canvas,
            "type": "Canvas",
            "partOf": [{"id": manifest, "type": "Manifest"}],
        }
    else:
        target = selectors.target(zone.canvas, manifest, zone.shape)
    return {
        "@context": PRESENTATION_3,
        "id": ids.content_state(resource_id, zone.feature),
        "type": "Annotation",
        "motivation": ["contentState"],
        "target": target,
    }
