import { describe, expect, it } from "vitest";

import {
    availableViews,
    isViewAvailable,
} from "@/manuspectrum/pages/AnalysisExplorer/views/registry.ts";

describe("views registry", () => {
    it("offers Corpus and Compare, not the Map yet", () => {
        expect(availableViews()).toEqual(["corpus", "compare"]);
        expect(isViewAvailable("compare")).toBe(true);
        expect(isViewAvailable("map")).toBe(false);
    });
});
