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
    markedZones,
    shapeBounds,
    shapeCentre,
    shapeCorner,
    shapeFeature,
    toLatLng,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/geometry.ts";

describe("folio geometry", () => {
    it("places a canvas pixel in the Arches annotation space", () => {
        expect(toLatLng(64, 32)).toEqual([-1, 2]);
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
                    zones: [
                        { canvas: 1, shape: rect, feature: "k1" },
                        { canvas: 0, shape: rect, feature: "k2" },
                    ],
                },
                {
                    id: uuid(902),
                    name: label("Point only"),
                    zones: [{ canvas: 0, shape: point, feature: "k3" }],
                },
                {
                    id: uuid(903),
                    name: label("Border"),
                    zones: [{ canvas: 0, shape: rect, feature: "k4" }],
                },
            ],
        });
        const [first, second] = payload.canvases;
        expect(componentOutlines(payload, first.id)).toEqual([
            { id: uuid(901), name: label("Initial"), shapes: [rect] },
            { id: uuid(903), name: label("Border"), shapes: [rect] },
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
