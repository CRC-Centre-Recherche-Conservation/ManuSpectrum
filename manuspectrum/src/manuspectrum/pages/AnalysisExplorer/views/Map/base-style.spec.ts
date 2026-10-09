import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";

import {
    BASE_ATTRIBUTION,
    BASE_SOURCE,
    WATER_LAYER,
    baseStyle,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/base-style.ts";
import { FALLBACK_COLOURS } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-colours.ts";

const STYLE = baseStyle(FALLBACK_COLOURS);

describe("baseStyle", () => {
    it("is a valid MapLibre style", () => {
        expect(validateStyleMin(STYLE)).toEqual([]);
    });

    it("draws no boundary, road or label", () => {
        const read = STYLE.layers.map((layer) =>
            "source-layer" in layer ? layer["source-layer"] : null,
        );
        expect(read).not.toContain("boundary");
        expect(read).not.toContain("transportation");
        expect(read).not.toContain("transportation_name");
        expect(STYLE.layers.some((layer) => layer.type === "symbol")).toBe(
            false,
        );
    });

    it("names the sea layer WATER_LAYER and paints land and sea from the colours", () => {
        const water = STYLE.layers.find((layer) => layer.id === WATER_LAYER);
        expect(water?.type).toBe("fill");
        expect(water?.paint).toMatchObject({
            "fill-color": FALLBACK_COLOURS.sea,
        });
        expect(STYLE.layers[0]).toMatchObject({
            type: "background",
            paint: { "background-color": FALLBACK_COLOURS.land },
        });
    });

    it("draws rivers from zoom 5 only", () => {
        expect(
            STYLE.layers.find((layer) => layer.id === "rivers"),
        ).toMatchObject({ minzoom: 5, "source-layer": "waterway" });
    });

    it("carries the exact attribution text", () => {
        expect(BASE_ATTRIBUTION).toBe(
            "OpenFreeMap © OpenMapTiles Data from OpenStreetMap",
        );
        expect(STYLE.sources[BASE_SOURCE]).toMatchObject({
            attribution: BASE_ATTRIBUTION,
        });
    });
});
