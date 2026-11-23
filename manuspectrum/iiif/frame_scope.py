"""Pure helpers of the ``annotation_frames`` verbs: the browser-measured frames file and the rebase arithmetic.

The file is written by the console script of ``verify --refused-out`` and read
by ``--frames``. Format::

    {"version": 1, "measured_at": "<ISO 8601>", "origin": "<https://host>",
     "frames": [{"service": "<id>", "info": {"width": int, "height": int,
                                              "tiles": [...]?, "tile_width": int?}}],
     "failed": [["<service>", "<reason>"]]}

``info`` holds raw ``info.json`` fields; ``units.info_from_json`` decides what
they mean.
"""

import json
from dataclasses import dataclass

from manuspectrum.iiif import frames, units
from manuspectrum.views.explorer.values import rewrite_legacy_url

FRAMES_FILE_VERSION = 1


@dataclass(frozen=True)
class FramesFile:
    """The content of a frames file: usable image descriptions by service, and the services it could not measure."""

    frames: dict
    failed: list
    measured_at: str
    origin: str


def read_frames_file(path):
    """The ``FramesFile`` at *path*; ValueError, whose message is the reason, when the file cannot be used.

    Services are normalised with ``rewrite_legacy_url(...).rstrip("/")``. An
    entry that is not an image description is listed in ``failed`` with its
    reason, after the services the script itself could not measure.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            body = json.load(handle)
    except UnicodeDecodeError as error:
        raise ValueError(f"not UTF-8 text ({error})") from error
    except OSError as error:
        raise ValueError(f"cannot read the frames file: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"not JSON ({error})") from error
    if not isinstance(body, dict):
        raise ValueError("the frames file is not a JSON object")
    if body.get("version") != FRAMES_FILE_VERSION:
        raise ValueError(
            f"unsupported version {body.get('version')!r} (expected {FRAMES_FILE_VERSION})"
        )
    for key in ("measured_at", "origin"):
        if not isinstance(body.get(key), str) or not body[key]:
            raise ValueError(f"{key} is missing")
    entries = body.get("frames")
    if not isinstance(entries, list):
        raise ValueError("frames is not a list")
    failed = []
    for item in body.get("failed") or []:
        if (
            isinstance(item, (list, tuple))
            and len(item) == 2
            and all(isinstance(part, str) for part in item)
        ):
            failed.append((item[0], item[1]))
        else:
            raise ValueError("failed holds an entry that is not [service, reason]")
    found = {}
    for entry in entries:
        service = entry.get("service") if isinstance(entry, dict) else None
        if not isinstance(service, str) or not service:
            failed.append((str(service), "entry without a service"))
            continue
        service = rewrite_legacy_url(service).rstrip("/")
        info = units.info_from_json(entry.get("info"))
        if info is None:
            failed.append((service, "not an image description"))
            continue
        found[service] = info
    return FramesFile(found, failed, body["measured_at"], body["origin"])


def rebase_factors(old, new, resize):
    """``(fx, fy)``, the factors that bring coordinates stored in the *old* frame to the *new* one; None when the zone cannot be carried over.

    Images of the same size need only the ratio of the units. Another size
    counts only with *resize* and when the aspect is kept (the height scaled
    by the width ratio is within one pixel of the new height): each axis then
    follows its own size ratio.
    """
    if (old.width, old.height) == (new.width, new.height):
        factor = old.unit / new.unit
        return factor, factor
    if resize and abs(round(old.height * new.width / old.width) - new.height) <= 1:
        return (
            old.unit * new.width / (old.width * new.unit),
            old.unit * new.height / (old.height * new.unit),
        )
    return None


_DEPTH = {
    "Point": 0,
    "LineString": 1,
    "MultiPoint": 1,
    "Polygon": 2,
    "MultiLineString": 2,
    "MultiPolygon": 3,
}


def _scaled(value, depth, fx, fy):
    if depth == 0:
        if not isinstance(value, list) or len(value) < 2:
            raise ValueError(f"not a position: {value!r}")
        for coordinate in value[:2]:
            frames.leaflet_round(coordinate)
        return [
            frames.leaflet_round(value[0] * fx),
            frames.leaflet_round(value[1] * fy),
            *value[2:],
        ]
    if not isinstance(value, list):
        raise ValueError(f"not a coordinate list: {value!r}")
    return [_scaled(item, depth - 1, fx, fy) for item in value]


def scaled_geometry(geometry, fx, fy):
    """A copy of the GeoJSON *geometry* with every ``[x, y]`` position scaled by (*fx*, *fy*) and rounded as Leaflet does.

    Point, LineString, Polygon and their Multi forms; ValueError for another
    type, a malformed position or a value ``frames.leaflet_round`` refuses.
    """
    kind = geometry.get("type") if isinstance(geometry, dict) else None
    if kind not in _DEPTH:
        raise ValueError(f"unsupported geometry: {kind!r}")
    try:
        coordinates = _scaled(geometry.get("coordinates"), _DEPTH[kind], fx, fy)
    except TypeError as error:
        raise ValueError(f"not a coordinate: {error}") from error
    return {**geometry, "coordinates": coordinates}
