import { describe, expect, it } from "vitest";

import {
    HEAT_STEPS,
    heatLevel,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/heat.ts";

describe("heatLevel", () => {
    it("spreads the counts over four steps, the largest on the last", () => {
        expect(HEAT_STEPS).toBe(4);
        expect([1, 2, 3, 4, 5, 6].map((count) => heatLevel(count, 6))).toEqual([
            1, 2, 2, 3, 4, 4,
        ]);
    });

    it("puts every count on the last step when they are all equal", () => {
        expect(heatLevel(3, 3)).toBe(4);
        expect(heatLevel(1, 1)).toBe(4);
    });

    it("gives no step to an empty count", () => {
        expect(heatLevel(0, 5)).toBe(0);
        expect(heatLevel(0, 0)).toBe(0);
    });
});
