import { describe, expect, it } from "vitest";

import type { Shape } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

import {
    annotation,
    documentPayload,
    label,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import {
    componentOutlines,
    liveUnit,
    markedZones,
    shapeBounds,
    shapeCentre,
    shapeCorner,
    shapeFeature,
    toLatLng,
    zoneUnitFor,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

describe("folio geometry", () => {
    it("places a canvas pixel in the Arches annotation space", () => {
        expect(toLatLng(64, 32)).toEqual([-1, 2]);
    });

    it.each([
        [2, 611, 947, [-473.5, 305.5]],
        [16, 1680, 925, [-57.8125, 105]],
        [32, 3360, 1850, [-57.8125, 105]],
        [64, 6720, 3700, [-57.8125, 105]],
    ])(
        "divides a canvas pixel by the canvas's unit of %i",
        (scale, x, y, expected) => {
            expect(toLatLng(x, y, { x: scale, y: scale, read: true })).toEqual(
                expected,
            );
        },
    );

    it("divides each axis by its own unit when the canvas is not at the image's size", () => {
        expect(toLatLng(500, 300, { x: 8, y: 7.5, read: true })).toEqual([
            -40, 62.5,
        ]);
    });

    it("reads a zone with its canvas's unit, read or assumed", () => {
        const rect = { type: "rect", x: 160, y: 320, w: 160, h: 160 } as const;
        const unit = { x: 16, y: 16, read: false };
        expect(shapeCentre(rect, unit)).toEqual([-25, 15]);
        expect(shapeBounds(rect, unit)).toEqual([
            [-30, 10],
            [-20, 20],
        ]);
        expect(shapeCorner(rect, unit)).toEqual([-20, 10]);
        expect(
            shapeFeature({ type: "point", x: 160, y: 320 }, {}, unit)?.geometry,
        ).toEqual({ type: "Point", coordinates: [10, -20] });
    });

    it("centres a rectangle and bounds it", () => {
        const rect = { type: "rect", x: 0, y: 0, w: 64, h: 32 } as const;
        expect(shapeCentre(rect)).toEqual([-0.5, 1]);
        expect(shapeBounds(rect)).toEqual([
            [-1, 0],
            [0, 2],
        ]);
    });

    it("turns a polygon into a closed GeoJSON ring in [lng, lat]", () => {
        const feature = shapeFeature(
            {
                type: "polygon",
                points: [
                    [0, 0],
                    [32, 0],
                    [32, 32],
                ],
            },
            { id: "a" },
        );
        expect(feature?.geometry).toEqual({
            type: "Polygon",
            coordinates: [
                [
                    [0, 0],
                    [1, 0],
                    [1, -1],
                    [0, 0],
                ],
            ],
        });
        expect(feature?.properties).toEqual({ id: "a" });
    });

    it("returns null for an empty polygon", () => {
        const empty: Shape = { type: "polygon", points: [] };
        expect(shapeCentre(empty)).toBeNull();
        expect(shapeBounds(empty)).toBeNull();
        expect(shapeFeature(empty, {})).toBeNull();
    });

    it("puts a label corner at the north-west of an extent, none on a point", () => {
        expect(shapeCorner({ type: "rect", x: 0, y: 0, w: 64, h: 32 })).toEqual(
            [0, 0],
        );
        expect(
            shapeCorner({
                type: "polygon",
                points: [
                    [32, 64],
                    [96, 64],
                    [64, 128],
                ],
            }),
        ).toEqual([-2, 1]);
        expect(shapeCorner({ type: "point", x: 5, y: 5 })).toBeNull();
    });

    it("outlines the components with an extent on one folio, in the payload's order", () => {
        const rect = { type: "rect", x: 0, y: 0, w: 64, h: 32 } as const;
        const point = { type: "point", x: 5, y: 5 } as const;
        const payload = documentPayload({
            components: [
                {
                    id: uuid(901),
                    name: label("Initial"),
                    unpublished: false,
                    zones: [
                        { canvas: 1, unit: null, shape: rect, feature: "k1" },
                        { canvas: 0, unit: null, shape: rect, feature: "k2" },
                    ],
                },
                {
                    id: uuid(902),
                    name: label("Point only"),
                    unpublished: false,
                    zones: [
                        { canvas: 0, unit: null, shape: point, feature: "k3" },
                    ],
                },
                {
                    id: uuid(903),
                    name: label("Border"),
                    unpublished: false,
                    zones: [
                        { canvas: 0, unit: null, shape: rect, feature: "k4" },
                    ],
                },
            ],
        });
        const [first, second] = payload.canvases;
        expect(componentOutlines(payload, first.id)).toEqual([
            {
                id: uuid(901),
                name: label("Initial"),
                shapes: [rect],
                units: [null],
            },
            {
                id: uuid(903),
                name: label("Border"),
                shapes: [rect],
                units: [null],
            },
        ]);
        expect(
            componentOutlines(payload, second.id).map((outline) => outline.id),
        ).toEqual([uuid(901)]);
        expect(
            componentOutlines(payload, "https://iiif.example/other"),
        ).toEqual([]);
    });

    it("has no bounds for a point", () => {
        expect(shapeBounds({ type: "point", x: 1, y: 1 })).toBeNull();
    });

    it("marks each analysis once, on its first zone with an extent, else on its first point", () => {
        const point = annotation(1, { key: "k1" });
        const firstZone = annotation(1, {
            key: "k2",
            shape: { type: "rect", x: 0, y: 0, w: 10, h: 10 },
        });
        const secondZone = annotation(1, {
            key: "k3",
            shape: { type: "rect", x: 50, y: 50, w: 10, h: 10 },
        });
        const pointOnly = annotation(2);
        expect(
            markedZones([point, firstZone, secondZone, pointOnly]).map(
                (entry) => [entry.analysis, entry.key],
            ),
        ).toEqual([
            [uuid(101), "k2"],
            [uuid(102), pointOnly.key],
        ]);
    });
});

describe("liveUnit and zoneUnitFor", () => {
    it("derives the unit of the zones from the frame of the live layer", () => {
        expect(
            liveUnit(
                { zoom: 4, width: 4913, height: 6609 },
                { width: 4913, height: 6609 },
            ),
        ).toEqual({ x: 16, y: 16, read: true });
        expect(
            liveUnit(
                { zoom: 3, width: 2000, height: 1000 },
                { width: 4000, height: 3000 },
            ),
        ).toEqual({ x: 16, y: 24, read: true });
    });

    it("keeps the zone's own unit, else the live one, else the canvas's", () => {
        const own = { x: 2, y: 2, read: false };
        const live = { x: 16, y: 16, read: true };
        const fallback = { x: 32, y: 32, read: false };
        expect(zoneUnitFor({ unit: own }, live, fallback)).toBe(own);
        expect(zoneUnitFor({ unit: null }, live, fallback)).toBe(live);
        expect(zoneUnitFor({}, null, fallback)).toBe(fallback);
        expect(zoneUnitFor({ unit: null }, null, null)).toBeNull();
    });
});
