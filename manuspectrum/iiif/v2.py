"""Presentation 2.1 / Open Annotation documents converted from their Presentation 3 form.

The v2 routes carry the same content as v3: every language of a label or a
metadata value as ``{"@value", "@language"}`` lists (``language.to_v2``), the
same bodies (``dctypes:Dataset``, ``dctypes:Image``, ``sc:Manifest``,
``cnt:ContentAsText``, ``oa:SpecificResource`` with ``oa:hasPurpose``), the
same motivations (``supplementing`` becomes ``oa:commenting``, any other
``oa:<motivation>``) and any ``xyReading`` of a body unchanged. Our ids move
from ``iiif/v3/`` to ``iiif/v2/``. A target becomes ``on``: the canvas, a
``#xywh=`` fragment of it for a rectangle, or an ``oa:Choice`` of the bounding
box (``default``) and the SVG (``item``) for a point or a polygon, which
Mirador 4 reads (``AnnotationResource.js``).
"""

from django.conf import settings

from manuspectrum.iiif import ids
from manuspectrum.iiif.constants import PRESENTATION_2, PRESENTATION_3
from manuspectrum.iiif.language import to_v2

TYPES = {
    "Dataset": "dctypes:Dataset",
    "Image": "dctypes:Image",
    "Text": "dctypes:Text",
    "Manifest": "sc:Manifest",
    "Canvas": "sc:Canvas",
    "Annotation": "oa:Annotation",
}


def _context(v3):
    """The v2 ``@context``: the extension contexts the v3 document lists, then Presentation 2."""
    context = v3.get("@context")
    extra = [
        c for c in (context if isinstance(context, list) else []) if c != PRESENTATION_3
    ]
    return [*extra, PRESENTATION_2] if extra else PRESENTATION_2


def _motivation(motivation):
    return "oa:commenting" if motivation == "supplementing" else f"oa:{motivation}"


def _labelled(target, v3, keys=("label",)):
    for key in keys:
        if v3.get(key):
            target[key] = to_v2(v3[key])
    return target


def _resource(body):
    """One v3 body or ``seeAlso`` entry as a v2 resource."""
    kind = body.get("type")
    if kind == "TextualBody":
        resource = {"@type": "cnt:ContentAsText", "chars": body.get("value", "")}
        for key in ("format", "language"):
            if body.get(key):
                resource[key] = body[key]
        if body.get("purpose"):
            resource["oa:hasPurpose"] = _motivation(body["purpose"])
        return resource
    if kind == "SpecificResource":
        source = body.get("source")
        source = dict(source) if isinstance(source, dict) else {"id": source}
        full = {"@id": ids.as_version(source.get("id"), 2)}
        if source.get("type"):
            full["@type"] = TYPES.get(source["type"], source["type"])
        _labelled(full, source)
        resource = {"@type": "oa:SpecificResource", "full": full}
        if body.get("purpose"):
            resource["oa:hasPurpose"] = _motivation(body["purpose"])
        return resource
    resource = {"@id": ids.as_version(body.get("id"), 2)}
    if kind:
        resource["@type"] = TYPES.get(kind, kind)
    if body.get("format"):
        resource["format"] = body["format"]
    _labelled(resource, body)
    if body.get("rights"):
        resource["license"] = body["rights"]
    statement = body.get("requiredStatement")
    if statement:
        resource["attribution"] = to_v2(statement["value"])
    if "xyReading" in body:
        resource["xyReading"] = body["xyReading"]
    if body.get("service"):
        resource["service"] = body["service"]
    return resource


def _selector(selectors):
    """``(fragment value, svg value)`` of a v3 selector or selector list."""
    fragment = svg = None
    point = None
    for selector in selectors if isinstance(selectors, list) else [selectors]:
        kind = selector.get("type")
        if kind == "FragmentSelector":
            fragment = selector["value"]
        elif kind == "SvgSelector":
            svg = selector["value"]
        elif kind == "PointSelector":
            point = (int(selector["x"]), int(selector["y"]))
    if fragment is None and point is not None:
        r = int(settings.IIIF_POINT_RADIUS)
        fragment = f"xywh={point[0] - r},{point[1] - r},{2 * r},{2 * r}"
    return fragment, svg


def on(target):
    """The v2 ``on`` of a v3 target."""
    if isinstance(target, str) or not target:
        return target
    source = target.get("source") or {}
    canvas = source.get("id") if isinstance(source, dict) else source
    fragment, svg = _selector(target.get("selector") or [])
    if svg is None:
        return f"{canvas}#{fragment}" if fragment else canvas
    result = {
        "@type": "oa:SpecificResource",
        "full": canvas,
        "selector": {
            "@type": "oa:Choice",
            "default": {"@type": "oa:FragmentSelector", "value": fragment},
            "item": {"@type": "oa:SvgSelector", "value": svg},
        },
    }
    manifests = source.get("partOf") if isinstance(source, dict) else None
    if manifests:
        result["within"] = {"@id": manifests[0]["id"], "@type": "sc:Manifest"}
    return result


def annotation(v3, *, context=True):
    """The ``oa:Annotation`` of a v3 annotation; *context* adds ``@context``."""
    converted = {"@context": _context(v3)} if context else {}
    converted.update(
        {
            "@id": ids.as_version(v3["id"], 2),
            "@type": "oa:Annotation",
            "motivation": _motivation(v3.get("motivation", "supplementing")),
        }
    )
    _labelled(converted, v3)
    body = v3.get("body")
    if body:
        converted["resource"] = [
            _resource(b) for b in (body if isinstance(body, list) else [body])
        ]
    converted["on"] = on(v3.get("target"))
    if v3.get("metadata"):
        converted["metadata"] = [
            {"label": to_v2(m["label"]), "value": to_v2(m["value"])}
            for m in v3["metadata"]
        ]
    if v3.get("seeAlso"):
        converted["seeAlso"] = [_resource(link) for link in v3["seeAlso"]]
    return converted


def page(v3):
    """The ``sc:AnnotationList`` of a v3 AnnotationPage, within its ``sc:Layer``."""
    converted = {
        "@context": _context(v3),
        "@id": ids.as_version(v3["id"], 2),
        "@type": "sc:AnnotationList",
    }
    _labelled(converted, v3)
    part_of = (v3.get("partOf") or [{}])[0]
    if part_of.get("id"):
        converted["within"] = _labelled(
            {"@id": ids.as_version(part_of["id"], 2), "@type": "sc:Layer"}, part_of
        )
    converted["resources"] = [annotation(a, context=False) for a in v3.get("items", [])]
    return converted


def layer(v3_collection, page_ids):
    """The ``sc:Layer`` of a v3 AnnotationCollection, listing the v3 *page_ids* as v2 lists."""
    converted = {
        "@context": _context(v3_collection),
        "@id": ids.as_version(v3_collection["id"], 2),
        "@type": "sc:Layer",
    }
    _labelled(converted, v3_collection)
    if page_ids:
        converted["otherContent"] = [ids.as_version(p, 2) for p in page_ids]
    return converted
