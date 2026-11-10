import logging
import sys

from django.conf import settings
from django.core.cache import cache

from arches.app.utils.search_thumbnail_fetcher import SearchThumbnailFetcher
from arches.app.utils.search_thumbnail_fetcher_factory import (
    SearchThumbnailFetcherFactory,
)
from manuspectrum.iiif.sources import ManifestReader, canvases_of, manifest_json
from manuspectrum.utils.http import safe_fetch
from manuspectrum.utils.iiif_tools import (
    CanvasIIIF,
    BBoxCalculator,
    own_cantaloupe_target,
)
from manuspectrum.utils.cache import stable_cache_key
from manuspectrum.utils.manifest_values import first_manifest_url
from manuspectrum.views.explorer.values import rewrite_legacy_url

logger = logging.getLogger(__name__)

# Longest side, in pixels, a region thumbnail is asked at.
THUMBNAIL_SIZE = 300

# Zoom of annotation coordinates (``BBoxCalculator``) and the factor of a
# Point's view radius.
ANNOTATION_ZOOM = 5
POINT_CONTEXT = 5

# Zone point radius when the annotation states none.
DEFAULT_POINT_RADIUS = 10

_NO_SOURCE = object()

# The shared session asks for JSON-LD (it exists for manifests); an image
# request has to say what it is actually after.
_IMAGE_HEADERS = {"Accept": "image/*,*/*;q=0.8"}


def _fetch_thumbnail(url):
    """Guarded GET of a thumbnail; this server's own image service is read internally."""
    target, extra = own_cantaloupe_target(url)
    return safe_fetch(target, headers=_IMAGE_HEADERS, purpose="thumbnail", **extra)


# Leading bytes of the formats a IIIF Image API server answers with. WebP is
# not here: its marker sits at offset 8, and _sniff_image_type handles it.
_IMAGE_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
    (b"\x00\x00\x00\x0cjP  \r\n\x87\n", "image/jp2"),
)


def _sniff_image_type(content):
    """The image type *content* actually is, or None."""
    for signature, content_type in _IMAGE_SIGNATURES:
        if content.startswith(signature):
            return content_type
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _image_payload(response):
    """``(bytes, content_type)`` for a usable image answer, or None.

    A thumbnail is relayed to the browser under this site's own origin, so
    what an image server sends is only accepted once its first bytes are an
    image format, and it is served as the format they name — never as whatever
    the provider (or whatever answered in its place) declared. A declared
    non-image type is refused outright: that is an error page, not a thumbnail.
    """
    if response.status_code != 200:
        logger.warning(
            "Thumbnail fetch returned %s for %s", response.status_code, response.url
        )
        return None
    declared = (response.headers.get("Content-Type") or "").split(";")[0].strip()
    if declared and not declared.lower().startswith("image/"):
        logger.warning("Refusing %r thumbnail from %s", declared, response.url)
        return None
    content_type = _sniff_image_type(response.content)
    if content_type is None:
        logger.warning("Refusing thumbnail from %s: not an image", response.url)
        return None
    return (response.content, content_type)


def _miss_key(resource):
    return stable_cache_key("search-thumbnail-miss", resource.resourceinstanceid)


def _recent_miss(resource):
    """Whether a retrieval for *resource* ended without an image within ``SEARCH_THUMBNAIL_MISS_TTL``."""
    try:
        return bool(cache.get(_miss_key(resource)))
    except Exception:
        return False


def _remember_miss(resource):
    try:
        cache.set(_miss_key(resource), True, settings.SEARCH_THUMBNAIL_MISS_TTL)
    except Exception:
        logger.warning("Search thumbnail miss flag not stored", exc_info=True)


def _region_size(width, height):
    """The IIIF ``w,`` size of a *width* x *height* region: bounded by ``THUMBNAIL_SIZE``, never larger than the region."""
    longest = max(width, height)
    if longest <= THUMBNAIL_SIZE:
        return width
    return max(1, round(width * THUMBNAIL_SIZE / longest))


def _region_url(service, bbox):
    x, y, w, h = bbox
    return f"{service}/{x},{y},{w},{h}/{_region_size(w, h)},/0/default.jpg"


def _canvas_names(manifest):
    """``{name: (image service, width, height)}`` of a manifest's canvases, by canvas id and by image service."""
    names = {}
    for canvas in canvases_of(manifest):
        image = canvas["image"]
        entry = (image["service"], image["width"], image["height"])
        names[canvas["id"].rstrip("/")] = entry
        if image["service"]:
            names[image["service"].rstrip("/")] = entry
    return names


def _extent(geometry, radius):
    """``(xmin, ymin, xmax, ymax)`` of a Polygon or Point in canvas pixels, margins excluded; None when not computable."""
    scale = 2**ANNOTATION_ZOOM
    coordinates = geometry.get("coordinates")
    try:
        if geometry.get("type") == "Polygon":
            ring = coordinates[0]
            xs = [lng * scale for lng, lat in ring]
            ys = [-lat * scale for lng, lat in ring]
            reach = 0
        else:
            xs = [coordinates[0] * scale]
            ys = [-coordinates[1] * scale]
            reach = radius * POINT_CONTEXT
        return min(xs) - reach, min(ys) - reach, max(xs) + reach, max(ys) + reach
    except Exception:
        return None


def _zone_region_url(annotation, manifests):
    """IIIF region URL of one annotation zone, or None when it cannot be shown.

    Polygons and Points are accepted. The zone's canvas is found in its
    manifest by id or image service, and the region is asked of that canvas's
    image service (the stored name when the canvas is unknown or has none). A
    canvas missing from the manifest does not clamp the region. A zone drawn
    outside a known canvas gives None.
    """
    feature = annotation.feature or {}
    properties = feature.get("properties") or {}
    stored = rewrite_legacy_url(annotation.canvas or "")
    manifest_url = properties.get("manifest")
    geometry = feature.get("geometry") or {}
    if not stored or not manifest_url or not geometry.get("coordinates"):
        return None
    if geometry.get("type") not in ("Polygon", "Point"):
        return None
    names = manifests.names(manifest_url)
    if names is None:
        return None
    service, width, height = names.get(stored.rstrip("/")) or (
        None,
        sys.maxsize,
        sys.maxsize,
    )
    service = (service or stored).rstrip("/")

    radius = properties.get("radius", DEFAULT_POINT_RADIUS)
    if width != sys.maxsize:
        extent = _extent(geometry, radius)
        if extent is None:
            return None
        xmin, ymin, xmax, ymax = extent
        if xmax <= 0 or ymax <= 0 or xmin >= width or ymin >= height:
            return None
    if geometry["type"] == "Polygon":
        bbox = BBoxCalculator.polygon_bbox(geometry["coordinates"], width, height)
    else:
        bbox = BBoxCalculator.point_bbox(
            geometry["coordinates"], width, height, radius=radius
        )
    if not bbox or bbox[2] <= 0 or bbox[3] <= 0:
        return None
    return _region_url(service, bbox)


class _Manifests:
    """The manifests one search reads, each read once, with its canvas names.

    ``names`` is None for a manifest that cannot be read; ``unreadable`` then
    lists it.
    """

    def __init__(self):
        self._reader = ManifestReader()
        self._names = {}
        self.unreadable = []

    def names(self, url):
        if url not in self._names:
            manifest = self._reader(url)
            if manifest:
                self._names[url] = _canvas_names(manifest)
            else:
                self._names[url] = None
                self.unreadable.append(url)
        return self._names[url]


def _zone_payload(resource):
    """The image of the first zone of *resource* that has a region, or None.

    Zones are taken in feature id order, the Explorer's first zone. Only that
    zone's image is requested: its failure ends the search, and so does a
    manifest that cannot be read.
    """
    from arches.app.models.models import VwAnnotation

    manifests = _Manifests()

    for annotation in VwAnnotation.objects.filter(resourceinstance=resource).order_by(
        "feature_id"
    ):
        url = _zone_region_url(annotation, manifests)
        if url:
            return _image_payload(_fetch_thumbnail(url))
        if manifests.unreadable:
            return None
    return None


def _has_zone(resource):
    from arches.app.models.models import VwAnnotation

    return VwAnnotation.objects.filter(resourceinstance=resource).exists()


def _manifest_url(resource):
    from arches.app.models.models import TileModel

    tiles = TileModel.objects.filter(
        resourceinstance=resource, nodegroup__node__datatype="manifest"
    )
    return first_manifest_url(value for tile in tiles for value in tile.data.values())


def _manifest_payload(manifest_url):
    """The image of a manifest's thumbnail, or None."""
    manifest = manifest_json(manifest_url)
    if not manifest:
        return None
    thumbnail_url = CanvasIIIF.get_thumbnail_url(manifest)
    if not thumbnail_url:
        return None
    return _image_payload(_fetch_thumbnail(thumbnail_url))


class _SourceFetcher(SearchThumbnailFetcher):
    """Shared contract of the search-thumbnail fetchers.

    With ``retrieve=False`` the answer is ``True`` when the resource has a
    thumbnail source and ``None`` when it has none, without any network call;
    ``False`` is never returned. With ``retrieve=True`` it is
    ``(bytes, content_type)`` or ``None``. A retrieval over an existing source
    that ends without an image is remembered for
    ``SEARCH_THUMBNAIL_MISS_TTL`` seconds, and both modes answer ``None`` from
    that memory without reading anything else. A resource fixed within that
    time keeps answering no thumbnail until the flag expires.

    A subclass defines ``_has_source()`` and ``_payload()``: the image, None
    when a source gave none, ``_NO_SOURCE`` when there is no source.
    """

    def get_thumbnail(self, retrieve=False):
        if _recent_miss(self.resource):
            return None
        if not retrieve:
            try:
                return True if self._has_source() else None
            except Exception:
                logger.exception("Error checking thumbnail existence")
                return None
        try:
            payload = self._payload()
        except Exception:
            logger.exception(
                "Error fetching thumbnail for resource %s",
                self.resource.resourceinstanceid,
            )
            payload = None
        if payload is _NO_SOURCE:
            return None
        if payload is None:
            _remember_miss(self.resource)
        return payload


@SearchThumbnailFetcherFactory.register("0c8226c1-11a9-4c48-9601-a7a0c6f2df6b")
class DocumentThumbnailFetcher(_SourceFetcher):
    """
    Fetcher for Documents: the thumbnail of the IIIF manifest (v2/v3) named by
    the first of the Document's 'manifest' values that is a manifest URL
    (``first_manifest_url``). An Arches-hosted manifest (``/manifest/<uuid>``)
    is read from the database, any other over HTTP.
    """

    def _has_source(self):
        return _manifest_url(self.resource) is not None

    def _payload(self):
        manifest_url = _manifest_url(self.resource)
        if not manifest_url:
            return _NO_SOURCE
        return _manifest_payload(manifest_url)


@SearchThumbnailFetcherFactory.register("d47595b4-f8a6-419c-8f33-b388206280c4")
class ComponentThumbnailFetcher(_SourceFetcher):
    """
    Fetcher for resources with IIIF annotations: the region of the first usable
    zone (Polygon or Point), by the IIIF Image API.
    """

    def _has_source(self):
        return _has_zone(self.resource)

    def _payload(self):
        if not _has_zone(self.resource):
            return _NO_SOURCE
        return _zone_payload(self.resource)


@SearchThumbnailFetcherFactory.register("60c85aba-f079-45bc-997f-21cdd4f77b6d")
class AnalysisThumbnailFetcher(_SourceFetcher):
    """
    Fetcher for analysis resources with manifest or IIIF annotations.
    Priority:
    1. Manifest thumbnail, from the first manifest URL among the manifest tiles
       (any failure of that step falls through to the annotation)
    2. Annotation-based thumbnail: the region of the first usable zone
    """

    def _has_source(self):
        return _manifest_url(self.resource) is not None or _has_zone(self.resource)

    def _payload(self):
        manifest_url = _manifest_url(self.resource)
        if manifest_url:
            try:
                payload = _manifest_payload(manifest_url)
            except Exception as e:
                logger.warning(
                    f"Manifest thumbnail unavailable for resource {self.resource.resourceinstanceid}: {e}"
                )
                payload = None
            if payload:
                return payload
        if not _has_zone(self.resource):
            return None if manifest_url else _NO_SOURCE
        return _zone_payload(self.resource)
