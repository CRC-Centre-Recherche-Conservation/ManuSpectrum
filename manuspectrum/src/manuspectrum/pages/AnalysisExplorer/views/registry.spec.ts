import { describe, expect, it } from "vitest";

import {
    availableViews,
    isViewAvailable,
} from "@/manuspectrum/pages/AnalysisExplorer/views/registry.ts";

describe("views registry", () => {
    it("offers Corpus, the Map and Compare", () => {
        expect(availableViews()).toEqual(["corpus", "map", "compare"]);
        expect(isViewAvailable("compare")).toBe(true);
        expect(isViewAvailable("map")).toBe(true);
    });
});
