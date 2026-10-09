import { describe, expect, it } from "vitest";

import {
    filterCss,
    isNeutral,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-filters.ts";
import { NEUTRAL_FILTERS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

describe("filterCss", () => {
    it("writes the filter of iiif-viewer.js, 100 being neutral", () => {
        expect(
            filterCss({
                brightness: 150,
                contrast: 80,
                saturation: 0,
                greyscale: true,
            }),
        ).toBe("brightness(1.5) contrast(0.8) saturate(0) grayscale(1)");
    });

    it("writes no filter at all for neutral values", () => {
        expect(filterCss(NEUTRAL_FILTERS)).toBe("");
        expect(isNeutral(NEUTRAL_FILTERS)).toBe(true);
        expect(isNeutral({ ...NEUTRAL_FILTERS, greyscale: true })).toBe(false);
    });
});
