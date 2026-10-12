import { describe, expect, it } from "vitest";

import {
    boundsOf,
    fitAspect,
    fromMercator,
    haversineKm,
    padBounds,
    project,
    toMercator,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";

describe("geography helpers", () => {
    it("measures Paris to London", () => {
        const km = haversineKm([2.3522, 48.8566], [-0.1276, 51.5072]);
        expect(km).toBeGreaterThan(342);
        expect(km).toBeLessThan(345);
    });

    it("round-trips Web Mercator", () => {
        const [lng, lat] = fromMercator(toMercator([2, 48]));
        expect(lng).toBeCloseTo(2, 6);
        expect(lat).toBeCloseTo(48, 6);
    });

    it("has no bounds for no points", () => {
        expect(boundsOf([])).toBeNull();
        expect(
            boundsOf([
                [1, 2],
                [3, -1],
            ]),
        ).toEqual({ west: 1, south: -1, east: 3, north: 2 });
    });

    it("pads 111.32 km per degree of latitude", () => {
        const padded = padBounds(
            { west: 0, south: 10, east: 1, north: 11 },
            111.32,
        );
        expect(padded.south).toBeCloseTo(9, 6);
        expect(padded.north).toBeCloseTo(12, 6);
        expect(padded.west).toBeLessThan(-1);
    });

    it("projects the south-west corner at the bottom-left of a centred box", () => {
        const bounds = { west: 0, south: 45, east: 4, north: 48 };
        const [x, y] = project([0, 45], bounds, 400, 800);
        const [x1, y1] = project([4, 48], bounds, 400, 800);
        expect(x).toBeCloseTo(0, 6);
        expect(y1).toBeGreaterThan(0);
        expect(y).toBeCloseTo(800 - y1, 6);
        expect(x1).toBeCloseTo(400, 6);
        expect(y).toBeGreaterThan(y1);
    });

    it("widens bounds to a box's aspect, so the box shows them exactly", () => {
        const bounds = { west: -2, south: 43, east: 6, north: 51 };
        const wide = fitAspect(bounds, 220, 160);
        const [x0, y0] = toMercator([wide.west, wide.south]);
        const [x1, y1] = toMercator([wide.east, wide.north]);
        expect((x1 - x0) / (y1 - y0)).toBeCloseTo(220 / 160, 6);
        expect(wide.south).toBeCloseTo(bounds.south, 6);
        expect(wide.north).toBeCloseTo(bounds.north, 6);
        expect(wide.west).toBeLessThan(bounds.west);
        for (const point of [
            [0, 45],
            [5, 50],
        ] as const) {
            const [x, y] = project(point, bounds, 220, 160);
            const [xw, yw] = project(point, wide, 220, 160);
            expect(xw).toBeCloseTo(x, 6);
            expect(yw).toBeCloseTo(y, 6);
        }
        const [left, top] = project([wide.west, wide.north], wide, 220, 160);
        expect(left).toBeCloseTo(0, 6);
        expect(top).toBeCloseTo(0, 6);
    });
});
