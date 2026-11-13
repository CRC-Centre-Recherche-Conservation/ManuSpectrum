"""Source manifests and canvases: read, listed, indexed and converted to Presentation 3.

A local manifest (``/manifest/<uuid>``) is read from the database, never over
HTTP; any other is fetched through ``CanvasIIIF``. Legacy hosts
(``EXPLORER_LEGACY_HOSTS``) are rewritten in every id read.

The IIIF output names a local manifest at ``ids.stored_manifest`` (see
``manifest_id``), the route serving ``published_manifest``. A manifest
imported from another institution keeps its publisher's URL in
``IIIFManifest.url``: ``manifest_source`` gives it wherever the output links
to the source; the server never fetches it.
"""

import hashlib
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings
from django.db.models import Q

from arches.app.models.models import IIIFManifest

from manuspectrum.constants.licenses import iiif_rights
from manuspectrum.iiif import ids
from manuspectrum.iiif import language as lang
from manuspectrum.utils.iiif_tools import CanvasIIIF
from manuspectrum.views.explorer.values import rewrite_legacy_url

_LEVEL = re.compile(r"level([0-2])")


_LOCAL_MANIFEST = re.compile(r"/manifest/(?P<uuid>[0-9a-fA-F-]{36})/?$")


def local_manifest_uuid(url):
    """The uuid a local ``/manifest/<uuid>`` URL (legacy host already rewritten) names, else None."""
    match = _LOCAL_MANIFEST.search(urlsplit(url).path)
    if match and (
        url.startswith("/") or url.startswith(settings.PUBLIC_SERVER_ADDRESS)
    ):
        return match["uuid"]
    return None


def local_manifest_id(url):
    """The canonical ``globalid`` of the stored manifest a local *url* names (``local_manifest_uuid`` after ``rewrite_legacy_url``), else None."""
    local = local_manifest_uuid(rewrite_legacy_url(url)) if url else None
    try:
        return str(uuid.UUID(local)) if local else None
    except ValueError:
        return None


def manifest_id(url):
    """The id the IIIF output gives the manifest a tile names by *url*.

    A local ``/manifest/<uuid>`` is ``ids.stored_manifest``, which serves the
    stored JSON under that id (``published_manifest``), readable cross-origin
    whatever its publisher's CORS; any other site path is made absolute; an
    external URL is unchanged.
    """
    globalid = local_manifest_id(url)
    if globalid:
        return ids.stored_manifest(globalid)
    return absolute_url(url) or url


@dataclass(frozen=True)
class ManifestSource:
    """Where a manifest reference comes from: the publisher's URL (None for a manifest created here) and the stored label."""

    original: str | None
    label: str | None


def _is_external(url):
    """Whether *url* is an absolute http(s) URL that is not a local manifest."""
    return (
        isinstance(url, str)
        and url.startswith(("http://", "https://"))
        and local_manifest_uuid(rewrite_legacy_url(url)) is None
    )


def original_url(row_url):
    """The publisher's URL an ``IIIFManifest.url`` holds (an imported manifest), else None."""
    return row_url if _is_external(row_url) else None


def manifest_sources(urls):
    """``{url: ManifestSource}`` of the manifest references among *urls*, read in one query.

    A local reference (``local_manifest_id``) takes its row's label; its
    ``original`` is the row's ``url`` when that is an absolute http(s) URL
    that is not itself local (an imported manifest), else None (a manifest
    created here). A raw external http(s) URL is its own ``original``, with
    the label of a row carrying that url when there is one. An empty URL, an
    unknown local id and anything else are left out. Nothing is fetched.
    """
    local, external = {}, set()
    for url in set(urls):
        if not url:
            continue
        globalid = local_manifest_id(url)
        if globalid:
            local[url] = uuid.UUID(globalid)
        elif _is_external(url):
            external.add(url)
    if not local and not external:
        return {}
    rows = IIIFManifest.objects.filter(
        Q(globalid__in=set(local.values())) | Q(url__in=external)
    ).values_list("globalid", "url", "label")
    by_id, by_url = {}, {}
    for globalid, row_url, label in rows:
        by_id[globalid] = (row_url, label)
        by_url.setdefault(row_url, label)
    found = {}
    for url, globalid in local.items():
        if globalid in by_id:
            row_url, label = by_id[globalid]
            found[url] = ManifestSource(original_url(row_url), label)
    for url in external:
        found[url] = ManifestSource(url, by_url.get(url))
    return found


def manifest_source(url):
    """The ``ManifestSource`` of one reference (``manifest_sources``), or None."""
    return manifest_sources([url]).get(url)


def published_manifest(manifest, globalid, original=None):
    """The stored *manifest* of *globalid* as ``ids.stored_manifest`` serves it.

    Legacy hosts are rewritten in every id, as everywhere a manifest is read
    here, so its canvases keep the ids the annotations target. Its own ``id``
    (``@id`` in Presentation 2) is always ``ids.stored_manifest``: a
    manifest's id is the URL it is published at. *original*, the publisher's
    URL of an imported manifest, is added to ``seeAlso`` beside any entry the
    manifest already has, unless one already names it.
    """
    published = _rewritten(manifest)
    for key in ("id", "@id"):
        if isinstance(published.get(key), str):
            published[key] = ids.stored_manifest(globalid)
    if original:
        _link_original(published, original)
    return published


def _link_original(published, original):
    """Add *original* to ``published["seeAlso"]`` in the form of the manifest's Presentation version."""
    if CanvasIIIF.detect_version(published) == 3:
        entry = {
            "id": original,
            "type": "Dataset",
            "format": "application/ld+json",
            "profile": "http://iiif.io/api/presentation/3/context.json",
        }
    else:
        entry = {
            "@id": original,
            "format": "application/ld+json",
            "profile": "http://iiif.io/api/presentation/2/context.json",
        }
    existing = published.get("seeAlso")
    if existing is None:
        existing = []
    elif not isinstance(existing, list):
        existing = [existing]
    for item in existing:
        named = item.get("id") or item.get("@id") if isinstance(item, dict) else item
        if named == original:
            published["seeAlso"] = existing
            return
    published["seeAlso"] = [*existing, entry]


def manifest_json(url):
    """Manifest JSON of *url*: a local ``/manifest/<uuid>`` is read from ``IIIFManifest`` in the database, never over HTTP.

    The path of *url* names the manifest; its query and fragment are ignored.
    """
    url = rewrite_legacy_url(url or "")
    if not url:
        return None
    local = local_manifest_uuid(url)
    if local:
        stored = (
            IIIFManifest.objects.filter(globalid=local)
            .values_list("manifest", flat=True)
            .first()
        )
        return stored if isinstance(stored, dict) else None
    return CanvasIIIF.fetch_manifest(url)


def local_manifests(urls):
    """``{url: manifest JSON}`` of the local manifests among *urls*, read in one query, as ``manifest_json`` reads each.

    A URL that is not local, or names no valid uuid, is left out.
    """
    wanted = {}
    for url in urls:
        key = local_manifest_id(url) if url else None
        wanted[url] = uuid.UUID(key) if key else None
    wanted = {url: key for url, key in wanted.items() if key}
    if not wanted:
        return {}
    stored = dict(
        IIIFManifest.objects.filter(globalid__in=set(wanted.values())).values_list(
            "globalid", "manifest"
        )
    )
    return {
        url: stored[key] if isinstance(stored.get(key), dict) else None
        for url, key in wanted.items()
    }


class ManifestReader:
    """*read* (``manifest_json``) memoised: each URL is read once; ``prime`` reads the local ones of many URLs in one query."""

    def __init__(self, read=manifest_json):
        self._read = read
        self._found = {}

    def __call__(self, url):
        if url not in self._found:
            self._found[url] = self._read(url)
        return self._found[url]

    def prime(self, urls):
        """Read the local manifests among *urls* not read yet, in one query."""
        self._found.update(local_manifests({u for u in urls if u not in self._found}))


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
