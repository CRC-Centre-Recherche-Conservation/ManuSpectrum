"""Selectors and targets of the zones of IIIF annotations, in canvas pixels.

v3 (Web Annotation, WADM §4.2: the selectors of an array select the same
content): a point is ``[PointSelector, SvgSelector]`` whose SVG is a circle of
``settings.IIIF_POINT_RADIUS`` pixels as a path Mirador draws; a rectangle one
media-fragment ``xywh`` ``FragmentSelector``; a polygon ``[SvgSelector
<polygon>, FragmentSelector of its bounding box]``. v2 (Open Annotation): a
rectangle is ``<canvas>#xywh=``; a point or a polygon an ``oa:Choice`` whose
``default`` is the bounding box and whose ``item`` is the SVG.
"""

from django.conf import settings

from manuspectrum.iiif.constants import MEDIA_FRAGMENTS, SVG_NAMESPACE


def circle_path(x, y, r):
    """SVG path of a circle of radius *r* centred on (*x*, *y*), as two arcs from the top."""
    return f"M {x} {y - r} A {r} {r} 0 1 1 {x} {y + r} A {r} {r} 0 1 1 {x} {y - r}"


def _radius():
    return int(settings.IIIF_POINT_RADIUS)


def _svg(element):
    return f'<svg xmlns="{SVG_NAMESPACE}">{element}</svg>'


def _box(points):
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def _xywh(box):
    return "xywh=" + ",".join(str(int(v)) for v in box)


def _parts(shape):
    """``(svg or None, bounding box)`` of a shape."""
    if shape["type"] == "point":
        x, y, r = int(shape["x"]), int(shape["y"]), _radius()
        return _svg(f'<path d="{circle_path(x, y, r)}"/>'), (x - r, y - r, 2 * r, 2 * r)
    if shape["type"] == "rect":
        return None, tuple(int(shape[k]) for k in ("x", "y", "w", "h"))
    points = [(int(x), int(y)) for x, y in shape["points"]]
    text = " ".join(f"{x},{y}" for x, y in points)
    return _svg(f'<polygon points="{text}"/>'), _box(points)


def _fragment(box):
    return {
        "type": "FragmentSelector",
        "conformsTo": MEDIA_FRAGMENTS,
        "value": _xywh(box),
    }


def selectors(shape):
    """The v3 selector (rectangle) or selectors (point, polygon) of a contract ``Shape``."""
    svg, box = _parts(shape)
    if shape["type"] == "point":
        return [
            {"type": "PointSelector", "x": int(shape["x"]), "y": int(shape["y"])},
            {"type": "SvgSelector", "value": svg},
        ]
    if svg is None:
        return _fragment(box)
    return [{"type": "SvgSelector", "value": svg}, _fragment(box)]


def target(canvas_id, manifest_url, shape):
    """v3 target: the canvas without *shape*, else a ``SpecificResource`` on the canvas, part of *manifest_url*."""
    if shape is None:
        return canvas_id
    source = {"id": canvas_id, "type": "Canvas"}
    if manifest_url:
        source["partOf"] = [{"id": manifest_url, "type": "Manifest"}]
    return {"type": "SpecificResource", "source": source, "selector": selectors(shape)}


def v2_on(canvas_id, manifest_url, shape):
    """v2 ``on``: the canvas, ``<canvas>#xywh=`` for a rectangle, else an ``oa:SpecificResource`` with a Choice."""
    if shape is None:
        return canvas_id
    svg, box = _parts(shape)
    if svg is None:
        return f"{canvas_id}#{_xywh(box)}"
    on = {
        "@type": "oa:SpecificResource",
        "full": canvas_id,
        "selector": {
            "@type": "oa:Choice",
            "default": {"@type": "oa:FragmentSelector", "value": _xywh(box)},
            "item": {"@type": "oa:SvgSelector", "value": svg},
        },
    }
    if manifest_url:
        on["within"] = {"@id": manifest_url, "@type": "sc:Manifest"}
    return on
