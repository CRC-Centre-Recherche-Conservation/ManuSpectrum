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
host, else leaflet-iiif's own default (an image served by this platform's own
image server is assumed tiled at ``IIIF_OWN_IMAGE_TILE``). A host that refuses this server
(``REFUSED``) gives a stable answer; a failed read (``UNAVAILABLE``) is a
symptom and marks the IIIF memo build degraded.

The conversion holds for the tiling served when the zone was drawn:
re-encoding an image or changing Cantaloupe's tile size moves its existing
unstamped zones, and the drawing of ``estimated`` ones over the live layer (a
measured frame keeps its place); a read is kept
``IIIF_IMAGE_INFO_CACHE_TTL`` seconds for reading zones, and a frame is stamped
only from a read at most ``IIIF_IMAGE_INFO_STAMP_MAX_AGE`` seconds old.

A ``Frame`` is the image frame a zone was drawn in, stamped on the zone: its
unit and the image size it was measured against, so its pixel position no
longer depends on the live image host (``frames.py`` stamps, ``unit_of_frame``
reads). A frame whose ``source`` is ``estimated`` was assumed, not measured.

The stamps rest on what Arches' IIIF viewer and leaflet-iiif do: the layer is
built without a ``tileSize`` and sets ``x``, ``y`` and ``maxNativeZoom`` from
the info.json, and the annotation card returns each feature with its id,
``properties.canvas`` and the geometry Leaflet wrote. At an Arches or
leaflet-iiif upgrade, ``tests/test_arches_pins.py`` (``ZoneFrameContractTests``)
fails when one of these moves; compare ``native_zoom`` with leaflet-iiif's
``_getInfo`` then.
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
from manuspectrum.utils.http import UnsafeURLError, safe_fetch
from manuspectrum.utils.iiif_tools import own_cantaloupe_target

logger = logging.getLogger(__name__)

# The tile width leaflet-iiif 3.0.0 takes when an info.json declares none.
DEFAULT_TILE = 256

# The unit of a zone whose canvas is unknown: no size to derive it from.
UNKNOWN_SCALE = 32

# The tile width assumed for this platform's own image server (Cantaloupe 5's
# ``endpoint.iiif.min_tile_size``).
DEFAULT_OWN_TILE = 512

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

    ``read`` tells whether the unit was measured: the image's info.json gave
    it, or the zone carries a stamp of a measured frame. ``width`` and
    ``height`` are the canvas size a shape is clamped to, None when the unit
    is assumed or estimated (the shape then keeps exactly what was stored,
    times the unit).
    """

    x: float
    y: float
    read: bool
    width: int | None = None
    height: int | None = None

    def payload(self):
        """The ``ZoneUnit`` of the Explorer contract."""
        return {"x": self.x, "y": self.y, "read": self.read}


FRAME_SOURCES = ("browser", "read", "estimated", "import-legacy")
ESTIMATED = "estimated"
MAX_UNIT = 2**20
MAX_FRAME_SIDE = 1_000_000


@dataclass(frozen=True)
class Frame:
    """The image frame of a zone: stored units are ``unit`` pixels of a ``width`` x ``height`` image.

    ``source`` is ``browser``, ``read`` or ``import-legacy`` for a measured
    frame, ``estimated`` for an assumed one.
    """

    unit: int
    width: int
    height: int
    source: str

    def __post_init__(self):
        for name, high in (
            ("unit", MAX_UNIT),
            ("width", MAX_FRAME_SIDE),
            ("height", MAX_FRAME_SIDE),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"frame {name} must be an int: {value!r}")
            if not 1 <= value <= high:
                raise ValueError(f"frame {name} out of range: {value}")
        if self.unit & (self.unit - 1):
            raise ValueError(f"frame unit must be a power of two: {self.unit}")
        if self.source not in FRAME_SOURCES:
            raise ValueError(f"unknown frame source: {self.source!r}")

    @property
    def measured(self):
        """True unless the frame was assumed (``estimated``) rather than measured."""
        return self.source != ESTIMATED

    def stamp(self):
        """The four feature properties that store this frame."""
        return {
            "msUnit": self.unit,
            "msImageWidth": self.width,
            "msImageHeight": self.height,
            "msFrame": self.source,
        }


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
    return int(found) if _whole(found) else DEFAULT_TILE


def _whole(value):
    """True for a finite whole number of at least 1 (not a bool)."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value >= 1
    return isinstance(value, float) and value.is_integer() and value >= 1


def _setting(name, default):
    return getattr(settings, name, default)


def _origin(url):
    return urlsplit(url).netloc.lower()


def _host_key(service):
    return stable_cache_key(_HOST_PREFIX, _origin(service))


def _fetch(service, seconds):
    """The info.json response of *service*, within *seconds* unless the caller already runs under a budget.

    This server's own image service is read from its internal endpoint
    (``own_cantaloupe_target``) without the per-host throttle; any other URL
    stays under the SSRF guard and the throttle.
    """
    target, extra = own_cantaloupe_target(f"{service}/info.json")
    timeout = _setting("IIIF_IMAGE_INFO_TIMEOUT", 4)

    def get():
        return safe_fetch(
            target,
            purpose="image_info",
            timeout=(timeout, timeout),
            max_bytes=_INFO_MAX_BYTES,
            throttle=not extra,
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
    if not (_whole(width) and _whole(height)):
        return None
    return ImageInfo(int(width), int(height), tile_width(info))


def _kept(held, max_age):
    """The ``ImageInfo`` of a positive cache entry *held* (width, height, tile, fetch time), or None.

    None as well for an entry older than *max_age* seconds, or of another shape.
    """
    if not (isinstance(held, (tuple, list)) and len(held) == 4):
        return None
    width, height, tile, fetched = held
    if max_age is not None and time.time() - fetched > max_age:
        return None
    return ImageInfo(width, height, tile)


def stamp_max_age():
    """The age in seconds past which a kept image description is read again before a frame is stamped from it."""
    return _setting("IIIF_IMAGE_INFO_STAMP_MAX_AGE", 3600)


def image_info(service, deadline=None, max_age=None):
    """``ImageInfo`` of the image service *service*, ``REFUSED`` or ``UNAVAILABLE``.

    A read is kept ``IIIF_IMAGE_INFO_CACHE_TTL`` seconds with its fetch time;
    with *max_age* a kept read older than *max_age* seconds is read again (the
    new read replaces it), while a kept ``REFUSED`` or a host noted down still
    answers without a request. ``REFUSED`` is an
    answer that will not change soon, kept ``IIIF_IMAGE_INFO_REFUSED_TTL``
    seconds: for the whole host after a 403 (a host that blocks servers is
    asked once per period, not once per image), for the one service after any
    other answer that is not an image description, or a URL the SSRF guard
    rejects. ``UNAVAILABLE`` is a failure (transport error, timeout, 429,
    5xx, a host name that does not resolve): the host is left alone
    ``IIIF_IMAGE_INFO_DOWN_TTL`` seconds and nothing is kept for the service.
    A failure caused by this server's own time cap (``BudgetSpent``, or a
    timeout under a read bound shorter than ``IIIF_IMAGE_INFO_TIMEOUT``) is
    ``UNAVAILABLE`` without a verdict on the host. *deadline*
    (``time.monotonic()``) bounds the read; past it the answer is
    ``UNAVAILABLE`` without a request. With
    ``IIIF_IMAGE_INFO_READ`` off nothing is requested and every service is
    ``REFUSED``.
    """
    service = (service or "").rstrip("/")
    if not service or not _setting("IIIF_IMAGE_INFO_READ", True):
        return REFUSED
    key = stable_cache_key(_INFO_PREFIX, service)
    held = cache.get(key)
    if held is False:
        return REFUSED
    kept = _kept(held, max_age)
    if kept is not None:
        return kept
    host = cache.get(_host_key(service))
    if host is not None:
        return host
    left = _setting("IIIF_IMAGE_INFO_TIMEOUT", 4)
    if deadline is not None:
        left = min(left, deadline - time.monotonic())
        if left <= 0:
            return UNAVAILABLE
    refused_ttl = _setting("IIIF_IMAGE_INFO_REFUSED_TTL", 3600)
    timeout = _setting("IIIF_IMAGE_INFO_TIMEOUT", 4)
    ambient = current_budget()
    capped = left < timeout or (ambient is not None and ambient.left() < timeout)
    down_ttl = _setting("IIIF_IMAGE_INFO_DOWN_TTL", 120)
    try:
        response = _fetch(service, left)
    except BudgetSpent:
        logger.warning("info.json of %s not read: time budget spent", _origin(service))
        return UNAVAILABLE
    except requests.exceptions.RequestException as exc:
        logger.warning("info.json of %s not read: %s", _origin(service), exc)
        if not (capped and isinstance(exc, requests.exceptions.Timeout)):
            cache.set(_host_key(service), UNAVAILABLE, down_ttl)
        return UNAVAILABLE
    except UnsafeURLError as exc:
        if exc.reason == "dns":
            logger.warning("info.json of %s not read: %s", _origin(service), exc)
            cache.set(_host_key(service), UNAVAILABLE, down_ttl)
            return UNAVAILABLE
        logger.warning("info.json of %s refused: %s", _origin(service), exc)
        cache.set(key, False, refused_ttl)
        return REFUSED
    except Exception as exc:
        logger.warning("info.json of %s refused: %s", _origin(service), exc)
        cache.set(key, False, refused_ttl)
        return REFUSED
    status = response.status_code
    if status == 429 or status >= 500:
        logger.warning("info.json of %s answered %s", _origin(service), status)
        cache.set(_host_key(service), UNAVAILABLE, down_ttl)
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
        (info.width, info.height, info.tile, time.time()),
        _setting("IIIF_IMAGE_INFO_CACHE_TTL", 7 * 24 * 3600),
    )
    return info


def known_info(service, max_age=None):
    """The kept ``ImageInfo`` of *service*, or None: the cache is read, nothing is requested and no host is noted.

    With *max_age*, a read older than *max_age* seconds counts as not kept.
    """
    service = (service or "").rstrip("/")
    if not service:
        return None
    return _kept(cache.get(stable_cache_key(_INFO_PREFIX, service)), max_age)


def _hinted_tile(service):
    hints = _setting("IIIF_IMAGE_TILE_HINTS", {}) or {}
    found = hints.get(urlsplit(service or "").hostname or "")
    if _whole(found):
        return int(found)
    own = (getattr(settings, "CANTALOUPE_HTTP_ENDPOINT", "") or "").rstrip("/") + "/"
    if own != "/" and (service or "").startswith(own):
        return _setting("IIIF_OWN_IMAGE_TILE", DEFAULT_OWN_TILE)
    return DEFAULT_TILE


def assumed_unit(width, height, service=None):
    """``ZoneUnit`` of a canvas whose image description was not read: the canvas size taken as the image's, the host's hinted tile width or 256."""
    scale = float(2 ** native_zoom(width, height, _hinted_tile(service)))
    return ZoneUnit(scale, scale, False)


def frame_from_info(info, source="read"):
    """The ``Frame`` of an image described by *info*."""
    return Frame(
        2 ** native_zoom(info.width, info.height, info.tile),
        info.width,
        info.height,
        source,
    )


def frame_assumed(service, width, height):
    """The ``estimated`` ``Frame`` of an image of *width* x *height* whose info.json was not read: the host's hinted tile width or 256."""
    unit = 2 ** native_zoom(width, height, _hinted_tile(service))
    return Frame(unit, width, height, ESTIMATED)


def unit_of_info(info, width, height):
    """``ZoneUnit`` of a canvas of *width* x *height* whose image is described by *info*.

    One stored unit is ``2 ** native_zoom`` image pixels, brought to canvas
    pixels by the ratio of the two sizes on each axis; a size that is not
    positive counts as unknown and the image's size stands for the canvas'.
    """
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


def unit_of_frame(frame, canvas_width, canvas_height):
    """``ZoneUnit`` of a canvas of *canvas_width* x *canvas_height* for a zone drawn in *frame*.

    The unit is brought to canvas pixels by the ratio of the canvas size to the
    frame's image size on each axis; a size of 0 or None counts as unknown and
    the frame's size stands for the canvas'. ``read`` tells whether the frame
    was measured. An ``estimated`` frame follows the assumed-unit rule: no
    clamp size, so the shape keeps exactly what was stored, times the unit.
    """
    if not (canvas_width and canvas_height and canvas_width > 0 and canvas_height > 0):
        canvas_width, canvas_height = frame.width, frame.height
    return ZoneUnit(
        frame.unit * canvas_width / frame.width,
        frame.unit * canvas_height / frame.height,
        frame.measured,
        canvas_width if frame.measured else None,
        canvas_height if frame.measured else None,
    )


def zone_unit(service, width, height, deadline=None):
    """``ZoneUnit`` of a canvas of *width* x *height* whose image is served by *service* (None without one).

    With the info.json read, the unit is ``unit_of_info``. Otherwise it is
    assumed (``assumed_unit``); a failed read marks the IIIF memo build
    degraded, a refusal does not.
    """
    info = image_info(service, deadline) if service else REFUSED
    if isinstance(info, ImageInfo):
        return unit_of_info(info, width, height)
    if info == UNAVAILABLE:
        memo.mark_degraded()
    return assumed_unit(width, height, service)


class UnitReader:
    """The units of one manifest's canvases, each read once, all reads within ``IIIF_IMAGE_INFO_DEADLINE`` seconds of the first."""

    def __init__(self):
        self._units = {}
        self._noted = {}
        self._deadline = None

    def __call__(self, canvas, service, width, height):
        if canvas not in self._units:
            if self._deadline is None:
                self._deadline = time.monotonic() + _setting(
                    "IIIF_IMAGE_INFO_DEADLINE", 6
                )
            self._units[canvas] = zone_unit(service, width, height, self._deadline)
        return self._units[canvas]

    def note(self, canvas, unit):
        """Record the *unit* a stamped zone was converted with.

        The first one noted stands; in ``used``, a unit taken from the canvas's
        image description (or assumed when it was not read) wins over a unit
        noted from a stamp.
        """
        self._noted.setdefault(canvas, unit)

    def used(self, canvas):
        """The unit given for *canvas* so far (taken from its image description or assumed, else noted from a stamp), or None."""
        return self._units.get(canvas) or self._noted.get(canvas)
