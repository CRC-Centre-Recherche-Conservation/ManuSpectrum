import {
    fromMercator,
    haversineKm,
    toMercator,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";

import type {
    Feature,
    FeatureCollection,
    MultiLineString,
    Polygon,
} from "geojson";
import type {
    Bounds,
    LngLat,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type { TerritoryColour } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-state.ts";

/**
 * The default influence threshold, in attestations: one full attestation
 * (weight 1) reaches it out to `r·√(ln 2)` ≈ 0.83 kernel radius.
 */
export const FLOOR = 0.5;
export const THRESHOLD_MIN = 0.25;
export const THRESHOLD_MAX = 3;
export const THRESHOLD_STEP = 0.25;
export const TIE_SHARE = 0.55;
export const CELL_RATIO = 0.18;
export const CELL_MIN_KM = 10;
export const MAX_CELLS = 6000;
/** Share of the viewport's span added on each side of the grid. */
export const VIEW_PAD = 0.1;
/** Kernel radii past the grid within which an attestation still counts. */
export const REACH_RADII = 3;
const LAT_STEP = 5;
const MAX_LATITUDE = 85.0511;
const KM_PER_DEGREE = 111.32;
const EACH_ALPHA = { base: 0.06, step: 0.025, max: 0.32 };
const DOMINANT_ALPHA = { base: 0.15, span: 0.6 };
const GROWTH = 1.25;
const SQRT3 = Math.sqrt(3);
const DEG = Math.PI / 180;
const SIDES = 6;

/** Pointy-top cells, odd rows shifted east by half a cell; direction k faces 60k° (0 = east, counter-clockwise). */
function offsets(odd: number): [number, number][] {
    return [
        [1, 0],
        [odd, 1],
        [odd - 1, 1],
        [-1, 0],
        [odd - 1, -1],
        [odd, -1],
    ];
}

export interface Attestation {
    lngLat: LngLat;
    weight: number;
    extentKm: number;
}
export interface TrackedField {
    slot: number;
    attestations: readonly Attestation[];
}
export interface HexCell {
    col: number;
    row: number;
    centre: LngLat;
    ring: LngLat[];
}
export interface TerritoryProps {
    layer: "cell" | "edge";
    slot: number;
    alpha: number;
    hatched: boolean;
}
interface Lattice {
    x0: number;
    y0: number;
    radius: number;
    width: number;
    columns: number;
    rows: number;
}

export function influenceAt(
    point: LngLat,
    attestations: readonly Attestation[],
    radiusKm: number,
): number {
    let total = 0;
    for (const attestation of attestations) {
        const ratio =
            haversineKm(point, attestation.lngLat) /
            Math.max(radiusKm, attestation.extentKm);
        total += attestation.weight * Math.exp(-(ratio * ratio));
    }
    return total;
}

/** Attestations sorted by latitude, with the farthest distance at which one still counts. */
interface Reach {
    sorted: Attestation[];
    km: number;
}

function reachOf(
    attestations: readonly Attestation[],
    radiusKm: number,
): Reach {
    const sorted = [...attestations].sort((a, b) => a.lngLat[1] - b.lngLat[1]);
    const extent = sorted.reduce((max, a) => Math.max(max, a.extentKm), 0);
    return { sorted, km: REACH_RADII * Math.max(radiusKm, extent) };
}

/** `influenceAt` over the attestations of `reach` within its distance of `point` in latitude and longitude. */
function influenceNear(point: LngLat, reach: Reach, radiusKm: number): number {
    const { sorted } = reach;
    const dLat = reach.km / KM_PER_DEGREE;
    const poleward = Math.min(MAX_LATITUDE, Math.abs(point[1]) + dLat);
    const dLng =
        reach.km / (KM_PER_DEGREE * Math.max(0.05, Math.cos(poleward * DEG)));
    let low = 0;
    let high = sorted.length;
    while (low < high) {
        const mid = (low + high) >> 1;
        if (sorted[mid].lngLat[1] < point[1] - dLat) low = mid + 1;
        else high = mid;
    }
    let total = 0;
    for (let i = low; i < sorted.length; i += 1) {
        const attestation = sorted[i];
        if (attestation.lngLat[1] > point[1] + dLat) break;
        const apart = Math.abs(attestation.lngLat[0] - point[0]) % 360;
        if (Math.min(apart, 360 - apart) > dLng) continue;
        const ratio =
            haversineKm(point, attestation.lngLat) /
            Math.max(radiusKm, attestation.extentKm);
        total += attestation.weight * Math.exp(-(ratio * ratio));
    }
    return total;
}

/**
 * The lattice covering `bounds`, anchored on a world-wide lattice (origin
 * snapped to whole columns and to pairs of rows, scale latitude rounded to
 * `LAT_STEP`) so a pan keeps the cells it still shows in place.
 */
function lattice(bounds: Bounds, cellKm: number): Lattice {
    const scaleLat =
        Math.round((bounds.south + bounds.north) / 2 / LAT_STEP) * LAT_STEP;
    const radius = (cellKm * 1000) / Math.cos(scaleLat * DEG);
    const width = SQRT3 * radius;
    const [west, south] = toMercator([bounds.west, bounds.south]);
    const [x1, y1] = toMercator([bounds.east, bounds.north]);
    const x0 = Math.floor(west / width) * width;
    const y0 = Math.floor(south / (3 * radius)) * 3 * radius;
    return {
        x0,
        y0,
        radius,
        width,
        columns: Math.ceil((x1 - x0) / width) + 1,
        rows: Math.ceil((y1 - y0) / (1.5 * radius)) + 1,
    };
}

/**
 * The grid's bounds for the map's `view`: widened by `VIEW_PAD` of its span
 * on each side so the zones do not stop at the frame, latitudes kept inside
 * Web Mercator, at most one world wide around the view's centre. Longitudes
 * may pass ±180 (a view across the antimeridian).
 */
export function gridBounds(view: Bounds): Bounds {
    const padLng = (view.east - view.west) * VIEW_PAD;
    const padLat = (view.north - view.south) * VIEW_PAD;
    let west = view.west - padLng;
    let east = view.east + padLng;
    if (east - west > 360) {
        const centre = (view.west + view.east) / 2;
        west = centre - 180;
        east = centre + 180;
    }
    return {
        west,
        south: Math.max(-MAX_LATITUDE, view.south - padLat),
        east,
        north: Math.min(MAX_LATITUDE, view.north + padLat),
    };
}

export function cellSizeKm(radiusKm: number, bounds: Bounds): number {
    let size = Math.max(CELL_MIN_KM, radiusKm * CELL_RATIO);
    for (
        let grid = lattice(bounds, size);
        grid.columns * grid.rows > MAX_CELLS;
        grid = lattice(bounds, size)
    ) {
        size *= GROWTH;
    }
    return size;
}

/** Whether even `MAX_CELLS` cells over `bounds` are larger than the kernel radius: too coarse to draw. */
export function tooCoarse(radiusKm: number, bounds: Bounds): boolean {
    return cellSizeKm(radiusKm, bounds) > radiusKm;
}

/**
 * Whether `attestation` lies within `REACH_RADII` kernel radii (or its own
 * extent if larger) of `bounds`, on any world copy.
 */
export function reaches(
    attestation: Attestation,
    bounds: Bounds,
    radiusKm: number,
): boolean {
    const km = REACH_RADII * Math.max(radiusKm, attestation.extentKm);
    const dLat = km / KM_PER_DEGREE;
    const poleward = Math.min(
        MAX_LATITUDE,
        Math.max(Math.abs(bounds.south), Math.abs(bounds.north)) + dLat,
    );
    const dLng =
        km / (KM_PER_DEGREE * Math.max(0.05, Math.cos(poleward * DEG)));
    const [lng, lat] = attestation.lngLat;
    if (lat < bounds.south - dLat || lat > bounds.north + dLat) return false;
    return [-360, 0, 360].some(
        (shift) =>
            lng + shift >= bounds.west - dLng &&
            lng + shift <= bounds.east + dLng,
    );
}

export function hexGrid(bounds: Bounds, cellKm: number): HexCell[] {
    return cellsOf(lattice(bounds, cellKm));
}

function cellsOf(grid: Lattice): HexCell[] {
    const cells: HexCell[] = [];
    for (let row = 0; row < grid.rows; row += 1) {
        for (let col = 0; col < grid.columns; col += 1) {
            const cx = grid.x0 + (col + (row & 1) / 2) * grid.width;
            const cy = grid.y0 + row * 1.5 * grid.radius;
            const ring: LngLat[] = [];
            for (let k = 0; k <= SIDES; k += 1) {
                const angle = (60 * (k % SIDES) - 30) * DEG;
                ring.push(
                    fromMercator([
                        cx + grid.radius * Math.cos(angle),
                        cy + grid.radius * Math.sin(angle),
                    ]),
                );
            }
            cells.push({ col, row, centre: fromMercator([cx, cy]), ring });
        }
    }
    return cells;
}

/**
 * The `col:row` key of the cell of `grid` holding `point` (the nearest
 * centre, on the world copy that falls inside `bounds`), or null outside.
 */
function homeKey(point: LngLat, grid: Lattice, bounds: Bounds): string | null {
    const shift = [0, -360, 360].find(
        (s) => point[0] + s >= bounds.west && point[0] + s <= bounds.east,
    );
    if (shift === undefined) return null;
    const [x, y] = toMercator([point[0] + shift, point[1]]);
    const below = Math.floor((y - grid.y0) / (1.5 * grid.radius));
    let best: string | null = null;
    let nearest = Infinity;
    for (const row of [below, below + 1]) {
        const col = Math.round((x - grid.x0) / grid.width - (row & 1) / 2);
        const dx = grid.x0 + (col + (row & 1) / 2) * grid.width - x;
        const dy = grid.y0 + row * 1.5 * grid.radius - y;
        if (dx * dx + dy * dy < nearest) {
            nearest = dx * dx + dy * dy;
            best = `${col}:${row}`;
        }
    }
    return best;
}

export function neighbour(
    col: number,
    row: number,
    direction: number,
): [number, number] {
    const [dc, dr] = offsets(row & 1)[direction];
    return [col + dc, row + dr];
}

/**
 * Index of the most attested field when it reaches `threshold`; under it,
 * the most attested of the fields whose own place lies in the cell
 * (`home`), or -1 when there is none.
 */
export function dominantOf(
    values: readonly number[],
    threshold: number = FLOOR,
    home: readonly boolean[] = [],
): number {
    let best = -1;
    let homeBest = -1;
    values.forEach((value, index) => {
        if (best < 0 || value > values[best]) best = index;
        if (home[index] && (homeBest < 0 || value > values[homeBest]))
            homeBest = index;
    });
    return best >= 0 && values[best] >= threshold ? best : homeBest;
}

/** Whether the runner-up comes close to `values[best]`: the best's share of the top two is under `TIE_SHARE`. */
export function nearlyTied(values: readonly number[], best: number): boolean {
    let second = 0;
    values.forEach((value, index) => {
        if (index !== best && value > second) second = value;
    });
    return values[best] / (values[best] + second) < TIE_SHARE;
}

function polygon(
    ring: LngLat[],
    properties: TerritoryProps,
): Feature<Polygon, TerritoryProps> {
    return {
        type: "Feature",
        geometry: {
            type: "Polygon",
            coordinates: [ring.map((p) => [p[0], p[1]])],
        },
        properties,
    };
}

/** One MultiLineString feature per slot holding every edge segment collected for it. */
function edgeFeatures(
    segments: ReadonlyMap<number, [LngLat, LngLat][]>,
): Feature<MultiLineString, TerritoryProps>[] {
    return [...segments].map(([slot, list]) => ({
        type: "Feature",
        geometry: {
            type: "MultiLineString",
            coordinates: list.map(([a, b]) => [
                [a[0], a[1]],
                [b[0], b[1]],
            ]),
        },
        properties: { layer: "edge", slot, alpha: 1, hatched: false },
    }));
}

/**
 * The influence model of the followed materials over a hex grid of `bounds`
 * (the map's padded view, `gridBounds`), cells sized from the radius
 * (`cellSizeKm`); nothing when that grid is `tooCoarse`. Only the
 * attestations that `reaches` the bounds are summed, each on the cells
 * within `REACH_RADII` radii of it (`influenceNear`). A field lights a
 * cell where its influence reaches `threshold`, and always the cells
 * holding one of its places. `each`: one translucent area per field over
 * the cells it lights, outlined where the neighbour is not lit. The edges
 * of one slot are a single MultiLineString feature. `dominant`: each cell in the colour of
 * its most attested field, opacity from its share of every field, hatched
 * when the runner-up nearly ties (`nearlyTied`), borders (slot 0) only
 * between two different dominants.
 */
export function territories(
    fields: readonly TrackedField[],
    radiusKm: number,
    bounds: Bounds,
    colour: TerritoryColour,
    threshold: number = FLOOR,
): FeatureCollection<Polygon | MultiLineString, TerritoryProps> {
    const features: Feature<Polygon | MultiLineString, TerritoryProps>[] = [];
    const segments = new Map<number, [LngLat, LngLat][]>();
    const edge = (slot: number, a: LngLat, b: LngLat): void => {
        const list = segments.get(slot) ?? [];
        list.push([a, b]);
        segments.set(slot, list);
    };
    if (fields.every((field) => field.attestations.length === 0)) {
        return { type: "FeatureCollection", features };
    }
    if (tooCoarse(radiusKm, bounds)) {
        return { type: "FeatureCollection", features };
    }
    const reached = fields.map((field) =>
        reachOf(
            field.attestations.filter((a) => reaches(a, bounds, radiusKm)),
            radiusKm,
        ),
    );
    const grid = lattice(bounds, cellSizeKm(radiusKm, bounds));
    const cells = cellsOf(grid);
    const index = new Map(
        cells.map((cell, i) => [`${cell.col}:${cell.row}`, i]),
    );
    const influence = cells.map((cell) =>
        reached.map((reach) => influenceNear(cell.centre, reach, radiusKm)),
    );
    const homes = reached.map(
        (reach) =>
            new Set(
                reach.sorted.flatMap((a) => {
                    const key = homeKey(a.lngLat, grid, bounds);
                    const i = key === null ? undefined : index.get(key);
                    return i === undefined ? [] : [i];
                }),
            ),
    );
    const lit = (i: number, f: number): boolean =>
        influence[i][f] >= threshold || homes[f].has(i);
    const near = (cell: HexCell, k: number): number | null => {
        const [col, row] = neighbour(cell.col, cell.row, k);
        return index.get(`${col}:${row}`) ?? null;
    };
    if (colour === "each") {
        fields.forEach((field, f) => {
            cells.forEach((cell, i) => {
                if (!lit(i, f)) return;
                const value = influence[i][f];
                features.push(
                    polygon(cell.ring, {
                        layer: "cell",
                        slot: field.slot,
                        alpha: Math.min(
                            EACH_ALPHA.max,
                            EACH_ALPHA.base + value * EACH_ALPHA.step,
                        ),
                        hatched: false,
                    }),
                );
                for (let k = 0; k < SIDES; k += 1) {
                    const j = near(cell, k);
                    if (j !== null && lit(j, f)) continue;
                    edge(field.slot, cell.ring[k], cell.ring[k + 1]);
                }
            });
        });
        features.push(...edgeFeatures(segments));
        return { type: "FeatureCollection", features };
    }
    const dominant = influence.map((values, i) =>
        dominantOf(
            values,
            threshold,
            homes.map((home) => home.has(i)),
        ),
    );
    cells.forEach((cell, i) => {
        const best = dominant[i];
        if (best < 0) return;
        const share =
            influence[i][best] / influence[i].reduce((sum, v) => sum + v, 0);
        features.push(
            polygon(cell.ring, {
                layer: "cell",
                slot: fields[best].slot,
                alpha: DOMINANT_ALPHA.base + DOMINANT_ALPHA.span * share,
                hatched: nearlyTied(influence[i], best),
            }),
        );
        for (let k = 0; k < SIDES; k += 1) {
            const j = near(cell, k);
            if (j === null || j < i || dominant[j] < 0 || dominant[j] === best)
                continue;
            edge(0, cell.ring[k], cell.ring[k + 1]);
        }
    });
    features.push(...edgeFeatures(segments));
    return { type: "FeatureCollection", features };
}
