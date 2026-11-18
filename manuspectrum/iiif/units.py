"""Canvas pixels per stored unit of an annotation zone.

Arches' IIIF viewer stores a zone in the Leaflet CRS.Simple units of the
leaflet-iiif layer it was drawn on, and leaflet-iiif 3.0.0 lays an image of
``width`` x ``height`` pixels over ``size / 2 ** native_zoom`` units
(``native_zoom``). One stored unit is ``2 ** native_zoom`` image pixels: 8,
16, 32… depending on the image's size and on the tile width its info.json
declares, which no manifest carries. ``zone_unit`` reads that info.json
(``image_info``, memoised) and gives the factors to the manifest's canvas
pixels, which differ from the image's when the canvas is declared at another
size.

An info.json that cannot be read leaves an assumed unit: the canvas size
taken as the image's and the tile width of ``IIIF_IMAGE_TILE_HINTS`` for the
host, else leaflet-iiif's own default. A host that refuses this server
(``REFUSED``) gives a stable answer; a failed read (``UNAVAILABLE``) is a
symptom and marks the IIIF memo build degraded.
"""

import logging
import math
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.core.cache import cache

from manuspectrum.iiif import memo
from manuspectrum.utils.budget import BudgetSpent, current_budget, upstream_budget
from manuspectrum.utils.cache import stable_cache_key
from manuspectrum.utils.http import safe_fetch
from manuspectrum.utils.iiif_tools import own_cantaloupe_target

logger = logging.getLogger(__name__)

# The tile width leaflet-iiif 3.0.0 takes when an info.json declares none.
DEFAULT_TILE = 256

# The unit of a zone whose canvas is unknown: no size to derive it from.
UNKNOWN_SCALE = 32

REFUSED = "refused"
UNAVAILABLE = "unavailable"

_INFO_MAX_BYTES = 1024 * 1024
_INFO_PREFIX = "iiif-image-info"
_HOST_PREFIX = "iiif-image-info-host"


@dataclass(frozen=True)
class ImageInfo:
    """What an info.json says of the image leaflet-iiif lays: its size and tile width, in pixels."""

    width: int
    height: int
    tile: int


@dataclass(frozen=True)
class ZoneUnit:
    """Canvas pixels per stored unit on each axis.

    ``read`` tells whether the image's info.json gave them; ``width`` and
    ``height`` are the canvas size a shape is clamped to, None when the unit
    is assumed (the shape then keeps exactly what was stored, times the unit).
    """

    x: float
    y: float
    read: bool
    width: int | None = None
    height: int | None = None

    def payload(self):
        """The ``ZoneUnit`` of the Explorer contract."""
        return {"x": self.x, "y": self.y, "read": self.read}


UNKNOWN_UNIT = ZoneUnit(float(UNKNOWN_SCALE), float(UNKNOWN_SCALE), False)


def native_zoom(width, height, tile=DEFAULT_TILE):
    """leaflet-iiif 3.0.0's ``maxNativeZoom`` of an image: the zoom at which one image pixel is one CRS.Simple unit.

    Same arithmetic as ``_getInfo`` (``ceil(log(x) / LN2)`` on each side over
    the tile width, never below 0).
    """

    def ceil_log2(value):
        return math.ceil(math.log(value) / math.log(2)) if value > 0 else 0

    return max(ceil_log2(width / tile), ceil_log2(height / tile), 0)


def tile_width(info):
    """The tile width leaflet-iiif reads in an info.json: ``tiles[0].width`` (Image API 2 and 3), else ``tile_width`` (1.1), else 256."""
    tiles = info.get("tiles")
    first = tiles[0] if isinstance(tiles, list) and tiles else None
    found = first.get("width") if isinstance(first, dict) else info.get("tile_width")
    return found if _positive(found) else DEFAULT_TILE


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _setting(name, default):
    return getattr(settings, name, default)


def _origin(url):
    return urlsplit(url).netloc.lower()


def _host_key(service):
    return stable_cache_key(_HOST_PREFIX, _origin(service))


def _fetch(service, seconds):
    """The info.json response of *service*, within *seconds* unless the caller already runs under a budget.

    This server's own image service is read from its internal endpoint
    (``own_cantaloupe_target``); any other URL stays under the SSRF guard.
    """
    target, extra = own_cantaloupe_target(f"{service}/info.json")
    timeout = _setting("IIIF_IMAGE_INFO_TIMEOUT", 4)

    def get():
        return safe_fetch(
            target,
            purpose="image_info",
            timeout=(timeout, timeout),
            max_bytes=_INFO_MAX_BYTES,
            throttle=False,
            **extra,
        )

    if current_budget() is not None:
        return get()
    with upstream_budget(seconds):
        return get()


def _parsed(response):
    """``ImageInfo`` of an info.json response, or None when it does not describe an image."""
    try:
        info = response.json()
    except ValueError:
        return None
    if not isinstance(info, dict):
        return None
    width, height = info.get("width"), info.get("height")
    if not (_positive(width) and _positive(height)):
        return None
    return ImageInfo(int(width), int(height), int(tile_width(info)))


def image_info(service, deadline=None):
    """``ImageInfo`` of the image service *service*, ``REFUSED`` or ``UNAVAILABLE``.

    A read is kept ``IIIF_IMAGE_INFO_CACHE_TTL`` seconds. ``REFUSED`` is an
    answer that will not change soon, kept ``IIIF_IMAGE_INFO_REFUSED_TTL``
    seconds: for the whole host after a 403 (a host that blocks servers is
    asked once per period, not once per image), for the one service after any
    other answer that is not an image description, or a URL the SSRF guard
    rejects. ``UNAVAILABLE`` is a failure (transport error, timeout, 429,
    5xx): the host is left alone ``IIIF_IMAGE_INFO_DOWN_TTL`` seconds and
    nothing is kept for the service. *deadline* (``time.monotonic()``) bounds
    the read; past it the answer is ``UNAVAILABLE`` without a request. With
    ``IIIF_IMAGE_INFO_READ`` off nothing is requested and every service is
    ``REFUSED``.
    """
    service = (service or "").rstrip("/")
    if not service or not _setting("IIIF_IMAGE_INFO_READ", True):
        return REFUSED
    key = stable_cache_key(_INFO_PREFIX, service)
    held = cache.get(key)
    if held is not None:
        return ImageInfo(*held) if held else REFUSED
    host = cache.get(_host_key(service))
    if host is not None:
        return host
    left = _setting("IIIF_IMAGE_INFO_TIMEOUT", 4)
    if deadline is not None:
        left = min(left, deadline - time.monotonic())
        if left <= 0:
            return UNAVAILABLE
    refused_ttl = _setting("IIIF_IMAGE_INFO_REFUSED_TTL", 3600)
    try:
        response = _fetch(service, left)
    except (BudgetSpent, requests.exceptions.RequestException) as exc:
        logger.warning("info.json of %s not read: %s", _origin(service), exc)
        cache.set(
            _host_key(service), UNAVAILABLE, _setting("IIIF_IMAGE_INFO_DOWN_TTL", 120)
        )
        return UNAVAILABLE
    except Exception as exc:
        logger.warning("info.json of %s refused: %s", _origin(service), exc)
        cache.set(key, False, refused_ttl)
        return REFUSED
    status = response.status_code
    if status == 429 or status >= 500:
        logger.warning("info.json of %s answered %s", _origin(service), status)
        cache.set(
            _host_key(service), UNAVAILABLE, _setting("IIIF_IMAGE_INFO_DOWN_TTL", 120)
        )
        return UNAVAILABLE
    if status == 403:
        logger.warning("info.json refused by %s (403)", _origin(service))
        cache.set(_host_key(service), REFUSED, refused_ttl)
        return REFUSED
    info = _parsed(response) if status == 200 else None
    if info is None:
        cache.set(key, False, refused_ttl)
        return REFUSED
    cache.set(
        key,
        (info.width, info.height, info.tile),
        _setting("IIIF_IMAGE_INFO_CACHE_TTL", 7 * 24 * 3600),
    )
    return info


def _hinted_tile(service):
    hints = _setting("IIIF_IMAGE_TILE_HINTS", {}) or {}
    found = hints.get(urlsplit(service or "").hostname or "")
    return found if _positive(found) else DEFAULT_TILE


def assumed_unit(width, height, service=None):
    """``ZoneUnit`` of a canvas whose image description was not read: the canvas size taken as the image's, the host's hinted tile width or 256."""
    scale = float(2 ** native_zoom(width, height, _hinted_tile(service)))
    return ZoneUnit(scale, scale, False)


def zone_unit(service, width, height, deadline=None):
    """``ZoneUnit`` of a canvas of *width* x *height* whose image is served by *service* (None without one).

    With the info.json read, one stored unit is ``2 ** native_zoom`` image
    pixels, brought to canvas pixels by the ratio of the two sizes on each
    axis. Otherwise the unit is assumed (``assumed_unit``); a failed read
    marks the IIIF memo build degraded, a refusal does not.
    """
    info = image_info(service, deadline) if service else REFUSED
    if isinstance(info, ImageInfo):
        scale = 2 ** native_zoom(info.width, info.height, info.tile)
        if not (width > 0 and height > 0):
            width, height = info.width, info.height
        return ZoneUnit(
            scale * width / info.width,
            scale * height / info.height,
            True,
            width,
            height,
        )
    if info == UNAVAILABLE:
        memo.mark_degraded()
    return assumed_unit(width, height, service)


class UnitReader:
    """The units of one manifest's canvases, each read once, all reads within ``IIIF_IMAGE_INFO_DEADLINE`` seconds of the first."""

    def __init__(self):
        self._units = {}
        self._deadline = None

    def __call__(self, canvas, service, width, height):
        if canvas not in self._units:
            if self._deadline is None:
                self._deadline = time.monotonic() + _setting(
                    "IIIF_IMAGE_INFO_DEADLINE", 6
                )
            self._units[canvas] = zone_unit(service, width, height, self._deadline)
        return self._units[canvas]

    def used(self, canvas):
        """The unit given for *canvas* so far, or None."""
        return self._units.get(canvas)
