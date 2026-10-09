import { describe, expect, it } from "vitest";

import {
    FLOOR,
    dominantOf,
    hexGrid,
    influenceAt,
    neighbour,
    territories,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/territories.ts";

const BOUNDS = { west: 0, south: 45, east: 4, north: 48 };
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

    it("a tracked material without attestations draws no cell, and none tracked draws nothing", () => {
        expect(
            territories([{ slot: 2, attestations: [] }], 150, BOUNDS, "each")
                .features,
        ).toEqual([]);
        expect(territories([], 150, BOUNDS, "each").features).toEqual([]);
        expect(dominantOf([FLOOR - 0.1, 0.2])).toBe(-1);
    });
});
