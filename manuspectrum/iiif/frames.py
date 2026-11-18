"""The stamp of the image frame on annotation zones, and the rule that writes it.

A feature of an annotation collection carries its frame in four properties
(``msUnit``, ``msImageWidth``, ``msImageHeight``, ``msFrame``): ``frame_of``
reads it back, valid or not at all. ``stamp_collection`` applies one rule per
feature of a collection being saved:

1. the feature matches one already stored (same id, same canvas, same
   geometry) and that one carries a stamp: the stored stamp wins over any
   value the client sent;
2. it matches one that carries none: it stays unstamped (a command stamps
   existing zones) and client stamp keys are dropped;
3. otherwise (new, moved geometry, moved canvas): a trusted writer's valid
   stamp is kept; any other feature gets ``frame_for(service)``, and when that
   is unknown the stamp keys are dropped and the feature is listed for a later
   resolution (trusted writers list nothing).

Inputs are never mutated. Geometry equality is coordinates rounded as Leaflet's
``toGeoJSON`` writes them (``leaflet_round``).
"""

import copy
import hashlib
import json
import math
from contextlib import contextmanager
from contextvars import ContextVar

from manuspectrum.accounts.lockout import current_request
from manuspectrum.iiif.units import FRAME_SOURCES, Frame
from manuspectrum.views.explorer.values import rewrite_legacy_url

STAMP_KEYS = ("msUnit", "msImageWidth", "msImageHeight", "msFrame")

_trusted = ContextVar("manuspectrum_trusted_zone_writes", default=False)


@contextmanager
def trusted_writes():
    """Mark the tile saves of this block as a trusted writer's: valid incoming stamps are kept.

    For an importer that saves tiles through ``Tile.save`` (or
    ``TileModel.save``) inside a request with stamps it took from a trusted
    source; outside any request every save is trusted already
    (``is_trusted``). A guarded ``.update()``, as the ``annotation_frames``
    command writes, fires no signal and needs no mark.
    """
    token = _trusted.set(True)
    try:
        yield
    finally:
        _trusted.reset(token)


def is_trusted():
    """True inside ``trusted_writes``, outside any request, or in Arches' ``resource_copy`` route.

    ``resource_copy`` copies stored tiles server-side and takes no tile data
    from the client, so the stamps it carries are the stored ones.
    """
    if _trusted.get():
        return True
    request = current_request()
    if request is None:
        return True
    match = getattr(request, "resolver_match", None)
    return getattr(match, "view_name", None) == "resource_copy"


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def frame_of(feature):
    """The ``Frame`` stamped on *feature*, or None when the stamp is absent or invalid (types, power of two, bounds of ``Frame``)."""
    props = feature.get("properties") if isinstance(feature, dict) else None
    if not isinstance(props, dict) or any(k not in props for k in STAMP_KEYS):
        return None
    unit, width, height, source = (props[k] for k in STAMP_KEYS)
    if not (_whole(unit) and _whole(width) and _whole(height)):
        return None
    try:
        return Frame(unit, width, height, source)
    except ValueError:
        return None


def leaflet_round(value):
    """*value* rounded as Leaflet 1.6 ``formatNum`` does: ``Math.round(value * 1e6) / 1e6``, halves up, -0.0 as 0.0.

    Raises ValueError for a bool, a NaN, an infinity or a value too large to scale.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"not a coordinate: {value!r}")
    try:
        scaled = float(value) * 1e6
    except OverflowError:
        raise ValueError(f"not a finite coordinate: {value!r}") from None
    if not math.isfinite(scaled):
        raise ValueError(f"not a finite coordinate: {value!r}")
    floor = math.floor(scaled)
    if scaled - floor >= 0.5:
        floor += 1
    return floor / 1e6 + 0.0


def _rounded(value):
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return leaflet_round(value)
    if isinstance(value, list):
        return [_rounded(v) for v in value]
    if isinstance(value, dict):
        return {k: _rounded(v) for k, v in value.items()}
    return value


def same_geometry(a, b):
    """True when two geometries have the same type and the same coordinates after ``leaflet_round``.

    A geometry holding a bool, NaN, an infinity or a value ``leaflet_round``
    refuses equals nothing.
    """
    try:
        return _rounded(a) == _rounded(b)
    except ValueError:
        return False


_INVALID_DIGEST = hashlib.sha1(b"invalid geometry").hexdigest()


def geometry_digest(geometry):
    """sha1 hex of *geometry* normalised by ``leaflet_round``: equal for geometries ``same_geometry`` equates.

    A geometry holding a bool, NaN, an infinity or a value ``leaflet_round``
    refuses gets one fixed sentinel digest.
    """
    try:
        text = json.dumps(_rounded(geometry), sort_keys=True, separators=(",", ":"))
    except ValueError:
        return _INVALID_DIGEST
    return hashlib.sha1(text.encode()).hexdigest()


def valid_id(value):
    """True for a feature id the rule can key on: a str or an int (not a bool)."""
    return isinstance(value, str) or _whole(value)


def canvas_of(feature):
    """The normalised canvas name of *feature*: legacy host rewritten, no trailing slash."""
    props = feature.get("properties") if isinstance(feature, dict) else None
    canvas = props.get("canvas") if isinstance(props, dict) else None
    return rewrite_legacy_url(canvas).rstrip("/") if isinstance(canvas, str) else ""


class PreviousFeatures:
    """The features stored before a save, from the tile's data and every provisional edit's value."""

    def __init__(self, data, provisionaledits):
        self._by_id = {}
        values = [data]
        if isinstance(provisionaledits, dict):
            values += [
                edit.get("value")
                for edit in provisionaledits.values()
                if isinstance(edit, dict)
            ]
        for value in values:
            if not isinstance(value, dict):
                continue
            for node_id, collection in value.items():
                for feature in _features(collection):
                    fid = feature.get("id")
                    if valid_id(fid):
                        self._by_id.setdefault((node_id, fid), []).append(feature)

    def match(self, feature, node_id):
        """A stored feature of the same id, canvas and geometry (one carrying a stamp first), or None."""
        if not valid_id(feature.get("id")):
            return None
        found = [
            old
            for old in self._by_id.get((node_id, feature.get("id")), ())
            if canvas_of(old) == canvas_of(feature)
            and same_geometry(old.get("geometry"), feature.get("geometry"))
        ]
        return next((o for o in found if frame_of(o)), found[0] if found else None)


def _features(collection):
    features = collection.get("features") if isinstance(collection, dict) else None
    return (
        [f for f in features if isinstance(f, dict)]
        if isinstance(features, list)
        else []
    )


def _without_stamp(properties):
    return {k: v for k, v in properties.items() if k not in STAMP_KEYS}


def stamp_collection(new, previous, node_id, frame_for, trusted):
    """Apply the stamping rule to the collection *new* of annotation node *node_id*.

    *frame_for(service)* gives the ``Frame`` of an image service or None.
    Returns the collection and ``{feature id: service}`` of the features left
    to resolve. A feature without a usable id (``valid_id``) or without a canvas
    is never matched, stamped or listed: its stamp keys are dropped, except a
    trusted writer's valid stamp on a feature without a usable id. Features of
    one new collection sharing an id overwrite each other in the resolution
    list: the last one listed names the service.
    """
    if not isinstance(new, dict) or not isinstance(new.get("features"), list):
        return new, {}
    out = copy.deepcopy(new)
    unresolved = {}
    for feature in out["features"]:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            props = feature["properties"] = {}
        if not valid_id(feature.get("id")):
            if not (trusted and frame_of(feature)):
                feature["properties"] = _without_stamp(props)
            continue
        old = previous.match(feature, node_id)
        if old is not None:
            stored = frame_of(old)
            feature["properties"] = _without_stamp(props)
            if stored:
                feature["properties"].update(stored.stamp())
            continue
        if trusted and frame_of(feature):
            continue
        service = canvas_of(feature)
        frame = frame_for(service) if service else None
        feature["properties"] = _without_stamp(props)
        if frame:
            feature["properties"].update(frame.stamp())
        elif service and not trusted:
            unresolved[feature.get("id")] = service
    return out, unresolved
