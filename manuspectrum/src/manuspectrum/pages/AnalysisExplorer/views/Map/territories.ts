import {
    fromMercator,
    haversineKm,
    toMercator,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";

import type { Feature, FeatureCollection, LineString, Polygon } from "geojson";
import type {
    Bounds,
    LngLat,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type { TerritoryColour } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-state.ts";

export const FLOOR = 1.2;
export const TIE_SHARE = 0.55;
export const CELL_RATIO = 0.18;
export const CELL_MIN_KM = 10;
export const MAX_CELLS = 6000;
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

function lattice(bounds: Bounds, cellKm: number): Lattice {
    const radius =
        (cellKm * 1000) / Math.cos(((bounds.south + bounds.north) / 2) * DEG);
    const [x0, y0] = toMercator([bounds.west, bounds.south]);
    const [x1, y1] = toMercator([bounds.east, bounds.north]);
    const width = SQRT3 * radius;
    return {
        x0,
        y0,
        radius,
        width,
        columns: Math.ceil((x1 - x0) / width) + 1,
        rows: Math.ceil((y1 - y0) / (1.5 * radius)) + 1,
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

export function hexGrid(bounds: Bounds, cellKm: number): HexCell[] {
    const grid = lattice(bounds, cellKm);
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

export function neighbour(
    col: number,
    row: number,
    direction: number,
): [number, number] {
    const [dc, dr] = offsets(row & 1)[direction];
    return [col + dc, row + dr];
}

/** Index of the most attested field, or -1 when even it is under `FLOOR`. */
export function dominantOf(values: readonly number[]): number {
    let best = 0;
    values.forEach((value, index) => {
        if (value > values[best]) best = index;
    });
    return values.length > 0 && values[best] >= FLOOR ? best : -1;
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

function line(
    a: LngLat,
    b: LngLat,
    properties: TerritoryProps,
): Feature<LineString, TerritoryProps> {
    return {
        type: "Feature",
        geometry: {
            type: "LineString",
            coordinates: [
                [a[0], a[1]],
                [b[0], b[1]],
            ],
        },
        properties,
    };
}

/**
 * The influence model of the followed materials over a hex grid of `bounds`.
 * `each`: one translucent area per field where its influence reaches `FLOOR`,
 * outlined where the neighbour does not. `dominant`: each cell in the colour of
 * its most attested field, opacity from its share, hatched under `TIE_SHARE`,
 * borders (slot 0) only between two different dominants.
 */
export function territories(
    fields: readonly TrackedField[],
    radiusKm: number,
    bounds: Bounds,
    colour: TerritoryColour,
): FeatureCollection<Polygon | LineString, TerritoryProps> {
    const features: Feature<Polygon | LineString, TerritoryProps>[] = [];
    if (fields.every((field) => field.attestations.length === 0)) {
        return { type: "FeatureCollection", features };
    }
    const cells = hexGrid(bounds, cellSizeKm(radiusKm, bounds));
    const index = new Map(
        cells.map((cell, i) => [`${cell.col}:${cell.row}`, i]),
    );
    const influence = cells.map((cell) =>
        fields.map((field) =>
            influenceAt(cell.centre, field.attestations, radiusKm),
        ),
    );
    const near = (cell: HexCell, k: number): number | null => {
        const [col, row] = neighbour(cell.col, cell.row, k);
        return index.get(`${col}:${row}`) ?? null;
    };
    if (colour === "each") {
        fields.forEach((field, f) => {
            cells.forEach((cell, i) => {
                const value = influence[i][f];
                if (value < FLOOR) return;
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
                    if (j !== null && influence[j][f] >= FLOOR) continue;
                    features.push(
                        line(cell.ring[k], cell.ring[k + 1], {
                            layer: "edge",
                            slot: field.slot,
                            alpha: 1,
                            hatched: false,
                        }),
                    );
                }
            });
        });
        return { type: "FeatureCollection", features };
    }
    const dominant = influence.map((values) => dominantOf(values));
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
                hatched: share < TIE_SHARE,
            }),
        );
        for (let k = 0; k < SIDES; k += 1) {
            const j = near(cell, k);
            if (j === null || j < i || dominant[j] < 0 || dominant[j] === best)
                continue;
            features.push(
                line(cell.ring[k], cell.ring[k + 1], {
                    layer: "edge",
                    slot: 0,
                    alpha: 1,
                    hatched: false,
                }),
            );
        }
    });
    return { type: "FeatureCollection", features };
}
