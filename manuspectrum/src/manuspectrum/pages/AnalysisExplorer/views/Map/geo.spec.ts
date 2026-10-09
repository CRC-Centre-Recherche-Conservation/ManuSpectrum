import { describe, expect, it } from "vitest";

import {
    boundsOf,
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
});
