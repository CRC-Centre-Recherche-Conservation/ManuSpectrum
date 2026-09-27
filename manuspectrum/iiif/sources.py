"""Source manifests and canvases: read, listed, indexed and converted to Presentation 3.

A local manifest (``/manifest/<uuid>``) is read from the database, never over
HTTP; any other is fetched through ``CanvasIIIF``. Legacy hosts
(``EXPLORER_LEGACY_HOSTS``) are rewritten in every id read.
"""

import hashlib
import re
from urllib.parse import urlsplit

from django.conf import settings

from arches.app.models.models import IIIFManifest

from manuspectrum.constants.licenses import iiif_rights
from manuspectrum.iiif import language as lang
from manuspectrum.utils.iiif_tools import CanvasIIIF
from manuspectrum.views.explorer.values import rewrite_legacy_url

_LEVEL = re.compile(r"level([0-2])")


_LOCAL_MANIFEST = re.compile(r"/manifest/(?P<uuid>[0-9a-fA-F-]{36})/?$")


def manifest_json(url):
    """Manifest JSON of *url*: a local ``/manifest/<uuid>`` is read from ``IIIFManifest`` in the database, never over HTTP.

    The path of *url* names the manifest; its query and fragment are ignored.
    """
    url = rewrite_legacy_url(url or "")
    if not url:
        return None
    match = _LOCAL_MANIFEST.search(urlsplit(url).path)
    if match and (
        url.startswith("/") or url.startswith(settings.PUBLIC_SERVER_ADDRESS)
    ):
        stored = (
            IIIFManifest.objects.filter(globalid=match["uuid"])
            .values_list("manifest", flat=True)
            .first()
        )
        return stored if isinstance(stored, dict) else None
    return CanvasIIIF.fetch_manifest(url)


def canvas_label(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for texts in value.values():
            if isinstance(texts, list) and texts:
                return str(texts[0])
    return ""


def canvases_of(manifest):
    """``{"id", "label", "image"}`` of every canvas of a v2 or v3 manifest; legacy hosts rewritten."""
    if not isinstance(manifest, dict):
        return []
    version = CanvasIIIF.detect_version(manifest)
    if version == 3:
        raw = manifest.get("items") or []
    else:
        raw = ((manifest.get("sequences") or [{}])[0] or {}).get("canvases") or []
    found = []
    for canvas in raw:
        canvas_id = canvas.get("id") or canvas.get("@id")
        if not canvas_id:
            continue
        service = (
            CanvasIIIF._get_image_service_url_v3(canvas)
            if version == 3
            else CanvasIIIF._get_image_service_url_v2(canvas)
        )
        width, height = CanvasIIIF.get_canvas_dimensions(canvas)
        found.append(
            {
                "id": rewrite_legacy_url(canvas_id),
                "label": canvas_label(canvas.get("label")),
                "image": {
                    "service": rewrite_legacy_url(service) if service else None,
                    "url": None,
                    "width": int(width),
                    "height": int(height),
                },
            }
        )
    return found


def canvas_index(canvases):
    """``{name: (canvas id, width, height)}`` of each canvas, by its id and by its image service.

    Arches' IIIF viewer stores an annotation under the image service it drew
    (the tile layer's URL), not under the manifest's canvas id; both names
    lead to the canvas.
    """
    index = {}
    for canvas in canvases:
        entry = (canvas["id"], canvas["image"]["width"], canvas["image"]["height"])
        index[canvas["id"].rstrip("/")] = entry
        if canvas["image"]["service"]:
            index[canvas["image"]["service"].rstrip("/")] = entry
    return index


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
            {"label": lang.gettext_map("Attribution"), "value": {"none": [attribution]}}
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
