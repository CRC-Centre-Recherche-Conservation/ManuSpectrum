export type LngLat = readonly [number, number];
export interface Bounds {
    west: number;
    south: number;
    east: number;
    north: number;
}
export const EARTH_RADIUS_KM = 6371.0088;
const MERCATOR_RADIUS_M = 6378137;
const DEG = Math.PI / 180;
const MAX_LATITUDE = 85.0511;
const KM_PER_DEGREE = 111.32;

export function haversineKm(a: LngLat, b: LngLat): number {
    const dLat = (b[1] - a[1]) * DEG;
    const dLng = (b[0] - a[0]) * DEG;
    const h =
        Math.sin(dLat / 2) ** 2 +
        Math.cos(a[1] * DEG) * Math.cos(b[1] * DEG) * Math.sin(dLng / 2) ** 2;
    return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function toMercator([lng, lat]: LngLat): [number, number] {
    const clamped = Math.max(-MAX_LATITUDE, Math.min(MAX_LATITUDE, lat));
    return [
        MERCATOR_RADIUS_M * lng * DEG,
        MERCATOR_RADIUS_M *
            Math.log(Math.tan(Math.PI / 4 + (clamped * DEG) / 2)),
    ];
}

export function fromMercator([x, y]: readonly [number, number]): [
    number,
    number,
] {
    return [
        x / MERCATOR_RADIUS_M / DEG,
        (2 * Math.atan(Math.exp(y / MERCATOR_RADIUS_M)) - Math.PI / 2) / DEG,
    ];
}

export function boundsOf(points: readonly LngLat[]): Bounds | null {
    if (points.length === 0) return null;
    return points.reduce<Bounds>(
        (b, [lng, lat]) => ({
            west: Math.min(b.west, lng),
            south: Math.min(b.south, lat),
            east: Math.max(b.east, lng),
            north: Math.max(b.north, lat),
        }),
        { west: Infinity, south: Infinity, east: -Infinity, north: -Infinity },
    );
}

/**
 * The bounds of `points` for fitting the map: across the antimeridian (east
 * past 180) when the points fit in half a world that way and in less than
 * the plain bounds span, else `boundsOf`.
 */
export function fitBoundsOf(points: readonly LngLat[]): Bounds | null {
    const plain = boundsOf(points);
    if (!plain || points.length < 2) return plain;
    const lngs = [...new Set(points.map(([lng]) => lng))].sort((a, b) => a - b);
    let gap = 0;
    let after = 0;
    for (let i = 1; i < lngs.length; i += 1) {
        if (lngs[i] - lngs[i - 1] > gap) {
            gap = lngs[i] - lngs[i - 1];
            after = i;
        }
    }
    const wrappedSpan = 360 - gap;
    const plainSpan = plain.east - plain.west;
    if (after === 0 || wrappedSpan > 180 || wrappedSpan >= plainSpan) {
        return plain;
    }
    return { ...plain, west: lngs[after], east: lngs[after - 1] + 360 };
}

/**
 * `point` on the world copy nearest the centre of `bounds` when they cross
 * the antimeridian (`east` past 180, as `fitBoundsOf` gives them); otherwise
 * `point` itself.
 */
export function wrapInto(point: LngLat, bounds: Bounds): LngLat {
    if (bounds.east <= 180) return point;
    const centre = (bounds.west + bounds.east) / 2;
    const turns = Math.round((centre - point[0]) / 360);
    return turns === 0 ? point : [point[0] + 360 * turns, point[1]];
}

export interface FitPadding {
    top: number;
    right: number;
    bottom: number;
    left: number;
}

/** Room left around fitted places for their names (CSS pixels per side). */
export const FIT_LABEL_ROOM_PX = { x: 120, y: 48 } as const;
const FIT_ROOM_SHARE = 0.2;

/**
 * The `fitBounds` padding of a `width`×`height` frame: `FIT_LABEL_ROOM_PX`,
 * at most `FIT_ROOM_SHARE` of the frame per side on a small screen.
 */
export function fitPadding(width: number, height: number): FitPadding {
    const x = Math.round(
        Math.min(FIT_LABEL_ROOM_PX.x, Math.max(0, width) * FIT_ROOM_SHARE),
    );
    const y = Math.round(
        Math.min(FIT_LABEL_ROOM_PX.y, Math.max(0, height) * FIT_ROOM_SHARE),
    );
    return { top: y, right: x, bottom: y, left: x };
}

export function padBounds(bounds: Bounds, km: number): Bounds {
    const dLat = km / KM_PER_DEGREE;
    const midLat = (bounds.south + bounds.north) / 2;
    const dLng = km / (KM_PER_DEGREE * Math.max(0.1, Math.cos(midLat * DEG)));
    return {
        west: bounds.west - dLng,
        south: Math.max(-MAX_LATITUDE, bounds.south - dLat),
        east: bounds.east + dLng,
        north: Math.min(MAX_LATITUDE, bounds.north + dLat),
    };
}

/** `point` in a `width`×`height` box showing `bounds` in Web Mercator, centred, y downwards. */
export function project(
    point: LngLat,
    bounds: Bounds,
    width: number,
    height: number,
): [number, number] {
    const [x0, y0] = toMercator([bounds.west, bounds.south]);
    const [x1, y1] = toMercator([bounds.east, bounds.north]);
    const scale = Math.min(
        width / Math.max(1, x1 - x0),
        height / Math.max(1, y1 - y0),
    );
    const [x, y] = toMercator(point);
    const left = (width - (x1 - x0) * scale) / 2;
    const top = (height - (y1 - y0) * scale) / 2;
    return [left + (x - x0) * scale, top + (y1 - y) * scale];
}

/**
 * `bounds` widened in Web Mercator, around its centre, to the aspect of a
 * `width`×`height` box: what `project` shows of the map in that box.
 */
export function fitAspect(
    bounds: Bounds,
    width: number,
    height: number,
): Bounds {
    const [x0, y0] = toMercator([bounds.west, bounds.south]);
    const [x1, y1] = toMercator([bounds.east, bounds.north]);
    const spanX = Math.max(1, x1 - x0);
    const spanY = Math.max(1, y1 - y0);
    const scale = Math.min(width / spanX, height / spanY);
    const halfX = width / scale / 2;
    const halfY = height / scale / 2;
    const midX = (x0 + x1) / 2;
    const midY = (y0 + y1) / 2;
    const [west, south] = fromMercator([midX - halfX, midY - halfY]);
    const [east, north] = fromMercator([midX + halfX, midY + halfY]);
    return { west, south, east, north };
}
