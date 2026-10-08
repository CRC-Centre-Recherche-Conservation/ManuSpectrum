import { describe, expect, it } from "vitest";

import {
    ELEMENT_HUES,
    elementColour,
    elementHue,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/element-colour.ts";

const COMMON = ["Pb", "Fe", "Ca", "Cu", "Hg", "Zn", "K", "S", "Ag", "Au"];

describe("elementHue", () => {
    it("gives the ten common elements ten different hues", () => {
        expect(new Set(COMMON.map(elementHue)).size).toBe(ELEMENT_HUES);
    });

    it("depends on the element alone, never on the others drawn", () => {
        expect(elementHue("Hg")).toBe(elementHue("Hg"));
        expect(elementHue("Cl")).toBe(17 % ELEMENT_HUES);
        expect(elementHue("Sn")).toBe(50 % ELEMENT_HUES);
    });

    it("stays inside the palette for any symbol, known or not", () => {
        for (const symbol of ["U", "Na", "Xx", ""]) {
            expect(elementHue(symbol)).toBeGreaterThanOrEqual(0);
            expect(elementHue(symbol)).toBeLessThan(ELEMENT_HUES);
        }
    });
});

describe("elementColour", () => {
    it("reads the theme's palette, ink when it has none", () => {
        const element = Array.from(
            { length: ELEMENT_HUES },
            (_, i) => `#e${i}`,
        );
        expect(elementColour({ element, ink: "#000" }, "Fe")).toBe("#e1");
        expect(elementColour({ element: [], ink: "#000" }, "Fe")).toBe("#000");
    });
});
