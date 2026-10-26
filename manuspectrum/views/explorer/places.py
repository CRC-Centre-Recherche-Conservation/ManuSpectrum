"""What the map reads of a stored place geometry and of a place's identifiers. Pure: no database.

Geometries are the GeoJSON feature collections Arches keeps in the tiles, in WGS84
longitude/latitude; ``geojson_geometries`` holds their EPSG:3857 copies, which the
map does not read (the data-version ledger does not watch that table). A feature
whose properties carry ``msDerivedFrom`` is a copy of a linked Place's geometry.
"""

import math
import re
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088
DERIVED_MARK = "msDerivedFrom"
_GEONAMES = re.compile(r"geonames\.org/(\d+)", re.I)
_WIKIDATA = re.compile(r"(?:wikidata\.org/(?:wiki|entity)/)?\b(Q\d+)\b")


@dataclass(frozen=True)
class PlaceGeometry:
    lng_lat: tuple
    kind: str
    extent_km: float | None


def haversine_km(a, b):
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _features(collection):
    if not isinstance(collection, dict):
        return []
    return [
        f
        for f in collection.get("features") or []
        if isinstance(f, dict) and isinstance(f.get("geometry"), dict)
    ]


def derived_only(collection):
    """Whether every feature of *collection* is a derived copy (``msDerivedFrom``); False for an empty one."""
    features = _features(collection)
    return bool(features) and all(
        DERIVED_MARK in (f.get("properties") or {}) for f in features
    )


def _position(value):
    if (
        isinstance(value, (list, tuple))
        and len(value) >= 2
        and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value[:2]
        )
        and -180 <= value[0] <= 180
        and -90 <= value[1] <= 90
    ):
        return (float(value[0]), float(value[1]))
    return None


def _ring(raw):
    ring = (
        [p for p in (_position(v) for v in raw or []) if p]
        if isinstance(raw, list)
        else []
    )
    return ring if len(ring) >= 4 else None


def _rings(geometry):
    kind, coordinates = geometry.get("type"), geometry.get("coordinates")
    if kind == "Polygon" and isinstance(coordinates, list) and coordinates:
        return [r for r in [_ring(coordinates[0])] if r]
    if kind == "MultiPolygon" and isinstance(coordinates, list):
        return [
            r
            for polygon in coordinates
            if isinstance(polygon, list) and polygon
            for r in [_ring(polygon[0])]
            if r
        ]
    return []


def _points(geometry):
    kind, coordinates = geometry.get("type"), geometry.get("coordinates")
    if kind == "Point":
        return [p for p in [_position(coordinates)] if p]
    if kind in ("MultiPoint", "LineString") and isinstance(coordinates, list):
        return [p for p in (_position(c) for c in coordinates) if p]
    return []


def _area_and_centroid(ring):
    area = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        cross = x1 * y2 - x2 * y1
        area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    area /= 2
    if area == 0:
        return 0.0, ring[0]
    return abs(area), (cx / (6 * area), cy / (6 * area))


def _inside(point, ring):
    x, y, inside = point[0], point[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _label_point(ring):
    _, centroid = _area_and_centroid(ring)
    if _inside(centroid, ring):
        return centroid
    y = centroid[1]
    crossings = sorted(
        x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        for (x1, y1), (x2, y2) in zip(ring, ring[1:])
        if (y1 > y) != (y2 > y)
    )
    pairs = list(zip(crossings[::2], crossings[1::2]))
    if not pairs:
        return centroid
    left, right = max(pairs, key=lambda pair: pair[1] - pair[0])
    return ((left + right) / 2, y)


def geometry_summary(collection):
    """``PlaceGeometry`` of a feature collection, None without a usable feature.

    Polygons make an area: its label point lies in its largest ring (the centroid,
    else the middle of the widest span of the horizontal line through it), its
    extent is half the diagonal of the bounding box. Points, multipoints and lines
    make a point at their first position.
    """
    features = _features(collection)
    rings = [r for f in features for r in _rings(f["geometry"])]
    if rings:
        largest = max(rings, key=lambda r: _area_and_centroid(r)[0])
        x, y = _label_point(largest)
        xs = [p[0] for r in rings for p in r]
        ys = [p[1] for r in rings for p in r]
        extent = haversine_km((min(xs), min(ys)), (max(xs), max(ys))) / 2
        return PlaceGeometry((round(x, 6), round(y, 6)), "area", round(extent, 1))
    points = [p for f in features for p in _points(f["geometry"])]
    if not points:
        return None
    return PlaceGeometry(
        (round(points[0][0], 6), round(points[0][1], 6)), "point", None
    )


def authorities_of(texts):
    """``{"geonames": id, "wikidata": Q-id}`` read off identifier texts; a key is present only when found."""
    found = {}
    for text in texts:
        if not isinstance(text, str):
            continue
        geonames, wikidata = _GEONAMES.search(text), _WIKIDATA.search(text)
        if geonames:
            found.setdefault("geonames", geonames.group(1))
        if wikidata:
            found.setdefault("wikidata", wikidata.group(1))
    return found
