import { describe, expect, it } from "vitest";

import type { Shape } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

import {
    shapeBounds,
    shapeCentre,
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

    it("has no bounds for a point", () => {
        expect(shapeBounds({ type: "point", x: 1, y: 1 })).toBeNull();
    });
});
