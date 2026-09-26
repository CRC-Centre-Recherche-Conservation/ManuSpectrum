"""The Explorer's IIIF Presentation 3 manifest of a scope (spec §11.1).

Building blocks, without database access: minted ids, selectors and targets,
source canvases (v2 or v3) as v3 canvases, and the data annotations of an
analysis. Annotations keep the shape of the project's v3 annotation
serializer (``supplementing``, ``Dataset`` bodies, ``seeAlso`` report) so
IIIF clients reading those read these the same way.
"""

import hashlib
import re
from urllib.parse import quote

from django.conf import settings
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

from manuspectrum.constants.licenses import iiif_rights
from manuspectrum.utils.iiif_tools import CanvasIIIF
from manuspectrum.views.explorer_values import rewrite_legacy_url

PRESENTATION_3 = "http://iiif.io/api/presentation/3/context.json"
MEDIA_FRAGMENTS = "http://www.w3.org/TR/media-frags/"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
OCTET_STREAM = "application/octet-stream"
_LEVEL = re.compile(r"level([0-2])")
_MIME = re.compile(r"^[a-z][a-z0-9.+-]*/[a-z0-9.+-]+$")


def mint(scope_digest, *parts):
    """Absolute id of a resource the manifest of *scope_digest* creates; it need not dereference."""
    path = reverse("iiif-v3-explorer-manifest").lstrip("/")
    tail = "".join(f"/{quote(str(part), safe='')}" for part in parts)
    return f"{settings.PUBLIC_SERVER_ADDRESS}{path}/{scope_digest}{tail}"


def selector(shape):
    """IIIF selector of a contract ``Shape`` in canvas pixels.

    A point is a ``PointSelector``, a rectangle a media-fragment ``xywh``
    ``FragmentSelector``, a polygon an ``SvgSelector`` with integer points.
    """
    if shape["type"] == "point":
        return {"type": "PointSelector", "x": int(shape["x"]), "y": int(shape["y"])}
    if shape["type"] == "rect":
        box = ",".join(str(int(shape[k])) for k in ("x", "y", "w", "h"))
        return {
            "type": "FragmentSelector",
            "conformsTo": MEDIA_FRAGMENTS,
            "value": f"xywh={box}",
        }
    points = " ".join(f"{int(x)},{int(y)}" for x, y in shape["points"])
    return {
        "type": "SvgSelector",
        "value": f'<svg xmlns="{SVG_NAMESPACE}"><polygon points="{points}"/></svg>',
    }


def target(canvas_id, manifest_url, shape):
    """Target of an annotation on *canvas_id*: the canvas itself without *shape*, else a ``SpecificResource`` on it."""
    if shape is None:
        return canvas_id
    return {
        "type": "SpecificResource",
        "source": {
            "id": canvas_id,
            "type": "Canvas",
            "partOf": [{"id": manifest_url, "type": "Manifest"}],
        },
        "selector": selector(shape),
    }


def _rewritten(value):
    """*value* with a legacy host rewritten in every ``id`` and ``@id``."""
    if isinstance(value, list):
        return [_rewritten(item) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                rewrite_legacy_url(item)
                if key in ("id", "@id") and isinstance(item, str)
                else _rewritten(item)
            )
            for key, item in value.items()
        }
    return value


def _text(value):
    """Plain text of a v2 string value: a string, a ``{"@value"}`` object or a list of them."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _text(value.get("@value"))
    if isinstance(value, list):
        return " ; ".join(t for t in (_text(v) for v in value) if t)
    return ""


def _rights(value):
    rights = value[0] if isinstance(value, list) and value else value
    return iiif_rights({"url": rights}) if isinstance(rights, str) else None


def _v2_painting(canvas, canvas_id, mint_id):
    key = hashlib.sha1(canvas_id.encode(), usedforsecurity=False).hexdigest()[:12]
    image = ((canvas.get("images") or [{}])[0] or {}).get("resource") or {}
    service = image.get("service") or {}
    if isinstance(service, list):
        service = service[0] if service else {}
    service_id = service.get("@id") or service.get("id")
    body = {
        "id": image.get("@id")
        or (f"{service_id.rstrip('/')}/full/full/0/default.jpg" if service_id else ""),
        "type": "Image",
        "format": image.get("format") or "image/jpeg",
    }
    width, height = image.get("width"), image.get("height")
    if isinstance(width, int) and isinstance(height, int):
        body.update(width=width, height=height)
    if service_id:
        level = _LEVEL.search(str(service.get("profile") or ""))
        body["service"] = [
            {
                "id": service_id,
                "type": "ImageService2",
                "profile": f"level{level[1] if level else 0}",
            }
        ]
    return [
        {
            "id": mint_id("painting", key),
            "type": "AnnotationPage",
            "items": [
                {
                    "id": mint_id("painting", key, "image"),
                    "type": "Annotation",
                    "motivation": "painting",
                    "target": canvas_id,
                    "body": body,
                }
            ],
        }
    ]


def v3_canvas(source_canvas, source_manifest, manifest_url, mint_id):
    """*source_canvas* of *source_manifest* (v2 or v3) as a v3 canvas, part of *manifest_url*.

    A v3 canvas keeps its ``id``, ``label``, size and ``items``; ``rights``
    and ``requiredStatement`` are its own, else the manifest's; its own
    ``annotations`` are dropped. A v2 canvas gets one minted painting page
    whose image carries an ``ImageService2``; the manifest's ``license``
    becomes ``rights`` and its ``attribution`` a ``requiredStatement``.
    ``rights`` is kept only in the ``http://`` form of a rights registry
    (``iiif_rights``). Legacy hosts are rewritten in every id.
    """
    source_canvas = _rewritten(source_canvas)
    source_manifest = source_manifest or {}
    width, height = CanvasIIIF.get_canvas_dimensions(source_canvas)
    if CanvasIIIF.detect_version(source_manifest) == 3:
        canvas_id = source_canvas["id"]
        canvas = {
            "id": canvas_id,
            "type": "Canvas",
            "label": source_canvas.get("label") or {"none": [""]},
            "width": int(width),
            "height": int(height),
            "items": source_canvas.get("items") or [],
        }
        rights = _rights(source_canvas.get("rights") or source_manifest.get("rights"))
        statement = source_canvas.get("requiredStatement") or source_manifest.get(
            "requiredStatement"
        )
    else:
        canvas_id = source_canvas["@id"]
        canvas = {
            "id": canvas_id,
            "type": "Canvas",
            "label": {"none": [_text(source_canvas.get("label"))]},
            "width": int(width),
            "height": int(height),
            "items": _v2_painting(source_canvas, canvas_id, mint_id),
        }
        rights = _rights(source_manifest.get("license"))
        attribution = _text(source_manifest.get("attribution"))
        statement = (
            {"label": {"none": [_("Attribution")]}, "value": {"none": [attribution]}}
            if attribution
            else None
        )
    if rights:
        canvas["rights"] = rights
    if statement:
        canvas["requiredStatement"] = statement
    canvas["partOf"] = [{"id": manifest_url, "type": "Manifest"}]
    return canvas


def layer_canvas(source_canvas, imaging_manifest, imaging_url, label, mint_id):
    """One image layer of an imaging manifest as a v3 canvas: its source id, the lngString *label*, part of *imaging_url*."""
    canvas = v3_canvas(source_canvas, imaging_manifest, imaging_url, mint_id)
    canvas["label"] = label
    return canvas


def absolute_url(url):
    """*url* as an absolute URL: a site path is prefixed with ``PUBLIC_SERVER_ADDRESS``; None when it is neither."""
    url = str(url or "")
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/") and not url.startswith("//"):
        return f"{settings.PUBLIC_SERVER_ADDRESS}{url.lstrip('/')}"
    return None


def _dataset_url(dataset):
    url = (dataset or {}).get("url") or ""
    if url.startswith("10."):
        return f"https://doi.org/{url}"
    return url if url.startswith(("http://", "https://")) else None


def _body(entry, language):
    """Annotation body of one ``FileEntry``: a ``Dataset``, or the ``Manifest`` of an imaging entry; None without a URL."""
    url = absolute_url(entry.get("downloadUrl"))
    if url is None:
        return None
    if entry.get("dataKind") == "chemical-imaging":
        return {"id": url, "type": "Manifest"}
    fmt = str(entry.get("format") or "").lower()
    body = {
        "id": url,
        "type": "Dataset",
        "format": fmt if _MIME.match(fmt) else OCTET_STREAM,
        "label": {language: [entry.get("name") or ""]},
    }
    licence = entry.get("license")
    rights = iiif_rights(licence)
    if rights:
        body["rights"] = rights
    if licence and not rights:
        text = " — ".join(
            t for t in (licence["label"]["value"], licence.get("attribution")) if t
        )
        body["requiredStatement"] = {
            "label": {language: [_("Licence")]},
            "value": {language: [text]},
        }
    elif licence and licence.get("attribution"):
        body["requiredStatement"] = {
            "label": {language: [_("Attribution")]},
            "value": {language: [licence["attribution"]]},
        }
    return body


def data_annotation(annotation_id, analysis, files, target, language):
    """The ``supplementing`` annotation of one analysis on *target*, its files as bodies.

    *analysis* holds ``name``, ``permalink``, ``dataset`` (``dataset_of``)
    and the plain-text metadata ``technique``, ``dates``, ``operators``,
    ``conditions``, ``document`` and ``component`` (empty ones are left
    out). Each file is a ``Dataset`` body: its absolute download URL, its
    MIME type (``application/octet-stream`` when the entry has none),
    ``rights`` when its licence is in a rights registry, else a
    ``requiredStatement`` naming the licence and its attribution; an
    attribution under a registry licence is a ``requiredStatement`` too. An
    imaging manifest is a ``Manifest`` body. ``seeAlso`` links the report
    and the dataset.
    """
    with translation.override(language):
        name = {language: [analysis["name"]]}
        see_also = [
            {
                "id": analysis["permalink"],
                "type": "Text",
                "format": "text/html",
                "label": name,
            }
        ]
        dataset = analysis.get("dataset")
        dataset_url = _dataset_url(dataset)
        if dataset_url:
            link = {"id": dataset_url, "type": "Dataset", "format": "text/html"}
            if dataset.get("label"):
                link["label"] = {language: [dataset["label"]]}
            see_also.append(link)
        metadata = []
        for label, value in (
            (_("Technique"), analysis.get("technique")),
            (_("Dates"), analysis.get("dates")),
            (_("Operators"), analysis.get("operators")),
            (_("Conditions"), analysis.get("conditions")),
            (_("Document"), analysis.get("document")),
            (_("Component"), analysis.get("component")),
        ):
            values = [value] if isinstance(value, str) else list(value or ())
            values = [v for v in values if v]
            if values:
                metadata.append(
                    {"label": {language: [label]}, "value": {language: values}}
                )
        return {
            "id": annotation_id,
            "type": "Annotation",
            "motivation": "supplementing",
            "label": name,
            "body": [b for b in (_body(f, language) for f in files) if b],
            "target": target,
            "seeAlso": see_also,
            "metadata": metadata,
        }
