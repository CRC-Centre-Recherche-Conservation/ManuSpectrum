import type { MultiLineString } from "geojson";
import { describe, expect, it } from "vitest";

import {
    CELL_MIN_KM,
    CELL_RATIO,
    FLOOR,
    THRESHOLD_MAX,
    cellSizeKm,
    dominantOf,
    gridBounds,
    hexGrid,
    influenceAt,
    nearlyTied,
    neighbour,
    reaches,
    territories,
    tooCoarse,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/territories.ts";
import { haversineKm } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import { LOW_WEIGHT } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";

import type { Feature } from "geojson";

const BOUNDS = { west: 0, south: 45, east: 4, north: 48 };
const PARIS = [2.35, 48.85] as const;
const AROUND_PARIS = { west: -4, south: 45, east: 9, north: 52 };
/** The centre of each drawn cell, the mean of its ring's six corners. */
const centres = (features: Feature[]): [number, number][] =>
    features
        .filter((f) => f.properties?.layer === "cell")
        .map((f) => {
            const ring = (
                f.geometry as { coordinates: number[][][] }
            ).coordinates[0].slice(0, 6);
            return [
                ring.reduce((sum, p) => sum + p[0], 0) / 6,
                ring.reduce((sum, p) => sum + p[1], 0) / 6,
            ];
        });
const near = (lng: number, lat: number, weight = 4, extentKm = 0) => ({
    lngLat: [lng, lat] as const,
    weight,
    extentKm,
});

describe("territories", () => {
    it("sums w·exp(-(d/r)²), an area reaching at least its extent", () => {
        expect(influenceAt([2, 46], [near(2, 46, 3)], 150)).toBeCloseTo(3);
        const far = influenceAt([0, 46], [near(2, 46, 1)], 50);
        expect(influenceAt([0, 46], [near(2, 46, 1, 200)], 50)).toBeGreaterThan(
            far,
        );
    });

    it("pairs each neighbour with the edge that faces it", () => {
        const cells = hexGrid(BOUNDS, 40);
        const byKey = new Map(
            cells.map((cell) => [`${cell.col}:${cell.row}`, cell]),
        );
        const cell = cells.find((c) => c.row === 3 && c.col === 3);
        if (!cell) throw new Error("no cell");
        for (let k = 0; k < 6; k += 1) {
            const [col, row] = neighbour(cell.col, cell.row, k);
            const other = byKey.get(`${col}:${row}`);
            if (!other) continue;
            const shared = other.ring
                .slice(0, 6)
                .filter((p) =>
                    [cell.ring[k], cell.ring[k + 1]].some(
                        (q) =>
                            Math.abs(q[0] - p[0]) < 1e-6 &&
                            Math.abs(q[1] - p[1]) < 1e-6,
                    ),
                );
            expect(shared).toHaveLength(2);
        }
    });

    it("draws each followed material's area and outline, cells under the floor empty", () => {
        const result = territories(
            [
                { slot: 1, attestations: [near(2, 46)] },
                { slot: 3, attestations: [near(3, 47)] },
            ],
            150,
            BOUNDS,
            "each",
        );
        const cells = result.features.filter(
            (f) => f.properties.layer === "cell",
        );
        expect(new Set(cells.map((f) => f.properties.slot))).toEqual(
            new Set([1, 3]),
        );
        expect(
            cells.every(
                (f) => f.properties.alpha <= 0.32 && f.properties.alpha >= 0.06,
            ),
        ).toBe(true);
        expect(
            result.features.some(
                (f) => f.properties.layer === "edge" && f.properties.slot === 1,
            ),
        ).toBe(true);
    });

    it("carries the outline of a material as one MultiLineString of segments", () => {
        const result = territories(
            [
                { slot: 1, attestations: [near(2, 46)] },
                { slot: 3, attestations: [near(3, 47)] },
            ],
            150,
            BOUNDS,
            "each",
        );
        const edges = result.features.filter(
            (f) => f.properties.layer === "edge",
        );
        expect(edges.map((f) => f.properties.slot).sort()).toEqual([1, 3]);
        for (const edge of edges) {
            expect(edge.geometry.type).toBe("MultiLineString");
            const lines = (edge.geometry as MultiLineString).coordinates;
            expect(lines.length).toBeGreaterThan(6);
            expect(lines.every((l) => l.length === 2)).toBe(true);
        }
    });

    it("dominant gives the share as opacity, hatches near ties and draws borders only where the dominant changes", () => {
        const result = territories(
            [
                { slot: 1, attestations: [near(1, 46)] },
                { slot: 2, attestations: [near(3, 46)] },
            ],
            150,
            BOUNDS,
            "dominant",
        );
        const cells = result.features.filter(
            (f) => f.properties.layer === "cell",
        );
        expect(cells.some((f) => f.properties.hatched)).toBe(true);
        expect(
            cells.every((f) => f.properties.alpha >= 0.15 + 0.6 * 0.5 - 1e-9),
        ).toBe(true);
        expect(
            result.features
                .filter((f) => f.properties.layer === "edge")
                .every((f) => f.properties.slot === 0),
        ).toBe(true);
    });

    it("calls a tie on the runner-up alone, whatever the other fields weigh", () => {
        expect(nearlyTied([8, 3, 3, 3], 0)).toBe(false);
        expect(nearlyTied([5, 4.5, 0.1], 0)).toBe(true);
        expect(nearlyTied([2, 0], 0)).toBe(false);
        const cells = territories(
            [
                { slot: 1, attestations: [near(2, 46, 8)] },
                { slot: 2, attestations: [near(2, 46, 3)] },
                { slot: 3, attestations: [near(2, 46, 3)] },
                { slot: 4, attestations: [near(2, 46, 3)] },
            ],
            150,
            BOUNDS,
            "dominant",
        ).features.filter((f) => f.properties.layer === "cell");
        expect(cells.length).toBeGreaterThan(0);
        expect(cells.some((f) => f.properties.hatched)).toBe(false);
    });

    it("dominant draws a frontier between two dominants", () => {
        const edges = territories(
            [
                { slot: 1, attestations: [near(0.5, 46)] },
                { slot: 2, attestations: [near(3.5, 46)] },
            ],
            150,
            BOUNDS,
            "dominant",
        ).features.filter((f) => f.properties.layer === "edge");
        expect(edges.length).toBeGreaterThan(0);
        expect(edges.every((f) => f.properties.slot === 0)).toBe(true);
    });

    it("a tracked material without attestations draws no cell, and none tracked draws nothing", () => {
        expect(
            territories([{ slot: 2, attestations: [] }], 150, BOUNDS, "each")
                .features,
        ).toEqual([]);
        expect(territories([], 150, BOUNDS, "each").features).toEqual([]);
        expect(dominantOf([FLOOR - 0.1, 0.2])).toBe(-1);
    });

    it("pads the view by a tenth of its span, inside Web Mercator and one world wide at most", () => {
        expect(gridBounds({ west: 0, south: 40, east: 10, north: 50 })).toEqual(
            { west: -1, south: 39, east: 11, north: 51 },
        );
        const world = gridBounds({
            west: -400,
            south: -85,
            east: 400,
            north: 85,
        });
        expect(world.east - world.west).toBe(360);
        expect(world.south).toBeCloseTo(-85.0511, 4);
        expect(world.north).toBeCloseTo(85.0511, 4);
    });

    it("sizes the cells of a European view from the radius, not from where the data lie", () => {
        const europe = gridBounds({
            west: -10,
            south: 36,
            east: 25,
            north: 60,
        });
        expect(cellSizeKm(400, europe)).toBeCloseTo(400 * CELL_RATIO);
        const size = cellSizeKm(60, europe);
        expect(size).toBeGreaterThanOrEqual(
            Math.max(CELL_MIN_KM, 60 * CELL_RATIO),
        );
        expect(size).toBeLessThan(60);
        const drawn = territories(
            [
                {
                    slot: 1,
                    attestations: [
                        near(2.35, 48.85),
                        near(116.4, 39.9),
                        near(174.76, -36.85),
                        near(-99.13, 19.43),
                    ],
                },
            ],
            60,
            europe,
            "each",
        ).features.filter((f) => f.properties.layer === "cell");
        expect(drawn.length).toBeGreaterThan(0);
        for (const cell of drawn) {
            const [lng, lat] = (
                cell.geometry.coordinates as number[][][]
            )[0][0];
            expect(lng).toBeGreaterThan(europe.west - 2);
            expect(lng).toBeLessThan(europe.east + 2);
            expect(lat).toBeGreaterThan(europe.south - 2);
            expect(lat).toBeLessThan(europe.north + 2);
        }
    });

    it("keeps the cells a pan still shows in place", () => {
        const centres = (west: number) =>
            new Set(
                hexGrid({ west, south: 44, east: west + 6, north: 49 }, 40).map(
                    (cell) =>
                        `${cell.centre[0].toFixed(6)},${cell.centre[1].toFixed(6)}`,
                ),
            );
        const before = centres(0);
        const after = centres(1.3);
        const shared = [...after].filter((key) => before.has(key));
        expect(shared.length).toBeGreaterThan(after.size / 2);
    });

    it("draws nothing when even the cap leaves cells coarser than the radius", () => {
        const world = gridBounds({
            west: -180,
            south: -80,
            east: 180,
            north: 80,
        });
        expect(tooCoarse(60, world)).toBe(true);
        expect(
            territories(
                [{ slot: 1, attestations: [near(2.35, 48.85, 40)] }],
                60,
                world,
                "dominant",
            ).features,
        ).toEqual([]);
        const europe = gridBounds({
            west: -10,
            south: 36,
            east: 25,
            north: 60,
        });
        expect(tooCoarse(60, europe)).toBe(false);
    });

    it("counts a place outside the view on the cells near its edge, and leaves out a far one", () => {
        const view = { west: 0, south: 44, east: 4, north: 48 };
        const outside = near(-1.5, 46, 6);
        expect(reaches(outside, view, 150)).toBe(true);
        expect(reaches(near(20, 46), view, 150)).toBe(false);
        const cells = territories(
            [{ slot: 1, attestations: [outside] }],
            150,
            view,
            "each",
        ).features.filter((f) => f.properties.layer === "cell");
        expect(cells.length).toBeGreaterThan(0);
    });

    it("reaches a place across the antimeridian from a view past 180°", () => {
        const view = { west: 165, south: -25, east: 195, north: -10 };
        const fiji = near(-178.4, -18.1, 6);
        expect(reaches(fiji, view, 150)).toBe(true);
        const cells = territories(
            [{ slot: 1, attestations: [fiji] }],
            150,
            view,
            "each",
        ).features.filter((f) => f.properties.layer === "cell");
        expect(cells.length).toBeGreaterThan(0);
    });

    it("draws a zone around a place attested once, out to about 0.83 radius", () => {
        for (const colour of ["each", "dominant"] as const) {
            const drawn = centres(
                territories(
                    [{ slot: 1, attestations: [near(...PARIS, 1)] }],
                    150,
                    AROUND_PARIS,
                    colour,
                ).features,
            );
            const reach = 150 * Math.sqrt(Math.log(1 / FLOOR));
            const cell = cellSizeKm(150, AROUND_PARIS);
            expect(drawn.length).toBeGreaterThan(20);
            const distances = drawn.map((c) => haversineKm(c, PARIS));
            expect(Math.max(...distances)).toBeLessThan(reach + cell);
            expect(Math.max(...distances)).toBeGreaterThan(reach - 2 * cell);
        }
    });

    it("colours the own cell of a place under the threshold, a lower-reliability one or any one above it", () => {
        for (const [weight, threshold] of [
            [LOW_WEIGHT, FLOOR],
            [1, THRESHOLD_MAX],
        ]) {
            for (const colour of ["each", "dominant"] as const) {
                const drawn = centres(
                    territories(
                        [
                            {
                                slot: 2,
                                attestations: [near(...PARIS, weight)],
                            },
                        ],
                        150,
                        AROUND_PARIS,
                        colour,
                        threshold,
                    ).features,
                );
                expect(drawn).toHaveLength(1);
                expect(haversineKm(drawn[0], PARIS)).toBeLessThan(
                    cellSizeKm(150, AROUND_PARIS) * 1.5,
                );
            }
        }
    });

    it("draws fewer cells under a higher threshold", () => {
        const cells = (threshold: number) =>
            centres(
                territories(
                    [{ slot: 1, attestations: [near(...PARIS, 4)] }],
                    150,
                    AROUND_PARIS,
                    "each",
                    threshold,
                ).features,
            ).length;
        expect(cells(2)).toBeLessThan(cells(FLOOR));
        expect(cells(2)).toBeGreaterThan(0);
    });

    it("bounds a dense place's zone at r·√(ln(w / threshold))", () => {
        const weight = 20;
        const drawn = centres(
            territories(
                [{ slot: 1, attestations: [near(...PARIS, weight)] }],
                60,
                AROUND_PARIS,
                "dominant",
            ).features,
        );
        const reach = 60 * Math.sqrt(Math.log(weight / FLOOR));
        const cell = cellSizeKm(60, AROUND_PARIS);
        const distances = drawn.map((c) => haversineKm(c, PARIS));
        expect(Math.max(...distances)).toBeLessThan(reach + cell);
        expect(Math.max(...distances)).toBeGreaterThan(reach - 2 * cell);
    });

    it("hatches the cells of a place attesting two followed materials once each", () => {
        const cells = territories(
            [
                { slot: 2, attestations: [near(...PARIS, 1)] },
                { slot: 3, attestations: [near(...PARIS, 1)] },
            ],
            150,
            AROUND_PARIS,
            "dominant",
        ).features.filter((f) => f.properties.layer === "cell");
        expect(cells.length).toBeGreaterThan(20);
        expect(cells.every((f) => f.properties.hatched)).toBe(true);
    });

    it("leads a cell under the threshold by the most attested field with a place in it", () => {
        expect(dominantOf([0.4, 0.3], FLOOR, [false, true])).toBe(1);
        expect(dominantOf([0.4, 0.3], FLOOR, [false, false])).toBe(-1);
        expect(dominantOf([0.6, 0.3], FLOOR, [false, true])).toBe(0);
    });
});
