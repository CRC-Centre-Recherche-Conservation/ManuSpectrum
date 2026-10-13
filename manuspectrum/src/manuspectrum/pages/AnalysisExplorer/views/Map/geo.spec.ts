import { describe, expect, it } from "vitest";

import {
    FIT_LABEL_ROOM_PX,
    boundsOf,
    fitAspect,
    fitBoundsOf,
    fitPadding,
    fromMercator,
    haversineKm,
    padBounds,
    project,
    toMercator,
    wrapInto,
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

    it("leaves room for the names of the places on the edges of a fit, less on a small screen", () => {
        expect(fitPadding(1200, 700)).toEqual({
            top: FIT_LABEL_ROOM_PX.y,
            right: FIT_LABEL_ROOM_PX.x,
            bottom: FIT_LABEL_ROOM_PX.y,
            left: FIT_LABEL_ROOM_PX.x,
        });
        expect(FIT_LABEL_ROOM_PX).toEqual({ x: 120, y: 48 });
        expect(fitPadding(360, 200)).toEqual({
            top: 40,
            right: 72,
            bottom: 40,
            left: 72,
        });
        expect(fitPadding(0, 0)).toEqual({
            top: 0,
            right: 0,
            bottom: 0,
            left: 0,
        });
    });

    it("fits places around the Pacific across the antimeridian", () => {
        const fit = fitBoundsOf([
            [166.45, -22.27],
            [174.76, -36.85],
            [-178.4, -18.1],
        ]);
        expect(fit?.west).toBe(166.45);
        expect(fit?.east).toBeCloseTo(181.6, 9);
        expect([fit?.south, fit?.north]).toEqual([-36.85, -18.1]);
    });

    it("projects a place past the antimeridian inside bounds that cross it", () => {
        const fit = { west: 166.45, south: -36.85, east: 181.6, north: -18.1 };
        const [lng, lat] = wrapInto([-178.4, -18.1], fit);
        expect(lng).toBeCloseTo(181.6, 9);
        expect(lat).toBe(-18.1);
        expect(wrapInto([174.76, -36.85], fit)).toEqual([174.76, -36.85]);
        const [x] = project(wrapInto([-178.4, -18.1], fit), fit, 100, 100);
        expect(x).toBeGreaterThan(50);
        expect(x).toBeLessThanOrEqual(100);
        const plain = { west: -10, south: 40, east: 10, north: 50 };
        expect(wrapInto([170, 45], plain)).toEqual([170, 45]);
    });

    it("keeps a worldwide spread in plain bounds, Europe in the middle", () => {
        const world: [number, number][] = [
            [-99.13, 19.43],
            [2.35, 48.85],
            [116.4, 39.9],
            [166.45, -22.27],
            [174.76, -36.85],
        ];
        expect(fitBoundsOf(world)).toEqual(boundsOf(world));
        expect(fitBoundsOf([])).toBeNull();
        expect(fitBoundsOf([[2, 48]])).toEqual(boundsOf([[2, 48]]));
    });
});
